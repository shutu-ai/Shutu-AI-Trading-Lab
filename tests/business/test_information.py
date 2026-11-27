"""Loader tests for ``business.information``: format round-trips, dedup
accounting, refusal accounting (missing PIT timestamps, hash mismatch,
unknown keys) and the PIT window of ``InfoBundle.usable``."""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from trading_lab.business.info_fixtures import demo_info_events  # noqa: E402
from trading_lab.business.information import (  # noqa: E402
    InfoBundle,
    content_hash_of,
    load_info_events,
)

SESSION_DATES = [dt.date(2026, 9, 1) + dt.timedelta(days=i) for i in range(6)]


def write_jsonl(path: Path, rows) -> Path:
    path.write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return path


def write_json(path: Path, rows) -> Path:
    path.write_text(json.dumps(list(rows)), encoding="utf-8")
    return path


def write_csv(path: Path, rows) -> Path:
    import csv as _csv

    keys = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = _csv.DictWriter(fh, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)
    return path


def pick(rows, event_id: str):
    return next(r for r in rows if r["event_id"] == event_id)


@pytest.fixture()
def demo_rows():
    return list(demo_info_events(SESSION_DATES))


class TestFormats:
    def test_jsonl_round_trip(self, tmp_path, demo_rows):
        path = write_jsonl(tmp_path / "events.jsonl", demo_rows)
        bundle = load_info_events([path])
        loaded_content = {e.event_id: e.content for e in bundle.events}
        skipped = {"EVT-DUP-B-008", "EVT-MISSING-AVAILABLE-010"}
        for row in demo_rows:
            if row["event_id"] in skipped:
                continue  # deduplicated duplicate / refused row
            assert loaded_content[row["event_id"]] == row["content"]
        assert len(bundle.events) == 10

    def test_json_round_trip_equals_jsonl(self, tmp_path, demo_rows):
        subset = demo_rows[:5]
        from_jsonl = load_info_events([write_jsonl(
            tmp_path / "a.jsonl", subset)])
        from_json = load_info_events([write_json(tmp_path / "b.json", subset)])
        assert from_json.events == from_jsonl.events
        assert from_json.rejected == from_jsonl.rejected

    def test_csv_round_trip_equals_jsonl(self, tmp_path, demo_rows):
        subset = demo_rows[:3]
        from_jsonl = load_info_events([write_jsonl(
            tmp_path / "a.jsonl", subset)])
        from_csv = load_info_events([write_csv(tmp_path / "b.csv", subset)])
        assert from_csv.events == from_jsonl.events
        assert from_csv.rejected == from_jsonl.rejected

    def test_mixed_formats_in_one_call(self, tmp_path, demo_rows):
        first = load_info_events([write_jsonl(
            tmp_path / "a.jsonl", demo_rows[:6])])
        second = load_info_events([
            write_jsonl(tmp_path / "a.jsonl", demo_rows[:3]),
            write_csv(tmp_path / "b.csv", demo_rows[3:6]),
        ])
        assert second.events == first.events

    def test_unsupported_suffix_raises(self, tmp_path):
        path = tmp_path / "events.txt"
        path.write_text("nope", encoding="utf-8")
        with pytest.raises(ValueError):
            load_info_events([path])

    def test_empty_path_list_raises(self):
        with pytest.raises(ValueError):
            load_info_events([])

    def test_json_doc_must_be_array(self, tmp_path, demo_rows):
        path = tmp_path / "events.json"
        path.write_text(json.dumps(demo_rows[0]), encoding="utf-8")
        with pytest.raises(ValueError):
            load_info_events([path])

    def test_unparsable_jsonl_line_is_rejected(self, tmp_path, demo_rows):
        good = json.dumps(demo_rows[0])
        path = tmp_path / "events.jsonl"
        path.write_text("{oops not json\n" + good + "\n", encoding="utf-8")
        bundle = load_info_events([path])
        assert len(bundle.rejected) == 1
        assert bundle.rejected[0].reason.startswith("JSON_LINE_UNPARSABLE")
        assert len(bundle.events) == 1


