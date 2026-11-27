"""Restricted historical collection entry — the logic behind
``scripts/collect_historical_snapshot.py`` (BUSINESS-MVP-V02 workflow A2).

One execution window, the two authorized symbols (SPY + QQQ, both
required together), the frozen license window 2017-01-01..2025-12-31
(ET session-date semantics via :class:`HistoricalWindow`), and the
authorized request budget of 30 shared across both symbols — every byte
through the existing :class:`GuardedGetClient`; this module adds only
orchestration, contract shaping and honest bookkeeping.

Transport discipline (fail-closed):

- ``probe`` (default): the in-repo deterministic FAKE transport
  (:class:`~apps.market_gateway.probe_transport.FakeAlpacaProbeTransport`)
  — zero real network; every artifact labeled ``FAKE_TRANSPORT``;
- ``live``: the real guarded client, REFUSED unless the operator has
  pre-set ``H1_REAL_API_AUTHORIZED=SIGNED`` in the environment (blind
  env mechanism mirroring the S8 runner: the token VALUE is never
  echoed; credential env NAMES may appear in the audit, values never).
  This entry never sets the variable itself.

Outputs — ALL under the ``historical_research`` namespace of the output
dir, nothing written elsewhere:

- ``historical_research/<SYMBOL>/bars.jsonl`` — one contract-shaped bar
  per line (frozen ``MarketBar`` fields; ``ts_event_utc`` = the
  calendar-derived session close, ``ts_available_utc`` = the calendar
  next-open rule), each line validated through ``MarketBar``;
- ``historical_research/collection_manifest.json`` — per-symbol row
  counts / denominators / actual missing, request audit (urls, pages,
  request_count), budget accounting vs 30, calendar supply version +
  hash, window, transport label, RECOMPUTED content hashes of the bars
  files, license/admission status. Written ONLY on full success — the
  manifest's existence is the success marker;
- ``historical_research/collection_audit_partial.json`` — the abort
  dump (reason + everything collected so far) when anything refuses
  mid-run; no manifest, no bars files (two-phase commit).

Admission honesty (workflow A4, recorded not hidden): everything this
entry produces is ``NOT_RESEARCH_ADMITTED`` — license
``LICENSE_UNVERIFIED``, PIT level ``ASSUMED`` (the next-open MODEL
assumption; an HTTP 200 never proves point-in-time publication), raw
prices only (no corporate actions — no total-return or long-horizon
comparability claims). This entry collects; it never admits.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from trading_lab.contracts.enums import AdjustmentKind
from trading_lab.contracts.events import MarketBar
from trading_lab.data.calendar import ET, UTC, CalendarError
from trading_lab.data.historical import HistoricalBarRecord, HistoricalDataError
from trading_lab.data.historical_calendar import VersionedMarketCalendar
from trading_lab.data.historical_calendar_supply import (
    FROZEN_SUPPLY_HASH_V2,
    NYSE_2017_2025_SUPPLY_V2,
    frozen_supply_hash,
)
from trading_lab.security.canonical import sha256_hex

from .historical_bars import (
    DEFAULT_MAX_REQUESTS,
    HISTORY_HOST,
    HISTORY_PATH_PATTERN,
    HistoricalBarsClient,
    HistoricalFetchResult,
    HistoricalRequestRefused,
    HistoricalWindow,
    TIMEFRAME,
)
from .http_client import GuardedGetClient, TransportError, market_data_headers
from .probe_transport import FAKE_TRANSPORT_LABEL, FakeAlpacaProbeTransport

__all__ = [
    "AUTH_ENV_VAR",
    "AUTHORIZED_UNIVERSE",
    "AuthorizationRefused",
    "BARS_FILE_NAME",
    "BUDGET_CAP",
    "BlockedEnv",
    "CollectionConfig",
    "CollectionError",
    "CollectionReport",
    "LICENSE_WINDOW",
    "LIVE_TRANSPORT_LABEL",
    "MANIFEST_NAME",
    "NAMESPACE_DIRNAME",
    "PARTIAL_AUDIT_NAME",
    "TRANSPORT_LIVE",
    "TRANSPORT_PROBE",
    "dedupe_bars_rows",
    "resolve_transport_authorization",
    "run_collection",
]

# -- frozen contract constants -----------------------------------------------

AUTH_ENV_VAR = "H1_REAL_API_AUTHORIZED"
AUTH_SIGNATURE_VALUE = "SIGNED"
#: credential env NAMES (blind mechanism — presence only, values never read)
CREDENTIAL_ENV_NAMES = ("APCA_API_KEY_ID", "APCA_API_SECRET_KEY")

LICENSE_WINDOW = HistoricalWindow(
    start=dt.date(2017, 1, 1),
    end=dt.date(2025, 12, 31),
    label="h1-frozen-license-window-2017-2025",
)
AUTHORIZED_UNIVERSE = frozenset({"SPY", "QQQ"})
#: canonical execution order for the universe (manifests and fetch order
#: are byte-deterministic regardless of how the operator typed --symbol)
AUTHORIZED_SYMBOL_ORDER = ("SPY", "QQQ")
BUDGET_CAP = DEFAULT_MAX_REQUESTS  # 30: probing + both symbols, one window

TRANSPORT_PROBE = "probe"
TRANSPORT_LIVE = "live"
LIVE_TRANSPORT_LABEL = "LIVE"
NAMESPACE_DIRNAME = "historical_research"
BARS_FILE_NAME = "bars.jsonl"
MANIFEST_NAME = "collection_manifest.json"
PARTIAL_AUDIT_NAME = "collection_audit_partial.json"

MANIFEST_SCHEMA = "collection_manifest_v1"
AUDIT_SCHEMA = "collection_audit_partial_v1"

#: probe runs are dry-run acceptance: the download moment is a DECLARED
#: fixture fact (frozen constant), so probe artifacts stay reproducible.
PROBE_RECEIVED_AT_UTC = dt.datetime(2026, 11, 27, tzinfo=UTC)

#: bars.jsonl row quality/source labels (honest: probe rows are fake)
SOURCE_PROBE = FAKE_TRANSPORT_LABEL
SOURCE_LIVE = "alpaca_iex"
QUALITY_LABEL = "PIT_ASSUMED_NEXT_OPEN"
_SYMBOL_SEGMENT_RE = re.compile(r"^[A-Z]{1,5}$")


# -- failures -----------------------------------------------------------------


class CollectionError(ValueError):
    """A configuration or authorization refusal (fail-closed) — raised
    BEFORE any transport work, nothing is ever written."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


