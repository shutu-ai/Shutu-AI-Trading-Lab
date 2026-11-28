"""B1 series-store tests: admission validation (fail-closed), PIT
availability accessors, staleness counting, admission summary digest, and
the JSONL loader (round-trip + rejections)."""

from __future__ import annotations

import datetime as dt
import json
from decimal import Decimal
from pathlib import Path

import pytest

from trading_lab.business.config import BusinessConfig
from trading_lab.business.fixtures import DemoDataset, build_demo_dataset
from trading_lab.business.series import (
    PIT_LEVEL,
    PURPOSE_LABEL,
    QUALITY_SYNTHETIC_OK,
    SeriesStore,
    SeriesStoreError,
    load_bars_jsonl,
)
from trading_lab.contracts import AdjustmentKind, MarketBar
from trading_lab.security.canonical import canonical_digest

UTC = dt.timezone.utc


def _asof(session_date: dt.date) -> dt.datetime:
    return dt.datetime.combine(session_date, dt.time(21, 0), tzinfo=UTC)


def _bar(
    symbol: str,
    event: dt.datetime,
    available: dt.datetime,
    *,
    close: str = "100.00",
    quality: str = QUALITY_SYNTHETIC_OK,
) -> MarketBar:
    return MarketBar(
        asset_id=symbol,
        ts_event_utc=event,
        ts_available_utc=available,
        interval="1d",
        open=Decimal("100.00"),
        high=Decimal("101.00"),
        low=Decimal("99.00"),
        close=Decimal(close),
        volume=Decimal("1000000"),
        source="SYNTHETIC",
        adjustment=AdjustmentKind.RAW,
        quality=quality,
    )


@pytest.fixture(scope="module")
def demo() -> DemoDataset:
    return build_demo_dataset(BusinessConfig())


@pytest.fixture(scope="module")
def store(demo) -> SeriesStore:
    return SeriesStore.from_dataset(demo.dataset)


class TestAdmissionValidation:
    def test_rejects_duplicate_ts_event(self) -> None:
        t1 = dt.datetime(2024, 1, 2, 21, 0, tzinfo=UTC)
        t2 = dt.datetime(2024, 1, 3, 21, 0, tzinfo=UTC)
        a1 = dt.datetime(2024, 1, 3, 13, 30, tzinfo=UTC)
        a2 = dt.datetime(2024, 1, 4, 13, 30, tzinfo=UTC)
        with pytest.raises(SeriesStoreError, match="strictly increasing"):
            SeriesStore({"SPY": [
                _bar("SPY", t1, a1),
                _bar("SPY", t1, a2),          # duplicate event
            ]})

    def test_rejects_non_monotonic_series(self) -> None:
        t1 = dt.datetime(2024, 1, 2, 21, 0, tzinfo=UTC)
        t2 = dt.datetime(2024, 1, 3, 21, 0, tzinfo=UTC)
        a1 = dt.datetime(2024, 1, 3, 13, 30, tzinfo=UTC)
        a2 = dt.datetime(2024, 1, 4, 13, 30, tzinfo=UTC)
        with pytest.raises(SeriesStoreError, match="strictly increasing"):
            SeriesStore({"SPY": [
                _bar("SPY", t2, a2),
                _bar("SPY", t1, a1),          # goes backwards
            ]})

    def test_rejects_unknown_quality(self) -> None:
        t1 = dt.datetime(2024, 1, 2, 21, 0, tzinfo=UTC)
        a1 = dt.datetime(2024, 1, 3, 13, 30, tzinfo=UTC)
        with pytest.raises(SeriesStoreError, match="vocabulary"):
            SeriesStore({"SPY": [_bar("SPY", t1, a1, quality="VENDOR_OK")]})

    def test_rejects_asset_id_mismatch_and_empty(self) -> None:
        t1 = dt.datetime(2024, 1, 2, 21, 0, tzinfo=UTC)
        a1 = dt.datetime(2024, 1, 3, 13, 30, tzinfo=UTC)
        with pytest.raises(SeriesStoreError, match="mismatch"):
            SeriesStore({"QQQ": [_bar("SPY", t1, a1)]})
        with pytest.raises(SeriesStoreError):
            SeriesStore({"QQQ": []})

    def test_accepts_stale_label_and_naive_asof_rejected(self) -> None:
        t1 = dt.datetime(2024, 1, 2, 21, 0, tzinfo=UTC)
        a1 = dt.datetime(2024, 1, 3, 13, 30, tzinfo=UTC)
        store = SeriesStore({
            "SPY": [_bar("SPY", t1, a1, close="100.00", quality="SYNTHETIC_STALE")],
        })
        assert store.available("SPY", dt.datetime(2024, 1, 3, 13, 30, tzinfo=UTC))
        with pytest.raises(SeriesStoreError, match="timezone-aware"):
            store.available("SPY", dt.datetime(2024, 1, 3, 13, 30))


