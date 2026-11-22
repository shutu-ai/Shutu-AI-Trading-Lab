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

from .http_client import GuardedGetClient, TransportError, market_data_headers
from .quality import QualityReject, validate_raw_bar

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

        # deterministic poll order: sorted symbols (independent of the
        # frozen YAML's listing order)
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

            event_id = f"{SOURCE}:{symbol}:{INTERVAL}:" \
                       f"{session_date.isoformat()}"
            dataset_hash = canonical_digest({
                "provider": PROVIDER, "feed": FEED, "symbol": symbol,
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
                "symbol": symbol,
                "interval": INTERVAL,
                "ts_event": session_close_utc,
                "ts_available": now,
                "received_at": now,
                "close": record.close,
                "environment": self._prereg.environment,
            })
            receipt = dict(receipt_base)
            receipt.update({
                "event_type": "RECEIPT",
                "event_id": event_id,
                "payload_digest": dataset_hash,
                "vendor_bar_ts": record.bar_ts.astimezone(dt.timezone.utc)
                    .isoformat(),
                "session_close_utc": session_close_utc.isoformat(),
                "receipt_lag_seconds":
                    (now - session_close_utc).total_seconds(),
            })
            result.receipts.append(receipt)
        return result


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
