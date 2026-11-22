"""M3-R2-T2 — sample gate (min_bars=100) vs official/smoke experiment
semantics (P1 R2-P1-1 fix), and the v2 batch governance.

RED-first evidence: written and run BEFORE the sample-gate API, the v2
protocol batch registry and the official r2 runner existed (ImportError /
ModuleNotFoundError = RED); implemented afterwards with zero weakening.

Contract under test:
- The frozen min_bars=100 threshold is NOT lowered; 99/100/101 boundary
  behavior is mechanical.
- The gate counts DATASET SESSIONS (independent bars), never equity-curve
  points (20 bars -> 21 curve points is still a 20-bar sample).
- Official engineering verdicts are REFUSED below the gate
  (OfficialRunRefused); sub-gate data may only ever be SYNTHETIC_SMOKE_ONLY.
- Arms with fewer trades than min_trades_for_stats have trade statistics
  stamped N_A — honestly not-computable, NOT "engineering invalid"; B0's
  zero-trade 0.0 return stays honest.
- Protocol v2 registers the r1 batch as legacy smoke-only (with its
  consumed budget) and the r2 batch as official; the r1 evidence ledger
  stays byte-intact.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import sys
from decimal import Decimal
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

import yaml  # noqa: E402

from trading_lab.backtest.arms import SyntheticDataset, run_arm  # noqa: E402
from trading_lab.contracts import AdjustmentKind, MarketBar  # noqa: E402
from trading_lab.validation import EvaluationProtocol  # noqa: E402
from trading_lab.validation.protocol import SampleGateVerdict  # noqa: E402

PROTOCOL_PATH = REPO_ROOT / "configs" / "evaluation_protocol.yaml"
R1_LEDGER = REPO_ROOT / "artifacts" / "evidence" / "M3" / "r1" / \
    "experiment-ledger.jsonl"


def load_runner_module():
    """Import scripts/run_m3_r2_baselines.py by path (module-level code is
    constants + pure functions only; main() is __main__-guarded)."""
    path = REPO_ROOT / "scripts" / "run_m3_r2_baselines.py"
    assert path.is_file(), "official r2 runner script must exist"
    spec = importlib.util.spec_from_file_location("run_m3_r2_baselines", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def make_dataset(n_bars: int, *, oscillating: bool = False):
    base = dt.datetime(2026, 2, 2, 21, 0, tzinfo=dt.timezone.utc)
    closes = []
    for i in range(n_bars):
        if oscillating:
            tri = i % 8
            tri = tri if tri <= 4 else 8 - tri      # 0..4 triangle, period 8
            osc = (Decimal(tri) - Decimal(2)) * Decimal("1.2")  # -2.4..+2.4
            closes.append(Decimal("100") + Decimal("0.05") * i + osc)
        else:
            closes.append(Decimal("100") + Decimal("0.3") * i)
    bars = [MarketBar.model_validate(dict(
        asset_id="SYN-ETF", ts_event_utc=base + dt.timedelta(days=i),
        ts_available_utc=base + dt.timedelta(days=i),
        interval="1d", open=c, high=c + Decimal("0.5"), low=c - Decimal("0.5"),
        close=c, volume=Decimal("5000000"), source="synthetic",
        adjustment=AdjustmentKind.RAW, quality="ok"))
        for i, c in enumerate(closes)]
    return SyntheticDataset(name=f"probe-{n_bars}-bars", bars={"SYN-ETF": bars})


# ---------------------------------------------------------------------------
# protocol v2: batch registry + unlowered threshold
# ---------------------------------------------------------------------------


class TestProtocolV2BatchGovernance:
    def test_v2_protocol_registers_r1_legacy_and_r2_official_batches(self):
        p = EvaluationProtocol.load(PROTOCOL_PATH)
        assert p.protocol_id == "m3-synthetic-engineering-v2"
        assert p.protocol_version == 2
        batches = p.experiment_batches
        r1 = batches["m3-r1-batch-1"]
        assert r1["status"] == "SYNTHETIC_SMOKE_ONLY_LEGACY"
        assert r1["sample_gate"] == "INSUFFICIENT_SAMPLE"
        assert int(r1["dataset_bars"]) == 20
        # r1 consumed budget is REGISTERED, not erased
        consumed = r1["consumed_budget"]
        assert consumed["trials"] == 9 and consumed["queries"] == 4
        assert consumed["per_arm_trials"] == {
            "B0_cash": 3, "B1_buy_hold": 3, "B2_single_rule": 3}
        assert r1["protocol_hash"].startswith("48dee861")
        assert r1["code_hash_scope"] == "RUNNER_ONLY_LEGACY"
        assert r1["code_hash"].startswith("c0a9ede5")
        r2 = batches["m3-r2-batch-1"]
        assert r2["status"] == "OFFICIAL_SYNTHETIC_ENFORCE_SAMPLE_GATE"
        assert int(r2["dataset_bars_min"]) >= 100

    def test_min_bars_not_lowered_and_per_arm_budget_structure_kept(self):
        """Anti-lowering pin: the frozen sample threshold stays 100; the
        equal-trial structure stays per-arm 3/3/3 for the official batch."""
        p = EvaluationProtocol.load(PROTOCOL_PATH)
        v = p.validation_thresholds
        assert int(v["min_bars"]) == 100
        assert int(v["min_trades_for_stats"]) == 10
        assert v["require_conservation_check"] is True
        tb = p.equal_trial_budget()
        assert tb["per_arm_trials"] == {
            "B0_cash": 3, "B1_buy_hold": 3, "B2_single_rule": 3}
        payload = yaml.safe_load(PROTOCOL_PATH.read_text(encoding="utf-8"))
        assert payload["budget"]["max_total_trials"] == 100

    def test_r1_ledger_file_stays_byte_intact(self):
        """The legacy ledger is read-only history: still exactly 13 chain
        entries (4 queries + 9 trials), all bound to v1.1 + legacy hash."""
        lines = [json.loads(l) for l in
                 R1_LEDGER.read_text(encoding="utf-8").splitlines()
                 if l.strip()]
        assert len(lines) == 13
        kinds = [e["kind"] for e in lines]
        assert kinds.count("QUERY") == 4 and kinds.count("TRIAL") == 9
        for e in lines:
            assert e["protocol_hash"].startswith("48dee861")
            assert e["code_hash"].startswith("c0a9ede5")


# ---------------------------------------------------------------------------
# sample gate API: mechanical boundary
# ---------------------------------------------------------------------------


class TestSampleGate:
    def test_gate_api_boundary_99_100_101(self):
        p = EvaluationProtocol.load(PROTOCOL_PATH)
        below = p.sample_gate(99)
        assert isinstance(below, SampleGateVerdict)
        assert below.satisfied is False
        assert below.verdict == "INSUFFICIENT_SAMPLE"
        assert below.role == "SMOKE_ONLY"
        at = p.sample_gate(100)
        assert at.satisfied is True
        assert at.verdict == "SATISFIED"
        assert at.role == "OFFICIAL_ENGINEERING_RUN"
        assert p.sample_gate(101).satisfied is True
        assert at.min_bars == 100 and below.min_bars == 100

    def test_gate_verdict_is_reportable_not_alpha(self):
        p = EvaluationProtocol.load(PROTOCOL_PATH)
        g = p.sample_gate(1000)
        assert g.verdict == "SATISFIED"
        assert p.max_claimable_evidence == "ENGINEERING_ONLY"  # scope unchanged


# ---------------------------------------------------------------------------
# results stamping: sessions vs curve points, trade-stats honesty
# ---------------------------------------------------------------------------


class TestResultStamping:
    def test_gate_counts_bars_not_curve_points(self):
        """20 sessions produce 21 equity-curve points; the stamp must say
        INSUFFICIENT_SAMPLE with sample_bars=20 — no point-inflation."""
        protocol = EvaluationProtocol.load(PROTOCOL_PATH)
        ds = make_dataset(20)
        r = run_arm("B1_buy_hold", ds, protocol, seed=42, code_hash="c" * 32)
        assert r.effective_observations == 21  # curve points, NOT the sample
        assert r.sample_bars == 20
        assert r.sample_gate_verdict == "INSUFFICIENT_SAMPLE"

    def test_satisfied_dataset_stamps_official_role(self):
        protocol = EvaluationProtocol.load(PROTOCOL_PATH)
        ds = make_dataset(120)
        r = run_arm("B1_buy_hold", ds, protocol, seed=42, code_hash="c" * 32)
        assert r.sample_bars == 120
        assert r.sample_gate_verdict == "SATISFIED"

    def test_zero_trade_arm_is_na_not_invalid(self):
        """B0 trades nothing: its trade statistics are honestly N_A; the
        engineering evidence class is unchanged (not 'all invalid')."""
        protocol = EvaluationProtocol.load(PROTOCOL_PATH)
        ds = make_dataset(120)
        r = run_arm("B0_cash", ds, protocol, seed=42, code_hash="c" * 32)
        assert r.fills == 0
        assert r.trade_stats_status == "N_A_INSUFFICIENT_TRADES"
        d = r.as_dict()
        assert d["trade_stats_status"] == "N_A_INSUFFICIENT_TRADES"
        assert d["net_return"] == "0.0000"  # honest zero, no fabricated carry
        assert d["evidence_class"] == "SYNTHETIC_ENGINEERING_ONLY"

    def test_trade_stats_gate_threshold_9_10(self):
        p = EvaluationProtocol.load(PROTOCOL_PATH)
        assert p.trade_stats_gate(9) == "N_A_INSUFFICIENT_TRADES"
        assert p.trade_stats_gate(10) == "OK"
        assert p.trade_stats_gate(11) == "OK"

    def test_armresult_status_consistent_with_its_own_fills(self):
        protocol = EvaluationProtocol.load(PROTOCOL_PATH)
        ds = make_dataset(160, oscillating=True)
        r = run_arm("B2_single_rule", ds, protocol, seed=42,
                    code_hash="c" * 32, ma_params=(2, 4))
        assert r.fills >= 10, f"fixture must clear the stats gate: {r.fills}"
        assert r.trade_stats_status == "OK"
        assert r.sample_gate_verdict == "SATISFIED"


# ---------------------------------------------------------------------------
# official runner: refuses below-gate data before any verdict
# ---------------------------------------------------------------------------


class TestOfficialRunnerGate:
    def test_official_sample_gate_refuses_20_bar_dataset(self):
        mod = load_runner_module()
        protocol = EvaluationProtocol.load(PROTOCOL_PATH)
        ds = make_dataset(20)
        with pytest.raises(mod.OfficialRunRefused, match="min_bars"):
            mod.official_sample_gate(protocol, ds)

    def test_official_dataset_has_100_plus_sessions_and_passes_gate(self):
        mod = load_runner_module()
        protocol = EvaluationProtocol.load(PROTOCOL_PATH)
        ds = mod.build_dataset()
        gate = mod.official_sample_gate(protocol, ds)
        assert gate.satisfied is True
        sessions = len({b.ts_event_utc for bars in ds.bars.values()
                        for b in bars})
        assert gate.n_bars == sessions >= 100
        # fully synthetic, hash-bound
        assert all(b.source == "synthetic" for bars in ds.bars.values()
                   for b in bars)
        assert len(ds.dataset_hash) == 64
