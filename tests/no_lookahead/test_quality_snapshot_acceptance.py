"""Quality denominators, snapshot determinism/tamper-detection, acceptance
verdict matrix, and the synthetic-vs-real evidence boundary."""

from __future__ import annotations

import datetime as dt
import sys
from decimal import Decimal
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from trading_lab.data.acceptance import (
    VERDICT_ACCEPT,
    VERDICT_BLOCKED_DATA,
    VERDICT_INCONCLUSIVE,
    DataAcceptanceConfigError,
    VendorFacts,
    evaluate_purpose,
    load_acceptance_config,
)
from trading_lab.data.quality import (
    QualityReport,
    bar_completeness,
    count_duplicate_or_out_of_order,
    field_coverage_metrics,
    latency_stats,
)
from trading_lab.data.records import MARKER_UNKNOWN_AVAILABILITY, SourceRecord
from trading_lab.data.snapshot import (
    DatasetEntry,
    SnapshotError,
    SnapshotManifest,
    build_snapshot,
    content_hash_of_rows,
)

from helpers_no_lookahead import D, NOW

CONFIG_PATH = REPO_ROOT / "configs/data_acceptance.yaml"
U = dt.timezone.utc


def source_record(available: object) -> SourceRecord:
    return SourceRecord(
        source="synthetic",
        dataset_version="v1",
        acquisition_time_utc=NOW,
        available_at_utc=available,
        raw_hash="a" * 64,
        transform_version="raw-0",
    )


def quality_report(
    missing_rate: float = 0.0,
    missing_bars: int = 0,
    duplicates: int = 0,
    latency_max: float | None = 300.0,
    samples: int = 10,
    unknown_availability: int = 0,
    inconclusive: bool = False,
) -> QualityReport:
    den = 10
    missing = int(den * missing_rate)
    metric_den = 0 if inconclusive else den
    cov = (
        field_coverage_metrics([{}] * metric_den, ["close", "ts_available_utc"])
        if metric_den == 0
        else (
            field_coverage_metrics(
                # present rows carry BOTH required fields; missing rows carry
                # neither (they are absent records, not partial ones)
                [{"close": 1, "ts_available_utc": NOW}] * (den - missing)
                + [{"close": None, "ts_available_utc": None}] * missing,
                ["close", "ts_available_utc"],
            )
        )
    )
    from trading_lab.data.quality import LatencyStats, MetricResult

    return QualityReport(
        field_coverage=cov,
        bar_completeness=MetricResult(
            name="bar_completeness",
            denominator=0 if inconclusive else 10,
            missing=missing_bars,
            observed=(0 if inconclusive else 10 - missing_bars),
            rate=None if inconclusive else (10 - missing_bars) / 10,
        ),
        duplicate_or_out_of_order=duplicates,
        latency=LatencyStats(
            sample_count=samples,
            unknown_availability_count=unknown_availability,
            min_seconds=60.0 if samples else None,
            median_seconds=120.0 if samples else None,
            max_seconds=latency_max,
        ),
        unknown_availability_count=unknown_availability,
        license_status="personal_research",
    )


class TestQualityDenominators:
    def test_zero_denominator_is_inconclusive_not_100(self):
        """零分母不得报告为 100%."""
        metrics = field_coverage_metrics([], ["close"])
        assert metrics[0].denominator == 0
        assert metrics[0].rate is None and metrics[0].is_inconclusive
        report = quality_report(inconclusive=True)
        problems = report.failures(max_missing_rate=0.01, max_latency_seconds=3600)
        assert any(p.startswith("INCONCLUSIVE") for p in problems)

    def test_missing_rate_reported_with_denominator(self):
        report = quality_report(missing_rate=0.2)
        problems = report.failures(max_missing_rate=0.01, max_latency_seconds=3600)
        assert any(p.startswith("MISSING_RATE_EXCEEDED:close:2/10") for p in problems)

    def test_latency_stats_include_sample_count_and_unknown(self):
        rows = [
            {
                "ts_event_utc": dt.datetime(2026, 11, 16, 21, 0, tzinfo=U),
                "ts_available_utc": dt.datetime(2026, 11, 16, 21, 5, tzinfo=U),
            },
            {"ts_event_utc": dt.datetime(2026, 11, 17, 21, 0, tzinfo=U)},  # no avail
        ]
        stats = latency_stats(rows)
        assert stats.sample_count == 1
        assert stats.unknown_availability_count == 1
        assert stats.max_seconds == 300.0

    def test_duplicate_and_out_of_order_counted(self):
        rows = [
            {"ts_event_utc": dt.datetime(2026, 11, 16, 21, 0, tzinfo=U)},
            {"ts_event_utc": dt.datetime(2026, 11, 16, 21, 0, tzinfo=U)},  # dup
            {"ts_event_utc": dt.datetime(2026, 11, 14, 21, 0, tzinfo=U)},  # out of order
        ]
        assert count_duplicate_or_out_of_order(rows) == 2

    def test_bar_completeness_counts_expected_sessions(self, week_sessions):
        received = {week_sessions[0], week_sessions[1]}  # 2 of 5
        m = bar_completeness(received, week_sessions)
        assert m.denominator == 5 and m.missing == 3


