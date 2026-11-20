"""M2-RESIDUAL-SAFETY-GATE-001 — RED reproductions for R1–R5."""

from __future__ import annotations

import datetime as dt
import sys
from decimal import Decimal
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

from trading_lab.contracts import Environment, RiskDecision  # noqa: E402
from trading_lab.oms import FenceCoordinator, OmsEngine, OrderJournal  # noqa: E402

from helpers_m2 import ACCOUNT, NOW, SYMBOL, make_intent  # noqa: E402


def sealed(stack, intent, symbol=SYMBOL):
    return stack["engine"].evaluate(intent, stack["producer"], symbol=symbol)


# ---------------------------------------------------------------------------
# R1 — fence loss / UNKNOWN must trip the GLOBAL persistent halt
# ---------------------------------------------------------------------------


class TestR1GlobalHalt:
    def test_fence_loss_blocks_next_new_intent(self, stack):
        """A 失去 fence 后，新的合法密封意图 B 必须 0 发送 + KillSwitch 持久 HALT。"""
        a = make_intent(800)
        stack["fence"].acquire(NOW)  # B bumps epoch — A loses its fence
        from trading_lab.oms import BrokerEgress as _E

        stack["egress"] = _E(stack["broker"], stack["fence"], stack["audit"], now_fn=lambda: NOW)
        stack["token"] = stack["fence"].acquire(NOW)
        stack["oms"] = OmsEngine(
            environment=Environment.PAPER, account_id=ACCOUNT,
            journal=stack["journal"], egress=stack["egress"], fence=stack["fence"],
            audit=stack["audit"], kill_switch=stack["ks"], now_fn=lambda: NOW,
            expected_policy_hash=stack["policy"].policy_hash,
            approval_secrets=stack["engine"]._approval_secrets,  # noqa: SLF001
        )
        outcome_a = stack["oms"].submit(a, sealed(stack, a), SYMBOL, "buy", Decimal("50"), stack["token"])
        assert outcome_a.state == "HALT_NEW_RISK"
        assert stack["ks"].is_halted()  # GREEN: fence 丧失即触发全局持久 HALT

        b = make_intent(801)
        outcome_b = stack["oms"].submit(b, sealed(stack, b), SYMBOL, "buy", Decimal("30"), stack["token"])
        assert stack["ks"].is_halted()  # GREEN: 全局持久 HALT
        assert stack["broker"].created_orders_by_intent(b.deterministic_client_order_id) == 0
        assert outcome_b.state == "HALT_NEW_RISK"

    def test_unknown_outcome_trips_global_halt(self, stack):
        """acknowledged=None（送达未知）→ KillSwitch 必须激活，下一意图 0 发送。"""
        intent = make_intent(810)
        original = stack["broker"].submit_order

        def unknown_submit(coid_, symbol, qty, side, epoch):
            from trading_lab.brokers import SubmitReceipt

            return SubmitReceipt(delivered=True, acknowledged=None, broker_order_id=None)

        stack["broker"].submit_order = unknown_submit  # type: ignore[method-assign]
        outcome = stack["oms"].submit(intent, sealed(stack, intent), SYMBOL, "buy",
                                      Decimal("50"), stack["token"])
        assert outcome.state == "UNKNOWN"
        assert stack["ks"].is_halted()  # GREEN: UNKNOWN 触发全局持久 HALT

        nxt = make_intent(811)
        outcome2 = stack["oms"].submit(nxt, sealed(stack, nxt), SYMBOL, "buy",
                                       Decimal("30"), stack["token"])
        assert stack["ks"].is_halted()  # GREEN
        assert stack["broker"].created_orders_by_intent(nxt.deterministic_client_order_id) == 0

    def test_recovered_submittng_intent_blocks_new_risk(self, stack):
        """崩溃窗口：journal 已 SUBMITTING 但 KillSwitch 尚未设置——恢复入口必须
        先阻断新增风险，且不得把记录当『未发送可重试』。"""
        intent = make_intent(812)
        stack["journal"].record_intent_and_submitting(
            intent_id=intent.intent_id,
            client_order_id=intent.deterministic_client_order_id,
            environment="PAPER", account_id=ACCOUNT, symbol=SYMBOL, side="buy",
            quantity="50", payload=intent.model_dump(mode="json"),
            risk_decision={}, fence_epoch=stack["token"].epoch,
        )
        assert not stack["ks"].is_halted()  # crashed before ks.set — the gap
        report = stack["oms"].recover(NOW)
        assert stack["ks"].is_halted()  # recovery must halt globally
        assert intent.intent_id in report.still_unknown  # 查无 ≠ 未发送


