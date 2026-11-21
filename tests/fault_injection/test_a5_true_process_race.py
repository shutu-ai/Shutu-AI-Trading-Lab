"""M2-A5-TRUE-PROCESS-RACE-AND-M3-GATED-001 — true concurrent cross-process
send-claim race tests (A5-T1) and abrupt crash recovery (A5-T2).

Key fix from the previous test: the parent sends commands to BOTH workers'
stdin BEFORE reading from EITHER stdout, so both workers race for the claim
concurrently. The previous test wrote to worker A, waited for A's result,
then wrote to worker B — which was sequential replay, not a race.
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

from helpers_m2 import ACCOUNT, NOW, SYMBOL, make_intent  # noqa: E402

from trading_lab.contracts import Environment  # noqa: E402
from trading_lab.oms import FenceCoordinator, OrderJournal  # noqa: E402

EVIDENCE_DIR = REPO_ROOT / "artifacts/evidence/M2/a5-true-process-race"
POLICY_DICT = {
    "version": 1, "environment": Environment.PAPER,
    "account_id": ACCOUNT, "policy_hash": "b" * 32,
    "max_gross_exposure_pct": __import__("decimal").Decimal("60"),
    "max_net_exposure_pct": __import__("decimal").Decimal("60"),
    "max_single_symbol_pct": __import__("decimal").Decimal("30"),
    "max_single_order_notional_usd": __import__("decimal").Decimal("100"),
    "max_daily_loss_pct": __import__("decimal").Decimal("2"),
    "max_peak_to_trough_drawdown_pct": __import__("decimal").Decimal("6"),
    "max_abnormal_orders_per_minute": 8,
    "max_market_bar_age_seconds": 120,
    "max_account_snapshot_age_seconds": 30,
    "max_broker_order_ack_wait_seconds": 10,
    "require_settled_funds": True, "allow_margin": False,
    "allow_short": False, "allowed_symbols": ("SPY", "QQQ", "IWM"),
    "recovery_requires": ("operator_release_after_incident",),
}

CLAIM_WORKER_CODE = """
import sys, json, os
sys.path.insert(0, r'{src}')
from trading_lab.oms import OrderJournal

journal_path, account = sys.argv[1], sys.argv[2]
journal = OrderJournal(journal_path, check_same_thread=False)
print(json.dumps({{"type": "ready", "pid": os.getpid()}}), flush=True)
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    cmd = json.loads(line)
    try:
        row = journal.claim_send_attempt(
            cmd["coid"], cmd["epoch"], cmd["symbol"], cmd["side"], cmd["quantity"],
            "PAPER", account)
        claimed = row is not None
        error = str(e) if False else None
    except Exception as e:
        claimed = False
        error = str(e)
    print(json.dumps({{"type": "result", "pid": os.getpid(),
                      "claimed": claimed, "error": error}}), flush=True)
    if cmd.get("action") == "claim_exit":
        sys.exit(0)
