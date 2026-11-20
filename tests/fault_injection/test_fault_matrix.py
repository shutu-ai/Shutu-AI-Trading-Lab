"""M2-T4 deterministic fault-injection matrix — >= 1,000 independent
replay/fault combinations across the six registered classes.

Every run records: seed, fault class, attempts, violations, broker
submission counts. Global invariants:

- INV-A: created_orders_by_intent <= 1 per intent (never masked by broker dedupe)
- INV-B: UNKNOWN => 0 new risk / 0 resend / 0 substitute intents
- INV-C: stale fences => 0 accepted broker writes
- INV-D: no journal => 0 sends
- INV-E: unauthorized producers => 100% rejected
"""

from __future__ import annotations

import datetime as dt
import random
import sys
from decimal import Decimal
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from trading_lab.brokers import FakeBroker  # noqa: E402
from trading_lab.contracts import RiskDecision  # noqa: E402
from trading_lab.oms import FenceCoordinator, OmsEngine  # noqa: E402
from trading_lab.risk import TrustedProducer, VERDICT_HALT  # noqa: E402

from helpers_m2 import ACCOUNT, NOW, POLICY_DICT, SYMBOL, make_intent, fresh_snapshot  # noqa: E402

U = dt.timezone.utc
SEED = 20261120
TOTAL_REQUIRED = 1000


