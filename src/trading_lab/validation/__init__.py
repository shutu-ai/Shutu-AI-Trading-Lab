"""Validation layer (M3): evaluation protocol registry, cohort hygiene,
sealed-holdout gate, experiment ledger. Research plane — must not import
oms/risk/brokers/data (enforced by scripts/check_architecture.py).
"""
from trading_lab.validation.protocol import ArmSpec, EvaluationProtocol, ProtocolError

__all__ = ["ArmSpec", "EvaluationProtocol", "ProtocolError"]
