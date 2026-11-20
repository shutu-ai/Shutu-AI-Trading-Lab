"""Schema Gate negative matrix — architecture §2.6 负例验收.

Every invalid input must yield NO_TRADE + an audit event; a valid signal
from a reviewed build passes. Nothing here raises.
"""

from __future__ import annotations

import datetime as dt
import json
import pickle
import sys
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from trading_lab.security import AuditLog, SchemaGate

from conftest import NOW

REVIEWED_BUILDS = {"demo_ma": {"a" * 32}}
ALLOWED_SYMBOLS = {"SPY", "QQQ"}


def make_gate(tmp_path):
    audit = AuditLog(tmp_path / "gate_audit.jsonl", "TEST")
    return SchemaGate(REVIEWED_BUILDS, ALLOWED_SYMBOLS, audit, now_fn=lambda: NOW), audit


def valid_signal_json(**over) -> str:
    payload = {
        "schema_version": "1",
        "strategy_id": "demo_ma",
        "strategy_version": "1.0.0",
        "reviewed_build_hash": "a" * 32,
        "snapshot_id": "snap-0001",
        "target_exposure": "0.30",
        "expires_at_utc": (NOW + dt.timedelta(minutes=5)).isoformat(),
        "rationale_hash": "b" * 32,
    }
    payload.update(over)
    return json.dumps(payload)


def audit_actions(audit: AuditLog) -> list[tuple[str, list[str]]]:
    out = []
    for line in audit.path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        out.append((rec["event_type"], rec["payload"].get("reason_codes", [])))
    return out


class TestPositive:
    def test_valid_signal_allowed(self, tmp_path):
        gate, _ = make_gate(tmp_path)
        d = gate.evaluate_signal(valid_signal_json())
        assert d.allow and d.action == "ALLOW_SIGNAL"
        assert d.reason_codes == ()


class TestStructuralRejections:
    def test_pickle_rejected(self, tmp_path):
        gate, _ = make_gate(tmp_path)
        blob = pickle.dumps({"evil": True})
        d = gate.evaluate_signal(blob)
        assert not d.allow and "NOT_VALID_JSON" in d.reason_codes

    def test_non_json_text_rejected(self, tmp_path):
        gate, _ = make_gate(tmp_path)
        d = gate.evaluate_signal("import os; os.system('rm -rf /')")
        assert not d.allow and "NOT_VALID_JSON" in d.reason_codes

    def test_json_array_top_level_rejected(self, tmp_path):
        gate, _ = make_gate(tmp_path)
        d = gate.evaluate_signal("[1, 2, 3]")
        assert not d.allow and "SCHEMA_VALIDATION_FAILED" in d.reason_codes[0]

    def test_unknown_field_command_injection_rejected(self, tmp_path):
        gate, _ = make_gate(tmp_path)
        raw = valid_signal_json().replace(
            '"rationale_hash"', '"cmd": "curl evil.sh", "rationale_hash"'
        )
        d = gate.evaluate_signal(raw)
        assert not d.allow
        assert any(r.startswith("SCHEMA_VALIDATION_FAILED") for r in d.reason_codes)

    def test_command_string_in_hash_field_rejected(self, tmp_path):
        gate, _ = make_gate(tmp_path)
        d = gate.evaluate_signal(valid_signal_json(rationale_hash="exec(evil)"))
        assert not d.allow  # pattern-validated hex hash field

    def test_missing_required_field_rejected(self, tmp_path):
        gate, _ = make_gate(tmp_path)
        raw = json.loads(valid_signal_json())
        del raw["snapshot_id"]
        d = gate.evaluate_signal(json.dumps(raw))
        assert not d.allow


