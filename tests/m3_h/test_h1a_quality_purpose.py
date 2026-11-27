"""H1A T3 — calendar-driven historical purpose gates.

Separates two things that must never be conflated:

- ``quality.latency_stats`` stays an OBSERVED statistic (available_at -
  ts_event over received rows) exactly as in M1;
- the H1A per-row gate derives each row's legal availability deadline
  from the versioned trading calendar (``ts_event -> next session open
  + pre-registered grace``), so legal holiday/half-day spans (65.5h,
  92.5h) are NOT violations and a fixed 48h number is proven wrong;

and derives ``max_latency_seconds`` from the frozen calendar + grace
(never fixed 48h, never backfilled from failures), wrapping
``evaluate_purpose`` so ASSUMED-only pit evidence caps the verdict at
RESTRICT_SCOPE with ``PIT_ASSUMED_NOT_VERIFIED`` — never an
unrestricted ACCEPT — while license/unknown/zero-denominator semantics
stay exactly as frozen (ADR-003 D5).

The official ``configs/data_acceptance.yaml`` row stays ABSENT this
round: ``PURPOSE_ROW_PENDING_CALENDAR_FREEZE`` (the frozen 2017-2025
research calendar is not sourced yet) — asserted here as a machine
check.
"""

from __future__ import annotations

import datetime as dt
import sys
from decimal import Decimal
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (REPO_ROOT / "src", REPO_ROOT / "tests"):
    _sp = str(_p)
    if _sp not in sys.path:
        sys.path.insert(0, _sp)

from trading_lab.data.acceptance import (  # noqa: E402
    VERDICT_ACCEPT,
    VERDICT_BLOCKED_DATA,
    VERDICT_INCONCLUSIVE,
    VERDICT_RESTRICT_SCOPE,
    PurposeRequirements,
    VendorFacts,
    evaluate_purpose,
)
from trading_lab.data.quality import LatencyStats, MetricResult, QualityReport  # noqa: E402
from trading_lab.data.records import SourceRecord  # noqa: E402
from trading_lab.data.snapshot import DatasetEntry, build_snapshot  # noqa: E402

from helpers_m3_h import nyse_2026_fixture_supply  # noqa: E402

UTC = dt.timezone.utc
RECEIVED_AT = dt.datetime(2026, 11, 26, 12, 0, tzinfo=UTC)
CUTOFF = dt.datetime(2026, 12, 31, 23, 59, tzinfo=UTC)
GRACE_SECONDS = 3600  # pre-registered template grace (fixture scope only)


def _requirements(max_latency_seconds: int) -> "PurposeRequirements":
    return PurposeRequirements(
        purpose_id="historical_research_limited_etf",
        description="H1A offline template purpose (test-only until calendar freeze)",
        data_scope="us_equities_daily_limited_etf_history",
        requires_daily_bars=True,
        requires_minute_bars=False,
        requires_corporate_actions=False,
        requires_history_membership=False,
        requires_delisting=False,
        available_at_rule="daily_close_available_next_open",
        max_missing_rate=0.001,
        min_coverage_rate=0.999,
        max_latency_seconds=max_latency_seconds,
        required_license_scope="personal_research",
        on_fail="RESTRICT_SCOPE",
    )


def _vendor(license_confirmed: bool = True, pit: str = "eod_only") -> VendorFacts:
    return VendorFacts(
        license_scope="personal_research",
        license_confirmed=license_confirmed,
        history_membership_coverage="yes",
        delisting_coverage="yes",
        corporate_actions_coverage="yes",
        pit_availability=pit,
    )


def _quality(samples: int = 3, max_seconds: float = 333000.0) -> QualityReport:
    fc = (
        MetricResult(name="close", denominator=10, missing=0, observed=10, rate=1.0),
        MetricResult(name="volume", denominator=10, missing=0, observed=10, rate=1.0),
    )
    bar = MetricResult(name="bar_completeness", denominator=10, missing=0, observed=10, rate=1.0)
    if samples:
        latency = LatencyStats(
            sample_count=samples,
            unknown_availability_count=0,
            min_seconds=234000.0,
            median_seconds=234000.0,
            max_seconds=max_seconds,
        )
    else:
        latency = LatencyStats(0, 0, None, None, None)
    return QualityReport(
        field_coverage=fc,
        bar_completeness=bar,
        duplicate_or_out_of_order=0,
        latency=latency,
        unknown_availability_count=0,
        license_status="personal_research",
        notes=(),
    )


def _entry(name: str, basis: str, available_at: object) -> DatasetEntry:
    rec = SourceRecord(
        source="alpaca_iex",
        dataset_version="synthetic-history-v1",
        acquisition_time_utc=RECEIVED_AT,
        available_at_utc=available_at,
        raw_hash="a" * 64,
        transform_version="raw-1",
        availability_basis=basis,
    )
    return DatasetEntry(name=name, content_hash="b" * 64, row_count=1, source=rec)


