"""M1-REVIEW-REMEDIATION-001 — RED-phase reproduction tests (R1/R2/R3/R5).

Each test reproduces a review finding against the pre-fix implementation.
R4 (architecture checker self-tests) lives in tests/architecture/.
"""

from __future__ import annotations

import datetime as dt
import sys
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

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
from trading_lab.data.membership import DelistingRecord, MembershipError, MembershipRecord, MembershipTable
from trading_lab.data.quality import QualityReport, MetricResult
from trading_lab.data.snapshot import DatasetEntry, build_snapshot, content_hash_of_rows, research_admissible

from conftest import NOW
from test_quality_snapshot_acceptance import quality_report, vendor, CONFIG_PATH

U = dt.timezone.utc


# ---------------------------------------------------------------------------
# R1 — PIT capability must materially gate admission
# ---------------------------------------------------------------------------


class TestR1PitCapabilityMatrix:
    def test_full_research_pit_none_must_not_accept(self):
        """其他条件全部满足但 PIT=none → 不得 ACCEPT（整改前：vendor() 默认
        pit_availability='none' 仍 ACCEPT——缺陷复现）。"""
        cfg = load_acceptance_config(CONFIG_PATH)
        req = cfg.purpose("historical_research_daily")
        perfect = vendor(
            history_membership_coverage="yes",
            delisting_coverage="yes",
            corporate_actions_coverage="yes",
            pit_availability="none",  # known-absent PIT capability
        )
        decision = evaluate_purpose(req, quality_report(), perfect)
        assert decision.verdict != VERDICT_ACCEPT
        assert any(r.startswith("PIT_CAPABILITY_ABSENT") for r in decision.reasons)

    def test_full_research_pit_unknown_blocked(self):
        cfg = load_acceptance_config(CONFIG_PATH)
        req = cfg.purpose("historical_research_daily")
        decision = evaluate_purpose(
            req, quality_report(),
            vendor(
                history_membership_coverage="yes", delisting_coverage="yes",
                corporate_actions_coverage="yes", pit_availability="unknown",
            ),
        )
        assert decision.verdict == VERDICT_BLOCKED_DATA
        assert any(r.startswith("PIT_CAPABILITY_UNKNOWN") for r in decision.reasons)

    def test_event_research_eod_only_insufficient(self):
        """事件研究不能由仅 EOD 的供应商冒充事件级可得性。"""
        cfg = load_acceptance_config(CONFIG_PATH)
        req = cfg.purpose("event_research")
        decision = evaluate_purpose(
            req, quality_report(),
            vendor(
                delisting_coverage="yes", corporate_actions_coverage="yes",
                pit_availability="eod_only",
            ),
        )
        assert decision.verdict != VERDICT_ACCEPT
        assert any(r.startswith("PIT_GRANULARITY_INSUFFICIENT") for r in decision.reasons)

    def test_bar_purpose_pit_none_restricted(self):
        cfg = load_acceptance_config(CONFIG_PATH)
        req = cfg.purpose("pipeline_poc")
        decision = evaluate_purpose(req, quality_report(), vendor(pit_availability="none"))
        assert decision.verdict != VERDICT_ACCEPT
        assert any(r.startswith("PIT_CAPABILITY_ABSENT") for r in decision.reasons)

    def test_full_research_accepts_only_with_event_level_pit(self):
        """正例：event_level + 全部覆盖满足 → ACCEPT（更新后的正例语义）。"""
        cfg = load_acceptance_config(CONFIG_PATH)
        req = cfg.purpose("historical_research_daily")
        decision = evaluate_purpose(
            req, quality_report(),
            vendor(
                history_membership_coverage="yes", delisting_coverage="yes",
                corporate_actions_coverage="yes", pit_availability="event_level",
            ),
        )
        assert decision.verdict == VERDICT_ACCEPT

    def test_available_at_rule_typo_rejected_at_load(self, tmp_path):
        """自由文本规则的最小合法值校验：拼写错误不得悄悄形成宽松准入。"""
        raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
        raw["purposes"][0]["available_at_rule"] = "bar_plus_whenever"
        bad = tmp_path / "bad.yaml"
        bad.write_text(yaml.safe_dump(raw), encoding="utf-8")
        with pytest.raises(DataAcceptanceConfigError):
            load_acceptance_config(bad)


# ---------------------------------------------------------------------------
# R2 — single authoritative quality formula; min_coverage_rate consumed
# ---------------------------------------------------------------------------


