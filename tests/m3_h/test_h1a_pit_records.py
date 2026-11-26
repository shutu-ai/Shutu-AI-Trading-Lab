"""H1A T2 — available_at / received_at / PIT evidence levels.

Three timestamps are never conflated:

- ``ts_event_utc``   — the bar's session close (calendar-derived ET->UTC)
- ``available_at_utc`` — a VERIFIED vendor publish fact, else the declared
  model assumption (next session open), else UNKNOWN
- ``received_at_utc`` — when WE downloaded the bytes (a 2026 fixture
  moment); it is NEVER usable as a historical availability fact

``pit_evidence_level`` is a closed vocabulary ``VERIFIED / ASSUMED /
UNKNOWN``. A backfilled 2026 download cannot claim 2017 market
availability; HTTP 200 + intact hash NEVER upgrade a row to VERIFIED;
UNKNOWN availability is never silently promoted to ASSUMED.
"""

from __future__ import annotations

import datetime as dt
import sys
from decimal import Decimal
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (REPO_ROOT / "src", REPO_ROOT / "tests"):
    _sp = str(_p)
    if _sp not in sys.path:
        sys.path.insert(0, _sp)

from trading_lab.data.calendar import ET  # noqa: E402
from trading_lab.data.records import (  # noqa: E402
    MARKER_UNKNOWN_AVAILABILITY,
    SourceRecord,
)
from trading_lab.data.snapshot import (  # noqa: E402
    DatasetEntry,
    _entry_dict,
    build_snapshot,
    content_hash_of_rows,
    research_admissible,
)

UTC = dt.timezone.utc

RECEIVED_AT = dt.datetime(2026, 11, 26, 12, 0, tzinfo=UTC)  # THIS download moment


def _vendor_row(close: str = "600.10") -> dict[str, object]:
    """One synthetic daily bar in the guarded-client's parsed shape
    (Decimal prices, int volume, ISO vendor event stamp)."""
    return {
        "t": "2026-11-25T05:00:00Z",  # vendor session-start stamp (ET midnight)
        "o": Decimal("599.00"),
        "h": Decimal("601.00"),
        "l": Decimal("598.50"),
        "c": Decimal(close),
        "v": 41230000,
    }


def _assumed_record(close: str = "600.10") -> "object":
    from trading_lab.data.historical import HistoricalBarRecord

    return HistoricalBarRecord.assumed_next_open_row(
        _vendor_row(close),
        symbol="SPY",
        session_date=dt.date(2026, 11, 25),
        session_close_utc=dt.datetime(2026, 11, 25, 21, 0, tzinfo=UTC),
        assumed_available_at_utc=dt.datetime(2026, 11, 27, 14, 30, tzinfo=UTC),
        received_at_utc=RECEIVED_AT,
    )


