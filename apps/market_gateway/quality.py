"""Data-quality validation for real market-data payloads (S8 contract
remediation R1).

Two contracts live here, explicitly separated:

- **`validate_raw_daily_bars`** — the ONLY production contract (ranged
  ``GET /v2/stocks/{symbol}/bars?timeframe=1Day``, official schema
  ``stock_bars_resp_single``: ``{"bars": [...], "next_page_token": ...,
  "symbol": ...}``; official-api-contract.md §2, retrieved 2026-11-22).
  Every raw payload is validated BEFORE it can become a daemon event; a
  rejected payload never reaches the forward engine (it is receipted
  with its denominator-honest reason). Fail-closed throughout.
- **`validate_raw_bar`** — LEGACY, pinned historical-defect evidence
  (``LEGACY_INVALID_VENDOR_CONTRACT``): the pre-remediation gate for the
  fabricated latest-bar shape (a ``bars`` ARRAY no real ``/bars/latest``
  endpoint returns, and minute-bar semantics consumed as daily). Kept
  ONLY so the pinned legacy-mode tests and RED evidence keep running;
  production never calls it under a ranged-contract preregistration.

Reject vocabulary (each reject carries a machine reason):

- ``SCHEMA``              — response shape is not the documented
                            ranged-bars object; required fields missing
                            or wrongly typed; more than one bar in a
                            1Day window for one symbol;
- ``NON_FINITE_PRICE``    — non-finite/zero/negative OHLC (exact
                            ``Decimal`` only; NaN/Infinity JSON literals
                            are refused at the transport);
- ``CROSSED_BAR``         — high < low, or close/open outside [low, high];
- ``NEGATIVE_VOLUME``     — volume < 0;
- ``SYMBOL_MISMATCH``     — a symbol echo disagrees with the requested
                            symbol;
- ``UNEXPECTED_BAR_DATE`` — bar timestamp maps to a LATER session than
                            the one being collected (a future/different
                            session can never be consumed as today's
                            bar);
- ``STALE_BAR``           — bar timestamp maps to an EARLIER session
                            (previous-session data is a gap, disclosed
                            in denominators, never silently consumed);
- ``NOT_A_DAILY_BAR``     — defense-in-depth (ranged contract only): a
                            bar stamped INSIDE the session trading hours
                            carries an intraday (minute-bar) stamp. The
                            vendor does NOT document the daily-stamp
                            convention (official-api-contract.md §2), so
                            this check is example-evidenced and
                            deliberately strict: the daily/minute
                            distinction belongs to the REQUEST contract
                            (timeframe=1Day + bounded window), and a
                            suspicious stamp is never relabeled into a
                            daily bar — collection fails closed;
- ``MISSING_BAR``         — the ranged window returned zero bars: a
                            legal "no data this session" answer,
                            receipted as a gap — zero events, zero day
                            credit.

Timestamp normalization is preregistered: a daily bar's ``t`` maps to its
ET session date; the event ``ts_event`` is that session's DST-correct
close instant (13:00 ET on preregistered half days, 16:00 otherwise).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from trading_lab.data.calendar import ET, MarketCalendar

__all__ = [
    "BarRecord",
    "QualityReject",
    "validate_raw_bar",           # LEGACY (pinned defect evidence)
    "validate_raw_daily_bars",    # production ranged contract
]


@dataclass(frozen=True)
class BarRecord:
    """A validated raw bar, normalized (all money values exact Decimal)."""

    symbol: str
    session_date: dt.date
    bar_ts: dt.datetime          # vendor timestamp (tz-aware UTC)
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    raw_payload_digest: str      # digest over the FULL raw response body


@dataclass(frozen=True)
class QualityReject:
    symbol: str
    reason: str
    detail: str


def _require(condition: bool, reason: str, detail: str) -> None:
    if not condition:
        raise _Reject(reason, detail)


class _Reject(Exception):
    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


def _as_decimal(value: Any, field: str) -> Decimal:
    # parse_float=Decimal already yields Decimal for JSON numbers; ints
    # (e.g. volume) arrive as int. Floats must never exist at this layer.
    if isinstance(value, bool) or not isinstance(value, (Decimal, int)):
        raise _Reject(
            "SCHEMA",
            f"{field} must be an exact JSON number (Decimal/int), got "
            f"{type(value).__name__}")
    d = Decimal(value) if isinstance(value, int) else value
    if not d.is_finite():
        raise _Reject("NON_FINITE_PRICE", f"{field} is not finite: {d}")
    return d


def validate_raw_bar(
    *,
    symbol: str,
    session_date: dt.date,
    payload: dict[str, Any],
    calendar: MarketCalendar,
    raw_payload_digest: str,
) -> BarRecord:
    """LEGACY (``LEGACY_INVALID_VENDOR_CONTRACT``): the pre-remediation
    gate for the fabricated bars-latest shape. Pinned for the legacy-mode
    tests and RED evidence; production never calls it under a ranged
    contract. Behavior is frozen — do not "fix" it in place."""
    try:
        return _validate_legacy(symbol, session_date, payload, calendar,
                                raw_payload_digest)
    except _Reject as exc:
        return QualityReject(symbol=symbol, reason=exc.reason,
                             detail=exc.detail)


def validate_raw_daily_bars(
    *,
    symbol: str,
    session_date: dt.date,
    merged_bars: list[Any],
    symbol_echo: Any,
    calendar: MarketCalendar,
    raw_payload_digest: str,
) -> BarRecord:
    """Validate the MERGED ``bars`` of one ranged 1Day window for
    ``symbol`` against the session being collected (production contract).

    ``merged_bars`` is the concatenated bars array across all pages; the
    feed handles pagination and passes the merged list plus the (first
    page's documented) ``symbol`` echo. Returns a :class:`BarRecord` or a
    :class:`QualityReject` — never throws except on programming errors.
    """
    try:
        return _validate_ranged(symbol, session_date, merged_bars,
                                symbol_echo, calendar, raw_payload_digest)
    except _Reject as exc:
        return QualityReject(symbol=symbol, reason=exc.reason,
                             detail=exc.detail)


def _validate_ranged(
    symbol: str,
    session_date: dt.date,
    merged_bars: list[Any],
    symbol_echo: Any,
    calendar: MarketCalendar,
    raw_payload_digest: str,
) -> BarRecord:
    # the ranged contract REQUIRES the symbol echo (official schema:
    # stock_bars_resp_single requires bars, next_page_token, symbol)
    _require(symbol_echo is not None, "SCHEMA",
             "response.symbol (documented required echo) missing")
    _require(symbol_echo == symbol, "SYMBOL_MISMATCH",
             f"response symbol echo {symbol_echo!r} != requested "
             f"{symbol!r}")
    _require(isinstance(merged_bars, list), "SCHEMA",
             "merged bars must be a list")
    if len(merged_bars) == 0:
        # a legal "no data this session" answer: a receipted gap, never
        # an event, never day credit
        raise _Reject("MISSING_BAR",
                      f"{symbol} returned no bar for "
                      f"{session_date.isoformat()} in the bounded window")
    _require(len(merged_bars) == 1, "SCHEMA",
             f"a 1Day window yields at most one bar per symbol, got "
             f"{len(merged_bars)}")
    record = _validate_bar_core(merged_bars[0], symbol, session_date,
                                calendar, raw_payload_digest)
    # defense-in-depth: an intraday (minute) stamp can never masquerade
    # as the daily bar even if the transport layers above are misused.
    # The documented daily-stamp convention is PRE-OPEN (the vendor's own
    # examples stamp 1Day bars at/before session midnight ET), so any
    # stamp at or after the session open is intraday and refused —
    # including post-close stamps a polling loop could observe.
    session = calendar.session(session_date)
    open_et, close_et = session.open_et, session.close_et
    assert open_et is not None and close_et is not None  # trading day
    if record.bar_ts.time() >= open_et:
        raise _Reject(
            "NOT_A_DAILY_BAR",
            f"bar stamp {record.bar_ts.time().isoformat()} ET is at or "
            f"after the session open {open_et.isoformat()} — an intraday "
            "stamp can never become the completed daily bar (the "
            "daily/minute distinction is the request contract; see "
            "official-api-contract.md)")
    return record


def _validate_legacy(
    symbol: str,
    session_date: dt.date,
    payload: dict[str, Any],
    calendar: MarketCalendar,
    raw_payload_digest: str,
) -> BarRecord:
    _require(isinstance(payload, dict), "SCHEMA", "response must be an object")
    # pinned legacy behavior: the fabricated shape's optional symbol echo
    # (the real contract makes it REQUIRED — enforced in _validate_ranged)
    echo = payload.get("symbol")
    if echo is not None:
        _require(echo == symbol, "SYMBOL_MISMATCH",
                 f"response symbol echo {echo!r} != requested {symbol!r}")
    bars = payload.get("bars")
    _require(isinstance(bars, list) and len(bars) >= 1, "SCHEMA",
             "response.bars must be a non-empty list")
    _require(len(bars) == 1, "SCHEMA",
             f"bars-latest must carry exactly one bar, got {len(bars)}")
    return _validate_bar_core(bars[0], symbol, session_date, calendar,
                              raw_payload_digest)


def _validate_bar_core(
    bar: Any,
    symbol: str,
    session_date: dt.date,
    calendar: MarketCalendar,
    raw_payload_digest: str,
) -> BarRecord:
    _require(isinstance(bar, dict), "SCHEMA", "bar entry must be an object")
    for field in ("t", "o", "h", "l", "c", "v"):
        _require(field in bar, "SCHEMA", f"bar field {field!r} missing")

    t = bar["t"]
    _require(isinstance(t, str), "SCHEMA", "bar.t must be an RFC3339 string")
    try:
        bar_ts = dt.datetime.fromisoformat(t.replace("Z", "+00:00"))
    except ValueError:
        raise _Reject("SCHEMA", f"bar.t {t!r} is not a parseable timestamp")
    _require(bar_ts.tzinfo is not None, "SCHEMA",
             "bar.t must carry a timezone — a naive vendor timestamp is "
             "not a fact")
    bar_ts = bar_ts.astimezone(ET)
    bar_date = bar_ts.date()
    _require(bar_date == session_date, (
        "UNEXPECTED_BAR_DATE" if bar_date > session_date else "STALE_BAR"),
        f"bar session {bar_date.isoformat()} != collected session "
        f"{session_date.isoformat()}")

    o = _as_decimal(bar["o"], "o")
    h = _as_decimal(bar["h"], "h")
    low = _as_decimal(bar["l"], "l")
    c = _as_decimal(bar["c"], "c")
    for name, d in (("o", o), ("h", h), ("l", low), ("c", c)):
        _require(d > 0, "NON_FINITE_PRICE", f"{name} must be positive")
    _require(h >= low, "CROSSED_BAR",
             f"high {h} < low {low}")
    _require(low <= min(o, c) and max(o, c) <= h, "CROSSED_BAR",
             f"close/open outside [low, high]: o={o} h={h} l={low} c={c}")
    v = _as_decimal(bar["v"], "v")
    _require(v >= 0, "NEGATIVE_VOLUME", f"volume {v} is negative")

    session = calendar.session(session_date)
    _require(session.is_trading_day, "SCHEMA",
             f"{session_date.isoformat()} is not a declared trading day")

    return BarRecord(
        symbol=symbol, session_date=session_date, bar_ts=bar_ts,
        open=o, high=h, low=low, close=c, volume=v,
        raw_payload_digest=raw_payload_digest)
