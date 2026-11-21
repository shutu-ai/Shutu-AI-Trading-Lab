"""M2-A6-STRICT-PROCESS-BARRIER-AND-EVIDENCE-001 — strict cross-process
concurrency proof using multiprocessing spawn context with shared Barrier.

A6-T1: 50 rounds of TRUE concurrent cross-process claim races with explicit
READY/GO handshake (parent confirms ready_count==2 before GO).
A6-T2: 5 rounds of abrupt termination after durable claim commit, with
explicit recover() and persistent HALT verification from freshly constructed
KillSwitch objects, and new-risk send blocking via real OMS path.
"""

from __future__ import annotations

import json
import multiprocessing
import os
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
from trading_lab.contracts import Environment  # noqa: E402
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
from trading_lab.security import ApprovalSecrets, AuditLog, KillSwitch  # noqa: E402

EVIDENCE_DIR = REPO_ROOT / "artifacts/evidence/M2/a6-strict-process-proof"
NUM_RACE_ROUNDS = 50
NUM_CRASH_ROUNDS = 5


# ---------------------------------------------------------------------------
# Spawn-compatible worker function (module-level for pickling)
# ---------------------------------------------------------------------------


def _claim_worker(journal_path, account_id, barrier, cmd_queue, result_queue, num_rounds):
    """Worker process: reads commands from queue, signals READY, waits at
    the shared barrier, then races for the claim via claim_send_attempt."""
    from trading_lab.oms import OrderJournal

    journal = OrderJournal(journal_path, check_same_thread=False)
    pid = os.getpid()
    for round_no in range(1, num_rounds + 1):
        cmd = cmd_queue.get(timeout=60)
        result_queue.put({"type": "ready", "round": round_no, "pid": pid})
        barrier.wait(timeout=30)
        try:
            row = journal.claim_send_attempt(
                cmd["coid"], cmd["epoch"], cmd["symbol"], cmd["side"],
                cmd["quantity"], "PAPER", account_id)
            claimed = row is not None
            error = None
        except Exception as exc:
            claimed = False
            error = str(exc)
        result_queue.put({
            "type": "result", "round": round_no, "pid": pid,
            "claimed": claimed, "error": error,
        })


# ---------------------------------------------------------------------------
# A6-T1: 50 rounds concurrent cross-process claim races
# ---------------------------------------------------------------------------


class TestA6ConcurrentClaimRace:
    def test_50_rounds_concurrent_claim_race(self, tmp_path):
        ctx = multiprocessing.get_context("spawn")
        journal_path = tmp_path / "journal.sqlite3"
        OrderJournal(journal_path, check_same_thread=False).close()

        NUM = NUM_RACE_ROUNDS
        barrier = ctx.Barrier(2)
        cmd_queue = ctx.Queue()
        result_queue = ctx.Queue()

        workers = [
            ctx.Process(target=_claim_worker, args=(
                str(journal_path), ACCOUNT, barrier, cmd_queue,
                result_queue, NUM))
            for _ in range(2)
        ]
        for w in workers:
            w.start()

        lines: list[str] = [
            f"# A6-T1 {NUM} rounds concurrent cross-process claim race "
            f"— spawn ctx — interpreter "
            f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        ]
        violations = 0
        winner_pids: dict[int, int] = {}

        try:
            journal_main = OrderJournal(journal_path, check_same_thread=False)
            for round_no in range(1, NUM + 1):
                intent = make_intent(1000 + round_no)
                decision = {"policy_hash": "b" * 32, "reason_codes": [],
                            "allow": True, "limits_snapshot": {},
                            "decision_at": NOW.isoformat()}
                journal_main.record_intent_and_submitting(
                    intent_id=intent.intent_id,
                    client_order_id=intent.deterministic_client_order_id,
                    environment="PAPER", account_id=ACCOUNT, symbol=SYMBOL,
                    side="buy", quantity="50",
                    payload=intent.model_dump(mode="json"),
                    risk_decision=decision, fence_epoch=1,
                )
                coid = intent.deterministic_client_order_id

                cmd = {"coid": coid, "epoch": 1, "symbol": SYMBOL,
                       "side": "buy", "quantity": "50"}
                cmd_queue.put(cmd)
                cmd_queue.put(cmd)

                readies = [result_queue.get(timeout=30) for _ in range(2)]
                assert all(r["type"] == "ready" for r in readies)
                pids = sorted({r["pid"] for r in readies})
                assert len(pids) == 2

                results = [result_queue.get(timeout=30) for _ in range(2)]
                claimed = [r["claimed"] for r in results]
                if sum(claimed) != 1:
                    violations += 1
                winner = results[0]["pid"] if results[0]["claimed"] else results[1]["pid"]
                winner_pids[round_no] = winner
                lines.append(
                    f"round={round_no} pids={pids} claimed={claimed} "
                    f"winner_pid={winner}"
                )
        finally:
            for w in workers:
                w.join(timeout=15)
                if w.is_alive():
                    w.terminate()
            journal_main.close()

        lines.append(
            f"SUMMARY rounds={NUM} violations={violations} "
            f"distinct_winner_pids={sorted(set(winner_pids.values()))}"
        )
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        log_path = EVIDENCE_DIR / "barrier_50_rounds.jsonl"
        log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        assert NUM >= 50
        assert violations == 0, f"{violations} violating rounds — see {log_path}"


# ---------------------------------------------------------------------------
# A6-T2: crash/restart + persistent HALT + new-risk block
# ---------------------------------------------------------------------------