class TestAvailabilityBasis:
    def test_default_basis_is_vendor_fact_and_legacy_dict_shape(self):
        rec = SourceRecord(
            source="alpaca_iex",
            dataset_version="v1",
            acquisition_time_utc=RECEIVED_AT,
            available_at_utc=dt.datetime(2026, 11, 20, 21, 0, tzinfo=UTC),
            raw_hash="a" * 64,
            transform_version="raw-1",
        )
        assert rec.availability_basis == "vendor_fact"
        entry = DatasetEntry(name="x", content_hash="b" * 64, row_count=1, source=rec)
        assert set(_entry_dict(entry).keys()) == {"name", "content_hash", "row_count", "source"}

    def test_legacy_manifest_hash_invariant(self):
        """Frozen from the pre-change code (T0 baseline capture, exact
        same inputs): legacy six-field SourceRecords must hash EXACTLY
        as before — recorded M1 evidence stays verifiable."""
        rec = SourceRecord(
            source="alpaca_iex",
            dataset_version="v1",
            acquisition_time_utc=dt.datetime(2026, 11, 20, tzinfo=UTC),
            available_at_utc=dt.datetime(2026, 11, 20, 21, 0, tzinfo=UTC),
            raw_hash="a" * 64,
            transform_version="raw-1",
        )
        entry = DatasetEntry(name="x", content_hash="b" * 64, row_count=1, source=rec)
        manifest = build_snapshot(dt.datetime(2026, 11, 21, tzinfo=UTC), [entry])
        assert manifest.dataset_hash == (
            "5be7617bd65b26863458af3b5ebb1aee812c740fd924a343a2ad0f07c8f6a597"
        )

    def test_assumed_basis_roundtrips_into_entry_dict(self):
        rec = SourceRecord(
            source="alpaca_iex",
            dataset_version="v1",
            acquisition_time_utc=RECEIVED_AT,
            available_at_utc=dt.datetime(2026, 11, 27, 14, 30, tzinfo=UTC),
            raw_hash="a" * 64,
            transform_version="raw-1",
            availability_basis="assumed_next_open",
        )
        entry = DatasetEntry(name="hist", content_hash="b" * 64, row_count=1, source=rec)
        payload = _entry_dict(entry)
        assert payload["source"]["availability_basis"] == "assumed_next_open"
        manifest = build_snapshot(dt.datetime(2026, 11, 28, tzinfo=UTC), [entry])
        assert manifest.verify()

    def test_unknown_basis_with_marker_allowed(self):
        rec = SourceRecord(
            source="alpaca_iex",
            dataset_version="v1",
            acquisition_time_utc=RECEIVED_AT,
            available_at_utc=MARKER_UNKNOWN_AVAILABILITY,
            raw_hash="a" * 64,
            transform_version="raw-1",
            availability_basis="unknown",
        )
        assert rec.availability_basis == "unknown"
        assert not rec.availability_known

    def test_assumed_basis_requires_a_datetime(self):
        with pytest.raises(ValueError):
            SourceRecord(
                source="alpaca_iex",
                dataset_version="v1",
                acquisition_time_utc=RECEIVED_AT,
                available_at_utc=MARKER_UNKNOWN_AVAILABILITY,
                raw_hash="a" * 64,
                transform_version="raw-1",
                availability_basis="assumed_next_open",
            )

    def test_invalid_basis_fail_closed(self):
        with pytest.raises(ValueError):
            SourceRecord(
                source="alpaca_iex",
                dataset_version="v1",
                acquisition_time_utc=RECEIVED_AT,
                available_at_utc=dt.datetime(2026, 11, 20, 21, 0, tzinfo=UTC),
                raw_hash="a" * 64,
                transform_version="raw-1",
                availability_basis="verified_because_hash_ok",
            )

    def test_research_admissible_semantics_unchanged_for_assumed_entry(self):
        """research_admissible stays the integrity+cutoff gate (ADR-003
        D8): an assumed entry inside cutoff passes it — which is exactly
        why pit_level_of_manifest must be consulted separately."""
        def _entry(available_at: dt.datetime) -> DatasetEntry:
            rec = SourceRecord(
                source="alpaca_iex",
                dataset_version="v1",
                acquisition_time_utc=RECEIVED_AT,
                available_at_utc=available_at,
                raw_hash="a" * 64,
                transform_version="raw-1",
                availability_basis="assumed_next_open",
            )
            return DatasetEntry(name="hist", content_hash="b" * 64, row_count=1, source=rec)

        manifest = build_snapshot(
            dt.datetime(2026, 11, 28, tzinfo=UTC), [_entry(dt.datetime(2026, 11, 27, 14, 30, tzinfo=UTC))]
        )
        assert research_admissible(manifest).ok
        late = build_snapshot(
            dt.datetime(2026, 11, 28, tzinfo=UTC), [_entry(dt.datetime(2026, 11, 29, 14, 30, tzinfo=UTC))]
        )
        result = research_admissible(late)
        assert not result.ok
        assert any(r.startswith("AVAILABLE_AFTER_CUTOFF") for r in result.reasons)


