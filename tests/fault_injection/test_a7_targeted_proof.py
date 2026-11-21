"""M2-A7-CLAIM-OWNER-CRASH-AND-RECOVERY-PROOF-001 (restored, M3-R1-T1).

A7-T1 (P0, 5 rounds): true claim-holder crash — subprocess claims
        SEND_CLAIMED then os._exit(37); fresh OMS recover() automatically
        triggers global HALT; new risk blocked through real OMS path.
        Restored verbatim from the verified git baseline f27892d after the
        regression at 3505799 deleted it (347 -> 343). Post-recovery
        blocking is now UNCONDITIONAL (no `if allow` escape): layer 1 =
        RiskEngine refuses with KILL_SWITCH_ENGAGED; layer 2 = a decision
        legally sealed BEFORE the halt is refused by oms.submit() with
        HALT_NEW_RISK and zero broker side effects.
A7-T2 (P0): RiskEngine and OMS dual-layer block (unconditional).
Kept from 3505799 (independent value, does NOT replace T1):
        TestClaimCasOneShot — in-process claim CAS is one-shot.
"""

from __future__ import annotations

import json
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

from helpers_m2 import (  # noqa: E402
    ACCOUNT,
    NOW,
    POLICY_DICT,
    SYMBOL,
    fresh_snapshot,
    make_intent,
)

