"""Audit skeleton tests: append-only growth, hash-chain verification,
tamper detection."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from trading_lab.security import AuditLog, GENESIS_HASH


class TestAppendAndVerify:
    def test_append_grows_and_chains(self, tmp_path):
        log = AuditLog(tmp_path / "audit.jsonl", "TEST")
        for i in range(5):
            log.append("TEST_EVENT", {"i": i})
        ok, bad = log.verify()
        assert ok and bad == 0
        lines = [json.loads(l) for l in (tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines()]
        assert [r["seq"] for r in lines] == [1, 2, 3, 4, 5]
        assert lines[0]["prev_hash"] == GENESIS_HASH
        assert lines[1]["prev_hash"] == lines[0]["event_hash"]

    def test_reopen_continues_chain(self, tmp_path):
        log1 = AuditLog(tmp_path / "audit.jsonl", "TEST")
        log1.append("A", {})
        log1.append("B", {})
        log2 = AuditLog(tmp_path / "audit.jsonl", "TEST")  # simulated restart
        log2.append("C", {})
        ok, _ = log2.verify()
        assert ok

    def test_gap_detected_on_load(self, tmp_path):
        log = AuditLog(tmp_path / "audit.jsonl", "TEST")
        log.append("A", {})
        log.append("B", {})
        log.append("C", {})
        # Simulate a lost middle line: seq jumps 1 -> 3, which must be caught.
        lines = (tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines()
        (tmp_path / "audit.jsonl").write_text(lines[0] + "\n" + lines[2] + "\n", encoding="utf-8")
        with pytest.raises(ValueError):
            AuditLog(tmp_path / "audit.jsonl", "TEST")


class TestTamperDetection:
    def test_payload_tamper_detected(self, tmp_path):
        log = AuditLog(tmp_path / "audit.jsonl", "TEST")
        log.append("EVENT", {"amount": "10"})
        log.append("EVENT", {"amount": "20"})
        path = tmp_path / "audit.jsonl"
        lines = path.read_text(encoding="utf-8").splitlines()
        rec = json.loads(lines[0])
        rec["payload"]["amount"] = "999999"  # history rewrite attempt
        lines[0] = json.dumps(rec, sort_keys=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        ok, bad = log.verify()
        assert not ok and bad == 1

    def test_tail_truncation_detected_by_head_record(self, tmp_path):
        """Tail truncation is internally chain-consistent, so the companion
        head record is what detects a lost tail."""
        log = AuditLog(tmp_path / "audit.jsonl", "TEST")
        log.append("A", {})
        log.append("B", {})
        log.append("C", {})
        path = tmp_path / "audit.jsonl"
        lines = path.read_text(encoding="utf-8").splitlines()
        path.write_text("\n".join(lines[:1]) + "\n", encoding="utf-8")  # drop tail
        log2 = AuditLog.__new__(AuditLog)  # verify() without the load gap-check
        log2._path = path  # noqa: SLF001 - test seam
        log2._head_path = Path(str(path) + ".head")  # noqa: SLF001 - test seam
        ok, bad = log2.verify()
        assert not ok and bad == 3  # head says 3 lines, file holds 1

    def test_empty_log_verifies(self, tmp_path):
        log = AuditLog(tmp_path / "audit.jsonl", "TEST")
        ok, _ = log.verify()
        assert ok