class TestHistoricalBarRecord:
    def test_assumed_row_binds_all_three_timestamps(self):
        rec = _assumed_record()
        assert rec.pit_evidence_level == "ASSUMED"
        assert rec.availability_evidence_kind == "model_assumption"
        assert rec.available_at_utc == rec.assumed_available_at_utc
        assert rec.ts_event_utc == dt.datetime(2026, 11, 25, 21, 0, tzinfo=UTC)
        assert rec.vendor_event_ts_utc == dt.datetime(2026, 11, 25, 5, 0, tzinfo=UTC)
        assert rec.received_at_utc == RECEIVED_AT
        # the assumption is NOT the download time, ever
        assert rec.available_at_utc != rec.received_at_utc

    def test_missing_vendor_field_rejected(self):
        from trading_lab.data.historical import HistoricalBarRecord

        row = _vendor_row()
        del row["v"]
        with pytest.raises(Exception) as exc:
            HistoricalBarRecord.assumed_next_open_row(
                row,
                symbol="SPY",
                session_date=dt.date(2026, 11, 25),
                session_close_utc=dt.datetime(2026, 11, 25, 21, 0, tzinfo=UTC),
                assumed_available_at_utc=dt.datetime(2026, 11, 27, 14, 30, tzinfo=UTC),
                received_at_utc=RECEIVED_AT,
            )
        assert "v" in str(exc.value)

    def test_naive_timestamps_rejected(self):
        from trading_lab.data.historical import HistoricalBarRecord, HistoricalDataError

        with pytest.raises(HistoricalDataError):
            HistoricalBarRecord.assumed_next_open_row(
                _vendor_row(),
                symbol="SPY",
                session_date=dt.date(2026, 11, 25),
                session_close_utc=dt.datetime(2026, 11, 25, 21, 0, tzinfo=UTC),
                assumed_available_at_utc=dt.datetime(2026, 11, 27, 14, 30),  # naive
                received_at_utc=RECEIVED_AT,
            )

    def test_unknown_row_has_no_assumption_and_never_promotes(self):
        from trading_lab.data.historical import HistoricalBarRecord, HistoricalDataError

        rec = HistoricalBarRecord.unknown_availability_row(
            _vendor_row(),
            symbol="SPY",
            session_date=dt.date(2026, 11, 25),
            session_close_utc=dt.datetime(2026, 11, 25, 21, 0, tzinfo=UTC),
            received_at_utc=RECEIVED_AT,
        )
        assert rec.pit_evidence_level == "UNKNOWN"
        assert rec.available_at_utc == MARKER_UNKNOWN_AVAILABILITY
        assert rec.assumed_available_at_utc is None
        # UNKNOWN availability must not be re-labeled as an assumption
        with pytest.raises(HistoricalDataError):
            HistoricalBarRecord(
                symbol="SPY",
                session_date=dt.date(2026, 11, 25),
                ts_event_utc=dt.datetime(2026, 11, 25, 21, 0, tzinfo=UTC),
                vendor_event_ts_utc=dt.datetime(2026, 11, 25, 5, 0, tzinfo=UTC),
                available_at_utc=MARKER_UNKNOWN_AVAILABILITY,
                assumed_available_at_utc=dt.datetime(2026, 11, 27, 14, 30, tzinfo=UTC),
                received_at_utc=RECEIVED_AT,
                pit_evidence_level="UNKNOWN",
                availability_evidence_kind="none",
                open=Decimal("599.00"),
                high=Decimal("601.00"),
                low=Decimal("598.50"),
                close=Decimal("600.10"),
                volume=41230000,
            )

    def test_verified_requires_vendor_published_time_evidence(self):
        from trading_lab.data.historical import HistoricalBarRecord, HistoricalDataError

        vendor_time = dt.datetime(2026, 11, 25, 21, 30, tzinfo=UTC)
        rec = HistoricalBarRecord.verified_vendor_row(
            _vendor_row(),
            symbol="SPY",
            session_date=dt.date(2026, 11, 25),
            session_close_utc=dt.datetime(2026, 11, 25, 21, 0, tzinfo=UTC),
            available_at_utc=vendor_time,
            evidence_detail="alpaca-history-receipt:deadbeef",
            received_at_utc=RECEIVED_AT,
        )
        assert rec.pit_evidence_level == "VERIFIED"
        assert rec.availability_evidence_kind == "vendor_published_time"
        assert rec.assumed_available_at_utc is None

        # declaring VERIFIED with no vendor evidence is refused
        with pytest.raises(HistoricalDataError):
            HistoricalBarRecord.verified_vendor_row(
                _vendor_row(),
                symbol="SPY",
                session_date=dt.date(2026, 11, 25),
                session_close_utc=dt.datetime(2026, 11, 25, 21, 0, tzinfo=UTC),
                available_at_utc=vendor_time,
                evidence_detail="",
                received_at_utc=RECEIVED_AT,
            )
        # ASSUMED rows can never carry vendor evidence either
        with pytest.raises(HistoricalDataError):
            HistoricalBarRecord(
                symbol="SPY",
                session_date=dt.date(2026, 11, 25),
                ts_event_utc=dt.datetime(2026, 11, 25, 21, 0, tzinfo=UTC),
                vendor_event_ts_utc=dt.datetime(2026, 11, 25, 5, 0, tzinfo=UTC),
                available_at_utc=dt.datetime(2026, 11, 27, 14, 30, tzinfo=UTC),
                assumed_available_at_utc=dt.datetime(2026, 11, 27, 14, 30, tzinfo=UTC),
                received_at_utc=RECEIVED_AT,
                pit_evidence_level="ASSUMED",
                availability_evidence_kind="vendor_published_time",
                open=Decimal("599.00"),
                high=Decimal("601.00"),
                low=Decimal("598.50"),
                close=Decimal("600.10"),
                volume=41230000,
            )

    def test_backdated_download_time_cannot_be_verified_availability(self):
        """A VERIFIED vendor publish time must precede our receipt: a row
        whose 'availability' is at/after the 2026 download moment is not a
        historical vendor fact — refused, not recorded as VERIFIED."""
        from trading_lab.data.historical import HistoricalBarRecord, HistoricalDataError

        with pytest.raises(HistoricalDataError):
            HistoricalBarRecord.verified_vendor_row(
                _vendor_row(),
                symbol="SPY",
                session_date=dt.date(2026, 11, 25),
                session_close_utc=dt.datetime(2026, 11, 25, 21, 0, tzinfo=UTC),
                available_at_utc=RECEIVED_AT,  # == download moment
                evidence_detail="download-receipt-not-a-vendor-fact",
                received_at_utc=RECEIVED_AT,
            )

    def test_ohlc_invariants_and_exact_decimal_types(self):
        from trading_lab.data.historical import HistoricalBarRecord, HistoricalDataError

        base = dict(
            symbol="SPY",
            session_date=dt.date(2026, 11, 25),
            ts_event_utc=dt.datetime(2026, 11, 25, 21, 0, tzinfo=UTC),
            vendor_event_ts_utc=dt.datetime(2026, 11, 25, 5, 0, tzinfo=UTC),
            available_at_utc=dt.datetime(2026, 11, 27, 14, 30, tzinfo=UTC),
            assumed_available_at_utc=dt.datetime(2026, 11, 27, 14, 30, tzinfo=UTC),
            received_at_utc=RECEIVED_AT,
            pit_evidence_level="ASSUMED",
            availability_evidence_kind="model_assumption",
        )
        with pytest.raises(HistoricalDataError):  # low above high
            HistoricalBarRecord(
                open=Decimal("599.00"),
                high=Decimal("598.00"),
                low=Decimal("599.50"),
                close=Decimal("600.10"),
                volume=41230000,
                **base,
            )
        with pytest.raises(HistoricalDataError):  # float price (platform ban)
            HistoricalBarRecord(
                open=599.00,
                high=Decimal("601.00"),
                low=Decimal("598.50"),
                close=Decimal("600.10"),
                volume=41230000,
                **base,
            )
        with pytest.raises(HistoricalDataError):  # negative volume
            HistoricalBarRecord(
                open=Decimal("599.00"),
                high=Decimal("601.00"),
                low=Decimal("598.50"),
                close=Decimal("600.10"),
                volume=-1,
                **base,
            )