class TestReviewAndTTL:
    def test_unreviewed_build_hash_rejected(self, tmp_path):
        gate, _ = make_gate(tmp_path)
        d = gate.evaluate_signal(valid_signal_json(reviewed_build_hash="e" * 32))
        assert not d.allow
        assert any(r.startswith("BUILD_NOT_REVIEWED") for r in d.reason_codes)

    def test_unknown_strategy_rejected(self, tmp_path):
        gate, _ = make_gate(tmp_path)
        d = gate.evaluate_signal(valid_signal_json(strategy_id="rogue_strategy"))
        assert not d.allow

    def test_expired_signal_rejected(self, tmp_path):
        gate, _ = make_gate(tmp_path)
        stale = (NOW - dt.timedelta(seconds=1)).isoformat()
        d = gate.evaluate_signal(valid_signal_json(expires_at_utc=stale))
        assert not d.allow
        assert "SIGNAL_EXPIRED" in d.reason_codes

    def test_unsupported_schema_version_rejected(self, tmp_path):
        gate, _ = make_gate(tmp_path)
        d = gate.evaluate_signal(valid_signal_json(schema_version="999"))
        assert not d.allow
        assert any(r.startswith("UNSUPPORTED_SCHEMA_VERSION") for r in d.reason_codes)


class TestNumericSafety:
    def test_nan_exposure_rejected(self, tmp_path):
        gate, _ = make_gate(tmp_path)
        raw = valid_signal_json().replace('"target_exposure": "0.30"', '"target_exposure": NaN')
        d = gate.evaluate_signal(raw)
        assert not d.allow  # NaN is not valid JSON either

    def test_exposure_above_one_rejected(self, tmp_path):
        gate, _ = make_gate(tmp_path)
        d = gate.evaluate_signal(valid_signal_json(target_exposure="1.5"))
        assert not d.allow
        assert any(r.startswith("TARGET_EXPOSURE_OUT_OF_RANGE") or r.startswith("SCHEMA_VALIDATION_FAILED") for r in d.reason_codes)

    def test_negative_exposure_rejected(self, tmp_path):
        gate, _ = make_gate(tmp_path)
        d = gate.evaluate_signal(valid_signal_json(target_exposure="-0.5"))
        assert not d.allow


class TestPortfolioGate:
    def valid_portfolio(self, **over) -> str:
        payload = {
            "account_id": "A1",
            "allocation": [
                {"symbol": "SPY", "weight": "0.60"},
                {"symbol": "QQQ", "weight": "0.30"},
            ],
            "cash_weight": "0.10",
            "risk_budget_id": "rb1",
            "timestamp": NOW.isoformat(),
        }
        payload.update(over)
        return json.dumps(payload)

    def test_valid_portfolio_allowed(self, tmp_path):
        gate, _ = make_gate(tmp_path)
        d = gate.evaluate_portfolio(self.valid_portfolio())
        assert d.allow and d.action == "ALLOW_PORTFOLIO"

    def test_off_pool_symbol_rejected(self, tmp_path):
        gate, _ = make_gate(tmp_path)
        d = gate.evaluate_portfolio(
            self.valid_portfolio(
                allocation=[
                    {"symbol": "SPY", "weight": "0.60"},
                    {"symbol": "DOGE", "weight": "0.30"},
                ]
            )
        )
        assert not d.allow
        assert any(r.startswith("SYMBOLS_OUTSIDE_ALLOWED_POOL") for r in d.reason_codes)

    def test_negative_weight_rejected(self, tmp_path):
        gate, _ = make_gate(tmp_path)
        d = gate.evaluate_portfolio(
            self.valid_portfolio(
                allocation=[{"symbol": "SPY", "weight": "-0.5"}],
                cash_weight="1.5",
            )
        )
        assert not d.allow  # contract rejects negatives: no leverage via weights


class TestAudit:
    def test_rejections_are_audited(self, tmp_path):
        gate, audit = make_gate(tmp_path)
        gate.evaluate_signal("not json")
        actions = [a for a, _ in audit_actions(audit)]
        assert actions == ["NO_TRADE"]

    def test_gate_never_raises(self, tmp_path):
        gate, _ = make_gate(tmp_path)
        for evil in (b"", b"\x00\xff", "null", "123", "{}", '{"strategy_id": 42}'):
            d = gate.evaluate_signal(evil)
            assert d.action == "NO_TRADE"
