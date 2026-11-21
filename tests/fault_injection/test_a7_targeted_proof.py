"""M2-A7 targeted proof — minimal focused tests.

Verifies: claim CAS is one-shot, fresh KillSwitch sees persistent HALT,
new risk blocked through OMS path, RiskEngine independently refuses.
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

from helpers_m2 import ACCOUNT, NOW, POLICY_DICT, SYMBOL, fresh_snapshot, make_intent  # noqa: E402

from trading_lab.brokers import FakeBroker  # noqa: E402
from trading_lab.contracts import Environment, RiskDecision  # noqa: E402
from trading_lab.oms import BrokerEgress, FenceCoordinator, OmsEngine, OrderJournal  # noqa: E402
from trading_lab.risk import ExposureState, RiskEngine, RiskPolicy, TrustedProducer  # noqa: E402
from trading_lab.security import ApprovalSecrets, AuditLog, KillSwitch  # noqa: E402


def make_stack(tmp):
    broker = FakeBroker()
    audit = AuditLog(tmp / "audit.jsonl", "PAPER")
    journal = OrderJournal(tmp / "journal.sqlite3", check_same_thread=False)
    fence = FenceCoordinator(tmp / "fence.sqlite3", Environment.PAPER, ACCOUNT)
    ks = KillSwitch(Environment.PAPER, ACCOUNT, tmp / "ks", audit)
    policy = RiskPolicy.model_validate(dict(POLICY_DICT))
    producer = TrustedProducer.mint("portfolio_agg_v1", "a" * 32)
    secrets = ApprovalSecrets.mint()
    engine = RiskEngine(policy=policy, kill_switch=ks, audit=audit,
                        trusted_producer=producer, now_fn=lambda: NOW,
                        snapshot_provider=fresh_snapshot,
                        exposure_provider=lambda: ExposureState(
                            gross_exposure_usd=Decimal("0"), net_exposure_usd=Decimal("0"),
                            equity_usd=Decimal("1000"), settled_cash_usd=Decimal("1000")),
                        approval_secrets=secrets)
    egress = BrokerEgress(broker, fence, audit, now_fn=lambda: NOW,
                          journal=journal, approval_secrets=secrets)
    oms = OmsEngine(environment=Environment.PAPER, account_id=ACCOUNT,
                    journal=journal, egress=egress, fence=fence,
                    audit=audit, kill_switch=ks, now_fn=lambda: NOW,
                    expected_policy_hash=policy.policy_hash,
                    approval_secrets=secrets)
    token = fence.acquire(NOW)
    return {"broker": broker, "audit": audit, "journal": journal,
            "fence": fence, "ks": ks, "engine": engine, "oms": oms,
            "token": token, "producer": producer, "secrets": secrets}


def seed_intent(stack, seq):
    intent = make_intent(seq)
    stack["journal"].record_intent_and_submitting(
        intent_id=intent.intent_id,
        client_order_id=intent.deterministic_client_order_id,
        environment="PAPER", account_id=ACCOUNT, symbol=SYMBOL, side="buy",
        quantity="50", payload=intent.model_dump(mode="json"),
        risk_decision={"policy_hash": "b" * 32, "reason_codes": [],
                       "allow": True, "limits_snapshot": {},
                       "decision_at": NOW.isoformat()},
        fence_epoch=stack["token"].epoch,
    )
    return intent


class TestClaimCasOneShot:
    def test_second_claim_returns_none(self, tmp_path):
        s = make_stack(tmp_path)
        intent = seed_intent(s, 1)
        row = s["journal"].claim_send_attempt(
            intent.deterministic_client_order_id, 1, SYMBOL, "buy", "50",
            "PAPER", ACCOUNT)
        assert row is not None
        second = s["journal"].claim_send_attempt(
            intent.deterministic_client_order_id, 1, SYMBOL, "buy", "50",
            "PAPER", ACCOUNT)
        assert second is None
        assert s["journal"].attempt_state_for_coid(
            intent.deterministic_client_order_id) == "SEND_CLAIMED"


class TestA7T2DualLayerBlock:
    def test_risk_deny_after_halt(self, stack):
        stack["ks"].set(reason="test halt", operator_id="a7")
        intent = make_intent(5000)
        d = stack["engine"].evaluate(intent, stack["producer"], symbol=SYMBOL)
        assert not d.allow
        assert "KILL_SWITCH_ENGAGED" in d.reason_codes

    def test_oms_deny_preapproved_after_halt(self, stack):
        intent = make_intent(5001)
        decision = stack["engine"].evaluate(intent, stack["producer"], symbol=SYMBOL)
        assert decision.allow
        stack["ks"].set(reason="test halt", operator_id="a7")
        outcome = stack["oms"].submit(intent, decision, SYMBOL, "buy",
                                      Decimal("50"), stack["token"])
        assert outcome.state == "HALT_NEW_RISK"
        assert stack["broker"].created_orders_by_intent(
            intent.deterministic_client_order_id) == 0