class TestPitLevelOfManifest:
    def _entry(self, name: str, basis: str, available_at: object) -> DatasetEntry:
        rec = SourceRecord(
            source="alpaca_iex",
            dataset_version="v1",
            acquisition_time_utc=RECEIVED_AT,
            available_at_utc=available_at,
            raw_hash="a" * 64,
            transform_version="raw-1",
            availability_basis=basis,
        )
        return DatasetEntry(name=name, content_hash="b" * 64, row_count=1, source=rec)

    def _manifest(self, entries: list[DatasetEntry]):
        return build_snapshot(dt.datetime(2026, 11, 28, tzinfo=UTC), entries)

    def test_all_assumed_manifest_is_assumed_not_verified(self):
        from trading_lab.data.historical import PIT_ASSUMED_NOT_VERIFIED, pit_level_of_manifest

        manifest = self._manifest(
            [self._entry("spy", "assumed_next_open", dt.datetime(2026, 11, 27, 14, 30, tzinfo=UTC))]
        )
        assert pit_level_of_manifest(manifest) == "ASSUMED"
        assert PIT_ASSUMED_NOT_VERIFIED == "PIT_ASSUMED_NOT_VERIFIED"

    def test_any_unknown_makes_manifest_unknown(self):
        from trading_lab.data.historical import pit_level_of_manifest

        manifest = self._manifest(
            [
                self._entry("spy", "assumed_next_open", dt.datetime(2026, 11, 27, 14, 30, tzinfo=UTC)),
                self._entry("qqq", "unknown", MARKER_UNKNOWN_AVAILABILITY),
            ]
        )
        assert pit_level_of_manifest(manifest) == "UNKNOWN"

    def test_all_vendor_fact_manifest_is_verified(self):
        from trading_lab.data.historical import pit_level_of_manifest

        manifest = self._manifest(
            [self._entry("spy", "vendor_fact", dt.datetime(2026, 11, 20, 21, 0, tzinfo=UTC))]
        )
        assert pit_level_of_manifest(manifest) == "VERIFIED"

    def test_empty_manifest_is_unknown(self):
        from trading_lab.data.historical import pit_level_of_manifest

        assert pit_level_of_manifest(self._manifest([])) == "UNKNOWN"


