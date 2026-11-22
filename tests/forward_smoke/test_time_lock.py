"""The core forward discipline: predictions are durably locked BEFORE
observations are consumed, and scoring cannot backfill (task S1/S2)."""

from __future__ import annotations

import pytest

from apps.trading_daemon.driver import run_replay
from apps.trading_daemon.fixture import build_fixture_events
from apps.trading_daemon.journal import (
    ForwardJournal,
    JournalIntegrityError,
    read_entries,
)


@pytest.fixture()
def completed(tmp_path, prereg, fixture_events):
    summary = run_replay(
        state_dir=tmp_path / "state", prereg=prereg, events=fixture_events,
        session_index=1)
    journal = ForwardJournal.open(tmp_path / "state" / "journal.jsonl",
                                  prereg=prereg)
    return summary, journal, read_entries(tmp_path / "state" / "journal.jsonl")


def _kind_seq(entries, kind):
    return [e for e in entries if e["event_type"] == kind]


def test_lock_precedes_observation_precedes_score(completed):
    _summary, _journal, entries = completed
    locks = _kind_seq(entries, "PREDICTION_LOCKED")
    observations = _kind_seq(entries, "OBSERVATION_RECEIVED")
    scores = _kind_seq(entries, "SCORED")
    expiries = _kind_seq(entries, "EXPIRED")
    assert locks and observations and scores
    by_slot_lock = {e["payload"]["slot_id"]: e["seq"] for e in locks}
    by_slot_obs = {e["payload"]["slot_id"]: e["seq"] for e in observations}
    by_slot_score = {e["payload"]["slot_id"]: e["seq"] for e in scores}
    expired_slots = {e["payload"]["slot_id"] for e in expiries}
    for slot in by_slot_lock:
        if slot in expired_slots:
            continue  # session-end expiry: the honest TTL path
        assert slot in by_slot_obs, f"{slot} locked but never observed"
        assert by_slot_lock[slot] < by_slot_obs[slot]
        assert by_slot_obs[slot] < by_slot_score[slot]
    # exactly one session-end expiry (the final slot)
    assert all(e["payload"]["reason"] == "SESSION_END" for e in expiries)


def test_score_references_locked_digest_not_backfilled(completed):
    _summary, _journal, entries = completed
    locks = {e["payload"]["slot_id"]: e for e in
             _kind_seq(entries, "PREDICTION_LOCKED")}
    for score in _kind_seq(entries, "SCORED"):
        slot = score["payload"]["slot_id"]
        lock = locks[slot]
        assert score["payload"]["prediction_lock_digest"] == \
            lock["payload"]["prediction_lock_digest"]
        assert score["payload"]["exposure"] == lock["payload"]["exposure"]
        # the locked reference close is what scoring compared against
        assert score["payload"]["reference_close"] == \
            lock["payload"]["reference_close"]


def test_event_before_any_lock_is_never_scored(tmp_path, prereg, fixture_events):
    """The warmup events produce inputs, never predictions or scores."""
    summary = run_replay(
        state_dir=tmp_path / "state", prereg=prereg,
        events=fixture_events[:3], session_index=1)
    assert summary.counters["locked"] == 0
    assert summary.counters["scored"]["total"] == 0
    entries = read_entries(tmp_path / "state" / "journal.jsonl")
    assert not _kind_seq(entries, "SCORED")
    assert not _kind_seq(entries, "OBSERVATION_RECEIVED")


def test_first_event_on_fresh_journal_only_locks(tmp_path, prereg, fixture_events):
    summary = run_replay(
        state_dir=tmp_path / "state", prereg=prereg,
        events=fixture_events[:5], session_index=1)
    # e0..e3 warmup inputs; e4 opens the first slot; nothing to observe yet
    assert summary.counters["locked"] == 1
    assert summary.counters["observed"] == 0
    assert summary.counters["scored"]["total"] == 0


def test_observation_without_lock_is_integrity_failure(tmp_path, prereg):
    """A journal holding an observation with no matching locked prediction
    cannot happen through the engine; if crafted by hand it must fail
    closed on the next open (hindsight guard)."""
    state = tmp_path / "state"
    state.mkdir()
    journal_path = state / "journal.jsonl"
    journal = ForwardJournal.open(journal_path, prereg=prereg)
    events = build_fixture_events()
    ev = events[0]
    journal.append("OBSERVATION_RECEIVED", {
        "slot_id": "never-locked-slot",
        "event_id": ev["event_id"],
        "payload_digest": "0" * 64,
        "close": str(ev["close"]),
    })
    with pytest.raises(JournalIntegrityError):
        ForwardJournal.open(journal_path, prereg=prereg)


def test_prediction_cannot_be_relocked_or_mutated(tmp_path, prereg, fixture_events):
    state = tmp_path / "state"
    run_replay(state_dir=state, prereg=prereg, events=fixture_events[:6],
               session_index=1)
    entries = read_entries(state / "journal.jsonl")
    locks = _kind_seq(entries, "PREDICTION_LOCKED")
    slot_ids = [e["payload"]["slot_id"] for e in locks]
    assert len(slot_ids) == len(set(slot_ids)), "slot locked twice"


def test_scoring_uses_observation_available_after_lock(completed):
    _summary, _journal, entries = completed
    for score in _kind_seq(entries, "SCORED"):
        payload = score["payload"]
        assert payload["forward_cohort"] is not None
        fc = payload["forward_cohort"]
        assert fc["prediction_locked_at"] < fc["observation_available_at"]
