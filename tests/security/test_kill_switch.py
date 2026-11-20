"""Kill switch tests: persistence across restart, fail-closed blocking,
explicit-authorization-only clearing, full audit trail."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from trading_lab.contracts import Environment, HaltState
from trading_lab.security import AuditLog, KillSwitch, KillSwitchError


def make_ks(tmp_path):
    audit = AuditLog(tmp_path / "audit.jsonl", "TEST")
    ks = KillSwitch(Environment.PAPER, "PAPER_TEST_ACCOUNT", tmp_path / "ks", audit)
    return ks, audit


def events(audit: AuditLog) -> list[str]:
    return [
        json.loads(l)["event_type"]
        for l in audit.path.read_text(encoding="utf-8").splitlines()
        if l.strip()
    ]


class TestHaltLifecycle:
    def test_normal_then_halt(self, tmp_path):
        ks, _ = make_ks(tmp_path)
        assert ks.halt_state() is HaltState.NORMAL
        ks.require_tradable()  # no-op while normal
        ks.set(reason="incident: reconciliation mismatch", operator_id="op-1")
        assert ks.is_halted()
        assert ks.halt_state() is HaltState.HALT_NEW_RISK

    def test_set_requires_reason(self, tmp_path):
        ks, _ = make_ks(tmp_path)
        with pytest.raises(ValueError):
            ks.set(reason="  ", operator_id="op-1")

    def test_halt_survives_restart(self, tmp_path):
        """§6.2: 事故状态必须持续存储，不得因重启自动清除."""
        ks, _ = make_ks(tmp_path)
        ks.set(reason="incident", operator_id="op-1")
        # A brand-new instance (simulated restart) must see the halt.
        ks2, _ = make_ks(tmp_path)
        assert ks2.is_halted()
        with pytest.raises(KillSwitchError):
            ks2.require_tradable()

    def test_clear_requires_authorization(self, tmp_path):
        ks, audit = make_ks(tmp_path)
        ks.set(reason="incident", operator_id="op-1")
        with pytest.raises(ValueError):
            ks.clear(operator_id="op-2", authorization_ref="   ")
        assert ks.is_halted()  # still halted
        assert "KILL_SWITCH_CLEAR_REFUSED_NO_AUTHORIZATION" in events(audit)

    def test_clear_with_authorization_releases(self, tmp_path):
        ks, audit = make_ks(tmp_path)
        ks.set(reason="incident", operator_id="op-1")
        ks.clear(
            operator_id="op-2",
            authorization_ref="operator approved; broker orders/positions/cash reconciled",
        )
        assert not ks.is_halted()
        ks.require_tradable()
        assert "KILL_SWITCH_CLEARED" in events(audit)

    def test_blocking_is_audited(self, tmp_path):
        ks, audit = make_ks(tmp_path)
        ks.set(reason="incident", operator_id="op-1")
        with pytest.raises(KillSwitchError):
            ks.require_tradable()
        assert "RISK_ACTION_REFUSED_HALTED" in events(audit)

    def test_full_lifecycle_audited(self, tmp_path):
        ks, audit = make_ks(tmp_path)
        ks.set(reason="incident", operator_id="op-1")
        ks.clear(operator_id="op-1", authorization_ref="auth-1")
        assert events(audit) == ["KILL_SWITCH_SET", "KILL_SWITCH_CLEARED"]

    def test_halt_file_has_no_place_for_tampered_state(self, tmp_path):
        """The persisted record carries reason/operator/timestamp for later
        human review; it must be valid JSON with the halt state."""
        ks, _ = make_ks(tmp_path)
        ks.set(reason="incident", operator_id="op-1")
        record = json.loads(ks.halt_file.read_text(encoding="utf-8"))
        assert record["state"] == HaltState.HALT_NEW_RISK.value
        assert record["reason"] == "incident"
        assert record["operator_id"] == "op-1"