class AuthorizationRefused(CollectionError):
    """Live transport without the operator's signature."""


class BlockedEnv(CollectionError):
    """Live transport signed, but credentials are not configured."""


# -- configuration -------------------------------------------------------------


@dataclass(frozen=True)
class CollectionConfig:
    """One collection execution window's pinned inputs.

    ``symbols`` must be exactly SPY+QQQ (both, together — the V0.2
    universe); the stored order is canonicalized to SPY,QQQ so manifests
    are byte-deterministic. ``request_budget`` may only LOWER the
    authorized cap of 30 (raising is structurally refused downstream by
    :class:`HistoricalBarsClient`)."""

    symbols: tuple[str, ...]
    start: dt.date
    end: dt.date
    output_dir: Path
    transport: str = TRANSPORT_PROBE
    request_budget: int = BUDGET_CAP

    def __post_init__(self) -> None:
        if set(self.symbols) != AUTHORIZED_UNIVERSE or len(self.symbols) != 2:
            raise CollectionError(
                "UNIVERSE_MISMATCH",
                "both SPY and QQQ are required together for the V0.2 "
                f"universe, got {sorted(set(self.symbols))}",
            )
        if not all(isinstance(s, str) and _SYMBOL_SEGMENT_RE.match(s) for s in self.symbols):
            raise CollectionError("SYMBOL_SEGMENT_UNSAFE", "symbols must be [A-Z]{1,5}")
        object.__setattr__(
            self,
            "symbols",
            tuple(s for s in AUTHORIZED_SYMBOL_ORDER if s in set(self.symbols)),
        )
        if not isinstance(self.start, dt.date) or not isinstance(self.end, dt.date):
            raise CollectionError("BAD_WINDOW", "start/end must be dates")
        if self.start > self.end:
            raise CollectionError("BAD_WINDOW", f"{self.start} > {self.end}")
        if not LICENSE_WINDOW.contains(self.start, self.end):
            raise CollectionError(
                "OUTSIDE_LICENSE_WINDOW",
                f"[{self.start.isoformat()}, {self.end.isoformat()}] outside the "
                f"frozen license window [{LICENSE_WINDOW.start.isoformat()}, "
                f"{LICENSE_WINDOW.end.isoformat()}]",
            )
        if self.transport not in (TRANSPORT_PROBE, TRANSPORT_LIVE):
            raise CollectionError(
                "BAD_TRANSPORT", f"transport must be probe|live, got {self.transport!r}"
            )
        if not isinstance(self.request_budget, int) or not 1 <= self.request_budget <= BUDGET_CAP:
            raise CollectionError(
                "BAD_BUDGET", f"request_budget must be 1..{BUDGET_CAP}, got {self.request_budget}"
            )


