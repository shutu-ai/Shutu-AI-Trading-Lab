"""M2-FINAL-SEND-CLAIM-AND-M3-GATED-001 (A) — controlled race tests for the
concurrent send-claim window.

A-RED1: two threads, same journal/coid/fence, Barrier-synchronized
        eligibility checks -> at most ONE real port entry (counted at the
        port boundary, not via FakeBroker dedupe).
A-RED2: two REAL OS processes race the same journal send claim; per-process
        result files carry the evidence (no in-process counters).
A-RED3: claim committed, crash before the port call -> recovery treats it
        conservatively (UNKNOWN/HALT), the claim is never re-granted.
A-RED4: direct egress calls on non-SUBMITTING intents / expired fence ->
        refused, zero port entries, existing orders untouched.
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
import sys
import threading
from decimal import Decimal
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

from helpers_m2 import ACCOUNT, NOW, SYMBOL, make_intent  # noqa: E402

from trading_lab.contracts import Environment  # noqa: E402
from trading_lab.oms import FenceCoordinator, OrderJournal  # noqa: E402


def persist_claimable_intent(stack, seq: int = 900, fence_epoch: int = 1):
    """A durable SUBMITTING intent + attempt carrying a REAL engine-sealed
    decision at ``fence_epoch`` — the pre-state two racers would both pass a
    SELECT-only eligibility check on."""
    intent = make_intent(seq)
    decision = stack["engine"].evaluate(intent, stack["producer"], symbol=SYMBOL)
    assert decision.allow
    stack["journal"].record_intent_and_submitting(
        intent_id=intent.intent_id,
        client_order_id=intent.deterministic_client_order_id,
        environment="PAPER", account_id=ACCOUNT, symbol=SYMBOL, side="buy",
        quantity="50", payload=intent.model_dump(mode="json"),
        risk_decision=decision.model_dump(mode="json"), fence_epoch=fence_epoch,
    )
    return intent


def sealed(stack, intent):
    return stack["engine"].evaluate(intent, stack["producer"], symbol=SYMBOL)


class TestARed1ThreadRace:
    def test_barrier_synced_eligibility_two_port_entries_max_one(self, stack):
        """受控竞争：Barrier 使两次资格检查同时完成。整改前 SELECT-only 检查
        双双通过 → 两次真实 port 进入（RED）；修复后原子 claim → 至多 1 次。"""
        import threading

        from trading_lab.oms import BrokerEgress as _E

        # Cross-thread sqlite connections: the racers run on worker threads,
        # so the journal/fence must opt out of thread locking — otherwise the
        # test would vacuously pass on unrelated ProgrammingErrors.
        journal = OrderJournal(stack["journal"].path, check_same_thread=False)
        fence = FenceCoordinator(stack["fence"].path, Environment.PAPER, ACCOUNT,
                                 check_same_thread=False)
        stack["egress"] = _E(stack["broker"], fence, stack["audit"], now_fn=lambda: NOW,
                             journal=journal,
                             approval_secrets=stack["engine"]._approval_secrets)  # noqa: SLF001
        token = fence.acquire(NOW)
        intent = persist_claimable_intent(stack, fence_epoch=token.epoch)
        coid = intent.deterministic_client_order_id

        entry_count = {"n": 0}
        lock = threading.Lock()
        original = stack["broker"].submit_order

        def counting_submit(*args):
            with lock:
                entry_count["n"] += 1
            return original(*args)

        stack["broker"].submit_order = counting_submit  # type: ignore[method-assign]

        barrier = threading.Barrier(2, timeout=10)
        # The eligibility gate: claim_send_attempt when available (post-fix),
        # otherwise the legacy SELECT-only check (pre-fix RED target).
        elig_fn = getattr(journal, "claim_send_attempt", None) or journal.get_send_eligibility

        def barrier_gate(*args, **kwargs):
            barrier.wait()  # 两个调用者同时到达资格检查点
            return elig_fn(*args, **kwargs)

        gate_name = "claim_send_attempt" if hasattr(journal, "claim_send_attempt") \
            else "get_send_eligibility"
        setattr(journal, gate_name, barrier_gate)

        errors: list = []

        def racer():
            try:
                stack["egress"].submit(token, coid, SYMBOL,
                                       Decimal("50"), "buy")
            except Exception as exc:
                errors.append(repr(exc))

        threads = [threading.Thread(target=racer), threading.Thread(target=racer)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)

        # The race must be REAL: at least one racer must have reached the
        # port (a vacuous pass on unrelated errors proves nothing).
        assert entry_count["n"] >= 1, (
            f"test setup invalid: entries={entry_count['n']} errors={errors}"
        )
        assert entry_count["n"] <= 1, (
            f"concurrent send window reproduced: {entry_count['n']} real port "
            f"entries for one intent (errors={errors})"
        )


class TestARed2ProcessRace:
    def test_two_process_claim_exactly_one_winner(self, stack, tmp_path):
        """两个真实 OS 进程竞争同一 journal send claim；各进程结果落独立文件。
        整改前 SELECT-only 检查双双通过（claimed 标记 true）；修复后恰有一个
        进程取得原子 claim。"""
        intent = persist_claimable_intent(stack)
        stack["journal"].close()

        worker_code = """
