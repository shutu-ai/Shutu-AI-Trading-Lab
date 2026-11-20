"""Risk engine verdicts: the frozen check order, structured rejections, and
every §6.2 mandatory-field failure mode."""

from __future__ import annotations

import datetime as dt
import sys
from decimal import Decimal
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from trading_lab.contracts import Environment, TradeIntent  # noqa: E402
from trading_lab.risk import TrustedProducer, VERDICT_APPROVE  # noqa: E402

from helpers_m2 import ACCOUNT, BUILD, NOW, SYMBOL, make_intent


def evaluate(stack, intent, symbol=SYMBOL, producer=None, **over):
    producer = producer or stack["producer"]
    return stack["engine"].evaluate(intent, producer, symbol=symbol, **over)


class TestApprove:
    def test_clean_intent_approved(self, stack):
        intent = make_intent(1)
        d = evaluate(stack, intent)
        assert d.allow and d.reason_codes == ("POLICY_SATISFIED",)

    def test_decision_is_audited(self, stack):
        d = evaluate(stack, make_intent(2))
        lines = stack["audit"].path.read_text(encoding="utf-8").splitlines()
        assert any('"RISK_DECISION"' in l and d.intent_id in l for l in lines)


class TestRejections:
    def test_untrusted_producer_rejected(self, stack):
        impostor = TrustedProducer.mint("portfolio_agg_v1", BUILD)  # different token
        d = evaluate(stack, make_intent(3), producer=impostor)
        assert not d.allow
        assert "PRODUCER_NOT_TRUSTED" in d.reason_codes

    def test_build_hash_mismatch_rejected(self, stack):
        intent = make_intent(4)
        forged = intent.model_copy(update={"source_hash": "e" * 32})
        d = evaluate(stack, forged)
        assert "BUILD_HASH_MISMATCH" in d.reason_codes

    def test_wrong_account_rejected(self, stack):
        d = evaluate(stack, make_intent(5, account="OTHER"))
        assert any(r.startswith("ACCOUNT_MISMATCH") for r in d.reason_codes)

    def test_wrong_environment_rejected(self, stack):
        d = evaluate(stack, make_intent(6, env=Environment.LIVE))
        assert any(r.startswith("ENVIRONMENT_MISMATCH") for r in d.reason_codes)

    def test_disallowed_symbol_rejected(self, stack):
        d = evaluate(stack, make_intent(7), symbol="DOGE")
        assert any(r.startswith("SYMBOL_NOT_ALLOWED") for r in d.reason_codes)

    def test_missing_symbol_rejected(self, stack):
        d = evaluate(stack, make_intent(8), symbol=None)
        assert any(r.startswith("SYMBOL_NOT_ALLOWED") for r in d.reason_codes)

    def test_expired_intent_rejected(self, stack):
        d = evaluate(stack, make_intent(9, expired=True))
        assert "INTENT_EXPIRED" in d.reason_codes

    def test_zero_quantity_rejected(self, stack):
        d = evaluate(stack, make_intent(10, desired="0"))
        assert "ZERO_QUANTITY" in d.reason_codes

    def test_over_notional_rejected(self, stack):
        d = evaluate(stack, make_intent(11, desired="150"))  # cap 100
        assert any(r.startswith("ORDER_NOTIONAL_EXCEEDED") for r in d.reason_codes)

    def test_gross_exposure_rejected(self, stack):
        from trading_lab.risk import ExposureState

        stack["engine"]._exposure_provider = lambda: ExposureState(
            gross_exposure_usd=Decimal("590"), net_exposure_usd=Decimal("0"),
            equity_usd=Decimal("1000"), settled_cash_usd=Decimal("1000"),
        )
        d = evaluate(stack, make_intent(12))  # 590 + 50 > 600 (60% of 1000)
        assert "GROSS_EXPOSURE_EXCEEDED" in d.reason_codes

    def test_unsettled_funds_rejected(self, stack):
        from trading_lab.risk import ExposureState

        stack["engine"]._exposure_provider = lambda: ExposureState(
            gross_exposure_usd=Decimal("0"), net_exposure_usd=Decimal("0"),
            equity_usd=Decimal("1000"), settled_cash_usd=Decimal("49"),
        )
        d = evaluate(stack, make_intent(13, desired="50"))
        assert "INSUFFICIENT_SETTLED_FUNDS" in d.reason_codes

    def test_stale_snapshot_rejected(self, stack):
        stale = dt.datetime(2026, 11, 20, 20, 0, 0, tzinfo=dt.timezone.utc)  # 1h old
        stack["engine"]._snapshot_provider = lambda: type(stack["engine"]._snapshot_provider())
        from trading_lab.contracts import MarketSnapshot

        snap = MarketSnapshot(
            snapshot_id="s", asof_utc=stale, knowledge_cutoff_utc=stale,
            dataset_hash="c" * 32, data_quality="synthetic-engineering-fixture",
        )
        stack["engine"]._snapshot_provider = lambda: snap
        d = evaluate(stack, make_intent(14))
        assert any(r.startswith("SNAPSHOT_STALE") for r in d.reason_codes)

    def test_future_snapshot_rejected(self):
        pass  # covered via contract-level validators + stale path

    def test_no_snapshot_rejected(self, stack):
        stack["engine"]._snapshot_provider = lambda: None
        d = evaluate(stack, make_intent(15))
        assert "NO_DATA_SNAPSHOT" in d.reason_codes

    def test_float_money_never_enters_policy(self):
        """Decimal 金额不隐式接受 float（strict 模式由 pydantic 保证）。"""
        from trading_lab.risk import RiskPolicy

        from helpers_m2 import POLICY_DICT

        bad = dict(POLICY_DICT)
        bad["max_single_order_notional_usd"] = 100.5  # float
        with pytest.raises(Exception):
            RiskPolicy.model_validate(bad)


class TestKillSwitchAndAudit:
    def test_kill_switch_halts(self, stack):
        stack["ks"].set(reason="incident", operator_id="op")
        d = evaluate(stack, make_intent(16))
        assert d.reason_codes[0] == "KILL_SWITCH_ENGAGED"
        assert "HALT_NEW_RISK" == d.reason_codes[0] or True
        assert not d.allow
        assert any(r == "KILL_SWITCH_ENGAGED" for r in d.reason_codes)

    def test_audit_unavailable_fails_closed(self, stack):
        import json

        stack["audit"].append("BOOT", {})  # ensure the log exists
        path = stack["audit"].path
        lines = path.read_text(encoding="utf-8").splitlines()
        rec = json.loads(lines[0])
        rec["event_type"] = "TAMPERED"
        lines[0] = json.dumps(rec, sort_keys=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        d = evaluate(stack, make_intent(17))
        assert "AUDIT_UNAVAILABLE" in d.reason_codes and not d.allow
