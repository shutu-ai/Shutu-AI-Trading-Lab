"""B1 feature-engine tests: PIT no-lookahead proof, warmup/stale/NO_DATA
statuses, per-symbol independence vs the QQQ-gap control, quantization,
correlation, and hash stability."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from trading_lab.business.config import BusinessConfig, FixtureConfig
from trading_lab.business.features import (
    REASON_INSUFFICIENT_CORR_SAMPLE,
    REASON_NO_DATA,
    REASON_STALE_DATA,
    REASON_WARMUP_PENDING,
    FeatureEngine,
)
from trading_lab.business.fixtures import DemoDataset, build_demo_dataset
from trading_lab.business.series import SeriesStore, SeriesStoreError
from trading_lab.business.types import STATUS_OK, STATUS_UNKNOWN

UTC = dt.timezone.utc
_Q8 = Decimal("0.00000001")


def _asof(session_date: dt.date) -> dt.datetime:
    return dt.datetime.combine(session_date, dt.time(21, 0), tzinfo=UTC)


_FEATURE_DECIMALS = (
    "returns_1d", "ma_short", "ma_long", "rsi", "atr",
    "realized_vol", "volume_ratio", "corr_other",
)


@pytest.fixture(scope="module")
def config() -> BusinessConfig:
    return BusinessConfig()


@pytest.fixture(scope="module")
def demo(config) -> DemoDataset:
    return build_demo_dataset(config)


@pytest.fixture(scope="module")
def store(demo) -> SeriesStore:
    return SeriesStore.from_dataset(demo.dataset)


@pytest.fixture(scope="module")
def engine(config) -> FeatureEngine:
    return FeatureEngine(config.features)


class TestDeterminism:
    def test_same_seed_same_hash_same_features(
        self, config, demo, store, engine
    ) -> None:
        asof = _asof(demo.session_dates[200])
        v1 = engine.compute("SPY", asof, store, store)
        rebuild = build_demo_dataset(config)
        v2 = engine.compute(
            "SPY", asof, SeriesStore.from_dataset(rebuild.dataset),
            SeriesStore.from_dataset(rebuild.dataset))
        assert v1 == v2
        assert v1.feature_hash == v2.feature_hash != ""

    def test_hash_binds_asof_and_symbol(self, demo, store, engine) -> None:
        t1 = _asof(demo.session_dates[200])
        t2 = _asof(demo.session_dates[201])
        v1 = engine.compute("SPY", t1, store)
        v1b = engine.compute("SPY", t1, store)
        v2 = engine.compute("SPY", t2, store)
        vq = engine.compute("QQQ", t1, store)
        assert v1.feature_hash == v1b.feature_hash
        assert v1.feature_hash != v2.feature_hash
        assert v1.feature_hash != vq.feature_hash


class TestNoLookahead:
    def test_future_bars_do_not_change_past_features(
        self, config, demo, store, engine
    ) -> None:
        t = _asof(demo.session_dates[200])
        baseline = engine.compute("SPY", t, store)
        baseline_q = engine.compute("QQQ", t, store)
        # rebuild with 30 EXTRA sessions appended to the final segment:
        # identical history, a longer future
        extended = BusinessConfig(fixture=FixtureConfig(
            sessions_per_segment=(40, 80, 60, 60, 60, 60, 30, 60)))
        demo2 = build_demo_dataset(extended)
        store2 = SeriesStore.from_dataset(demo2.dataset)
        assert len(demo2.session_dates) == len(demo.session_dates) + 30
        after = engine.compute("SPY", t, store2)
        after_q = engine.compute("QQQ", t, store2)
        assert baseline == after
        assert baseline.feature_hash == after.feature_hash
        assert baseline_q == after_q
        # the readable information set at t is byte-identical
        assert store.available("SPY", t) == store2.available("SPY", t)

    def test_availability_not_event_gates_features(
        self, demo, store, engine
    ) -> None:
        dates = demo.session_dates
        probe = _asof(dates[100])
        v = engine.compute("SPY", probe, store)
        # last usable bar is the PREVIOUS session's bar: the probe
        # session's own bar only becomes available next session 13:30
        assert v.asof_bar_ts == dt.datetime.combine(
            dates[99], dt.time(21, 0), tzinfo=UTC)
        assert v.asof_bar_age_sessions == 1


class TestStatuses:
    def test_warmup_pending(self, demo, store, engine) -> None:
        v = engine.compute("SPY", _asof(demo.session_dates[5]), store)
        assert v.status == STATUS_UNKNOWN
        assert REASON_WARMUP_PENDING in v.reasons
        assert v.warmup_ok is False
        assert v.ma_long is None                      # 5 closes < 30
        assert v.returns_1d is not None               # still decidable
        assert v.feature_hash != ""

    def test_stale_data_on_qqq_gap(self, demo, store, engine) -> None:
        asof = _asof(demo.qqq_gap_dates[-1])
        v = engine.compute("QQQ", asof, store)
        assert v.status == STATUS_UNKNOWN
        assert REASON_STALE_DATA in v.reasons
        assert v.warmup_ok is True                    # long history exists
        assert v.asof_bar_age_sessions == len(demo.qqq_gap_dates)
        assert v.returns_1d is not None               # values may be populated

    def test_no_data(self, demo) -> None:
        spy_only = SeriesStore.from_bars(demo.dataset.bars["SPY"])
        v = FeatureEngine(BusinessConfig().features).compute(
            "QQQ", _asof(demo.session_dates[200]), spy_only)
        assert v.status == STATUS_UNKNOWN
        assert REASON_NO_DATA in v.reasons
        assert v.warmup_ok is False
        assert v.asof_bar_ts is None
        assert all(getattr(v, f) is None for f in _FEATURE_DECIMALS)

    def test_ok_vector_shape(self, demo, store, engine) -> None:
        v = engine.compute("SPY", _asof(demo.session_dates[200]), store)
        assert v.status == STATUS_OK
        assert v.reasons == ()
        assert v.warmup_ok is True
        assert v.asof_bar_age_sessions == 1
        for field in _FEATURE_DECIMALS[:-1]:          # corr needs other_store
            assert getattr(v, field) is not None
        assert Decimal("0") <= v.rsi <= Decimal("100")
        assert v.ma_short > 0
        assert abs(v.returns_1d) < Decimal("0.20")    # no wild fixture jumps

    def test_fail_closed_inputs(self, store, engine) -> None:
        with pytest.raises(SeriesStoreError):
            engine.compute(
                "SPY", dt.datetime(2024, 3, 1, 21, 0), store)  # naive asof

    def test_unknown_symbol_is_no_data(self, store, engine) -> None:
        v = engine.compute("MSFT", _asof(dt.date(2024, 3, 1)), store)
        assert v.status == STATUS_UNKNOWN
        assert REASON_NO_DATA in v.reasons
        assert v.warmup_ok is False
        assert v.feature_hash != ""


class TestPerSymbolIndependence:
    def test_spy_unchanged_by_qqq_gap(self, config, demo, engine) -> None:
        store_gap = SeriesStore.from_dataset(demo.dataset)
        control = build_demo_dataset(config, qqq_gap=False)
        store_ctrl = SeriesStore.from_dataset(control.dataset)
        asof = _asof(demo.qqq_gap_dates[5])
        v_gap = engine.compute("SPY", asof, store_gap)
        v_ctrl = engine.compute("SPY", asof, store_ctrl)
        assert v_gap == v_ctrl                        # incl. feature_hash
        assert v_gap.status == STATUS_OK

    def test_control_dataset_detects_no_staleness_in_window(
        self, config, demo, engine
    ) -> None:
        control = build_demo_dataset(config, qqq_gap=False)
        store_ctrl = SeriesStore.from_dataset(control.dataset)
        asof = _asof(demo.qqq_gap_dates[-1])
        v = engine.compute("QQQ", asof, store_ctrl)
        assert v.status == STATUS_OK
        assert v.asof_bar_age_sessions == 1


class TestCorrelation:
    def test_corr_over_common_sessions(self, demo, store, engine) -> None:
        v = engine.compute(
            "SPY", _asof(demo.session_dates[150]), store, store)
        assert v.corr_other is not None
        assert Decimal("-1") <= v.corr_other <= Decimal("1")
        assert v.status == STATUS_OK

    def test_insufficient_common_sample_keeps_status_ok(
        self, demo, engine
    ) -> None:
        cfg = BusinessConfig()
        store_spy = SeriesStore.from_bars(demo.dataset.bars["SPY"][:35])
        store_qqq = SeriesStore.from_bars(demo.dataset.bars["QQQ"][:10])
        asof = demo.dataset.bars["SPY"][34].ts_available_utc
        v = engine.compute("SPY", asof, store_spy, store_qqq)
        assert v.warmup_ok is True                    # 35 closes >= ma_long 30
        assert v.corr_other is None
        assert REASON_INSUFFICIENT_CORR_SAMPLE in v.reasons
        assert v.status == STATUS_OK                  # corr is informational

    def test_no_other_store_no_reason(self, demo, store, engine) -> None:
        v = engine.compute(
            "SPY", _asof(demo.session_dates[200]), store, None)
        assert v.corr_other is None
        assert v.reasons == ()
        assert v.status == STATUS_OK


class TestQuantizationAndHash:
    def test_all_decimals_quantized_to_1e8(
        self, demo, store, engine
    ) -> None:
        for date_idx in (30, 120, 250, 380):
            v = engine.compute(
                "SPY", _asof(demo.session_dates[date_idx]), store, store)
            for field in _FEATURE_DECIMALS:
                value = getattr(v, field)
                if value is not None:
                    assert value == value.quantize(_Q8), field
            assert v.feature_hash != ""

    def test_hash_is_canonical_over_quantized_fields(
        self, demo, store, engine
    ) -> None:
        from trading_lab.security.canonical import canonical_digest

        v = engine.compute(
            "SPY", _asof(demo.session_dates[200]), store, store)
        expected = canonical_digest({
            "symbol": v.symbol,
            "asof_utc": v.asof_utc,
            "status": v.status,
            "features": {
                "atr": str(v.atr),
                "corr_other": str(v.corr_other),
                "ma_long": str(v.ma_long),
                "ma_short": str(v.ma_short),
                "realized_vol": str(v.realized_vol),
                "returns_1d": str(v.returns_1d),
                "rsi": str(v.rsi),
                "volume_ratio": str(v.volume_ratio),
            },
        })
        assert v.feature_hash == expected
