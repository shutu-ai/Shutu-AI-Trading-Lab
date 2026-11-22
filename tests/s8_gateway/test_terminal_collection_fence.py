"""T8 terminal collection fence + pure-offline completion repair.

Task ``M35-S8-T8-TERMINAL-FENCE-OFFLINE-RECOVERY-AND-CI-BACKFILL-R1-20261122``:

- P1-A: once a ``WINDOW_COMPLETED`` receipt is committed, the ordinary
  collection entries (``collect --once`` and ``collect --complete``) must
  refuse BEFORE any credential read, network client/feed construction, or
  chain write — a completed window must never drift through the
  collection gate, and must never silently succeed.
- P1-B: recovering ``CHAIN_COMMITTED_SNAPSHOT_MISSING`` must be possible
  through a pure-offline ``repair-completion`` subcommand that never
  touches credentials, network, ``collect_once``, ``run_collection_cycle``
  or ``run_replay(complete=True)``; it may only rewrite a MISSING snapshot
  bound to exactly one verifiably committed completion receipt — never
  mint a first completion, never disguise a corrupted chain as
  recoverable, never overwrite a tampered snapshot.

Exit-code contract additions (documented in the runner docstring):
``8`` = TERMINAL_WINDOW (the target window is closed by a committed
completion; ordinary collection refused — use ``repair-completion`` for
offline snapshot repair). ``6`` integrity refusal at the gate, ``7``
recoverable repair-write failure, ``1`` nothing-to-repair refusals.
All previous codes keep their meanings.

EVERY window below is SIMULATED_REAL_SHAPE_TEST_ONLY: fixture events in
``tmp_path``, a sentinel feed that never touches the network, and (where
"nothing may run" is asserted) a sealed ``socket.socket``. No real state
dir, no credentials, no HTTP.
"""

from __future__ import annotations

import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from apps.market_gateway.feed_session import (  # noqa: E402
    FORWARD_STATE_SUBDIR,
    run_collection_cycle,
)
from apps.market_gateway.offline_fixtures import (  # noqa: E402
    build_selftest_feed,
    load_fixture_table,
)
from apps.trading_daemon.journal import read_entries  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
RUNNER = str(REPO / "scripts" / "run_m35_s8_shadow_real.py")
CONFIG_V2 = REPO / "configs" / "forward_observation_s8_real_v2.yaml"
CONFIG_LEGACY = REPO / "configs" / "forward_observation_s8_real.yaml"
FIXTURE_V2 = REPO / "apps" / "market_gateway" / "fixtures" / \
    "selftest_daily_bars_v2.json"

EXIT_FAILURE = 1
EXIT_INTEGRITY_FAILURE = 6
EXIT_COMPLETION_INCOMPLETE = 7
EXIT_TERMINAL_WINDOW = 8

SNAPSHOT_NAME = "forward-window-evaluation.json"
RECEIPTS_NAME = "receipts.jsonl"


# ---------------------------------------------------------------------------
# simulated window + sentinels
# ---------------------------------------------------------------------------

def _simulated_window(state: Path, ranged_prereg, s8_identity, *,
                      cycles: int = 6, disconnect_cycle: int | None = 0,
                      redeliver: bool = True) -> Path:
    """Same shape as the T7 persistence tests: 5 full-coverage fixture
    days + one scripted disconnect episode with recovery + one audited
    redelivery. Fixture data only; tmp_path only."""
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


def _complete(state: Path, ranged_prereg, s8_identity):
    from scripts.run_m35_s8_shadow_real import _complete_window
    payload = _complete_window(state, ranged_prereg, s8_identity)
    assert payload["completion"] == "COMPLETE_VERIFIED"
    return payload


def _window_records(state: Path) -> list[dict]:
    entries = read_entries(state / RECEIPTS_NAME)
    return [e["payload"] for e in entries
            if e["payload"].get("event_type") == "WINDOW_COMPLETED"]


def _journal_bytes(state: Path) -> bytes:
    return (state / FORWARD_STATE_SUBDIR / "journal.jsonl").read_bytes()


def make_feed_sentinel(monkeypatch):
    """A discriminating collect_once(): records the call and returns an
    EMPTY transport answer (never a network byte). Applied AFTER the
    simulated window is built (the builder must drive the real fixture
    feed); the fence must make sure it is never reached for a sealed
    window."""
    import apps.market_gateway.alpaca_feed as af
    calls: list[int] = []

    def sentinel(self):
        calls.append(1)
        return types.SimpleNamespace(
            receipts=[], quality_rejects=[], transport_errors=[],
            events=[], status="MARKET_CLOSED", session_date=None)

    monkeypatch.setattr(af.AlpacaIexDailyBarFeed, "collect_once", sentinel)
    return calls


