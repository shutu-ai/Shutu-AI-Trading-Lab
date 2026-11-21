"""Shared helpers for backtest kernel tests.

Deliberately NOT named ``conftest``-importable: other test directories
(e.g. tests/security) also have a ``conftest.py``, and a top-level
``import conftest`` resolves to whichever one entered ``sys.modules``
first. Tests import from this unambiguous module name instead.
"""

from __future__ import annotations

import datetime as dt
import sys
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

from trading_lab.contracts import AdjustmentKind, MarketBar  # noqa: E402

DAY0 = dt.datetime(2026, 1, 5, 21, 0, tzinfo=dt.timezone.utc)  # 16:00 ET close


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
    """Session close timestamp n sessions after DAY0 (fixtures use
    consecutive UTC days; market-calendar semantics live in the M1 data
    layer, which this synthetic kernel consumes timestamps from)."""
    return DAY0 + dt.timedelta(days=n)