class TestSnapshotSensitivity:
    def test_one_price_change_changes_content_hash(self):
        rows_a = [{"symbol": "SPY", "close": "600.10", "ts": "2026-11-25T21:00:00Z"}]
        rows_b = [{"symbol": "SPY", "close": "600.11", "ts": "2026-11-25T21:00:00Z"}]
        assert content_hash_of_rows(rows_a) != content_hash_of_rows(rows_b)

    def test_one_timestamp_change_changes_content_hash(self):
        rows_a = [{"symbol": "SPY", "close": "600.10", "ts": "2026-11-25T21:00:00Z"}]
        rows_b = [{"symbol": "SPY", "close": "600.10", "ts": "2026-11-25T21:00:01Z"}]
        assert content_hash_of_rows(rows_a) != content_hash_of_rows(rows_b)

    def test_stale_hash_manifest_fails_verify(self):
        from trading_lab.data.snapshot import SnapshotManifest

        rec = SourceRecord(
            source="alpaca_iex",
            dataset_version="v1",
            acquisition_time_utc=RECEIVED_AT,
            available_at_utc=dt.datetime(2026, 11, 27, 14, 30, tzinfo=UTC),
            raw_hash="a" * 64,
            transform_version="raw-1",
            availability_basis="assumed_next_open",
        )
        entry = DatasetEntry(name="spy", content_hash="b" * 64, row_count=1, source=rec)
        manifest = build_snapshot(dt.datetime(2026, 11, 28, tzinfo=UTC), [entry])
        # a manifest whose recorded hash belongs to DIFFERENT entries
        # (row_count drifted after hashing) must fail its own verify()
        drifted = (DatasetEntry(name="spy", content_hash="b" * 64, row_count=2, source=rec),)
        stale = SnapshotManifest(
            knowledge_cutoff_utc=manifest.knowledge_cutoff_utc,
            entries=drifted,
            dataset_hash=manifest.dataset_hash,
        )
        assert manifest.verify()
        assert not stale.verify()
