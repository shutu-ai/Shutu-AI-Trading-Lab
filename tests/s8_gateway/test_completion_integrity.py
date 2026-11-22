"""T7 completion integrity — fail-closed contract tests (RED first).

Task ``M35-S8-T7-COMPLETION-INTEGRITY-AND-OPERATOR-PREFLIGHT-R1-20261122``:

- P0-A: a failed ``WINDOW_COMPLETED`` receipt persistence must never leave
  a success-form evaluation snapshot behind, must never reach the
  committed evidence set, and ``collect --complete`` must not exit 0.
- P0-B: ``status`` must fail closed (documented non-zero, distinguishable,
  stable exit codes) when the persisted completion evidence fails
  verification — digest mismatch, protocol mismatch, an unbound snapshot,
  a chain-committed completion without its snapshot, non-idempotent
  duplicate completions, or corrupted chains.
- Completion is a terminal, idempotent state machine over the receipt
  chain: re-completion with unchanged facts repairs the snapshot without
  a second receipt; re-completion after the window drifted is refused;
  crash recovery across process boundaries never mints a fake COMPLETE
  nor a duplicate completion receipt.

EVERY window below is SIMULATED_REAL_SHAPE_TEST_ONLY: fixture events
driven through the real pipeline inside ``tmp_path``. They never touch
the committed evidence set, never open a network connection, and never
read credential values. Exit-code contract (documented in the runner):
0 OK / 1 FAILURE / 3 BLOCKED_ENV / 4 AUTHORIZATION_REFUSED /
5 LEGACY_CONTRACT / 6 INTEGRITY_FAILURE / 7 COMPLETION_INCOMPLETE.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from apps.market_gateway.feed_session import (  # noqa: E402
    FORWARD_STATE_SUBDIR,
    run_collection_cycle,
    window_facts_from_journal,
)
from apps.market_gateway.offline_fixtures import (  # noqa: E402
    build_selftest_feed,
    load_fixture_table,
)
from apps.trading_daemon.journal import read_entries  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
RUNNER = str(REPO / "scripts" / "run_m35_s8_shadow_real.py")
CONFIG_V2 = REPO / "configs" / "forward_observation_s8_real_v2.yaml"
FIXTURE_V2 = REPO / "apps" / "market_gateway" / "fixtures" / \
    "selftest_daily_bars_v2.json"

# T7 exit-code contract (stable, distinguishable; documented in the
# runner and in artifacts/evidence/M3.5/s8-contract-r2/verification.log)
EXIT_INTEGRITY_FAILURE = 6
EXIT_COMPLETION_INCOMPLETE = 7

SNAPSHOT_NAME = "forward-window-evaluation.json"
RECEIPTS_NAME = "receipts.jsonl"


# ---------------------------------------------------------------------------
# simulated window assembly (fixture data only, tmp_path only)
# ---------------------------------------------------------------------------

def _simulated_window(state: Path, ranged_prereg, s8_identity, *,
                      cycles: int = 6, disconnect_cycle: int | None = 0,
                      redeliver: bool = True) -> Path:
    """Drive a SIMULATED window through the real pipeline (same shape as
    the persistence tests): 5 full-coverage fixture days + one scripted
    transport-disconnect episode with recovery + one audited redelivery.
    Returns the state dir; facts are computed from its chains."""
    fixture = load_fixture_table(FIXTURE_V2)
    feed, client, clock = build_selftest_feed(
        prereg=ranged_prereg, fixture=fixture, identity=s8_identity)
    state.mkdir(parents=True, exist_ok=True)
    for index in range(cycles):
        if disconnect_cycle is not None and index == disconnect_cycle:
            fixture_d = load_fixture_table(FIXTURE_V2)
            from apps.market_gateway.offline_fixtures import (
                ScriptedBarsClient,
            )
            transport = ranged_prereg.transport_config
            failing = ScriptedBarsClient(
                allowed_hosts=list(transport.get("allowed_hosts") or ()),
                allowed_paths=list(transport.get("allowed_paths") or ()),
                cycles=fixture_d["cycles"],
                fail_hosts=set(transport.get("allowed_hosts") or ()),
            )
            failing.cycle_index = index
            clock.sync_with(failing)
            from apps.market_gateway.alpaca_feed import AlpacaIexDailyBarFeed
            feed_f = AlpacaIexDailyBarFeed(
                client=failing.client, prereg=ranged_prereg, now_fn=clock,
                code_identity=None,
                credential_reader=lambda name: "OFFLINE-SIMULATED")
            run_collection_cycle(feed=feed_f, prereg=ranged_prereg,
                                 state_dir=state, identity=s8_identity,
                                 session_index=index + 1)
            client.set_cycle(index + 1)
            clock.sync_with(client)
            continue
        run_collection_cycle(feed=feed, prereg=ranged_prereg,
                             state_dir=state, identity=s8_identity,
                             session_index=index + 1)
        client.advance_cycle()
        clock.sync_with(client)
    if redeliver:
        client.set_cycle(cycles - 1)
        clock.sync_with(client)
        run_collection_cycle(feed=feed, prereg=ranged_prereg,
                             state_dir=state, identity=s8_identity,
                             session_index=cycles + 1)
    return state


def _completion_records(state: Path) -> list[dict]:
    entries = read_entries(state / RECEIPTS_NAME)
    return [e["payload"] for e in entries
            if e["payload"].get("event_type") == "WINDOW_COMPLETED"]


def _run_status(state: Path) -> subprocess.CompletedProcess:
    """The real CLI ``status`` subcommand against a simulated state dir."""
    import os as _os
    env = dict(_os.environ)
    env.pop("S8_OPERATOR_AUTHORIZATION", None)
    return subprocess.run(
        [sys.executable, RUNNER, "status",
         "--state-dir", str(state),
         "--config", str(CONFIG_V2)],
        capture_output=True, text=True, timeout=300,
        cwd=str(REPO), env=env)


def _last_json(stdout: str) -> dict:
    lines = stdout.strip().splitlines()
    start = max(i for i, line in enumerate(lines) if line.startswith("{"))
    return json.loads("\n".join(lines[start:]))


_CRASH_CHILD = """import os, sys
repo = sys.argv[3]
sys.path.insert(0, repo)
sys.path.insert(0, repo + "/src")
mode, state = sys.argv[1], sys.argv[2]
from apps.market_gateway.prereg_real import PreregistrationReal
from apps.trading_daemon.identity import build_s8_forward_identity
from scripts.run_m35_s8_shadow_real import _complete_window
prereg = PreregistrationReal.load(
    repo + "/configs/forward_observation_s8_real_v2.yaml")
