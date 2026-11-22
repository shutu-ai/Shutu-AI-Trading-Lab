"""Alpaca Basic/IEX daily-bar feed — the read-only real event adapter.

One :meth:`collect_once` call = one poll cycle over the preregistered
symbols (sorted, deterministic order), producing:

- validated, normalized **envelope events** ready for the Shadow engine
  (the event contract is the daemon's own ``ForwardEvent`` — the real
  plane invents no second envelope);
- **receipt records** for the collector's receipt chain: provider, feed,
  symbol, event_id, vendor bar timestamp, received_at (real wall clock),
  payload digest, protocol hash, collector code hash, and the receipt lag
  against the session close. Credential header VALUES never appear here;
- **quality rejects** and **transport errors**, receipt-logged the same
  way (failed evidence is evidence — never deleted to make a window look
  complete).

Normalization rules (preregistered in the v2 config):

- ``event_id`` = ``alpaca_iex:{SYMBOL}:1d:{session_date}`` — deterministic,
  so a re-poll of the same session is an IDEMPOTENT DUPLICATE in the
  engine, and a vendor revision of the same bar (same id, different
  payload) is a CONFLICT that conservatively suspends scoring;
- ``ts_event`` = the session's ET close converted to UTC (DST-correct,
  half-day table honored);
- ``ts_available`` = ``received_at`` — the CONSERVATIVE choice: the
  collector cannot prove when the vendor actually published the bar, so
  availability is claimed only at real receipt;
- ``dataset_hash`` = canonical digest of the normalized bar (receipt
  content hash — the real preregistration pins no fixture hash);
- ``environment`` = the preregistered session environment, stamped on
  every event.
"""

from __future__ import annotations

import datetime as dt
import os
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Callable

from trading_lab.data.calendar import ET, MarketCalendar
from trading_lab.security.canonical import canonical_digest

from urllib.parse import urlencode

from .http_client import GuardedGetClient, TransportError, market_data_headers
from .quality import (  # noqa: F401  (validate_raw_bar: pinned legacy)
    QualityReject,
    validate_raw_bar,
    validate_raw_daily_bars,
)

__all__ = [
    "AlpacaIexDailyBarFeed",
    "CollectResult",
    "CollectorCodeIdentity",
    "CREDENTIAL_ENV_NAMES",
    "FeedConfigError",
    "SOURCE",
    "credential_env_visible",
]

SOURCE = "alpaca_iex"
PROVIDER = "alpaca"
FEED = "iex"
INTERVAL = "1d"
#: receipt-chain record schema (v2 = ranged contract; adds
#: disconnect_eligible classification per FEED_ERROR record)
RECEIPT_SCHEMA = "s8-receipts-v2"

#: visibility is audited (names only); values are read by the collector
#: process only when building request headers and never logged.
CREDENTIAL_ENV_NAMES = ("APCA_API_KEY_ID", "APCA_API_SECRET_KEY")

NowFn = Callable[[], dt.datetime]


class FeedConfigError(RuntimeError):
    """The feed was constructed against something its preregistration
    does not admit."""


@dataclass(frozen=True)
class CollectorCodeIdentity:
    """The collector's own code identity, receipt-logged per message
    (forward-daemon-identity-v1 over the S8 scope)."""

    schema: str
    code_hash: str


@dataclass(frozen=True)
class CollectResult:
    session_date: dt.date | None
    status: str                       # OK | MARKET_CLOSED | OUTSIDE_POLL_WINDOW
    events: list[dict[str, Any]] = field(default_factory=list)
    receipts: list[dict[str, Any]] = field(default_factory=list)
    quality_rejects: list[dict[str, Any]] = field(default_factory=list)
    transport_errors: list[dict[str, Any]] = field(default_factory=list)


def credential_env_visible(env: dict[str, str] | None = None) -> list[str]:
    e = os.environ if env is None else env
    return sorted(name for name in CREDENTIAL_ENV_NAMES if name in e)


