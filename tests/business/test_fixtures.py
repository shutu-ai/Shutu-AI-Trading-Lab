"""B1 fixture tests: determinism, calendar/segment shape, DATA_QUALITY
defects, sample-gate size, the QQQ-gap control construct, and the
next-open helper."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from pathlib import Path

import pytest

from trading_lab.business.config import BusinessConfig
from trading_lab.business.fixtures import (
    DATASET_NAME,
    SEGMENT_TAGS,
    DemoDataset,
    build_demo_dataset,
)
from trading_lab.business.series import QUALITY_SYNTHETIC_STALE
from trading_lab.validation import EvaluationProtocol

REPO_ROOT = Path(__file__).resolve().parents[2]
PROTOCOL_PATH = REPO_ROOT / "configs" / "evaluation_protocol.yaml"
UTC = dt.timezone.utc


def _asof(session_date: dt.date) -> dt.datetime:
    """Synthetic decision clock: session close, 21:00 UTC."""
    return dt.datetime.combine(session_date, dt.time(21, 0), tzinfo=UTC)


def _bars_by_date(bars) -> dict[dt.date, object]:
    return {bar.ts_event_utc.date(): bar for bar in bars}


@pytest.fixture(scope="module")
def config() -> BusinessConfig:
    return BusinessConfig()


@pytest.fixture(scope="module")
def demo(config) -> DemoDataset:
    return build_demo_dataset(config)


class TestDeterminism:
    def test_same_config_identical_hash_and_bars(self, config, demo) -> None:
        rebuild = build_demo_dataset(config)
        assert rebuild.dataset.dataset_hash == demo.dataset.dataset_hash
        assert rebuild.session_dates == demo.session_dates
        assert dict(rebuild.scenario_tags) == dict(demo.scenario_tags)
        for symbol, series in demo.dataset.bars.items():
            assert rebuild.dataset.bars[symbol] == tuple(series)

    def test_features_identical_across_independent_builds(
        self, config, demo
    ) -> None:
        from trading_lab.business.features import FeatureEngine
        from trading_lab.business.series import SeriesStore

        engine = FeatureEngine(config.features)
        asof = _asof(demo.session_dates[200])
        v1 = engine.compute("SPY", asof, SeriesStore.from_dataset(demo.dataset))
        rebuild = build_demo_dataset(config)
        v2 = engine.compute("SPY", asof, SeriesStore.from_dataset(rebuild.dataset))
        assert v1 == v2
        assert v1.feature_hash == v2.feature_hash
        assert v1.feature_hash != ""


class TestCalendarAndSegments:
    def test_session_calendar_shape(self, demo) -> None:
        dates = demo.session_dates
        assert len(dates) == 420
        assert dates[0] == dt.date(2024, 1, 2)
        assert all(d.weekday() < 5 for d in dates)          # Mon-Fri only
        assert all(a < b for a, b in zip(dates, dates[1:]))  # strictly increasing

    def test_bars_follow_next_open_availability(self, demo) -> None:
        dates = demo.session_dates
        for symbol, series in demo.dataset.bars.items():
            assert {b.ts_event_utc.date() for b in series} <= set(dates)
            for bar in series:
                assert bar.ts_event_utc == _asof(bar.ts_event_utc.date())
                assert bar.source == "SYNTHETIC"
                assert bar.interval == "1d"
            for i, bar in enumerate(series):
                event_date = bar.ts_event_utc.date()
                idx = dates.index(event_date)
                if idx + 1 < len(dates):
                    assert bar.ts_available_utc == dt.datetime.combine(
                        dates[idx + 1], dt.time(13, 30), tzinfo=UTC)
            last = series[-1]
            assert last.ts_available_utc.date() > dates[-1]          # next b.d.
            assert last.ts_available_utc.date().weekday() < 5

    def test_segment_tags_cover_all_sessions(self, demo, config) -> None:
        lengths = config.fixture.sessions_per_segment
        assert sum(lengths) == len(demo.session_dates)
        for i, tag in enumerate(SEGMENT_TAGS):
            block = demo.session_dates[sum(lengths[:i]):sum(lengths[:i + 1])]
            assert block, f"segment {tag} is empty"
            assert all(
                demo.scenario_tags[d.isoformat()] == tag for d in block
            ), f"segment {tag} mislabeled"
        # DATA_QUALITY is the fixed 7th segment (index 6)
        assert SEGMENT_TAGS[6] == "DATA_QUALITY"

    def test_dataset_name_is_pinned(self, demo) -> None:
        assert demo.dataset.name == DATASET_NAME


class TestDataQualityDefects:
    def test_spy_drop_dates(self, demo) -> None:
        assert len(demo.spy_drop_dates) == 6
        spy = _bars_by_date(demo.dataset.bars["SPY"])
        assert all(d not in spy for d in demo.spy_drop_dates)
        assert all(d in demo.session_dates for d in demo.spy_drop_dates)

    def test_qqq_gap_contiguous_window(self, demo) -> None:
        gap = demo.qqq_gap_dates
        assert len(gap) == 10
        dates = demo.session_dates
        idx = [dates.index(d) for d in gap]
        assert idx == list(range(idx[0], idx[0] + 10))          # contiguous
        qqq = _bars_by_date(demo.dataset.bars["QQQ"])
        assert all(d not in qqq for d in gap)

    def test_spy_stale_run(self, demo) -> None:
        stale = demo.spy_stale_dates
        assert len(stale) == 4
        spy = _bars_by_date(demo.dataset.bars["SPY"])
        run = [spy[d] for d in stale]
        assert all(bar.quality == QUALITY_SYNTHETIC_STALE for bar in run)
        # >= 3 consecutive bars with close exactly equal to previous close:
        # the pre-run bar and the whole run share one close
        dates = demo.session_dates
        first_idx = dates.index(stale[0])
        predecessor = None
        for back in range(first_idx - 1, -1, -1):
            if dates[back] in spy:
                predecessor = spy[dates[back]]
                break
        assert predecessor is not None
        closes = [predecessor.close] + [bar.close for bar in run]
        assert len(set(closes)) == 1
        assert all(bar.close == bar.open for bar in run)         # frozen day


class TestBarSanity:
    def test_positive_prices_and_low_le_high(self, demo) -> None:
        for series in demo.dataset.bars.values():
            for bar in series:
                assert bar.low <= bar.high
                for price in (bar.open, bar.high, bar.low, bar.close):
                    assert price > 0

    def test_gapless_opens_between_adjacent_sessions(self, demo) -> None:
        dates = demo.session_dates
        for series in demo.dataset.bars.values():
            for prev, cur in zip(series, series[1:]):
                adjacent = (
                    dates.index(cur.ts_event_utc.date())
                    - dates.index(prev.ts_event_utc.date()) == 1
                )
                if adjacent:
                    assert cur.open == prev.close

    def test_volume_positive_and_highvol_boosted(self, demo, config) -> None:
        lengths = config.fixture.sessions_per_segment
        hi_vol = demo.session_dates[sum(lengths[:4]):sum(lengths[:5])]
        hi = {d for d in hi_vol}
        for symbol, series in demo.dataset.bars.items():
            for bar in series:
                assert bar.volume > 0
                if bar.ts_event_utc.date() in hi:
                    # 1.8x base, noise clamped to +-40%: floor 1.08M
                    assert bar.volume >= Decimal("1000000")
                else:
                    assert bar.volume <= Decimal("1500000")


class TestSampleGate:
    def test_fixture_satisfies_protocol_sample_gate(self, demo) -> None:
        protocol = EvaluationProtocol.load(PROTOCOL_PATH)
        sessions = len({
            b.ts_event_utc
            for series in demo.dataset.bars.values() for b in series
        })
        gate = protocol.sample_gate(sessions)
        # the discovered pre-registered constant: validation.min_bars = 100
        assert gate.min_bars == 100
        assert sessions >= gate.min_bars
        assert gate.satisfied is True
        assert gate.verdict == "SATISFIED"


class TestQQQGapControl:
    def test_control_restores_only_qqq_window(self, config, demo) -> None:
        control = build_demo_dataset(config, qqq_gap=False)
        assert demo.dataset.dataset_hash != control.dataset.dataset_hash
        # SPY untouched: identical bars and anomaly reporting
        assert control.dataset.bars["SPY"] == demo.dataset.bars["SPY"]
        assert control.spy_drop_dates == demo.spy_drop_dates
        assert control.spy_stale_dates == demo.spy_stale_dates
        # QQQ: control emits the full calendar; the gap build shares the
        # same underlying path — identical closes + volumes on shared dates
        # (opens differ by design: gapless opens anchor to the last
        # EMITTED close, which the missing window changes)
        assert len(control.dataset.bars["QQQ"]) == len(demo.session_dates)
        gap_bars = _bars_by_date(demo.dataset.bars["QQQ"])
        for bar in control.dataset.bars["QQQ"]:
            d = bar.ts_event_utc.date()
            if d in gap_bars:
                assert gap_bars[d].close == bar.close
                assert gap_bars[d].volume == bar.volume
                assert gap_bars[d].ts_event_utc == bar.ts_event_utc


class TestNextOpenPrice:
    def test_returns_next_emitted_bar_open(self, demo) -> None:
        series = demo.dataset.bars["SPY"]
        probe = demo.session_dates[100]
        expected = next(
            b.open for b in series
            if b.ts_event_utc.date() > probe
        )
        assert demo.next_open_price("SPY", probe) == expected

    def test_skips_dropped_session(self, demo) -> None:
        dropped = demo.spy_drop_dates[0]
        series = demo.dataset.bars["SPY"]
        expected = next(
            b.open for b in series
            if b.ts_event_utc.date() > dropped
        )
        assert demo.next_open_price("SPY", dropped) == expected

    def test_none_after_last_session(self, demo) -> None:
        assert demo.next_open_price("SPY", demo.session_dates[-1]) is None
        assert demo.next_open_price("SPY", dt.date(2030, 1, 1)) is None

    def test_qqq_next_open_crosses_gap(self, demo) -> None:
        before_gap = demo.qqq_gap_dates[0]
        series = demo.dataset.bars["QQQ"]
        expected = next(
            b.open for b in series
            if b.ts_event_utc.date() > before_gap
        )
        assert demo.next_open_price("QQQ", before_gap) == expected