class TestDemoFixtureAccounting:
    def test_inventory_shape(self, demo_rows):
        assert len(demo_rows) == 12
        assert sum(1 for r in demo_rows if "available_at_utc" not in r) == 1
        dup_hashes = [r["content_hash"] for r in demo_rows]
        assert len(set(dup_hashes)) == len(dup_hashes) - 1  # one dup pair

    def test_loader_accounting(self, tmp_path, demo_rows):
        path = write_jsonl(tmp_path / "events.jsonl", demo_rows)
        bundle = load_info_events([path])
        # 12 rows: 1 refused (missing available_at), 1 duplicate member
        assert len(bundle.events) == 10
        assert bundle.duplicate_count == 1
        assert len(bundle.rejected) == 1
        rejected = bundle.rejected[0]
        assert rejected.event_id == "EVT-MISSING-AVAILABLE-010"
        assert rejected.reason.startswith("MISSING_KEYS:")
        assert "available_at_utc" in rejected.reason
        ids = {e.event_id for e in bundle.events}
        assert "EVT-MISSING-AVAILABLE-010" not in ids
        assert "EVT-DUP-A-007" in ids and "EVT-DUP-B-008" not in ids

    def test_unknown_asset_loads(self, tmp_path, demo_rows):
        path = write_jsonl(tmp_path / "events.jsonl", demo_rows)
        bundle = load_info_events([path])
        assert any(e.asset == "ZZUNKN" for e in bundle.events)

    def test_future_event_is_far_after_window(self, tmp_path, demo_rows):
        path = write_jsonl(tmp_path / "events.jsonl", demo_rows)
        bundle = load_info_events([path])
        future = next(e for e in bundle.events
                      if e.event_id == "EVT-FUTURE-005")
        last_close = dt.datetime.combine(
            SESSION_DATES[-1], dt.time(21, 0), tzinfo=dt.timezone.utc)
        assert future.available_at_utc > last_close


class TestRefusals:
    def test_content_hash_mismatch_refused(self, tmp_path, demo_rows):
        bad = {**demo_rows[0], "content_hash": "ab" * 32}
        path = write_jsonl(tmp_path / "events.jsonl", [bad])
        bundle = load_info_events([path])
        assert bundle.events == ()
        assert len(bundle.rejected) == 1
        assert bundle.rejected[0].reason.startswith("CONTENT_HASH_MISMATCH")
        assert content_hash_of(bad["content"]) in bundle.rejected[0].reason

    def test_unknown_key_refused(self, tmp_path, demo_rows):
        bad = {**demo_rows[0], "insider_note": "buy before the print"}
        path = write_jsonl(tmp_path / "events.jsonl", [bad])
        bundle = load_info_events([path])
        assert len(bundle.rejected) == 1
        assert bundle.rejected[0].reason == (
            "UNKNOWN_KEYS:insider_note")

    def test_missing_received_at_refused(self, tmp_path, demo_rows):
        bad = {k: v for k, v in demo_rows[0].items()
               if k != "received_at_utc"}
        path = write_jsonl(tmp_path / "events.jsonl", [bad])
        bundle = load_info_events([path])
        assert len(bundle.rejected) == 1
        assert bundle.rejected[0].reason == "MISSING_KEYS:received_at_utc"

    def test_csv_row_with_empty_pit_cell_refused(
            self, tmp_path, demo_rows):
        """An event without a parseable available_at (empty CSV cell)
        never enters decisions — the contract refuses the record."""
        good = pick(demo_rows, "EVT-BULL-EARN-001")
        bad = {**good, "available_at_utc": ""}
        path = write_csv(tmp_path / "events.csv", [bad, good])
        bundle = load_info_events([path])
        assert len(bundle.rejected) == 1
        assert bundle.rejected[0].event_id == "EVT-BULL-EARN-001"
        assert bundle.rejected[0].reason.startswith("CONTRACT_INVALID")
        assert "available_at_utc" in bundle.rejected[0].reason
        assert len(bundle.events) == 1
        # the second CSV row is the valid copy of the same event
        assert bundle.events[0].event_id == "EVT-BULL-EARN-001"
        assert bundle.events[0].available_at_utc == dt.datetime.combine(
            SESSION_DATES[4], dt.time(14, 35), tzinfo=dt.timezone.utc)


