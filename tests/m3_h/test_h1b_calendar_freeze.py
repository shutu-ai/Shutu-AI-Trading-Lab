"""H1B T3 — frozen NYSE 2017–2025 calendar supply + purpose row.

The supply was assembled from archived OFFICIAL NYSE calendar pages
(Wayback snapshots of nyse.com, snapshot+original URLs recorded) plus
the ICE/NYSE press release for the 2018-12-05 national day of mourning,
retrieved 2026-11-27. Window deliberately ends 2026-01-31: it covers
the H1 study window 2017-01-01..2025-12-31 PLUS the required next
trading day (Fri 2026-01-02, three sources agreeing) with a small
boundary margin, so only facts actually sourced are frozen.

Positive tests use calendar PATTERN DISCRIMINATORS — the same calendar
date pattern in different years MUST yield different next-opens purely
from the frozen supply (never weekday inference):

- Jun 18 close: 2021 -> Mon Jun 21 (no Juneteenth observation);
  2022 -> Tue Jun 21 (Juneteenth observed Mon Jun 20)
- Dec 21..24 closings: 2017 Fri Dec 22 -> Tue Dec 26 (no Christmas Eve
  early close); 2018 Fri Dec 21 -> Mon Dec 24 (early-close day still
  OPENS 09:30); 2021 Thu Dec 23 -> Mon Dec 27 (Dec 24 = observed
  holiday, full closure); 2022 Thu Dec 23 -> Tue Dec 27 (Dec 26
  observed, Dec 23 NOT an early close)
- New Year: 2021 Dec 31 -> Mon Jan 3 2022 (NO observation, Rule 7.2);
  2022 Dec 30 -> Tue Jan 3 2023 (Jan 2 observed)
- Mourning: Tue Dec 4 2018 -> Thu Dec 6 2018 (Dec 5 closure)
- Boundary: Thu Dec 31 2025 -> Fri Jan 2 2026 (first 2026 session)

License: ICE/NYSE website terms are ambiguous-to-restrictive for
systematic collection — recorded LICENSE_UNVERIFIED in the supply
metadata; this round does NOT claim real-research usability.
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

from trading_lab.data.calendar import ET, UTC, CalendarError  # noqa: E402


def _et(y, m, d, hh, mm):
    return dt.datetime(y, m, d, hh, mm, tzinfo=ET)


FROZEN_GRACE_SECONDS = 900  # pre-registered next-open tolerance, frozen this round


class TestFrozenSupply:
    def test_supply_constructs_versioned_and_windowed(self):
        from trading_lab.data.historical_calendar_supply import NYSE_2017_2025_SUPPLY as s

        assert s.version == "nyse-2017-2026-01-frozen-v1"
        assert s.valid_from == dt.date(2017, 1, 1)
        assert s.valid_until == dt.date(2026, 1, 31)
        assert s.retrieved_utc == dt.datetime(2026, 11, 27, tzinfo=dt.timezone.utc)
        assert "web.archive.org" in s.source_url or "nyse.com" in s.source_url
        assert "LICENSE_UNVERIFIED" in s.source

    def test_every_holiday_is_a_closed_weekday_session(self):
        from trading_lab.data.historical_calendar import VersionedMarketCalendar
        from trading_lab.data.historical_calendar_supply import NYSE_2017_2025_SUPPLY as supply

        cal = VersionedMarketCalendar.from_supply(supply)
        for day in sorted(supply.holidays):
            assert day.weekday() < 5, f"{day} is a weekend date (supply defect)"
            assert not cal.is_trading_day(day), f"{day} declared holiday but trading"

    def test_every_half_day_closes_at_1300_et(self):
        from trading_lab.data.historical_calendar import VersionedMarketCalendar
        from trading_lab.data.historical_calendar_supply import NYSE_2017_2025_SUPPLY as supply

        cal = VersionedMarketCalendar.from_supply(supply)
        for day in sorted(supply.half_days):
            info = cal.session(day)
            assert info.is_trading_day and info.is_half_day
            assert info.close_et == dt.time(13, 0)

    def test_juneteenth_discriminator(self):
        from trading_lab.data.historical_calendar import VersionedMarketCalendar
        from trading_lab.data.historical_calendar_supply import NYSE_2017_2025_SUPPLY

        cal = VersionedMarketCalendar.from_supply(NYSE_2017_2025_SUPPLY)
        # 2021: law signed June 2021, NYSE did NOT observe it that year
        assert cal.session_open_after(_et(2021, 6, 18, 16, 0).astimezone(UTC)) == _et(2021, 6, 21, 9, 30)
        # 2022: first NYSE Juneteenth closure (Jun 19 Sunday -> Jun 20 observed)
        assert cal.session_open_after(_et(2022, 6, 17, 16, 0).astimezone(UTC)) == _et(2022, 6, 21, 9, 30)

    def test_bush_mourning_day_discriminator(self):
        from trading_lab.data.historical_calendar import VersionedMarketCalendar
        from trading_lab.data.historical_calendar_supply import NYSE_2017_2025_SUPPLY

        cal = VersionedMarketCalendar.from_supply(NYSE_2017_2025_SUPPLY)
        assert cal.session_open_after(_et(2018, 12, 4, 16, 0).astimezone(UTC)) == _et(2018, 12, 6, 9, 30)

    def test_christmas_week_pattern_discriminators(self):
        from trading_lab.data.historical_calendar import VersionedMarketCalendar
        from trading_lab.data.historical_calendar_supply import NYSE_2017_2025_SUPPLY

        cal = VersionedMarketCalendar.from_supply(NYSE_2017_2025_SUPPLY)
        # 2017: Dec 24 Sunday -> no Christmas Eve early close
        assert cal.session_open_after(_et(2017, 12, 22, 16, 0).astimezone(UTC)) == _et(2017, 12, 26, 9, 30)
        # 2018: Dec 24 (Monday) EARLY CLOSE day still opens 09:30
        assert cal.session_open_after(_et(2018, 12, 21, 16, 0).astimezone(UTC)) == _et(2018, 12, 24, 9, 30)
        # 2021: Dec 24 itself = observed Christmas holiday (full closure)
        assert cal.session_open_after(_et(2021, 12, 23, 16, 0).astimezone(UTC)) == _et(2021, 12, 27, 9, 30)
        # 2022: Dec 23 NOT an early close; Dec 26 Monday = observed holiday
        assert cal.session_open_after(_et(2022, 12, 23, 16, 0).astimezone(UTC)) == _et(2022, 12, 27, 9, 30)

    def test_new_year_observation_discriminator(self):
        from trading_lab.data.historical_calendar import VersionedMarketCalendar
        from trading_lab.data.historical_calendar_supply import NYSE_2017_2025_SUPPLY

        cal = VersionedMarketCalendar.from_supply(NYSE_2017_2025_SUPPLY)
        # 2022: Jan 1 Saturday, NO observation (NYSE Rule 7.2)
        assert cal.session_open_after(_et(2021, 12, 31, 16, 0).astimezone(UTC)) == _et(2022, 1, 3, 9, 30)
        # 2023: Jan 1 Sunday -> Jan 2 Monday observed
        assert cal.session_open_after(_et(2022, 12, 30, 16, 0).astimezone(UTC)) == _et(2023, 1, 3, 9, 30)

    def test_2026_boundary_next_trading_day(self):
        from trading_lab.data.historical_calendar import VersionedMarketCalendar
        from trading_lab.data.historical_calendar_supply import NYSE_2017_2025_SUPPLY

        cal = VersionedMarketCalendar.from_supply(NYSE_2017_2025_SUPPLY)
        # first 2026 session: Friday Jan 2 (Jan 1 Thursday holiday)
        assert cal.session_open_after(_et(2025, 12, 31, 16, 0).astimezone(UTC)) == _et(2026, 1, 2, 9, 30)

    def test_outside_window_fail_closed(self):
        from trading_lab.data.historical_calendar import VersionedMarketCalendar
        from trading_lab.data.historical_calendar_supply import NYSE_2017_2025_SUPPLY

        cal = VersionedMarketCalendar.from_supply(NYSE_2017_2025_SUPPLY)
        with pytest.raises(CalendarError):
            cal.session(dt.date(2026, 2, 2))  # beyond 2026-01-31 window
        with pytest.raises(CalendarError) as exc:
            cal.session_open_after(_et(2026, 1, 30, 16, 0).astimezone(UTC))
        assert "coverage" in str(exc.value).lower()

    def test_freeze_hash_is_stable(self):
        from trading_lab.data.historical_calendar_supply import (
            NYSE_2017_2025_SUPPLY,
            frozen_supply_hash,
        )

        assert (
            frozen_supply_hash(NYSE_2017_2025_SUPPLY)
            == "826bd96a08b18ada69f77010fa2006516f5088d69a8fb1ceec44033ec106e285"
        )


class TestPurposeRowFrozen:
    def test_row_present_with_concrete_thresholds(self):
        from trading_lab.data.acceptance import load_acceptance_config
        from trading_lab.data.historical import derive_max_latency_seconds
        from trading_lab.data.historical_calendar import VersionedMarketCalendar
        from trading_lab.data.historical_calendar_supply import NYSE_2017_2025_SUPPLY

        cfg = load_acceptance_config(REPO_ROOT / "configs" / "data_acceptance.yaml")
        row = cfg.purpose("historical_research_limited_etf")
        assert row.available_at_rule == "daily_close_available_next_open"
        assert row.on_fail == "RESTRICT_SCOPE"
        assert row.required_license_scope == "personal_research"
        assert row.max_missing_rate == 0.001 and row.min_coverage_rate == 0.999
        calendar = VersionedMarketCalendar.from_supply(NYSE_2017_2025_SUPPLY)
        derived, derivation = derive_max_latency_seconds(calendar, FROZEN_GRACE_SECONDS)
        # single source of truth: config threshold == frozen derivation
        assert row.max_latency_seconds == derived
        assert derivation["grace_seconds"] == FROZEN_GRACE_SECONDS

    def test_four_legacy_purposes_untouched(self):
        from trading_lab.data.acceptance import load_acceptance_config

        cfg = load_acceptance_config(REPO_ROOT / "configs" / "data_acceptance.yaml")
        ids = [p.purpose_id for p in cfg.purposes]
        assert ids == [
            "pipeline_poc",
            "engineering_monitoring",
            "historical_research_daily",
            "event_research",
            "historical_research_limited_etf",
        ]
        old = cfg.purpose("historical_research_daily")
        assert old.available_at_rule == "announced_or_published_before_use"
        assert old.max_latency_seconds == 7200 and old.on_fail == "BLOCKED_DATA"
        assert cfg.purpose("pipeline_poc").max_latency_seconds == 86400
        assert cfg.purpose("engineering_monitoring").max_latency_seconds == 3600
        assert cfg.purpose("event_research").max_latency_seconds == 900
