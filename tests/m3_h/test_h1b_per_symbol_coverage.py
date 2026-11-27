"""H1B P0-Q1 — per-symbol historical bar completeness.

H1A computed the completeness denominator over the UNION of received
session dates across symbols, so SPY 3/3 + QQQ 1/3 could still read
100%. The H1 requirement is per-symbol per-trading-day completeness:
every authorized symbol's every expected session counts, fully-missing
symbols must stay visible, and the aggregate denominator is the SUM of
per-symbol expected sessions — the same
missing/denominator formula the pre-registered
``configs/data_acceptance.yaml`` thresholds judge.

Fixture sessions: Fri 2026-11-20, Mon 11-23, Tue 11-24 (all trading
days in the nyse-2026-h1a-fixture-v1 window). SYNTHETIC_OFFLINE_ONLY.
"""

from __future__ import annotations

import datetime as dt
import sys
from decimal import Decimal
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (REPO_ROOT / "src", REPO_ROOT / "tests", REPO_ROOT):
    _sp = str(_p)
    if _sp not in sys.path:
        sys.path.insert(0, _sp)

from helpers_m3_h import H1A_RECEIVED_AT, nyse_2026_fixture_supply  # noqa: E402

UTC = dt.timezone.utc
CUTOFF = dt.datetime(2026, 12, 31, 23, 59, tzinfo=UTC)
GRACE_SECONDS = 3600
SESSIONS = ["2026-11-20", "2026-11-23", "2026-11-24"]


def _bar(session: str, close: str, base: str = "600") -> dict:
    """OHLC-self-consistent synthetic bar (H1B fixture fix): the bar's
    close is enclosed by its own low/high by construction."""
    from decimal import Decimal

    c = Decimal(close)
    b = Decimal(base)
    low = min(b, c) - Decimal("1")
    high = max(b, c) + Decimal("1")
    return {
        "t": f"{session}T05:00:00Z",
        "o": b,
        "h": high,
        "l": low,
        "c": c,
        "v": 1000,
    }


def _result(symbol: str, sessions: list[str], start, end):
    from apps.market_gateway.historical_bars import HistoricalFetchResult

    rows = []
    for s in sessions:
        base = "600" if symbol == "SPY" else "300"
        row = _bar(s, f"{float(base) + 0.5:.2f}", base)
        row["session_date"] = s
        rows.append(row)
    return HistoricalFetchResult(
        symbol=symbol,
        start=start,
        end=end,
        rows=tuple(rows),
        pages=1,
        request_count=1,
        request_urls=(f"https://data.alpaca.markets/v2/stocks/{symbol}/bars",),
        page_tokens_seen=(),
        complete=True,
    )


def _build(results):
    from trading_lab.data.acceptance import PurposeRequirements, VendorFacts
    from trading_lab.data.historical import (
        build_historical_snapshot,
        derive_max_latency_seconds,
    )
    from trading_lab.data.historical_calendar import VersionedMarketCalendar

    calendar = VersionedMarketCalendar.from_supply(nyse_2026_fixture_supply())
    derived, _ = derive_max_latency_seconds(calendar, GRACE_SECONDS)
    requirements = PurposeRequirements(
        purpose_id="historical_research_limited_etf",
        description="H1B offline template purpose",
        data_scope="us_equities_daily_limited_etf_history",
        requires_daily_bars=True,
        requires_minute_bars=False,
        requires_corporate_actions=False,
        requires_history_membership=False,
        requires_delisting=False,
        available_at_rule="daily_close_available_next_open",
        max_missing_rate=0.001,
        min_coverage_rate=0.999,
        max_latency_seconds=derived,
        required_license_scope="personal_research",
        on_fail="RESTRICT_SCOPE",
    )
    return build_historical_snapshot(
        fetch_results=results,
        calendar=calendar,
        received_at_utc=H1A_RECEIVED_AT,
        knowledge_cutoff_utc=CUTOFF,
        requirements=requirements,
        vendor=_vendor(license_confirmed=False),
        grace_seconds=GRACE_SECONDS,
    )


