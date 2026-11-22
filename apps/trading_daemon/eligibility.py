"""S5 eligibility machine — real-forward-window qualification rules.

Fail-closed defaults (proven by tests):

- facts default **synthetic** and receipt evidence defaults **unproven**:
  a caller that forgets to pass honest facts is refused, never upgraded;
- synthetic fixtures can NEVER mint ``PENDING_FORWARD_WINDOW`` or
  ``PASS`` — those require a preregistered REAL window with verified
  receipt-evidence bindings (every consumed event receipt-bound to a
  real arrival record).

S8 (approval ``S8_DATA_READ_ONLY=APPROVED_WITH_SCOPE``, 2026-11-22): the
stage guard is lifted ONLY for a separately-authorized real
preregistration (``real_window.enabled``), and the full ``E=PASS``
additionally requires the preregistered ``min_trading_days`` (>= 5 real
observable US trading days — insufficient observation may NOT claim a
full E-Gate PASS), at least one disconnect/restart recovery and one
duplicate-event recovery inside the real window, zero unauthorized and
zero duplicate broker orders, and full replay/identity/data-quality
audits passing. Statistical ``S`` stays ``INCONCLUSIVE`` in every
outcome: five engineered-forward days are stability evidence, never
alpha.
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
                         claim: str | None = None,
                         min_trading_days: int | None = None) -> dict[str, Any]:
    """Evaluate the machine states from preregistration + facts.

    ``claim`` forces an explicit claim (PASS / PENDING_FORWARD_WINDOW)
    that must be justified by REAL, receipt-bound facts; synthetic or
    receipt-unproven facts refuse.
    """
    facts_synthetic = bool(real_window_facts.get("events_synthetic", True))
    receipt_ok = bool(real_window_facts.get("receipt_evidence_ok", False))
    trading_days = int(real_window_facts.get("trading_days_observed", 0))
    real_admissible = (
        not facts_synthetic
        and prereg_real_window_enabled
        and receipt_ok
        and trading_days > 0)

    if claim == "PASS":
        if not real_admissible:
            raise EligibilityRefused(
                "E=PASS requires REAL arrival records bound to a verified "
                "receipt chain under an enabled real preregistration — "
                "synthetic windows can never substitute (task S5)")
        if min_trading_days is None:
            raise EligibilityRefused(
                "PASS requires a preregistered min_trading_days threshold")
        if trading_days < int(min_trading_days):
            raise EligibilityRefused(
                f"PASS requires >= {int(min_trading_days)} real observable "
                f"US trading days; collected {trading_days} — insufficient "
                "observation may not claim a full E-Gate PASS (S8 approval "
                "condition 5)")
        for key in ("disconnect_recoveries", "duplicate_recoveries"):
            if int(real_window_facts.get(key, 0)) < 1:
                raise EligibilityRefused(
                    f"PASS requires >= 1 {key} inside the real window "
                    "(task S5)")
        for key in ("unauthorized_broker_orders", "duplicate_broker_orders"):
            if int(real_window_facts.get(key, 0)) != 0:
                raise EligibilityRefused(
                    f"PASS requires zero {key}")
        if not bool(real_window_facts.get("audits_passed", False)):
            raise EligibilityRefused(
                "PASS requires the full replay/identity/data-quality "
                "audits to pass inside the real window")
    if claim == "PENDING_FORWARD_WINDOW":
        if not real_admissible:
            raise EligibilityRefused(
                "PENDING_FORWARD_WINDOW requires legally obtained REAL "
                "arrived forward observations with verified receipt "
                "evidence; synthetic fixtures are never a forward window")

    # the harness facts gate EVERY outcome, claims included: a broken
    # harness is BLOCKED_ENV even if the window facts look complete
    harness_failed = sorted(
        k for k, v in harness.items() if v is False)
    harness_ok = bool(harness) and not harness_failed
    if not harness_ok:
        return {
            "real_source": "NONE_BLOCKED"
            if source_authorization == "NONE" else source_authorization,
            "s": "INCONCLUSIVE",
            "r": "NOT_STARTED",
            "paper_orders": "PAPER_NOT_RUN",
            "broker_writes": 0,
            "eligibility": "BLOCKED_ENV",
            "reason": (
                f"offline harness incomplete: "
                f"{', '.join(harness_failed)}"),
            "forward_window_status": "NOT_STARTED",
            "trading_days_observed": trading_days,
        }

    if claim == "PASS":
        eligibility = "PASS"
        forward_window_status = "COMPLETE"
    elif claim == "PENDING_FORWARD_WINDOW":
        eligibility = "PENDING_FORWARD_WINDOW"
        forward_window_status = "ACCUMULATING"
    else:
        eligibility = "OFFLINE_HARNESS_PASS_WITH_SCOPE"
        forward_window_status = (
            "ACCUMULATING" if prereg_real_window_enabled and trading_days > 0
            and not facts_synthetic else "NOT_STARTED")

    result = {
        "real_source": "NONE_BLOCKED"
        if source_authorization == "NONE" else source_authorization,
        "s": "INCONCLUSIVE",          # no valid forward statistical evidence
        "r": "NOT_STARTED",
        "paper_orders": "PAPER_NOT_RUN",
        "broker_writes": 0,
        "eligibility": eligibility,
        "reason": (
            "real forward window claim validated against receipt-bound "
            "arrival facts"
            if claim in ("PASS", "PENDING_FORWARD_WINDOW") else
            "synthetic replay harness passed; scope is the test fixture "
            "only — never a real forward window"),
        "forward_window_status": forward_window_status,
        "trading_days_observed": trading_days,
    }
    if source_authorization == "NONE":
        result["real_source"] = "BLOCKED_DATA"
    return result