class TestPITAccess:
    def test_available_respects_information_availability(
        self, demo, store
    ) -> None:
        dates = demo.session_dates
        probe = _asof(dates[100])                       # session close clock
        spy = store.available("SPY", probe)
        assert spy[-1].ts_event_utc.date() == dates[99]
        assert all(b.ts_available_utc <= probe for b in spy)
        assert dates[100] not in {b.ts_event_utc.date() for b in spy}
        # the same session's bar enters only at its NEXT 13:30 availability
        boundary = dt.datetime.combine(
            dates[101], dt.time(13, 30), tzinfo=UTC)
        assert store.available("SPY", boundary)[-1].ts_event_utc.date() == dates[100]

    def test_last_available_none_before_first_bar(self, store) -> None:
        assert store.last_available(
            "SPY", dt.datetime(2023, 1, 1, tzinfo=UTC)) is None
        assert store.available("SPY", dt.datetime(2023, 1, 1, tzinfo=UTC)) == []

    def test_sessions_since_counts_decision_session(self, store) -> None:
        # mini store Mon-Thu; at any session close clock the freshest
        # available bar is the PREVIOUS session's bar (next-open
        # availability), so staleness reads one elapsed session
        def day(n: int) -> dt.datetime:
            return dt.datetime(2024, 1, 8 + n, 21, 0, tzinfo=UTC)

        def avail_of(n: int) -> dt.datetime:
            return dt.datetime(2024, 1, 9 + n, 13, 30, tzinfo=UTC)

        store2 = SeriesStore({"SPY": [
            _bar("SPY", day(n), avail_of(n), close=f"10{n}.00")
            for n in range(4)               # Mon..Thu event, Tue..Fri avail
        ]})
        for clock_day in (1, 2, 3, 4):      # Tue..Fri decision clocks
            assert store2.sessions_since("SPY", day(clock_day)) == 1
        assert store2.sessions_since("NOPE", day(1)) is None

    def test_qqq_gap_shows_as_staleness(self, demo, store) -> None:
        asof = _asof(demo.qqq_gap_dates[-1])
        assert store.sessions_since("QQQ", asof) == len(demo.qqq_gap_dates)
        assert store.sessions_since("SPY", asof) == 1

    def test_unknown_symbol_reads_as_no_data(self, store) -> None:
        # an unadmitted symbol is the honest no-data state, not an error
        assert store.available("MSFT", _asof(dt.date(2024, 2, 1))) == []
        assert store.last_available("MSFT", _asof(dt.date(2024, 2, 1))) is None
        assert store.sessions_since("MSFT", _asof(dt.date(2024, 2, 1))) is None


