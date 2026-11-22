"""Crash recovery across restarts — true subprocess os._exit, real
journal state, exactly-once scoring after every crash point (task S3).

Crash points exercised (S3 崩溃时刻):
- locked-but-unobserved / mid-stream crash: the restart resumes the
  stream; nothing is scored twice; no slot is lost;
- observed-but-unscored (the durable state between the two appends,
  crafted verbatim): recovery completes that score exactly once from
  the stored observation;
- scored-then-restart: redelivery is pure duplicates, no re-scoring;
- crash before any persistence: clean start, no phantom locks.

Lease timing is made deterministic by rewriting the abandoned lock's
``expires_at`` into the past — equivalent to waiting out the lease and
keeps the tests off real-time sleeps.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from collections import Counter
from datetime import datetime as dtm
from pathlib import Path

import pytest
import yaml

from apps.trading_daemon.driver import run_replay
from apps.trading_daemon.envelope import ForwardEvent, payload_digest
from apps.trading_daemon.fixture import build_fixture_events
from apps.trading_daemon.journal import (
    ForwardJournal,
    read_entries,
    verify_journal_file,
)
from apps.trading_daemon.session import LockHeldError

REPO_ROOT = Path(__file__).resolve().parents[2]

WORKER_TEMPLATE = textwrap.dedent("""
    import os, sys, pathlib
    n = {n}
    root = r"{root}"
    sys.path.insert(0, root)
    sys.path.insert(0, root + "/src")
    from apps.trading_daemon.prereg import Preregistration
    from apps.trading_daemon.fixture import build_fixture_events
    from apps.trading_daemon.session import SessionLock
    prereg = Preregistration.load(pathlib.Path(r"{prereg}"))
    events = build_fixture_events()
    state = pathlib.Path(r"{state}")
    state.mkdir(parents=True, exist_ok=True)
    # hold the lease like the real driver would, then die WITHOUT any
    # cleanup: the lock file and the open session are what a crash leaves
    SessionLock(state / "session.lock", lease_seconds=60).acquire()
    if n == 0:
        os._exit(0)   # crash BEFORE any persistence
    from apps.trading_daemon.driver import run_replay
    run_replay(state_dir=str(state), prereg=prereg,
               events=events[:n], session_index=1, lease_seconds=60,
               complete=False, with_lock=False)
    # every append() returned => journal state is durable on disk now
    os._exit(0)