@dataclass(frozen=True)
class CollectionReport:
    """The single result object the CLI prints; credential-free."""

    status: str  # COLLECTED | ABORTED
    manifest: dict[str, Any] | None
    partial_audit: dict[str, Any] | None
    manifest_path: Path | None
    partial_audit_path: Path | None
    bars_paths: tuple[Path, ...]

    @property
    def ok(self) -> bool:
        return self.status == "COLLECTED"


@dataclass(frozen=True)
class TransportAuthorization:
    """The resolved transport + what the environment authorized (NAMES
    only — values are never read into this object)."""

    transport: str
    label: str
    credential_env_visible: tuple[str, ...]


def resolve_transport_authorization(
    transport: str, *, environ: Mapping[str, str]
) -> TransportAuthorization:
    """Fail-closed transport gate. ``live`` runs only when the operator
    has pre-signed the environment (``H1_REAL_API_AUTHORIZED=SIGNED``);
    the entry never sets it, and a wrong/missing token is refused with
    the operator's value never echoed."""
    if transport == TRANSPORT_PROBE:
        return TransportAuthorization(TRANSPORT_PROBE, FAKE_TRANSPORT_LABEL, ())
    token = environ.get(AUTH_ENV_VAR)
    if token != AUTH_SIGNATURE_VALUE:
        raise AuthorizationRefused(
            "LIVE_AUTHORIZATION_REFUSED",
            f"environment {AUTH_ENV_VAR} must equal {AUTH_SIGNATURE_VALUE!r} "
            "(set by the operator after signing the revised H1 §7 — this "
            "entry never sets it itself)",
        )
    visible = tuple(
        name for name in CREDENTIAL_ENV_NAMES if environ.get(name) is not None
    )
    if len(visible) != len(CREDENTIAL_ENV_NAMES):
        missing = sorted(set(CREDENTIAL_ENV_NAMES) - set(visible))
        raise BlockedEnv(
            "LIVE_BLOCKED_ENV",
            "market-data credentials are not visible in the environment "
            f"(missing names: {', '.join(missing)}); values are never read "
            "at this gate",
        )
    return TransportAuthorization(TRANSPORT_LIVE, LIVE_TRANSPORT_LABEL, visible)


# -- namespace paths -----------------------------------------------------------


def _bars_path(output_dir: Path, symbol: str) -> Path:
    return output_dir / NAMESPACE_DIRNAME / symbol / BARS_FILE_NAME


