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
entry produces is ``NOT_RESEARCH_ADMITTED`` — PIT level ``ASSUMED`` (the
next-open MODEL assumption; an HTTP 200 never proves point-in-time
publication), raw prices only (no corporate actions — no total-return or
long-horizon comparability claims). This entry collects; it never admits.

Authorization-facts binding (V0.3 T1): a live run additionally requires
the operator's signed authorization FACTS (``LicenseFacts`` /
``AdmissionFacts``, parsed by :func:`parse_authorization_record` from the
operator-written record file). The env signature is a necessary run
switch and NEVER a substitute: live without supplied facts refuses with
``AUTHORIZATION_FACTS_MISSING`` instead of emitting unverifiable labels.
When facts are bound, the license doc carries
``LICENSE_VERIFIED_PER_OPERATOR_ATTESTATION`` (operator attestation,
mechanically copied — NOT an independent verification) plus the
authorization_ref / scope echo / attested_by / attested_at fields; the
admission doc carries the same binding but its status stays
``NOT_RESEARCH_ADMITTED``. Probe runs never bind facts and stay
byte-stable unsigned.
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
    FEED,
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
    "AUTHORIZATION_FACTS_INCOMPATIBLE",
    "AUTHORIZATION_FACTS_MISSING",
    "AUTHORIZATION_SCOPE_MISMATCH",
    "AdmissionFacts",
    "AuthorizationFactsRefused",
    "AuthorizationRecord",
    "AuthorizationRefused",
    "AuthorizedScope",
    "BARS_FILE_NAME",
    "BUDGET_CAP",
    "BlockedEnv",
    "CollectionConfig",
    "CollectionError",
    "CollectionReport",
    "LICENSE_STATUS_ATTESTED",
    "LICENSE_WINDOW",
    "LicenseFacts",
    "LIVE_TRANSPORT_LABEL",
    "MANIFEST_NAME",
    "NAMESPACE_DIRNAME",
    "PARTIAL_AUDIT_NAME",
    "TRANSPORT_LIVE",
    "TRANSPORT_PROBE",
    "dedupe_bars_rows",
    "parse_authorization_record",
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

#: honest license label for a live run bound to the operator's signed
#: authorization record: it records an OPERATOR ATTESTATION, which is
#: explicitly NOT an independent verification by this pipeline
LICENSE_STATUS_ATTESTED = "LICENSE_VERIFIED_PER_OPERATOR_ATTESTATION"

#: AuthorizationFactsRefused reasons
AUTHORIZATION_FACTS_MISSING = "AUTHORIZATION_FACTS_MISSING"
AUTHORIZATION_SCOPE_MISMATCH = "AUTHORIZATION_SCOPE_MISMATCH"
AUTHORIZATION_FACTS_INCOMPATIBLE = "AUTHORIZATION_FACTS_INCOMPATIBLE"

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


class AuthorizationFactsRefused(CollectionError):
    """Authorization-facts refusals (fail-closed, before any disk write):

    - ``AUTHORIZATION_FACTS_MISSING``: live transport signed but no
      operator-supplied facts were bound (the env var alone never
      substitutes for a signature);
    - ``AUTHORIZATION_SCOPE_MISMATCH``: supplied facts' scope does not
      match the frozen authorized scope;
    - ``AUTHORIZATION_FACTS_INCOMPATIBLE``: facts supplied to a probe run
      (probe artifacts are FAKE_TRANSPORT validation data and never bind
      attestation)."""


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


# -- operator authorization facts (V0.3 T1) -------------------------------------
#
# The ``SIGNED`` env var is a necessary run switch, never a substitute for
# a signature: a live run additionally requires the operator's signed
# authorization FACTS, and those facts — not hand-edited labels — are what
# the new snapshot's license/admission docs carry.


