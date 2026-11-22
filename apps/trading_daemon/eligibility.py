"""S5 eligibility machine — real-forward-window qualification rules.

The offline synthetic harness can produce exactly two honest outcomes:
``OFFLINE_HARNESS_PASS_WITH_SCOPE`` (fixture proof only) or a BLOCKED
state. Synthetic facts can NEVER mint ``PENDING_FORWARD_WINDOW`` or
``PASS`` — those require preregistered REAL arrival records that do not
exist in this stage. Attempts to claim them raise.
"""

from __future__ import annotations

from typing import Any

__all__ = ["EligibilityRefused", "evaluate_eligibility"]


class EligibilityRefused(ValueError):
    """An evidence claim exceeds what the collected facts support."""


def evaluate_eligibility(*, prereg_real_window_enabled: bool,
                         source_authorization: str,
                         harness: dict[str, bool],
                         real_window_facts: dict[str, Any],
                         claim: str | None = None) -> dict[str, Any]:
    """Evaluate the machine states from preregistration + facts.

    ``claim`` forces an explicit claim (PASS / PENDING_FORWARD_WINDOW)
    that must be justified by REAL facts; synthetic facts refuse.
    """
    synthetic_only = not real_window_facts.get("events_synthetic", False) \
        or True  # this stage: all events are synthetic by construction
    trading_days = int(real_window_facts.get("trading_days_observed", 0))

    if claim == "PASS":
        raise EligibilityRefused(
            "E=PASS requires at least 5 REAL observable US trading days "
            "with pre-lock predictions, disconnect/duplicate recoveries "
            "and 0 unauthorized broker orders — synthetic windows can "
            "never substitute (task S5)")
    if claim == "PENDING_FORWARD_WINDOW":
        if synthetic_only or trading_days <= 0 or \
                not prereg_real_window_enabled:
            raise EligibilityRefused(
                "PENDING_FORWARD_WINDOW requires legally obtained REAL "
                "arrived forward observations; synthetic fixtures are "
                "never a forward window")

    harness_failed = sorted(
        k for k, v in harness.items() if v is False)
    harness_ok = bool(harness) and not harness_failed
    result: dict[str, Any] = {
        "real_source": "NONE_BLOCKED"
        if source_authorization == "NONE" else source_authorization,
        "s": "INCONCLUSIVE",          # no valid forward statistical evidence
        "r": "NOT_STARTED",
        "paper_orders": "PAPER_NOT_RUN",
        "broker_writes": 0,
    }
    if not harness_ok:
        result["eligibility"] = "BLOCKED_ENV"
        result["reason"] = (
            f"offline harness incomplete: {', '.join(harness_failed)}")
        result["forward_window_status"] = "NOT_STARTED"
        return result
    result["eligibility"] = "OFFLINE_HARNESS_PASS_WITH_SCOPE"
    result["reason"] = ("synthetic replay harness passed; scope is the "
                        "test fixture only — never a real forward window")
    result["forward_window_status"] = (
        "ACCUMULATING" if prereg_real_window_enabled and trading_days > 0
        else "NOT_STARTED")
    result["real_source"] = "BLOCKED_DATA" \
        if source_authorization == "NONE" else result["real_source"]
    return result