@pytest.fixture
def sealed_network(monkeypatch):
    """Any real network attempt fails loudly while this fixture is up."""
    import socket

    def _sealed(*args, **kwargs):
        raise AssertionError("network access attempted (socket sealed)")

    monkeypatch.setattr(socket, "socket", _sealed)


@pytest.fixture
def preflight_recorder(monkeypatch):
    """Records whether the credential-visibility gate was even reached."""
    import scripts.run_m35_s8_shadow_real as runner
    calls: list[str] = []
    gate = types.SimpleNamespace(status="READY", reason="",
                                 credential_env_visible=[])

    def recorder(operator_authorization=None):
        calls.append("preflight")
        return gate

    monkeypatch.setattr(runner, "preflight", recorder)
    return calls


def _run_cli(args: list[str]) -> subprocess.CompletedProcess:
    import os as _os
    env = dict(_os.environ)
    env.pop("S8_OPERATOR_AUTHORIZATION", None)
    return subprocess.run(
        [sys.executable, RUNNER, *args],
        capture_output=True, text=True, timeout=300,
        cwd=str(REPO), env=env)


def _last_json(stdout: str) -> dict:
    lines = stdout.strip().splitlines()
    start = max(i for i, line in enumerate(lines) if line.startswith("{"))
    return json.loads("\n".join(lines[start:]))


# ---------------------------------------------------------------------------
# legal-path guards — the fence must never seal a live window
# ---------------------------------------------------------------------------

def test_in_progress_window_collect_path_unchanged(
        tmp_path, ranged_prereg, s8_identity, monkeypatch,
        preflight_recorder):
    state = _simulated_window(tmp_path / "state", ranged_prereg,
                              s8_identity)
    feed_sentinel = make_feed_sentinel(monkeypatch)
    import scripts.run_m35_s8_shadow_real as runner
    code = runner.cmd_collect(state, once=True, complete=False,
                              config_path=CONFIG_V2)
    assert code == 0
    assert feed_sentinel == [1]
    assert preflight_recorder == ["preflight"]
    assert not (state / SNAPSHOT_NAME).exists()


def test_empty_state_collect_still_reaches_cycle(
        tmp_path, ranged_prereg, s8_identity, monkeypatch,
        preflight_recorder):
    state = tmp_path / "fresh"
    feed_sentinel = make_feed_sentinel(monkeypatch)
    import scripts.run_m35_s8_shadow_real as runner
    code = runner.cmd_collect(state, once=True, complete=False,
                              config_path=CONFIG_V2)
    assert code == 0
    assert feed_sentinel == [1]


# ---------------------------------------------------------------------------
# P1-A: the terminal fence
# ---------------------------------------------------------------------------

def test_collect_once_after_completion_refuses_before_credentials_and_writes(
        tmp_path, ranged_prereg, s8_identity, monkeypatch,
        preflight_recorder, sealed_network):
    state = _simulated_window(tmp_path / "state", ranged_prereg,
                              s8_identity)
    _complete(state, ranged_prereg, s8_identity)
    snapshot_bytes = (state / SNAPSHOT_NAME).read_bytes()
    journal_bytes = _journal_bytes(state)
    records_before = len(_window_records(state))

    feed_sentinel = make_feed_sentinel(monkeypatch)
    import scripts.run_m35_s8_shadow_real as runner
    code = runner.cmd_collect(state, once=True, complete=False,
                              config_path=CONFIG_V2)

    assert code == EXIT_TERMINAL_WINDOW, (
        f"sealed window: collect --once exited {code} (must be "
        f"{EXIT_TERMINAL_WINDOW}) — a completed window must never be "
        "silently accepted by the collection gate")
    assert preflight_recorder == [], \
        "the fence must fire before any credential visibility audit"
    assert feed_sentinel == [], \
        "the fence must fire before any feed/network access"
    assert len(_window_records(state)) == records_before == 1
    assert _journal_bytes(state) == journal_bytes, \
        "the refusal must not append sessions to the journal"
    assert (state / SNAPSHOT_NAME).read_bytes() == snapshot_bytes