@dataclass(frozen=True)
class AuthorizedScope:
    """The scope a signed authorization covers, echoed for mechanical
    validation against the frozen window / universe / transport. The
    symbol order is canonicalized (SPY, QQQ) so scope docs stay
    byte-deterministic regardless of how the record listed them."""

    start: dt.date
    end: dt.date
    symbols: tuple[str, ...]
    feed: str
    timeframe: str

    def __post_init__(self) -> None:
        if not isinstance(self.start, dt.date) or not isinstance(self.end, dt.date):
            raise CollectionError(
                "BAD_SCOPE", "scope start/end must be dates")
        if self.start > self.end:
            raise CollectionError("BAD_SCOPE", f"{self.start} > {self.end}")
        if (
            not isinstance(self.symbols, tuple)
            or len(self.symbols) != len(AUTHORIZED_UNIVERSE)
            or len(set(self.symbols)) != len(self.symbols)
            or not all(
                isinstance(s, str) and _SYMBOL_SEGMENT_RE.match(s)
                for s in self.symbols
            )
        ):
            raise CollectionError(
                "BAD_SCOPE",
                "scope symbols must be two distinct [A-Z]{1,5} symbols, "
                f"got {self.symbols!r}",
            )
        object.__setattr__(
            self,
            "symbols",
            tuple(s for s in AUTHORIZED_SYMBOL_ORDER if s in set(self.symbols)),
        )
        if not isinstance(self.feed, str) or not self.feed.strip():
            raise CollectionError("BAD_SCOPE", "scope feed must be a non-empty string")
        if not isinstance(self.timeframe, str) or not self.timeframe.strip():
            raise CollectionError(
                "BAD_SCOPE", "scope timeframe must be a non-empty string")


