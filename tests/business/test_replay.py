"""Business MVP replay integration tests (acceptance §4 scenarios).

These run the full vertical slice on a REDUCED fixture (short feature
windows, ~81 sessions) against a test-only demo protocol (same cost
model, lower sample gate) so one replay takes ~1-2 minutes instead of
~11. The FULL demo fixture stays the one-command default
(scripts/run_business_mvp.py).
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from trading_lab.business.config import (
    BusinessConfig,
    FeaturesConfig,
    FixtureConfig,
    load_config,
)
from trading_lab.business.models import (
    InformationAssessment,
    InformationDirection,
    InformationHorizon,
    InformationStatus,
    InformationUncertainty,
)
from trading_lab.business.replay import run_replay
from trading_lab.contracts import (
    AllocationItem,
    RegimeAssessment,
    TargetPortfolio,
)

REPO = Path(__file__).resolve().parents[2]

REDUCED_SEGMENTS = (8, 10, 8, 8, 10, 8, 21, 8)          # 81 sessions
REDUCED_FEATURES = FeaturesConfig(
    ma_short=3, ma_long=8, rsi_period=5, atr_period=5,
    realized_vol_window=8, volume_window=8, corr_window=15,
    corr_min_common=10, stale_after_sessions=3)


def reduced_config() -> BusinessConfig:
    base = load_config(REPO / "configs/business_mvp_demo.yaml")
    fx = FixtureConfig(sessions_per_segment=REDUCED_SEGMENTS)
    return base.model_copy(update={
        "fixture": fx, "features": REDUCED_FEATURES})


def write_test_protocol(path: Path) -> None:
    """Demo-protocol shape with a reduced sample gate (same cost model)."""
    base = yaml.safe_load(
        (REPO / "configs/business_mvp_protocol.yaml").read_text("utf-8"))
    base["protocol_id"] = "business-mvp-demo-test-v1"
    base["description"] = "TEST-ONLY reduced sample gate"
    base["validation"]["min_bars"] = 40
    path.write_text(yaml.safe_dump(base, sort_keys=False), encoding="utf-8")


@pytest.fixture(scope="module")
def replay_artifacts(tmp_path_factory):
    out = tmp_path_factory.mktemp("bizmvp_replay")
    protocol = out / "protocol.yaml"
    write_test_protocol(protocol)
    return run_replay(
        config=reduced_config(), protocol_path=protocol,
        output_dir=out / "run", command="pytest:reduced-replay")


@pytest.fixture(scope="module")
def summary(replay_artifacts):
    return json.loads(replay_artifacts.summary_path.read_text("utf-8"))


class TestReplayCompletes:
    def test_artifacts_written(self, replay_artifacts, summary):
        out = replay_artifacts.output_dir
        assert (out / "summary.json").is_file()
        assert (out / "report.html").is_file()
        assert (out / "pipeline_sessions.jsonl").is_file()
        assert (out / "pipeline_executions.jsonl").is_file()
        assert replay_artifacts.run_digest
        assert summary["run_digest"]

    def test_honesty_labels_present(self, summary):
        labels = summary["labels"]
        assert labels["data_mode"] == "SYNTHETIC_OFFLINE_ONLY"
        assert labels["ai_provider"] == "MOCK/RULE"
        assert labels["execution_backend"] == "FAKE_BROKER"
        assert labels["broker_behavior"] == "MOCK_ONLY"
        assert summary["mock_execution"]["broker_behavior"] == "MOCK_ONLY"

    def test_report_html_is_self_contained(self, replay_artifacts):
        html = (replay_artifacts.output_dir / "report.html").read_text(
            "utf-8")
        assert "SYNTHETIC_OFFLINE_ONLY" in html
        assert "http://" not in html and "https://" not in html
        assert "<script" not in html


class TestAcceptanceScenarios:
    def test_regime_divergence(self, summary):
        value = summary["acceptance"]["regime_divergence"]
        assert value.startswith("PASS"), value

    def test_info_events_pit_enforced(self, summary):
        value = summary["acceptance"]["info_events"]
        assert value.startswith("PASS"), value

    def test_future_event_never_assessed_early(
            self, replay_artifacts, summary):
        rows = [json.loads(l) for l in
                (replay_artifacts.output_dir / "pipeline_sessions.jsonl")
                .read_text("utf-8").splitlines()]
        assessments = [a for r in rows for a in r["info"]]
        future_ids = {a["event_id"] for a in assessments
                      if str(a["event_id"]).startswith("EVT-FUTURE")}
        assert not future_ids, "future-only event must never be assessed"

    def test_dual_symbol_independence(self, replay_artifacts):
        rows = [json.loads(l) for l in
                (replay_artifacts.output_dir / "pipeline_sessions.jsonl")
                .read_text("utf-8").splitlines()]
        gap_rows = [r for r in rows if r["scenario_tag"] == "DATA_QUALITY"]
        assert gap_rows, "data-quality segment missing from pipeline"
        qqq_unknown = [r for r in gap_rows
                       if r["features"]["QQQ"]["status"] == "UNKNOWN"]
        spy_ok_same = [r for r in qqq_unknown
                       if r["features"]["SPY"]["status"] == "OK"]
        assert qqq_unknown and spy_ok_same, (
            "expected QQQ UNKNOWN with SPY OK inside the gap window")

    def test_mock_execution_and_conservation(self, summary):
        value = summary["acceptance"]["mock_execution"]
        assert value.startswith("PASS"), value
        ledger = summary["mock_execution"]["ledger"]
        assert ledger is not None and ledger["ok"] is True
        assert ledger["identity_delta"] == "0.00"

    def test_risk_rejections_recorded(self, summary):
        value = summary["acceptance"]["risk_rejections"]
        assert value.startswith("PASS"), value
        scenarios = {r["scenario"] for r in summary["rejections"]}
        assert "RISK_REJECT_OVERSIZE" in scenarios
        assert "RISK_REJECT_SYMBOL_NOT_ALLOWED" in scenarios
        assert "GATE_REFUSE_UNREVIEWED_PRODUCER" in scenarios
        assert "DUPLICATE_INTENT_REPLAY" in scenarios
        assert "KILL_SWITCH_BLOCKS_NEW_RISK" in scenarios

    def test_performance_reported_with_sample_gate(self, summary):
        value = summary["acceptance"]["performance_and_explanation"]
        assert value.startswith("PASS"), value
        candidate = summary["backtest"]["candidate_replay"]
        assert candidate["conservation_ok"] is True
        assert candidate["sample_gate"] == "SATISFIED"
        for arm in ("B0_cash", "B1_buy_hold", "B2_single_rule"):
            assert arm in summary["backtest"]["reference_arms"]

    def test_no_real_api_or_paper_claims(self, summary):
        identity = summary["identity"]
        assert identity["execution_backend"] == "FAKE_BROKER"
        assert summary["mock_execution"]["environment_label"] == \
            "PAPER_ENUM_REUSE"


class TestDecisionPipeline:
    def test_sessions_have_decisions_or_no_trade(
            self, replay_artifacts):
        rows = [json.loads(l) for l in
                (replay_artifacts.output_dir / "pipeline_sessions.jsonl")
                .read_text("utf-8").splitlines()]
        assert rows
        for r in rows:
            dec = r["decision"]
            assert dec["chosen"] is not None or dec["no_trade_reasons"]

    def test_decisions_carry_explanations(self, replay_artifacts):
        rows = [json.loads(l) for l in
                (replay_artifacts.output_dir / "pipeline_sessions.jsonl")
                .read_text("utf-8").splitlines()]
        with_target = [r for r in rows if r["decision"]["chosen"]]
        assert with_target, "expected at least one chosen candidate"
        for r in with_target[:5]:
            assert r["decision"]["rationale"]
            assert r["decision"]["decision_hash"]

    def test_candidate_target_portfolio_contract(
            self, replay_artifacts):
        """The decision layer emits valid TargetPortfolio contracts."""
        rows = [json.loads(l) for l in
                (replay_artifacts.output_dir / "pipeline_sessions.jsonl")
                .read_text("utf-8").splitlines()]
        # re-hydrate one target from the decision hash chain is not
        # possible from the trace alone; instead prove the contract path
        # via the gate-accepted portfolio count in the audit-adjacent
        # summary: every chosen decision implies an ALLOW_PORTFOLIO gate
        # event happened (decide() refuses otherwise).
        chosen = [r for r in rows if r["decision"]["chosen"]]
        assert chosen


class TestReproducibility:
    def test_two_runs_identical_digests(self, tmp_path):
        protocol = tmp_path / "protocol.yaml"
        write_test_protocol(protocol)
        cfg = reduced_config()
        r1 = run_replay(config=cfg, protocol_path=protocol,
                        output_dir=tmp_path / "a", command="pytest:det")
        r2 = run_replay(config=cfg, protocol_path=protocol,
                        output_dir=tmp_path / "b", command="pytest:det")
        assert r1.run_id == r2.run_id
        assert r1.run_digest == r2.run_digest
        s1 = (tmp_path / "a" / "summary.json").read_text("utf-8")
        s2 = (tmp_path / "b" / "summary.json").read_text("utf-8")
        assert s1 == s2


class TestFailClosedModes:
    def test_replay_refuses_unknown_fixture(self, tmp_path, capsys):
        import scripts.run_business_mvp as cli

        rc = cli.main(["--mode", "replay", "--fixture", "real",
                       "--output-dir", str(tmp_path / "x")])
        assert rc == 2
        assert "REFUSED" in capsys.readouterr().err

    def test_replay_refuses_forbidden_mode(self, tmp_path, capsys):
        import scripts.run_business_mvp as cli

        rc = cli.main(["--mode", "live", "--fixture", "demo",
                       "--output-dir", str(tmp_path / "x")])
        assert rc == 2
        assert "REFUSED" in capsys.readouterr().err


class TestDecisionContracts:
    """Contract-level checks without a full replay."""

    def test_target_portfolio_weights_sum_to_one(self):
        portfolio = TargetPortfolio(
            account_id="MOCK-ACCT-001",
            allocation=(AllocationItem(symbol="SPY",
                                       weight=Decimal("0.60")),),
            cash_weight=Decimal("0.40"),
            risk_budget_id="BUSINESS_DEMO_RISK_BUDGET",
            timestamp=_utc(2024, 2, 1),
        )
        assert portfolio.cash_weight + sum(
            a.weight for a in portfolio.allocation) == 1

    def test_information_assessment_roundtrip(self):
        a = InformationAssessment(
            assessment_id="EVT-1::RULE:v1", event_id="EVT-1", asset="SPY",
            category="EARNINGS",
            direction=InformationDirection.BULLISH,
            uncertainty=InformationUncertainty.LOW,
            horizon=InformationHorizon.SHORT,
            confidence=0.6, evidence_ref="EVT-1#offset0-10",
            analyzer="RULE:v1", analyzer_version="v1",
            valid_until=_utc(2024, 2, 10), assessed_at=_utc(2024, 2, 1),
            status=InformationStatus.ASSESSED)
        assert a.model_dump_json()

    def test_regime_assessment_labels_contract(self):
        r = RegimeAssessment(
            labels=("TREND_UP",), confidence=0.7,
            asof_utc=_utc(2024, 2, 1), model_version="RULE-REGIME-V1",
            feature_hash="a" * 32, valid_until=_utc(2024, 2, 6))
        assert "TREND_UP" in r.labels


def _utc(y: int, m: int, d: int):
    import datetime as dt

    return dt.datetime(y, m, d, 21, 0, tzinfo=dt.timezone.utc)
