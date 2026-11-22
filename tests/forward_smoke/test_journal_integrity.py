"""Journal integrity: hash chain, head record, external anchor; tail
truncation / edits / anchor mismatch must refuse startup (task S3)."""

from __future__ import annotations

import json

import pytest

from apps.trading_daemon.driver import run_replay
from apps.trading_daemon.fixture import build_fixture_events
from apps.trading_daemon.journal import (
    ANCHOR_NAME,
    ForwardJournal,
    JournalIntegrityError,
    verify_journal_file,
)


def _run(state, tmp_path, prereg, events, session_index=1):
    return run_replay(state_dir=tmp_path / state, prereg=prereg,
                      events=events, session_index=session_index)


def test_verify_clean_after_run(tmp_path, prereg, fixture_events):
    state = tmp_path / "state"
    _run("state", tmp_path, prereg, fixture_events)
    ok, msg = verify_journal_file(state / "journal.jsonl")
    assert ok, msg


def _open_refuses(path, exc=JournalIntegrityError):
    with pytest.raises(exc):
        ForwardJournal.open(path, prereg=None)


def test_tail_truncation_detected_via_head_record(tmp_path, prereg, fixture_events):
    state = tmp_path / "state"
    _run("state", tmp_path, prereg, fixture_events[:10])
    path = state / "journal.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
    ok, msg = verify_journal_file(path)
    assert not ok
    assert "truncat" in msg.lower() or "head" in msg.lower()
    _open_refuses(path)


def test_middle_edit_detected(tmp_path, prereg, fixture_events):
    state = tmp_path / "state"
    _run("state", tmp_path, prereg, fixture_events[:10])
    path = state / "journal.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[3])
    record["payload"]["close"] = "999"          # forge history
    lines[3] = json.dumps(record, sort_keys=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    ok, _msg = verify_journal_file(path)
    assert not ok
    _open_refuses(path)


def test_external_anchor_detects_whole_file_replacement(
        tmp_path, prereg, fixture_events):
    """Head records travel WITH the journal; the external anchor closes
    the whole-file-replacement hole (same pattern as the M3 ledger
    anchor)."""
    state = tmp_path / "state"
    _run("state", tmp_path, prereg, fixture_events)
    path = state / "journal.jsonl"
    entries = [json.loads(l) for l in
               path.read_text(encoding="utf-8").splitlines() if l.strip()]
    forged = entries[:6]                        # keep the head, drop the tail
    path.write_text(
        "\n".join(json.dumps(e, sort_keys=True) for e in forged) + "\n",
        encoding="utf-8")
    # internal chain of the forged prefix is intact, but the co-located
    # head record still claims the full entry count — and the external
    # anchor binds the true tail. Either layer refusing is fail-closed:
    with pytest.raises(JournalIntegrityError):
        ForwardJournal.open(path, prereg=prereg)


def test_anchor_tampering_detected(tmp_path, prereg, fixture_events):
    state = tmp_path / "state"
    _run("state", tmp_path, prereg, fixture_events)
    anchor_path = state / ANCHOR_NAME
    anchor = json.loads(anchor_path.read_text(encoding="utf-8"))
    anchor["tail_digest"] = "f" * 64
    anchor_path.write_text(json.dumps(anchor, sort_keys=True), encoding="utf-8")
    with pytest.raises(JournalIntegrityError):
        ForwardJournal.open(state / "journal.jsonl", prereg=prereg)


def test_shorter_journal_than_anchor_refused(tmp_path, prereg, fixture_events):
    state = tmp_path / "state"
    _run("state", tmp_path, prereg, fixture_events)
    path = state / "journal.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join(lines[:-2]) + "\n", encoding="utf-8")
    _open_refuses(path)