def _manifest_path(output_dir: Path) -> Path:
    return output_dir / NAMESPACE_DIRNAME / MANIFEST_NAME


def _partial_audit_path(output_dir: Path) -> Path:
    return output_dir / NAMESPACE_DIRNAME / PARTIAL_AUDIT_NAME


def _write_json_doc(path: Path, doc: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(doc, indent=2, sort_keys=True) + "\n").encode("utf-8"))


# -- disclosure documents (A4 honesty fields) -----------------------------------


def _license_doc() -> dict[str, str]:
    return {
        "status": "LICENSE_UNVERIFIED",
        "calendar_supply_license": (
            "LICENSE_UNVERIFIED (carried unchanged from calendar supply v2: "
            "ICE/NYSE website personal-use terms are not a dataset license)"
        ),
        "market_data_license": (
            "Alpaca historical-data personal-research attestation (H1 §7 "
            "draft) remains unsigned"
        ),
    }


def _pit_doc() -> dict[str, str]:
    return {
        "level": "ASSUMED",
        "rule": "daily_close_available_next_open",
        "disclosure": (
            "ASSUMED stays ASSUMED: HTTP 200 does not prove point-in-time "
            "publication and the receipt moment is never backfilled as an "
            "availability time; ts_available_utc is the calendar next-open "
            "MODEL ASSUMPTION, never vendor evidence"
        ),
        "api_verified_claim": "NONE",
    }


def _admission_doc() -> dict[str, str]:
    return {
        "status": "NOT_RESEARCH_ADMITTED",
        "until": (
            "the account owner signs the revised H1 §7 and confirms the "
            "calendar/data licenses; until then these files must not enter "
            "formal research"
        ),
        "corporate_actions": "NONE_COLLECTED",
        "raw_only_disclosure": (
            "raw prices without corporate actions: no total-return, "
            "long-horizon comparability, or unbiased-alpha claims are "
            "permitted from this data"
        ),
        "s8_forward_ledger": "EXCLUDED",
    }


def _window_doc(config: CollectionConfig) -> dict[str, Any]:
    return {
        "start": config.start.isoformat(),
        "end": config.end.isoformat(),
        "label": LICENSE_WINDOW.label,
        "semantics": "ET session dates (HistoricalWindow)",
        "within_frozen_license": True,
    }


# -- contract shaping -----------------------------------------------------------


def _row_key(row: Mapping[str, Any]) -> tuple[str, str]:
    """Deterministic dedup key: (asset_id, session close instant). The
    close instant IS the session identity for daily bars."""
    ts = dt.datetime.fromisoformat(str(row["ts_event_utc"])).astimezone(UTC)
    return (str(row["asset_id"]), ts.isoformat())


def dedupe_bars_rows(
    rows: Sequence[Mapping[str, Any]], *, context: str
) -> tuple[dict[str, Any], ...]:
    """Deterministic dedup over duplicate/overlapping row sets: rows that
    agree on the dedup key AND every field collapse to one; rows that
    share a key but disagree on any field are a CONFLICT and refuse (we
    never silently pick a winner). Output is sorted by (asset_id,
    session close) — byte-stable regardless of input order."""
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = _row_key(row)
        candidate = dict(row)
        existing = merged.get(key)
        if existing is None:
            merged[key] = candidate
        elif existing != candidate:
            raise HistoricalDataError(
                f"{context}: conflicting duplicate rows for {key[0]} @ "
                f"{key[1]} — refusing to merge differing data"
            )
    ordered = sorted(merged.items(), key=lambda item: (item[0][0], item[0][1]))
    return tuple(dict(row) for _key, row in ordered)


