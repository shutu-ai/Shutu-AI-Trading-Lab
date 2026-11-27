"""Current-window incremental market-data update entry (T3-B of
BUSINESS-V03-OPERATIONAL-ACTIVATION-20261127-R1) — the logic behind
``scripts/update_market_data.py``.

Mirrors ``collection_session.py`` (same guarded client, same pinned
host/path/symbols/feed/timeframe/adjustment, same ``historical_research``
namespace layout, same two-phase commit) but for INCREMENTAL
current-window updates driven by the OPERATOR-SUPPLIED current calendar
supply (:func:`~trading_lab.data.historical_calendar_supply.load_supply_from_config`),
NOT the frozen H1 2017-2025 window:

- window: explicit ``--start/--end`` (ET session-date semantics), or by
  default end = yesterday ET and start = the 10th session back per the
  current supply;
- request budget: default 6, STRUCTURALLY CAPPED at 6 — current-window
  dates, endpoints and frequencies are a SEPARATE authorization from
  the H1 2017-2025 license window, which never extends here; raising
  the cap is a code change plus a new authorization, not a CLI flag;
- authorization gate, fail-closed: ``--transport live`` requires BOTH
  ``CURRENT_DATA_AUTHORIZED=SIGNED`` in the environment (blind
  mechanism — the variable's actual value is never echoed) AND an
  operator-written ``--authorization-record`` JSON (``authorization_ref``,
  ``attested_by``, ``attested_at``, ``scope{symbols,start,end,budget}``)
  whose scope matches the invocation exactly — any mismatch refuses
  before any byte is sent;
- probe (default) runs offline against the in-repo deterministic FAKE
  transport (same seam as the collector) and labels every artifact
  ``FAKE_TRANSPORT_INCREMENTAL`` — probe rows are fake data, never
  presented as market data;
- output: a CLEAN output root only, via the caller-chosen
  ``--output-dir``. The run REFUSES if the target namespace already
  holds a manifest or any bars file — incremental MERGE into an
  existing snapshot is future work, documented, not silently done;
- admission honesty: everything this entry produces is
  ``NOT_RESEARCH_ADMITTED`` (probe rows are fake; live rows are raw
  prices with ASSUMED next-open availability — an HTTP 200 never
  proves point-in-time publication). The calendar license is whatever
  the operator's config states (placeholder ``LICENSE_UNVERIFIED``),
  recorded verbatim, never upgraded.

The calendar supply is SUPPLIED DATA: sessions, half-days and holidays
come only from the operator-maintained config; data gaps in market
data are never treated as closures.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from trading_lab.data.calendar import CalendarError, ET
from trading_lab.data.historical import HistoricalDataError
from trading_lab.data.historical_calendar import CalendarSupply, VersionedMarketCalendar
from trading_lab.data.historical_calendar_supply import frozen_supply_hash
from trading_lab.security.canonical import sha256_hex

from .collection_session import (  # same-package reuse — ONE implementation each
    AUTHORIZED_SYMBOL_ORDER,
    AUTHORIZED_UNIVERSE,
    BARS_FILE_NAME,
    CREDENTIAL_ENV_NAMES,
    LIVE_TRANSPORT_LABEL,
    MANIFEST_NAME,
    NAMESPACE_DIRNAME,
    PROBE_RECEIVED_AT_UTC,
    TRANSPORT_LIVE,
    TRANSPORT_PROBE,
    _SYMBOL_SEGMENT_RE,
    _pit_doc,
    _to_contract_row,
)
from .historical_bars import (
    HISTORY_HOST,
    HISTORY_PATH_PATTERN,
    HistoricalBarsClient,
    HistoricalFetchResult,
    HistoricalRequestRefused,
    HistoricalWindow,
)
from .http_client import GuardedGetClient, TransportError, market_data_headers
from .probe_transport import FakeAlpacaProbeTransport

__all__ = [
    "AUTH_ENV_VAR",
    "AUTH_SIGNATURE_VALUE",
    "AuthorizationRecord",
    "AuthorizationRefused",
    "AuthorizationScope",
    "BlockedEnv",
    "DEFAULT_SESSIONS_LOOKBACK",
    "UPDATE_BUDGET_CAP",
    "UPDATE_DEFAULT_BUDGET",
    "UPDATE_MANIFEST_NAME",
    "UPDATE_PARTIAL_AUDIT_NAME",
    "TRANSPORT_LABEL_PROBE_INCREMENTAL",
    "UpdateConfig",
    "UpdateError",
    "UpdateReport",
    "WINDOW_SOURCE_DEFAULT",
    "WINDOW_SOURCE_EXPLICIT",
    "load_authorization_record",
    "parse_authorization_record",
    "resolve_default_window",
    "resolve_update_authorization",
    "run_update",
]

# -- frozen contract constants -------------------------------------------------

AUTH_ENV_VAR = "CURRENT_DATA_AUTHORIZED"
AUTH_SIGNATURE_VALUE = "SIGNED"
#: structural budget cap for current-window updates. Current dates are a
#: SEPARATE authorization from H1 2017-2025; the cap binds the CLI —
#: raising it is a code change plus a new operator authorization.
UPDATE_BUDGET_CAP = 6
UPDATE_DEFAULT_BUDGET = 6
#: default window depth: end = yesterday ET, start = this many sessions back
DEFAULT_SESSIONS_LOOKBACK = 10

TRANSPORT_LABEL_PROBE_INCREMENTAL = "FAKE_TRANSPORT_INCREMENTAL"
SOURCE_LIVE_INCREMENTAL = "alpaca_iex"
UPDATE_MANIFEST_NAME = "update_manifest.json"
UPDATE_PARTIAL_AUDIT_NAME = "update_audit_partial.json"
MANIFEST_SCHEMA = "update_manifest_v1"
AUDIT_SCHEMA = "update_audit_partial_v1"

WINDOW_SOURCE_EXPLICIT = "explicit_cli_dates"
WINDOW_SOURCE_DEFAULT = "default_yesterday_et_minus_10_sessions"

_RECORD_KEYS = frozenset({"authorization_ref", "attested_by", "attested_at", "scope"})
_SCOPE_KEYS = frozenset({"symbols", "start", "end", "budget"})


# -- failures --------------------------------------------------------------------


class UpdateError(ValueError):
    """A configuration or authorization refusal (fail-closed) — raised
    BEFORE any transport work, nothing is ever written."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


