"""Real-path eligibility machine (S8): the five machine states under the
signed approval, fail-closed defaults, and the 5-real-day PASS bar.

Canonical names are taken verbatim from
``apps/trading_daemon/eligibility.py``; pytest is the authority here,
not visual review."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from apps.trading_daemon.eligibility import (  # noqa: E402
    EligibilityRefused,
    evaluate_eligibility,
)

HARNESS_OK = {
    "harness_complete": True,
    "negatives_passed": None,     # attested by CI + negative-tests log
    "replay_reproducible": True,
    "journal_verified": True,
    "no_broker_writes": True,
}

REAL_OK = {
    "events_synthetic": False,
    "receipt_evidence_ok": True,
    "trading_days_observed": 3,
    "disconnect_recoveries": 1,
    "duplicate_recoveries": 1,
    "unauthorized_broker_orders": 0,
    "duplicate_broker_orders": 0,
    "audits_passed": True,
}


def _eval(facts, claim=None, *, window_enabled=True, harness=None):
    return evaluate_eligibility(
        prereg_real_window_enabled=window_enabled,
        source_authorization="ALPACA_IEX_BASIC_READ_ONLY",
        harness=dict(HARNESS_OK if harness is None else harness),
        real_window_facts=dict(facts),
        claim=claim,
        min_trading_days=5)


def test_real_pending_forward_window_with_partial_days():
    result = _eval(REAL_OK, claim="PENDING_FORWARD_WINDOW")
    assert result["eligibility"] == "PENDING_FORWARD_WINDOW"
    assert result["forward_window_status"] == "ACCUMULATING"
    assert result["trading_days_observed"] == 3
    assert result["s"] == "INCONCLUSIVE"
    assert result["paper_orders"] == "PAPER_NOT_RUN"
    assert result["broker_writes"] == 0
    assert result["real_source"] == "ALPACA_IEX_BASIC_READ_ONLY"


def test_full_pass_after_five_real_days():
    facts = dict(REAL_OK, trading_days_observed=5)
    result = _eval(facts, claim="PASS")
    assert result["eligibility"] == "PASS"
    assert result["forward_window_status"] == "COMPLETE"
    # the engineering E-Gate says nothing statistically:
    assert result["s"] == "INCONCLUSIVE"
    assert result["r"] == "NOT_STARTED"


def test_pass_refused_below_five_days():
    """Signed approval condition 5: insufficient observation may NOT
    claim a full E-Gate PASS."""
    facts = dict(REAL_OK, trading_days_observed=4)
    with pytest.raises(EligibilityRefused) as excinfo:
        _eval(facts, claim="PASS")
    assert "insufficient" in str(excinfo.value)


@pytest.mark.parametrize("missing", ["disconnect_recoveries",
                                     "duplicate_recoveries"])
def test_pass_refused_without_window_recoveries(missing):
    facts = dict(REAL_OK, trading_days_observed=5, **{missing: 0})
    with pytest.raises(EligibilityRefused) as excinfo:
        _eval(facts, claim="PASS")
    assert missing in str(excinfo.value)


@pytest.mark.parametrize("key", ["unauthorized_broker_orders",
                                 "duplicate_broker_orders"])
def test_pass_refused_by_any_broker_order(key):
    facts = dict(REAL_OK, trading_days_observed=5, **{key: 1})
    with pytest.raises(EligibilityRefused):
        _eval(facts, claim="PASS")


def test_pass_refused_without_audit_pass():
    facts = dict(REAL_OK, trading_days_observed=5, audits_passed=False)
    with pytest.raises(EligibilityRefused):
        _eval(facts, claim="PASS")


# ---------------------------------------------------------------------------
# fail-closed defaults
# ---------------------------------------------------------------------------

def test_missing_receipt_evidence_defaults_to_refused():
    facts = dict(REAL_OK, trading_days_observed=5)
    facts.pop("receipt_evidence_ok")
    with pytest.raises(EligibilityRefused):
        _eval(facts, claim="PENDING_FORWARD_WINDOW")


def test_missing_synthetic_flag_defaults_to_synthetic():
    facts = dict(REAL_OK, trading_days_observed=5)
    facts.pop("events_synthetic")
    with pytest.raises(EligibilityRefused):
        _eval(facts, claim="PASS")


def test_disabled_real_preregistration_never_admits_real_claims():
    facts = dict(REAL_OK, trading_days_observed=5)
    with pytest.raises(EligibilityRefused):
        _eval(facts, claim="PENDING_FORWARD_WINDOW", window_enabled=False)


def test_zero_days_is_never_a_window():
    facts = dict(REAL_OK, trading_days_observed=0)
    with pytest.raises(EligibilityRefused):
        _eval(facts, claim="PENDING_FORWARD_WINDOW")


def test_broken_harness_blocks_even_complete_facts():
    facts = dict(REAL_OK, trading_days_observed=5)
    harness = dict(HARNESS_OK, no_broker_writes=False)
    result = _eval(facts, claim="PASS", harness=harness)
    assert result["eligibility"] == "BLOCKED_ENV"


def test_synthetic_scope_outcomes_unchanged():
    """The v1 synthetic path behaves exactly as before: no claim, no real
    facts -> OFFLINE_HARNESS_PASS_WITH_SCOPE / NOT_STARTED / BLOCKED_DATA;
    synthetic days can never mint PASS."""
    all_true = {k: True for k in HARNESS_OK}
    result = evaluate_eligibility(
        prereg_real_window_enabled=False,
        source_authorization="NONE",
        harness=all_true,
        real_window_facts={"trading_days_observed": 0})
    assert result["eligibility"] == "OFFLINE_HARNESS_PASS_WITH_SCOPE"
    assert result["forward_window_status"] == "NOT_STARTED"
    assert result["real_source"] == "BLOCKED_DATA"
    with pytest.raises(EligibilityRefused):
        evaluate_eligibility(
            prereg_real_window_enabled=False,
            source_authorization="NONE",
            harness=all_true,
            real_window_facts={"trading_days_observed": 30},
            claim="PASS")
