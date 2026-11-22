"""S5 eligibility machine: the harness scope can only ever produce
OFFLINE_HARNESS_PASS_WITH_SCOPE or BLOCKED_*; synthetic facts can never
mint PASS or PENDING_FORWARD_WINDOW."""

from __future__ import annotations

import pytest

from apps.trading_daemon.eligibility import (
    EligibilityRefused,
    evaluate_eligibility,
)


HARNESS_OK = {
    "harness_complete": True,
    "negatives_passed": True,
    "replay_reproducible": True,
    "journal_verified": True,
    "no_broker_writes": True,
}


def test_synthetic_harness_pass_is_scoped():
    result = evaluate_eligibility(
        prereg_real_window_enabled=False,
        source_authorization="NONE",
        harness=HARNESS_OK,
        real_window_facts={"trading_days_observed": 0})
    assert result["eligibility"] == "OFFLINE_HARNESS_PASS_WITH_SCOPE"
    assert result["forward_window_status"] == "NOT_STARTED"
    assert result["real_source"] == "BLOCKED_DATA"


def test_incomplete_harness_is_blocked_env():
    harness = dict(HARNESS_OK, negatives_passed=False)
    result = evaluate_eligibility(
        prereg_real_window_enabled=False,
        source_authorization="NONE",
        harness=harness,
        real_window_facts={"trading_days_observed": 0})
    assert result["eligibility"] == "BLOCKED_ENV"
    assert "harness" in result["reason"].lower()


def test_synthetic_cannot_mint_pass():
    with pytest.raises(EligibilityRefused):
        evaluate_eligibility(
            prereg_real_window_enabled=False,
            source_authorization="NONE",
            harness=HARNESS_OK,
            real_window_facts={"trading_days_observed": 0},
            claim="PASS")


def test_synthetic_cannot_mint_pending_forward_window():
    """Five synthetic days are never five real trading days — claiming
    accumulation of a real window from synthetic facts is refused."""
    with pytest.raises(EligibilityRefused):
        evaluate_eligibility(
            prereg_real_window_enabled=False,
            source_authorization="NONE",
            harness=HARNESS_OK,
            real_window_facts={"trading_days_observed": 5,
                               "events_synthetic": True},
            claim="PENDING_FORWARD_WINDOW")


def test_pass_requires_real_preregistered_window():
    """Even with a real-looking claim, PASS without an enabled real
    window and full preregistered coverage is refused."""
    with pytest.raises(EligibilityRefused):
        evaluate_eligibility(
            prereg_real_window_enabled=True,
            source_authorization="LICENSED",
            harness=HARNESS_OK,
            real_window_facts={"trading_days_observed": 4},
            claim="PASS")


def test_blocked_data_when_source_unauthorized():
    result = evaluate_eligibility(
        prereg_real_window_enabled=False,
        source_authorization="NONE",
        harness=HARNESS_OK,
        real_window_facts={"trading_days_observed": 0})
    assert result["real_source"] == "BLOCKED_DATA"
    assert result["s"] == "INCONCLUSIVE"
    assert result["r"] == "NOT_STARTED"
    assert result["paper_orders"] == "PAPER_NOT_RUN"