class TestSnapshot:
    def make_entry(self, rows: list[dict]) -> DatasetEntry:
        return DatasetEntry(
            name="daily_bars",
            content_hash=content_hash_of_rows(rows),
            row_count=len(rows),
            source=source_record(NOW),
        )

    def test_deterministic_hash(self):
        rows = [{"t": "2026-11-16", "c": "100.0"}, {"t": "2026-11-17", "c": "101.0"}]
        s1 = build_snapshot(NOW, [self.make_entry(rows)])
        s2 = build_snapshot(NOW, [self.make_entry(rows)])
        assert s1.dataset_hash == s2.dataset_hash and s1.verify()

    def test_row_order_independent(self):
        rows = [{"t": "2026-11-16", "c": "100.0"}, {"t": "2026-11-17", "c": "101.0"}]
        s1 = build_snapshot(NOW, [self.make_entry(list(reversed(rows)))])
        s2 = build_snapshot(NOW, [self.make_entry(rows)])
        assert s1.dataset_hash == s2.dataset_hash

    def test_single_value_change_changes_hash(self):
        """修改一行原始价格 → hash 必变."""
        rows_a = [{"t": "2026-11-16", "c": "100.0"}]
        rows_b = [{"t": "2026-11-16", "c": "100.5"}]
        assert content_hash_of_rows(rows_a) != content_hash_of_rows(rows_b)
        s_a = build_snapshot(NOW, [self.make_entry(rows_a)])
        s_b = build_snapshot(NOW, [self.make_entry(rows_b)])
        assert s_a.dataset_hash != s_b.dataset_hash

    def test_tampered_manifest_detected(self):
        rows = [{"t": "2026-11-16", "c": "100.0"}]
        manifest = build_snapshot(NOW, [self.make_entry(rows)])
        tampered = (
            SnapshotManifest(knowledge_cutoff_utc=manifest.knowledge_cutoff_utc,
                             entries=manifest.entries,
                             dataset_hash="f" * 64)
        )
        assert not tampered.verify()

    def test_unknown_availability_explicit_in_manifest(self):
        entry = DatasetEntry(
            name="events", content_hash="a" * 64, row_count=1,
            source=source_record(MARKER_UNKNOWN_AVAILABILITY),
        )
        snap = build_snapshot(NOW, [entry])
        assert snap.verify()
        assert not entry.source.availability_known

    def test_duplicate_dataset_names_rejected(self):
        rows = [{"t": "2026-11-16", "c": "100.0"}]
        with pytest.raises(SnapshotError):
            build_snapshot(NOW, [self.make_entry(rows), self.make_entry(rows)])


def vendor(**over) -> VendorFacts:
    base = dict(
        license_scope="personal_research",
        license_confirmed=True,
        history_membership_coverage="no",
        delisting_coverage="no",
        corporate_actions_coverage="no",
        pit_availability="none",
    )
    base.update(over)
    return VendorFacts(**base)


