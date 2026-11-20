"""Shared no-lookahead suite helpers (unique module name)."""

from __future__ import annotations

import datetime as dt
import sys
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from trading_lab.data.calendar import ET  # noqa: E402

NOW = dt.datetime(2026, 11, 20, 12, 0, 0, tzinfo=dt.timezone.utc)
D = dt.date(2026, 11, 16)

HOLIDAYS = {dt.date(2026, 11, 26)}
HALF_DAYS = {dt.date(2026, 11, 27)}

REVIEWED_BUILDS = {"demo_ma": {"a" * 32}}
ALLOWED_SYMBOLS = {"SPY", "QQQ"}
REVIEWED_PRODUCER = "portfolio_agg_v1"


def bar_day(session_date: dt.date) -> dt.datetime:
    return dt.datetime.combine(session_date, dt.time(16, 0), tzinfo=ET).astimezone(
        dt.timezone.utc
    )


def daily_bars(sessions: list[dt.date], base: str = "100") -> list[tuple[dt.datetime, Decimal]]:
    return [(bar_day(d), Decimal(base)) for d in sessions]


def split_action(effective: dt.datetime, available: object, factor: str = "2") -> dict:
    return {
        "kind": "SPLIT",
        "factor": Decimal(factor),
        "announced_at": effective - dt.timedelta(days=2),
        "effective_at": effective,
        "available_at": available,
        "source": "synthetic",
    }
