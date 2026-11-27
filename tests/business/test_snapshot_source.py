"""B1 snapshot-source tests: the V0.2 historical collection reader.

Hand-built fixture directories (tmp_path, no network, fully
deterministic) in the EXACT manifest shape
``apps/market_gateway/collection_session.py`` writes: every documented
per-symbol refusal, the admission/license/PIT gates, source/transport
mislabels, and the manifest hard errors.

Fixture notes: the "admitted-path" fixtures carry bars with the store
plane's demo quality vocabulary so ``SeriesStore`` admission is exercised
end-to-end; the collector-shaped probe fixture carries the producer's
real labels (source FAKE_TRANSPORT, quality PIT_ASSUMED_NEXT_OPEN,
LICENSE_UNVERIFIED / ASSUMED / NOT_RESEARCH_ADMITTED) and asserts the
honest exploratory outcome. A quality label outside the store plane's
vocabulary is refused per symbol (STORE_ADMISSION_REFUSED) — the reader
never duplicates nor bypasses the store's own vocabulary gate.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path

import pytest

from trading_lab.business.snapshot_source import (
    ADMISSION_RESTRICTED,
    COLLECTED_STATUS,
    MANIFEST_SCHEMA,
    NAMESPACE_MARKER,
    PIT_ASSUMED_NOT_VERIFIED,
    SCENARIO_TAG_ADMITTED,
    SCENARIO_TAG_EXPLORATORY,
    SOURCE_PROBE,
    SnapshotSourceError,
    load_historical_snapshot,
)
from trading_lab.business.series import QUALITY_SYNTHETIC_OK, SeriesStore
from trading_lab.contracts import AdjustmentKind, MarketBar
from trading_lab.security.canonical import canonical_digest, canonical_json_bytes

UTC = dt.timezone.utc
SESSIONS = [dt.date(2024, 1, d) for d in (2, 3, 4, 5, 8)]  # Mon..Fri week
COLLECTOR_QUALITY = "PIT_ASSUMED_NEXT_OPEN"   # collection_session.QUALITY_LABEL


# ---------------------------------------------------------------------------
# fixture builders (real manifest shape)
# ---------------------------------------------------------------------------


def _bar(
    symbol: str,
    session_date: dt.date,
    *,
    source: str = SOURCE_PROBE,
    quality: str = QUALITY_SYNTHETIC_OK,
    close: str = "100.00",
) -> MarketBar:
    price = Decimal(close)
    return MarketBar(
        asset_id=symbol,
        ts_event_utc=dt.datetime.combine(
            session_date, dt.time(21, 0), tzinfo=UTC),
        ts_available_utc=dt.datetime.combine(
            session_date + dt.timedelta(days=1), dt.time(13, 30), tzinfo=UTC),
        interval="1Day",
        open=price,
        high=price + Decimal("1.00"),
        low=price - Decimal("1.00"),
        close=price,
        volume=Decimal("1000000"),
        source=source,
        adjustment=AdjustmentKind.RAW,
        quality=quality,
    )


def _write_symbol_bars(root: Path, symbol: str, bars: list[MarketBar]) -> None:
    directory = root / symbol
    directory.mkdir(parents=True, exist_ok=True)
    payload = "\n".join(b.model_dump_json() for b in bars) + "\n"
    (directory / "bars.jsonl").write_text(payload, encoding="utf-8")


def _bars_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_snapshot(
    tmp_path: Path,
    specs: dict[str, list[MarketBar]],
    mutate: Callable[[dict], None] | None = None,
) -> Path:
    """Build a collection directory whose manifest matches the files on
    disk (hashes + counts), then optionally mutate the manifest to plant
    a defect. Returns the namespace root (manifest's parent)."""
    root = tmp_path / "snapshot"
    root.mkdir()
    for symbol, bars in specs.items():
        _write_symbol_bars(root, symbol, bars)
    all_dates = [b.ts_event_utc.date() for bars in specs.values() for b in bars]
    manifest: dict[str, object] = {
        "schema": MANIFEST_SCHEMA,
        "status": COLLECTED_STATUS,
        "namespace": NAMESPACE_MARKER,
        "window": {
            "start": min(all_dates).isoformat(),
            "end": max(all_dates).isoformat(),
            "label": "test-window",
            "semantics": "ET session dates (HistoricalWindow)",
        },
        "transport": {
            "mode": "probe",
            "label": "FAKE_TRANSPORT",
            "real_network_used": False,
        },
        "calendar_supply": {
            "version": "NYSE-2017-2025-TEST-v1",
            "hash": "a" * 64,
            "hash_frozen": "b" * 64,
        },
        "budget": {"cap": 30, "spent": 4, "remaining": 26},
        "symbols": {
            symbol: {
                "row_count": len(bars),
                "bars_sha256": _bars_digest(root / symbol / "bars.jsonl"),
                "bars_file": f"historical_research/{symbol}/bars.jsonl",
            }
            for symbol, bars in specs.items()
        },
        "license": {"status": "LICENSE_VERIFIED"},
        "pit": {"level": "VERIFIED", "rule": "daily_close_available_next_open"},
        "admission": {"status": "RESEARCH_ADMITTED"},
    }
    if mutate is not None:
        mutate(manifest)
    (root / "collection_manifest.json").write_bytes(
        canonical_json_bytes(manifest))
    return root


def _default_specs() -> dict[str, list[MarketBar]]:
    return {
        "SPY": [_bar("SPY", d, close=f"10{i}.00")
                for i, d in enumerate(SESSIONS)],
        "QQQ": [_bar("QQQ", d, close=f"20{i}.00")
                for i, d in enumerate(SESSIONS)],
    }


def _reasons(bundle) -> set[str]:
    return {r.reason for r in bundle.refusals}


# ---------------------------------------------------------------------------
# the good path (admitted state)
# ---------------------------------------------------------------------------


class TestGoodBundle:
    def test_good_bundle_loads(self, tmp_path: Path) -> None:
        root = _write_snapshot(tmp_path, _default_specs())
        bundle = load_historical_snapshot(root)
        assert set(bundle.stores) == {"SPY", "QQQ"}
        assert set(bundle.bars) == {"SPY", "QQQ"}
        assert bundle.blockers == ()
        assert bundle.refusals == ()
        assert bundle.research_admitted is True
        assert bundle.session_dates == tuple(sorted(set(SESSIONS)))
        assert set(bundle.scenario_tags) == {"SPY", "QQQ"}
        assert set(bundle.scenario_tags.values()) == {SCENARIO_TAG_ADMITTED}
        summary = bundle.manifest_summary
        assert summary["transport"]["mode"] == "probe"
        assert summary["transport"]["expected_source"] == SOURCE_PROBE
        assert summary["symbols_loaded"] == ["QQQ", "SPY"]
        assert summary["symbols_declared"] == ["QQQ", "SPY"]
        calendar = summary["calendar_supply"]
        assert calendar["version"] == "NYSE-2017-2025-TEST-v1"

    def test_dataset_hash_recomputed_over_rows(self, tmp_path: Path) -> None:
        root = _write_snapshot(tmp_path, _default_specs())
        bundle = load_historical_snapshot(root)
        fields = ("asset_id", "ts_event_utc", "ts_available_utc", "interval",
                  "open", "high", "low", "close", "volume", "source",
                  "adjustment", "quality")
        rows = sorted(
            ({k: getattr(b, k) for k in fields}
             for bars in bundle.bars.values() for b in bars),
            key=lambda r: (r["asset_id"], r["ts_event_utc"]),
        )
        assert bundle.dataset_hash == canonical_digest({"rows": rows})
        assert bundle.manifest_summary["dataset_hash"] == bundle.dataset_hash

    def test_stores_are_independent_instances(self, tmp_path: Path) -> None:
        root = _write_snapshot(tmp_path, _default_specs())
        bundle = load_historical_snapshot(root)
        spy, qqq = bundle.stores["SPY"], bundle.stores["QQQ"]
        assert isinstance(spy, SeriesStore) and isinstance(qqq, SeriesStore)
        assert spy is not qqq
        probe = dt.datetime(2024, 1, 9, 21, 0, tzinfo=UTC)
        assert {b.asset_id for b in spy.available("SPY", probe)} == {"SPY"}
        assert spy.available("QQQ", probe) == []

    def test_next_open_price_semantics(self, tmp_path: Path) -> None:
        root = _write_snapshot(tmp_path, _default_specs())
        bundle = load_historical_snapshot(root)
        # strictly after: the 2024-01-03 bar opens at its close (101.00)
        assert bundle.next_open_price("SPY", dt.date(2024, 1, 2)) \
            == Decimal("101.00")
        assert bundle.next_open_price("SPY", dt.date(2024, 1, 1)) \
            == Decimal("100.00")
        # final session: no later bar
        assert bundle.next_open_price("SPY", dt.date(2024, 1, 8)) is None
        assert bundle.next_open_price("SPY", dt.date(2024, 1, 9)) is None
        # refused/unknown symbol reads as no price, never an exception
        assert bundle.next_open_price("MSFT", dt.date(2024, 1, 2)) is None

    def test_deterministic_reload(self, tmp_path: Path) -> None:
        root = _write_snapshot(tmp_path, _default_specs())
        first = load_historical_snapshot(root)
        second = load_historical_snapshot(root)
        assert first.dataset_hash == second.dataset_hash
        assert first.session_dates == second.session_dates
        assert first.manifest_summary == second.manifest_summary
        assert first.research_admitted == second.research_admitted


# ---------------------------------------------------------------------------
# collector-shaped probe snapshot (the honest restricted state)
# ---------------------------------------------------------------------------


class TestCollectorProbeShape:
    def _probe_specs(self) -> dict[str, list[MarketBar]]:
        return {
            symbol: [_bar(symbol, d, quality=COLLECTOR_QUALITY,
                          close=f"{30 + i}.00")
                     for i, d in enumerate(SESSIONS)]
            for symbol in ("SPY", "QQQ")
        }

    def _restricted_manifest(self, manifest: dict) -> None:
        manifest["license"] = {"status": "LICENSE_UNVERIFIED"}
        manifest["pit"] = {
            "level": "ASSUMED",
            "rule": "daily_close_available_next_open",
            "api_verified_claim": "NONE",
        }
        manifest["admission"] = {"status": ADMISSION_RESTRICTED}

    def test_restricted_probe_bundle_is_exploratory_only(
        self, tmp_path: Path,
    ) -> None:
        root = _write_snapshot(
            tmp_path, self._probe_specs(), self._restricted_manifest)
        bundle = load_historical_snapshot(root)
        assert bundle.research_admitted is False
        for expected in ("ADMISSION_NOT_RELEASED", "LICENSE_NOT_VERIFIED",
                         PIT_ASSUMED_NOT_VERIFIED):
            assert expected in bundle.blockers
        assert set(bundle.scenario_tags.values()) == {
            SCENARIO_TAG_EXPLORATORY}
        summary = bundle.manifest_summary
        assert summary["license_status"] == "LICENSE_UNVERIFIED"
        assert summary["pit_level"] == "ASSUMED"
        assert summary["admission_status"] == ADMISSION_RESTRICTED
        # the exploratory tag covers every manifest-declared symbol
        assert bundle.scenario_tags == {
            "SPY": SCENARIO_TAG_EXPLORATORY,
            "QQQ": SCENARIO_TAG_EXPLORATORY,
        }
        # only rows the bundle actually admitted can price a fill
        assert set(bundle.bars) <= {"SPY", "QQQ"}

    def test_probe_hash_integrity_enforced(self, tmp_path: Path) -> None:
        def plant(manifest: dict) -> None:
            manifest["symbols"]["SPY"]["bars_sha256"] = "0" * 64
            self._restricted_manifest(manifest)

        root = _write_snapshot(
            tmp_path, self._probe_specs(), plant)
        bundle = load_historical_snapshot(root)
        spy_refusal = next(
            r for r in bundle.refusals if r.symbol == "SPY")
        assert spy_refusal.reason == "HASH_MISMATCH"
        assert "HASH_MISMATCH:SPY" in bundle.blockers


# ---------------------------------------------------------------------------
# per-symbol refusals (other symbols keep loading)
# ---------------------------------------------------------------------------


class TestPerSymbolRefusals:
    def test_bad_content_hash_refuses_only_that_symbol(
        self, tmp_path: Path,
    ) -> None:
        def plant(manifest: dict) -> None:
            manifest["symbols"]["SPY"]["bars_sha256"] = "0" * 64

        root = _write_snapshot(tmp_path, _default_specs(), plant)
        bundle = load_historical_snapshot(root)
        assert "SPY" not in bundle.stores
        assert set(bundle.stores) == {"QQQ"}          # independent validity
        assert _reasons(bundle) == {"HASH_MISMATCH"}
        assert "HASH_MISMATCH:SPY" in bundle.blockers

    def test_row_count_mismatch_refuses(self, tmp_path: Path) -> None:
        def plant(manifest: dict) -> None:
            manifest["symbols"]["SPY"]["row_count"] = 4   # file has 5

        root = _write_snapshot(tmp_path, _default_specs(), plant)
        bundle = load_historical_snapshot(root)
        assert _reasons(bundle) == {"ROW_COUNT_MISMATCH"}
        assert "ROW_COUNT_MISMATCH:SPY" in bundle.blockers
        assert set(bundle.stores) == {"QQQ"}

    def test_row_outside_window_refuses(self, tmp_path: Path) -> None:
        def plant(manifest: dict) -> None:
            manifest["window"] = {
                "start": SESSIONS[0].isoformat(),
                "end": SESSIONS[2].isoformat(),       # bars 4..5 outside
            }

        root = _write_snapshot(tmp_path, _default_specs(), plant)
        bundle = load_historical_snapshot(root)
        assert _reasons(bundle) == {"OUTSIDE_WINDOW"}
        assert bundle.stores == {}

    def test_non_monotonic_series_refuses(self, tmp_path: Path) -> None:
        bars = list(reversed(_default_specs()["SPY"]))    # newest first
        specs = {"SPY": bars, "QQQ": _default_specs()["QQQ"]}
        root = _write_snapshot(tmp_path, specs)
        bundle = load_historical_snapshot(root)
        assert _reasons(bundle) == {"NON_MONOTONIC_TS_EVENT"}
        assert set(bundle.stores) == {"QQQ"}

    def test_ts_available_before_event_refused_at_parse(
        self, tmp_path: Path,
    ) -> None:
        # hand-write a contract-invalid row (the MarketBar validator must
        # refuse it; the loader records the refusal instead of crashing)
        row = json.loads(_bar("SPY", SESSIONS[0]).model_dump_json())
        row["ts_event_utc"], row["ts_available_utc"] = (
            row["ts_available_utc"], row["ts_event_utc"])
        directory = tmp_path / "snapshot" / "SPY"
        directory.mkdir(parents=True)
        bars_path = directory / "bars.jsonl"
        bars_path.write_text(json.dumps(row) + "\n", encoding="utf-8")
        manifest = {
            "schema": MANIFEST_SCHEMA,
            "status": COLLECTED_STATUS,
            "namespace": NAMESPACE_MARKER,
            "window": {"start": SESSIONS[0].isoformat(),
                       "end": SESSIONS[-1].isoformat()},
            "calendar_supply": {"version": "NYSE-TEST-v1"},
            "transport": {"mode": "probe", "label": "FAKE_TRANSPORT",
                          "real_network_used": False},
            "license": {"status": "LICENSE_VERIFIED"},
            "pit": {"level": "VERIFIED"},
            "admission": {"status": "RESEARCH_ADMITTED"},
            "symbols": {"SPY": {"row_count": 1,
                                "bars_sha256": _bars_digest(bars_path)}},
        }
        (tmp_path / "snapshot" / "collection_manifest.json").write_bytes(
            canonical_json_bytes(manifest))
        bundle = load_historical_snapshot(tmp_path / "snapshot")
        assert _reasons(bundle) == {"PARSE_INVALID"}
        assert bundle.stores == {}

    def test_empty_partition_refused(self, tmp_path: Path) -> None:
        root = _write_snapshot(
            tmp_path, {"SPY": [], "QQQ": _default_specs()["QQQ"]})
        bundle = load_historical_snapshot(root)
        assert _reasons(bundle) == {"EMPTY_PARTITION"}
        assert set(bundle.stores) == {"QQQ"}

    def test_missing_bars_file_refused(self, tmp_path: Path) -> None:
        def plant(manifest: dict) -> None:
            manifest["symbols"]["SPY"] = {
                "row_count": 5, "bars_sha256": "1" * 64}

        root = _write_snapshot(
            tmp_path, {"QQQ": _default_specs()["QQQ"]}, plant)
        bundle = load_historical_snapshot(root)
        assert _reasons(bundle) == {"MISSING_BARS_FILE"}
        assert set(bundle.stores) == {"QQQ"}

    def test_quality_outside_store_vocabulary_refused(
        self, tmp_path: Path,
    ) -> None:
        # a label the store plane does not know: recorded refusal, the
        # reader never bypasses SeriesStore's own admission gate
        specs = {"SPY": [_bar("SPY", d, quality="VENDOR_OK")
                         for d in SESSIONS]}
        root = _write_snapshot(tmp_path, specs)
        bundle = load_historical_snapshot(root)
        assert _reasons(bundle) == {"STORE_ADMISSION_REFUSED"}
        assert bundle.stores == {}
        assert "STORE_ADMISSION_REFUSED:SPY" in bundle.blockers
        # refused rows never enter the bundle's bars
        assert "SPY" not in bundle.bars
        assert bundle.refusals[0].symbol == "SPY"

    def test_unlisted_symbol_dir_never_loaded_only_recorded(
        self, tmp_path: Path,
    ) -> None:
        root = _write_snapshot(tmp_path, _default_specs())
        (root / "MSFT").mkdir()                      # on disk, not in manifest
        bundle = load_historical_snapshot(root)
        assert "MSFT" not in bundle.stores
        assert "UNLISTED_SYMBOL_DIR:MSFT" in bundle.blockers
        assert set(bundle.stores) == {"SPY", "QQQ"}
        assert bundle.research_admitted is True      # gates stay governable


# ---------------------------------------------------------------------------
# real/synthetic source mislabel
# ---------------------------------------------------------------------------


class TestSourceLabelMismatch:
    def test_probe_manifest_but_vendor_source(self, tmp_path: Path) -> None:
        specs = {"SPY": [_bar("SPY", d, source="alpaca_iex")
                         for d in SESSIONS]}
        root = _write_snapshot(tmp_path, specs)
        bundle = load_historical_snapshot(root)
        assert _reasons(bundle) == {"SOURCE_LABEL_MISMATCH"}
        assert bundle.stores == {}
        assert "SOURCE_LABEL_MISMATCH:SPY" in bundle.blockers

    def test_live_manifest_but_probe_source(self, tmp_path: Path) -> None:
        def plant(manifest: dict) -> None:
            manifest["transport"] = {
                "mode": "live", "label": "LIVE", "real_network_used": True}

        root = _write_snapshot(tmp_path, _default_specs(), plant)
        bundle = load_historical_snapshot(root)
        assert _reasons(bundle) == {"SOURCE_LABEL_MISMATCH"}
        assert bundle.stores == {}

    def test_matching_live_labels_load(self, tmp_path: Path) -> None:
        specs = {"SPY": [_bar("SPY", d, source="alpaca_iex")
                         for d in SESSIONS]}

        def plant(manifest: dict) -> None:
            manifest["transport"] = {
                "mode": "live", "label": "LIVE", "real_network_used": True}

        root = _write_snapshot(tmp_path, specs, plant)
        bundle = load_historical_snapshot(root)
        assert bundle.refusals == ()
        assert set(bundle.stores) == {"SPY"}


# ---------------------------------------------------------------------------
# admission / license / PIT gates (exploratory load, never silent)
# ---------------------------------------------------------------------------


class TestAdmissionGates:
    def test_license_unverified_loads_exploratory_only(
        self, tmp_path: Path,
    ) -> None:
        def plant(manifest: dict) -> None:
            manifest["license"] = {"status": "LICENSE_UNVERIFIED"}

        root = _write_snapshot(tmp_path, _default_specs(), plant)
        bundle = load_historical_snapshot(root)
        assert bundle.research_admitted is False
        assert set(bundle.stores) == {"SPY", "QQQ"}   # exploratory use works
        assert "LICENSE_NOT_VERIFIED" in bundle.blockers
        assert set(bundle.scenario_tags.values()) == {
            SCENARIO_TAG_EXPLORATORY}

    def test_missing_pit_doc_blocks_admission(self, tmp_path: Path) -> None:
        def plant(manifest: dict) -> None:
            del manifest["pit"]

        root = _write_snapshot(tmp_path, _default_specs(), plant)
        bundle = load_historical_snapshot(root)
        assert bundle.research_admitted is False
        assert "PIT_BASIS_MISSING" in bundle.blockers
        assert bundle.manifest_summary["pit_level"] is None

    def test_pit_unknown_blocks_admission(self, tmp_path: Path) -> None:
        def plant(manifest: dict) -> None:
            manifest["pit"] = {"level": "UNKNOWN"}

        root = _write_snapshot(tmp_path, _default_specs(), plant)
        bundle = load_historical_snapshot(root)
        assert bundle.research_admitted is False
        assert "PIT_LEVEL_UNKNOWN" in bundle.blockers

    def test_restricted_marker_blocks_admission(self, tmp_path: Path) -> None:
        def plant(manifest: dict) -> None:
            manifest["admission"] = {"status": ADMISSION_RESTRICTED}

        root = _write_snapshot(tmp_path, _default_specs(), plant)
        bundle = load_historical_snapshot(root)
        assert bundle.research_admitted is False
        assert "ADMISSION_NOT_RELEASED" in bundle.blockers
        # license and PIT facts stay individually visible
        assert "LICENSE_NOT_VERIFIED" not in bundle.blockers
        assert set(bundle.stores) == {"SPY", "QQQ"}


# ---------------------------------------------------------------------------
# manifest hard errors (no bundle at all)
# ---------------------------------------------------------------------------


class TestManifestHardErrors:
    def test_missing_snapshot_dir(self, tmp_path: Path) -> None:
        with pytest.raises(SnapshotSourceError, match="snapshot dir missing"):
            load_historical_snapshot(tmp_path / "absent")

    def test_missing_manifest_file(self, tmp_path: Path) -> None:
        root = tmp_path / "snapshot"
        root.mkdir()
        with pytest.raises(SnapshotSourceError, match="missing snapshot manifest"):
            load_historical_snapshot(root)

    def test_unparsable_manifest(self, tmp_path: Path) -> None:
        root = tmp_path / "snapshot"
        root.mkdir()
        (root / "collection_manifest.json").write_bytes(b"{not json")
        with pytest.raises(SnapshotSourceError, match="unparsable"):
            load_historical_snapshot(root)

    def test_non_mapping_manifest(self, tmp_path: Path) -> None:
        root = tmp_path / "snapshot"
        root.mkdir()
        (root / "collection_manifest.json").write_bytes(b"[1, 2]")
        with pytest.raises(SnapshotSourceError, match="mapping"):
            load_historical_snapshot(root)

    @pytest.mark.parametrize(
        "mutate, match",
        [
            (lambda m: m.__setitem__("schema", "collection_manifest_v99"),
             "schema"),
            (lambda m: m.__setitem__("status", "PARTIAL"), "status"),
            (lambda m: m.__setitem__("namespace", "somewhere_else"),
             "namespace"),
            (lambda m: m.pop("admission"), "admission"),
            (lambda m: m["admission"].__setitem__("status", "MAYBE"),
             "admission status"),
            (lambda m: m["calendar_supply"].pop("version"), "version"),
            (lambda m: m["calendar_supply"].__setitem__("hash", "zz"),
             "hash"),
            (lambda m: m.__setitem__("transport", {}), "transport"),
            (lambda m: m["transport"].__setitem__("mode", "smuggled"),
             "transport mode"),
            (lambda m: m["transport"].__setitem__("label", ""), "label"),
            (lambda m: m["transport"].pop("real_network_used"),
             "real_network_used"),
            (lambda m: m.__setitem__("window", {}), "window"),
            (lambda m: m.__setitem__(
                "window", {"start": "2024-01-05", "end": "2024-01-01"}),
             "end precedes start"),
            (lambda m: m.pop("license"), "license"),
            (lambda m: m["license"].__setitem__("status", "MAYBE"),
             "license status"),
            (lambda m: m.__setitem__("pit", {"level": "GUESSED"}),
             "pit level"),
            (lambda m: m.__setitem__("symbols", {}), "non-empty"),
            (lambda m: m["symbols"].__setitem__("spy", m["symbols"]["SPY"]),
             "segment unsafe"),
            (lambda m: m["symbols"]["SPY"].__setitem__("row_count", -1),
             "row_count"),
            (lambda m: m["symbols"]["SPY"].__setitem__("bars_sha256", "zz"),
             "bars_sha256"),
        ],
    )
    def test_shape_violations_are_hard_errors(
        self, tmp_path: Path, mutate: Callable[[dict], None], match: str,
    ) -> None:
        root = _write_snapshot(tmp_path, _default_specs(), mutate)
        with pytest.raises(SnapshotSourceError, match=match):
            load_historical_snapshot(root)
