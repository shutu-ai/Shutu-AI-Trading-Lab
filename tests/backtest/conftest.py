"""Shared fixtures for backtest kernel tests (M3-R1-T3).

Bars are real ``contracts.MarketBar`` instances — the backtest kernel must
not carry a second bar type (the stub ``Bar`` dataclass was removed).
Bar/day helpers live in helpers_backtest.py (an unambiguous module name;
see its docstring for why ``import conftest`` must not be used).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tests"))
sys.path.insert(0, str(REPO_ROOT / "tests" / "backtest"))

from trading_lab.validation import EvaluationProtocol  # noqa: E402

PROTOCOL_PATH = REPO_ROOT / "configs" / "evaluation_protocol.yaml"


@pytest.fixture(scope="session")
def protocol() -> EvaluationProtocol:
    return EvaluationProtocol.load(PROTOCOL_PATH)