def _to_contract_row(
    vendor_row: Mapping[str, Any],
    *,
    symbol: str,
    calendar: VersionedMarketCalendar,
    source: str,
    received_at_utc: dt.datetime,
) -> dict[str, str]:
    """One validated vendor row -> one contract-shaped dict: ts_event is
    the calendar-derived session close, ts_available the calendar
    next-open rule (a declared MODEL assumption, never vendor evidence)."""
    session_date = dt.date.fromisoformat(str(vendor_row["session_date"]))
    session = calendar.session(session_date)
    close_utc = session.close_utc()
    if close_utc is None:
        raise HistoricalDataError(
            f"{symbol} {session_date.isoformat()}: supply says no session close"
        )
    available_utc = calendar.session_open_after(close_utc)
    record = HistoricalBarRecord.assumed_next_open_row(
        vendor_row,
        symbol=symbol,
        session_date=session_date,
        session_close_utc=close_utc,
        assumed_available_at_utc=available_utc,
        received_at_utc=received_at_utc,
    )
    if not isinstance(record.available_at_utc, dt.datetime):
        raise HistoricalDataError(
            f"{symbol} {session_date.isoformat()}: availability is not a "
            "timestamp (the UNKNOWN marker must never reach the contract "
            "shaper)"
        )
    row = {
        "asset_id": record.symbol,
        "ts_event_utc": record.ts_event_utc.isoformat(),
        "ts_available_utc": record.available_at_utc.astimezone(UTC).isoformat(),
        "interval": TIMEFRAME,
        "open": str(record.open),
        "high": str(record.high),
        "low": str(record.low),
        "close": str(record.close),
        "volume": str(Decimal(record.volume)),
        "source": source,
        "adjustment": AdjustmentKind.RAW.value,
        "quality": QUALITY_LABEL,
    }
    _validate_contract_row(row, context=f"{symbol} {session_date.isoformat()}")
    return row


def _validate_contract_row(row: Mapping[str, Any], *, context: str) -> None:
    """The exact dict that will be serialized must parse as the frozen
    MarketBar contract (JSON mode = the file's wire format)."""
    try:
        MarketBar.model_validate_json(json.dumps(row, sort_keys=True))
    except ValueError as exc:
        raise HistoricalDataError(
            f"{context}: row violates the MarketBar contract: {exc}"
        ) from exc


def _load_existing_rows(path: Path, *, context: str) -> tuple[dict[str, Any], ...]:
    """Read a previous run's bars.jsonl (if any) for the merge dedup; a
    corrupt file refuses the run instead of being silently overwritten."""
    if not path.exists():
        return ()
    rows: list[dict[str, Any]] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise HistoricalDataError(
                f"{context}: existing {path.name} line {lineno} is not JSON — "
                "refusing to build on a corrupt file"
            ) from exc
    return tuple(rows)