def test_collect_complete_after_completion_refuses_before_collecting(
        tmp_path, ranged_prereg, s8_identity, monkeypatch,
        preflight_recorder, sealed_network):
    """collect --complete must never become an implicit
    collect-then-repair network path for an already completed window."""
    state = _simulated_window(tmp_path / "state", ranged_prereg,
                              s8_identity)
    _complete(state, ranged_prereg, s8_identity)
    snapshot_bytes = (state / SNAPSHOT_NAME).read_bytes()
    journal_bytes = _journal_bytes(state)

    feed_sentinel = make_feed_sentinel(monkeypatch)
    import scripts.run_m35_s8_shadow_real as runner
    code = runner.cmd_collect(state, once=True, complete=True,
                              config_path=CONFIG_V2)

    assert code == EXIT_TERMINAL_WINDOW
    assert preflight_recorder == []
    assert feed_sentinel == [], "no collection may happen behind the repair"
    assert len(_window_records(state)) == 1, \
        "no second completion receipt"
    assert _journal_bytes(state) == journal_bytes
    assert (state / SNAPSHOT_NAME).read_bytes() == snapshot_bytes, \
        "the fenced refusal must not touch the committed snapshot"


def test_collect_refused_on_corrupt_chain_before_any_access(
        tmp_path, ranged_prereg, s8_identity, monkeypatch,
        preflight_recorder, sealed_network):
    state = _simulated_window(tmp_path / "state", ranged_prereg,
                              s8_identity)
    _complete(state, ranged_prereg, s8_identity)
    receipt_path = state / RECEIPTS_NAME
    lines = receipt_path.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[0])
    record["payload"]["payload_digest"] = "1" * 64
    lines[0] = json.dumps(record, sort_keys=True)
    tampered = "\n".join(lines) + "\n"
    receipt_path.write_text(tampered, encoding="utf-8")
    journal_bytes = _journal_bytes(state)

    feed_sentinel = make_feed_sentinel(monkeypatch)
    import scripts.run_m35_s8_shadow_real as runner
    code = runner.cmd_collect(state, once=True, complete=False,
                              config_path=CONFIG_V2)

    assert code == EXIT_INTEGRITY_FAILURE, (
        f"corrupt receipt chain at the gate exited {code}")
    assert preflight_recorder == []
    assert feed_sentinel == []
    assert receipt_path.read_text(encoding="utf-8") == tampered
    assert _journal_bytes(state) == journal_bytes


def test_repeated_terminal_invocations_are_inert(
        tmp_path, ranged_prereg, s8_identity, monkeypatch,
        preflight_recorder, sealed_network):
    state = _simulated_window(tmp_path / "state", ranged_prereg,
                              s8_identity)
    _complete(state, ranged_prereg, s8_identity)
    snapshot_bytes = (state / SNAPSHOT_NAME).read_bytes()
    journal_bytes = _journal_bytes(state)
    snapshot_digest = json.loads(snapshot_bytes.decode("utf-8"))[
        "facts_digest"]

    feed_sentinel = make_feed_sentinel(monkeypatch)
    import scripts.run_m35_s8_shadow_real as runner
    for _ in range(2):
        assert runner.cmd_collect(state, once=True, complete=False,
                                  config_path=CONFIG_V2) == \
            EXIT_TERMINAL_WINDOW
    assert feed_sentinel == []
    assert len(_window_records(state)) == 1
    assert _journal_bytes(state) == journal_bytes
    assert (state / SNAPSHOT_NAME).read_bytes() == snapshot_bytes
    assert json.loads((state / SNAPSHOT_NAME).read_bytes())[
        "facts_digest"] == snapshot_digest


# ---------------------------------------------------------------------------
# P1-B: pure-offline repair-completion
# ---------------------------------------------------------------------------

def _chain_committed_missing_snapshot(state: Path) -> None:
    (state / SNAPSHOT_NAME).unlink()
    assert len(_window_records(state)) == 1
    assert not (state / SNAPSHOT_NAME).exists()


