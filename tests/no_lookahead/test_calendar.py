"""Calendar tests: DST correctness, holiday/half-day classification, the
point-in-time availability gate, and rejection of naive timestamps."""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from trading_lab.data.calendar import CalendarError, ET, MarketCalendar, UTC

from conftest import HALF_DAYS, HOLIDAYS, D


class TestDstConversion:
    def test_summer_edt_minus_four(self):
        july = dt.datetime(2026, 7, 15, 12, 0, tzinfo=ET)
        assert july.astimezone(UTC).utcoffset() == dt.timedelta(0)
        assert july.utcoffset() == dt.timedelta(hours=-4)

    def test_winter_est_minus_five(self):
        jan = dt.datetime(2026, 1, 15, 12, 0, tzinfo=ET)
        assert jan.utcoffset() == dt.timedelta(hours=-5)

    def test_dst_transition_day_resolved(self):
        # 2026-03-08 02:30 ET does not exist (spring forward); 03:30 does.
        after = dt.datetime(2026, 3, 8, 3, 30, tzinfo=ET)
        assert after.utcoffset() == dt.timedelta(hours=-4)
        fall_back = dt.datetime(2026, 11, 1, 1, 30, tzinfo=ET)  # ambiguous hour
        assert fall_back.utcoffset() in (dt.timedelta(hours=-4), dt.timedelta(hours=-5))

    def test_naive_utc_rejected_on_to_et(self):
        with pytest.raises(CalendarError):
            MarketCalendar.to_et(dt.datetime(2026, 1, 15, 17, 0))

    def test_roundtrip_et_utc(self):
        stamp = dt.datetime(2026, 11, 20, 9, 30, tzinfo=ET)
        assert MarketCalendar.to_et(MarketCalendar.to_utc(stamp)) == stamp


class TestSessions:
    def test_holiday_not_trading_day(self, calendar: MarketCalendar):
        thanksgiving = dt.date(2026, 11, 26)
        info = calendar.session(thanksgiving)
        assert not info.is_trading_day and info.close_et is None

    def test_half_day_closes_1300_et(self, calendar: MarketCalendar):
        info = calendar.session(dt.date(2026, 11, 27))
        assert info.is_trading_day and info.is_half_day
        assert info.close_et == dt.time(13, 0)
        assert info.close_utc() == dt.datetime(2026, 11, 27, 18, 0, tzinfo=UTC)

    def test_weekend_not_trading_day(self, calendar: MarketCalendar):
        assert not calendar.is_trading_day(dt.date(2026, 11, 21))  # Saturday

    def test_regular_session_930_to_1600(self, calendar: MarketCalendar):
        info = calendar.session(D)
        assert info.open_utc() == dt.datetime(2026, 11, 16, 14, 30, tzinfo=UTC)
        assert info.close_utc() == dt.datetime(2026, 11, 16, 21, 0, tzinfo=UTC)

    def test_duplicate_holiday_rejected(self):
        # A set cannot contain duplicates — feed a list-equivalent via two
        # equal dates expressed distinctly to hit the validator.
        with pytest.raises(CalendarError):
            MarketCalendar(holidays={dt.date(2026, 12, 25)}, half_days={dt.date(2026, 12, 25)})


class TestPitGate:
    def test_available_at_or_before_cutoff_passes(self):
        assert MarketCalendar.is_available(
            dt.datetime(2026, 11, 20, 20, 0, tzinfo=UTC),
            dt.datetime(2026, 11, 20, 21, 0, tzinfo=UTC),
        )

    def test_available_after_cutoff_blocked(self):
        assert not MarketCalendar.is_available(
            dt.datetime(2026, 11, 20, 22, 0, tzinfo=UTC),
            dt.datetime(2026, 11, 20, 21, 0, tzinfo=UTC),
        )

    def test_naive_timestamps_rejected(self):
        with pytest.raises(CalendarError):
            MarketCalendar.is_available(
                dt.datetime(2026, 11, 20, 20, 0), dt.datetime(2026, 11, 20, 21, 0, tzinfo=UTC)
            )
