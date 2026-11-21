"""M3-R1-T2 — evaluation protocol registry: hash freeze, fail-closed,
controlled-field immutability, honest INCONCLUSIVE for unset gates.

RED-first evidence: these tests were written and run BEFORE
src/trading_lab/validation/protocol.py existed (ImportError = RED), then
the module was implemented to turn them GREEN.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

from trading_lab.security.canonical import canonical_digest  # noqa: E402

PROTOCOL_PATH = REPO_ROOT / "configs" / "evaluation_protocol.yaml"


# ---------------------------------------------------------------------------
# Load + hash
# ---------------------------------------------------------------------------


class TestProtocolLoadAndHash:
    def test_load_succeeds_and_binds_hash(self):
        from trading_lab.validation.protocol import EvaluationProtocol

        p = EvaluationProtocol.load(PROTOCOL_PATH)
        assert p.protocol_id == "m3-synthetic-engineering-v1"
        assert len(p.protocol_hash) == 64  # sha256 hex

    def test_hash_is_deterministic_across_reloads(self):
        from trading_lab.validation.protocol import EvaluationProtocol

        h1 = EvaluationProtocol.load(PROTOCOL_PATH).protocol_hash
        h2 = EvaluationProtocol.load(PROTOCOL_PATH).protocol_hash
        assert h1 == h2

    def test_hash_matches_canonical_digest_of_payload(self):
        """The hash is the canonical digest of the parsed payload — no
        private canonicalization (reuse security.canonical per task)."""
        import yaml

        from trading_lab.validation.protocol import EvaluationProtocol

        payload = yaml.safe_load(PROTOCOL_PATH.read_text(encoding="utf-8"))
        assert EvaluationProtocol.load(PROTOCOL_PATH).protocol_hash == (
            canonical_digest(payload)
        )

    def test_hash_covers_every_controlled_field(self):
        """Freeze completeness is proven per-section by the parametrized
        TestControlledFieldChange probes below; this test only pins the
        loader's purity (same payload -> same hash) as the base case."""
        from trading_lab.validation.protocol import EvaluationProtocol

        base_hash = EvaluationProtocol.load(PROTOCOL_PATH).protocol_hash
        assert EvaluationProtocol.load(PROTOCOL_PATH).protocol_hash == base_hash


# ---------------------------------------------------------------------------
# Controlled-field change => new hash (parametrized over sections)
# ---------------------------------------------------------------------------

# Each probe mutates exactly one controlled field; every probe must yield a
# different hash. Chosen to cover every governance-bearing section.
_CHANGE_PROBES = [
    ("seeds", lambda d: d.__setitem__("seeds", [42, 137])),
    ("cost_model", lambda d: d["cost_model"].__setitem__(
        "commission_per_trade", "1.50")),
    ("execution", lambda d: d["execution"].__setitem__(
        "settlement_days", 1)),
    ("pit_rule", lambda d: d.__setitem__(
        "pit_rule", "available_at < decision_at")),
    ("arms", lambda d: d["arms"]["B2_single_rule"].__setitem__(
        "description", "changed definition")),
    ("budget", lambda d: d["budget"].__setitem__("max_total_trials", 99)),
    ("validation", lambda d: d["validation"].__setitem__("min_bars", 101)),
    ("holdout", lambda d: d["holdout"].__setitem__(
        "candidate_selection_rule", "changed rule")),
    ("multiplicity", lambda d: d["multiplicity"].__setitem__(
        "register_all_trials", False)),
]


class TestControlledFieldChange:
    @pytest.mark.parametrize("section,mutate", _CHANGE_PROBES)
    def test_any_controlled_change_gives_new_hash(self, section, mutate):
        import copy
        import yaml

        from trading_lab.validation.protocol import EvaluationProtocol

        base = yaml.safe_load(PROTOCOL_PATH.read_text(encoding="utf-8"))
        base_hash = EvaluationProtocol.load(PROTOCOL_PATH).protocol_hash
        mutated = copy.deepcopy(base)
        mutate(mutated)
        # The mutated payload's canonical digest differs…
        assert canonical_digest(mutated) != canonical_digest(base)
        # …and the loader is a pure function of the payload.
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            alt = Path(td) / "alt.yaml"
            alt.write_text(
                yaml.safe_dump(mutated, sort_keys=False), encoding="utf-8")
            assert EvaluationProtocol.load(alt).protocol_hash != base_hash


# ---------------------------------------------------------------------------
# Fail-closed + immutability
# ---------------------------------------------------------------------------


class TestFailClosedAndFrozen:
    def test_missing_file_fails_closed(self, tmp_path):
        from trading_lab.validation.protocol import ProtocolError

        with pytest.raises(ProtocolError, match="cannot read"):
            from trading_lab.validation import protocol as _p
            _p.EvaluationProtocol.load(tmp_path / "missing.yaml")

    def test_missing_required_section_fails_closed(self, tmp_path):
        import yaml

        from trading_lab.validation.protocol import ProtocolError

        raw = yaml.safe_load(PROTOCOL_PATH.read_text(encoding="utf-8"))
        del raw["budget"]
        p = tmp_path / "broken.yaml"
        p.write_text(yaml.safe_dump(raw), encoding="utf-8")
        with pytest.raises(ProtocolError, match="budget"):
            from trading_lab.validation import protocol as _p
            _p.EvaluationProtocol.load(p)

    def test_runtime_threshold_mutation_refused(self):
        """The frozen view refuses attribute writes — thresholds cannot be
        silently changed at runtime; a change means a new file + new hash."""
        from trading_lab.validation.protocol import EvaluationProtocol

        p = EvaluationProtocol.load(PROTOCOL_PATH)
        with pytest.raises((AttributeError, TypeError)):
            p.max_total_trials = 10**9  # type: ignore[misc]

    def test_budget_view_is_read_only(self):
        from trading_lab.validation.protocol import EvaluationProtocol

        p = EvaluationProtocol.load(PROTOCOL_PATH)
        with pytest.raises(TypeError):
            p.budget["max_total_trials"] = 10**9  # type: ignore[index]


