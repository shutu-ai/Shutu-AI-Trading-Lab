"""Shared M3-H H1A suite helpers (unique module name, mirrors
helpers_no_lookahead / helpers_m2 pattern)."""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
for _p in (REPO_ROOT / "src", REPO_ROOT / "tests"):
    _sp = str(_p)
    if _sp not in sys.path:
        sys.path.insert(0, _sp)

UTC = dt.timezone.utc
NYSE_HOURS_CALENDAR_URL = "https://www.nyse.com/trade/hours-calendars"

#: THIS round's synthetic download moment (received_at fixture fact)
H1A_RECEIVED_AT = dt.datetime(2026, 11, 26, 12, 0, tzinfo=UTC)


def nyse_2026_fixture_supply():
    """Versioned FIXTURE calendar supply (fixture scope only, Nov 20 -
    Dec 31 2026). Versioned, sourced, windowed — the shape every real
    historical calendar supply must take before any purpose row freezes."""
    from trading_lab.data.historical_calendar import CalendarSupply

    return CalendarSupply(
        version="nyse-2026-h1a-fixture-v1",
        source="NYSE 2026 holiday & early-close calendar (fixture scope only)",
        source_url=NYSE_HOURS_CALENDAR_URL,
        retrieved_utc=dt.datetime(2026, 11, 26, tzinfo=UTC),
        valid_from=dt.date(2026, 11, 20),
        valid_until=dt.date(2026, 12, 31),
        holidays=frozenset({dt.date(2026, 11, 26), dt.date(2026, 12, 25)}),
        half_days=frozenset({dt.date(2026, 11, 27), dt.date(2026, 12, 24)}),
    )
