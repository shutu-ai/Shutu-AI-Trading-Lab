"""OMS journal/state-machine/core-flow tests: persistence across restart,
journal-before-send, UNKNOWN-never-resend, recovery reconciliation,
duplicate fills, stale fence refusal."""

from __future__ import annotations

import datetime as dt
import sys
from decimal import Decimal
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from trading_lab.oms import IllegalTransition, validate_transition  # noqa: E402
from trading_lab.oms.fence import FenceError  # noqa: E402

from helpers_m2 import NOW, SYMBOL, make_intent  # noqa: E402

U = dt.timezone.utc


class TestStateMachine:
    def test_legal_chain(self):
        for cur, nxt in [
            ("NEW_INTENT", "PERSISTED"), ("PERSISTED", "SUBMITTING"),
            ("SUBMITTING", "ACKED"), ("ACKED", "FILLED"),
            ("SUBMITTING", "UNKNOWN"), ("UNKNOWN", "HALT_NEW_RISK"),
            ("HALT_NEW_RISK", "RECONCILED"), ("RECONCILED", "FILLED"),
        ]:
            validate_transition(cur, nxt)

    def test_illegal_transitions_rejected(self):
        for cur, nxt in [
            ("UNKNOWN", "SUBMITTING"),      # 盲重发路径
            ("UNKNOWN", "ACKED"),
            ("FILLED", "CANCEL_PENDING"),
            ("REJECTED", "SUBMITTING"),
            ("PERSISTED", "FILLED"),
            ("NEW_INTENT", "ACKED"),
        ]:
            with pytest.raises(IllegalTransition):
                validate_transition(cur, nxt)


def sealed_decision(stack, intent):
    """M2-R1: decisions must come from the RiskEngine (HMAC-sealed)."""
    return stack["engine"].evaluate(intent, stack["producer"], symbol=SYMBOL)


class TestJournalPersistence:
    def test_intent_survives_reopen(self, stack):
        oms = stack["oms"]
        intent = make_intent(100)
        decision = sealed_decision(stack, intent)
        outcome = oms.submit(intent, decision, SYMBOL, "buy", Decimal("50"), stack["token"])
        assert outcome.state == "ACKED"
        # Simulated restart: a brand-new journal object sees the same rows —
        # ACKED is non-terminal (fills pending), so it stays in open_intents.
        from trading_lab.oms import OrderJournal

        j2 = OrderJournal(stack["journal"].path)
        assert j2.state_of(intent.intent_id) == "ACKED"
        rows = j2.open_intents()
        assert [r["intent_id"] for r in rows] == [intent.intent_id]
        assert rows[0]["state"] == "ACKED"

    def test_intent_persisted_before_send(self, stack):
        """INV-1: journal 已含 SUBMITTING 记录后才允许出口调用——用故障出口
        验证：出口炸掉后 journal 里仍有完整意图与尝试记录。"""
        stack["broker"].schedule_fault("submit_timeout", make_intent(101).deterministic_client_order_id)
        intent = make_intent(101)
        decision = sealed_decision(stack, intent)
        outcome = stack["oms"].submit(intent, decision, SYMBOL, "buy", Decimal("50"), stack["token"])
        assert outcome.state == "UNKNOWN"
        assert stack["journal"].state_of(intent.intent_id) == "HALT_NEW_RISK"