def _assumed_manifest() -> "object":
    return build_snapshot(
        CUTOFF,
        [_entry("spy_daily", "assumed_next_open", dt.datetime(2026, 11, 27, 14, 30, tzinfo=UTC))],
    )


def _verified_manifest() -> "object":
    return build_snapshot(
        CUTOFF,
        [_entry("spy_daily", "vendor_fact", dt.datetime(2026, 11, 25, 21, 30, tzinfo=UTC))],
    )


class TestCalendarDerivedThreshold:
    def test_derivation_beats_fixed_48h_and_matches_worst_span(self):
        from trading_lab.data.historical import derive_max_latency_seconds
        from trading_lab.data.historical_calendar import VersionedMarketCalendar

        calendar = VersionedMarketCalendar.from_supply(nyse_2026_fixture_supply())
        derived, derivation = derive_max_latency_seconds(calendar, GRACE_SECONDS)
        # worst legal fixture span: Thu 12-24 13:00 ET close -> Mon 12-28
        # 09:30 ET open = 92.5h = 333000s (a fixed 48h = 172800s is wrong)
        assert derived == 333000 + GRACE_SECONDS
        assert derivation["formula"] == "max_session(next_open - session_close) + grace_seconds"
        assert derivation["calendar_version"] == "nyse-2026-h1a-fixture-v1"
        assert derivation["grace_seconds"] == GRACE_SECONDS
        assert derivation["worst_case_session_date"] == "2026-12-24"
        assert derived > 172800, "must not be the fixed 48h number"

    def test_negative_grace_refused(self):
        from trading_lab.data.historical import HistoricalDataError, derive_max_latency_seconds
        from trading_lab.data.historical_calendar import VersionedMarketCalendar

        calendar = VersionedMarketCalendar.from_supply(nyse_2026_fixture_supply())
        with pytest.raises(HistoricalDataError):
            derive_max_latency_seconds(calendar, -1)

    def test_template_requirements_validate_with_derived_threshold(self):
        from trading_lab.data.historical import derive_max_latency_seconds
        from trading_lab.data.historical_calendar import VersionedMarketCalendar

        calendar = VersionedMarketCalendar.from_supply(nyse_2026_fixture_supply())
        derived, _ = derive_max_latency_seconds(calendar, GRACE_SECONDS)
        req = _requirements(derived)  # must construct (thresholds consistent)
        assert req.max_latency_seconds == derived


class TestOfficialRowPendingCalendarFreeze:
    """H1A-era state: the row was ABSENT pending calendar freeze. H1B
    (2026-11-27, authorized round) sourced + froze the 2017-2025 NYSE
    calendar and appended the row — these tests now assert the FROZEN
    state (see test_h1b_calendar_freeze.py for the freeze assertions)."""

    def test_official_yaml_has_no_placeholder_markers(self):
        text = (REPO_ROOT / "configs" / "data_acceptance.yaml").read_text(encoding="utf-8")
        assert "PROPOSED_NEW_RULE_NOT_IMPLEMENTED" not in text
        assert "PROPOSED_CALENDAR_DRIVEN_THRESHOLD_NOT_IMPLEMENTED" not in text

    def test_pending_marker_constant_exists(self):
        from trading_lab.data.historical import PURPOSE_ROW_PENDING_CALENDAR_FREEZE

        assert PURPOSE_ROW_PENDING_CALENDAR_FREEZE == "PURPOSE_ROW_PENDING_CALENDAR_FREEZE"


