"""Historical research data plane (H1A, M3-H workstream).

Everything the restricted-ETF historical pipeline (SPY/QQQ daily bars,
offline this round) needs ON THE DATA SIDE, reusing the M1 models —
never a second data model or a second snapshot format:

- the ``VERIFIED / ASSUMED / UNKNOWN`` pit evidence vocabulary and the
  per-row record binding all three timestamps (event / availability /
  receipt);
- :func:`pit_level_of_manifest` — the manifest-level pit verdict that
  must be quoted NEXT TO (never instead of) ``snapshot.research_admissible``:
  integrity + cutoff admissibility and vendor-pit verification are
  orthogonal (ADR-003 D8, errata P1-4) and must not impersonate each
  other;
- calendar-driven per-row availability deadlines and the derivation of
  ``max_latency_seconds`` from a FROZEN calendar supply (T3);
- the ASSUMED-capped purpose verdict wrapper (T3);
- the ``historical_research`` namespace snapshot writer (T4).

Hard honesty rules enforced here (2026-11-26 errata P1-4):

- a backfilled download's ``received_at_utc`` is never a historical
  availability fact;
- HTTP 200 + intact hashes NEVER upgrade a row to VERIFIED;
- UNKNOWN availability is never silently promoted to an assumption;
- ASSUMED-only evidence caps purpose verdicts at RESTRICT_SCOPE with
  ``PIT_ASSUMED_NOT_VERIFIED`` — never an unrestricted ACCEPT, and
  never ``HIST_OOS_SUPPORTED`` evidence.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping

from ..security.canonical import canonical_json_bytes
from .calendar import CalendarError
from .quality import (
    LatencyStats,
    MetricResult,
    QualityReport,
    bar_completeness,
    count_duplicate_or_out_of_order,
    field_coverage_metrics,
    latency_stats,
)
from .records import (
    AVAILABILITY_BASIS_ASSUMED_NEXT_OPEN,
    AVAILABILITY_BASIS_UNKNOWN,
    AVAILABILITY_BASIS_VENDOR_FACT,
    MARKER_UNKNOWN_AVAILABILITY,
    SourceRecord,
)
from .snapshot import DatasetEntry, SnapshotManifest, _entry_dict, build_snapshot, content_hash_of_rows

__all__ = [
    "EVIDENCE_KIND_MODEL_ASSUMPTION",
    "EVIDENCE_KIND_NONE",
    "EVIDENCE_KIND_VENDOR_PUBLISHED_TIME",
    "HistoricalAcceptanceDecision",
    "HistoricalBarRecord",
    "HistoricalDataError",
    "PIT_ASSUMED_NOT_VERIFIED",
    "PIT_LEVEL_ASSUMED",
    "PIT_LEVEL_UNKNOWN",
    "PIT_LEVEL_VERIFIED",
    "PIT_LEVELS",
    "PURPOSE_ROW_PENDING_CALENDAR_FREEZE",
    "HistoricalSnapshotBuild",
    "build_historical_snapshot",
    "calendar_deadline_violations",
    "derive_max_latency_seconds",
    "evaluate_historical_research",
    "pit_level_of_manifest",
    "write_historical_namespace",
]

#: pit evidence vocabulary — closed, fail-closed at construction.
PIT_LEVEL_VERIFIED = "VERIFIED"
PIT_LEVEL_ASSUMED = "ASSUMED"
PIT_LEVEL_UNKNOWN = "UNKNOWN"
PIT_LEVELS = frozenset({PIT_LEVEL_VERIFIED, PIT_LEVEL_ASSUMED, PIT_LEVEL_UNKNOWN})

#: what justifies each level (exactly one kind per level).
EVIDENCE_KIND_VENDOR_PUBLISHED_TIME = "vendor_published_time"
EVIDENCE_KIND_MODEL_ASSUMPTION = "model_assumption"
EVIDENCE_KIND_NONE = "none"

_LEVEL_TO_KIND = {
    PIT_LEVEL_VERIFIED: EVIDENCE_KIND_VENDOR_PUBLISHED_TIME,
    PIT_LEVEL_ASSUMED: EVIDENCE_KIND_MODEL_ASSUMPTION,
    PIT_LEVEL_UNKNOWN: EVIDENCE_KIND_NONE,
}

#: the claim marker any ASSUMED-only result MUST carry (errata P1-4).
PIT_ASSUMED_NOT_VERIFIED = "PIT_ASSUMED_NOT_VERIFIED"

#: the ONLY safe partition-directory segment for a symbol (review fix
#: 2026-11-26: an unvalidated segment let crafted names escape the
#: namespace root via path separators)
_SYMBOL_SEGMENT_RE = re.compile(r"^[A-Z]{1,5}$")


class HistoricalDataError(ValueError):
    """A historical record or claim violates the pit/evidence contract."""


def _aware(value: dt.datetime, field: str) -> dt.datetime:
    if not isinstance(value, dt.datetime) or value.tzinfo is None:
        raise HistoricalDataError(f"{field} must be a timezone-aware datetime")
    return value


def _price(value: object, field: str) -> Decimal:
    """Exact-decimal price: Decimal or int from the guarded client's
    parser; floats and strings are platform-banned at this layer."""
    if isinstance(value, bool) or not isinstance(value, (Decimal, int)):
        raise HistoricalDataError(
            f"{field} must be an exact number (Decimal/int), got {type(value).__name__}"
        )
    d = Decimal(value) if isinstance(value, int) else value
    if not d.is_finite():
        raise HistoricalDataError(f"{field} is not finite: {d}")
    if d <= 0:
        raise HistoricalDataError(f"{field} must be positive, got {d}")
    return d


@dataclass(frozen=True)
class HistoricalBarRecord:
    """One historical daily bar with its three timestamps and its pit
    evidence level, validated fail-closed at construction."""

    symbol: str
    session_date: dt.date
    ts_event_utc: dt.datetime          # session close instant (calendar-derived)
    vendor_event_ts_utc: dt.datetime   # the vendor "t" stamp as received
    available_at_utc: object           # aware datetime or MARKER_UNKNOWN_AVAILABILITY
    assumed_available_at_utc: dt.datetime | None
    received_at_utc: dt.datetime       # when WE downloaded the bytes
    pit_evidence_level: str
    availability_evidence_kind: str
    availability_evidence_detail: str = ""  # non-empty only for VERIFIED
    open: Decimal = Decimal("0")
    high: Decimal = Decimal("0")
    low: Decimal = Decimal("0")
    close: Decimal = Decimal("0")
    volume: int = 0

    def __post_init__(self) -> None:
        if not self.symbol:
            raise HistoricalDataError("symbol must be non-empty")
        if self.pit_evidence_level not in PIT_LEVELS:
            raise HistoricalDataError(
                f"pit_evidence_level {self.pit_evidence_level!r} outside "
                f"{sorted(PIT_LEVELS)}"
            )
        expected_kind = _LEVEL_TO_KIND[self.pit_evidence_level]
        if self.availability_evidence_kind != expected_kind:
            raise HistoricalDataError(
                f"pit_evidence_level {self.pit_evidence_level} requires "
                f"availability_evidence_kind {expected_kind!r}, got "
                f"{self.availability_evidence_kind!r} — an assumption is "
                "never vendor evidence and vice versa"
            )
        _aware(self.ts_event_utc, "ts_event_utc")
        _aware(self.vendor_event_ts_utc, "vendor_event_ts_utc")
        _aware(self.received_at_utc, "received_at_utc")

        if self.pit_evidence_level == PIT_LEVEL_VERIFIED:
            if not self.availability_evidence_detail:
                raise HistoricalDataError(
                    "VERIFIED requires non-empty availability_evidence_detail "
                    "(the vendor receipt/fact this level is pinned to)"
                )
            available = _aware(self.available_at_utc, "available_at_utc")
            # a vendor publish time STRICTLY PRECEDES our receipt; a fact
            # at/after the download moment is a backfill artifact, not
            # history
            if available >= self.received_at_utc:
                raise HistoricalDataError(
                    "VERIFIED available_at_utc must precede received_at_utc — "
                    "a download-time fact cannot be a historical vendor publish time"
                )
            if self.assumed_available_at_utc is not None:
                raise HistoricalDataError("VERIFIED rows carry no assumption")
        elif self.pit_evidence_level == PIT_LEVEL_ASSUMED:
            if self.availability_evidence_detail:
                raise HistoricalDataError("ASSUMED rows carry no vendor evidence detail")
            assumed = _aware(self.assumed_available_at_utc, "assumed_available_at_utc")
            if self.available_at_utc != assumed:
                raise HistoricalDataError(
                    "ASSUMED available_at_utc must equal assumed_available_at_utc"
                )
        else:  # UNKNOWN
            if self.available_at_utc != MARKER_UNKNOWN_AVAILABILITY:
                raise HistoricalDataError(
                    "UNKNOWN availability must carry the UNKNOWN_AVAILABILITY marker"
                )
            if self.assumed_available_at_utc is not None:
                raise HistoricalDataError(
                    "UNKNOWN availability is never promoted to an assumption"
                )

        for name in ("open", "high", "low", "close"):
            _price(getattr(self, name), name)
        low, high = self.low, self.high
        if low > high:
            raise HistoricalDataError("low must not exceed high")
        if isinstance(self.volume, bool) or not isinstance(self.volume, int):
            raise HistoricalDataError(
                f"volume must be an int, got {type(self.volume).__name__}"
            )
        if self.volume < 0:
            raise HistoricalDataError("volume must be non-negative")

    # -- row parsing (vendor shape = guarded-client output) -------------------

    @staticmethod
    def _parse_vendor_row(row: Mapping[str, Any]) -> tuple[dt.datetime, Decimal, Decimal, Decimal, Decimal, int]:
        required = ("t", "o", "h", "l", "c", "v")
        for key in required:
            if key not in row:
                raise HistoricalDataError(f"vendor row missing field {key!r}")
        try:
            vendor_ts = dt.datetime.fromisoformat(str(row["t"]).replace("Z", "+00:00"))
        except ValueError as exc:
            raise HistoricalDataError(f"vendor row t is not an ISO timestamp: {row['t']!r}") from exc
        if vendor_ts.tzinfo is None:
            raise HistoricalDataError("vendor row t must carry a timezone")
        return (
            vendor_ts,
            _price(row["o"], "o"),
            _price(row["h"], "h"),
            _price(row["l"], "l"),
            _price(row["c"], "c"),
            row["v"],
        )

    @classmethod
    def assumed_next_open_row(
        cls,
        row: Mapping[str, Any],
        *,
        symbol: str,
        session_date: dt.date,
        session_close_utc: dt.datetime,
        assumed_available_at_utc: dt.datetime,
        received_at_utc: dt.datetime,
    ) -> "HistoricalBarRecord":
        vendor_ts, o, h, low, c, v = cls._parse_vendor_row(row)
        return cls(
            symbol=symbol,
            session_date=session_date,
            ts_event_utc=session_close_utc,
            vendor_event_ts_utc=vendor_ts,
            available_at_utc=assumed_available_at_utc,
            assumed_available_at_utc=assumed_available_at_utc,
            received_at_utc=received_at_utc,
            pit_evidence_level=PIT_LEVEL_ASSUMED,
            availability_evidence_kind=EVIDENCE_KIND_MODEL_ASSUMPTION,
            open=o,
            high=h,
            low=low,
            close=c,
            volume=v,
        )

    @classmethod
    def verified_vendor_row(
        cls,
        row: Mapping[str, Any],
        *,
        symbol: str,
        session_date: dt.date,
        session_close_utc: dt.datetime,
        available_at_utc: dt.datetime,
        evidence_detail: str,
        received_at_utc: dt.datetime,
    ) -> "HistoricalBarRecord":
        vendor_ts, o, h, low, c, v = cls._parse_vendor_row(row)
        return cls(
            symbol=symbol,
            session_date=session_date,
            ts_event_utc=session_close_utc,
            vendor_event_ts_utc=vendor_ts,
            available_at_utc=available_at_utc,
            assumed_available_at_utc=None,
            received_at_utc=received_at_utc,
            pit_evidence_level=PIT_LEVEL_VERIFIED,
            availability_evidence_kind=EVIDENCE_KIND_VENDOR_PUBLISHED_TIME,
            availability_evidence_detail=evidence_detail,
            open=o,
            high=h,
            low=low,
            close=c,
            volume=v,
        )

    @classmethod
    def unknown_availability_row(
        cls,
        row: Mapping[str, Any],
        *,
        symbol: str,
        session_date: dt.date,
        session_close_utc: dt.datetime,
        received_at_utc: dt.datetime,
    ) -> "HistoricalBarRecord":
        vendor_ts, o, h, low, c, v = cls._parse_vendor_row(row)
        return cls(
            symbol=symbol,
            session_date=session_date,
            ts_event_utc=session_close_utc,
            vendor_event_ts_utc=vendor_ts,
            available_at_utc=MARKER_UNKNOWN_AVAILABILITY,
            assumed_available_at_utc=None,
            received_at_utc=received_at_utc,
            pit_evidence_level=PIT_LEVEL_UNKNOWN,
            availability_evidence_kind=EVIDENCE_KIND_NONE,
            open=o,
            high=h,
            low=low,
            close=c,
            volume=v,
        )


def pit_level_of_manifest(manifest: SnapshotManifest) -> str:
    """Worst-case pit level over the manifest's entries, from the pinned
    availability bases: any UNKNOWN -> UNKNOWN; else any assumed ->
    ASSUMED (quote ``PIT_ASSUMED_NOT_VERIFIED``); only all-vendor-fact
    manifests are VERIFIED. An empty manifest proves nothing (UNKNOWN).

    Orthogonal to ``snapshot.research_admissible`` (ADR-003 D8): that
    gate answers integrity + cutoff admissibility; this answers whether
    the availability facts were vendor-verified. Neither implies the
    other; purpose admission needs both."""
    if not manifest.entries:
        return PIT_LEVEL_UNKNOWN
    bases = {entry.source.availability_basis for entry in manifest.entries}
    if AVAILABILITY_BASIS_UNKNOWN in bases:
        return PIT_LEVEL_UNKNOWN
    if AVAILABILITY_BASIS_ASSUMED_NEXT_OPEN in bases:
        return PIT_LEVEL_ASSUMED
    return PIT_LEVEL_VERIFIED


# ---------------------------------------------------------------------------
# T3 — calendar-driven quality gate and the historical purpose verdict.
# ---------------------------------------------------------------------------

#: the config marker for the candidate purpose row whose
#: ``max_latency_seconds`` depends on a calendar that is not frozen yet:
#: the row stays OUT of configs/data_acceptance.yaml and this marker is
#: reported instead of any fabricated readiness claim.
PURPOSE_ROW_PENDING_CALENDAR_FREEZE = "PURPOSE_ROW_PENDING_CALENDAR_FREEZE"


def derive_max_latency_seconds(
    calendar: "VersionedMarketCalendar", grace_seconds: int
) -> tuple[int, dict[str, Any]]:
    """Derive the numeric ``max_latency_seconds`` for the
    ``daily_close_available_next_open`` rule from a FROZEN calendar
    supply + the pre-registered grace: the worst legal
    session-close -> next-open span over the whole coverage window,
    plus grace. Returns the number AND its derivation record (both
    belong in the purpose-row freeze evidence). Never a fixed 48h, and
    never back-fitted after seeing failures — the calendar must be
    frozen first."""
    if grace_seconds < 0:
        raise HistoricalDataError("grace_seconds must be non-negative")
    supply = calendar.supply
    worst_seconds: float | None = None
    worst_day: dt.date | None = None
    sessions_total = 0
    sessions_skipped = 0
    for day in calendar.expected_sessions(supply.valid_from, supply.valid_until):
        sessions_total += 1
        close = calendar.session(day).close_utc()
        if close is None:
            continue
        try:
            next_open = calendar.session_open_after(close)
        except CalendarError:
            # the covered window's final session has no certifiable next
            # open (fail-closed rule) — excluded from the derivation, and
            # the real calendar freeze must cover study window + 1 session
            sessions_skipped += 1
            continue
        span = (next_open - close).total_seconds()
        if worst_seconds is None or span > worst_seconds:
            worst_seconds = span
            worst_day = day
    if worst_seconds is None:
        raise HistoricalDataError(
            "calendar supply yields no certifiable close->next-open pair — "
            "no threshold can be derived"
        )
    derived = int(worst_seconds) + grace_seconds
    derivation: dict[str, Any] = {
        "formula": "max_session(next_open - session_close) + grace_seconds",
        "calendar_version": supply.version,
        "calendar_source_url": supply.source_url,
        "calendar_valid_from": supply.valid_from.isoformat(),
        "calendar_valid_until": supply.valid_until.isoformat(),
        "grace_seconds": grace_seconds,
        "sessions_total": sessions_total,
        "sessions_skipped_next_open_outside_coverage": sessions_skipped,
        "worst_case_seconds": int(worst_seconds),
        "worst_case_session_date": worst_day.isoformat() if worst_day else None,
        "max_latency_seconds": derived,
    }
    return derived, derivation


def calendar_deadline_violations(
    rows: Any,
    calendar: Any,
    grace_seconds: int,
) -> tuple[str, ...]:
    """Per-row calendar-driven check for the ``daily_close_available_next_open``
    rule: each ASSUMED row's declared availability must not exceed its
    own deadline ``next_session_open(ts_event) + grace_seconds``.

    This is deliberately NOT ``quality.latency_stats``: the observed
    statistic stays a statistic; this gate judges each row against the
    frozen calendar, so legal holiday/half-day spans (41.5h/65.5h/92.5h)
    pass while a deferral past the pre-registered deadline fails. Rows
    with UNKNOWN availability are flagged (never silently skipped and
    never assumed); rows whose next session is outside calendar coverage
    are flagged as coverage refusals."""
    if grace_seconds < 0:
        raise HistoricalDataError("grace_seconds must be non-negative")
    reasons: list[str] = []
    for row in rows:
        if row.pit_evidence_level == PIT_LEVEL_UNKNOWN:
            reasons.append(
                f"UNKNOWN_AVAILABILITY:{row.symbol}:{row.session_date.isoformat()}"
            )
            continue
        if row.pit_evidence_level != PIT_LEVEL_ASSUMED:
            continue  # VERIFIED rows are judged against vendor facts
        try:
            deadline = calendar.session_open_after(row.ts_event_utc) + dt.timedelta(
                seconds=grace_seconds
            )
        except CalendarError as exc:
            reasons.append(
                f"CALENDAR_COVERAGE_REFUSAL:{row.symbol}:{row.session_date.isoformat()}:"
                f"{exc}"
            )
            continue
        if row.available_at_utc > deadline:
            reasons.append(
                f"ASSUMED_AVAILABLE_PAST_DEADLINE:{row.symbol}:{row.session_date.isoformat()}:"
                f"available={row.available_at_utc.isoformat()}>deadline={deadline.isoformat()}"
            )
    return tuple(reasons)


@dataclass(frozen=True)
class HistoricalAcceptanceDecision:
    """The purpose verdict for historical data WITH its pit disclosure.
    ``verdict`` is the quotable outcome; ``base_verdict`` records what
    the general ``evaluate_purpose`` said so the cap is auditable."""

    purpose_id: str
    verdict: str
    reasons: tuple[str, ...]
    pit_level: str
    base_verdict: str


def evaluate_historical_research(
    requirements: Any,
    quality: Any,
    vendor: Any,
    manifest: SnapshotManifest,
) -> HistoricalAcceptanceDecision:
    """The H1 historical-purpose verdict: ``evaluate_purpose``'s frozen
    order, composed with the snapshot gates so no layer can impersonate
    another (ADR-003 D5 + D8, errata P1-4):

    0. manifest integrity/cutoff admissibility broken -> BLOCKED_DATA;
    1. ``evaluate_purpose`` (license -> unknown facts -> zero
       denominators -> PIT matrix -> coverage -> quality -> ACCEPT);
    2. pit level UNKNOWN -> BLOCKED_DATA (nothing assumed silently);
    3. pit level ASSUMED caps ACCEPT at RESTRICT_SCOPE and always adds
       ``PIT_ASSUMED_NOT_VERIFIED`` — never an unrestricted ACCEPT and
       never a VERIFIED claim.

    Verdicts are only ever capped, never upgraded: a base
    BLOCKED_DATA / INCONCLUSIVE / REJECT stays as it is.

    Disclosure (review 2026-11-26, deferred): entries built with the
    LEGACY default ``availability_basis='vendor_fact'`` classify as
    pit VERIFIED here without this vocabulary having existed when they
    were recorded. Route manifests into this verdict only when their
    provenance genuinely earned its basis."""
    from .acceptance import (
        VERDICT_ACCEPT,
        VERDICT_BLOCKED_DATA,
        VERDICT_RESTRICT_SCOPE,
        evaluate_purpose,
    )
    from .snapshot import research_admissible

    pit = pit_level_of_manifest(manifest)
    base = evaluate_purpose(requirements, quality, vendor)
    reasons: list[str] = list(base.reasons)

    admissible = research_admissible(manifest)
    if not admissible.ok:
        reasons = [f"SNAPSHOT_NOT_ADMISSIBLE:{r}" for r in admissible.reasons]
        return HistoricalAcceptanceDecision(
            requirements.purpose_id, VERDICT_BLOCKED_DATA, tuple(reasons), pit, base.verdict
        )

    if pit == PIT_LEVEL_UNKNOWN:
        reasons.append("PIT_LEVEL_UNKNOWN:availability_facts_missing_or_conflicting")
        return HistoricalAcceptanceDecision(
            requirements.purpose_id, VERDICT_BLOCKED_DATA, tuple(reasons), pit, base.verdict
        )

    if pit == PIT_LEVEL_ASSUMED:
        reasons.append(PIT_ASSUMED_NOT_VERIFIED)
        if base.verdict == VERDICT_ACCEPT:
            return HistoricalAcceptanceDecision(
                requirements.purpose_id,
                VERDICT_RESTRICT_SCOPE,
                tuple(reasons),
                pit,
                base.verdict,
            )

    return HistoricalAcceptanceDecision(
        requirements.purpose_id, base.verdict, tuple(reasons), pit, base.verdict
    )


# ---------------------------------------------------------------------------
# T4 — the thin adapter: validated fetch results -> one deterministic
# historical snapshot in the historical_research namespace. This is NOT a
# second backtest engine and never replaces the M3 formal one; it only
# produces reviewed data, hashes and admission records.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HistoricalSnapshotBuild:
    """Everything one offline historical admission run produced: the
    manifest (integrity), per-row records (pit levels), the quality
    report (denominators) and the capped purpose verdict."""

    manifest: SnapshotManifest
    entries: tuple[DatasetEntry, ...]
    records: tuple[HistoricalBarRecord, ...]
    quality: QualityReport
    decision: HistoricalAcceptanceDecision
    grace_seconds: int


def _row_payload(record: HistoricalBarRecord) -> dict[str, object]:
    """Canonical, hashable projection of one record (prices as strings —
    the canonical serializer renders Decimals as strings anyway, this
    just makes it explicit)."""
    available = (
        record.available_at_utc
        if isinstance(record.available_at_utc, str)
        else record.available_at_utc.isoformat()
    )
    return {
        "symbol": record.symbol,
        "session_date": record.session_date.isoformat(),
        "ts_event_utc": record.ts_event_utc.isoformat(),
        "vendor_event_ts_utc": record.vendor_event_ts_utc.isoformat(),
        "available_at_utc": available,
        "assumed_available_at_utc": (
            record.assumed_available_at_utc.isoformat()
            if record.assumed_available_at_utc is not None
            else None
        ),
        "received_at_utc": record.received_at_utc.isoformat(),
        "pit_evidence_level": record.pit_evidence_level,
        "availability_evidence_kind": record.availability_evidence_kind,
        "open": str(record.open),
        "high": str(record.high),
        "low": str(record.low),
        "close": str(record.close),
        "volume": record.volume,
    }


def build_historical_snapshot(
    *,
    fetch_results: Any,
    calendar: Any,
    received_at_utc: dt.datetime,
    knowledge_cutoff_utc: dt.datetime,
    requirements: Any,
    vendor: Any,
    grace_seconds: int = 0,
) -> HistoricalSnapshotBuild:
    """Build the deterministic historical snapshot from validated fetch
    results (the gateway client output shape).

    Every row is stamped through the versioned calendar: session close
    (``ts_event_utc``), next-session-open assumption
    (``available_at_utc`` = ``assumed_available_at_utc``, pit level
    ASSUMED), and the download moment (``received_at_utc``). The
    per-row calendar deadline gate runs over the built records — any
    violation refuses the whole build. Quality facts keep their M1
    denominators; the verdict comes from the ASSUMED-capped wrapper.
    """
    if not fetch_results:
        raise HistoricalDataError("no fetch results — nothing to admit")
    if grace_seconds < 0:
        raise HistoricalDataError("grace_seconds must be non-negative")
    _aware(received_at_utc, "received_at_utc")
    _aware(knowledge_cutoff_utc, "knowledge_cutoff_utc")

    records: list[HistoricalBarRecord] = []
    all_session_dates: set[dt.date] = set()
    window_start = min(r.start for r in fetch_results)
    window_end = max(r.end for r in fetch_results)
    try:
        expected_sessions = calendar.expected_sessions(window_start, window_end)
    except CalendarError as exc:
        raise HistoricalDataError(
            f"study window [{window_start.isoformat()}, {window_end.isoformat()}] "
            f"is outside calendar supply coverage: {exc}"
        ) from exc

    for result in fetch_results:
        if not _SYMBOL_SEGMENT_RE.fullmatch(str(result.symbol)):
            raise HistoricalDataError(
                f"SYMBOL_SEGMENT_UNSAFE:{result.symbol!r} — partition names "
                "derive from the symbol segment; refusing anything outside "
                "[A-Z]{1,5} (namespace-root escape guard)"
            )
        for row in result.rows:
            session_date = dt.date.fromisoformat(str(row["session_date"]))
            try:
                info = calendar.session(session_date)
            except CalendarError as exc:
                raise HistoricalDataError(
                    f"{result.symbol} session {session_date.isoformat()} outside "
                    f"calendar supply coverage: {exc}"
                ) from exc
            if not info.is_trading_day:
                raise HistoricalDataError(
                    f"{result.symbol} carries a bar on non-trading day "
                    f"{session_date.isoformat()}"
                )
            close_utc = info.close_utc()
            if close_utc is None:
                raise HistoricalDataError(
                    f"session {session_date.isoformat()} has no close time"
                )
            assumed = calendar.session_open_after(close_utc)
            records.append(
                HistoricalBarRecord.assumed_next_open_row(
                    row,
                    symbol=result.symbol,
                    session_date=session_date,
                    session_close_utc=close_utc,
                    assumed_available_at_utc=assumed,
                    received_at_utc=received_at_utc,
                )
            )
            all_session_dates.add(session_date)

    violations = calendar_deadline_violations(records, calendar, grace_seconds)
    if violations:
        raise HistoricalDataError(
            "availability stamps failed the calendar deadline gate: "
            + "; ".join(violations)
        )

    field_rows = [{"close": r.close, "volume": r.volume} for r in records]
    # duplicates/out-of-order are a per-symbol series property: two
    # symbols legitimately interleave the same sessions, so the count
    # never runs across the symbol boundary
    duplicates = sum(
        count_duplicate_or_out_of_order(
            [{"ts_event_utc": r.ts_event_utc} for r in records if r.symbol == symbol]
        )
        for symbol in sorted({r.symbol for r in records})
    )
    quality = QualityReport(
        field_coverage=field_coverage_metrics(field_rows, ["close", "volume"]),
        bar_completeness=bar_completeness(all_session_dates, expected_sessions),
        duplicate_or_out_of_order=duplicates,
        latency=latency_stats(
            [
                {"ts_event_utc": r.ts_event_utc, "ts_available_utc": r.available_at_utc}
                for r in records
            ]
        ),
        unknown_availability_count=0,
        license_status="personal_research",
        notes=(
            "pit_rule=daily_close_available_next_open",
            f"grace_seconds={grace_seconds}",
            "pit_level=ASSUMED(model assumption, never verified)",
        ),
    )

    entries: list[DatasetEntry] = []
    for result in fetch_results:
        symbol_records = [r for r in records if r.symbol == result.symbol]
        content_hash = content_hash_of_rows([_row_payload(r) for r in symbol_records])
        raw_hash = content_hash_of_rows([dict(row) for row in result.rows])
        max_assumed = max(r.assumed_available_at_utc for r in symbol_records)
        source = SourceRecord(
            source="alpaca_iex",
            dataset_version=f"iex-1Day-raw-pages:{result.pages}",
            acquisition_time_utc=received_at_utc,
            available_at_utc=max_assumed,
            raw_hash=raw_hash,
            transform_version="h1a-adapter-1",
            availability_basis=AVAILABILITY_BASIS_ASSUMED_NEXT_OPEN,
        )
        entries.append(
            DatasetEntry(
                name=f"historical_research/{result.symbol}/1Day/raw",
                content_hash=content_hash,
                row_count=len(symbol_records),
                source=source,
            )
        )

    manifest = build_snapshot(knowledge_cutoff_utc, entries)
    decision = evaluate_historical_research(requirements, quality, vendor, manifest)
    return HistoricalSnapshotBuild(
        manifest=manifest,
        entries=tuple(entries),
        records=tuple(records),
        quality=quality,
        decision=decision,
        grace_seconds=grace_seconds,
    )


def write_historical_namespace(root: Any, build: HistoricalSnapshotBuild) -> dict[str, Any]:
    """Write the namespace files ONLY under ``root`` (the caller owns the
    location; tests pass a temp directory): ``snapshot-manifest.json``,
    ``admission.json`` and per-symbol partition row files. Forward S8
    state, journals, receipts and M3 synthetic ledgers are never touched
    — this function has no knowledge of any other path. Deterministic
    bytes: canonical JSON, so the same build writes identical files."""
    from pathlib import Path as _Path

    from .snapshot import research_admissible

    root_path = _Path(root)
    root_path.mkdir(parents=True, exist_ok=True)
    written: dict[str, Any] = {}

    manifest_doc = {
        "namespace": "historical_research",
        "knowledge_cutoff_utc": build.manifest.knowledge_cutoff_utc.isoformat(),
        "entries": [_entry_dict(e) for e in build.manifest.entries],
        "dataset_hash": build.manifest.dataset_hash,
        "pit_level": build.decision.pit_level,
        "research_admissible": bool(research_admissible(build.manifest).ok),
    }
    manifest_path = root_path / "snapshot-manifest.json"
    manifest_path.write_bytes(canonical_json_bytes(manifest_doc))
    written["snapshot-manifest.json"] = manifest_path

    admission_doc = {
        "namespace": "historical_research",
        "purpose_id": build.decision.purpose_id,
        "verdict": build.decision.verdict,
        "reasons": list(build.decision.reasons),
        "pit_level": build.decision.pit_level,
        "base_verdict": build.decision.base_verdict,
        "api_verified_claim": "NONE",
        "claim_marker": (
            PIT_ASSUMED_NOT_VERIFIED
            if build.decision.pit_level == PIT_LEVEL_ASSUMED
            else None
        ),
        "purpose_row_status": PURPOSE_ROW_PENDING_CALENDAR_FREEZE,
        "grace_seconds": build.grace_seconds,
    }
    admission_path = root_path / "admission.json"
    admission_path.write_bytes(canonical_json_bytes(admission_doc))
    written["admission.json"] = admission_path

    for entry in build.entries:
        symbol = entry.name.split("/")[1]
        if not _SYMBOL_SEGMENT_RE.fullmatch(symbol):
            raise HistoricalDataError(
                f"SYMBOL_SEGMENT_UNSAFE:{symbol!r} — refusing to write outside "
                "the namespace root (entry-name escape guard)"
            )
        symbol_path = root_path / "partitions" / symbol / "daily-raw-rows.json"
        symbol_path.parent.mkdir(parents=True, exist_ok=True)
        payload = [_row_payload(r) for r in build.records if r.symbol == symbol]
        symbol_path.write_bytes(canonical_json_bytes(payload))
        written[f"partitions/{symbol}/daily-raw-rows.json"] = symbol_path
    return written