class TestAdmissionSummary:
    def test_labels_and_counts(self, demo, store) -> None:
        summary = store.admission_summary()
        assert summary["purpose"] == PURPOSE_LABEL == "BUSINESS_MVP_DEMO"
        assert summary["pit_level"] == PIT_LEVEL == "SYNTHETIC"
        assert summary["bars_per_symbol"] == {
            "QQQ": len(demo.dataset.bars["QQQ"]),
            "SPY": len(demo.dataset.bars["SPY"]),
        }
        assert summary["calendar_sessions"] == len(demo.session_dates)
        span = summary["session_span"]
        assert span["first"] == demo.session_dates[0].isoformat()
        assert span["last"] == demo.session_dates[-1].isoformat()
        assert summary["quality_counts"] == {
            "SYNTHETIC_OK": 820, "SYNTHETIC_STALE": 4}

    def test_digest_is_recomputed_from_content(self, demo, store) -> None:
        summary = store.admission_summary()
        # independent recomputation over the admitted bar fields
        fields = ("asset_id", "ts_event_utc", "ts_available_utc", "interval",
                  "open", "high", "low", "close", "volume", "source",
                  "adjustment", "quality")
        rows = sorted(
            ({k: getattr(b, k) for k in fields}
             for series in demo.dataset.bars.values() for b in series),
            key=lambda r: (r["asset_id"], r["ts_event_utc"]),
        )
        assert summary["content_digest"] == canonical_digest(rows)
        # same content twice -> same digest; one bar less -> different
        again = SeriesStore.from_dataset(demo.dataset).admission_summary()
        assert again["content_digest"] == summary["content_digest"]
        trimmed = SeriesStore.from_bars(
            demo.dataset.bars["SPY"][:-1]).admission_summary()
        assert trimmed["content_digest"] != summary["content_digest"]


class TestJsonlLoader:
    def _write_demo_spy(self, tmp_path: Path):
        demo = build_demo_dataset(BusinessConfig())
        bars = demo.dataset.bars["SPY"]
        path = tmp_path / "spy.jsonl"
        path.write_text(
            "\n".join(b.model_dump_json() for b in bars) + "\n",
            encoding="utf-8")
        return path, bars

    def test_roundtrip(self, tmp_path) -> None:
        path, bars = self._write_demo_spy(tmp_path)
        loaded = load_bars_jsonl(path)
        assert loaded == tuple(bars)

    def test_rejects_missing_field(self, tmp_path) -> None:
        path, bars = self._write_demo_spy(tmp_path)
        payload = json.loads(bars[0].model_dump_json())
        del payload["close"]
        lines = path.read_text(encoding="utf-8").splitlines()
        lines.insert(2, json.dumps(payload))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        with pytest.raises(SeriesStoreError, match="line 3"):
            load_bars_jsonl(path)

    def test_rejects_unknown_key(self, tmp_path) -> None:
        path, bars = self._write_demo_spy(tmp_path)
        payload = json.loads(bars[0].model_dump_json())
        payload["smuggled"] = "value"
        path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
        with pytest.raises(SeriesStoreError):
            load_bars_jsonl(path)

    def test_rejects_float_price(self, tmp_path) -> None:
        path, bars = self._write_demo_spy(tmp_path)
        payload = json.loads(bars[0].model_dump_json())
        payload["close"] = 100.5                        # JSON number, not str
        path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
        with pytest.raises(SeriesStoreError):
            load_bars_jsonl(path)

    def test_rejects_malformed_line(self, tmp_path) -> None:
        path, _ = self._write_demo_spy(tmp_path)
        path.write_text(
            path.read_text(encoding="utf-8") + "not-json-at-all\n",
            encoding="utf-8")
        with pytest.raises(SeriesStoreError, match="invalid MarketBar"):
            load_bars_jsonl(path)

    def test_rejects_missing_file(self, tmp_path) -> None:
        with pytest.raises(SeriesStoreError, match="cannot read"):
            load_bars_jsonl(tmp_path / "absent.jsonl")

    def test_empty_and_blank_lines_ok(self, tmp_path) -> None:
        path, bars = self._write_demo_spy(tmp_path)
        path.write_text("\n\n" + bars[0].model_dump_json() + "\n\n",
                        encoding="utf-8")
        assert load_bars_jsonl(path) == (bars[0],)
