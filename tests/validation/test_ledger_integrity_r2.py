"""M3-R2-T3 — ledger verify-before-replay, external anchor, single-writer
lock, batch binding (P1 R2-P1-2 fix).

RED-first evidence: written and run BEFORE LedgerIntegrityError,
LedgerLockedError, LedgerAnchor, verify_ledger_file, batch_id/anchor
kwargs existed (ImportError = RED); implemented afterwards with zero
weakening. All attack samples live in tmp dirs — the real M3/r1 ledger is
never touched.

Honest capability boundary pinned here:
- The hash chain alone detects retained-head-and-tail middle deletion or
  retro-editing ONLY. Tail truncation, whole-file replacement and full
  clearing are detectable exclusively against an externally stored
  LedgerAnchor (head/tail digest + entry count + identity); an unanchored
  self-consistent tail MUST still verify — that limitation is pinned by
  test, not hidden.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

from trading_lab.security.canonical import sha256_hex  # noqa: E402
from trading_lab.validation.ledger import (  # noqa: E402
    BudgetExceeded,
    ExperimentLedger,
    LedgerAnchor,
    LedgerIntegrityError,
    LedgerLockedError,
    _json_default,
    canonical_json_entry,
    verify_ledger_file,
)

LIMITS = {
    "max_total_trials": 5,
    "max_search_queries": 3,
    "max_failures_before_halt": 2,
    "max_hypotheses": 2,
    "max_holdout_unlocks": 1,
    "per_arm_trials": {"B0_cash": 3},
}


def make_ledger(tmp_path, name="ledger.jsonl", batch_id=None, anchor=None):
    return ExperimentLedger(
        tmp_path / name, limits=LIMITS, protocol_hash="p" * 32,
        code_hash="c" * 32, batch_id=batch_id, anchor=anchor)


def seed_entries(tmp_path, n=3, name="ledger.jsonl", batch_id=None):
    led = make_ledger(tmp_path, name=name, batch_id=batch_id)
    if batch_id is not None:
        led.register_batch_init(batch_id, lineage="test")
    for i in range(n):
        led.register_trial("B0_cash", seed=i, dataset_hash="d" * 32)
    anchor = led.export_anchor() if batch_id is not None else None
    led.close()
    return tmp_path / name, anchor


def rechain(path: Path) -> None:
    """Recompute the whole chain after a content edit — models a
    sophisticated attacker who keeps the chain internally consistent."""
    lines = [json.loads(l) for l in
             path.read_text(encoding="utf-8").splitlines() if l.strip()]
    prev = None
    for e in lines:
        e["prev"] = prev
        body = {k: v for k, v in e.items() if k != "digest"}
        e["digest"] = sha256_hex(canonical_json_entry(body))
        prev = e["digest"]
    path.write_text(
        "".join(json.dumps(e, sort_keys=True, default=_json_default) + "\n"
                for e in lines),
        encoding="utf-8")


def read_lines(path: Path) -> list[str]:
    return [l for l in path.read_text(encoding="utf-8").splitlines()
            if l.strip()]


def write_lines(path: Path, lines: list[str]) -> None:
    path.write_text(
        "".join(l + "\n" for l in lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# verify BEFORE replay: a broken ledger must never load or continue
# ---------------------------------------------------------------------------


class TestVerifyBeforeReplay:
    def test_midchain_detail_tamper_refused_at_load(self, tmp_path):
        path, _ = seed_entries(tmp_path)
        lines = read_lines(path)
        obj = json.loads(lines[1])
        obj["detail"]["seed"] = 999  # "that trial used another seed"
        lines[1] = json.dumps(obj, sort_keys=True, default=_json_default)
        write_lines(path, lines)
        with pytest.raises(LedgerIntegrityError):
            make_ledger(tmp_path)

    def test_deleted_middle_entry_refused_at_load(self, tmp_path):
        path, _ = seed_entries(tmp_path)
        lines = read_lines(path)
        del lines[1]  # "erase trial #2, keep head and tail"
        write_lines(path, lines)
        with pytest.raises(LedgerIntegrityError):
            make_ledger(tmp_path)

    def test_truncated_partial_last_line_refused_at_load(self, tmp_path):
        """A crash mid-append leaves a half-written line: load must fail
        closed, never silently drop it and continue."""
        path, _ = seed_entries(tmp_path)
        with path.open("a", encoding="utf-8") as fh:
            fh.write('{"ts": "2026-11-21T00:00:00Z", "kind": "TRI')
        with pytest.raises(LedgerIntegrityError, match="malformed|truncated"):
            make_ledger(tmp_path)

    def test_identity_mismatch_refused_at_load(self, tmp_path):
        path, _ = seed_entries(tmp_path)
        with pytest.raises(LedgerIntegrityError, match="mismatch"):
            ExperimentLedger(path, limits=LIMITS, protocol_hash="p" * 32,
                             code_hash="OTHER" + "c" * 27)
        with pytest.raises(LedgerIntegrityError, match="mismatch"):
            ExperimentLedger(path, limits=LIMITS, protocol_hash="OTHER" + "p" * 27,
                             code_hash="c" * 32)

    def test_counters_consistency_enforced_even_when_chain_rechained(
            self, tmp_path):
        """Chain-valid but counter-lying history: edit an entry's
        counters_after, re-chain everything. Plain chain verification is
        blind to it; the replay-vs-counters_after check is not."""
        path, _ = seed_entries(tmp_path)
        lines = [json.loads(l) for l in read_lines(path)]
        lines[1]["counters_after"]["trials"] = 5  # lie about consumption
        write_lines(path, [json.dumps(e, sort_keys=True,
                                      default=_json_default)
                           for e in lines])
        rechain(path)  # attacker re-chains so plain verification is blind
        ok, msg = verify_ledger_file(path)
        assert ok, f"fixture must be chain-valid: {msg}"
        with pytest.raises(LedgerIntegrityError, match="counters"):
            make_ledger(tmp_path)

    def test_budget_state_from_history_still_enforced_after_clean_restart(
            self, tmp_path):
        led = make_ledger(tmp_path)
        led.register_failure("B0_cash", seed=1, dataset_hash="d" * 32,
                             error="f1")
        led.register_retry("B0_cash", seed=2, dataset_hash="d" * 32)
        led.close()
        led2 = make_ledger(tmp_path)
        assert led2.counters()["failures"] == 1
        assert led2.counters()["retries"] == 1
        assert led2.arm_trials()["B0_cash"] == 2  # failures bill trials too
        with pytest.raises(BudgetExceeded):
            for i in range(3):
                led2.register_trial("B0_cash", seed=i, dataset_hash="d" * 32)
        led2.close()


# ---------------------------------------------------------------------------
# external anchor: tail truncation / replacement / clearing detectable
# ---------------------------------------------------------------------------


class TestExternalAnchor:
    def test_anchor_detects_tail_truncation(self, tmp_path):
        path, anchor = seed_entries(tmp_path, n=3, batch_id="b2")
        lines = read_lines(path)
        write_lines(path, lines[:-1])  # drop the last entry cleanly
        with pytest.raises(LedgerIntegrityError, match="anchor"):
            make_ledger(tmp_path, batch_id="b2", anchor=anchor)

    def test_anchor_detects_wholesale_replacement(self, tmp_path):
        path, anchor = seed_entries(tmp_path, n=3, batch_id="b2")
        forged = tmp_path / "forged.jsonl"
        led = make_ledger(tmp_path, name="forged.jsonl", batch_id="b2")
        led.register_trial("B0_cash", seed=1, dataset_hash="d" * 32)
        led.close()
        forged.replace(path)
        with pytest.raises(LedgerIntegrityError, match="anchor"):
            make_ledger(tmp_path, batch_id="b2", anchor=anchor)

    def test_anchor_detects_cleared_file(self, tmp_path):
        path, anchor = seed_entries(tmp_path, n=3, batch_id="b2")
        path.write_text("", encoding="utf-8")
        with pytest.raises(LedgerIntegrityError, match="anchor"):
            make_ledger(tmp_path, batch_id="b2", anchor=anchor)

    def test_anchor_json_roundtrip_positive_control(self, tmp_path):
        """The intended production pattern: export the anchor, store it
        OUTSIDE the ledger (here: JSON round-trip), reopen intact file."""
        path, anchor = seed_entries(tmp_path, n=3, batch_id="b2")
        blob = json.loads(json.dumps(asdict(anchor)))
        restored = LedgerAnchor(**blob)
        assert restored == anchor
        led = make_ledger(tmp_path, batch_id="b2", anchor=restored)
        assert led.counters()["trials"] == 3
        assert verify_ledger_file(path)[0]
        led.close()

    def test_unanchored_verification_cannot_detect_tail_truncation(
            self, tmp_path):
        """Honest capability boundary — PINNED, not hidden: with head and
        tail retained, the remaining chain verifies True even though the
        ledger lost its last entry. Only an external anchor closes this
        gap; unanchored JSONL is never claimed non-repudiable."""
        path, _ = seed_entries(tmp_path, n=3, batch_id="b2")
        write_lines(path, read_lines(path)[:-1])  # drop the last entry
        ok, msg = verify_ledger_file(path)
        assert ok is True and "3 entries" in msg

    def test_read_anchor_refuses_broken_file(self, tmp_path):
        path, _ = seed_entries(tmp_path)
        lines = read_lines(path)
        del lines[1]  # middle deletion: retained chain is broken
        write_lines(path, lines)
        with pytest.raises(LedgerIntegrityError):
            from trading_lab.validation.ledger import read_ledger_anchor
            read_ledger_anchor(path)


# ---------------------------------------------------------------------------
# single-writer: lock, concurrent processes, stale lock after crash
# ---------------------------------------------------------------------------


class TestSingleWriter:
    def test_second_writer_same_process_refused(self, tmp_path):
        led1 = make_ledger(tmp_path)
        led1.register_trial("B0_cash", seed=1, dataset_hash="d" * 32)
        with pytest.raises(LedgerLockedError, match="lock"):
            make_ledger(tmp_path)
        led1.close()
        led3 = make_ledger(tmp_path)  # lock released on close
        assert led3.counters()["trials"] == 1
        led3.close()

    def test_second_process_writer_refused_then_budget_preserved(
            self, tmp_path):
        path = tmp_path / "ledger.jsonl"
        src = str(REPO_ROOT / "src")
        child = (
            "import sys, time;"
            f"sys.path.insert(0, r'{src}');"
            "from trading_lab.validation.ledger import ExperimentLedger;"
            f"led = ExperimentLedger(r'{path}', "
            f"limits={json.dumps(LIMITS)}, "
            "protocol_hash='p' * 32, code_hash='c' * 32);"
            "led.register_trial('B0_cash', seed=7, dataset_hash='d' * 32);"
            "print('READY', flush=True);"
            "time.sleep(5);"
            "led.close()"
        )
        proc = subprocess.Popen(
            [sys.executable, "-I", "-c", child],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        assert proc.stdout is not None
        line = proc.stdout.readline().strip()
        assert line == "READY", f"child failed to start: {line}"
        # while the child holds the ledger, a second writer is refused —
        # never two appends against the same prev
        with pytest.raises(LedgerLockedError):
            make_ledger(tmp_path)
        proc.wait(timeout=30)
        led = make_ledger(tmp_path)
        assert led.counters()["trials"] == 1  # child's trial is preserved
        assert led.arm_trials()["B0_cash"] == 1
        assert verify_ledger_file(path)[0]
        led.close()

    def test_crash_leaves_fail_closed_stale_lock_with_recovery(
            self, tmp_path):
        """A writer killed mid-session (os._exit, A7-style) leaves its
        lock: every subsequent open refuses (fail closed). Recovery is an
        explicit operator action (remove the stale lock after forensic
        review) — history/budget are then preserved exactly."""
        path = tmp_path / "ledger.jsonl"
        src = str(REPO_ROOT / "src")
        child = (
            "import os, sys;"
            f"sys.path.insert(0, r'{src}');"
            "from trading_lab.validation.ledger import ExperimentLedger;"
            f"led = ExperimentLedger(r'{path}', "
            f"limits={json.dumps(LIMITS)}, "
            "protocol_hash='p' * 32, code_hash='c' * 32);"
            "led.register_failure('B0_cash', seed=3, dataset_hash='d' * 32, "
            "error='crash-after-write');"
            "sys.stdout.flush();"
            "os._exit(37)"  # no close(): stale lock by design
        )
        proc = subprocess.run(
            [sys.executable, "-I", "-c", child], capture_output=True,
            text=True, timeout=60)
        assert proc.returncode == 37
        with pytest.raises(LedgerLockedError, match="lock"):
            make_ledger(tmp_path)
        os.unlink(str(path) + ".lock")  # documented operator recovery
        led = make_ledger(tmp_path)
        assert led.counters()["failures"] == 1
        assert led.arm_trials()["B0_cash"] == 1  # ALL_BILLED preserved
        assert verify_ledger_file(path)[0]
        led.close()


# ---------------------------------------------------------------------------
# batch binding: legitimate version migration is explicit, never silent
# ---------------------------------------------------------------------------


class TestBatchBinding:
    def test_batch_init_is_first_entry_and_bound(self, tmp_path):
        path, _ = seed_entries(tmp_path, n=2, batch_id="b2")
        first = json.loads(read_lines(path)[0])
        assert first["kind"] == "BATCH_INIT"
        assert first["batch_id"] == "b2"
        led = make_ledger(tmp_path, batch_id="b2")
        assert led.counters()["trials"] == 2
        with pytest.raises(LedgerIntegrityError):
            led.register_batch_init("b2", lineage="again")  # not first
        led.close()

    def test_batch_mismatch_refused_at_load(self, tmp_path):
        seed_entries(tmp_path, n=1, batch_id="b2")
        with pytest.raises(LedgerIntegrityError, match="batch"):
            make_ledger(tmp_path, batch_id="b3")
        with pytest.raises(LedgerIntegrityError, match="batch"):
            make_ledger(tmp_path, batch_id=None)

    def test_legacy_unbatched_file_opens_with_batch_id_none(self, tmp_path):
        """r1-style files (no batch_id key) open only as unbatched."""
        seed_entries(tmp_path, n=2, batch_id=None)
        led = make_ledger(tmp_path, batch_id=None)
        assert led.counters()["trials"] == 2
        led.close()

    def test_verify_ledger_file_clean_report_matches_legacy_contract(
            self, tmp_path):
        path, _ = seed_entries(tmp_path, n=3)
        ok, msg = verify_ledger_file(path)
        assert ok and msg == "3 entries verified"
        led = make_ledger(tmp_path)
        ok2, msg2 = led.verify_chain()
        assert ok2 and msg2 == "3 entries verified"
        led.close()