def test_repair_completion_repairs_missing_snapshot_offline(
        tmp_path, ranged_prereg, s8_identity):
    state = _simulated_window(tmp_path / "state", ranged_prereg,
                              s8_identity)
    _complete(state, ranged_prereg, s8_identity)
    _chain_committed_missing_snapshot(state)
    receipts_before = (state / RECEIPTS_NAME).read_bytes()

    proc = _run_cli(["repair-completion", "--state-dir", str(state),
                     "--config", str(CONFIG_V2)])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    payload = _last_json(proc.stdout)
    assert payload["repair"] == "REPAIRED_SNAPSHOT"
    assert (state / SNAPSHOT_NAME).is_file()
    assert (state / RECEIPTS_NAME).read_bytes() == receipts_before, \
        "offline repair must not append receipts"
    assert len(_window_records(state)) == 1
    status = _run_cli(["status", "--state-dir", str(state),
                       "--config", str(CONFIG_V2)])
    assert status.returncode == 0
    assert _last_json(status.stdout)["completion_state"] == \
        "COMPLETE_VERIFIED"


def test_repair_completion_noop_on_verified_completion(
        tmp_path, ranged_prereg, s8_identity):
    state = _simulated_window(tmp_path / "state", ranged_prereg,
                              s8_identity)
    _complete(state, ranged_prereg, s8_identity)
    snapshot_bytes = (state / SNAPSHOT_NAME).read_bytes()

    proc = _run_cli(["repair-completion", "--state-dir", str(state),
                     "--config", str(CONFIG_V2)])
    assert proc.returncode == 0
    assert _last_json(proc.stdout)["repair"] == "ALREADY_COMPLETE_NOOP"
    assert (state / SNAPSHOT_NAME).read_bytes() == snapshot_bytes, \
        "a verified snapshot must not be rewritten byte-for-byte"


def test_repair_completion_refuses_without_committed_completion(
        tmp_path, ranged_prereg, s8_identity):
    """repair-completion must never 'helpfully complete' a window that
    was never completed — that would mint a first WINDOW_COMPLETED
    outside the controlled operator path."""
    state = _simulated_window(tmp_path / "state", ranged_prereg,
                              s8_identity)
    assert not (state / SNAPSHOT_NAME).exists()
    receipts_before = (state / RECEIPTS_NAME).read_bytes()
    journal_before = _journal_bytes(state)

    proc = _run_cli(["repair-completion", "--state-dir", str(state),
                     "--config", str(CONFIG_V2)])
    assert proc.returncode != 0
    assert _last_json(proc.stdout)["repair"] == "NO_COMMITTED_COMPLETION"
    assert not (state / SNAPSHOT_NAME).exists()
    assert (state / RECEIPTS_NAME).read_bytes() == receipts_before
    assert _journal_bytes(state) == journal_before


def test_repair_completion_refuses_empty_state(
        tmp_path, ranged_prereg, s8_identity):
    proc = _run_cli(["repair-completion", "--state-dir",
                     str(tmp_path / "empty"), "--config", str(CONFIG_V2)])
    assert proc.returncode != 0
    assert _last_json(proc.stdout)["repair"] == "NO_COMMITTED_COMPLETION"


def test_repair_completion_refuses_corrupt_chain(
        tmp_path, ranged_prereg, s8_identity):
    state = _simulated_window(tmp_path / "state", ranged_prereg,
                              s8_identity)
    _complete(state, ranged_prereg, s8_identity)
    _chain_committed_missing_snapshot(state)
    receipt_path = state / RECEIPTS_NAME
    lines = receipt_path.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[0])
    record["payload"]["payload_digest"] = "1" * 64
    lines[0] = json.dumps(record, sort_keys=True)
    receipt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    proc = _run_cli(["repair-completion", "--state-dir", str(state),
                     "--config", str(CONFIG_V2)])
    assert proc.returncode == EXIT_INTEGRITY_FAILURE
    assert _last_json(proc.stdout)["repair"] == "REFUSED_CHAIN_CORRUPT"
    assert not (state / SNAPSHOT_NAME).exists(), \
        "a corrupted chain must never be disguised as recoverable"


def test_repair_completion_refuses_digest_drift(
        tmp_path, ranged_prereg, s8_identity):
    """New chain events after the committed completion change the facts:
    the repair must refuse instead of writing a snapshot the receipt does
    not vouch for."""
    state = _simulated_window(tmp_path / "state", ranged_prereg,
                              s8_identity)
    _complete(state, ranged_prereg, s8_identity)
    _chain_committed_missing_snapshot(state)
    fixture = load_fixture_table(FIXTURE_V2)
    feed, client, clock = build_selftest_feed(
        prereg=ranged_prereg, fixture=fixture, identity=s8_identity)
    client.set_cycle(1)
    clock.sync_with(client)
    run_collection_cycle(feed=feed, prereg=ranged_prereg, state_dir=state,
                         identity=s8_identity, session_index=99)

    proc = _run_cli(["repair-completion", "--state-dir", str(state),
                     "--config", str(CONFIG_V2)])
    assert proc.returncode == EXIT_INTEGRITY_FAILURE
    assert _last_json(proc.stdout)["repair"] == "REFUSED_DIGEST_DRIFT"
    assert not (state / SNAPSHOT_NAME).exists()