"""


class ClaimWorker:
    """Long-lived subprocess for concurrent claim racing."""

    def __init__(self, journal_path: Path, name: str):
        code = CLAIM_WORKER_CODE.format(src=str(REPO_ROOT / "src"))
        self.proc = subprocess.Popen(
            [sys.executable, "-c", code, str(journal_path), ACCOUNT],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, cwd=str(REPO_ROOT),
        )
        self.name = name
        first = self.proc.stdout.readline()
        if not first.strip():
            err = self.proc.stderr.read()
            raise RuntimeError(f"worker {name} died at startup: {err[:500]}")
        self.pid = json.loads(first)["pid"]

    def send_claim(self, coid: str, epoch: int) -> None:
        """Write claim command WITHOUT waiting for the result."""
        import json as _json

        cmd = _json.dumps({"coid": coid, "epoch": epoch, "symbol": SYMBOL,
                           "side": "buy", "quantity": "50"})
        self.proc.stdin.write(cmd + "\n")
        self.proc.stdin.flush()

    def read_result(self) -> dict:
        import json as _json

        return _json.loads(self.proc.stdout.readline())

    def close(self) -> None:
        try:
            self.proc.stdin.close()
        except Exception:
            pass
        try:
            self.proc.wait(timeout=10)
        except Exception:
            self.proc.kill()

    def terminate(self) -> None:
        self.proc.terminate()


def seeded_intent(journal: OrderJournal, seq: int, fence_epoch: int = 1):
    """Persist a durable SUBMITTING intent + attempt carrying a valid HMAC
    decision (for eligibility). Returns the intent."""
    intent = make_intent(seq)
    decision = {"policy_hash": "b" * 32,
                "limits_snapshot": {"approval_seal": "0" * 64,
                                    "decision_expires_at": NOW.isoformat()},
                "decision_at": NOW.isoformat()}
    journal.record_intent_and_submitting(
        intent_id=intent.intent_id,
        client_order_id=intent.deterministic_client_order_id,
        environment="PAPER", account_id=ACCOUNT, symbol=SYMBOL, side="buy",
        quantity="50", payload=intent.model_dump(mode="json"),
        risk_decision=decision, fence_epoch=fence_epoch,
    )
    return intent


# ---------------------------------------------------------------------------
# A5-T1: >=50 rounds of TRUE concurrent cross-process claim races
# ---------------------------------------------------------------------------


class TestA5TrueProcessRace:
    def test_50_rounds_concurrent_cross_process_claim(self, tmp_path):
        journal_path = tmp_path / "journal.sqlite3"
        lines: list[str] = [
            f"# A5-T1 50 rounds of concurrent cross-process claim races "
            f"— interpreter {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        ]

        worker_a = ClaimWorker(journal_path, "A")
        worker_b = ClaimWorker(journal_path, "B")
        lines.append(f"workerA pid={worker_a.pid} workerB pid={worker_b.pid} "
                     f"distinct_pids={worker_a.pid != worker_b.pid}")
        assert worker_a.pid != worker_b.pid

        violations = 0
        winner_pids = {}
        journal = OrderJournal(journal_path, check_same_thread=False)
        try:
            for round_no in range(1, 51):
                journal2 = OrderJournal(journal_path, check_same_thread=False)
                intent = seeded_intent(journal2, 1000 + round_no)
                coid = intent.deterministic_client_order_id
                journal2.close()

                # Send claim command to BOTH workers BEFORE reading either
                # result — this is the concurrency guarantee.
                worker_a.send_claim(coid, 1)
                worker_b.send_claim(coid, 1)

                res_a = worker_a.read_result()
                res_b = worker_b.read_result()

                claimed = [res_a["claimed"], res_b["claimed"]]
                if sum(claimed) != 1:
                    violations += 1
                winner = res_a["pid"] if res_a["claimed"] else res_b["pid"]
                winner_pids[round_no] = winner
                lines.append(
                    f"round={round_no} coid={coid} pidA={res_a['pid']} "
                    f"pidB={res_b['pid']} claimed={claimed} winner_pid={winner} "
                    f"errors=[{res_a.get('error')},{res_b.get('error')}]"
                )
        finally:
            worker_a.close()
            worker_b.close()

        lines.append(
            f"SUMMARY rounds=50 violations={violations} "
            f"distinct_winner_pids={sorted(set(winner_pids.values()))}"
        )
        log_path = EVIDENCE_DIR / "process_concurrent_50.log"
        log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        assert violations == 0, f"{violations} violating rounds — see {log_path}"


# ---------------------------------------------------------------------------
# A5-T2: abrupt termination after claim, recovery with explicit recover()
# ---------------------------------------------------------------------------


class TestA5AbruptCrashRecovery:
    def test_abrupt_crash_and_recovery(self, tmp_path):
        import json as _json
        import datetime as dt

        from trading_lab.security import AuditLog, KillSwitch
        from trading_lab.oms import OmsEngine, BrokerEgress
        from trading_lab.brokers import FakeBroker
        from trading_lab.risk import RiskEngine, RiskPolicy, TrustedProducer, ExposureState
        from trading_lab.security import ApprovalSecrets

        journal_path = tmp_path / "journal.sqlite3"
        crash_results = []

        for round_no in range(1, 6):
            ks_audit = AuditLog(tmp_path / f"ks_audit_{round_no}.jsonl", "PAPER")
            ks = KillSwitch(Environment.PAPER, ACCOUNT, tmp_path / f"ks_{round_no}", ks_audit)
            journal = OrderJournal(journal_path, check_same_thread=False)
            fence = FenceCoordinator(tmp_path / f"fence_{round_no}.sqlite3",
                                     Environment.PAPER, ACCOUNT)
            intent = seeded_intent(journal, 3000 + round_no)
            coid = intent.deterministic_client_order_id

            # Claim from a subprocess that is abruptly terminated.
            claimer = ClaimWorker(journal_path, f"C{round_no}")
            claimer.send_claim(coid, 1)
            res = claimer.read_result()
            assert res["claimed"] is True
            claimer.proc.terminate()
            claimer.proc.wait(timeout=10)

            # SEND_CLAIMED persisted
            state = journal.attempt_state_for_coid(coid)
            assert state == "SEND_CLAIMED"

            # Second claim must NOT re-grant
            second = journal.claim_send_attempt(coid, 1, SYMBOL, "buy", "50",
                                                "PAPER", ACCOUNT)
            assert second is None

            # Recovery: rebuild OMS stack on same journal, call recover()
            audit = AuditLog(tmp_path / f"audit_{round_no}.jsonl", "PAPER")
            policy = RiskPolicy.model_validate(dict(POLICY_DICT))
            producer = TrustedProducer.mint("portfolio_agg_v1", "a" * 32)
            secrets = ApprovalSecrets.mint()

            def snap():
                from helpers_m2 import fresh_snapshot

                return fresh_snapshot()

            engine = RiskEngine(policy=policy, kill_switch=ks, audit=audit,
                                trusted_producer=producer, now_fn=lambda: NOW,
                                snapshot_provider=snap,
                                exposure_provider=lambda: ExposureState(
                                    gross_exposure_usd=Decimal("0"),
                                    net_exposure_usd=Decimal("0"),
                                    equity_usd=Decimal("1000"),
                                    settled_cash_usd=Decimal("1000")),
                                approval_secrets=secrets)
            broker = FakeBroker()
            egress = BrokerEgress(broker, fence, audit, now_fn=lambda: NOW,
                                  journal=journal, approval_secrets=secrets)
            oms = OmsEngine(
                environment=Environment.PAPER, account_id=ACCOUNT,
                journal=journal, egress=egress, fence=fence, audit=audit,
                kill_switch=ks, now_fn=lambda: NOW,
                expected_policy_hash=policy.policy_hash,
                approval_secrets=secrets,
            )

            report = oms.recover(NOW)
            assert intent.intent_id in report.still_unknown
            assert ks.is_halted()

            # Operator unlock still requires explicit authorization
            with pytest.raises(Exception):
                oms.operator_unlock("op", "")

            crash_results.append({
                "round": round_no, "coid": coid,
                "db_state": state, "still_unknown": True, "halted": True,
            })
            journal.close()

        log_path = tmp_path / "abrupt_crash_recovery.log"
        log_path.write_text("\n".join(_json.dumps(r) for r in crash_results) + "\n",
                            encoding="utf-8")
        assert all(r["halted"] for r in crash_results)
