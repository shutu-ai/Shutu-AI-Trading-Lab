"""End-to-end offline harness: the full synthetic replay with the real
frozen preregistration — counters, cohort hygiene, determinism."""

from __future__ import annotations

from apps.trading_daemon.driver import run_replay
from apps.trading_daemon.fixture import build_fixture_events


def test_full_replay_counters(tmp_path, prereg, fixture_events):
    summary = run_replay(state_dir=tmp_path / "state", prereg=prereg,
                         events=fixture_events, session_index=1)
    c = summary.counters
    assert c["events_delivered"] == 30
    assert c["consumed"] == 30
    # e4..e29 lock slots (26); e5..e29 observe+score slots e4..e28 (25);
    # the final slot expires at session end
    assert c["locked"] == 26
    assert c["observed"] == 25
    assert c["scored"]["total"] == 25
    assert c["scored"]["hit"] + c["scored"]["miss"] + \
        c["scored"]["no_claim"] == 25
    assert c["expired"] == 1
    assert summary.suspended is False
    assert summary.no_broker_writes is True


def test_cohort_hygiene_recorded(tmp_path, prereg, fixture_events):
    summary = run_replay(state_dir=tmp_path / "state", prereg=prereg,
                         events=fixture_events, session_index=1)
    cohort = summary.cohort
    assert cohort["role"] == "FORWARD"
    assert cohort["prediction_locked_at"] < cohort["last_observation_at"]
    assert cohort["independent_disclosure"] is not None


def test_anchor_written_and_reopenable(tmp_path, prereg, fixture_events):
    from apps.trading_daemon.journal import (
        ANCHOR_NAME, ForwardJournal, verify_journal_file)
    state = tmp_path / "state"
    run_replay(state_dir=state, prereg=prereg, events=fixture_events,
               session_index=1)
    assert (state / ANCHOR_NAME).exists()
    ok, msg = verify_journal_file(state / "journal.jsonl")
    assert ok, msg
    journal = ForwardJournal.open(state / "journal.jsonl", prereg=prereg)
    ok2, msg2 = journal.verify()
    assert ok2, msg2


def test_identical_fixture_replays_are_equivalent(tmp_path, prereg):
    events = build_fixture_events()
    a = run_replay(state_dir=tmp_path / "a", prereg=prereg, events=events,
                   session_index=1)
    b = run_replay(state_dir=tmp_path / "b", prereg=prereg, events=events,
                   session_index=1)
    assert a.logical_digest == b.logical_digest
    assert a.score_sequence == b.score_sequence


def test_replay_with_admitted_fixture_only(tmp_path, prereg):
    """The runner refuses to feed events whose dataset is not the
    preregistered fixture (defense in depth beyond the engine)."""
    import copy
    events = build_fixture_events()
    events[10]["dataset_hash"] = "2" * 64
    summary = run_replay(state_dir=tmp_path / "state", prereg=prereg,
                         events=events, session_index=1)
    assert summary.counters["rejected"] >= 1