import sys, json
sys.path.insert(0, r'{src}')
from trading_lab.oms import OrderJournal

journal_path, coid, out_path, symbol = (
    sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4])
journal = OrderJournal(journal_path, check_same_thread=False)
# claim when available (post-fix); legacy SELECT-only check pre-fix
claim = getattr(journal, "claim_send_attempt", None)
if claim is not None:
    row = claim(coid, 1, symbol, "buy", "50", "PAPER", "PAPER_TEST_ACCOUNT")
    result = {{"claimed": row is not None, "mode": "atomic_claim"}}
else:
    row = journal.get_send_eligibility(
        coid, 1, symbol, "buy", "50", "PAPER", "PAPER_TEST_ACCOUNT")
    result = {{"claimed": row is not None, "mode": "select_only"}}
with open(out_path, "w", encoding="utf-8") as fh:
    json.dump(result, fh)
"""
        code = worker_code.format(src=str(REPO_ROOT / "src"))
        out_a = tmp_path / "worker_a.json"
        out_b = tmp_path / "worker_b.json"
        procs = [
            subprocess.Popen(
                [sys.executable, "-c", code, str(tmp_path / "journal.sqlite3"),
                 intent.deterministic_client_order_id, str(out), SYMBOL],
                cwd=str(REPO_ROOT),
            )
            for out in (out_a, out_b)
        ]
        for p in procs:
            assert p.wait(timeout=120) == 0

        results = [json.loads(p.read_text(encoding="utf-8"))
                   for p in (out_a, out_b)]
        claimed = [r["claimed"] for r in results]
        modes = {r["mode"] for r in results}
        # 不变量（两模式一致）：恰有一个进程取得发送资格。
        assert sum(claimed) == 1, (
            f"claim race reproduced: {claimed} modes={modes} — exactly one "
            f"winner required"
        )


class TestARed3CrashAfterClaim:
    def test_claimed_then_crash_is_conservative_unknown(self, stack):
        """claim 提交后、port 调用前崩溃：恢复按保守 UNKNOWN 处理，claim 不再授予。"""
        journal = stack["journal"]
        intent = persist_claimable_intent(stack)
        coid = intent.deterministic_client_order_id
        row = journal.claim_send_attempt(
            coid, 1, SYMBOL, "buy", "50", "PAPER", ACCOUNT)
        assert row is not None  # claimed, port never called (simulated crash)
        report = stack["oms"].recover(NOW)
        assert stack["ks"].is_halted()
        assert intent.intent_id in report.still_unknown  # 保守 UNKNOWN，不是可重试
        # claim 不得再授予（不盲重发）
        assert journal.claim_send_attempt(
            coid, 1, SYMBOL, "buy", "50", "PAPER", ACCOUNT) is None


class TestARed4NonSubmittingStates:
    def test_direct_egress_on_non_submitting_states_zero_created(self, stack):
        intent = make_intent(910)
        outcome = stack["oms"].submit(intent, sealed(stack, intent),
                                      SYMBOL, "buy", Decimal("50"), stack["token"])
        assert outcome.state == "ACKED"
        coid = intent.deterministic_client_order_id

        # ACKED 状态下直接 egress → 拒绝
        with pytest.raises(Exception):
            stack["egress"].submit(stack["token"], coid, SYMBOL, Decimal("50"), "buy")

        # 过期 fence → 拒绝
        expired_token = stack["fence"].acquire(NOW - dt.timedelta(hours=1))
        with pytest.raises(Exception):
            stack["egress"].submit(expired_token, coid, SYMBOL, Decimal("50"), "buy")

        assert stack["broker"].created_orders_by_intent(coid) == 1  # 不变