class AuthorizationRefused(UpdateError):
    """Live transport without the operator's signature or record."""


class BlockedEnv(UpdateError):
    """Live transport signed and recorded, but credentials not configured."""


# -- authorization record ----------------------------------------------------------


@dataclass(frozen=True)
class AuthorizationScope:
    """The scope one authorization record attests (closed world)."""

    symbols: frozenset[str]
    start: dt.date
    end: dt.date
    budget: int


@dataclass(frozen=True)
class AuthorizationRecord:
    """One operator-written current-data authorization record."""

    authorization_ref: str
    attested_by: str
    attested_at: dt.datetime
    scope: AuthorizationScope
    source: str


def parse_authorization_record(raw: Mapping[str, Any], *, source: str) -> AuthorizationRecord:
    """Parse + validate one operator-written authorization record.
    Fail-closed: unknown keys (top level and scope), missing fields,
    empty attestation fields, a naive ``attested_at``, a budget outside
    the structural cap — all refuse. (Scope-vs-invocation matching is a
    separate, later gate.)"""
    if not isinstance(raw, dict):
        raise AuthorizationRefused(
            "AUTHORIZATION_RECORD_INVALID",
            f"{source}: record must be a JSON object",
        )
    unknown = sorted(str(key) for key in set(raw) - _RECORD_KEYS)
    if unknown:
        raise AuthorizationRefused(
            "AUTHORIZATION_RECORD_INVALID",
            f"{source}: unknown keys {unknown} — known keys are {sorted(_RECORD_KEYS)}",
        )
    missing = sorted(_RECORD_KEYS - set(raw))
    if missing:
        raise AuthorizationRefused(
            "AUTHORIZATION_RECORD_INVALID",
            f"{source}: missing fields {missing}",
        )
    ref = raw["authorization_ref"]
    attested_by = raw["attested_by"]
    if not isinstance(ref, str) or not ref.strip():
        raise AuthorizationRefused(
            "AUTHORIZATION_RECORD_INVALID",
            f"{source}: authorization_ref must be a non-empty string",
        )
    if not isinstance(attested_by, str) or not attested_by.strip():
        raise AuthorizationRefused(
            "AUTHORIZATION_RECORD_INVALID",
            f"{source}: attested_by must be a non-empty string",
        )
    attested_at = raw["attested_at"]
    if not isinstance(attested_at, str):
        raise AuthorizationRefused(
            "AUTHORIZATION_RECORD_INVALID",
            f"{source}: attested_at must be an ISO-8601 datetime string",
        )
    try:
        parsed_at = dt.datetime.fromisoformat(attested_at)
    except ValueError as exc:
        raise AuthorizationRefused(
            "AUTHORIZATION_RECORD_INVALID",
            f"{source}: attested_at {attested_at!r} is not ISO-8601",
        ) from exc
    if parsed_at.tzinfo is None:
        raise AuthorizationRefused(
            "AUTHORIZATION_RECORD_INVALID",
            f"{source}: attested_at must carry a timezone",
        )
    scope_raw = raw["scope"]
    if not isinstance(scope_raw, dict):
        raise AuthorizationRefused(
            "AUTHORIZATION_RECORD_INVALID",
            f"{source}: scope must be a JSON object",
        )
    scope_unknown = sorted(str(key) for key in set(scope_raw) - _SCOPE_KEYS)
    if scope_unknown:
        raise AuthorizationRefused(
            "AUTHORIZATION_RECORD_INVALID",
            f"{source}: unknown scope keys {scope_unknown} — known keys are {sorted(_SCOPE_KEYS)}",
        )
    scope_missing = sorted(_SCOPE_KEYS - set(scope_raw))
    if scope_missing:
        raise AuthorizationRefused(
            "AUTHORIZATION_RECORD_INVALID",
            f"{source}: scope missing fields {scope_missing}",
        )
    scope_symbols = scope_raw["symbols"]
    if not isinstance(scope_symbols, list) or not scope_symbols or not all(
        isinstance(symbol, str) and symbol.strip() for symbol in scope_symbols
    ):
        raise AuthorizationRefused(
            "AUTHORIZATION_RECORD_INVALID",
            f"{source}: scope.symbols must be a non-empty list of strings",
        )
    scope_start = _record_date(scope_raw["start"], "scope.start", source)
    scope_end = _record_date(scope_raw["end"], "scope.end", source)
    if scope_start > scope_end:
        raise AuthorizationRefused(
            "AUTHORIZATION_RECORD_INVALID",
            f"{source}: scope.start {scope_start.isoformat()} is after scope.end "
            f"{scope_end.isoformat()}",
        )
    scope_budget = scope_raw["budget"]
    if isinstance(scope_budget, bool) or not isinstance(scope_budget, int):
        raise AuthorizationRefused(
            "AUTHORIZATION_RECORD_INVALID",
            f"{source}: scope.budget must be an integer",
        )
    if not 1 <= scope_budget <= UPDATE_BUDGET_CAP:
        raise AuthorizationRefused(
            "AUTHORIZATION_RECORD_INVALID",
            f"{source}: scope.budget {scope_budget} is outside the structural "
            f"update cap 1..{UPDATE_BUDGET_CAP} — a larger current-window "
            "budget is a separate authorization requiring a code change",
        )
    return AuthorizationRecord(
        authorization_ref=ref,
        attested_by=attested_by,
        attested_at=parsed_at,
        scope=AuthorizationScope(
            symbols=frozenset(scope_symbols),
            start=scope_start,
            end=scope_end,
            budget=scope_budget,
        ),
        source=source,
    )