class AlpacaIexDailyBarFeed:
    """Read-only daily-bar collector for the preregistered symbols."""

    def __init__(
        self,
        *,
        client: GuardedGetClient,
        prereg,                                 # PreregistrationReal
        now_fn: NowFn,
        code_identity: CollectorCodeIdentity | None = None,
        credential_reader: Callable[[str], str] | None = None,
        calendar: MarketCalendar | None = None,
    ) -> None:
        self._client = client
        self._prereg = prereg
        self._now_fn = now_fn
        self._identity = code_identity
        self._credential_reader = credential_reader or os.environ.get
        self._calendar = calendar or MarketCalendar(
            holidays=set(prereg.holidays), half_days=set(prereg.half_days))
        transport = prereg.transport_config
        allowed_hosts = frozenset(
            h.lower() for h in transport.get("allowed_hosts") or ())
        # the feed binds to the transport its preregistration declares —
        # any drift is a configuration defect, refused before use
        client_hosts = frozenset(h.lower() for h in
                                 getattr(client, "_hosts", frozenset()))
        if not client_hosts <= allowed_hosts:
            raise FeedConfigError(
                f"client hosts {sorted(client_hosts)} exceed the "
                f"preregistered allowlist {sorted(allowed_hosts)}")
        self._data_host = sorted(allowed_hosts)[0]
        self._allowed_paths = tuple(transport.get("allowed_paths") or ())

    # -- one poll cycle ---------------------------------------------------------

    def collect_once(self) -> CollectResult:
        now = self._now_fn()
        if now.tzinfo is None or now.utcoffset() is None:
            raise FeedConfigError(
                "collector clock returned a naive datetime — not a fact")
        et_now = now.astimezone(ET)
        session_date = et_now.date()

        if not (self._prereg.calendar_valid_from <= session_date
                <= self._prereg.calendar_valid_until):
            # the declared calendar authority is exhausted: collection must
            # not run on invented calendar assumptions — a new prereg
            # version is required
            raise FeedConfigError(
                f"session {session_date.isoformat()} lies outside the "
                f"preregistered calendar coverage "
                f"[{self._prereg.calendar_valid_from.isoformat()}, "
                f"{self._prereg.calendar_valid_until.isoformat()}] — "
                "freeze a new preregistration version before collecting")
        if not self._calendar.is_trading_day(session_date):
            return CollectResult(session_date=session_date,
                                 status="MARKET_CLOSED")
        window = self._prereg.poll_window_et
        if not (window[0] <= et_now.time() <= window[1]):
            return CollectResult(session_date=session_date,
                                 status="OUTSIDE_POLL_WINDOW")

        headers = market_data_headers(
            self._credential_reader(CREDENTIAL_ENV_NAMES[0]) or "",
            self._credential_reader(CREDENTIAL_ENV_NAMES[1]) or "")

        result = CollectResult(session_date=session_date, status="OK")
        session_close_utc = self._calendar.session(session_date).close_utc()
        assert session_close_utc is not None  # trading day: close exists

        # contract dispatch: the PINNED LEGACY contract keeps its frozen
        # (defective) behavior for evidence reproduction only; production
        # runs the ranged daily-bars contract (schema v3)
        if self._prereg.contract_legacy:
            self._collect_legacy(result, now, session_date,
                                 session_close_utc, headers)
        else:
            self._collect_ranged(result, now, session_date,
                                 session_close_utc, headers)
        return result

    # -- legacy branch (FROZEN historical-defect evidence) ----------------------

    def _collect_legacy(self, result: CollectResult, now: dt.datetime,
                        session_date: dt.date,
                        session_close_utc: dt.datetime,
                        headers: dict[str, str]) -> None:
        """LEGACY_INVALID_VENDOR_CONTRACT — byte-frozen pre-remediation
        behavior (fabricated bars-latest shape, minute semantics consumed
        as daily). Never called under a ranged-contract preregistration;
        kept so the pinned legacy tests and RED evidence keep running."""
        for symbol in sorted(self._prereg.symbols):
            path = f"/v2/stocks/{symbol}/bars/latest"
            receipt_base: dict[str, Any] = {
                "environment": self._prereg.environment,
                "provider": PROVIDER,
                "feed": FEED,
                "symbol": symbol,
                "interval": INTERVAL,
                "session_date": session_date.isoformat(),
                "request_path": path,
                "request_query": "feed=iex",
                "received_at": now.isoformat(),
                "protocol_hash": self._prereg.hash,
            }
            if self._identity is not None:
                receipt_base["collector_code_hash"] = self._identity.code_hash
                receipt_base["collector_identity_schema"] = \
                    self._identity.schema
            try:
                payload = self._client.get_json(
                    host=self._data_host, path=path,
                    params={"feed": FEED}, headers=headers)
            except TransportError as exc:
                failure = dict(receipt_base)
                failure.update({
                    "event_type": "FEED_ERROR",
                    "error_reason": exc.reason,
                    "error_status": exc.status,
                })
                result.transport_errors.append(failure)
                continue

            raw_digest = canonical_digest(
                {"symbol": symbol, "session_date": session_date.isoformat(),
                 "payload": _jsonable(payload)})
            record = validate_raw_bar(
                symbol=symbol, session_date=session_date, payload=payload,
                calendar=self._calendar, raw_payload_digest=raw_digest)
            if isinstance(record, QualityReject):
                reject = dict(receipt_base)
                reject.update({
                    "event_type": "QUALITY_REJECT",
                    "reject_reason": record.reason,
                    "reject_detail": record.detail,
                })
                result.quality_rejects.append(reject)
                continue
            self._emit_event(result, record, receipt_base, now,
                             session_date, session_close_utc,
                             receipt_schema=None)

    # -- production branch: ranged daily bars (schema v3) -----------------------

    def _collect_ranged(self, result: CollectResult, now: dt.datetime,
                        session_date: dt.date,
                        session_close_utc: dt.datetime,
                        headers: dict[str, str]) -> None:
        """The official ranged daily-bars contract (official-api-contract.md
        §2): one bounded window per requested session — start = session
        midnight ET (inclusive; covers the vendor's pre-open daily stamp),
        end = real receipt time — with explicit timeframe=1Day, feed=iex,
        adjustment=raw; pagination bounded by the preregistered page cap.
        Every outcome (receipt / gap / quality reject / transport error) is
        receipt-logged; only a contract-valid completed daily bar can
        become a forward event."""
        contract = self._prereg.data_contract
        midnight_et = dt.datetime.combine(session_date, dt.time(0, 0),
                                          tzinfo=ET)
        base_params = {
            "timeframe": contract["timeframe"],
            "feed": FEED,
            "adjustment": contract["adjustment"],
            "start": _iso_utc(midnight_et),
            "end": _iso_utc(now),
            "limit": str(self._prereg.bars_limit),
            "sort": contract.get("sort", "asc"),
        }
        # contract drift guards — refuse before any request
        if base_params["timeframe"] != "1Day" or \
                contract["bars_endpoint"] != "ranged_daily_bars" or \
                base_params["feed"] != self._prereg.feed:
            raise FeedConfigError(
                "preregistration data_contract drift: ranged 1Day/iex "
                "required")
        query = urlencode(sorted(base_params.items()))
        for symbol in sorted(self._prereg.symbols):
            path = f"/v2/stocks/{symbol}/bars"
            receipt_base: dict[str, Any] = {
                "environment": self._prereg.environment,
                "provider": PROVIDER,
                "feed": FEED,
                "symbol": symbol,
                "interval": INTERVAL,
                "session_date": session_date.isoformat(),
                "request_path": path,
                "request_query": query,
                "receipt_schema": RECEIPT_SCHEMA,
                "received_at": now.isoformat(),
                "protocol_hash": self._prereg.hash,
            }
            if self._identity is not None:
                receipt_base["collector_code_hash"] = self._identity.code_hash
                receipt_base["collector_identity_schema"] = \
                    self._identity.schema
            try:
                merged, symbol_echo, raw_digest = self._paged_get(
                    path, dict(base_params), headers)
            except TransportError as exc:
                failure = dict(receipt_base)
                failure.update({
                    "event_type": "FEED_ERROR",
                    "error_reason": exc.reason,
                    "error_status": exc.status,
                    "disconnect_eligible": _disconnect_eligible(exc),
                })
                result.transport_errors.append(failure)
                continue

            record = validate_raw_daily_bars(
                symbol=symbol, session_date=session_date,
                merged_bars=merged, symbol_echo=symbol_echo,
                calendar=self._calendar, raw_payload_digest=raw_digest)
            if isinstance(record, QualityReject):
                reject = dict(receipt_base)
                reject.update({
                    "event_type": "QUALITY_REJECT",
                    "reject_reason": record.reason,
                    "reject_detail": record.detail,
                })
                result.quality_rejects.append(reject)
                continue
            self._emit_event(result, record, receipt_base, now,
                             session_date, session_close_utc,
                             receipt_schema=RECEIPT_SCHEMA)

    def _paged_get(self, path: str, params: dict[str, str],
                   headers: dict[str, str]) -> tuple[list[Any], Any, str]:
        """Fetch ALL pages of the bounded window (page_token loop, capped
        by the preregistered page cap). Returns (merged bars, symbol
        echo, canonical digest over the merged content)."""
        merged: list[Any] = []
        echo: Any = None
        pages: list[Any] = []
        cap = self._prereg.page_cap
        for _page in range(cap):
            resp = self._client.get_json(
                host=self._data_host, path=path, params=params,
                headers=headers)
            pages.append(_jsonable(resp))
            page_bars = resp.get("bars")
            if not isinstance(page_bars, list):
                raise TransportError(
                    "CONTRACT_SHAPE",
                    "a ranged-bars page is missing its documented bars "
                    "array (official schema stock_bars_resp_single)")
            page_echo = resp.get("symbol")
            if page_echo is None:
                raise TransportError(
                    "CONTRACT_SHAPE",
                    "a ranged-bars page is missing its documented symbol "
                    "echo")
            if echo is None:
                echo = page_echo
            elif page_echo != echo:
                raise TransportError(
                    "CONTRACT_SHAPE",
                    "symbol echo differs across pages — contract breach")
            merged.extend(page_bars)
            token = resp.get("next_page_token", None)
            if token is None or token == "":
                session_date = self._session_date()
                digest = canonical_digest({
                    "symbol": str(echo),
                    "session_date": session_date.isoformat(),
                    "bars": _jsonable(merged)})
                return merged, echo, digest
            params = {**params, "page_token": str(token)}
        raise TransportError(
            "CONTRACT_SHAPE",
            f"pagination exceeded the preregistered page cap ({cap}) — "
            "refusing to sweep beyond the bounded window")

    def _session_date(self) -> dt.date:
        return self._now_fn().astimezone(ET).date()

    # -- shared event/receipt emission ------------------------------------------

    def _emit_event(self, result: CollectResult, record, receipt_base,
                    now: dt.datetime, session_date: dt.date,
                    session_close_utc: dt.datetime,
                    *, receipt_schema: str | None) -> None:
        event_id = f"{SOURCE}:{record.symbol}:{INTERVAL}:" \
                   f"{session_date.isoformat()}"
        dataset_hash = canonical_digest({
            "provider": PROVIDER, "feed": FEED, "symbol": record.symbol,
            "interval": INTERVAL,
            "session_date": session_date.isoformat(),
            "bar": {
                "t": record.bar_ts.isoformat(),
                "o": str(record.open), "h": str(record.high),
                "l": str(record.low), "c": str(record.close),
                "v": str(record.volume),
            },
        })
        result.events.append({
            "event_id": event_id,
            "source": SOURCE,
            "dataset_hash": dataset_hash,
            "symbol": record.symbol,
            "interval": INTERVAL,
            "ts_event": session_close_utc,
            "ts_available": now,
            "received_at": now,
            "close": record.close,
            "environment": self._prereg.environment,
        })
        receipt = dict(receipt_base)
        receipt["event_id"] = event_id
        if receipt_schema is not None:
            receipt["receipt_schema"] = receipt_schema
        receipt.update({
            "event_type": "RECEIPT",
            "payload_digest": dataset_hash,
            "vendor_bar_ts": record.bar_ts.astimezone(dt.timezone.utc)
                .isoformat(),
            "session_close_utc": session_close_utc.isoformat(),
            "receipt_lag_seconds":
                (now - session_close_utc).total_seconds(),
        })
        result.receipts.append(receipt)


def _iso_utc(moment: dt.datetime) -> str:
    """RFC-3339 UTC string (the ranged endpoint's documented format)."""
    return moment.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _disconnect_eligible(exc: TransportError) -> bool:
    """Which transport failures count as DISCONNECT evidence for the
    E-Gate: network failures (TRANSPORT) and rate/server failures
    (429/5xx). Credential/config rejections (400/401/403/404) are NOT
    disconnects — they are operator-side faults and are receipted, but
    can never back a recovery claim (official-api-contract.md §2)."""
    if exc.reason == "TRANSPORT":
        return True
    if exc.reason == "HTTP_STATUS" and exc.status is not None and \
            (exc.status == 429 or exc.status >= 500):
        return True
    return False


def _jsonable(value: Any) -> Any:
    """Normalize a parsed payload (Decimal/int/str/dict/list) into the
    canonical-digest input (strings for decimals)."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bool) or value is None or \
            isinstance(value, (str, int)):
        return value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    raise FeedConfigError(
        f"payload carries an unexpected type {type(value).__name__}")
