"""Calendar supply v2 self-validation (BUSINESS-MVP-V02 workflow A1).

v1 of the frozen NYSE supply shipped with two hard errors: it omitted
2025-01-09 (Carter national day of mourning) and 2026-01-19 (MLK Day)
while claiming coverage through 2026-01-31. v2 folds the corrections
in; this file pins, version by version:

- the v2 hash is deterministic and matches the frozen constant;
- the defect is pinned HONESTLY: v1 genuinely lacked both dates (the
  old hash/evidence is preserved, never rewritten);
- a full-coverage sweep over [2017-01-01, 2026-01-31] classifies every
  date without error, weekends and holidays non-trading;
- the v1->v2 session-count delta is exactly the documented -2;
- the next-open rule jumps correctly over both newly-closed days.

v1 test expectations (tests/m3_h/test_h1b_calendar_freeze.py) are NOT
modified here — they pin v1 as-frozen, defects included.
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (REPO_ROOT / "src", REPO_ROOT / "tests", REPO_ROOT):
    _sp = str(_p)
    if _sp not in sys.path:
        sys.path.insert(0, _sp)

from trading_lab.data.calendar import ET  # noqa: E402
from trading_lab.data.historical_calendar import VersionedMarketCalendar  # noqa: E402
from trading_lab.data.historical_calendar_supply import (  # noqa: E402
    FROZEN_SUPPLY_HASH,
    FROZEN_SUPPLY_HASH_V2,
    NYSE_2017_2025_SUPPLY,
    NYSE_2017_2025_SUPPLY_V2,
    frozen_supply_hash,
)

UTC = dt.timezone.utc
CARTER_MOURNING = dt.date(2025, 1, 9)
MLK_2026 = dt.date(2026, 1, 19)


def _et_close_utc(day: dt.date) -> dt.datetime:
    """16:00 ET of ``day`` as a UTC instant (DST via zoneinfo)."""
    return dt.datetime.combine(day, dt.time(16, 0), tzinfo=ET).astimezone(UTC)


# ---------------------------------------------------------------------------
# (a) v2 hash determinism
# ---------------------------------------------------------------------------


class TestV2HashDeterminism:
    def test_v2_hash_matches_frozen_constant(self) -> None:
        assert frozen_supply_hash(NYSE_2017_2025_SUPPLY_V2) == FROZEN_SUPPLY_HASH_V2

    def test_v2_hash_computed_twice_is_stable(self) -> None:
        first = frozen_supply_hash(NYSE_2017_2025_SUPPLY_V2)
        again = VersionedMarketCalendar.from_supply(
            NYSE_2017_2025_SUPPLY_V2
        ).supply
        assert frozen_supply_hash(again) == first == FROZEN_SUPPLY_HASH_V2

    def test_v1_frozen_hash_untouched_and_distinct(self) -> None:
        """v1 stays pinned exactly as frozen (evidence preservation) and
        the correction necessarily changed the hash."""
        assert frozen_supply_hash(NYSE_2017_2025_SUPPLY) == FROZEN_SUPPLY_HASH
        assert FROZEN_SUPPLY_HASH_V2 != FROZEN_SUPPLY_HASH

    def test_v2_version_and_window_fields(self) -> None:
        supply = NYSE_2017_2025_SUPPLY_V2
        assert supply.version == "nyse-2017-2026-01-frozen-v2"
        assert supply.valid_from == dt.date(2017, 1, 1)
        assert supply.valid_until == dt.date(2026, 1, 31)
        # nothing but the holidays moved
        assert supply.half_days == NYSE_2017_2025_SUPPLY.half_days
        assert supply.valid_from == NYSE_2017_2025_SUPPLY.valid_from
        assert supply.valid_until == NYSE_2017_2025_SUPPLY.valid_until
        assert "LICENSE_UNVERIFIED" in supply.source


# ---------------------------------------------------------------------------
# (b) the defect, pinned honestly — v1 lacks both dates, v2 has them
# ---------------------------------------------------------------------------


class TestPinnedDefect:
    def test_v2_contains_both_added_holidays(self) -> None:
        assert CARTER_MOURNING in NYSE_2017_2025_SUPPLY_V2.holidays
        assert MLK_2026 in NYSE_2017_2025_SUPPLY_V2.holidays

    def test_v1_historically_lacked_both_dates(self) -> None:
        """The historical defect is recorded, not hidden: the preserved
        v1 supply classified both days as trading sessions."""
        assert CARTER_MOURNING not in NYSE_2017_2025_SUPPLY.holidays
        assert MLK_2026 not in NYSE_2017_2025_SUPPLY.holidays

    def test_v2_delta_is_exactly_the_two_dates(self) -> None:
        delta = NYSE_2017_2025_SUPPLY_V2.holidays - NYSE_2017_2025_SUPPLY.holidays
        assert delta == {CARTER_MOURNING, MLK_2026}
        assert NYSE_2017_2025_SUPPLY.holidays - NYSE_2017_2025_SUPPLY_V2.holidays == set()

    def test_both_added_dates_are_weekdays(self) -> None:
        """MarketCalendar refuses weekend holiday entries at construction
        (VersionedMarketCalendar.from_supply would raise), so a successful
        construction below is itself the weekday proof."""
        assert CARTER_MOURNING.weekday() == 3  # Thursday
        assert MLK_2026.weekday() == 0  # Monday


# ---------------------------------------------------------------------------
# (c) full-coverage sweep [2017-01-01, 2026-01-31]
# ---------------------------------------------------------------------------

SWEEP_START = dt.date(2017, 1, 1)
SWEEP_END = dt.date(2026, 1, 31)


class TestFullCoverageSweep:
    def test_every_date_classifies_weekends_and_holidays_closed(self) -> None:
        calendar = VersionedMarketCalendar.from_supply(NYSE_2017_2025_SUPPLY_V2)
        day = SWEEP_START
        checked_trading = 0
        while day <= SWEEP_END:
            info = calendar.session(day)  # must never raise in-window
            if day.weekday() >= 5 or day in NYSE_2017_2025_SUPPLY_V2.holidays:
                assert not info.is_trading_day, (
                    f"{day.isoformat()} is a weekend/holiday but classified "
                    "as a trading session"
                )
                assert info.open_et is None and info.close_et is None
            else:
                assert info.is_trading_day
                checked_trading += 1
            day += dt.timedelta(days=1)

    def test_all_supplied_holidays_are_weekdays_inside_window(self) -> None:
        supply = NYSE_2017_2025_SUPPLY_V2
        for day in supply.holidays:
            assert day.weekday() < 5
            assert supply.valid_from <= day <= supply.valid_until

    def test_full_window_session_count_drops_by_exactly_two(self) -> None:
        v2 = VersionedMarketCalendar.from_supply(NYSE_2017_2025_SUPPLY_V2)
        v1 = VersionedMarketCalendar.from_supply(NYSE_2017_2025_SUPPLY)
        assert len(v2.expected_sessions(SWEEP_START, SWEEP_END)) == (
            len(v1.expected_sessions(SWEEP_START, SWEEP_END)) - 2
        )


# ---------------------------------------------------------------------------
# (d) expected_sessions deltas around the two fixed dates
# ---------------------------------------------------------------------------


class TestExpectedSessionDeltas:
    def test_week_of_carter_mourning_differs_by_exactly_minus_one(self) -> None:
        v2 = VersionedMarketCalendar.from_supply(NYSE_2017_2025_SUPPLY_V2)
        v1 = VersionedMarketCalendar.from_supply(NYSE_2017_2025_SUPPLY)
        v1_sessions = v1.expected_sessions(dt.date(2025, 1, 8), dt.date(2025, 1, 10))
        v2_sessions = v2.expected_sessions(dt.date(2025, 1, 8), dt.date(2025, 1, 10))
        # v1 wrongly counted the Thursday 2025-01-09 closure as a session
        assert v1_sessions == [
            dt.date(2025, 1, 8),
            dt.date(2025, 1, 9),
            dt.date(2025, 1, 10),
        ]
        assert v2_sessions == [dt.date(2025, 1, 8), dt.date(2025, 1, 10)]
        assert len(v2_sessions) == len(v1_sessions) - 1

    def test_week_of_mlk_2026_differs_by_exactly_minus_one(self) -> None:
        v2 = VersionedMarketCalendar.from_supply(NYSE_2017_2025_SUPPLY_V2)
        v1 = VersionedMarketCalendar.from_supply(NYSE_2017_2025_SUPPLY)
        v1_sessions = v1.expected_sessions(dt.date(2026, 1, 16), dt.date(2026, 1, 20))
        v2_sessions = v2.expected_sessions(dt.date(2026, 1, 16), dt.date(2026, 1, 20))
        # v1 wrongly counted Monday 2026-01-19 (MLK) as a session
        assert v1_sessions == [
            dt.date(2026, 1, 16),
            dt.date(2026, 1, 19),
            dt.date(2026, 1, 20),
        ]
        assert v2_sessions == [dt.date(2026, 1, 16), dt.date(2026, 1, 20)]
        assert len(v2_sessions) == len(v1_sessions) - 1

    def test_documented_delta_over_full_window_is_exactly_minus_two(self) -> None:
        v2 = VersionedMarketCalendar.from_supply(NYSE_2017_2025_SUPPLY_V2)
        v1 = VersionedMarketCalendar.from_supply(NYSE_2017_2025_SUPPLY)
        v1_sessions = set(v1.expected_sessions(SWEEP_START, SWEEP_END))
        v2_sessions = set(v2.expected_sessions(SWEEP_START, SWEEP_END))
        assert v1_sessions - v2_sessions == {CARTER_MOURNING, MLK_2026}
        assert v2_sessions - v1_sessions == set()


# ---------------------------------------------------------------------------
# (e) the next-open rule jumps over the newly closed days
# ---------------------------------------------------------------------------


class TestNextOpenJumps:
    def test_next_open_after_2025_01_08_close_skips_mourning_day(self) -> None:
        v2 = VersionedMarketCalendar.from_supply(NYSE_2017_2025_SUPPLY_V2)
        v1 = VersionedMarketCalendar.from_supply(NYSE_2017_2025_SUPPLY)
        close = _et_close_utc(dt.date(2025, 1, 8))  # Wed 2025-01-08 21:00 UTC
        # v2 (correct): the next OPEN session is Friday 2025-01-10
        assert v2.session_open_after(close) == dt.datetime(
            2025, 1, 10, 14, 30, tzinfo=UTC
        )
        # the preserved v1 table would have answered the closed day —
        # this is precisely the hard error the correction removes
        assert v1.session_open_after(close) == dt.datetime(
            2025, 1, 9, 14, 30, tzinfo=UTC
        )

    def test_next_open_after_2026_01_16_close_skips_mlk_2026(self) -> None:
        v2 = VersionedMarketCalendar.from_supply(NYSE_2017_2025_SUPPLY_V2)
        v1 = VersionedMarketCalendar.from_supply(NYSE_2017_2025_SUPPLY)
        close = _et_close_utc(dt.date(2026, 1, 16))  # Fri 2026-01-16 21:00 UTC
        # v2 (correct): Friday close -> Tuesday 2026-01-20 open (Monday closed)
        assert v2.session_open_after(close) == dt.datetime(
            2026, 1, 20, 14, 30, tzinfo=UTC
        )
        # v1 would have wrongly answered the MLK holiday itself
        assert v1.session_open_after(close) == dt.datetime(
            2026, 1, 19, 14, 30, tzinfo=UTC
        )

    def test_both_new_holidays_never_answer_as_available_moments(self) -> None:
        """No bar closing on the eve of either new holiday can get an
        availability stamp inside the closed day itself."""
        calendar = VersionedMarketCalendar.from_supply(NYSE_2017_2025_SUPPLY_V2)
        for closed_day in (CARTER_MOURNING, MLK_2026):
            eve_close = _et_close_utc(closed_day - dt.timedelta(days=1))
            next_open = calendar.session_open_after(eve_close)
            assert next_open.astimezone(ET).date() != closed_day
            assert next_open > eve_close


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-q"]))