def _record_date(value: Any, field: str, source: str) -> dt.date:
    if isinstance(value, str):
        try:
            return dt.date.fromisoformat(value.strip())
        except ValueError as exc:
            raise AuthorizationRefused(
                "AUTHORIZATION_RECORD_INVALID",
                f"{source}: {field} {value!r} is not YYYY-MM-DD",
            ) from exc
    raise AuthorizationRefused(
        "AUTHORIZATION_RECORD_INVALID",
        f"{source}: {field} must be a YYYY-MM-DD string",
    )


def load_authorization_record(path: Path | str) -> AuthorizationRecord:
    """Read + parse one operator-written authorization record file.
    Missing/unreadable/unparsable files refuse as authorization
    refusals — a broken record never downgrades the run to probe."""
    record_path = Path(path)
    try:
        text = record_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise AuthorizationRefused(
            "AUTHORIZATION_RECORD_UNREADABLE",
            f"{record_path}: {exc}",
        ) from exc
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AuthorizationRefused(
            "AUTHORIZATION_RECORD_INVALID",
            f"{record_path} is not valid JSON: {exc}",
        ) from exc
    return parse_authorization_record(raw, source=str(record_path))


# -- configuration ------------------------------------------------------------------


@dataclass(frozen=True)
class UpdateConfig:
    """One incremental-update execution window's pinned inputs.

    Same universe pins as the collector (SPY+QQQ both, together);
    ``calendar_supply`` is the operator-supplied current supply from
    :func:`load_supply_from_config`; the window must sit inside that
    supply's coverage — outside coverage there is NO calendar answer and
    the run refuses rather than assuming sessions. ``request_budget`` is
    capped at :data:`UPDATE_BUDGET_CAP` (6): raising is structurally
    refused — a bigger current-window budget is a separate authorization."""

    symbols: tuple[str, ...]
    start: dt.date
    end: dt.date
    output_dir: Path
    calendar_supply: CalendarSupply
    transport: str = TRANSPORT_PROBE
    request_budget: int = UPDATE_DEFAULT_BUDGET
    window_source: str = WINDOW_SOURCE_EXPLICIT
    authorization_record: AuthorizationRecord | None = None

    def __post_init__(self) -> None:
        if set(self.symbols) != AUTHORIZED_UNIVERSE or len(self.symbols) != 2:
            raise UpdateError(
                "UNIVERSE_MISMATCH",
                "both SPY and QQQ are required together for the update "
                f"universe, got {sorted(set(self.symbols))}",
            )
        if not all(isinstance(s, str) and _SYMBOL_SEGMENT_RE.match(s) for s in self.symbols):
            raise UpdateError("SYMBOL_SEGMENT_UNSAFE", "symbols must be [A-Z]{1,5}")
        object.__setattr__(
            self,
            "symbols",
            tuple(s for s in AUTHORIZED_SYMBOL_ORDER if s in set(self.symbols)),
        )
        if (
            isinstance(self.start, dt.datetime)
            or isinstance(self.end, dt.datetime)
            or not isinstance(self.start, dt.date)
            or not isinstance(self.end, dt.date)
        ):
            raise UpdateError("BAD_WINDOW", "start/end must be dates")
        if self.start > self.end:
            raise UpdateError("BAD_WINDOW", f"{self.start} > {self.end}")
        if not isinstance(self.calendar_supply, CalendarSupply):
            raise UpdateError(
                "BAD_CALENDAR_SUPPLY",
                "calendar_supply must be a CalendarSupply built by "
                "build_current_supply / load_supply_from_config",
            )
        if not (self.calendar_supply.covers(self.start) and self.calendar_supply.covers(self.end)):
            raise UpdateError(
                "OUTSIDE_CALENDAR_COVERAGE",
                f"window [{self.start.isoformat()}, {self.end.isoformat()}] is "
                f"outside the current calendar supply coverage "
                f"[{self.calendar_supply.valid_from.isoformat()}, "
                f"{self.calendar_supply.valid_until.isoformat()}] "
                f"(version={self.calendar_supply.version!r}) — extend the "
                "operator-maintained calendar config first",
            )
        if self.transport not in (TRANSPORT_PROBE, TRANSPORT_LIVE):
            raise UpdateError(
                "BAD_TRANSPORT", f"transport must be probe|live, got {self.transport!r}"
            )
        if (
            isinstance(self.request_budget, bool)
            or not isinstance(self.request_budget, int)
            or not 1 <= self.request_budget <= UPDATE_BUDGET_CAP
        ):
            raise UpdateError(
                "BAD_BUDGET",
                f"request_budget must be 1..{UPDATE_BUDGET_CAP}, got "
                f"{self.request_budget} — the current-window budget is "
                "structurally capped; raising it is a separate authorization",
            )
        if self.window_source not in (WINDOW_SOURCE_EXPLICIT, WINDOW_SOURCE_DEFAULT):
            raise UpdateError(
                "BAD_WINDOW_SOURCE",
                f"window_source must be {WINDOW_SOURCE_EXPLICIT!r} or "
                f"{WINDOW_SOURCE_DEFAULT!r}, got {self.window_source!r}",
            )


