"""Deterministic offline backtest — pure computation, no broker access.

Research plane: may import contracts + security only (ADR-004 §6;
enforced by scripts/check_architecture.py).
"""
from trading_lab.backtest.engine import (
    BacktestAccount,
    BacktestEngine,
    BacktestError,
    BacktestEvent,
    CostModel,
    ExecutionConfig,
)

__all__ = [
    "BacktestAccount",
    "BacktestEngine",
    "BacktestError",
    "BacktestEvent",
    "CostModel",
    "ExecutionConfig",
]
