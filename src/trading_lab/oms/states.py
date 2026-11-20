"""Order state machine — legal transitions only; anything else is rejected
and audited by the OMS."""

from __future__ import annotations

LEGAL_TRANSITIONS: dict[str, frozenset[str]] = {
    "NEW_INTENT": frozenset({"PERSISTED"}),
    "PERSISTED": frozenset({"SUBMITTING", "CANCEL_PENDING"}),
    "SUBMITTING": frozenset({
        "ACKED",        # delivered + acknowledged
        "UNKNOWN",      # delivered? answer lost / timeout / get_order None
        "REJECTED",     # provably not delivered and broker refused pre-arrival
        "HALT_NEW_RISK" # journal/egress fault while submitting
    }),
    "ACKED": frozenset({"PARTIALLY_FILLED", "FILLED", "CANCEL_PENDING", "UNKNOWN"}),
    "PARTIALLY_FILLED": frozenset({"PARTIALLY_FILLED", "FILLED", "CANCEL_PENDING", "UNKNOWN"}),
    "FILLED": frozenset(),                       # terminal
    "CANCEL_PENDING": frozenset({"CANCELLED", "FILLED", "PARTIALLY_FILLED", "UNKNOWN"}),
    "CANCELLED": frozenset(),                    # terminal
    "REJECTED": frozenset(),                     # terminal (never sent / provably refused)
    "UNKNOWN": frozenset({"RECONCILED", "HALT_NEW_RISK"}),  # NEVER back to SUBMITTING
    "HALT_NEW_RISK": frozenset({"RECONCILED"}),  # only reconciliation moves out
    "RECONCILED": frozenset({"FILLED", "CANCELLED"}),  # terminal mapping after reconcile
}

TERMINAL_STATES = frozenset({"FILLED", "CANCELLED", "REJECTED"})


class IllegalTransition(RuntimeError):
    pass


def validate_transition(current: str, target: str) -> None:
    allowed = LEGAL_TRANSITIONS.get(current)
    if allowed is None:
        raise IllegalTransition(f"unknown state {current!r}")
    if target not in allowed:
        raise IllegalTransition(f"illegal transition {current!r} -> {target!r}")


__all__ = ["LEGAL_TRANSITIONS", "IllegalTransition", "TERMINAL_STATES", "validate_transition"]
