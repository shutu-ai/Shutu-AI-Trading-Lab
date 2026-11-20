"""Corporate-action recomputation and membership PIT negatives: hindsight
adjustment, unknown availability, future-known actions, today's-universe
substitution, delisted omission, ticker reuse."""

from __future__ import annotations

import datetime as dt
import sys
from decimal import Decimal
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from trading_lab.data.actions import (
    ADJUST_TRANSFORM_VERSION,
    ActionError,
    ActionRecord,
    adjust_series,
)
from trading_lab.data.membership import (
    DelistingRecord,
    MembershipError,
    MembershipRecord,
    MembershipTable,
)
from trading_lab.data.records import MARKER_UNKNOWN_AVAILABILITY

from conftest import NOW, bar_day, daily_bars

U = dt.timezone.utc


def make_action(effective: dt.datetime, available: object, factor: str = "2") -> ActionRecord:
    return ActionRecord(
        symbol="SPY",
        kind="SPLIT",
        factor=Decimal(factor),
        announced_at=effective - dt.timedelta(days=2),
        effective_at=effective,
        available_at=available,
        source="synthetic",
    )


class TestAdjustSeries:
    def test_split_recomputation_exact(self):
        sessions = [dt.date(2026, 11, 16) + dt.timedelta(days=i) for i in range(4)]
        bars = daily_bars(sessions, base="100")
        split = make_action(bar_day(dt.date(2026, 11, 18)), bar_day(dt.date(2026, 11, 16)))
        result = adjust_series("SPY", bars, [split], asof=NOW)
        assert result.transform_version == ADJUST_TRANSFORM_VERSION
        # Pre-split bars halved; post-split bars unchanged.
        values = {t: v for t, v in result.adjusted_closes}
        assert values[bar_day(sessions[0])] == Decimal("50.0000")
        assert values[bar_day(dt.date(2026, 11, 18))] == Decimal("100.0000")
        assert len(result.applied_actions) == 1

    def test_deterministic_same_inputs_same_output(self):
        sessions = [dt.date(2026, 11, 16) + dt.timedelta(days=i) for i in range(3)]
        bars = daily_bars(sessions)
        split = make_action(bar_day(dt.date(2026, 11, 17)), bar_day(dt.date(2026, 11, 16)))
        r1 = adjust_series("SPY", bars, [split], asof=NOW)
        r2 = adjust_series("SPY", bars, [split], asof=NOW)
        assert r1.adjusted_closes == r2.adjusted_closes

    def test_hindsight_split_not_applied_before_available(self):
        """复权因子事后知识混入: a split becomes available *after* NOW —
        viewing the series at NOW must not use it, at a later asof it must."""
        sessions = [dt.date(2026, 11, 16) + dt.timedelta(days=i) for i in range(2)]
        bars = daily_bars(sessions)
        split = make_action(
            bar_day(dt.date(2026, 11, 17)),
            available=NOW + dt.timedelta(days=1),  # available tomorrow
        )
        before = adjust_series("SPY", bars, [split], asof=NOW)
        assert before.applied_actions == ()
        assert all(v == Decimal("100.0000") for _, v in before.adjusted_closes)
        later = adjust_series(
            "SPY", bars, [split], asof=dt.datetime(2026, 11, 22, tzinfo=U)
        )
        assert len(later.applied_actions) == 1
        assert any(v == Decimal("50.0000") for _, v in later.adjusted_closes)

    def test_unknown_availability_never_applied_and_reported(self):
        """缺少可得时间: the action cannot be silently applied; it is
        reported so the caller degrades the series."""
        bars = daily_bars([dt.date(2026, 11, 16)])
        act = make_action(bar_day(dt.date(2026, 11, 16)), MARKER_UNKNOWN_AVAILABILITY)
        result = adjust_series("SPY", bars, [act], asof=NOW)
        assert result.applied_actions == ()
        assert len(result.unknown_availability_actions) == 1
        assert all(v == Decimal("100.0000") for _, v in result.adjusted_closes)

    def test_future_known_action_reported_not_applied(self):
        bars = daily_bars([dt.date(2026, 11, 16)])
        act = make_action(
            effective=bar_day(dt.date(2026, 12, 1)),  # effective after NOW
            available=bar_day(dt.date(2026, 11, 16)),
        )
        result = adjust_series("SPY", bars, [act], asof=NOW)
        assert result.applied_actions == ()
        assert len(result.future_known_actions) == 1

    def test_action_with_future_effective_within_window(self):
        """公告晚于决策时刻: announced after asof -> not usable at asof."""
        bars = daily_bars([dt.date(2026, 11, 16)])
        act = ActionRecord(
            symbol="SPY",
            kind="SPLIT",
            factor=Decimal(2),
            announced_at=dt.datetime(2026, 11, 25, tzinfo=U),  # announced later
            effective_at=bar_day(dt.date(2026, 11, 17)),
            available_at=dt.datetime(2026, 11, 25, tzinfo=U),
            source="synthetic",
        )
        result = adjust_series("SPY", bars, [act], asof=NOW)
        assert result.applied_actions == ()

    def test_invalid_factor_rejected(self):
        with pytest.raises(ActionError):
            make_action(bar_day(dt.date(2026, 11, 17)), bar_day(dt.date(2026, 11, 16)), factor="0")

    def test_naive_effective_rejected(self):
        with pytest.raises(ActionError):
            ActionRecord(
                symbol="SPY", kind="SPLIT", factor=Decimal(2),
                announced_at=None,
                effective_at=dt.datetime(2026, 11, 17, 21, 0),  # naive
                available_at=dt.datetime(2026, 11, 16, tzinfo=U),
                source="s",
            )