from trading_lab.brokers import FakeBroker  # noqa: E402
from trading_lab.contracts import Environment, RiskDecision  # noqa: E402
from trading_lab.oms import (  # noqa: E402
    BrokerEgress,
    FenceCoordinator,
    OmsEngine,
    OrderJournal,
)
from trading_lab.risk import (  # noqa: E402
    ExposureState,
    RiskEngine,
    RiskPolicy,
    TrustedProducer,
)
from trading_lab.security import (  # noqa: E402
    ApprovalSecrets,
    AuditLog,
    KillSwitch,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_oms_stack(journal_path: Path) -> dict:
    """Build a complete OMS stack on the given journal path."""
    tmp = journal_path.parent
    broker = FakeBroker()
    audit = AuditLog(tmp / "audit.jsonl", "PAPER")
    journal = OrderJournal(journal_path, check_same_thread=False)
    fence = FenceCoordinator(tmp / "fence.sqlite3", Environment.PAPER,
                             ACCOUNT, check_same_thread=False)
    ks = KillSwitch(Environment.PAPER, ACCOUNT, tmp / "ks", audit)
    policy = RiskPolicy.model_validate(dict(POLICY_DICT))
    producer = TrustedProducer.mint("portfolio_agg_v1", "a" * 32)
    secrets = ApprovalSecrets.mint()
    engine = RiskEngine(
        policy=policy, kill_switch=ks, audit=audit, trusted_producer=producer,
        now_fn=lambda: NOW, snapshot_provider=fresh_snapshot,
        exposure_provider=lambda: ExposureState(
            gross_exposure_usd=Decimal("0"), net_exposure_usd=Decimal("0"),
            equity_usd=Decimal("1000"), settled_cash_usd=Decimal("1000")),
        approval_secrets=secrets,
    )
    egress = BrokerEgress(broker, fence, audit, now_fn=lambda: NOW,
                          journal=journal, approval_secrets=secrets)
    oms = OmsEngine(
        environment=Environment.PAPER, account_id=ACCOUNT, journal=journal,
        egress=egress, fence=fence, audit=audit, kill_switch=ks,
        now_fn=lambda: NOW, expected_policy_hash=policy.policy_hash,
        approval_secrets=secrets,
    )
    token = fence.acquire(NOW)
    return {"broker": broker, "audit": audit, "journal": journal,
            "fence": fence, "ks": ks, "engine": engine, "oms": oms,
            "token": token, "producer": producer, "secrets": secrets}


def make_stack(tmp: Path) -> dict:
    """Thin wrapper for in-process tests (fixed journal name)."""
    return _make_oms_stack(tmp / "journal.sqlite3")


def seed_intent(stack: dict, seq: int):
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


# ---------------------------------------------------------------------------
# A7-T1: claim-holder crash + automatic recovery HALT (5 rounds)
# ---------------------------------------------------------------------------


class TestA7T1ClaimHolderCrash:
    """P0 (5 rounds): the claim-winning subprocess abruptly terminates via
    os._exit(37) after durable SEND_CLAIMED commit. A fresh OMS stack with
    a fresh KillSwitch calls recover() which AUTOMATICALLY triggers global
    HALT. New risk is then blocked UNCONDITIONALLY through both real
    layers: the RiskEngine refuses to approve, and a decision that was
    legally sealed BEFORE the halt is refused by oms.submit() with zero
    broker side effects."""

    @pytest.mark.parametrize("round_no", range(1, 6))
    def test_claim_holder_crash_auto_halt(self, tmp_path, round_no):
        journal_path = tmp_path / f"journal_{round_no}.sqlite3"

        # --- Phase 1: Seed intent + attempt (single-threaded setup) ---
        stack = _make_oms_stack(journal_path)
        intent = make_intent(3000 + round_no)
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
        coid = intent.deterministic_client_order_id

        # Pre-approve a SECOND intent NOW — before any crash/halt exists —
        # so layer 2 can prove OMS refuses even a legally sealed decision.
        pre_intent = make_intent(4000 + round_no)
        pre_decision = stack["engine"].evaluate(
            pre_intent, stack["producer"], symbol=SYMBOL)
        assert pre_decision.allow, (
            "pre-halt decision must be a legal approval for this proof")

        # --- Phase 2: subprocess claims then crashes with os._exit(37) ---
        fact_path = str(tmp_path / f"fact_{round_no}.json")
        src_dir = str(REPO_ROOT / "src")
        worker_code = (
            "import sys, os, json\n"
            f"sys.path.insert(0, r'{src_dir}')\n"
            "from trading_lab.oms import OrderJournal\n"
            f"journal = OrderJournal(r'{journal_path}', check_same_thread=False)\n"
            f"row = journal.claim_send_attempt(\n"
            f"    '{coid}', 1, '{SYMBOL}', 'buy', '50',\n"
            f"    'PAPER', '{ACCOUNT}')\n"
            f"with open(r'{fact_path}', 'w') as fh:\n"
            f"    json.dump({{'claimed': row is not None, 'pid': os.getpid()}}, fh)\n"
            f"os._exit(37)\n"
        )
        proc = subprocess.Popen(
            [sys.executable, "-c", worker_code],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, cwd=str(REPO_ROOT),
        )
        exit_code = proc.wait(timeout=30)
        assert exit_code == 37, f"expected os._exit(37), got {exit_code}"
        fact = json.loads(Path(fact_path).read_text(encoding="utf-8"))
        assert fact["claimed"] is True

        # Verify SEND_CLAIMED persisted (from fresh connection)
        check = OrderJournal(journal_path, check_same_thread=False)
        assert check.attempt_state_for_coid(coid) == "SEND_CLAIMED"
        check.close()

        # --- Phase 3: FRESH OMS stack, NO pre-set HALT, recover() ---
        stack = _make_oms_stack(journal_path)
        assert not stack["ks"].is_halted(), (
            "pre-recovery KillSwitch must NOT be halted"
        )

        report = stack["oms"].recover(NOW)
        assert intent.intent_id in report.still_unknown

        # POST-RECOVERY: HALT triggered automatically by recover()
        assert stack["ks"].is_halted()

        # --- Layer 1 (unconditional): RiskEngine refuses new risk ---
        new_decision = stack["engine"].evaluate(
            pre_intent, stack["producer"], symbol=SYMBOL)
        assert not new_decision.allow, (
            "RiskEngine must refuse after automatic recovery HALT")
        assert "KILL_SWITCH_ENGAGED" in new_decision.reason_codes

        # --- Layer 2 (unconditional): OMS refuses the PRE-APPROVED decision ---
        outcome = stack["oms"].submit(
            pre_intent, pre_decision, SYMBOL, "buy",
            Decimal("50"), stack["token"])
        assert outcome.state == "HALT_NEW_RISK"
        assert stack["broker"].created_orders_by_intent(
            pre_intent.deterministic_client_order_id) == 0


# ---------------------------------------------------------------------------
# Kept from 3505799: in-process claim CAS one-shot (independent value)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# A7-T2: Risk vs OMS dual-layer block
# ---------------------------------------------------------------------------


class TestA7T2DualLayerBlock:
    def test_risk_deny_after_halt(self, stack):
        stack["ks"].set(reason="test halt", operator_id="a7")
        intent = make_intent(5000)
        d = stack["engine"].evaluate(intent, stack["producer"], symbol=SYMBOL)
        assert not d.allow
        assert "KILL_SWITCH_ENGAGED" in d.reason_codes

    def test_oms_deny_preapproved_after_halt(self, stack):
        """HALT 前生成有效密封决策 → HALT 后 OMS.submit() → HALT_NEW_RISK + 0 port。"""
        intent = make_intent(5001)
        decision = stack["engine"].evaluate(intent, stack["producer"], symbol=SYMBOL)
        assert decision.allow
        stack["ks"].set(reason="test halt", operator_id="a7")
        outcome = stack["oms"].submit(intent, decision, SYMBOL, "buy",
                                      Decimal("50"), stack["token"])
        assert outcome.state == "HALT_NEW_RISK"
        assert stack["broker"].created_orders_by_intent(
            intent.deterministic_client_order_id) == 0
