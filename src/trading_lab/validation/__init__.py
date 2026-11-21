"""Validation layer (M3): evaluation protocol registry, cohort hygiene,
sealed-holdout gate, experiment ledger. Research plane — must not import
oms/risk/brokers/data (enforced by scripts/check_architecture.py).
"""
from trading_lab.validation.protocol import ArmSpec, EvaluationProtocol, ProtocolError
from trading_lab.validation.cohorts import (
    CohortError,
    CohortRole,
    CohortSpec,
    ForwardCohort,
    OverlapReport,
)
from trading_lab.validation.holdout import HoldoutError, HoldoutRole, SealedHoldout
from trading_lab.validation.ledger import BudgetExceeded, ExperimentLedger

__all__ = [
    "ArmSpec",
    "BudgetExceeded",
    "CohortError",
    "CohortRole",
    "CohortSpec",
    "EvaluationProtocol",
    "ExperimentLedger",
    "ForwardCohort",
    "HoldoutError",
    "HoldoutRole",
    "OverlapReport",
    "ProtocolError",
    "SealedHoldout",
]
