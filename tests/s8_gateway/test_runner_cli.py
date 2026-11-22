"""S8 runner CLI — honest exit codes and honest states.

- check-config: 0 with frozen facts;
- selftest: 0 offline (OFFLINE_HARNESS_PASS_WITH_SCOPE), fixture facts,
  claims refused; --no-evidence keeps the repo clean in tests;
- collect without credentials: exit 3 (BLOCKED_ENV), no network attempt;
- collect with a wrong operator token: exit 4 (AUTHORIZATION_REFUSED);
- status: honest NOT_STARTED on an empty state dir."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER = str(REPO_ROOT / "scripts" / "run_m35_s8_shadow_real.py")


def _run(args, env_extra=None):
    import os
    env = dict(os.environ)
    env.pop("S8_OPERATOR_AUTHORIZATION", None)
    env.update(env_extra or {})
    return subprocess.run(
        [sys.executable, RUNNER, *args], capture_output=True,
        text=True, timeout=300, cwd=str(REPO_ROOT), env=env)


def _last_json(stdout: str) -> dict:
    lines = stdout.strip().splitlines()
    start = max(i for i, line in enumerate(lines)
                if line.startswith("{"))
    return json.loads("\n".join(lines[start:]))


def test_check_config_prints_frozen_facts():
    """Default --config is the ranged v2 protocol (contract remediation
    R1): the legacy v2-schema file is pinned evidence and is never the
    silent default."""
    proc = _run(["check-config"])
    assert proc.returncode == 0, proc.stderr
    payload = _last_json(proc.stdout)
    assert payload["protocol_id"] == "m35-s8-real-shadow-readonly-v2"
    assert payload["mode"] == "REAL_SHADOW_READ_ONLY"
    assert payload["symbols"] == ["SPY", "QQQ"]
    assert payload["min_trading_days"] == 5
    assert payload["read_only"] is True
    assert payload["paper_write"] == "NOT_AUTHORIZED"
    assert payload["contract_legacy"] is False
    contract = payload["data_contract"]
    assert contract["bars_endpoint"] == "ranged_daily_bars"
    assert contract["timeframe"] == "1Day"
    assert contract["adjustment"] == "raw"
    assert contract["window_bounds"] == "session_midnight_et_to_received_at"
    assert len(payload["protocol_hash"]) == 64
    assert "2026-11-26" in payload["calendar"]["holidays"]
    assert "2026-11-27" in payload["calendar"]["half_days"]


def test_check_config_on_legacy_file_is_pinned_evidence():
    proc = _run(["check-config", "--config",
                 "configs/forward_observation_s8_real.yaml"])
    assert proc.returncode == 0, proc.stderr
    payload = _last_json(proc.stdout)
    assert payload["protocol_id"] == "m35-s8-real-shadow-readonly-v1"
    assert payload["contract_legacy"] is True
    assert "data_contract" not in payload  # the legacy contract is empty


def test_collect_under_legacy_contract_is_structurally_refused(tmp_path):
    """T3.1: the legacy protocol can never run real collection (exit 5),
    regardless of gates."""
    proc = _run(["collect", "--config",
                 "configs/forward_observation_s8_real.yaml",
                 "--state-dir", str(tmp_path / "state")],
                env_extra={"S8_OPERATOR_AUTHORIZATION":
                           "S8_APPROVAL_20261122",
                           "APCA_API_KEY_ID": "k", "APCA_API_SECRET_KEY": "s"})
    assert proc.returncode == 5, proc.stdout + proc.stderr
    payload = _last_json(proc.stdout)
    assert payload["collect"] == "LEGACY_CONTRACT_INVALID"


def test_selftest_passes_offline_and_refuses_claims(tmp_path):
    proc = _run(["selftest", "--state-dir", str(tmp_path / "state"),
                 "--no-evidence"])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    payload = _last_json(proc.stdout)
    assert payload["outcome"] == "OFFLINE_HARNESS_PASS_WITH_SCOPE"
    assert payload["problems"] == []
    assert payload["events_synthetic"] is True
    dup = payload["duplicate_cycle"]
    assert dup["new_scores"] == 0
    assert dup["engine_duplicates"] >= dup["events_emitted"]
    facts = payload["facts"]
    assert facts["receipt_evidence_ok"] is True
    assert facts["trading_days_observed"] == 6
    for claim, refusal in payload["claim_refusals"].items():
        assert "INTEGRITY FAILURE" not in refusal, f"{claim} was minted"
        assert refusal, f"{claim} did not refuse"
    assert payload["journal_ok"] is True


def test_selftest_is_reproducible(tmp_path):
    """Same inputs -> same logical outcomes (counters + facts), independent
    runs; evidence digests may differ, the contract facts may not."""
    outs = []
    for run in range(2):
        proc = _run(["selftest", "--state-dir",
                     str(tmp_path / f"state-{run}"), "--no-evidence"])
        assert proc.returncode == 0, proc.stderr
        payload = _last_json(proc.stdout)
        outs.append({
            "days": payload["facts"]["trading_days_observed"],
            "scored": payload["facts"]["scored"],
            "eligibility": payload["eligibility"]["eligibility"],
            "problems": payload["problems"],
        })
    assert outs[0] == outs[1]


def test_collect_without_token_is_authorization_refused(tmp_path):
    """Gate order: the signed-approval token comes FIRST — without it the
    runner refuses before even considering credentials (exit 4)."""
    proc = _run(["collect", "--state-dir", str(tmp_path / "state")])
    assert proc.returncode == 4, proc.stdout + proc.stderr
    payload = _last_json(proc.stdout)
    assert payload["collect"] == "AUTHORIZATION_REFUSED"
    # the state dir was never created with a journal: no cycle ran
    assert not (tmp_path / "state" / "forward" / "journal.jsonl").exists()


def test_collect_with_token_but_no_credentials_is_blocked_env(tmp_path):
    """The honest BLOCKED_ENV path: operator token present but no legal
    data access configured -> exit 3, no real connection attempted."""
    from apps.market_gateway.feed_session import (
        OPERATOR_AUTHORIZATION_TOKEN)
    proc = _run(
        ["collect", "--state-dir", str(tmp_path / "state")],
        env_extra={"S8_OPERATOR_AUTHORIZATION": OPERATOR_AUTHORIZATION_TOKEN})
    assert proc.returncode == 3, proc.stdout + proc.stderr
    payload = _last_json(proc.stdout)
    assert payload["collect"] == "BLOCKED_ENV"
    assert "APCA_API_KEY_ID" in payload["reason"]
    assert not (tmp_path / "state" / "forward" / "journal.jsonl").exists()


def test_collect_with_wrong_operator_token_is_refused(tmp_path):
    proc = _run(["collect", "--state-dir", str(tmp_path / "state")],
                env_extra={"S8_OPERATOR_AUTHORIZATION": "WRONG_TOKEN"})
    assert proc.returncode == 4, proc.stdout + proc.stderr
    payload = _last_json(proc.stdout)
    assert payload["collect"] == "AUTHORIZATION_REFUSED"


def test_status_on_empty_state_is_honest_not_started(tmp_path):
    proc = _run(["status", "--state-dir", str(tmp_path / "empty")])
    assert proc.returncode == 0, proc.stderr
    payload = _last_json(proc.stdout)
    assert payload["eligibility"]["forward_window_status"] == "NOT_STARTED"
    assert payload["facts"]["trading_days_observed"] == 0
    assert payload["facts"]["events_synthetic"] is False