class TestSubmitFlows:
    def test_happy_path_acked_once(self, stack):
        intent = make_intent(200)
        outcome = stack["oms"].submit(intent, sealed_decision(stack, intent), SYMBOL, "buy", Decimal("50"), stack["token"])
        assert outcome.state == "ACKED" and outcome.delivered and outcome.acknowledged
        assert stack["broker"].created_orders_by_intent(intent.deterministic_client_order_id) == 1

    def test_broker_reject_is_terminal_no_retry(self, stack):
        intent = make_intent(201)
        stack["broker"].schedule_fault("reject", intent.deterministic_client_order_id)
        outcome = stack["oms"].submit(intent, sealed_decision(stack, intent), SYMBOL, "buy", Decimal("50"), stack["token"])
        assert outcome.state == "REJECTED"
        assert stack["broker"].created_orders_by_intent(intent.deterministic_client_order_id) == 0

    @pytest.mark.parametrize("fault", ["ack_lost", "submit_timeout"])
    def test_unknown_faults_never_resend(self, stack, fault):
        """INV-2: UNKNOWN 后 created 计数最多 1、状态 HALT、无重发路径。
        ack_lost = 订单已在券商侧但回执丢失；submit_timeout = 是否到达未知。
        两者的共同不变量：绝不超过一次、绝无重发。"""
        intent = make_intent(202)
        coid = intent.deterministic_client_order_id
        stack["broker"].schedule_fault(fault, coid)
        outcome = stack["oms"].submit(intent, sealed_decision(stack, intent), SYMBOL, "buy", Decimal("50"), stack["token"])
        assert outcome.state == "UNKNOWN" and outcome.halted
        created = stack["broker"].created_orders_by_intent(coid)
        assert created <= 1
        if fault == "ack_lost":
            assert created == 1  # order provably exists broker-side
        assert stack["journal"].state_of(intent.intent_id) == "HALT_NEW_RISK"
        assert stack["ks"].is_halted()

    def test_duplicate_fill_ignored(self, stack):
        intent = make_intent(203)
        outcome = stack["oms"].submit(intent, sealed_decision(stack, intent), SYMBOL, "buy", Decimal("50"), stack["token"])
        assert outcome.state == "ACKED"
        assert stack["oms"].process_fill(intent.intent_id, "EVT-1-FILL", Decimal("50"))
        assert not stack["oms"].process_fill(intent.intent_id, "EVT-1-FILL", Decimal("50"))


class TestRecovery:
    def test_recovery_reconciles_unknown_and_requires_unlock(self, stack):
        intent = make_intent(300)
        coid = intent.deterministic_client_order_id
        stack["broker"].schedule_fault("ack_lost", coid)
        stack["oms"].submit(intent, sealed_decision(stack, intent), SYMBOL, "buy", Decimal("50"), stack["token"])
        assert stack["ks"].is_halted()
        # The "lost" order did reach the fake broker; recovery adopts it.
        stack["broker"].late_order_appears(coid, SYMBOL, Decimal("50"), "buy")
        report = stack["oms"].recover(NOW)
        assert intent.intent_id in report.reconciled
        assert report.halted and stack["ks"].is_halted()
        # Only explicit operator unlock resumes.
        with pytest.raises(Exception):
            stack["ks"].clear(operator_id="op", authorization_ref="  ")
        stack["oms"].operator_unlock("op", "reconciled:order-found-adopted")
        assert not stack["ks"].is_halted()

    def test_recovery_unknown_without_broker_state_stays_halted(self, stack):
        intent = make_intent(301)
        stack["broker"].schedule_fault("submit_timeout", intent.deterministic_client_order_id)
        stack["oms"].submit(intent, sealed_decision(stack, intent), SYMBOL, "buy", Decimal("50"), stack["token"])
        report = stack["oms"].recover(NOW)
        assert intent.intent_id in report.still_unknown  # 查无 ≠ 未发送
        assert stack["ks"].is_halted()  # operator unlock required


class TestFencing:
    def test_stale_token_refused_at_egress(self, stack):
        old_token = stack["token"]
        stack["fence"].acquire(NOW)  # someone else bumps the epoch
        intent = make_intent(400)
        decision = sealed_decision(stack, intent)
        outcome = stack["oms"].submit(intent, decision, SYMBOL, "buy", Decimal("50"), old_token)
        assert outcome.state == "HALT_NEW_RISK"
        assert stack["broker"].created_orders_by_intent(intent.deterministic_client_order_id) == 0

    def test_expired_lease_refused(self, stack):
        token = stack["fence"].acquire(NOW - dt.timedelta(hours=1))
        with pytest.raises(FenceError):
            stack["egress"].submit(token, "X:Y:1", SYMBOL, Decimal("1"), "buy")

    def test_new_epoch_supersedes_old_token(self, stack):
        old = stack["fence"].acquire(NOW)
        new = stack["fence"].acquire(NOW)
        assert new.epoch == old.epoch + 1
        with pytest.raises(FenceError):
            stack["fence"].validate(old, NOW)
        stack["fence"].validate(new, NOW)