@dataclass(frozen=True)
class LicenseFacts:
    """Operator-supplied license authorization FACTS, copied mechanically
    from a signed record (never self-issued by this pipeline). The emitted
    status ``LICENSE_VERIFIED_PER_OPERATOR_ATTESTATION`` says exactly what
    this is: an operator attestation, NOT an independent verification."""

    authorization_ref: str
    attested_by: str
    attested_at: str
    scope: AuthorizedScope
    calendar_license_note: str

    def __post_init__(self) -> None:
        if not isinstance(self.scope, AuthorizedScope):
            raise CollectionError(
                "BAD_AUTHORIZATION_FACTS",
                "license facts scope must be an AuthorizedScope")
        for field_name in (
            "authorization_ref", "attested_by", "attested_at",
            "calendar_license_note",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise CollectionError(
                    "BAD_AUTHORIZATION_FACTS",
                    f"license facts {field_name} must be a non-empty string")


@dataclass(frozen=True)
class AdmissionFacts:
    """Operator-supplied admission-side attestation binding. It NEVER
    changes the emitted admission status (this entry never admits — PIT
    stays ASSUMED); it records WHO attested the authorization and whether
    the signed record explicitly permits restricted-research USE under
    the existing protocol (recorded as ``restricted_research_permitted``)."""

    authorization_ref: str
    attested_by: str
    attested_at: str
    scope: AuthorizedScope
    restricted_research_permitted: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.scope, AuthorizedScope):
            raise CollectionError(
                "BAD_AUTHORIZATION_FACTS",
                "admission facts scope must be an AuthorizedScope")
        for field_name in ("authorization_ref", "attested_by", "attested_at"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise CollectionError(
                    "BAD_AUTHORIZATION_FACTS",
                    f"admission facts {field_name} must be a non-empty string")
        if not isinstance(self.restricted_research_permitted, bool):
            raise CollectionError(
                "BAD_AUTHORIZATION_FACTS",
                "admission facts restricted_research_permitted must be boolean")


@dataclass(frozen=True)
class AuthorizationRecord:
    """One operator-written authorization record, parsed into the
    license-side and admission-side bindings for a run."""

    license: LicenseFacts
    admission: AdmissionFacts


_RECORD_KEYS = frozenset({
    "authorization_ref", "attested_by", "attested_at",
    "calendar_license_note", "scope", "restricted_research_permitted",
})
_SCOPE_KEYS = frozenset({"start", "end", "symbols", "feed", "timeframe"})


def _require_record_str(
    payload: Mapping[str, Any], key: str, *, context: str
) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise CollectionError(
            "AUTHORIZATION_RECORD_INVALID",
            f"{context} key {key!r} must be a non-empty string")
    return value.strip()


def parse_authorization_record(payload: Mapping[str, Any]) -> AuthorizationRecord:
    """Validate + shape an operator-written authorization record (a JSON
    mapping the OPERATOR writes; this pipeline never authors one). Unknown
    keys are refused — a typo'd intent field must never be silently
    dropped. The scope echo is shape-validated here and validated AGAINST
    the frozen authorized scope at binding time."""
    if not isinstance(payload, Mapping):
        raise CollectionError(
            "AUTHORIZATION_RECORD_INVALID",
            "authorization record must be a JSON mapping")
    unknown = sorted(set(payload) - _RECORD_KEYS)
    if unknown:
        raise CollectionError(
            "AUTHORIZATION_RECORD_INVALID",
            f"authorization record has unknown keys {unknown}; expected "
            f"{sorted(_RECORD_KEYS)}")
    scope_payload = payload.get("scope")
    if not isinstance(scope_payload, Mapping):
        raise CollectionError(
            "AUTHORIZATION_RECORD_INVALID",
            "authorization record scope must be a mapping with "
            "start/end/symbols/feed/timeframe")
    unknown_scope = sorted(set(scope_payload) - _SCOPE_KEYS)
    if unknown_scope:
        raise CollectionError(
            "AUTHORIZATION_RECORD_INVALID",
            f"authorization record scope has unknown keys {unknown_scope}; "
            f"expected {sorted(_SCOPE_KEYS)}")
    permitted = payload.get("restricted_research_permitted", False)
    if not isinstance(permitted, bool):
        raise CollectionError(
            "AUTHORIZATION_RECORD_INVALID",
            "authorization record restricted_research_permitted must be "
            "boolean")
    symbols_raw = scope_payload.get("symbols")
    if (
        not isinstance(symbols_raw, (list, tuple))
        or len(symbols_raw) != len(AUTHORIZED_UNIVERSE)
        or not all(isinstance(s, str) for s in symbols_raw)
    ):
        raise CollectionError(
            "AUTHORIZATION_RECORD_INVALID",
            "authorization record scope symbols must be a two-symbol list "
            f"of strings, got {symbols_raw!r}")
    try:
        start = dt.date.fromisoformat(
            _require_record_str(scope_payload, "start",
                                context="authorization record scope"))
        end = dt.date.fromisoformat(
            _require_record_str(scope_payload, "end",
                                context="authorization record scope"))
        scope = AuthorizedScope(
            start=start,
            end=end,
            symbols=tuple(symbols_raw),
            feed=_require_record_str(scope_payload, "feed",
                                     context="authorization record scope"),
            timeframe=_require_record_str(scope_payload, "timeframe",
                                          context="authorization record scope"),
        )
    except CollectionError as exc:
        raise CollectionError(
            "AUTHORIZATION_RECORD_INVALID",
            f"authorization record scope invalid: {exc}") from exc
    except ValueError as exc:
        raise CollectionError(
            "AUTHORIZATION_RECORD_INVALID",
            f"authorization record scope dates invalid: {exc}") from exc
    license_facts = LicenseFacts(
        authorization_ref=_require_record_str(payload, "authorization_ref",
                                              context="authorization record"),
        attested_by=_require_record_str(payload, "attested_by",
                                        context="authorization record"),
        attested_at=_require_record_str(payload, "attested_at",
                                        context="authorization record"),
        scope=scope,
        calendar_license_note=_require_record_str(
            payload, "calendar_license_note", context="authorization record"),
    )
    admission_facts = AdmissionFacts(
        authorization_ref=license_facts.authorization_ref,
        attested_by=license_facts.attested_by,
        attested_at=license_facts.attested_at,
        scope=scope,
        restricted_research_permitted=permitted,
    )
    return AuthorizationRecord(license=license_facts, admission=admission_facts)


def _validate_facts_scope(scope: AuthorizedScope, *, context: str) -> None:
    """The record's scope must cover EXACTLY the frozen authorized scope
    (window equality — scope shortening needs its own signed approval,
    universe equality, and the authorized feed/timeframe)."""
    if (scope.start, scope.end) != (LICENSE_WINDOW.start, LICENSE_WINDOW.end):
        raise AuthorizationFactsRefused(
            AUTHORIZATION_SCOPE_MISMATCH,
            f"{context}: authorized window "
            f"[{scope.start.isoformat()}, {scope.end.isoformat()}] != the "
            f"frozen license window [{LICENSE_WINDOW.start.isoformat()}, "
            f"{LICENSE_WINDOW.end.isoformat()}] — a shortened scope needs "
            "its own signed approval")
    if (
        set(scope.symbols) != AUTHORIZED_UNIVERSE
        or len(scope.symbols) != len(AUTHORIZED_UNIVERSE)
    ):
        raise AuthorizationFactsRefused(
            AUTHORIZATION_SCOPE_MISMATCH,
            f"{context}: authorized symbols {sorted(scope.symbols)} != "
            f"{sorted(AUTHORIZED_UNIVERSE)}")
    if scope.feed != FEED or scope.timeframe != TIMEFRAME:
        raise AuthorizationFactsRefused(
            AUTHORIZATION_SCOPE_MISMATCH,
            f"{context}: authorized feed/timeframe {scope.feed!r}/"
            f"{scope.timeframe!r} != {FEED!r}/{TIMEFRAME!r}")


@dataclass(frozen=True)
class _BoundFacts:
    """The authorization facts resolved for ONE run: both None on probe
    runs; license non-None (admission optional) on live runs."""

    license: LicenseFacts | None
    admission: AdmissionFacts | None


def _bind_authorization_facts(
    transport: str,
    *,
    license_facts: LicenseFacts | None,
    admission_facts: AdmissionFacts | None,
) -> _BoundFacts:
    """Resolve + validate the run's authorization facts. Probe runs never
    bind facts; live runs REQUIRE license facts (the env signature alone
    is not enough) whose scope matches the frozen authorized scope."""
    if transport == TRANSPORT_PROBE:
        if license_facts is not None or admission_facts is not None:
            raise AuthorizationFactsRefused(
                AUTHORIZATION_FACTS_INCOMPATIBLE,
                "probe transport never binds operator authorization facts "
                "(probe artifacts are FAKE_TRANSPORT validation data and "
                "must keep their unsigned labels); drop the authorization "
                "record for probe runs")
        return _BoundFacts(license=None, admission=None)
    if license_facts is None:
        raise AuthorizationFactsRefused(
            AUTHORIZATION_FACTS_MISSING,
            f"live transport with {AUTH_ENV_VAR}={AUTH_SIGNATURE_VALUE} "
            "still requires the operator's authorization FACTS (the env "
            "var is a necessary run switch and never a substitute for a "
            "signed record); pass --authorization-record")
    _validate_facts_scope(license_facts.scope, context="license facts")
    if admission_facts is not None:
        _validate_facts_scope(admission_facts.scope, context="admission facts")
    return _BoundFacts(license=license_facts, admission=admission_facts)


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


def _scope_doc(scope: AuthorizedScope) -> dict[str, Any]:
    """The authorized scope echo copied from the facts object (window /
    symbols / feed / timeframe) — mechanically, never free text."""
    return {
        "start": scope.start.isoformat(),
        "end": scope.end.isoformat(),
        "symbols": list(scope.symbols),
        "feed": scope.feed,
        "timeframe": scope.timeframe,
    }


def _license_doc(supplied: LicenseFacts | None = None) -> dict[str, Any]:
    """With no supplied facts (probe / unattested runs): the exact legacy
    unsigned doc, byte-stable. With supplied facts: the operator's
    attestation binding, copied mechanically — the status says
    attestation, never independent verification."""
    if supplied is None:
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
    return {
        "status": LICENSE_STATUS_ATTESTED,
        "calendar_supply_license": supplied.calendar_license_note,
        "market_data_license": (
            f"operator attestation {supplied.authorization_ref}: the "
            "account owner's signed authorization record is bound "
            "mechanically below — this is an operator attestation, NOT "
            "an independent verification by this pipeline"
        ),
        "authorization_ref": supplied.authorization_ref,
        "authorization_scope": _scope_doc(supplied.scope),
        "attested_by": supplied.attested_by,
        "attested_at": supplied.attested_at,
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


def _admission_doc(supplied: AdmissionFacts | None = None) -> dict[str, Any]:
    """With no supplied facts: the exact legacy restricted doc,
    byte-stable. With supplied facts: the same NOT_RESEARCH_ADMITTED
    status (an operator attestation never admits — PIT stays ASSUMED),
    plus the attestation binding and whether the signed record explicitly
    permits restricted-research use under the existing protocol."""
    if supplied is None:
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
    return {
        "status": "NOT_RESEARCH_ADMITTED",
        "until": (
            "full PIT verification (vendor per-day publication evidence): "
            "an operator license attestation does not admit raw ASSUMED-"
            "PIT prices into formal research"
        ),
        "corporate_actions": "NONE_COLLECTED",
        "raw_only_disclosure": (
            "raw prices without corporate actions: no total-return, "
            "long-horizon comparability, or unbiased-alpha claims are "
            "permitted from this data"
        ),
        "s8_forward_ledger": "EXCLUDED",
        "authorization_ref": supplied.authorization_ref,
        "authorization_scope": _scope_doc(supplied.scope),
        "license_status": LICENSE_STATUS_ATTESTED,
        "attested_by": supplied.attested_by,
        "attested_at": supplied.attested_at,
        "restricted_research_permitted": supplied.restricted_research_permitted,
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
    license_facts: LicenseFacts | None = None,
    admission_facts: AdmissionFacts | None = None,
) -> CollectionReport:
    """Run one collection window. Configuration/authorization refusals
    raise :class:`CollectionError` subclasses BEFORE any disk write;
    mid-run refusals (budget, HTTP status, contract) return an ABORTED
    report with the partial-audit dump written and NO manifest.

    Live transport additionally requires the operator's authorization
    facts (``license_facts`` — from the signed authorization record):
    the ``SIGNED`` env var alone refuses with AUTHORIZATION_FACTS_MISSING.
    Probe runs never bind facts and never emit verified labels."""
    environ = os.environ if environ is None else environ
    auth = resolve_transport_authorization(config.transport, environ=environ)
    facts = _bind_authorization_facts(
        config.transport,
        license_facts=license_facts,
        admission_facts=admission_facts,
    )
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
    audit = _base_audit_doc(config, auth, calendar, supply_hash, output_dir, facts)
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
        config, auth, calendar, client, output_dir, fetched, rows_by_symbol,
        received_at, facts,
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
    facts: _BoundFacts,
) -> dict[str, Any]:
    audit: dict[str, Any] = {
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
        "license": _license_doc(facts.license),
        "pit": _pit_doc(),
        "admission": _admission_doc(facts.admission),
        "previous_manifest_present": _manifest_path(output_dir).exists(),
    }
    if facts.admission is not None:
        audit["restricted_research_permitted"] = (
            facts.admission.restricted_research_permitted)
    return audit


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
    facts: _BoundFacts,
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
        "license": _license_doc(facts.license),
        "pit": _pit_doc(),
        "admission": _admission_doc(facts.admission),
    }
    if facts.admission is not None:
        manifest["restricted_research_permitted"] = (
            facts.admission.restricted_research_permitted)
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
