"""Shared fixtures for backtest kernel tests (M3-R1-T3).

Bars are real ``contracts.MarketBar`` instances — the backtest kernel must
not carry a second bar type (the stub ``Bar`` dataclass was removed).
"""

from __future__ import annotations

import datetime as dt
import sys
from decimal import Decimal
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

from trading_lab.contracts import AdjustmentKind, MarketBar  # noqa: E402
from trading_lab.validation import EvaluationProtocol  # noqa: E402

PROTOCOL_PATH = REPO_ROOT / "configs" / "evaluation_protocol.yaml"

DAY0 = dt.datetime(2026, 1, 5, 21, 0, tzinfo=dt.timezone.utc)  # a 16:00 ET close


def bar(symbol: str, ts: dt.datetime, close: str | Decimal, *,
        open_: str | Decimal | None = None,
        high: str | Decimal | None = None,
        low: str | Decimal | None = None,
        volume: str = "1000000") -> MarketBar:
    c = Decimal(close)
    o = Decimal(open_) if open_ is not None else c
    h = Decimal(high) if high is not None else max(o, c)
    l = Decimal(low) if low is not None else min(o, c)
    return MarketBar.model_validate(dict(
        asset_id=symbol, ts_event_utc=ts, ts_available_utc=ts,
        interval="1d", open=o, high=h, low=l, close=c,
        volume=Decimal(volume), source="synthetic",
        adjustment=AdjustmentKind.RAW, quality="ok",
    ))


def day(n: int) -> dt.datetime:
    """Session close timestamp n trading sessions after DAY0 (fixtures use
    consecutive UTC days; market-calendar semantics live in the M1 data
    layer, which this synthetic kernel consumes timestamps from)."""
    return DAY0 + dt.timedelta(days=n)


@pytest.fixture(scope="session")
def protocol() -> EvaluationProtocol:
    return EvaluationProtocol.load(PROTOCOL_PATH)