""")


def _spawn_crashed_worker(tmp_path, prereg_path, state, n) -> None:
    code = WORKER_TEMPLATE.format(
        root=str(REPO_ROOT), prereg=str(prereg_path), state=str(state),
        n=n)
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True,
        cwd=str(tmp_path), timeout=120)
    assert proc.returncode == 0, proc.stderr


def _expire_lockfile(state: Path) -> None:
    """Simulate the lease having elapsed (deterministic instead of a
    real-time sleep): the abandoned holder is gone; the takeover below
    is the audited recovery path."""
    lock = state / "session.lock"
    record = json.loads(lock.read_text(encoding="utf-8"))
    record["expires_at"] = (
        dtm.now(dtm.now().astimezone().tzinfo)).isoformat()
    lock.write_text(json.dumps(record, sort_keys=True), encoding="utf-8")


@pytest.fixture()
def prereg_path(prereg, tmp_path) -> Path:
    p = tmp_path / "forward_observation.yaml"
    p.write_text(
        yaml.safe_dump(prereg.plain_payload(), sort_keys=True),
        encoding="utf-8")
    return p


def _scored_by_slot(entries) -> Counter:
    return Counter(
        e["payload"]["slot_id"] for e in entries
        if e["event_type"] == "SCORED")


def test_crash_after_partial_stream_then_recover(
        tmp_path, prereg, prereg_path, fixture_events):
    state = tmp_path / "state"
    _spawn_crashed_worker(tmp_path, prereg_path, state, n=12)
    assert (state / "journal.jsonl").exists()

    # the crashed worker left an UNEXPIRED lease: conservative refusal
    with pytest.raises(LockHeldError):
        run_replay(state_dir=state, prereg=prereg, events=fixture_events,
                   session_index=2, lease_seconds=60)
    _expire_lockfile(state)
    summary = run_replay(state_dir=state, prereg=prereg,
                         events=fixture_events, session_index=2,
                         lease_seconds=60)

    ok, msg = verify_journal_file(state / "journal.jsonl")
    assert ok, msg
    entries = read_entries(state / "journal.jsonl")
    scored = _scored_by_slot(entries)
    assert all(v == 1 for v in scored.values()), "double SCORED entry"
    # cumulative across both sessions: slots e4..e28 scored exactly once
    n_locks = sum(1 for e in entries
                  if e["event_type"] == "PREDICTION_LOCKED")
    assert n_locks == 26
    assert sum(scored.values()) == 25
    # the takeover was audited in the journal itself
    assert any(e["event_type"] == "RECOVERY"
               and e["payload"].get("reason") == "STALE_LEASE_TAKEOVER"
               for e in entries)


def test_resume_observed_but_unscored_slot(
        tmp_path, prereg, prereg_path, fixture_events):
    """Craft exactly the durable state a crash between the two appends
    leaves: OBSERVATION_RECEIVED persisted, SCORED not yet. Recovery
    must complete that score exactly once from the stored observation."""
    state = tmp_path / "state"
    _spawn_crashed_worker(tmp_path, prereg_path, state, n=7)
    # state: slots e4,e5 SCORED; slot e6 LOCKED (session left open)
    path = state / "journal.jsonl"

    # e7 arrives and is consumed as the observation of slot(e6); the
    # process dies after that append, before the SCORED append:
    journal = ForwardJournal.open(path, prereg=prereg)
    ev = ForwardEvent.model_validate(fixture_events[7])
    journal.append("OBSERVATION_RECEIVED", {
        "slot_id": f"slot-{fixture_events[6]['event_id']}",
        "event_id": ev.event_id,
        "payload_digest": payload_digest(ev),
        "close": str(ev.close),
        "ts_event": ev.ts_event.isoformat(),
        "ts_available": ev.ts_available.isoformat(),
    })
    _expire_lockfile(state)

    summary = run_replay(state_dir=state, prereg=prereg,
                         events=fixture_events, session_index=2,
                         lease_seconds=60)
    ok, msg = verify_journal_file(path)
    assert ok, msg
    final = read_entries(path)
    scored = _scored_by_slot(final)
    assert all(v == 1 for v in scored.values())
    assert sum(scored.values()) == 25
    recovered = [e for e in final
                 if e["event_type"] == "SCORED"
                 and e["payload"].get("recovered") is True]
    assert len(recovered) == 1
    assert recovered[0]["payload"]["slot_id"].endswith(
        fixture_events[6]["event_id"])
    # e0..e6 were consumed in the crashed session -> duplicates; the
    # crafted observation event e7 was never itself consumed, so it
    # reprocesses normally (exactly the post-crash semantics)
    assert summary.counters["duplicates"] == 7


def test_full_run_then_restart_all_duplicates(
        tmp_path, prereg, prereg_path, fixture_events):
    state = tmp_path / "state"
    run_replay(state_dir=state, prereg=prereg, events=fixture_events,
               session_index=1)
    before = _scored_by_slot(read_entries(state / "journal.jsonl"))

    _spawn_crashed_worker(tmp_path, prereg_path, state, n=0)
    _expire_lockfile(state)
    summary = run_replay(state_dir=state, prereg=prereg,
                         events=fixture_events, session_index=2)
    after = _scored_by_slot(read_entries(state / "journal.jsonl"))
    assert before == after
    assert summary.counters["duplicates"] == len(fixture_events)


def test_crash_before_any_persistence_is_clean_start(
        tmp_path, prereg, prereg_path, fixture_events):
    state = tmp_path / "state"
    _spawn_crashed_worker(tmp_path, prereg_path, state, n=0)
    _expire_lockfile(state)
    summary = run_replay(state_dir=state, prereg=prereg,
                         events=fixture_events, session_index=1)
    assert summary.counters["scored"]["total"] == 25
    assert summary.recovery_status == "CLEAN_START"