class TestPerRowCalendarGate:
    def _record(self, available_at: dt.datetime):
        from trading_lab.data.historical import HistoricalBarRecord

        return HistoricalBarRecord.assumed_next_open_row(
            {
                "t": "2026-12-24T05:00:00Z",
                "o": Decimal("600"),
                "h": Decimal("602"),
                "l": Decimal("599"),
                "c": Decimal("601"),
                "v": 1000,
            },
            symbol="SPY",
            session_date=dt.date(2026, 12, 24),
            session_close_utc=dt.datetime(2026, 12, 24, 18, 0, tzinfo=UTC),
            assumed_available_at_utc=available_at,
            received_at_utc=RECEIVED_AT,
        )

    def test_legal_92_5h_holiday_span_is_not_a_violation(self):
        from trading_lab.data.historical import calendar_deadline_violations
        from trading_lab.data.historical_calendar import VersionedMarketCalendar

        calendar = VersionedMarketCalendar.from_supply(nyse_2026_fixture_supply())
        legal = self._record(dt.datetime(2026, 12, 28, 14, 30, tzinfo=UTC))  # exact next open
        assert calendar_deadline_violations([legal], calendar, GRACE_SECONDS) == ()

    def test_deferral_past_preregistered_deadline_rejected(self):
        from trading_lab.data.historical import calendar_deadline_violations
        from trading_lab.data.historical_calendar import VersionedMarketCalendar

        calendar = VersionedMarketCalendar.from_supply(nyse_2026_fixture_supply())
        late = self._record(dt.datetime(2026, 12, 28, 14, 30, tzinfo=UTC) + dt.timedelta(hours=2))
        reasons = calendar_deadline_violations([late], calendar, GRACE_SECONDS)
        assert len(reasons) == 1
        assert reasons[0].startswith("ASSUMED_AVAILABLE_PAST_DEADLINE:SPY:2026-12-24")
        # ...and the old observed-latency view is a DIFFERENT mechanism
        from trading_lab.data.quality import latency_stats

        rows = [
            {
                "ts_event_utc": dt.datetime(2026, 12, 24, 18, 0, tzinfo=UTC),
                "ts_available_utc": late.available_at_utc,
            }
        ]
        stats = latency_stats(rows)
        assert stats.max_seconds == (92.5 + 2.0) * 3600  # observed, not a deadline

    def test_unknown_availability_flagged_not_skipped(self):
        from trading_lab.data.historical import HistoricalBarRecord, calendar_deadline_violations
        from trading_lab.data.historical_calendar import VersionedMarketCalendar

        calendar = VersionedMarketCalendar.from_supply(nyse_2026_fixture_supply())
        unknown = HistoricalBarRecord.unknown_availability_row(
            {
                "t": "2026-12-24T05:00:00Z",
                "o": Decimal("600"),
                "h": Decimal("602"),
                "l": Decimal("599"),
                "c": Decimal("601"),
                "v": 1000,
            },
            symbol="SPY",
            session_date=dt.date(2026, 12, 24),
            session_close_utc=dt.datetime(2026, 12, 24, 18, 0, tzinfo=UTC),
            received_at_utc=RECEIVED_AT,
        )
        reasons = calendar_deadline_violations([unknown], calendar, GRACE_SECONDS)
        assert reasons == ("UNKNOWN_AVAILABILITY:SPY:2026-12-24",)


class TestHistoricalPurposeWrapper:
    def _decide(self, *, quality=None, vendor=None, manifest=None, requirements=None):
        from trading_lab.data.historical import derive_max_latency_seconds, evaluate_historical_research
        from trading_lab.data.historical_calendar import VersionedMarketCalendar

        if requirements is None:
            calendar = VersionedMarketCalendar.from_supply(nyse_2026_fixture_supply())
            derived, _ = derive_max_latency_seconds(calendar, GRACE_SECONDS)
            requirements = _requirements(derived)
        return evaluate_historical_research(
            requirements or _requirements(336600),
            quality or _quality(),
            vendor or _vendor(),
            manifest or _assumed_manifest(),
        )

    def test_assumed_pit_caps_accept_at_restrict_scope(self):
        decision = self._decide()
        base = evaluate_purpose(
            _requirements(336600), _quality(), _vendor()
        )
        assert base.verdict == VERDICT_ACCEPT  # the naive base verdict
        assert decision.base_verdict == VERDICT_ACCEPT
        assert decision.verdict == VERDICT_RESTRICT_SCOPE
        assert decision.pit_level == "ASSUMED"
        assert "PIT_ASSUMED_NOT_VERIFIED" in decision.reasons

    def test_verified_pit_allows_plain_accept(self):
        decision = self._decide(manifest=_verified_manifest())
        assert decision.verdict == VERDICT_ACCEPT
        assert decision.pit_level == "VERIFIED"

    def test_license_unconfirmed_stays_blocked_even_with_assumed_pit(self):
        decision = self._decide(vendor=_vendor(license_confirmed=False))
        assert decision.verdict == VERDICT_BLOCKED_DATA
        assert any(r.startswith("LICENSE_UNCONFIRMED") for r in decision.reasons)

    def test_zero_latency_samples_stay_inconclusive(self):
        decision = self._decide(quality=_quality(samples=0))
        assert decision.verdict == VERDICT_INCONCLUSIVE
        assert any("INCONCLUSIVE:latency:zero_samples" == r or "INCONCLUSIVE" in r for r in decision.reasons)

    def test_unknown_pit_manifest_blocks(self):
        decision = self._decide(
            manifest=build_snapshot(
                CUTOFF, [_entry("spy_daily", "unknown", "UNKNOWN_AVAILABILITY")]
            )
        )
        assert decision.verdict == VERDICT_BLOCKED_DATA
        assert decision.pit_level == "UNKNOWN"

    def test_broken_manifest_integrity_blocks(self):
        from trading_lab.data.snapshot import SnapshotManifest

        good = _assumed_manifest()
        stale = SnapshotManifest(
            knowledge_cutoff_utc=good.knowledge_cutoff_utc,
            entries=good.entries,
            dataset_hash="0" * 64,
        )
        decision = self._decide(manifest=stale)
        assert decision.verdict == VERDICT_BLOCKED_DATA
        assert any("INTEGRITY_FAILURE" in r for r in decision.reasons)