def test_repair_completion_refuses_cross_protocol(
        tmp_path, ranged_prereg, s8_identity):
    state = _simulated_window(tmp_path / "state", ranged_prereg,
                              s8_identity)
    _complete(state, ranged_prereg, s8_identity)
    _chain_committed_missing_snapshot(state)

    proc = _run_cli(["repair-completion", "--state-dir", str(state),
                     "--config", str(CONFIG_LEGACY)])
    assert proc.returncode == EXIT_INTEGRITY_FAILURE
    assert _last_json(proc.stdout)["repair"] == "REFUSED_PROTOCOL_MISMATCH"
    assert not (state / SNAPSHOT_NAME).exists()


def test_repair_completion_write_failure_is_recoverable(
        tmp_path, ranged_prereg, s8_identity):
    state = _simulated_window(tmp_path / "state", ranged_prereg,
                              s8_identity)
    _complete(state, ranged_prereg, s8_identity)
    _chain_committed_missing_snapshot(state)
    # block the atomic-write TEMP path (target stays genuinely missing —
    # opening a directory for writing fails identically on Windows/POSIX)
    tmp_blocker = state / (SNAPSHOT_NAME + ".tmp")
    tmp_blocker.mkdir()

    proc = _run_cli(["repair-completion", "--state-dir", str(state),
                     "--config", str(CONFIG_V2)])
    assert proc.returncode == EXIT_COMPLETION_INCOMPLETE
    assert _last_json(proc.stdout)["repair"] == "REPAIR_WRITE_FAILED"
    assert not (state / SNAPSHOT_NAME).exists(), \
        "no fake COMPLETE may appear from a failed repair write"
    status = _run_cli(["status", "--state-dir", str(state),
                       "--config", str(CONFIG_V2)])
    assert status.returncode == EXIT_COMPLETION_INCOMPLETE, \
        "no fake COMPLETE may appear from a failed repair write"

    tmp_blocker.rmdir()
    proc = _run_cli(["repair-completion", "--state-dir", str(state),
                     "--config", str(CONFIG_V2)])
    assert proc.returncode == 0
    assert _last_json(proc.stdout)["repair"] == "REPAIRED_SNAPSHOT"
    assert len(_window_records(state)) == 1


def test_repair_completion_never_touches_network_feed_or_credentials(
        tmp_path, ranged_prereg, s8_identity, monkeypatch,
        preflight_recorder, sealed_network):
    """In-process proof: the repair path performs pure file work only."""
    state = _simulated_window(tmp_path / "state", ranged_prereg,
                              s8_identity)
    _complete(state, ranged_prereg, s8_identity)
    _chain_committed_missing_snapshot(state)
    feed_sentinel = make_feed_sentinel(monkeypatch)
    import scripts.run_m35_s8_shadow_real as runner
    code = runner.cmd_repair_completion(state, CONFIG_V2)
    assert code == 0
    assert feed_sentinel == []
    assert preflight_recorder == []
    assert (state / SNAPSHOT_NAME).is_file()


def test_repair_completion_tampered_existing_snapshot_is_refused(
        tmp_path, ranged_prereg, s8_identity):
    """A snapshot that exists but fails verification is an integrity
    failure for human review — the repair never overwrites it."""
    state = _simulated_window(tmp_path / "state", ranged_prereg,
                              s8_identity)
    _complete(state, ranged_prereg, s8_identity)
    snapshot = json.loads((state / SNAPSHOT_NAME).read_text(encoding="utf-8"))
    snapshot["facts_digest"] = "9" * 64
    (state / SNAPSHOT_NAME).write_text(json.dumps(snapshot),
                                       encoding="utf-8")

    proc = _run_cli(["repair-completion", "--state-dir", str(state),
                     "--config", str(CONFIG_V2)])
    assert proc.returncode == EXIT_INTEGRITY_FAILURE
    assert _last_json(proc.stdout)["repair"] == "REFUSED_INTEGRITY"
