"""OMS plane: the single order management system — durable intents
(SQLite WAL FULL), deterministic state machine, UNKNOWN-never-resend
semantics, single-writer fencing egress, reconciliation recovery.

The OMS consumes RiskDecision as data (it does not import the risk package)
and reaches brokers only through the single trusted egress.
"""

from .egress import BrokerEgress, EgressRefusalError
from .engine import OmsEngine, OmsError, RecoveryReport, SubmitOutcome
from .fence import FenceCoordinator, FenceError, FenceToken
from .journal import JournalError, OrderJournal
from .states import LEGAL_TRANSITIONS, IllegalTransition, TERMINAL_STATES, validate_transition

__all__ = [
    "BrokerEgress",
    "EgressRefusalError",
    "FenceCoordinator",
    "FenceError",
    "FenceToken",
    "IllegalTransition",
    "JournalError",
    "LEGAL_TRANSITIONS",
    "OmsEngine",
    "OmsError",
    "OrderJournal",
    "RecoveryReport",
    "SubmitOutcome",
    "TERMINAL_STATES",
    "SubmitOutcome",
    "validate_transition",
]
