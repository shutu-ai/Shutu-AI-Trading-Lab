"""M3-H H1A targeted-suite fixtures — offline: zero network, zero
credentials, zero real-API calls (REAL_API_CALLS=0 task boundary).

The calendar supply here is a clearly-scoped FIXTURE table: NYSE 2026
Nov 20 - Dec 31 facts only (Thanksgiving 11-26 closed; 11-27 and 12-24
early close 13:00 ET; Christmas 12-25 closed), per the NYSE official
hours calendar. The frozen 2017-2025 research calendar is NOT supplied
this round — that freeze is a separately authorized step
(H1A_PURPOSE_CONFIG=PENDING_CALENDAR_FREEZE).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (REPO_ROOT / "src", REPO_ROOT / "tests"):
    _sp = str(_p)
    if _sp not in sys.path:
        sys.path.insert(0, _sp)

from helpers_m3_h import nyse_2026_fixture_supply  # noqa: E402


@pytest.fixture()
def nyse_calendar():
    from trading_lab.data.historical_calendar import VersionedMarketCalendar

    return VersionedMarketCalendar.from_supply(nyse_2026_fixture_supply())