def membership_table() -> MembershipTable:
    A = lambda *a: dt.datetime(*a, tzinfo=U)  # noqa: E731
    return MembershipTable(
        membership=[
            MembershipRecord(
                index_id="SPX", symbol="OLD", effective_from=A(1990, 1, 1),
                effective_to=A(2020, 1, 1),
                announced_at=A(1990, 1, 1), available_at=A(1990, 1, 1),
                source="synthetic",
            ),
            MembershipRecord(
                index_id="SPX", symbol="NEW", effective_from=A(2020, 1, 1),
                effective_to=None,
                announced_at=A(2019, 12, 20), available_at=A(2019, 12, 23),
                source="synthetic",
            ),
            MembershipRecord(
                index_id="SPX", symbol="PENDING", effective_from=A(2026, 12, 1),
                effective_to=None,
                announced_at=A(2026, 12, 1), available_at=A(2026, 12, 1),
                source="synthetic",
            ),
        ],
        delistings=[
            DelistingRecord(
                symbol="GONE", venue="NASDAQ", listed_from=A(2000, 1, 1),
                listed_to=A(2015, 6, 1), delisted_at=A(2015, 6, 1),
                successor_ticker=None, source="synthetic",
            ),
            DelistingRecord(
                symbol="REBRAND", venue="NYSE", listed_from=A(2000, 1, 1),
                listed_to=A(2018, 1, 1), delisted_at=A(2018, 1, 1),
                successor_ticker="NEWNAME", source="synthetic",
            ),
            # Ticker reuse: SAME ticker listed twice, non-contiguous.
            DelistingRecord(
                symbol="TWICE", venue="NYSE", listed_from=A(2000, 1, 1),
                listed_to=A(2005, 1, 1), delisted_at=A(2005, 1, 1),
                successor_ticker=None, source="synthetic",
            ),
            DelistingRecord(
                symbol="TWICE", venue="NYSE", listed_from=A(2010, 1, 1),
                listed_to=A(2020, 1, 1), delisted_at=A(2020, 1, 1),
                successor_ticker=None, source="synthetic",
            ),
        ],
    )


class TestMembershipPit:
    def test_universe_uses_history_not_today(self):
        """今天证券池替代过去证券池: at 2019, OLD is a member and NEW is
        not-yet-effective; today's snapshot would say NEW only."""
        table = membership_table()
        u2019 = table.universe_asof(dt.datetime(2019, 6, 1, tzinfo=U), "SPX")
        assert "OLD" in u2019 and "NEW" not in u2019
        u2020 = table.universe_asof(dt.datetime(2020, 6, 1, tzinfo=U), "SPX")
        assert "NEW" in u2020 and "OLD" not in u2020

    def test_unavailable_future_change_excluded(self):
        table = membership_table()
        u = table.universe_asof(NOW, "SPX")
        assert "PENDING" not in u  # announced/effective after NOW

    def test_delisted_symbols_retained(self):
        """退市证券遗漏: delisted symbols must remain queryable forever."""
        table = membership_table()
        gone = table.delisted_symbols(NOW)
        assert "GONE" in gone and "REBRAND" in gone
        # and before the delisting date they are not yet "delisted"
        assert "GONE" not in table.delisted_symbols(dt.datetime(2014, 1, 1, tzinfo=U))

    def test_ticker_reuse_detected(self):
        table = membership_table()
        assert "TWICE" in table.reused_tickers

    def test_mapping_resolves_after_delisting(self):
        table = membership_table()
        assert table.mapping_for("REBRAND", NOW) == "NEWNAME"
        assert table.mapping_for("REBRAND", dt.datetime(2017, 1, 1, tzinfo=U)) is None

    def test_overlapping_reused_intervals_rejected(self):
        A = lambda *a: dt.datetime(*a, tzinfo=U)  # noqa: E731
        with pytest.raises(MembershipError):
            MembershipTable(
                membership=[],
                delistings=[
                    DelistingRecord("X", "NYSE", A(2000, 1, 1), A(2005, 1, 1), A(2005, 1, 1), None, "s"),
                    DelistingRecord("X", "NYSE", A(2004, 1, 1), A(2010, 1, 1), A(2010, 1, 1), None, "s"),
                ],
            )