# ---------------------------------------------------------------------------
# Honest gates: PROTOCOL_INCOMPLETE fields must exist and be declared
# ---------------------------------------------------------------------------


class TestHonestGates:
    def test_no_unbounded_fake_thresholds(self):
        """The 3505799 stub had `max_drawdown_pct: 100` presented as a risk
        gate. The frozen protocol must not carry any numeric threshold with
        an effectively-vacuous bound; risk/statistical alpha gates that
        cannot be set without real-data basis must be declared as
        NOT_SETTABLE with verdict INCONCLUSIVE."""
        from trading_lab.validation.protocol import EvaluationProtocol

        p = EvaluationProtocol.load(PROTOCOL_PATH)
        all_thresholds = p.numeric_gates()  # name -> (value, settable)
        for name, (value, settable) in all_thresholds.items():
            if not settable:
                assert value is None
        assert "max_drawdown_pct" not in {
            n for n, (v, s) in all_thresholds.items() if s and v >= 100
        }

    def test_unset_alpha_gates_declared_inconclusive(self):
        from trading_lab.validation.protocol import EvaluationProtocol

        p = EvaluationProtocol.load(PROTOCOL_PATH)
        alpha = p.gate_status("statistical_alpha")
        assert alpha == "NOT_SETTABLE"
        assert p.verdict_for_incomplete_gate("statistical_alpha") == (
            "INCONCLUSIVE")

    def test_engineering_gates_are_settable(self):
        """Conservation / PIT / determinism are engineering gates that CAN
        be binding in the synthetic scope."""
        from trading_lab.validation.protocol import EvaluationProtocol

        p = EvaluationProtocol.load(PROTOCOL_PATH)
        for gate in ("conservation", "pit", "determinism"):
            assert p.gate_status(gate) == "SET"

    def test_no_alpha_pass_from_synthetic_scope(self):
        """The protocol itself must state that synthetic results can never
        be reported as alpha/HIST_OOS_SUPPORTED evidence."""
        from trading_lab.validation.protocol import EvaluationProtocol

        p = EvaluationProtocol.load(PROTOCOL_PATH)
        assert p.data_scope == "SYNTHETIC_ENGINEERING_ONLY"
        assert p.max_claimable_evidence == "ENGINEERING_ONLY"


# ---------------------------------------------------------------------------
# Arms + budgets
# ---------------------------------------------------------------------------


class TestArmsAndBudgets:
    def test_b0_b2_enabled_b3_b8_registered_not_shell(self):
        from trading_lab.validation.protocol import EvaluationProtocol

        p = EvaluationProtocol.load(PROTOCOL_PATH)
        enabled = {a.arm_id for a in p.enabled_arms()}
        assert enabled == {"B0_cash", "B1_buy_hold", "B2_single_rule"}
        frozen_defs = {a.arm_id for a in p.registered_disabled_arms()}
        assert frozen_defs == {
            "B3_regime", "B4_multi_static", "B5_regime_routing",
            "B6_ai_champion", "B7_rule_search", "B8_rebalance",
        }
        for a in p.registered_disabled_arms():
            assert a.enabled is False
            assert a.definition  # definition frozen, not an empty shell

    def test_budgets_are_structured_not_booleans(self):
        """equal_trial_budget / equal_economic_budget must be concrete
        per-arm structures, not two `true` flags."""
        from trading_lab.validation.protocol import EvaluationProtocol

        p = EvaluationProtocol.load(PROTOCOL_PATH)
        tb = p.equal_trial_budget()
        assert tb["per_arm_trials"] == {"B0_cash": 3, "B1_buy_hold": 3,
                                        "B2_single_rule": 3}
        assert tb["count_failures"] is True
        assert tb["count_retries"] is True
        eb = p.equal_economic_budget()
        assert eb["status"] in {"DECLARED", "NOT_APPLICABLE_YET"}
        assert "llm_usd_cap" in eb and "compute_hours_cap" in eb
        assert eb["note"]  # honest note about which arms it binds

    def test_budget_limits_enumerable_for_ledger(self):
        from trading_lab.validation.protocol import EvaluationProtocol

        p = EvaluationProtocol.load(PROTOCOL_PATH)
        limits = p.budget_limits()
        assert limits["max_total_trials"] > 0
        assert limits["max_search_queries"] > 0
        assert limits["max_failures_before_halt"] > 0
        assert limits["max_holdout_unlocks"] == 1


# ---------------------------------------------------------------------------
# M9 sealed holdout registration
# ---------------------------------------------------------------------------


class TestSealedHoldoutRegistration:
    def test_holdout_not_materialized_no_fake_ids(self):
        """Real data is BLOCKED in M3: the holdout must be registered as
        not materialized, with NO fabricated sample IDs/hashes."""
        from trading_lab.validation.protocol import EvaluationProtocol

        p = EvaluationProtocol.load(PROTOCOL_PATH)
        h = p.holdout_registration()
        assert h["status"] == "SEALED_NOT_MATERIALIZED"
        assert h["sample_ids"] is None
        assert h["dataset_hash"] is None
        assert h["max_unlocks"] == 1
        assert h["candidate_selection_rule"]
        assert list(h["verdict_states"]) == [
            "PASS", "FAILED", "INCONCLUSIVE", "INVALIDATED"]
        assert h["unlock_policy"] == "M9_ONLY_INDEPENDENT_GOVERNANCE"