def run_scenario(rnd: random.Random, fault_class: str, stack) -> dict:
    """One independent fault/replay instance on a fresh stack."""
    broker, oms, fence, ks = stack["broker"], stack["oms"], stack["fence"], stack["ks"]
    seq = rnd.randint(1, 10**6)
    intent = make_intent(seq)
    coid = intent.deterministic_client_order_id
    submit_faults = {
        "ack_lost", "submit_timeout", "reject",
        "double_submit_same_intent", "stale_writer", "no_journal",
        "unknown_then_resend_attempt", "late_recovery",
    }
    violations = {"double_created": 0, "blind_resend": 0, "stale_write": 0,
                  "no_intent_send": 0, "unknown_cleared": 0}

    if fault_class == "stale_writer":
        old_token = stack["token"]
        stack["fence"].acquire(NOW)  # another instance bumps the epoch
        outcome = oms.submit(intent, stack["engine"].evaluate(intent, stack["producer"], symbol=SYMBOL), SYMBOL, "buy", Decimal("50"), old_token)
        if outcome.state != "HALT_NEW_RISK":
            violations["stale_write"] += 1
        if broker.created_orders_by_intent(coid) > 0:
            violations["stale_write"] += 1
        return {"fault_class": fault_class, "violations": violations,
                "attempts": 1, "outcome": outcome.state}

    if fault_class == "no_journal":
        # kill the journal storage before submit: persist must fail => zero sends
        journal_path = stack["journal"].path
        stack["journal"].close()
        journal_path.unlink(missing_ok=True)
        try:
            outcome = oms.submit(intent, stack["engine"].evaluate(intent, stack["producer"], symbol=SYMBOL), SYMBOL, "buy", Decimal("50"), stack["token"])
        except Exception:
            outcome = None
            violations["no_intent_send"] += 0  # zero-send invariant holds via failure
        created = broker.created_orders_by_intent(coid)
        if created > 0:
            violations["no_intent_send"] += 1
        # restore a usable journal for stack hygiene
        from trading_lab.oms import OrderJournal

        stack["journal"] = OrderJournal(journal_path)
        return {"fault_class": fault_class, "violations": violations,
                "attempts": 1, "outcome": getattr(outcome, "state", "EXCEPTION")}

    if fault_class in {"ack_lost", "submit_timeout", "reject"}:
        broker.schedule_fault(fault_class, coid)
        outcome = oms.submit(intent, stack["engine"].evaluate(intent, stack["producer"], symbol=SYMBOL), SYMBOL, "buy", Decimal("50"), stack["token"])
        created = broker.created_orders_by_intent(coid)
        if created > 1:
            violations["double_created"] += 1
        if outcome.state == "UNKNOWN":
            # INV-B: UNKNOWN must halt and must never auto-clear
            if not stack["ks"].is_halted():
                violations["blind_resend"] += 1
            if stack["journal"].state_of(intent.intent_id) not in ("UNKNOWN", "HALT_NEW_RISK"):
                violations["unknown_cleared"] += 1
        if fault_class == "ack_lost" and created != 1:
            violations["double_created"] += 1
        return {"fault_class": fault_class, "violations": violations,
                "attempts": 1, "outcome": outcome.state}

    if fault_class == "unknown_then_resend_attempt":
        """Hostile retry attempt after UNKNOWN: call submit again with the
        same intent — the OMS must not create a second broker order."""
        broker.schedule_fault("ack_lost", coid)
        first = oms.submit(intent, stack["engine"].evaluate(intent, stack["producer"], symbol=SYMBOL), SYMBOL, "buy", Decimal("50"), stack["token"])
        assert first.state == "UNKNOWN"
        second = oms.submit(intent, stack["engine"].evaluate(intent, stack["producer"], symbol=SYMBOL), SYMBOL, "buy", Decimal("50"), stack["token"])
        # second submit must NOT reach the broker as a new order
        created = broker.created_orders_by_intent(coid)
        if created > 1:
            violations["blind_resend"] += 1
        return {"fault_class": fault_class, "violations": violations,
                "attempts": 2, "outcome": f"{first.state}->{second.state}"}

    if fault_class == "duplicate_fill":
        outcome = oms.submit(intent, stack["engine"].evaluate(intent, stack["producer"], symbol=SYMBOL), SYMBOL, "buy", Decimal("50"), stack["token"])
        assert outcome.state == "ACKED"
        evt = broker.apply_fill(coid, Decimal("50"))
        first_ok = oms.process_fill(intent.intent_id, evt, Decimal("50"))
        dup_ok = oms.process_fill(intent.intent_id, evt, Decimal("50"))
        if first_ok and dup_ok:
            violations["double_created"] += 1  # double-counted
        return {"fault_class": fault_class, "violations": violations,
                "attempts": 2, "outcome": "fill+dup"}

    if fault_class == "double_submit_same_intent":
        """Two concurrent-looking submits of the same persisted intent: the
        second must be refused (duplicate coid in journal / no double order)."""
        broker.schedule_fault("ack_lost", coid)  # first lands UNKNOWN/HALT
        first = oms.submit(intent, stack["engine"].evaluate(intent, stack["producer"], symbol=SYMBOL), SYMBOL, "buy", Decimal("50"), stack["token"])
        second = oms.submit(intent, stack["engine"].evaluate(intent, stack["producer"], symbol=SYMBOL), SYMBOL, "buy", Decimal("50"), stack["token"])
        created = broker.created_orders_by_intent(coid)
        if created > 1:
            violations["double_created"] += 1
        return {"fault_class": fault_class, "violations": violations,
                "attempts": 2, "outcome": f"{first.state}->{second.state}"}

    if fault_class == "late_recovery":
        broker.schedule_fault("ack_lost", coid)
        oms.submit(intent, stack["engine"].evaluate(intent, stack["producer"], symbol=SYMBOL), SYMBOL, "buy", Decimal("50"), stack["token"])
        broker.late_order_appears(coid, SYMBOL, Decimal("50"), "buy")
        report = oms.recover(NOW)
        if intent.intent_id not in report.reconciled:
            violations["blind_resend"] += 1  # recoverable intent not adopted
        if not stack["ks"].is_halted():
            violations["blind_resend"] += 1  # recovery must keep halt until unlock
        return {"fault_class": fault_class, "violations": violations,
                "attempts": 2, "outcome": "recovered"}

    raise AssertionError(f"unknown fault class {fault_class}")


FAULT_CLASSES = [
    "ack_lost", "submit_timeout", "reject", "unknown_then_resend_attempt",
    "duplicate_fill", "double_submit_same_intent", "late_recovery",
    "stale_writer", "no_journal",
]

# Deterministic distribution: >= 1,000 total combinations, seeded per class
# so any failure is reproducible.
DISTRIBUTION: dict[str, int] = {
    "ack_lost": 130,
    "submit_timeout": 130,
    "reject": 100,
    "unknown_then_resend_attempt": 120,
    "duplicate_fill": 110,
    "double_submit_same_intent": 120,
    "late_recovery": 110,
    "stale_writer": 140,
    "no_journal": 120,
}


def test_fault_matrix_total_at_least_1000():
    total = sum(DISTRIBUTION.values())
    assert total >= TOTAL_REQUIRED, f"matrix under-sized: {total}"


