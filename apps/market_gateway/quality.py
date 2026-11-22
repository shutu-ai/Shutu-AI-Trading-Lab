"""Data-quality validation for real market-data payloads (S8-T2).

Every raw vendor payload is validated BEFORE it can become a daemon
event; a rejected payload never reaches the forward engine (it is
receipt-logged as ``QUALITY_REJECT`` with its denominator-honest
reason). Checks are fail-closed: an unparseable or out-of-contract bar
is missing data, never "close enough".

Validation vocabulary (each reject carries a machine reason):

- ``SCHEMA``            — response shape is not the documented
                          bars-latest object; required fields missing or
                          wrongly typed;
- ``NON_FINITE_PRICE``  — NaN/inf/zero/negative OHLC (the platform bans
                          floats; values arrive as exact ``Decimal``);
- ``CROSSED_BAR``       — high < low, or close outside [low, high];
- ``NEGATIVE_VOLUME``   — volume < 0;
- ``SYMBOL_MISMATCH``   — a symbol echo disagrees with the requested
                          symbol;
- ``UNEXPECTED_BAR_DATE`` — bar timestamp maps to a LATER session than
                          the one being collected (a future/different
                          session can never be consumed as today's bar);
- ``STALE_BAR``         — bar timestamp maps to an EARLIER session
                          (previous-session data is a gap, disclosed in
                          denominators, never silently consumed).

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

__all__ = ["BarRecord", "QualityReject", "validate_raw_bar"]


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
    """Validate one bars-latest response body for ``symbol`` against the
    session being collected. Raises-free interface: returns a
    :class:`BarRecord` or a :class:`QualityReject` (never throws except
    on programming errors)."""
    try:
        return _validate(symbol, session_date, payload, calendar,
                         raw_payload_digest)
    except _Reject as exc:
        return QualityReject(symbol=symbol, reason=exc.reason,
                             detail=exc.detail)


def _validate(
    symbol: str,
    session_date: dt.date,
    payload: dict[str, Any],
    calendar: MarketCalendar,
    raw_payload_digest: str,
) -> BarRecord:
    _require(isinstance(payload, dict), "SCHEMA", "response must be an object")
    bars = payload.get("bars")
    _require(isinstance(bars, list) and len(bars) >= 1, "SCHEMA",
             "response.bars must be a non-empty list")
    _require(len(bars) == 1, "SCHEMA",
             f"bars-latest must carry exactly one bar, got {len(bars)}")
    bar = bars[0]
    _require(isinstance(bar, dict), "SCHEMA", "bar entry must be an object")
    for field in ("t", "o", "h", "l", "c", "v"):
        _require(field in bar, "SCHEMA", f"bar field {field!r} missing")

    echo = payload.get("symbol")
    if echo is not None:
        _require(echo == symbol, "SYMBOL_MISMATCH",
                 f"response symbol echo {echo!r} != requested {symbol!r}")

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
