"""CLI discipline: synthetic-replay is the only mode; anything else is
refused before any state is touched."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _run_cli(args, cwd=REPO_ROOT):
    return subprocess.run(
        [sys.executable, "-m", "apps.trading_daemon", *args],
        capture_output=True, text=True, cwd=str(cwd), timeout=300,
        env=None)


def test_cli_without_mode_refused():
    proc = _run_cli(["--state-dir", "unused-state"])
    assert proc.returncode == 2
    assert "synthetic-replay" in proc.stderr.lower()


def test_cli_real_modes_refused(tmp_path):
    for mode in ("shadow-real", "paper", "live", "real-observation"):
        proc = _run_cli(["--mode", mode, "--state-dir", str(tmp_path)])
        assert proc.returncode == 2, mode
        assert "synthetic-replay" in (proc.stderr + proc.stdout).lower()
        assert not (tmp_path / "journal.jsonl").exists()


def test_cli_synthetic_replay_end_to_end(tmp_path):
    state = tmp_path / "state"
    proc = _run_cli(["--mode", "synthetic-replay",
                     "--state-dir", str(state)])
    assert proc.returncode == 0, proc.stderr
    report = json.loads(proc.stdout.strip())
    assert report["mode"] == "SYNTHETIC_REPLAY"
    assert report["no_broker_writes"] is True
    assert report["counters"]["scored"]["total"] == 25