# ---------------------------------------------------------------------------
# R2 — egress must require journal-backed durable send eligibility
# ---------------------------------------------------------------------------


class TestR2EgressEligibility:
    def test_direct_egress_without_intent_zero_created(self, stack):
        """有效 fence 直接调公开 egress.submit，无对应 journal 意图 → 精确
        拒绝（EgressRefusalError）且 0 创建（A-RED5：禁止宽泛 except 掩盖）。"""
        from trading_lab.oms import EgressRefusalError

        with pytest.raises(EgressRefusalError,
                      match=r"NO_ELIGIBLE_OR_ALREADY_CLAIMED|NO_ELIGIBLE_INTENT"):
            stack["egress"].submit(stack["token"], "PAPER:PAPER_TEST_ACCOUNT:99999999",
                                   SYMBOL, Decimal("50"), "buy")
        assert stack["broker"].created_orders_by_intent(
            "PAPER:PAPER_TEST_ACCOUNT:99999999") == 0

    def test_replayed_egress_submit_never_second_order(self, stack):
        """同一意图合法提交后，直接重放 egress submit 不得第二次到达 FakeBroker。"""
        intent = make_intent(820)
        outcome = stack["oms"].submit(intent, sealed(stack, intent), SYMBOL, "buy",
                                      Decimal("50"), stack["token"])
        assert outcome.state == "ACKED"
        coid = intent.deterministic_client_order_id
        try:
            stack["egress"].submit(stack["token"], coid, SYMBOL, Decimal("50"), "buy")
        except Exception:
            pass
        assert stack["broker"].created_orders_by_intent(coid) == 1  # <- RED: 会变 2

    def test_journal_unavailable_refuses_before_port(self, stack):
        """Journal/资格校验不可用必须在调用 Port 之前拒绝，created 保持 0。"""
        intent = make_intent(821)
        stack["journal"].close()
        with pytest.raises(Exception):
            stack["egress"].submit(stack["token"], intent.deterministic_client_order_id,
                                   SYMBOL, Decimal("50"), "buy")
        assert stack["broker"].created_orders_by_intent(intent.deterministic_client_order_id) == 0

    def test_legitimate_chain_still_exactly_one(self, stack):
        intent = make_intent(822)
        outcome = stack["oms"].submit(intent, sealed(stack, intent), SYMBOL, "buy",
                                      Decimal("50"), stack["token"])
        assert outcome.state == "ACKED"
        assert stack["broker"].created_orders_by_intent(intent.deterministic_client_order_id) == 1


# ---------------------------------------------------------------------------
# R3 — CAS transitions must also honor the state machine
# ---------------------------------------------------------------------------