ident = build_s8_forward_identity(repo)
if mode == "crash_before_receipt":
    import apps.market_gateway.feed_session as fs
    def _boom(*a, **k):
        os._exit(9)
    fs.append_receipts = _boom
elif mode == "crash_after_receipt":
    from trading_lab.security.audit import AuditLog
    _orig = AuditLog.append
    def _patched(self, event_type, payload):
        rec = _orig(self, event_type, payload)
        if isinstance(payload, dict) and \\
                payload.get("event_type") == "WINDOW_COMPLETED":
            sys.stdout.flush()
            os._exit(9)   # hard death AFTER the receipt chain commit
        return rec
    AuditLog.append = _patched
summary = _complete_window(state, prereg, ident)
print("COMPLETION:", summary.get("completion", "<none>"))
"""


def _run_child(state: Path, mode: str, tmp_path: Path) -> subprocess.CompletedProcess:
    script = tmp_path / "crash_child.py"
    script.write_text(_CRASH_CHILD, encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(script), mode, str(state), str(REPO)],
        capture_output=True, text=True, timeout=300, cwd=str(REPO))


def _write_snapshot(state: Path, ranged_prereg, *, facts_digest: str,
                    protocol_hash: str) -> None:
    """Hand-write a plausible evaluation snapshot (used to simulate the
    P0-A artifact: a snapshot with NO committed completion receipt)."""
    facts = window_facts_from_journal(state, ranged_prereg,
                                      events_synthetic=False)
    payload = {
        "schema": "s8-forward-window-evaluation-v1",
        "facts_digest": facts_digest,
        "facts": facts,
        "eligibility": {"eligibility": "OFFLINE_HARNESS_PASS_WITH_SCOPE",
                        "forward_window_status": "ACCUMULATING"},
        "claim_attempt": None,
        "claim_error": None,
        "protocol_hash": protocol_hash,
    }
    (state / SNAPSHOT_NAME).write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8")


# ---------------------------------------------------------------------------
# legal query states — availability must survive the integrity fixes
# ---------------------------------------------------------------------------

def test_status_empty_state_stays_legal_exit_zero(tmp_path):
    proc = _run_status(tmp_path / "empty")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    payload = _last_json(proc.stdout)
    assert payload["eligibility"]["forward_window_status"] == "NOT_STARTED"
    assert payload["completion_state"] == "NOT_STARTED"


def test_status_in_progress_intact_chains_stays_legal_exit_zero(
        tmp_path, ranged_prereg, s8_identity):
    """A window that never completed (no WINDOW_COMPLETED, no snapshot)
    is an in-progress query, NOT an integrity failure."""
    state = _simulated_window(tmp_path / "state", ranged_prereg,
                              s8_identity)
    assert not (state / SNAPSHOT_NAME).exists()
    proc = _run_status(state)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    payload = _last_json(proc.stdout)
    assert payload["completion_state"] == "NOT_COMPLETED"
    assert payload["facts"]["trading_days_observed"] == 5


# ---------------------------------------------------------------------------
# P0-A: receipt persistence failure must not leave success evidence
# ---------------------------------------------------------------------------

def test_receipt_write_failure_leaves_no_success_snapshot(
        tmp_path, ranged_prereg, s8_identity, monkeypatch):
    """Inject an audit-sink write failure at the WINDOW_COMPLETED append:
    the un-fixed path still wrote a success-form snapshot. Desired: the
    failure is reported, NO snapshot file exists, and no evidence copy is
    written into the committed evidence set."""
    import apps.market_gateway.feed_session as fs
    from scripts.run_m35_s8_shadow_real import EVIDENCE_DIR
    state = _simulated_window(tmp_path / "state", ranged_prereg,
                              s8_identity)

    real_append = fs.append_receipts

    def failing_append(state_dir, records, environment):
        for record in records:
            if record.get("event_type") == "WINDOW_COMPLETED":
                raise OSError("injected audit sink failure (T7 fault)")
        return real_append(state_dir, records, environment=environment)

    monkeypatch.setattr(fs, "append_receipts", failing_append)
    from scripts.run_m35_s8_shadow_real import _complete_window
    payload = _complete_window(state, ranged_prereg, s8_identity)

    assert payload["completion"] == "RECEIPT_WRITE_FAILED"
    assert str(payload.get("window_completed_receipt", "")).startswith(
        "FAILED:"), "diagnostic must be retained"
    assert not (state / SNAPSHOT_NAME).exists(), (
        "P0-A: a completion whose receipt never persisted must not leave "
        "a success-form evaluation snapshot")
    assert not (EVIDENCE_DIR / "real-forward-window-status.json").exists()
    assert _completion_records(state) == []


def test_collect_complete_returns_nonzero_on_receipt_failure(
        tmp_path, ranged_prereg, s8_identity, monkeypatch, capsys):
    """cmd_collect --complete must not return EXIT_OK when the completion
    receipt failed to persist (P0-A: it returned 0). Feed and gates are
    simulated; no network path is exercised."""
    import types
    import scripts.run_m35_s8_shadow_real as runner
    import apps.market_gateway.feed_session as fs
    import apps.market_gateway.alpaca_feed as af

    state = _simulated_window(tmp_path / "state", ranged_prereg,
                              s8_identity)

    gate = types.SimpleNamespace(status="READY", reason="",
                                 credential_env_visible=[])
    monkeypatch.setattr(runner, "preflight",
                        lambda operator_authorization=None: gate)

    def dummy_collect_once(self):
        return types.SimpleNamespace(
            receipts=[], quality_rejects=[], transport_errors=[],
            events=[], status="MARKET_CLOSED", session_date=None)

    monkeypatch.setattr(af.AlpacaIexDailyBarFeed, "collect_once",
                        dummy_collect_once)

    real_append = fs.append_receipts

    def failing_append(state_dir, records, environment):
        for record in records:
            if record.get("event_type") == "WINDOW_COMPLETED":
                raise OSError("injected audit sink failure (T7 fault)")
        return real_append(state_dir, records, environment=environment)

    monkeypatch.setattr(fs, "append_receipts", failing_append)

    code = runner.cmd_collect(state, once=True, complete=True,
                              config_path=CONFIG_V2)
    out = capsys.readouterr().out
    assert code == EXIT_COMPLETION_INCOMPLETE, (
        f"P0-A: collect --complete returned {code} after a failed "
        "completion receipt persistence")
    payload = _last_json(out)["window_completion"]
    assert payload["completion"] == "RECEIPT_WRITE_FAILED"
    assert not (state / SNAPSHOT_NAME).exists()


def test_receipt_failure_with_evidence_dir_writes_no_evidence_copy(
        tmp_path, ranged_prereg, s8_identity, monkeypatch):
    """Even on the operator-shaped path (evidence_dir passed), a failed
    receipt persistence must not produce committed evidence files."""
    import apps.market_gateway.feed_session as fs
    evidence_dir = tmp_path / "evidence-operator"
    state = _simulated_window(tmp_path / "state", ranged_prereg,
                              s8_identity)
    real_append = fs.append_receipts

    def failing_append(state_dir, records, environment):
        for record in records:
            if record.get("event_type") == "WINDOW_COMPLETED":
                raise OSError("injected audit sink failure (T7 fault)")
        return real_append(state_dir, records, environment=environment)

    monkeypatch.setattr(fs, "append_receipts", failing_append)
    from scripts.run_m35_s8_shadow_real import _complete_window
    payload = _complete_window(state, ranged_prereg, s8_identity,
                               evidence_dir=evidence_dir)
    assert payload["completion"] == "RECEIPT_WRITE_FAILED"
    assert not evidence_dir.exists(), (
        "a failed completion must never write evidence files")
    assert "evidence_copy" not in payload


# ---------------------------------------------------------------------------
# P0-A: completion is a terminal, idempotent, crash-recoverable machine
# ---------------------------------------------------------------------------

def test_recompletion_with_unchanged_facts_is_idempotent(
        tmp_path, ranged_prereg, s8_identity):
    """Re-running completion on unchanged chains must NOT append a second
    WINDOW_COMPLETED receipt (P0-A family: unguarded duplicates)."""
    from scripts.run_m35_s8_shadow_real import _complete_window
    state = _simulated_window(tmp_path / "state", ranged_prereg,
                              s8_identity)
    first = _complete_window(state, ranged_prereg, s8_identity)
    assert first["completion"] == "COMPLETE_VERIFIED"
    snapshot_bytes = (state / SNAPSHOT_NAME).read_bytes()
    second = _complete_window(state, ranged_prereg, s8_identity)
    assert second["completion"] == "COMPLETE_VERIFIED"
    records = _completion_records(state)
    assert len(records) == 1, (
        f"idempotent re-completion appended a duplicate receipt "
        f"({len(records)} WINDOW_COMPLETED records)")
    assert (state / SNAPSHOT_NAME).read_bytes() == snapshot_bytes


def test_recompletion_after_window_drift_is_refused(
        tmp_path, ranged_prereg, s8_identity):
    """Once the completion receipt is committed, the window is closed.
    New chain events change the facts — a re-completion attempt must be
    REFUSED: no second receipt, no snapshot overwrite, no journal
    mutation by the refusal path."""
    from scripts.run_m35_s8_shadow_real import _complete_window
    fixture = load_fixture_table(FIXTURE_V2)
    state = _simulated_window(tmp_path / "state", ranged_prereg,
                              s8_identity)
    first = _complete_window(state, ranged_prereg, s8_identity)
    assert first["completion"] == "COMPLETE_VERIFIED"
    digest_committed = first["facts_digest"]
    snapshot_bytes = (state / SNAPSHOT_NAME).read_bytes()

    # drift the chains: re-deliver an already-consumed cycle -> audited
    # DUPLICATE entries change the facts
    feed, client, clock = build_selftest_feed(
        prereg=ranged_prereg, fixture=fixture, identity=s8_identity)
    client.set_cycle(1)
    clock.sync_with(client)
    run_collection_cycle(feed=feed, prereg=ranged_prereg, state_dir=state,
                         identity=s8_identity, session_index=99)
    # baseline for the refusal: AFTER the drift, BEFORE the attempted
    # re-completion (the refusal itself must mutate nothing)
    journal_bytes = (state / FORWARD_STATE_SUBDIR / "journal.jsonl") \
        .read_bytes()

    second = _complete_window(state, ranged_prereg, s8_identity)
    assert second["completion"] == "REFUSED_ALREADY_COMPLETED", (
        f"completion after window drift must be refused, got "
        f"{second.get('completion')!r}")
    assert len(_completion_records(state)) == 1
    assert (state / SNAPSHOT_NAME).read_bytes() == snapshot_bytes
    assert (state / FORWARD_STATE_SUBDIR / "journal.jsonl") \
        .read_bytes() == journal_bytes, \
        "the refusal path must not mutate the journal"
    assert second["facts_digest"] != digest_committed


def test_snapshot_write_failure_is_reported_and_recoverable(
        tmp_path, ranged_prereg, s8_identity, monkeypatch):
    """Crash point: receipt committed, snapshot write fails (injected by
    blocking the snapshot path with a directory — a fault that works on
    Windows and POSIX alike). Desired: SNAPSHOT_WRITE_FAILED report with
    no fake COMPLETE; a later re-completion repairs the snapshot WITHOUT
    duplicating the receipt."""
    from scripts.run_m35_s8_shadow_real import _complete_window
    state = _simulated_window(tmp_path / "state", ranged_prereg,
                              s8_identity)
    blocker = state / SNAPSHOT_NAME
    blocker.mkdir()          # snapshot path is now unwritable as a file

    payload = _complete_window(state, ranged_prereg, s8_identity)
    assert payload["completion"] == "SNAPSHOT_WRITE_FAILED"
    assert _completion_records(state), (
        "the receipt commit precedes the snapshot write; the chain must "
        "carry the committed completion")

    blocker.rmdir()          # unblock; fresh re-completion repairs
    repair = _complete_window(state, ranged_prereg, s8_identity)
    assert repair["completion"] == "COMPLETE_VERIFIED"
    assert len(_completion_records(state)) == 1, \
        "crash recovery must never append a duplicate completion receipt"
    assert (state / SNAPSHOT_NAME).is_file()


# ---------------------------------------------------------------------------
# cross-process crash recovery (os._exit in a fresh child process)
# ---------------------------------------------------------------------------

def test_crash_before_receipt_then_repair_across_processes(
        tmp_path, ranged_prereg, s8_identity):
    """Fault point 'before receipt write': the child dies after closing
    the session but before any completion commit. Nothing may look
    completed; a fresh repair run completes exactly once."""
    state = _simulated_window(tmp_path / "state", ranged_prereg,
                              s8_identity)
    child = _run_child(state, "crash_before_receipt", tmp_path)
    assert child.returncode == 9, child.stdout + child.stderr  # hard death
    assert _completion_records(state) == []
    assert not (state / SNAPSHOT_NAME).exists()
    proc = _run_status(state)
    assert proc.returncode == 0
    assert _last_json(proc.stdout)["completion_state"] == "NOT_COMPLETED"

    repair = _run_child(state, "normal", tmp_path)
    assert repair.returncode == 0, repair.stdout + repair.stderr
    assert "COMPLETE_VERIFIED" in repair.stdout
    assert len(_completion_records(state)) == 1
    proc = _run_status(state)
    assert proc.returncode == 0
    assert _last_json(proc.stdout)["completion_state"] == "COMPLETE_VERIFIED"


def test_crash_after_receipt_no_fake_complete_then_repair(
        tmp_path, ranged_prereg, s8_identity):
    """Fault point 'after receipt commit, before snapshot': a fresh
    status MUST NOT report success (exit 0 with nothing completed was
    the P0-B family defect); it must report the recoverable incomplete
    state. A fresh repair run must write the snapshot without a second
    receipt."""
    state = _simulated_window(tmp_path / "state", ranged_prereg,
                              s8_identity)
    child = _run_child(state, "crash_after_receipt", tmp_path)
    assert child.returncode == 9, child.stdout + child.stderr
    records = _completion_records(state)
    assert len(records) == 1, "the receipt itself must be committed"
    assert not (state / SNAPSHOT_NAME).exists()

    proc = _run_status(state)
    payload = _last_json(proc.stdout)
    assert proc.returncode == EXIT_COMPLETION_INCOMPLETE, (
        f"chain-committed completion with missing snapshot exited "
        f"{proc.returncode}: completion evidence is incomplete")
    assert payload["completion_state"] == "CHAIN_COMMITTED_SNAPSHOT_MISSING"

    repair = _run_child(state, "normal", tmp_path)
    assert repair.returncode == 0, repair.stdout + repair.stderr
    assert "COMPLETE_VERIFIED" in repair.stdout
    assert len(_completion_records(state)) == 1, \
        "repair must not duplicate the committed completion receipt"
    assert (state / SNAPSHOT_NAME).is_file()
    proc = _run_status(state)
    assert proc.returncode == 0
    assert _last_json(proc.stdout)["completion_state"] == "COMPLETE_VERIFIED"


# ---------------------------------------------------------------------------
# P0-B: status integrity failures must fail closed with stable codes
# ---------------------------------------------------------------------------

def test_status_detects_tampered_snapshot_digest(
        tmp_path, ranged_prereg, s8_identity):
    from scripts.run_m35_s8_shadow_real import _complete_window
    state = _simulated_window(tmp_path / "state", ranged_prereg,
                              s8_identity)
    _complete_window(state, ranged_prereg, s8_identity)
    snapshot = json.loads((state / SNAPSHOT_NAME).read_text(encoding="utf-8"))
    snapshot["facts_digest"] = "9" * 64
    (state / SNAPSHOT_NAME).write_text(json.dumps(snapshot),
                                       encoding="utf-8")
    proc = _run_status(state)
    payload = _last_json(proc.stdout)
    assert proc.returncode == EXIT_INTEGRITY_FAILURE, (
        f"P0-B: tampered snapshot digest exited {proc.returncode}")
    assert payload["completion_state"] == "INTEGRITY_FAILURE"
    assert "DIGEST_MISMATCH" in payload["completion_problems"]


def test_status_detects_snapshot_protocol_mismatch(
        tmp_path, ranged_prereg, s8_identity):
    from scripts.run_m35_s8_shadow_real import _complete_window
    state = _simulated_window(tmp_path / "state", ranged_prereg,
                              s8_identity)
    _complete_window(state, ranged_prereg, s8_identity)
    snapshot = json.loads((state / SNAPSHOT_NAME).read_text(encoding="utf-8"))
    snapshot["protocol_hash"] = "0" * 64
    (state / SNAPSHOT_NAME).write_text(json.dumps(snapshot),
                                       encoding="utf-8")
    proc = _run_status(state)
    payload = _last_json(proc.stdout)
    assert proc.returncode == EXIT_INTEGRITY_FAILURE
    assert "PROTOCOL_MISMATCH" in payload["completion_problems"]


def test_status_refuses_unbound_snapshot_without_completion_receipt(
        tmp_path, ranged_prereg, s8_identity):
    """The P0-A artifact: a plausible snapshot whose digest matches the
    recomputed facts but with NO committed WINDOW_COMPLETED record in the
    receipt chain. Digest equality alone must never count as COMPLETE —
    the snapshot must be bound to a committed chain record."""
    from trading_lab.security.canonical import canonical_digest
    state = _simulated_window(tmp_path / "state", ranged_prereg,
                              s8_identity)
    facts = window_facts_from_journal(state, ranged_prereg,
                                      events_synthetic=False)
    _write_snapshot(state, ranged_prereg,
                    facts_digest=canonical_digest(facts),
                    protocol_hash=ranged_prereg.hash)
    proc = _run_status(state)
    payload = _last_json(proc.stdout)
    assert proc.returncode == EXIT_INTEGRITY_FAILURE, (
        f"P0-B: unbound snapshot (digest_match=true, no committed "
        f"completion record) exited {proc.returncode}")
    assert payload["completion_state"] == "INTEGRITY_FAILURE"
    assert "UNBOUND_SNAPSHOT" in payload["completion_problems"]


def test_status_reports_chain_committed_completion_without_snapshot(
        tmp_path, ranged_prereg, s8_identity):
    from scripts.run_m35_s8_shadow_real import _complete_window
    state = _simulated_window(tmp_path / "state", ranged_prereg,
                              s8_identity)
    _complete_window(state, ranged_prereg, s8_identity)
    (state / SNAPSHOT_NAME).unlink()
    proc = _run_status(state)
    payload = _last_json(proc.stdout)
    assert proc.returncode == EXIT_COMPLETION_INCOMPLETE
    assert payload["completion_state"] == "CHAIN_COMMITTED_SNAPSHOT_MISSING"


def test_status_detects_conflicting_duplicate_completions(
        tmp_path, ranged_prereg, s8_identity):
    """Two WINDOW_COMPLETED records under one protocol with different
    fact digests violate the terminal/idempotent completion semantics."""
    from scripts.run_m35_s8_shadow_real import _complete_window
    from apps.market_gateway.feed_session import append_receipts
    state = _simulated_window(tmp_path / "state", ranged_prereg,
                              s8_identity)
    _complete_window(state, ranged_prereg, s8_identity)
    append_receipts(state, [{
        "event_type": "WINDOW_COMPLETED",
        "facts_digest": "1" * 64,
        "eligibility": "PASS",
        "forward_window_status": "COMPLETE",
        "trading_days_observed": 5,
        "protocol_hash": ranged_prereg.hash,
        "environment": ranged_prereg.environment,
        "received_at": "2026-11-22T00:00:00+00:00",
        "receipt_schema": "s8-receipts-v2",
    }], environment=ranged_prereg.environment)
    proc = _run_status(state)
    payload = _last_json(proc.stdout)
    assert proc.returncode == EXIT_INTEGRITY_FAILURE
    assert "CONFLICTING_COMPLETIONS" in payload["completion_problems"]


def test_status_detects_identical_duplicate_completions(
        tmp_path, ranged_prereg, s8_identity):
    """Even byte-identical duplicate completion receipts violate the
    idempotent writer contract — the fixed writer never emits them."""
    from scripts.run_m35_s8_shadow_real import _complete_window
    from apps.market_gateway.feed_session import append_receipts
    state = _simulated_window(tmp_path / "state", ranged_prereg,
                              s8_identity)
    _complete_window(state, ranged_prereg, s8_identity)
    records = _completion_records(state)
    assert len(records) == 1
    clone = dict(records[0])
    append_receipts(state, [clone],
                    environment=ranged_prereg.environment)
    proc = _run_status(state)
    payload = _last_json(proc.stdout)
    assert proc.returncode == EXIT_INTEGRITY_FAILURE
    assert "DUPLICATE_COMPLETION" in payload["completion_problems"]


def test_status_detects_corrupt_receipt_chain(
        tmp_path, ranged_prereg, s8_identity):
    from scripts.run_m35_s8_shadow_real import _complete_window
    state = _simulated_window(tmp_path / "state", ranged_prereg,
                              s8_identity)
    _complete_window(state, ranged_prereg, s8_identity)
    receipt_path = state / RECEIPTS_NAME
    lines = receipt_path.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[0])
    record["payload"]["payload_digest"] = "1" * 64
    lines[0] = json.dumps(record, sort_keys=True)
    receipt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    proc = _run_status(state)
    payload = _last_json(proc.stdout)
    assert proc.returncode == EXIT_INTEGRITY_FAILURE, (
        f"P0-B: corrupt receipt chain exited {proc.returncode}")
    assert payload["completion_state"] == "INTEGRITY_FAILURE"
    assert "RECEIPT_CHAIN_CORRUPT" in payload["completion_problems"]


def test_status_detects_corrupt_journal(
        tmp_path, ranged_prereg, s8_identity):
    from scripts.run_m35_s8_shadow_real import _complete_window
    state = _simulated_window(tmp_path / "state", ranged_prereg,
                              s8_identity)
    _complete_window(state, ranged_prereg, s8_identity)
    journal_path = state / FORWARD_STATE_SUBDIR / "journal.jsonl"
    lines = journal_path.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[0])
    record["payload"]["protocol_hash"] = "f" * 64
    lines[0] = json.dumps(record, sort_keys=True)
    journal_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    proc = _run_status(state)
    payload = _last_json(proc.stdout)
    assert proc.returncode == EXIT_INTEGRITY_FAILURE
    assert payload["completion_state"] == "INTEGRITY_FAILURE"
    assert "JOURNAL_CORRUPT" in payload["completion_problems"]
