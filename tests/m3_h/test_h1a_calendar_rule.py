"""H1A T1 — trading-calendar-driven next-open availability rule and the
controlled ``daily_close_available_next_open`` vocabulary addition.

Calendar facts pinned here (NYSE official hours calendar, cross-checked
2026-11-26; supersedes the WRONG fixture in the 2026-11-24 errata text
that claimed 2026-11-27 closed and next open 2026-11-30 = 113.5h):

- Thu 2026-11-26 Thanksgiving: CLOSED
- Fri 2026-11-27: OPEN, regular 09:30 ET open, 13:00 ET early close
- Thu 2026-12-24: OPEN, 13:00 ET early close
- Fri 2026-12-25 Christmas: CLOSED

Next-open spans (absolute hours, asserted exactly):

- Fri regular close 16:00 -> Mon open 09:30        = 65.5h
- Wed 11-25 close 16:00 -> Fri 11-27 open 09:30    = 41.5h  (NOT 113.5h)
- Fri 11-27 13:00 early close -> Mon 11-30 09:30   = 68.5h
- Thu 12-24 13:00 early close -> Mon 12-28 09:30   = 92.5h
- Fri 03-06 close (EST) -> Mon 03-09 open (EDT)    = 64.5h  (DST weekend)

The rule is a declared MODEL ASSUMPTION: a daily close bar becomes a
decision input at the OPEN of the next valid US trading session. It is
never ``bar_ts_plus_0`` semantics, and a day the calendar supply cannot
certify never yields a positive PIT conclusion (fail-closed).
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (REPO_ROOT / "src", REPO_ROOT / "tests"):
    _sp = str(_p)
    if _sp not in sys.path:
        sys.path.insert(0, _sp)

from trading_lab.data.acceptance import (  # noqa: E402
    AVAILABLE_AT_RULES,
    DataAcceptanceConfigError,
    PurposeRequirements,
    load_acceptance_config,
)
from trading_lab.data.calendar import ET, UTC, CalendarError  # noqa: E402


def _et(y: int, m: int, d: int, hh: int, mm: int) -> dt.datetime:
    return dt.datetime(y, m, d, hh, mm, tzinfo=ET)


def _purpose(rule: str) -> PurposeRequirements:
    """Full-requirements candidate for the H1A template purpose (test-only;
    the official configs/data_acceptance.yaml row stays
    PURPOSE_ROW_PENDING_CALENDAR_FREEZE this round)."""
    return PurposeRequirements(
        purpose_id="historical_research_limited_etf",
        description="H1A offline template purpose (test-only until calendar freeze)",
        data_scope="us_equities_daily_limited_etf_history",
        requires_daily_bars=True,
        requires_minute_bars=False,
        requires_corporate_actions=False,
        requires_history_membership=False,
        requires_delisting=False,
        available_at_rule=rule,
        max_missing_rate=0.001,
        min_coverage_rate=0.999,
        # 335400s = 93.25h template placeholder; the real row's threshold
        # must come from derive_max_latency_seconds() over a FROZEN calendar
        max_latency_seconds=335400,
        required_license_scope="personal_research",
        on_fail="RESTRICT_SCOPE",
    )


class TestRuleVocabulary:
    def test_new_rule_in_closed_vocabulary(self):
        assert "daily_close_available_next_open" in AVAILABLE_AT_RULES

    def test_original_three_values_unchanged(self):
        assert {
            "bar_ts_plus_0",
            "bar_ts_plus_15min",
            "announced_or_published_before_use",
        } <= set(AVAILABLE_AT_RULES)

    def test_new_rule_constructs_purpose_requirements(self):
        req = _purpose("daily_close_available_next_open")
        assert req.available_at_rule == "daily_close_available_next_open"

    def test_illegal_rule_still_fail_closed(self):
        # Direct construction: pydantic wraps the vocabulary ValueError into
        # a ValidationError (fail-closed before any decision can see it).
        with pytest.raises(ValidationError) as exc:
            _purpose("bar_ts_plus_0_but_trust_me")
        assert "available_at_rule" in str(exc.value)

    def test_illegal_rule_via_config_loader_fail_closed(self, tmp_path):
        # The YAML boundary turns the same fault into the uniform
        # DataAcceptanceConfigError callers fail closed on.
        import yaml as _yaml

        payload = _yaml.safe_load(
            (REPO_ROOT / "configs" / "data_acceptance.yaml").read_text(encoding="utf-8")
        )
        payload["purposes"] = [dict(payload["purposes"][0])]
        payload["purposes"][0]["available_at_rule"] = "not_a_real_rule"
        cfg_path = tmp_path / "bad_rule.yaml"
        cfg_path.write_text(_yaml.safe_dump(payload), encoding="utf-8")
        with pytest.raises(DataAcceptanceConfigError):
            load_acceptance_config(cfg_path)

    def test_official_yaml_unchanged_four_purposes(self):
        """H1A pinned four purposes; H1B (2026-11-27) appended
        historical_research_limited_etf after freezing the calendar —
        append-only evolution, the four legacy rows unchanged (values
        asserted in test_h1b_calendar_freeze.py)."""
        cfg = load_acceptance_config(REPO_ROOT / "configs" / "data_acceptance.yaml")
        assert cfg.version == 1
        assert [p.purpose_id for p in cfg.purposes][:4] == [
            "pipeline_poc",
            "engineering_monitoring",
            "historical_research_daily",
            "event_research",
        ]


class TestVersionedCalendarSupply:
    def test_supply_metadata_is_recorded(self, nyse_calendar):
        s = nyse_calendar.supply
        assert s.version == "nyse-2026-h1a-fixture-v1"
        assert s.source_url == "https://www.nyse.com/trade/hours-calendars"
        assert s.source
        assert s.retrieved_utc.tzinfo is not None

    def test_supply_rejects_out_of_window_holiday(self):
        from trading_lab.data.historical_calendar import CalendarSupply

        with pytest.raises(CalendarError):
            CalendarSupply(
                version="v",
                source="s",
                source_url="u",
                retrieved_utc=dt.datetime(2026, 11, 26, tzinfo=dt.timezone.utc),
                valid_from=dt.date(2026, 12, 1),
                valid_until=dt.date(2026, 12, 31),
                holidays=frozenset({dt.date(2026, 11, 26)}),  # outside window
                half_days=frozenset(),
            )

    def test_supply_rejects_naive_retrieval_time(self):
        from trading_lab.data.historical_calendar import CalendarSupply

        with pytest.raises(CalendarError):
            CalendarSupply(
                version="v",
                source="s",
                source_url="u",
                retrieved_utc=dt.datetime(2026, 11, 26),  # naive
                valid_from=dt.date(2026, 11, 20),
                valid_until=dt.date(2026, 12, 31),
                holidays=frozenset(),
                half_days=frozenset(),
            )

    def test_supply_rejects_empty_version_or_source(self):
        from trading_lab.data.historical_calendar import CalendarSupply

        with pytest.raises(CalendarError):
            CalendarSupply(
                version="",
                source="s",
                source_url="u",
                retrieved_utc=dt.datetime(2026, 11, 26, tzinfo=dt.timezone.utc),
                valid_from=dt.date(2026, 11, 20),
                valid_until=dt.date(2026, 12, 31),
                holidays=frozenset(),
                half_days=frozenset(),
            )


class TestSessionClassification:
    def test_thanksgiving_closed(self, nyse_calendar):
        assert not nyse_calendar.is_trading_day(dt.date(2026, 11, 26))

    def test_1127_is_half_day_regular_open(self, nyse_calendar):
        info = nyse_calendar.session(dt.date(2026, 11, 27))
        assert info.is_trading_day and info.is_half_day
        assert info.open_et == dt.time(9, 30)
        assert info.close_et == dt.time(13, 0)

    def test_1224_is_half_day(self, nyse_calendar):
        info = nyse_calendar.session(dt.date(2026, 12, 24))
        assert info.is_trading_day and info.is_half_day

    def test_session_outside_window_refused(self, nyse_calendar):
        with pytest.raises(CalendarError):
            nyse_calendar.session(dt.date(2027, 1, 4))

    def test_no_positive_pit_conclusion_for_uncertified_day(self, nyse_calendar):
        """A day the supply cannot certify never yields a positive
        availability claim — no silent weekday-only assumption."""
        with pytest.raises(CalendarError):
            nyse_calendar.session(dt.date(2026, 10, 30))


class TestNextOpenRule:
    def test_friday_close_to_monday_open_65_5h(self, nyse_calendar):
        close = _et(2026, 11, 20, 16, 0)
        nxt = nyse_calendar.session_open_after(close.astimezone(UTC))
        assert nxt == _et(2026, 11, 23, 9, 30)
        assert nxt - close == dt.timedelta(hours=65.5)

    def test_wed_1125_close_to_fri_1127_open_41_5h(self, nyse_calendar):
        close = _et(2026, 11, 25, 16, 0)
        nxt = nyse_calendar.session_open_after(close.astimezone(UTC))
        assert nxt == _et(2026, 11, 27, 9, 30)  # NOT 2026-11-30 (errata fix)
        assert nxt - close == dt.timedelta(hours=41.5)

    def test_1127_half_day_close_to_monday_open_68_5h(self, nyse_calendar):
        close = _et(2026, 11, 27, 13, 0)
        nxt = nyse_calendar.session_open_after(close.astimezone(UTC))
        assert nxt == _et(2026, 11, 30, 9, 30)
        assert nxt - close == dt.timedelta(hours=68.5)

    def test_christmas_early_close_to_monday_open_92_5h(self, nyse_calendar):
        close = _et(2026, 12, 24, 13, 0)
        nxt = nyse_calendar.session_open_after(close.astimezone(UTC))
        assert nxt == _et(2026, 12, 28, 9, 30)
        assert nxt - close == dt.timedelta(hours=92.5)

    def test_dst_spring_forward_weekend_span_64_5h(self):
        """Same wall-clock schedule across a DST change yields a different
        absolute span: Fri EST close -> Mon EDT open = 64.5h (not 65.5h)."""
        from trading_lab.data.historical_calendar import (
            CalendarSupply,
            VersionedMarketCalendar,
        )

        supply = CalendarSupply(
            version="synthetic-dst-window-v1",
            source="synthetic supply for DST mechanics (no exchange facts implied)",
            source_url="synthetic://tests",
            retrieved_utc=dt.datetime(2026, 11, 26, tzinfo=dt.timezone.utc),
            valid_from=dt.date(2026, 3, 2),
            valid_until=dt.date(2026, 3, 13),
            holidays=frozenset(),
            half_days=frozenset(),
        )
        cal = VersionedMarketCalendar.from_supply(supply)
        close = _et(2026, 3, 6, 16, 0)  # EST (UTC-5) -> 21:00Z
        nxt = cal.session_open_after(close.astimezone(UTC))
        assert nxt == _et(2026, 3, 9, 9, 30)  # EDT (UTC-4) -> 13:30Z
        assert nxt - close == dt.timedelta(hours=64.5)

    def test_open_instant_itself_is_not_its_own_next_open(self, nyse_calendar):
        """The open instant of a session is not 'after' itself: the next
        open after Mon 09:30 ET is Tue 09:30 ET (strictly-after rule)."""
        open_mon = _et(2026, 11, 23, 9, 30)
        nxt = nyse_calendar.session_open_after(open_mon.astimezone(UTC))
        assert nxt == _et(2026, 11, 24, 9, 30)

    def test_next_open_beyond_coverage_refused(self, nyse_calendar):
        # 2026-12-31 (Thu) close -> next session is in Jan 2027: OUTSIDE the
        # fixture window. Must refuse — never silently assume 2027-01-04.
        close = _et(2026, 12, 31, 16, 0)
        with pytest.raises(CalendarError) as exc:
            nyse_calendar.session_open_after(close.astimezone(UTC))
        assert "coverage" in str(exc.value).lower()

    def test_moment_before_window_refused(self, nyse_calendar):
        early = _et(2026, 11, 2, 16, 0)
        with pytest.raises(CalendarError):
            nyse_calendar.session_open_after(early.astimezone(UTC))

    def test_naive_moment_refused(self, nyse_calendar):
        with pytest.raises(CalendarError):
            nyse_calendar.session_open_after(dt.datetime(2026, 11, 23, 14, 30))


class TestExpectedSessions:
    def test_expected_sessions_within_window(self, nyse_calendar):
        sessions = nyse_calendar.expected_sessions(
            dt.date(2026, 11, 23), dt.date(2026, 11, 27)
        )
        assert sessions == [
            dt.date(2026, 11, 23),
            dt.date(2026, 11, 24),
            dt.date(2026, 11, 25),
            dt.date(2026, 11, 27),
        ]

    def test_expected_sessions_outside_window_refused(self, nyse_calendar):
        with pytest.raises(CalendarError):
            nyse_calendar.expected_sessions(dt.date(2026, 1, 5), dt.date(2026, 2, 6))