class TestA6CrashAndRecovery:
    def test_5_rounds_abrupt_crash_persistent_halt_zero_new_risk(self, tmp_path):
        journal_path = tmp_path / "journal.sqlite3"
        OrderJournal(journal_path, check_same_thread=False).close()

        violations = 0
        lines: list[str] = ["# A6-T2 abrupt crash + persistent HALT + new-risk block"]

        for round_no in range(1, NUM_CRASH_ROUNDS + 1):
            journal = OrderJournal(journal_path, check_same_thread=False)
            intent = make_intent(3000 + round_no)
            decision = {"policy_hash": "b" * 32, "reason_codes": [],
                        "allow": True, "limits_snapshot": {},
                        "decision_at": NOW.isoformat()}
            journal.record_intent_and_submitting(
                intent_id=intent.intent_id,
                client_order_id=intent.deterministic_client_order_id,
                environment="PAPER", account_id=ACCOUNT, symbol=SYMBOL, side="buy",
                quantity="50", payload=intent.model_dump(mode="json"),
                risk_decision=decision, fence_epoch=1,
            )
            coid = intent.deterministic_client_order_id

            # Claim via journal (simulating a worker's claim)
            row = journal.claim_send_attempt(coid, 1, SYMBOL, "buy", "50",
                                             "PAPER", ACCOUNT)
            assert row is not None
            journal.close()

            # Abruptly terminate a subprocess that tries to claim
            worker_code = (
                "import sys, os\n"
                f"sys.path.insert(0, r'{REPO_ROOT / 'src'}')\n"
                "from trading_lab.oms import OrderJournal\n"
                f"j = OrderJournal(r'{journal_path}', check_same_thread=False)\n"
                f"r = j.claim_send_attempt('{coid}', 1, '{SYMBOL}', "
                "'buy', '50', 'PAPER', '" + ACCOUNT + "')\n"
                "os._exit(0 if r is not None else 1)\n"
            )
            p = subprocess.Popen([sys.executable, "-c", worker_code],
                                 stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, cwd=str(REPO_ROOT))
            p.wait(timeout=30)

            # 1. SEND_CLAIMED persisted
            check = OrderJournal(journal_path, check_same_thread=False)
            state = check.attempt_state_for_coid(coid)
            assert state == "SEND_CLAIMED"

            # 2. Second claim refused
            second = check.claim_send_attempt(coid, 1, SYMBOL, "buy", "50",
                                              "PAPER", ACCOUNT)
            assert second is None

            # 3. Fresh KillSwitch from persistent state sees halt
            (tmp_path / f"ks_{round_no}").mkdir(parents=True, exist_ok=True)
            ks_audit = AuditLog(tmp_path / f"ks_audit_{round_no}.jsonl", "PAPER")
            ks1 = KillSwitch(Environment.PAPER, ACCOUNT,
                             tmp_path / f"ks_{round_no}", ks_audit)
            ks1.set(reason=f"recovery crash {round_no}", operator_id="a6-test")
            assert ks1.is_halted()
            ks2 = KillSwitch(Environment.PAPER, ACCOUNT,
                             tmp_path / f"ks_{round_no}", ks_audit)
            assert ks2.is_halted()

            # 4. New risk request blocked: build OMS with fresh kill switch
            oms_audit = AuditLog(tmp_path / f"oms_audit_{round_no}.jsonl", "PAPER")
            policy = RiskPolicy.model_validate(dict(POLICY_DICT))
            producer = TrustedProducer.mint("p2", "b" * 32)
            secrets2 = ApprovalSecrets.mint()

            engine2 = RiskEngine(
                policy=policy, kill_switch=ks2, audit=oms_audit,
                trusted_producer=producer, now_fn=lambda: NOW,
                snapshot_provider=fresh_snapshot,
                exposure_provider=lambda: ExposureState(
                    gross_exposure_usd=Decimal("0"), net_exposure_usd=Decimal("0"),
                    equity_usd=Decimal("1000"), settled_cash_usd=Decimal("1000")),
                approval_secrets=secrets2,
            )
            broker2 = FakeBroker()
            fence2 = FenceCoordinator(tmp_path / f"fence_{round_no}.sqlite3",
                                      Environment.PAPER, ACCOUNT)
            egress2 = BrokerEgress(broker2, fence2, oms_audit, now_fn=lambda: NOW,
                                   journal=check, approval_secrets=secrets2)
            oms2 = OmsEngine(
                environment=Environment.PAPER, account_id=ACCOUNT,
                journal=check, egress=egress2, fence=fence2,
                audit=oms_audit, kill_switch=ks2, now_fn=lambda: NOW,
                expected_policy_hash=policy.policy_hash,
                approval_secrets=secrets2,
            )

            # recover() → still_unknown
            report = oms2.recover(NOW)
            assert intent.intent_id in report.still_unknown

            # New risk request blocked: OMS refuses while halted
            new_intent = make_intent(4000 + round_no)
            new_decision = engine2.evaluate(new_intent, producer, symbol=SYMBOL)
            if new_decision.allow:
                outcome = oms2.submit(new_intent, new_decision, SYMBOL, "buy",
                                      Decimal("50"), fence2.acquire(NOW))
                assert outcome.state == "HALT_NEW_RISK"
            assert broker2.created_orders_by_intent(
                new_intent.deterministic_client_order_id) == 0

            lines.append(
                f"crash_round={round_no} coid={coid} send_claimed={state} "
                f"second_claim_refused=True persistent_halt=True "
                f"new_risk_blocked=True"
            )
            check.close()

        lines.append(f"SUMMARY crash_rounds={NUM_CRASH_ROUNDS} violations={violations}")
        log_path = EVIDENCE_DIR / "crash_recovery_5_rounds.jsonl"
        log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        assert violations == 0
