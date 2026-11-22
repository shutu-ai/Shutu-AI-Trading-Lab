"""Idempotency across duplicate deliveries and full replays (task S1/S3)."""

from __future__ import annotations

import copy

from apps.trading_daemon.driver import run_replay
from apps.trading_daemon.journal import ForwardJournal, read_entries


def _kind_seq(entries, kind):
    return [e for e in entries if e["event_type"] == kind]


def test_redelivery_same_payload_is_idempotent_duplicate(
        tmp_path, prereg, fixture_events):
    state = tmp_path / "state"
    doubled = fixture_events[:8] + fixture_events[:8]
    summary = run_replay(state_dir=state, prereg=prereg, events=doubled,
                         session_index=1)
    assert summary.counters["duplicates"] == 8
    # duplicates did not change the scored outcome
    assert summary.counters["scored"]["total"] == 3
    entries = read_entries(state / "journal.jsonl")
    assert len(_kind_seq(entries, "SCORED")) == 3


def test_same_event_id_different_payload_is_conflict(
        tmp_path, prereg, fixture_events):
    state = tmp_path / "state"
    events = copy.deepcopy(fixture_events[:6])
    impostor = copy.deepcopy(events[4])
    impostor["close"] = str(impostor["close"]) + "1"   # different logical payload
    events.insert(6, impostor)
    summary = run_replay(state_dir=state, prereg=prereg, events=events,
                         session_index=1)
    assert summary.counters["rejected"] >= 1
    assert summary.suspended is True
    entries = read_entries(state / "journal.jsonl")
    rejections = _kind_seq(entries, "REJECTED")
    assert any(r["payload"]["reason"] == "CONFLICT_PAYLOAD_DIFFERS"
               for r in rejections)


def test_engine_suspended_after_conflict_refuses_further_work(
        tmp_path, prereg, fixture_events):
    state = tmp_path / "state"
    events = copy.deepcopy(fixture_events[:6])
    impostor = copy.deepcopy(events[4])
    impostor["close"] = str(impostor["close"]) + "2"
    events.insert(6, impostor)
    events.extend(copy.deepcopy(fixture_events[6:9]))
    summary = run_replay(state_dir=state, prereg=prereg, events=events,
                         session_index=1)
    assert summary.suspended is True
    # nothing after the conflict was consumed
    assert summary.counters["consumed"] == 6


def test_full_replay_on_same_journal_all_duplicates_no_new_scores(
        tmp_path, prereg, fixture_events):
    state = tmp_path / "state"
    first = run_replay(state_dir=state, prereg=prereg,
                       events=fixture_events, session_index=1)
    entries_before = read_entries(state / "journal.jsonl")
    scores_before = len(_kind_seq(entries_before, "SCORED"))

    second = run_replay(state_dir=state, prereg=prereg,
                        events=fixture_events, session_index=2)
    assert second.counters["duplicates"] == len(fixture_events)
    assert second.counters["scored"]["total"] == 0
    entries_after = read_entries(state / "journal.jsonl")
    assert len(_kind_seq(entries_after, "SCORED")) == scores_before
    assert first.counters["scored"]["total"] == 25


def test_replay_reproducibility_same_inputs_same_logical_summary(
        tmp_path, prereg, fixture_events):
    """Same fixture, same locked identity, fresh state => equivalent
    logical output (task S2.4). Wall-clock audit stamps differ; the
    logical summary must not."""
    a = run_replay(state_dir=tmp_path / "a", prereg=prereg,
                   events=fixture_events, session_index=1)
    b = run_replay(state_dir=tmp_path / "b", prereg=prereg,
                   events=fixture_events, session_index=1)
    assert a.logical_digest == b.logical_digest
    assert a.counters == b.counters
    assert a.score_sequence == b.score_sequence