class TestAcceptanceVerdicts:
    def test_config_loads_and_purposes_have_all_fields(self):
        cfg = load_acceptance_config(CONFIG_PATH)
        assert cfg.version >= 1
        assert {p.purpose_id for p in cfg.purposes} >= {
            "pipeline_poc", "engineering_monitoring", "historical_research_daily",
        }
        with pytest.raises(DataAcceptanceConfigError):
            cfg.purpose("does_not_exist")

    def test_missing_threshold_is_config_error(self, tmp_path):
        import yaml

        raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
        del raw["purposes"][0]["max_missing_rate"]
        bad = tmp_path / "bad.yaml"
        bad.write_text(yaml.safe_dump(raw), encoding="utf-8")
        with pytest.raises(DataAcceptanceConfigError):
            load_acceptance_config(bad)

    def test_historical_research_blocked_on_unknown_license(self):
        cfg = load_acceptance_config(CONFIG_PATH)
        req = cfg.purpose("historical_research_daily")
        decision = evaluate_purpose(req, quality_report(), vendor(license_confirmed=False))
        assert decision.verdict == VERDICT_BLOCKED_DATA
        assert any(r.startswith("LICENSE_UNCONFIRMED") for r in decision.reasons)

    def test_historical_research_blocked_on_unknown_membership_coverage(self):
        """覆盖未知（未实测）≠ 没有：一律 BLOCKED_DATA 而非乐观 ACCEPT."""
        cfg = load_acceptance_config(CONFIG_PATH)
        req = cfg.purpose("historical_research_daily")
        decision = evaluate_purpose(
            req, quality_report(),
            vendor(history_membership_coverage="unknown", delisting_coverage="yes",
                   corporate_actions_coverage="yes"),
        )
        assert decision.verdict == VERDICT_BLOCKED_DATA
        assert any(r.startswith("HISTORY_MEMBERSHIP_COVERAGE_UNKNOWN") for r in decision.reasons)

    def test_historical_research_blocked_on_absent_membership(self):
        cfg = load_acceptance_config(CONFIG_PATH)
        req = cfg.purpose("historical_research_daily")
        decision = evaluate_purpose(req, quality_report(), vendor())
        assert decision.verdict == VERDICT_BLOCKED_DATA
        assert any(r.startswith("HISTORY_MEMBERSHIP_COVERAGE_ABSENT") for r in decision.reasons)

    def test_historical_research_accepts_only_with_event_level_pit(self):
        """R1 修正后的正例语义：event_level PIT + 全部覆盖 + 质量达标 → ACCEPT。"""
        cfg = load_acceptance_config(CONFIG_PATH)
        req = cfg.purpose("historical_research_daily")
        decision = evaluate_purpose(
            req, quality_report(),
            vendor(history_membership_coverage="yes", delisting_coverage="yes",
                   corporate_actions_coverage="yes", pit_availability="event_level"),
        )
        assert decision.verdict == VERDICT_ACCEPT

    def test_historical_research_pit_none_no_longer_accepts(self):
        """整改前缺陷回归锚点：pit=none 曾获得 ACCEPT（M1-REVIEW-REMEDIATION-001 R1）。"""
        cfg = load_acceptance_config(CONFIG_PATH)
        req = cfg.purpose("historical_research_daily")
        decision = evaluate_purpose(req, quality_report(), vendor())
        assert decision.verdict != VERDICT_ACCEPT

    def test_quality_failure_uses_declared_on_fail(self):
        cfg = load_acceptance_config(CONFIG_PATH)
        req = cfg.purpose("pipeline_poc")
        decision = evaluate_purpose(
            req, quality_report(missing_rate=0.5), vendor()
        )
        assert decision.verdict == "RESTRICT_SCOPE"
        assert any(p.startswith("MISSING_RATE_EXCEEDED") for p in decision.reasons)

    def test_unknown_availability_enforced_for_strict_rules(self):
        cfg = load_acceptance_config(CONFIG_PATH)
        req = cfg.purpose("event_research")
        decision = evaluate_purpose(
            req, quality_report(unknown_availability=7),
            vendor(delisting_coverage="yes", corporate_actions_coverage="yes",
                   pit_availability="event_level"),
        )
        assert decision.verdict == "RESTRICT_SCOPE"
        assert any(r.startswith("UNKNOWN_AVAILABILITY_PRESENT") for r in decision.reasons)

    def test_acceptance_on_real_config_and_synthetic_boundary(self):
        """The synthetic fixtures prove gate logic only; the vendor coverage
        verdicts in data-vendors.md come from DOCUMENTED evidence, and this
        test pins that the full-market research purpose is currently BLOCKED
        under those documented facts (no vendor offers membership coverage
        without a paid subscription we do not hold)."""
        cfg = load_acceptance_config(CONFIG_PATH)
        req = cfg.purpose("historical_research_daily")
        decision = evaluate_purpose(req, quality_report(), vendor())
        assert decision.verdict == VERDICT_BLOCKED_DATA