class TestDedup:
    def test_first_occurrence_wins_across_files(self, tmp_path, demo_rows):
        a = pick(demo_rows, "EVT-DUP-A-007")
        b = pick(demo_rows, "EVT-DUP-B-008")
        p1 = write_jsonl(tmp_path / "a.jsonl", [a])
        p2 = write_jsonl(tmp_path / "b.jsonl", [b])
        bundle = load_info_events([p1, p2])
        assert len(bundle.events) == 1
        assert bundle.events[0].event_id == "EVT-DUP-A-007"
        assert bundle.duplicate_count == 1
        reversed_bundle = load_info_events([p2, p1])
        assert reversed_bundle.events[0].event_id == "EVT-DUP-B-008"

    def test_content_hash_is_the_dedup_key_not_event_id(
            self, tmp_path, demo_rows):
        a = pick(demo_rows, "EVT-DUP-A-007")
        b = pick(demo_rows, "EVT-DUP-B-008")
        assert a["content"] == b["content"]
        assert a["event_id"] != b["event_id"]
        path = write_jsonl(tmp_path / "events.jsonl", [a, b])
        bundle = load_info_events([path])
        assert bundle.duplicate_count == 1


class TestOrderingAndPit:
    def test_deterministic_ordering(self, tmp_path, demo_rows):
        path = write_jsonl(tmp_path / "a.jsonl", demo_rows)
        b1 = load_info_events([path])
        assert b1.events == load_info_events([path]).events  # stable rerun
        keyed = [(e.available_at_utc, e.event_id) for e in b1.events]
        assert keyed == sorted(keyed)
        # reversed arrival flips only the dedup survivor (first wins);
        # every other event, and the stored order itself, is unchanged
        b2 = load_info_events([
            write_jsonl(tmp_path / "b.jsonl", list(reversed(demo_rows)))])
        keyed2 = [(e.available_at_utc, e.event_id) for e in b2.events]
        assert keyed2 == sorted(keyed2)

        def without(bundle, event_id):
            return [(e.available_at_utc, e.event_id) for e in bundle.events
                    if e.event_id != event_id]

        assert without(b1, "EVT-DUP-A-007") == without(b2, "EVT-DUP-B-008")

    def test_usable_respects_received_at_gate(self, tmp_path, demo_rows):
        path = write_jsonl(tmp_path / "events.jsonl", demo_rows)
        bundle = load_info_events([path])
        event = next(e for e in bundle.events
                     if e.event_id == "EVT-BULL-EARN-001")
        between = event.available_at_utc + dt.timedelta(minutes=1)
        assert event.available_at_utc < between < event.received_at_utc
        assert event.event_id not in {
            e.event_id for e in bundle.usable(between)}
        assert event.event_id in {
            e.event_id for e in bundle.usable(event.received_at_utc)}

    def test_future_event_not_usable_before_available(
            self, tmp_path, demo_rows):
        path = write_jsonl(tmp_path / "events.jsonl", demo_rows)
        bundle = load_info_events([path])
        future = next(e for e in bundle.events
                      if e.event_id == "EVT-FUTURE-005")
        last_close = dt.datetime.combine(
            SESSION_DATES[-1], dt.time(21, 0), tzinfo=dt.timezone.utc)
        assert future.event_id not in {
            e.event_id for e in bundle.usable(last_close)}
        after = future.available_at_utc + dt.timedelta(days=1)
        assert future.event_id in {
            e.event_id for e in bundle.usable(after)}

    def test_usable_rejects_naive_asof(self, tmp_path, demo_rows):
        path = write_jsonl(tmp_path / "events.jsonl", demo_rows)
        bundle = load_info_events([path])
        with pytest.raises(ValueError):
            bundle.usable(dt.datetime(2026, 9, 10, 21, 0))

    def test_bundle_is_frozen(self, tmp_path, demo_rows):
        bundle = load_info_events(
            [write_jsonl(tmp_path / "events.jsonl", demo_rows)])
        with pytest.raises(Exception):
            bundle.duplicate_count = 99  # type: ignore[misc]
