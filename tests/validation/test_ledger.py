"""M3-R1-T5 — experiment ledger: append-only, hash-chained, budget
fail-closed, ALL_BILLED accounting.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

from trading_lab.validation.ledger import (  # noqa: E402
    BudgetExceeded,
    ExperimentLedger,
)

LIMITS = {
    "max_total_trials": 5,
    "max_search_queries": 3,
    "max_failures_before_halt": 2,
    "max_hypotheses": 2,
    "max_holdout_unlocks": 1,
    "per_arm_trials": {"B2_single_rule": 1, "B1_buy_hold": 1},
}


def make_ledger(tmp_path, limits=LIMITS):
    return ExperimentLedger(
        tmp_path / "ledger.jsonl", limits=limits,
        protocol_hash="p" * 32, code_hash="c" * 32)


class TestAppendOnlyAccounting:
    def test_successes_failures_and_retries_all_billed(self, tmp_path):
        led = make_ledger(tmp_path)  # B0_cash: no per-arm cap in LIMITS
        led.register_trial("B0_cash", seed=42, dataset_hash="d" * 32)
        led.register_failure("B0_cash", seed=42, dataset_hash="d" * 32,
                             error="boom")
        led.register_retry("B0_cash", seed=42, dataset_hash="d" * 32)
        c = led.counters()
        assert c["trials"] == 1 and c["failures"] == 1 and c["retries"] == 1
        # failures/retries bill the arm's equal-trial budget too
        assert led.arm_trials()["B0_cash"] == 3
        led.close()

    def test_per_arm_budget_fail_closed(self, tmp_path):
        led = make_ledger(tmp_path)
        led.register_trial("B2_single_rule", seed=1, dataset_hash="d" * 32)
        with pytest.raises(BudgetExceeded, match="per-arm trial budget"):
            led.register_trial("B2_single_rule", seed=2,
                               dataset_hash="d" * 32)
        # the refusal itself is on the ledger — counts never shrink
        assert led.counters()["trials"] == 1
        led.close()

    def test_global_trial_budget_fail_closed(self, tmp_path):
        limits = dict(LIMITS, per_arm_trials={})
        led = make_ledger(tmp_path, limits=limits)
        for i in range(5):
            led.register_trial("B0_cash", seed=i, dataset_hash="d" * 32)
        with pytest.raises(BudgetExceeded, match="max_total_trials"):
            led.register_trial("B0_cash", seed=99, dataset_hash="d" * 32)
        refusals = [json.loads(l) for l in
                    (tmp_path / "ledger.jsonl").read_text(
                        encoding="utf-8").splitlines()
                    if "BUDGET_REFUSAL" in l]
        assert len(refusals) == 1
        led.close()

    def test_query_budget_fail_closed(self, tmp_path):
        led = make_ledger(tmp_path)
        for i in range(3):
            led.register_query(note=f"q{i}")
        with pytest.raises(BudgetExceeded, match="max_search_queries"):
            led.register_query(note="one too many")
        led.close()

    def test_failure_halt_freezes_research(self, tmp_path):
        led = make_ledger(tmp_path)
        led.register_failure("B0_cash", seed=1, dataset_hash="d" * 32,
                             error="f1")
        led.register_failure("B0_cash", seed=2, dataset_hash="d" * 32,
                             error="f2")
        assert led.halted  # max_failures_before_halt == 2 reached
        with pytest.raises(BudgetExceeded, match="HALT"):
            led.register_trial("B0_cash", seed=3, dataset_hash="d" * 32)
        led.close()

    def test_halt_survives_restart(self, tmp_path):
        led = make_ledger(tmp_path)
        led.register_failure("B0_cash", seed=1, dataset_hash="d" * 32,
                             error="f1")
        led.register_failure("B0_cash", seed=2, dataset_hash="d" * 32,
                             error="f2")
        led.close()
        led2 = ExperimentLedger(tmp_path / "ledger.jsonl", limits=LIMITS,
                                protocol_hash="p" * 32, code_hash="c" * 32)
        assert led2.halted  # replayed from history
        with pytest.raises(BudgetExceeded):
            led2.register_trial("B0_cash", seed=3, dataset_hash="d" * 32)
        led2.close()


class TestHashChainIntegrity:
    def test_chain_verifies_clean(self, tmp_path):
        led = make_ledger(tmp_path)
        led.register_trial("B0_cash", seed=1, dataset_hash="d" * 32)
        led.register_failure("B0_cash", seed=2, dataset_hash="d" * 32,
                             error="x")
        led.register_query(note="q")
        led.close()
        ok, msg = ExperimentLedger(tmp_path / "ledger.jsonl",
                                   limits=LIMITS, protocol_hash="p" * 32,
                                   code_hash="c" * 32).verify_chain()
        assert ok, msg

    def test_deletion_breaks_chain(self, tmp_path):
        led = make_ledger(tmp_path)
        led.register_trial("B0_cash", seed=1, dataset_hash="d" * 32)
        led.register_failure("B0_cash", seed=2, dataset_hash="d" * 32,
                             error="x")
        led.register_query(note="after")
        led.close()
        p = tmp_path / "ledger.jsonl"
        lines = p.read_text(encoding="utf-8").splitlines()
        # "erase the failure" — delete the middle entry; its successor's
        # prev-pointer no longer matches
        del lines[1]
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        led2 = ExperimentLedger(p, limits=LIMITS, protocol_hash="p" * 32,
                                code_hash="c" * 32)
        ok, msg = led2.verify_chain()
        assert not ok
        assert "chain break" in msg
        led2.close()

    def test_history_edit_breaks_chain(self, tmp_path):
        led = make_ledger(tmp_path)
        led.register_failure("B0_cash", seed=1, dataset_hash="d" * 32,
                             error="the-failure")
        led.register_trial("B0_cash", seed=2, dataset_hash="d" * 32)
        led.close()
        p = tmp_path / "ledger.jsonl"
        text = p.read_text(encoding="utf-8").replace(
            "the-failure", "nothing-happened")
        p.write_text(text, encoding="utf-8")
        led2 = ExperimentLedger(p, limits=LIMITS, protocol_hash="p" * 32,
                                code_hash="c" * 32)
        ok, msg = led2.verify_chain()
        assert not ok
        assert "digest mismatch" in msg
        led2.close()

    def test_restart_preserves_monotone_counts(self, tmp_path):
        led = make_ledger(tmp_path)
        led.register_trial("B0_cash", seed=1, dataset_hash="d" * 32)
        led.register_failure("B0_cash", seed=2, dataset_hash="d" * 32,
                             error="x")
        led.close()
        led2 = ExperimentLedger(tmp_path / "ledger.jsonl", limits=LIMITS,
                                protocol_hash="p" * 32, code_hash="c" * 32)
        assert led2.counters()["trials"] == 1
        assert led2.counters()["failures"] == 1
        led2.close()


class TestEntryBinding:
    def test_entries_carry_hashes_and_seed(self, tmp_path):
        led = make_ledger(tmp_path)
        led.register_trial("B1_buy_hold", seed=137, dataset_hash="d" * 32)
        led.close()
        entry = json.loads((tmp_path / "ledger.jsonl").read_text(
            encoding="utf-8").splitlines()[0])
        assert entry["protocol_hash"] == "p" * 32
        assert entry["code_hash"] == "c" * 32
        assert entry["detail"]["seed"] == 137
        assert entry["detail"]["arm"] == "B1_buy_hold"
        assert entry["ts"].endswith("Z")

    def test_unknown_kind_rejected(self, tmp_path):
        led = make_ledger(tmp_path)
        with pytest.raises(ValueError, match="unknown ledger entry kind"):
            led._append("FREE_WIN", {})
        led.close()