@dataclass(frozen=True)
class UpdateReport:
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
    """The resolved transport + what authorized it (credential NAMES
    only — values are never read into this object)."""

    transport: str
    label: str
    credential_env_visible: tuple[str, ...]
    authorization_ref: str | None


def resolve_update_authorization(
    transport: str,
    *,
    symbols: tuple[str, ...],
    start: dt.date,
    end: dt.date,
    budget: int,
    environ: Mapping[str, str],
    authorization_record: AuthorizationRecord | None,
) -> TransportAuthorization:
    """Fail-closed current-data transport gate. ``live`` runs only when
    BOTH (a) the operator pre-signed the environment
    (``CURRENT_DATA_AUTHORIZED=SIGNED`` — this entry never sets it, and
    the variable's actual value is never echoed on refusal) AND (b) an
    authorization record whose scope matches the invocation exactly.
    The H1 2017-2025 authorization does NOT extend here; neither gate
    substitutes for the other."""
    if transport == TRANSPORT_PROBE:
        return TransportAuthorization(
            TRANSPORT_PROBE, TRANSPORT_LABEL_PROBE_INCREMENTAL, (), None
        )
    token = environ.get(AUTH_ENV_VAR)
    if token != AUTH_SIGNATURE_VALUE:
        raise AuthorizationRefused(
            "LIVE_AUTHORIZATION_REFUSED",
            f"environment {AUTH_ENV_VAR} must equal {AUTH_SIGNATURE_VALUE!r} "
            "(set by the operator after authorizing the current-window "
            "scope — this entry never sets it itself, and the variable's "
            "actual value is never echoed)",
        )
    if authorization_record is None:
        raise AuthorizationRefused(
            "LIVE_AUTHORIZATION_RECORD_REQUIRED",
            "--authorization-record <path> (operator-written JSON with "
            "authorization_ref, attested_by, attested_at and "
            "scope{symbols,start,end,budget}) is required for live "
            "current-window updates — the H1 2017-2025 authorization "
            "does NOT extend to current dates",
        )
    scope = authorization_record.scope
    mismatches: list[str] = []
    if scope.symbols != set(symbols):
        mismatches.append(
            f"symbols: record {sorted(scope.symbols)} != requested {sorted(set(symbols))}"
        )
    if scope.start != start:
        mismatches.append(
            f"start: record {scope.start.isoformat()} != requested {start.isoformat()}"
        )
    if scope.end != end:
        mismatches.append(
            f"end: record {scope.end.isoformat()} != requested {end.isoformat()}"
        )
    if scope.budget < budget:
        mismatches.append(
            f"budget: record authorizes {scope.budget} < requested {budget}"
        )
    if mismatches:
        raise AuthorizationRefused(
            "AUTHORIZATION_SCOPE_MISMATCH",
            "authorization record scope does not match this invocation: "
            + "; ".join(mismatches),
        )
    visible = tuple(name for name in CREDENTIAL_ENV_NAMES if environ.get(name) is not None)
    if len(visible) != len(CREDENTIAL_ENV_NAMES):
        missing = sorted(set(CREDENTIAL_ENV_NAMES) - set(visible))
        raise BlockedEnv(
            "LIVE_BLOCKED_ENV",
            "market-data credentials are not visible in the environment "
            f"(missing names: {', '.join(missing)}); values are never read "
            "at this gate",
        )
    return TransportAuthorization(
        TRANSPORT_LIVE, LIVE_TRANSPORT_LABEL, visible, authorization_record.authorization_ref
    )