class TestR2QualityThresholds:
    def test_inconsistent_coverage_missing_config_rejected(self, tmp_path):
        """min_coverage_rate < 1 - max_missing_rate = 误导性死配置 → 加载即拒。"""
        raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
        raw["purposes"][0]["max_missing_rate"] = 0.05
        raw["purposes"][0]["min_coverage_rate"] = 0.90  # complement is 0.95
        bad = tmp_path / "bad.yaml"
        bad.write_text(yaml.safe_dump(raw), encoding="utf-8")
        with pytest.raises(DataAcceptanceConfigError):
            load_acceptance_config(bad)

    def test_stricter_min_coverage_is_consumed(self, tmp_path):
        """min_coverage 严于互补值时必须真实参与判定（整改前：从未被消费）。"""
        raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
        raw["purposes"][0]["max_missing_rate"] = 0.05
        raw["purposes"][0]["min_coverage_rate"] = 0.98  # stricter than 0.95
        strict = tmp_path / "strict.yaml"
        strict.write_text(yaml.safe_dump(raw), encoding="utf-8")
        cfg = load_acceptance_config(strict)
        req = cfg.purpose("pipeline_poc")
        # missing 5% -> missing_rate OK vs 0.05, but coverage 0.95 < 0.98 -> fail
        decision = evaluate_purpose(req, quality_report(missing_rate=0.1), vendor(pit_availability="eod_only"))
        assert decision.verdict != VERDICT_ACCEPT
        assert any(r.startswith("COVERAGE_RATE_BELOW_MIN") for r in decision.reasons)

    def test_bar_missing_within_tolerance_not_a_failure(self):
        """bar 缺失率与字段缺失率同一公式与同一阈值（整改前：缺 1 根即失败）。"""
        report = quality_report(missing_bars=1)
        # 10 bars, 1 missing = 10% > default tolerances? construct explicit case:
        small = QualityReport(
            field_coverage=report.field_coverage,
            bar_completeness=MetricResult(name="bar_completeness", denominator=100, missing=1, observed=99, rate=0.99),
            duplicate_or_out_of_order=0,
            latency=report.latency,
            unknown_availability_count=0,
            license_status="personal_research",
        )
        problems = small.failures(max_missing_rate=0.05, max_latency_seconds=3600)
        assert not any(p.startswith("BARS_MISSING") for p in problems)

    def test_bar_missing_exceeding_tolerance_fails(self):
        from trading_lab.data.quality import MetricResult

        report = quality_report()
        big = QualityReport(
            field_coverage=report.field_coverage,
            bar_completeness=MetricResult(name="bar_completeness", denominator=100, missing=6, observed=94, rate=0.94),
            duplicate_or_out_of_order=0,
            latency=report.latency,
            unknown_availability_count=0,
            license_status="personal_research",
        )
        problems = big.failures(max_missing_rate=0.05, max_latency_seconds=3600)
        assert any(p.startswith("BARS_MISSING") for p in problems)

    def test_zero_denominators_give_inconclusive_verdict(self):
        cfg = load_acceptance_config(CONFIG_PATH)
        req = cfg.purpose("pipeline_poc")
        decision = evaluate_purpose(
            req, quality_report(inconclusive=True), vendor(pit_availability="eod_only")
        )
        assert decision.verdict == VERDICT_INCONCLUSIVE

    def test_latency_zero_samples_inconclusive_not_accept(self):
        cfg = load_acceptance_config(CONFIG_PATH)
        req = cfg.purpose("pipeline_poc")
        decision = evaluate_purpose(
            req, quality_report(samples=0, latency_max=None), vendor(pit_availability="eod_only")
        )
        assert decision.verdict == VERDICT_INCONCLUSIVE

    def test_priority_frozen_license_blocker_beats_zero_denominator(self):
        """零分母与许可不明并存 → 判定顺序冻结：BLOCKED_DATA 优先。"""
        cfg = load_acceptance_config(CONFIG_PATH)
        req = cfg.purpose("pipeline_poc")
        decision = evaluate_purpose(
            req, quality_report(inconclusive=True), vendor(pit_availability="eod_only", license_confirmed=False)
        )
        assert decision.verdict == VERDICT_BLOCKED_DATA
        assert any(r.startswith("LICENSE_UNCONFIRMED") for r in decision.reasons)


# ---------------------------------------------------------------------------
# R3 — membership interval overlaps must be rejected
# ---------------------------------------------------------------------------


def A(*a) -> dt.datetime:
    return dt.datetime(*a, tzinfo=U)


