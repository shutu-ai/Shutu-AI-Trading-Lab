"""Shared fixtures for the M1 no-lookahead / data-quality suite.

All fixtures are synthetic — they prove the LOGIC only; vendor coverage and
latency claims come exclusively from data-vendors.md (DOCUMENTED) or future
API_VERIFIED evidence. This boundary is asserted in test_acceptance.
"""

from __future__ import annotations

import datetime as dt
import sys
from decimal import Decimal
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from trading_lab.data.calendar import ET, MarketCalendar  # noqa: E402

NOW = dt.datetime(2026, 11, 20, 21, 0, 0, tzinfo=dt.timezone.utc)  # 16:00 ET
D = dt.date(2026, 11, 16)  # Monday

# A fixed, self-consistent holiday table (synthetic dates, not a real-year
# calendar): Thanksgiving-like Thursday off + a Friday half day.
HOLIDAYS = {dt.date(2026, 11, 26)}
HALF_DAYS = {dt.date(2026, 11, 27)}


@pytest.fixture()
def calendar() -> MarketCalendar:
    return MarketCalendar(holidays=HOLIDAYS, half_days=HALF_DAYS)


@pytest.fixture()
def week_sessions(calendar: MarketCalendar) -> list[dt.date]:
    """Mon..Fri of the fixture week: 4 trading days (Thu holiday, Fri half)."""
    return [D + dt.timedelta(days=i) for i in range(5)]


def bar_day(session_date: dt.date) -> dt.datetime:
    """UTC stamp for a session's 16:00 ET close on ``session_date``."""
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
