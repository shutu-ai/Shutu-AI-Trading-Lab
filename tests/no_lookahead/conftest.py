"""No-lookahead suite fixtures (constants live in helpers_no_lookahead)."""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

from helpers_no_lookahead import D, HALF_DAYS, HOLIDAYS  # noqa: E402

from trading_lab.data.calendar import MarketCalendar  # noqa: E402


@pytest.fixture()
def calendar() -> MarketCalendar:
    return MarketCalendar(holidays=HOLIDAYS, half_days=HALF_DAYS)


@pytest.fixture()
def week_sessions(calendar: MarketCalendar) -> list[dt.date]:
    """Mon..Fri of the fixture week: Thu holiday, Fri half day."""
    return [D + dt.timedelta(days=i) for i in range(5)]
