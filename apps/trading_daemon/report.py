"""S4 monitoring/evidence model — the status report.

Minimal structured fields (mandated by the task), explicit denominators,
no zero-sample percentage claims, no dashboard. ``build_status_report``
returns a plain JSON-serializable dict; ``render_markdown`` renders a
small CLI-friendly view.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

__all__ = ["build_status_report", "render_markdown"]


def build_status_report(summary, *, prereg, harness: dict[str, Any],
                        eligibility: dict[str, Any] | None = None) \
        -> dict[str, Any]:
    from .eligibility import evaluate_eligibility
    if eligibility is None:
        eligibility = evaluate_eligibility(
            prereg_real_window_enabled=bool(
                prereg.payload["real_window"]["enabled"]),
            source_authorization=str(
                prereg.payload["source_authorization"]["real_market_data"]),
            harness=harness,
            real_window_facts={"trading_days_observed": 0})
    counters = summary.counters
    status = getattr(summary, "last_status", {}) or {}
    environment = str(prereg.payload["environment_must_equal"])
    evidence_level = ("SHADOW_REAL_OBSERVED"
                      if environment == "REAL_SHADOW_READ_ONLY"
                      else "SYNTHETIC_REPLAY")
    return {
        # -- mandated S4 fields -----------------------------------------
        "mode": environment,
        "source_authorization_status": str(
            prereg.payload["source_authorization"]["real_market_data"]),
        "source_evidence_level": evidence_level,
        "cohort_id": summary.cohort_id,
        "event_id": status.get("event_id"),
        "strategy_hash": status.get("strategy_hash"),
        "code_hash": status.get("code_hash"),
        "protocol_hash": status.get("protocol_hash"),
        "dataset_hash": status.get("dataset_hash"),
        "prediction_lock_digest": status.get("prediction_lock_digest"),
        "event_ts": status.get("event_ts"),
        "available_at": status.get("available_at"),
        "received_at": status.get("received_at"),
        "decision_at": status.get("decision_at"),
        "score_at": status.get("score_at"),
        "replay_count": status.get("replay_count", 0),
        "duplicate_count": counters.get("duplicates", 0),
        "gap_count": counters.get("held", 0),
        "clock_skew": status.get("clock_skew_seconds"),
        "recovery_status": summary.recovery_status,
        "account_environment": environment,
        "no_broker_writes": summary.no_broker_writes,
        # -- explicit denominators and anomaly counts --------------------
        "counters": counters,
        "expired_count": counters.get("expired", 0),
        "rejected_count": counters.get("rejected", 0),
        "events_delivered": counters.get("events_delivered", 0),
        # -- S5 machine states -------------------------------------------
        "eligibility": eligibility,
        "real_forward_window": {
            "status": eligibility["forward_window_status"],
            "authorized_source": eligibility["real_source"],
            "trading_days_observed": int(
                eligibility.get("trading_days_observed", 0)),
            "min_trading_days": int(
                prereg.payload["real_window"]["min_trading_days"]),
            "paper_orders": eligibility["paper_orders"],
            "s": eligibility["s"],
            "r": eligibility["r"],
        },
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }


def render_markdown(report: dict[str, Any]) -> str:
    elig = report["eligibility"]
    counters = report["counters"]
    scored = counters.get("scored", {})
    lines = [
        "# M3.5 forward observation status",
        "",
        f"- mode: {report['mode']} (evidence level "
        f"{report['source_evidence_level']})",
        f"- eligibility: **{elig['eligibility']}** — {elig['reason']}",
        f"- real forward window: "
        f"{report['real_forward_window']['status']} "
        f"(source {report['real_forward_window']['authorized_source']}; "
        f"{report['real_forward_window']['trading_days_observed']}/"
        f"{report['real_forward_window']['min_trading_days']} real days)",
        f"- S={elig['s']} · R={elig['r']} · "
        f"paper={elig['paper_orders']} · broker writes="
        f"{elig['broker_writes']}",
        f"- cohort: {report['cohort_id']} · "
        f"duplicates={report['duplicate_count']} · "
        f"held={report['gap_count']} · expired={report['expired_count']} · "
        f"rejected={report['rejected_count']}",
        f"- scored: {scored.get('total', 0)} "
        f"(hit {scored.get('hit', 0)} / miss {scored.get('miss', 0)} / "
        f"no_claim {scored.get('no_claim', 0)} / "
        f"flat_close {scored.get('flat_close', 0)}) — engineering "
        "stability counters only, never alpha",
        f"- no_broker_writes: {report['no_broker_writes']} · "
        f"account_environment: {report['account_environment']}",
        "",
        "SYNTHETIC_REPLAY outcomes are fixture proofs. They are not real "
        "forward trading days and cannot support E=PASS, alpha, or Live "
        "eligibility.",
    ]
    return "\n".join(lines)