# -- default window ------------------------------------------------------------------


def resolve_default_window(
    calendar: VersionedMarketCalendar, *, now_et: dt.datetime | None = None
) -> tuple[dt.date, dt.date]:
    """The default update window: end = yesterday ET, start = the
    ``DEFAULT_SESSIONS_LOOKBACK``-th session back per the CURRENT supply
    (sessions are supplied data; weekends/holidays simply do not count).

    Fail-closed when the calendar supply is stale: an ``end`` outside the
    supply's coverage refuses with ``CALENDAR_SUPPLY_STALE`` (extend
    configs/current_calendar.yaml from the licensed source), and a
    coverage window too short for the lookback refuses with
    ``INSUFFICIENT_SESSION_HISTORY``."""
    moment = now_et if now_et is not None else dt.datetime.now(ET)
    if not isinstance(moment, dt.datetime) or moment.tzinfo is None:
        raise UpdateError("BAD_CLOCK", "now_et must be a timezone-aware datetime")
    end = moment.astimezone(ET).date() - dt.timedelta(days=1)
    supply = calendar.supply
    if not supply.covers(end):
        raise UpdateError(
            "CALENDAR_SUPPLY_STALE",
            f"yesterday ET {end.isoformat()} is outside the current calendar "
            f"supply coverage [{supply.valid_from.isoformat()}, "
            f"{supply.valid_until.isoformat()}] (version={supply.version!r}) — "
            "the operator must extend/replace the calendar config from the "
            "licensed source before updates can run",
        )
    sessions: list[dt.date] = []
    day = end
    while day >= supply.valid_from and len(sessions) < DEFAULT_SESSIONS_LOOKBACK:
        if calendar.is_trading_day(day):
            sessions.append(day)
        day -= dt.timedelta(days=1)
    if len(sessions) < DEFAULT_SESSIONS_LOOKBACK:
        raise UpdateError(
            "INSUFFICIENT_SESSION_HISTORY",
            f"the current calendar supply holds only {len(sessions)} sessions "
            f"before {end.isoformat()} within its coverage "
            f"[{supply.valid_from.isoformat()}, {supply.valid_until.isoformat()}] — "
            f"{DEFAULT_SESSIONS_LOOKBACK} required for the default window",
        )
    return sessions[-1], end


