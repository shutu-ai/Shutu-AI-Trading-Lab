"""Single-writer session lease lock: held lock refuses startup; expired
leases allow audited takeover; dual processes conflict (task S1/S3)."""

from __future__ import annotations

import subprocess
import sys
import textwrap
import time

import pytest

from apps.trading_daemon.session import LockHeldError, SessionLock


def test_acquire_release_roundtrip(tmp_path):
    lock = SessionLock(tmp_path / "session.lock", lease_seconds=60)
    lock.acquire()
    assert lock.path.exists()
    lock.release()
    assert not lock.path.exists()


def test_second_acquire_while_held_refused(tmp_path):
    first = SessionLock(tmp_path / "session.lock", lease_seconds=60)
    first.acquire()
    second = SessionLock(tmp_path / "session.lock", lease_seconds=60)
    with pytest.raises(LockHeldError):
        second.acquire()
    first.release()


def test_expired_lease_allows_audited_takeover(tmp_path):
    facts: list[dict] = []
    first = SessionLock(tmp_path / "session.lock", lease_seconds=60)
    first.acquire()
    # deterministically simulate the lease elapsing (equivalent to
    # waiting; no real-time sleep)
    import json as _json
    from datetime import datetime as _dtm
    record = _json.loads(
        (tmp_path / "session.lock").read_text(encoding="utf-8"))
    record["expires_at"] = "2020-01-01T00:00:00+00:00"
    (tmp_path / "session.lock").write_text(
        _json.dumps(record, sort_keys=True), encoding="utf-8")
    second = SessionLock(tmp_path / "session.lock", lease_seconds=60)
    second.acquire(on_takeover=facts.append)
    assert facts and facts[0]["stale_owner_instance_id"] == \
        first.owner_instance_id
    assert facts[0]["reason"] == "STALE_LEASE_TAKEOVER"
    second.release()


def test_dual_process_conflict(tmp_path):
    """A live foreign holder refuses the second writer — real subprocess,
    no mocks (task S3 双进程写者冲突)."""
    from pathlib import Path as _P
    repo_root = str(_P(__file__).resolve().parents[2])
    worker = textwrap.dedent("""
        import sys, time
        sys.path.insert(0, r"{root}")
        sys.path.insert(0, r"{root}" + "\\src")
        from apps.trading_daemon.session import SessionLock
        lock = SessionLock(r"{lockpath}", lease_seconds=60)
        lock.acquire()
        print("HELD", flush=True)
        time.sleep(30)
        lock.release()
    """).format(root=repo_root, lockpath=str(tmp_path / "session.lock"))
    proc = subprocess.Popen(
        [sys.executable, "-c", worker], stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, cwd=str(tmp_path))
    try:
        assert proc.stdout is not None
        line = proc.stdout.readline().strip()
        assert line == "HELD", proc.stderr.read() if proc.stderr else ""
        second = SessionLock(tmp_path / "session.lock", lease_seconds=60)
        with pytest.raises(LockHeldError):
            second.acquire()
    finally:
        proc.kill()
        proc.wait(timeout=10)