def _vendor(*, license_confirmed: bool):
    from trading_lab.data.acceptance import VendorFacts

    return VendorFacts(
        license_scope="personal_research",
        license_confirmed=license_confirmed,
        history_membership_coverage="yes",
        delisting_coverage="yes",
        corporate_actions_coverage="yes",
        pit_availability="eod_only",
    )


class TestPerSymbolCompleteness:
    def test_spy_full_qqq_partial_reads_4_of_6_not_3_of_3(self):
        build = _build(
            [
                _result("SPY", SESSIONS, dt.date(2026, 11, 20), dt.date(2026, 11, 24)),
                _result("QQQ", SESSIONS[:1], dt.date(2026, 11, 20), dt.date(2026, 11, 24)),
            ]
        )
        agg = build.quality.bar_completeness
        assert (agg.denominator, agg.missing, agg.observed) == (6, 2, 4)
        per = {m.name: (m.denominator, m.missing, m.observed) for m in build.quality.per_symbol_completeness}
        assert per["bar_completeness:SPY"] == (3, 0, 3)
        assert per["bar_completeness:QQQ"] == (3, 2, 1)

    def test_partial_coverage_cannot_read_as_ready(self):
        from trading_lab.data.historical import evaluate_historical_research

        build = _build(
            [
                _result("SPY", SESSIONS, dt.date(2026, 11, 20), dt.date(2026, 11, 24)),
                _result("QQQ", SESSIONS[:1], dt.date(2026, 11, 20), dt.date(2026, 11, 24)),
            ]
        )
        from trading_lab.data.acceptance import PurposeRequirements
        from trading_lab.data.historical import derive_max_latency_seconds
        from trading_lab.data.historical_calendar import VersionedMarketCalendar

        calendar = VersionedMarketCalendar.from_supply(nyse_2026_fixture_supply())
        derived, _ = derive_max_latency_seconds(calendar, GRACE_SECONDS)
        req = PurposeRequirements(
            purpose_id="historical_research_limited_etf",
            description="H1B offline template purpose",
            data_scope="us_equities_daily_limited_etf_history",
            requires_daily_bars=True,
            requires_minute_bars=False,
            requires_corporate_actions=False,
            requires_history_membership=False,
            requires_delisting=False,
            available_at_rule="daily_close_available_next_open",
            max_missing_rate=0.001,
            min_coverage_rate=0.999,
            max_latency_seconds=derived,
            required_license_scope="personal_research",
            on_fail="RESTRICT_SCOPE",
        )
        decision = evaluate_historical_research(
            req, build.quality, _vendor(license_confirmed=True), build.manifest
        )
        assert decision.base_verdict != "ACCEPT"
        assert decision.verdict == "RESTRICT_SCOPE"
        assert any("MISSING" in r or "COVERAGE" in r for r in decision.reasons)

    def test_both_full_reads_6_of_6(self):
        build = _build(
            [
                _result("SPY", SESSIONS, dt.date(2026, 11, 20), dt.date(2026, 11, 24)),
                _result("QQQ", SESSIONS, dt.date(2026, 11, 20), dt.date(2026, 11, 24)),
            ]
        )
        agg = build.quality.bar_completeness
        assert (agg.denominator, agg.missing, agg.observed) == (6, 0, 6)

    def test_qqq_zero_rows_stays_visible(self):
        build = _build(
            [
                _result("SPY", SESSIONS, dt.date(2026, 11, 20), dt.date(2026, 11, 24)),
                _result("QQQ", [], dt.date(2026, 11, 20), dt.date(2026, 11, 24)),
            ]
        )
        agg = build.quality.bar_completeness
        assert (agg.denominator, agg.missing, agg.observed) == (6, 3, 3)
        per = {m.name: (m.denominator, m.missing, m.observed) for m in build.quality.per_symbol_completeness}
        assert per["bar_completeness:QQQ"] == (3, 3, 0)

    def test_all_zero_rows_is_inconclusive(self):
        from trading_lab.data.historical import evaluate_historical_research

        build = _build(
            [
                _result("SPY", [], dt.date(2026, 11, 20), dt.date(2026, 11, 24)),
                _result("QQQ", [], dt.date(2026, 11, 20), dt.date(2026, 11, 24)),
            ]
        )
        decision = evaluate_historical_research(
            _requirements_of(build), build.quality, _vendor(license_confirmed=True), build.manifest
        )
        assert decision.verdict == "INCONCLUSIVE"
        # empty manifest = structurally unobservable (ADR-003 D5 first
        # clause): nothing observed, nothing claimed — pit UNKNOWN, and
        # the verdict is NEVER upgraded by the cap
        assert decision.pit_level == "UNKNOWN"

    def test_disjoint_windows_covered_by_own_range(self):
        """Different requested windows: each symbol is judged against its
        OWN window's expected sessions, never the union window."""
        build = _build(
            [
                _result("SPY", SESSIONS[:2], dt.date(2026, 11, 20), dt.date(2026, 11, 23)),
                _result("QQQ", SESSIONS[1:], dt.date(2026, 11, 23), dt.date(2026, 11, 24)),
            ]
        )
        per = {m.name: (m.denominator, m.missing) for m in build.quality.per_symbol_completeness}
        assert per["bar_completeness:SPY"] == (2, 0)
        assert per["bar_completeness:QQQ"] == (2, 0)
        agg = build.quality.bar_completeness
        assert (agg.denominator, agg.missing) == (4, 0)

    def test_per_symbol_duplicate_refused_verdict_level(self):
        """Duplicate detection is per-symbol (cross-symbol same-session
        interleave is legal). The fetch-time client refuses duplicates
        outright; at the adapter a duplicated row lands in the per-symbol
        violation count and refuses any 'data ready' verdict."""
        from trading_lab.data.historical import evaluate_historical_research

        build = _build(
            [
                _result("SPY", [SESSIONS[0], SESSIONS[0]], dt.date(2026, 11, 20), dt.date(2026, 11, 20)),
                _result("QQQ", SESSIONS, dt.date(2026, 11, 20), dt.date(2026, 11, 24)),
            ]
        )
        assert build.quality.duplicate_or_out_of_order == 1
        decision = evaluate_historical_research(
            _requirements_of(build), build.quality, _vendor(license_confirmed=True), build.manifest
        )
        assert decision.base_verdict != "ACCEPT"
        assert any("DUPLICATE" in r for r in decision.reasons)

    def test_quality_report_remains_backward_compatible(self):
        """M1 compatibility: the additive per-symbol field defaults to
        empty — existing QualityReport constructors keep working and the
        M1 formula is untouched."""
        from trading_lab.data.quality import (
            LatencyStats,
            MetricResult,
            QualityReport,
        )

        report = QualityReport(
            field_coverage=(MetricResult("f", 1, 0, 1, 1.0),),
            bar_completeness=MetricResult("bar_completeness", 1, 0, 1, 1.0),
            duplicate_or_out_of_order=0,
            latency=LatencyStats(1, 0, 1.0, 1.0, 1.0),
            unknown_availability_count=0,
            license_status="personal_research",
        )
        assert report.per_symbol_completeness == ()


def _requirements_of(build):
    """Rebuild the same requirements the build used (for wrapper calls)."""
    from trading_lab.data.acceptance import PurposeRequirements
    from trading_lab.data.historical import derive_max_latency_seconds
    from trading_lab.data.historical_calendar import VersionedMarketCalendar

    calendar = VersionedMarketCalendar.from_supply(nyse_2026_fixture_supply())
    derived, _ = derive_max_latency_seconds(calendar, GRACE_SECONDS)
    return PurposeRequirements(
        purpose_id="historical_research_limited_etf",
        description="H1B offline template purpose",
        data_scope="us_equities_daily_limited_etf_history",
        requires_daily_bars=True,
        requires_minute_bars=False,
        requires_corporate_actions=False,
        requires_history_membership=False,
        requires_delisting=False,
        available_at_rule="daily_close_available_next_open",
        max_missing_rate=0.001,
        min_coverage_rate=0.999,
        max_latency_seconds=derived,
        required_license_scope="personal_research",
        on_fail="RESTRICT_SCOPE",
    )