class TestR3CasStateMachine:
    def _acked_intent(self, stack, seq):
        intent = make_intent(seq)
        stack["journal"].record_intent_and_submitting(
            intent_id=intent.intent_id,
            client_order_id=intent.deterministic_client_order_id,
            environment="PAPER", account_id=ACCOUNT, symbol=SYMBOL, side="buy",
            quantity="50", payload=intent.model_dump(mode="json"),
            risk_decision={}, fence_epoch=1,
        )
        stack["journal"].transition_state(intent.intent_id, "SUBMITTING", "ACKED", bump_version=True)
        return intent

    @pytest.mark.parametrize("expected,target", [
        ("ACKED", "NEW_INTENT"),
        ("UNKNOWN", "SUBMITTING"),
        ("FILLED", "ACKED"),
        ("ACKED", "RECONCILED"),  # ACKED 不可直达 RECONCILED
        ("BOGUS_STATE", "ACKED"),
    ])
    def test_illegal_cas_transitions_rejected(self, stack, expected, target):
        intent = self._acked_intent(stack, 830)
        with pytest.raises(Exception):
            stack["journal"].transition_state(intent.intent_id, expected, target)
        assert stack["journal"].state_of(intent.intent_id) == "ACKED"  # 状态/版本不变

    def test_legal_transition_still_works(self, stack):
        intent = self._acked_intent(stack, 831)
        stack["journal"].transition_state(intent.intent_id, "ACKED", "PARTIALLY_FILLED")
        assert stack["journal"].state_of(intent.intent_id) == "PARTIALLY_FILLED"


# ---------------------------------------------------------------------------
# R4 — fill quantity must be strictly positive finite Decimal
# ---------------------------------------------------------------------------


class TestR4FillQuantity:
    def _acked(self, stack, seq):
        intent = make_intent(seq)
        outcome = stack["oms"].submit(intent, sealed(stack, intent), SYMBOL, "buy",
                                      Decimal("50"), stack["token"])
        assert outcome.state == "ACKED"
        return intent

    @pytest.mark.parametrize("bad", [
        Decimal("0"), Decimal("-5"), Decimal("-Infinity"), Decimal("NaN"), 5.0, 5, True,
    ])
    def test_invalid_quantities_refused(self, stack, bad):
        intent = self._acked(stack, 840)
        ok, reason = stack["journal"].apply_fill(intent.intent_id, f"EVT-{abs(hash(str(bad)))}", bad)
        assert not ok
        assert reason.startswith("INVALID_FILL")
        assert stack["journal"].state_of(intent.intent_id) == "ACKED"  # 零状态变化

    def test_valid_fills_still_work(self, stack):
        intent = self._acked(stack, 841)
        ok, _ = stack["journal"].apply_fill(intent.intent_id, "EVT-V1", Decimal("20"))
        assert ok
        ok, _ = stack["journal"].apply_fill(intent.intent_id, "EVT-V2", Decimal("30"))
        assert ok
        assert stack["journal"].state_of(intent.intent_id) == "FILLED"


# ---------------------------------------------------------------------------
# R5 — OMS must bind environment/account and pin the policy hash
# ---------------------------------------------------------------------------


class TestR5OmsBinding:
    def test_cross_account_intent_refused(self, stack):
        """错误装配/交叉账户：intent 属其他账户 → OMS 拒绝而非依赖装配正确。"""
        other = make_intent(850, account="OTHER_ACCOUNT")
        decision = sealed(stack, other)  # same secrets assembly — seal is valid
        outcome = stack["oms"].submit(other, decision, SYMBOL, "buy", Decimal("50"), stack["token"])
        assert stack["broker"].created_orders_by_intent(
            other.deterministic_client_order_id) == 0  # <- RED: 整改前会发送
        assert outcome.state == "REJECTED"

    def test_unpinned_policy_hash_constructor_refused(self, stack):
        """缺省 expected_policy_hash 的构造必须被拒绝（fail-closed pin）。"""
        with pytest.raises(Exception):
            OmsEngine(
                environment=Environment.PAPER, account_id=ACCOUNT,
                journal=stack["journal"], egress=stack["egress"], fence=stack["fence"],
                audit=stack["audit"], kill_switch=stack["ks"], now_fn=lambda: NOW,
                expected_policy_hash="",
                approval_secrets=stack["engine"]._approval_secrets,  # noqa: SLF001
            )

    def test_normal_paper_positive_kept(self, stack):
        intent = make_intent(851)
        outcome = stack["oms"].submit(intent, sealed(stack, intent), SYMBOL, "buy",
                                      Decimal("50"), stack["token"])
        assert outcome.state == "ACKED"