# -- namespace paths --------------------------------------------------------------------


def _bars_path(output_dir: Path, symbol: str) -> Path:
    return output_dir / NAMESPACE_DIRNAME / symbol / BARS_FILE_NAME


def _manifest_path(output_dir: Path) -> Path:
    return output_dir / NAMESPACE_DIRNAME / UPDATE_MANIFEST_NAME


def _partial_audit_path(output_dir: Path) -> Path:
    return output_dir / NAMESPACE_DIRNAME / UPDATE_PARTIAL_AUDIT_NAME


def _write_json_doc(path: Path, doc: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(doc, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def _require_clean_target(config: UpdateConfig) -> None:
    """A current-window update never merges into an existing snapshot
    directory: the target must be clean. An existing collector manifest,
    an existing update manifest, or any existing bars file for the
    requested symbols refuses the run (incremental merge is future work,
    documented — not silently attempted)."""
    namespace = Path(config.output_dir) / NAMESPACE_DIRNAME
    offenders = [
        namespace / MANIFEST_NAME,
        namespace / UPDATE_MANIFEST_NAME,
        *(namespace / symbol / BARS_FILE_NAME for symbol in config.symbols),
    ]
    present = [path for path in offenders if path.exists()]
    if present:
        raise UpdateError(
            "UPDATE_TARGET_NOT_CLEAN",
            "refusing to write into an existing snapshot directory — "
            f"incremental merge is future work and is never silent; already "
            f"present: {[str(p) for p in present]}",
        )


def _require_certifiable_boundary(calendar: VersionedMarketCalendar, config: UpdateConfig) -> None:
    """Pre-flight the availability MODEL for the window's final session:
    its next-open answer must be certifiable INSIDE the supply, otherwise
    the last row's assumed availability would abort mid-run — refuse
    before any request spends the budget."""
    sessions = calendar.expected_sessions(config.start, config.end)
    if not sessions:
        raise UpdateError(
            "WINDOW_HAS_NO_SESSIONS",
            f"[{config.start.isoformat()}, {config.end.isoformat()}] contains "
            "no trading sessions per the current calendar supply — nothing "
            "to update, refusing instead of sending budget on an empty window",
        )
    last_close = calendar.session(sessions[-1]).close_utc()
    if last_close is None:  # pragma: no cover — sessions[-1] is a trading day
        raise UpdateError(
            "CALENDAR_SUPPLY_BOUNDARY",
            f"{sessions[-1].isoformat()} has no certifiable session close",
        )
    try:
        calendar.session_open_after(last_close)
    except CalendarError as exc:
        raise UpdateError(
            "CALENDAR_SUPPLY_BOUNDARY",
            f"the window's final session {sessions[-1].isoformat()} has no "
            f"certifiable next-session open inside the current supply "
            f"(version={calendar.supply.version!r}): {exc} — extend the "
            "calendar config before updating through the supply boundary",
        ) from exc


# -- disclosure documents -------------------------------------------------------------
#: the placeholder marker whose presence in the supply's stated source means
#: the calendar license is still unverified
_LICENSE_PLACEHOLDER = "LICENSE_UNVERIFIED"


def _license_doc(supply: CalendarSupply) -> dict[str, Any]:
    stated = _LICENSE_PLACEHOLDER in supply.source
    return {
        "status": "LICENSE_UNVERIFIED" if stated else "OPERATOR_STATED",
        "calendar_license_note": supply.source,
        "calendar_supply_license_stated_by_operator": True,
        "market_data_license": (
            "current-window market data is a SEPARATE authorization from "
            "the H1 2017-2025 window (which never extends here); live runs "
            "require the operator's authorization record matching the "
            "invocation scope exactly"
        ),
    }


def _admission_doc() -> dict[str, Any]:
    return {
        "status": "NOT_RESEARCH_ADMITTED",
        "until": (
            "the account owner authorizes the current-window scope and "
            "confirms the calendar/data licenses; until then these files "
            "must not enter formal research"
        ),
        "corporate_actions": "NONE_COLLECTED",
        "raw_only_disclosure": (
            "raw prices without corporate actions: no total-return, "
            "long-horizon comparability, or unbiased-alpha claims are "
            "permitted from this data"
        ),
        "s8_forward_ledger": "EXCLUDED",
        "merge_note": (
            "incremental merge into an existing snapshot is future work; "
            "this entry writes only into a clean target"
        ),
    }


def _window_doc(config: UpdateConfig) -> dict[str, Any]:
    supply = config.calendar_supply
    return {
        "start": config.start.isoformat(),
        "end": config.end.isoformat(),
        "semantics": "ET session dates (HistoricalWindow)",
        "source": config.window_source,
        "supply_coverage": {
            "valid_from": supply.valid_from.isoformat(),
            "valid_until": supply.valid_until.isoformat(),
            "within": True,
        },
    }


def _authorization_doc(
    config: UpdateConfig, auth: TransportAuthorization
) -> dict[str, Any]:
    record = config.authorization_record
    doc: dict[str, Any] = {
        "env_signature_name": AUTH_ENV_VAR,
        "env_signature_present": auth.transport == TRANSPORT_LIVE,
        "credential_env_visible": list(auth.credential_env_visible),
        "record_ref": auth.authorization_ref,
    }
    if auth.transport == TRANSPORT_LIVE and record is not None:
        doc["attested_by"] = record.attested_by
        doc["attested_at"] = record.attested_at.isoformat()
        doc["scope"] = {
            "symbols": sorted(record.scope.symbols),
            "start": record.scope.start.isoformat(),
            "end": record.scope.end.isoformat(),
            "budget": record.scope.budget,
        }
    return doc


# -- the update run -----------------------------------------------------------------------


def run_update(
    config: UpdateConfig,
    *,
    environ: Mapping[str, str] | None = None,
    probe_opener: FakeAlpacaProbeTransport | None = None,
) -> UpdateReport:
    """Run one incremental current-window update. Configuration and
    authorization refusals raise :class:`UpdateError` subclasses BEFORE
    any disk write; mid-run refusals (budget, HTTP status, contract)
    return an ABORTED report with the partial-audit dump written and NO
    manifest (manifest existence == success marker)."""
    environ = os.environ if environ is None else environ
    auth = resolve_update_authorization(
        config.transport,
        symbols=config.symbols,
        start=config.start,
        end=config.end,
        budget=config.request_budget,
        environ=environ,
        authorization_record=config.authorization_record,
    )
    supply = config.calendar_supply
    supply_hash = frozen_supply_hash(supply)
    calendar = VersionedMarketCalendar.from_supply(supply)
    _require_certifiable_boundary(calendar, config)
    _require_clean_target(config)
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
        window=HistoricalWindow(
            start=supply.valid_from,
            end=supply.valid_until,
            label=f"current-calendar-supply-{supply.version}",
        ),
        max_requests=config.request_budget,
    )
    audit = _base_audit_doc(config, auth, supply, supply_hash)
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
        source = (
            TRANSPORT_LABEL_PROBE_INCREMENTAL
            if config.transport == TRANSPORT_PROBE
            else SOURCE_LIVE_INCREMENTAL
        )
        rows_by_symbol = {
            result.symbol: tuple(
                _to_contract_row(
                    row,
                    symbol=result.symbol,
                    calendar=calendar,
                    source=source,
                    received_at_utc=received_at,
                )
                for row in result.rows
            )
            for result in fetched
        }
    except (HistoricalRequestRefused, TransportError, HistoricalDataError, CalendarError) as exc:
        return _abort(config, audit, client, opener, exc)
    return _commit(
        config, auth, supply, supply_hash, calendar, client,
        output_dir, fetched, rows_by_symbol, received_at,
    )


# -- audit / manifest assembly ---------------------------------------------------------------


def _base_audit_doc(
    config: UpdateConfig,
    auth: TransportAuthorization,
    supply: CalendarSupply,
    supply_hash: str,
) -> dict[str, Any]:
    return {
        "schema": AUDIT_SCHEMA,
        "entry": "incremental_update",
        "status": "ABORTED",
        "reason": None,
        "detail": None,
        "transport": {"mode": config.transport, "label": auth.label},
        "calendar_supply": {
            "version": supply.version,
            "hash": supply_hash,
            "license_note": supply.source,
            "valid_from": supply.valid_from.isoformat(),
            "valid_until": supply.valid_until.isoformat(),
        },
        "window": _window_doc(config),
        "budget": {
            "cap": config.request_budget,
            "structural_cap": UPDATE_BUDGET_CAP,
            "authorization_budget": (
                config.authorization_record.scope.budget
                if config.authorization_record is not None
                else None
            ),
            "spent": 0,
            "remaining": config.request_budget,
        },
        "symbols": {},
        "request_urls_seen": [],
        "request_urls_note": (
            "URL-level receipts exist for the probe transport (fixture); "
            "live partial receipts belong to the separately authorized "
            "current-window scope"
        ),
        "authorization": _authorization_doc(config, auth),
        "license": _license_doc(supply),
        "pit": _pit_doc(),
        "admission": _admission_doc(),
    }


def _abort(
    config: UpdateConfig,
    audit: dict[str, Any],
    client: HistoricalBarsClient,
    opener: FakeAlpacaProbeTransport | None,
    exc: Exception,
) -> UpdateReport:
    audit["reason"] = str(getattr(exc, "reason", "") or type(exc).__name__)
    audit["detail"] = str(exc)
    audit["budget"]["spent"] = client.request_count
    audit["budget"]["remaining"] = max(0, config.request_budget - client.request_count)
    if opener is not None:
        audit["request_urls_seen"] = list(opener.requests)
    for state in audit["symbols"].values():
        if state.get("status") == "IN_FLIGHT":
            state["status"] = "REFUSED"
    path = _partial_audit_path(Path(config.output_dir))
    _write_json_doc(path, audit)
    return UpdateReport(
        status="ABORTED",
        manifest=None,
        partial_audit=audit,
        manifest_path=None,
        partial_audit_path=path,
        bars_paths=(),
    )


def _commit(
    config: UpdateConfig,
    auth: TransportAuthorization,
    supply: CalendarSupply,
    supply_hash: str,
    calendar: VersionedMarketCalendar,
    client: HistoricalBarsClient,
    output_dir: Path,
    fetched: list[HistoricalFetchResult],
    rows_by_symbol: dict[str, tuple[dict[str, Any], ...]],
    received_at: dt.datetime,
) -> UpdateReport:
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
        "entry": "incremental_update",
        "status": "COLLECTED",
        "namespace": NAMESPACE_DIRNAME,
        "window": _window_doc(config),
        "transport": {
            "mode": config.transport,
            "label": (
                TRANSPORT_LABEL_PROBE_INCREMENTAL
                if config.transport == TRANSPORT_PROBE
                else auth.label
            ),
            "real_network_used": config.transport == TRANSPORT_LIVE,
        },
        "calendar_supply": {
            "version": supply.version,
            "hash": supply_hash,
            "license_note": supply.source,
            "valid_from": supply.valid_from.isoformat(),
            "valid_until": supply.valid_until.isoformat(),
        },
        "budget": {
            "cap": config.request_budget,
            "structural_cap": UPDATE_BUDGET_CAP,
            "authorization_budget": (
                config.authorization_record.scope.budget
                if config.authorization_record is not None
                else None
            ),
            "spent": client.request_count,
            "remaining": config.request_budget - client.request_count,
        },
        "received_at_utc": received_at.isoformat(),
        "received_at_is_probe_fixture_fact": config.transport == TRANSPORT_PROBE,
        "authorization": _authorization_doc(config, auth),
        "symbols": symbols_doc,
        "license": _license_doc(supply),
        "pit": _pit_doc(),
        "admission": _admission_doc(),
    }
    manifest_path = _manifest_path(output_dir)
    _write_json_doc(manifest_path, manifest)
    return UpdateReport(
        status="COLLECTED",
        manifest=manifest,
        partial_audit=None,
        manifest_path=manifest_path,
        partial_audit_path=None,
        bars_paths=tuple(bars_paths),
    )


def _write_bars_file(path: Path, rows: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    payload = "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload.encode("utf-8"))
    data = path.read_bytes()  # recomputed from disk — never trusted upstream
    return {"bytes": len(data), "sha256": sha256_hex(data)}