def _write_bars_file(path: Path, rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    payload = "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload.encode("utf-8"))
    data = path.read_bytes()  # recomputed from disk — never trusted upstream
    return {"bytes": len(data), "sha256": sha256_hex(data)}


# -- the collection run ----------------------------------------------------------


def run_collection(
    config: CollectionConfig,
    *,
    environ: Mapping[str, str] | None = None,
    probe_opener: FakeAlpacaProbeTransport | None = None,
) -> CollectionReport:
    """Run one collection window. Configuration/authorization refusals
    raise :class:`CollectionError` subclasses BEFORE any disk write;
    mid-run refusals (budget, HTTP status, contract) return an ABORTED
    report with the partial-audit dump written and NO manifest."""
    environ = os.environ if environ is None else environ
    auth = resolve_transport_authorization(config.transport, environ=environ)
    calendar = VersionedMarketCalendar.from_supply(NYSE_2017_2025_SUPPLY_V2)
    supply_hash = frozen_supply_hash(NYSE_2017_2025_SUPPLY_V2)
    if supply_hash != FROZEN_SUPPLY_HASH_V2:
        raise CollectionError(
            "CALENDAR_SUPPLY_DRIFT",
            "computed v2 supply hash does not match the frozen constant — "
            "the calendar drifted; refuse and re-verify sources",
        )
    output_dir = Path(config.output_dir)
    received_at = (
        PROBE_RECEIVED_AT_UTC
        if config.transport == TRANSPORT_PROBE
        else dt.datetime.now(dt.timezone.utc)
    )
    opener = (
        probe_opener if probe_opener is not None else FakeAlpacaProbeTransport(calendar=calendar)
    )
    headers: Mapping[str, str] | None = None
    if auth.transport == TRANSPORT_LIVE:
        # blind credential pass-through: values flow into request headers
        # only; they are never logged, receipted, or printed anywhere.
        headers = market_data_headers(
            environ["APCA_API_KEY_ID"], environ["APCA_API_SECRET_KEY"]
        )
    client = HistoricalBarsClient(
        client=GuardedGetClient(
            allowed_hosts=[HISTORY_HOST],
            allowed_paths=[HISTORY_PATH_PATTERN],
            opener=opener if config.transport == TRANSPORT_PROBE else None,
        ),
        window=LICENSE_WINDOW,
        max_requests=config.request_budget,
    )
    audit = _base_audit_doc(config, auth, calendar, supply_hash, output_dir)
    try:
        fetched: list[HistoricalFetchResult] = []
        for symbol in config.symbols:
            audit["symbols"][symbol] = {"status": "IN_FLIGHT"}
            result = client.fetch_daily_bars(
                symbol=symbol,
                start=config.start,
                end=config.end,
                received_at_utc=received_at,
                headers=headers,
            )
            audit["symbols"][symbol] = {
                "status": "FETCHED",
                "rows": len(result.rows),
                "pages": result.pages,
                "request_urls": list(result.request_urls),
            }
            fetched.append(result)
        source = SOURCE_PROBE if config.transport == TRANSPORT_PROBE else SOURCE_LIVE
        rows_by_symbol = {
            result.symbol: _merge_rows(
                _bars_path(output_dir, result.symbol),
                [
                    _to_contract_row(
                        row,
                        symbol=result.symbol,
                        calendar=calendar,
                        source=source,
                        received_at_utc=received_at,
                    )
                    for row in result.rows
                ],
            )
            for result in fetched
        }
    except (HistoricalRequestRefused, TransportError, HistoricalDataError, CalendarError) as exc:
        return _abort(config, audit, client, opener, exc)
    return _commit(
        config, auth, calendar, client, output_dir, fetched, rows_by_symbol, received_at
    )


def _merge_rows(
    bars_path: Path,
    incoming: list[dict[str, str]],
) -> tuple[dict[str, Any], ...]:
    """Merge this run's rows over any previous run's file with the
    deterministic dedup (idempotent reruns, overlapping windows keep
    history, conflicting data refuses)."""
    existing = _load_existing_rows(bars_path, context="merge-with-existing")
    return dedupe_bars_rows(
        [*existing, *incoming], context=f"merge {bars_path.parent.name}"
    )


# -- audit / manifest assembly ----------------------------------------------------


def _base_audit_doc(
    config: CollectionConfig,
    auth: TransportAuthorization,
    calendar: VersionedMarketCalendar,
    supply_hash: str,
    output_dir: Path,
) -> dict[str, Any]:
    return {
        "schema": AUDIT_SCHEMA,
        "status": "ABORTED",
        "reason": None,
        "detail": None,
        "transport": {"mode": config.transport, "label": auth.label},
        "calendar_supply": {
            "version": calendar.supply.version,
            "hash": supply_hash,
            "hash_frozen": FROZEN_SUPPLY_HASH_V2,
        },
        "window": _window_doc(config),
        "budget": {"cap": BUDGET_CAP, "spent": 0, "remaining": BUDGET_CAP},
        "symbols": {},
        "request_urls_seen": [],
        "request_urls_note": (
            "URL-level receipts exist for the probe transport (fixture); "
            "live partial receipts belong to the separately authorized pilot"
        ),
        "authorization": {"credential_env_visible": list(auth.credential_env_visible)},
        "license": _license_doc(),
        "pit": _pit_doc(),
        "admission": _admission_doc(),
        "previous_manifest_present": _manifest_path(output_dir).exists(),
    }


def _abort(
    config: CollectionConfig,
    audit: dict[str, Any],
    client: HistoricalBarsClient,
    opener: FakeAlpacaProbeTransport | None,
    exc: Exception,
) -> CollectionReport:
    audit["reason"] = str(getattr(exc, "reason", "") or type(exc).__name__)
    audit["detail"] = str(exc)
    audit["budget"]["spent"] = client.request_count
    audit["budget"]["remaining"] = max(0, BUDGET_CAP - client.request_count)
    if opener is not None:
        audit["request_urls_seen"] = list(opener.requests)
    for state in audit["symbols"].values():
        if state.get("status") == "IN_FLIGHT":
            state["status"] = "REFUSED"
    path = _partial_audit_path(Path(config.output_dir))
    _write_json_doc(path, audit)
    return CollectionReport(
        status="ABORTED",
        manifest=None,
        partial_audit=audit,
        manifest_path=None,
        partial_audit_path=path,
        bars_paths=(),
    )


def _commit(
    config: CollectionConfig,
    auth: TransportAuthorization,
    calendar: VersionedMarketCalendar,
    client: HistoricalBarsClient,
    output_dir: Path,
    fetched: list[HistoricalFetchResult],
    rows_by_symbol: dict[str, tuple[dict[str, Any], ...]],
    received_at: dt.datetime,
) -> CollectionReport:
    expected = set(calendar.expected_sessions(config.start, config.end))
    symbols_doc: dict[str, Any] = {}
    bars_paths: list[Path] = []
    for result in fetched:
        symbol = result.symbol
        rows = rows_by_symbol[symbol]
        path = _bars_path(output_dir, symbol)
        file_doc = _write_bars_file(path, rows)
        bars_paths.append(path)
        observed = {
            dt.datetime.fromisoformat(str(row["ts_event_utc"])).astimezone(ET).date()
            for row in rows
        }
        missing = sorted(expected - observed)
        symbols_doc[symbol] = {
            "row_count": len(rows),
            "expected_sessions": len(expected),
            "missing_sessions": [day.isoformat() for day in missing],
            "missing_rate": (len(missing) / len(expected)) if expected else 0.0,
            "pages": result.pages,
            "request_count_cumulative": result.request_count,
            "request_urls": list(result.request_urls),
            "page_tokens_seen": list(result.page_tokens_seen),
            "complete": result.complete,
            "bars_file": path.relative_to(output_dir).as_posix(),
            "bars_bytes": file_doc["bytes"],
            "bars_sha256": file_doc["sha256"],
        }
    manifest: dict[str, Any] = {
        "schema": MANIFEST_SCHEMA,
        "status": "COLLECTED",
        "namespace": NAMESPACE_DIRNAME,
        "window": _window_doc(config),
        "transport": {
            "mode": config.transport,
            "label": auth.label,
            "real_network_used": config.transport == TRANSPORT_LIVE,
        },
        "calendar_supply": {
            "version": calendar.supply.version,
            "hash": frozen_supply_hash(calendar.supply),
            "hash_frozen": FROZEN_SUPPLY_HASH_V2,
        },
        "budget": {
            "cap": BUDGET_CAP,
            "spent": client.request_count,
            "remaining": BUDGET_CAP - client.request_count,
        },
        "received_at_utc": received_at.isoformat(),
        "received_at_is_probe_fixture_fact": config.transport == TRANSPORT_PROBE,
        "symbols": symbols_doc,
        "license": _license_doc(),
        "pit": _pit_doc(),
        "admission": _admission_doc(),
    }
    manifest_path = _manifest_path(output_dir)
    _write_json_doc(manifest_path, manifest)
    return CollectionReport(
        status="COLLECTED",
        manifest=manifest,
        partial_audit=None,
        manifest_path=manifest_path,
        partial_audit_path=None,
        bars_paths=tuple(bars_paths),
    )