def mem(index_id: str, symbol: str, frm: dt.datetime, to: dt.datetime | None) -> MembershipRecord:
    return MembershipRecord(
        index_id=index_id, symbol=symbol, effective_from=frm, effective_to=to,
        announced_at=frm, available_at=frm, source="synthetic",
    )


class TestR3IntervalOverlaps:
    def test_overlapping_different_starts_rejected(self):
        with pytest.raises(MembershipError):
            MembershipTable(
                membership=[
                    mem("SPX", "X", A(2000, 1, 1), A(2010, 1, 1)),
                    mem("SPX", "X", A(2005, 1, 1), A(2020, 1, 1)),
                ],
                delistings=[],
            )

    def test_same_start_different_ends_rejected(self):
        with pytest.raises(MembershipError):
            MembershipTable(
                membership=[
                    mem("SPX", "X", A(2000, 1, 1), A(2010, 1, 1)),
                    mem("SPX", "X", A(2000, 1, 1), A(2005, 1, 1)),
                ],
                delistings=[],
            )

    def test_open_ended_then_new_record_rejected(self):
        with pytest.raises(MembershipError):
            MembershipTable(
                membership=[
                    mem("SPX", "X", A(2000, 1, 1), None),
                    mem("SPX", "X", A(2010, 1, 1), A(2020, 1, 1)),
                ],
                delistings=[],
            )

    def test_touching_boundaries_allowed(self):
        table = MembershipTable(
            membership=[
                mem("SPX", "X", A(2000, 1, 1), A(2010, 1, 1)),
                mem("SPX", "X", A(2010, 1, 1), A(2020, 1, 1)),
            ],
            delistings=[],
        )
        assert table.universe_asof(A(2005, 1, 1), "SPX") == frozenset({"X"})
        assert table.universe_asof(A(2015, 1, 1), "SPX") == frozenset({"X"})

    def test_same_symbol_different_index_overlaps_allowed(self):
        MembershipTable(
            membership=[
                mem("SPX", "X", A(2000, 1, 1), A(2010, 1, 1)),
                mem("NDX", "X", A(2005, 1, 1), A(2020, 1, 1)),
            ],
            delistings=[],
        )

    def test_gap_between_intervals_allowed(self):
        MembershipTable(
            membership=[
                mem("SPX", "X", A(2000, 1, 1), A(2005, 1, 1)),
                mem("SPX", "X", A(2010, 1, 1), A(2020, 1, 1)),
            ],
            delistings=[],
        )


# ---------------------------------------------------------------------------
# R5 — snapshot integrity is not research PIT admission
# ---------------------------------------------------------------------------


def entry(available: object) -> DatasetEntry:
    return DatasetEntry(
        name="daily_bars",
        content_hash=content_hash_of_rows([{"t": "2026-11-16", "c": "100.0"}]),
        row_count=1,
        source=__import__("trading_lab.data.records", fromlist=["SourceRecord"]).SourceRecord(
            source="synthetic", dataset_version="v1", acquisition_time_utc=NOW,
            available_at_utc=available, raw_hash="a" * 64, transform_version="raw-0",
        ),
    )


class TestR5SnapshotPitGate:
    def test_unknown_availability_hash_valid_but_not_research_admissible(self):
        manifest = build_snapshot(NOW, [entry(MARKER := "UNKNOWN_AVAILABILITY")])
        assert manifest.verify()  # hash integrity holds
        result = research_admissible(manifest)
        assert not result.ok
        assert any("UNKNOWN_AVAILABILITY" in r for r in result.reasons)

    def test_available_after_cutoff_hash_valid_but_not_admissible(self):
        late = NOW + dt.timedelta(hours=1)
        manifest = build_snapshot(NOW, [entry(late)])
        assert manifest.verify()
        result = research_admissible(manifest)
        assert not result.ok
        assert any(r.startswith("AVAILABLE_AFTER_CUTOFF") for r in result.reasons)

    def test_legal_manifest_admissible(self):
        manifest = build_snapshot(NOW, [entry(NOW - dt.timedelta(hours=1))])
        assert manifest.verify()
        assert research_admissible(manifest).ok

    def test_tampered_manifest_fails_both(self):
        manifest = build_snapshot(NOW, [entry(NOW)])
        broken = type(manifest)(manifest.knowledge_cutoff_utc, manifest.entries, "f" * 64)
        assert not broken.verify()
        assert not research_admissible(broken).ok


from trading_lab.data.records import MARKER_UNKNOWN_AVAILABILITY as MARKER  # noqa: E402