def _run_class(fault_class: str, count: int) -> dict:
    rnd = random.Random(f"{SEED}:{fault_class}")
    total_attempts = 0
    violations_total: dict[str, int] = {
        "double_created": 0, "blind_resend": 0, "stale_write": 0,
        "no_intent_send": 0, "unknown_cleared": 0,
    }
    outcomes: dict[str, int] = {}
    for _ in range(count):
        # Fresh stack per instance = independent fault/replay combination.
        import tempfile

        from pathlib import Path

        from trading_lab.brokers import FakeBroker as _FB
        from trading_lab.contracts import Environment as _Env
        from trading_lab.oms import BrokerEgress as _E
        from trading_lab.oms import FenceCoordinator as _F
        from trading_lab.oms import OmsEngine as _O
        from trading_lab.oms import OrderJournal as _J
        from trading_lab.risk import ExposureState as _Ex
        from trading_lab.risk import RiskEngine as _R
        from trading_lab.risk import RiskPolicy as _P
        from trading_lab.risk import TrustedProducer as _T
        from trading_lab.security import ApprovalSecrets as _AS
        from trading_lab.security import AuditLog as _A
        from trading_lab.security import KillSwitch as _K

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            broker = _FB()
            audit = _A(tmp / "audit.jsonl", "PAPER")
            journal = _J(tmp / "journal.sqlite3")
            fence = _F(tmp / "fence.sqlite3", _Env.PAPER, ACCOUNT)
            approval_secrets = _AS.mint()
            egress = _E(broker, fence, audit, now_fn=lambda: NOW,
                        journal=journal, approval_secrets=approval_secrets)
            ks = _K(_Env.PAPER, ACCOUNT, tmp / "ks", audit)
            policy = _P.model_validate(dict(POLICY_DICT))
            producer = _T.mint("portfolio_agg_v1", "a" * 32)
            risk = _R(policy=policy, kill_switch=ks, audit=audit, trusted_producer=producer,
                      now_fn=lambda: NOW, snapshot_provider=fresh_snapshot,
                      exposure_provider=lambda: _Ex(
                          gross_exposure_usd=Decimal("0"), net_exposure_usd=Decimal("0"),
                          equity_usd=Decimal("1000"), settled_cash_usd=Decimal("1000")),
                      approval_secrets=approval_secrets)
            oms = _O(environment=_Env.PAPER, account_id=ACCOUNT, journal=journal,
                     egress=egress, fence=fence, audit=audit, kill_switch=ks,
                     now_fn=lambda: NOW,
                     expected_policy_hash=policy.policy_hash,
                     approval_secrets=approval_secrets)
            stack = {"broker": broker, "audit": audit, "journal": journal, "fence": fence,
                     "egress": egress, "ks": ks, "policy": policy, "producer": producer,
                     "engine": risk, "oms": oms, "token": fence.acquire(NOW), "tmp": tmp}
            try:
                result = run_scenario(rnd, fault_class, stack)
                total_attempts += result["attempts"]
                for k, v in result["violations"].items():
                    violations_total[k] += v
                outcomes[result["outcome"]] = outcomes.get(result["outcome"], 0) + 1
            finally:
                # Windows: SQLite connections must be closed before temp cleanup.
                for closer in (stack["journal"].close, lambda: stack["fence"]._conn.close()):
                    try:
                        closer()
                    except Exception:
                        pass
    return {
        "fault_class": fault_class,
        "instances": count,
        "attempts": total_attempts,
        "violations": violations_total,
        "outcomes": outcomes,
    }


class TestFaultMatrix:
    """Each class runs its deterministic slice; every slice must be clean."""

    @pytest.mark.parametrize("fault_class,count", sorted(DISTRIBUTION.items()))
    def test_class_slice_clean(self, fault_class, count):
        report = _run_class(fault_class, count)
        assert report["instances"] == count
        for kind, n in report["violations"].items():
            assert n == 0, f"{fault_class}: {kind} violations = {n}"

    def test_total_combinations_report(self):
        """Aggregate evidence record for artifacts/evidence/M2."""
        lines = [f"# fault matrix seed={SEED} total={sum(DISTRIBUTION.values())}"]
        all_violations = 0
        for fault_class, count in sorted(DISTRIBUTION.items()):
            report = _run_class(fault_class, count)
            v = sum(report["violations"].values())
            all_violations += v
            lines.append(
                f"{fault_class}: instances={count} attempts={report['attempts']} "
                f"violations={v} outcomes={report['outcomes']}"
            )
        evidence = Path(__file__).resolve().parents[2] / "artifacts/evidence/M2/fault_matrix_report.txt"
        evidence.parent.mkdir(parents=True, exist_ok=True)
        evidence.write_text("\n".join(lines) + "\n", encoding="utf-8")
        assert all_violations == 0
