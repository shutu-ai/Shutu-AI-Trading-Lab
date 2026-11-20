"""M2-INDEPENDENT-REVIEW-REMEDIATION-001 — RED reproductions for R1–R7.

Each test encodes the security invariant the review demands and fails
against the pre-fix implementation. GREEN lands in the same files as the
fixes (risk/engine.py, oms/*, brokers/fake.py).
"""

from __future__ import annotations

import datetime as dt
import sys
from decimal import Decimal
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

from trading_lab.contracts import Environment, RiskDecision, TradeIntent  # noqa: E402
from trading_lab.oms import OmsEngine
from trading_lab.risk import RiskEngine, RiskPolicy, TrustedProducer  # noqa: E402

from helpers_m2 import (  # noqa: E402
    ACCOUNT,
    BUILD,
    NOW,
    POLICY_DICT,
    SYMBOL,
    fresh_snapshot,
    make_intent,
    stack,
)


def decision_for(intent, allow=True, policy_hash="b" * 32, decision_at=NOW,
                 limits_snapshot=None) -> RiskDecision:
    return RiskDecision(
        intent_id=intent.intent_id,
        policy_hash=policy_hash,
        allow=allow,
        reason_codes=("POLICY_SATISFIED",) if allow else ("SYNTHETIC_DENY",),
        limits_snapshot=limits_snapshot if limits_snapshot is not None else {},
        decision_at=decision_at,
    )


# ---------------------------------------------------------------------------
# R1 — the OMS must enforce the risk approval cryptographically
# ---------------------------------------------------------------------------


class TestR1ApprovalEnforcement:
    def test_disallowed_decision_zero_sends(self, stack):
        """allow=False 决策：整改前 OMS 不检查 allow，照常发单（缺陷）。"""
        intent = make_intent(700)
        outcome = stack["oms"].submit(
            intent, decision_for(intent, allow=False), SYMBOL, "buy", Decimal("50"), stack["token"]
        )
        assert stack["broker"].created_orders_by_intent(intent.deterministic_client_order_id) == 0
        assert stack["journal"].state_of(intent.intent_id) is None  # nothing persisted as sendable

    def test_forged_decision_zero_sends(self, stack):
        """伪造 allow=True 决策（非引擎签发、无密封）→ 0 发送。"""
        intent = make_intent(701)
        outcome = stack["oms"].submit(
            intent, decision_for(intent, allow=True), SYMBOL, "buy", Decimal("50"), stack["token"]
        )
        assert stack["broker"].created_orders_by_intent(intent.deterministic_client_order_id) == 0

    def test_intent_id_mismatch_zero_sends(self, stack):
        intent = make_intent(702)
        decision = decision_for(intent)
        other = make_intent(703)
        mismatched = decision.model_copy(update={"intent_id": other.intent_id})
        outcome = stack["oms"].submit(intent, mismatched, SYMBOL, "buy", Decimal("50"), stack["token"])
        assert stack["broker"].created_orders_by_intent(intent.deterministic_client_order_id) == 0

    def test_parameter_substitution_zero_sends(self, stack):
        """参数替换：批准 buy SPY 50，提交时换成 QQQ / sell / 5000 → 0 发送。"""
        intent = make_intent(704)
        decision = stack["engine"].evaluate(intent, stack["producer"], symbol=SYMBOL)
        assert decision.allow
        for sym, side, qty in (("QQQ", "buy", Decimal("50")),
                               (SYMBOL, "sell", Decimal("50")),
                               (SYMBOL, "buy", Decimal("5000"))):
            outcome = stack["oms"].submit(intent, decision, sym, side, qty, stack["token"])
            coid = intent.deterministic_client_order_id
            assert stack["broker"].created_orders_by_intent(coid) == 0, (sym, side, qty)

    def test_expired_or_future_decision_zero_sends(self, stack):
        intent = make_intent(705)
        expired = decision_for(intent, decision_at=NOW - dt.timedelta(minutes=10))
        outcome = stack["oms"].submit(intent, expired, SYMBOL, "buy", Decimal("50"), stack["token"])
        assert stack["broker"].created_orders_by_intent(intent.deterministic_client_order_id) == 0
        future = decision_for(intent, decision_at=NOW + dt.timedelta(minutes=10))
        outcome = stack["oms"].submit(intent, future, SYMBOL, "buy", Decimal("50"), stack["token"])
        assert stack["broker"].created_orders_by_intent(intent.deterministic_client_order_id) == 0

    def test_policy_mismatch_zero_sends(self, stack):
        intent = make_intent(706)
        outcome = stack["oms"].submit(
            intent, decision_for(intent, policy_hash="9" * 32), SYMBOL, "buy", Decimal("50"), stack["token"]
        )
        assert stack["broker"].created_orders_by_intent(intent.deterministic_client_order_id) == 0

    def test_engine_signed_decision_still_flows(self, stack):
        """正例：引擎真实签发（含绑定密封）的批准照常走通。"""
        intent = make_intent(707)
        decision = stack["engine"].evaluate(intent, stack["producer"], symbol=SYMBOL)
        assert decision.allow
        outcome = stack["oms"].submit(intent, decision, SYMBOL, "buy", Decimal("50"), stack["token"])
        assert outcome.state == "ACKED"
        assert stack["broker"].created_orders_by_intent(intent.deterministic_client_order_id) == 1


# ---------------------------------------------------------------------------
# R2 — LIVE must be absolutely unexecutable in M2
# ---------------------------------------------------------------------------


def live_stack(stack):
    policy = stack["policy"].model_copy(update={"environment": Environment.LIVE})
    engine = RiskEngine(
        policy=policy,
        kill_switch=stack["ks"],
        audit=stack["audit"],
        trusted_producer=stack["producer"],
        now_fn=lambda: NOW,
        snapshot_provider=fresh_snapshot,
        exposure_provider=lambda: __import__("trading_lab.risk", fromlist=["ExposureState"]).ExposureState(
            gross_exposure_usd=Decimal("0"), net_exposure_usd=Decimal("0"),
            equity_usd=Decimal("1000"), settled_cash_usd=Decimal("1000"),
        ),
        approval_verifier=None,  # 缺失验签器
    )
    stack["engine"] = engine
    return stack


class TestR2LiveFailClosed:
    def test_live_without_verifier_rejected(self, stack):
        stack = live_stack(stack)
        intent = make_intent(710, env=Environment.LIVE)
        d = stack["engine"].evaluate(intent, stack["producer"], symbol=SYMBOL)
        assert not d.allow
        assert any(r.startswith("LIVE_APPROVAL_VERIFIER_MISSING") for r in d.reason_codes)

    def test_live_verifier_exception_fail_closed(self, stack):
        stack = live_stack(stack)
        stack["engine"]._approval_verifier = lambda i: (_ for _ in ()).throw(
            RuntimeError("verifier crash")
        )
        intent = make_intent(711, env=Environment.LIVE)
        d = stack["engine"].evaluate(intent, stack["producer"], symbol=SYMBOL)
        assert not d.allow

    def test_live_unenforced_mandatory_fields_rejected(self, stack):
        """LIVE + MOCK_ONLY 不可执行字段存在 → 不得放行。"""
        stack = live_stack(stack)
        stack["engine"]._approval_verifier = lambda i: (True, "mock")
        intent = make_intent(712, env=Environment.LIVE)
        d = stack["engine"].evaluate(intent, stack["producer"], symbol=SYMBOL)
        assert not d.allow
        assert any(r.startswith("LIVE_MOCK_ONLY_UNENFORCED") for r in d.reason_codes)


# ---------------------------------------------------------------------------
# R3 — unlock requires verified reconciliation, not just text
# ---------------------------------------------------------------------------


class TestR3UnlockGate:
    def test_unlock_refused_with_unresolved_unknown(self, stack):
        intent = make_intent(720)
        stack["broker"].schedule_fault("submit_timeout", intent.deterministic_client_order_id)
        stack["oms"].submit(intent, stack["engine"].evaluate(intent, stack["producer"], symbol=SYMBOL),
                            SYMBOL, "buy", Decimal("50"), stack["token"])
        report = stack["oms"].recover(NOW)
        assert intent.intent_id in report.still_unknown
        # 仅凭授权文本不得解除新增风险锁
        with pytest.raises(Exception):
            stack["oms"].operator_unlock("op", "approved")
        assert stack["ks"].is_halted()

    def test_unlock_allowed_after_full_reconciliation(self, stack):
        intent = make_intent(721)
        coid = intent.deterministic_client_order_id
        stack["broker"].schedule_fault("ack_lost", coid)
        stack["oms"].submit(intent, stack["engine"].evaluate(intent, stack["producer"], symbol=SYMBOL),
                            SYMBOL, "buy", Decimal("50"), stack["token"])
        stack["broker"].late_order_appears(coid, SYMBOL, Decimal("50"), "buy")
        report = stack["oms"].recover(NOW)
        assert intent.intent_id in report.reconciled
        stack["oms"].operator_unlock("op", "reconciled:order-level-mock-only")
        assert not stack["ks"].is_halted()


# ---------------------------------------------------------------------------
# R4 — journal single-transaction intent+attempt boundary
# ---------------------------------------------------------------------------


class TestR4AtomicBoundary:
    def test_single_transaction_entry_exists(self):
        from trading_lab.oms import OrderJournal

        assert hasattr(OrderJournal, "record_intent_and_submitting"), (
            "journal must expose one atomic intent+attempt entry"
        )
        assert not hasattr(OrderJournal, "record_intent") or not hasattr(
            OrderJournal, "mark_submitting"
        ), "two-step legacy entries must not remain (no consumerless compat)"

    def test_crash_between_steps_leaves_no_sendable_state(self, stack):
        """单事务语义：不存在『意图已持久但尝试未记录』的中间可见状态。"""
        journal = stack["journal"]
        intent = make_intent(730)
        # 旧两步法移除后，直接走原子入口；崩溃窗口 = 事务未提交 → 两者皆无
        with pytest.raises(Exception):
            journal.record_intent_and_submitting(
                intent_id=intent.intent_id,
                client_order_id=intent.deterministic_client_order_id,
                environment="PAPER", account_id=ACCOUNT, symbol=SYMBOL, side="buy",
                quantity="50", payload={}, risk_decision={},
                fence_epoch=1,
                simulate_crash_before_commit=True,
            )
        assert journal.state_of(intent.intent_id) is None  # rollback = nothing


# ---------------------------------------------------------------------------
# R5 — fills persist state atomically
# ---------------------------------------------------------------------------


class TestR5FillAtomicity:
    def _acked(self, stack, seq):
        intent = make_intent(seq)
        decision = stack["engine"].evaluate(intent, stack["producer"], symbol=SYMBOL)
        outcome = stack["oms"].submit(intent, decision, SYMBOL, "buy", Decimal("50"), stack["token"])
        assert outcome.state == "ACKED", outcome
        return intent

    def test_fill_persists_new_state(self, stack):
        intent = self._acked(stack, 740)
        assert stack["oms"].process_fill(intent.intent_id, "EVT-F1", Decimal("50"))
        assert stack["journal"].state_of(intent.intent_id) == "FILLED"

    def test_partial_fill_persists(self, stack):
        intent = self._acked(stack, 741)
        assert stack["oms"].process_fill(intent.intent_id, "EVT-F2", Decimal("20"))
        assert stack["journal"].state_of(intent.intent_id) == "PARTIALLY_FILLED"

    def test_overfill_refused(self, stack):
        intent = self._acked(stack, 742)
        assert stack["oms"].process_fill(intent.intent_id, "EVT-F3", Decimal("50"))  # filled
        ok = stack["oms"].process_fill(intent.intent_id, "EVT-F4", Decimal("10"))
        assert not ok  # 超量成交拒绝
        assert stack["journal"].state_of(intent.intent_id) == "FILLED"

    def test_fill_on_cancelled_refused(self, stack):
        intent = self._acked(stack, 743)
        stack["journal"].transition_state(intent.intent_id, "ACKED", "CANCEL_PENDING")
        stack["journal"].transition_state(intent.intent_id, "CANCEL_PENDING", "CANCELLED")
        ok = stack["oms"].process_fill(intent.intent_id, "EVT-F5", Decimal("10"))
        assert not ok  # 撤单后成交 fail-closed

    def test_replay_of_any_event_id_once_only(self, stack):
        intent = self._acked(stack, 744)
        assert stack["oms"].process_fill(intent.intent_id, "EVT-F6", Decimal("25"))
        assert not stack["oms"].process_fill(intent.intent_id, "EVT-F6", Decimal("25"))
        assert stack["journal"].state_of(intent.intent_id) == "PARTIALLY_FILLED"


# ---------------------------------------------------------------------------
# R6 — egress TOCTOU: superseded writer's result must never be adopted
# ---------------------------------------------------------------------------


class TestR6FenceRace:
    def test_epoch_bump_during_call_yields_halt_not_ack(self, stack):
        """A 校验通过后在 port 内阻塞；B 提升 epoch；A 继续 → 结果不得 ACK。"""
        import threading

        # Cross-thread connections: the in-flight call runs on another
        # thread, so the sqlite links must opt out of thread locking.
        from trading_lab.oms import OrderJournal as _J
        from trading_lab.oms import FenceCoordinator as _F

        stack["journal"] = _J(stack["journal"].path, check_same_thread=False)
        stack["fence"] = _F(stack["fence"].path, stack["fence"]._env, ACCOUNT,
                            check_same_thread=False)
        from trading_lab.oms import BrokerEgress as _E
        from trading_lab.security import AuditLog as _A

        stack["egress"] = _E(stack["broker"], stack["fence"], stack["audit"],
                             now_fn=lambda: NOW, journal=stack["journal"],
                             approval_secrets=stack["engine"]._approval_secrets)  # noqa: SLF001
        stack["token"] = stack["fence"].acquire(NOW)  # token from THIS coordinator instance
        stack["oms"] = OmsEngine(
            environment=stack["engine"]._policy.environment,  # noqa: SLF001 - test seam
            account_id=ACCOUNT,
            journal=stack["journal"],
            egress=stack["egress"],
            fence=stack["fence"],
            audit=stack["audit"],
            kill_switch=stack["ks"],
            now_fn=lambda: NOW,
            expected_policy_hash=stack["policy"].policy_hash,
            approval_secrets=stack["engine"]._approval_secrets,  # noqa: SLF001
        )
        intent = make_intent(750)
        coid = intent.deterministic_client_order_id
        entered = threading.Event()
        release = threading.Event()

        original = stack["broker"].submit_order

        def blocking_submit(coid_, symbol, qty, side, epoch):
            entered.set()
            release.wait(timeout=30)
            return original(coid_, symbol, qty, side, epoch)

        stack["broker"].submit_order = blocking_submit  # type: ignore[method-assign]
        from trading_lab.contracts import RiskDecision

        result: dict = {}

        def worker():
            try:
                decision = stack["engine"].evaluate(intent, stack["producer"], symbol=SYMBOL)
                result["outcome"] = stack["oms"].submit(
                    intent, decision, SYMBOL, "buy", Decimal("50"), stack["token"]
                )
            except Exception as exc:  # post-validation refusal surfaces here
                result["exception"] = exc

        t = threading.Thread(target=worker)
        t.start()
        for _ in range(100):  # wait for port entry OR early worker failure
            if entered.is_set() or not t.is_alive():
                break
            t.join(timeout=0.1)
        if not entered.is_set():
            t.join(timeout=5)
            detail = result.get("exception") or result.get("outcome")
            raise AssertionError(f"worker never entered the port: {detail!r}")
        stack["fence"].acquire(NOW)  # B 提升.epoch — A 已在飞行中
        release.set()
        t.join(timeout=30)

        outcome = result.get("outcome")
        # 被取代的旧写者：即使 broker 已建单，OMS 也不得采纳 ACK
        assert outcome is None or outcome.state in ("HALT_NEW_RISK", "UNKNOWN"), (
            f"superseded writer adopted its result: {outcome}"
        )
        assert stack["journal"].state_of(intent.intent_id) in (
            None, "HALT_NEW_RISK", "UNKNOWN"
        )


# ---------------------------------------------------------------------------
# R7 — §6.2 mandatory fields actually enforced
# ---------------------------------------------------------------------------


class TestR7MandatoryFields:
    def test_explicit_zero_bar_age_not_shadowed_by_default(self, stack):
        """`or` 缺陷：显式 0 容忍被策略默认 120 秒遮蔽（整改前放行）。"""
        intent = make_intent(760)
        d = stack["engine"].evaluate(intent, stack["producer"], symbol=SYMBOL,
                                     max_bar_age_seconds=0)
        assert not d.allow  # 10 秒前的快照对 0 容忍即过期

    def test_net_exposure_enforced(self, stack):
        from trading_lab.risk import ExposureState

        stack["engine"]._exposure_provider = lambda: ExposureState(
            gross_exposure_usd=Decimal("0"), net_exposure_usd=Decimal("570"),
            equity_usd=Decimal("1000"), settled_cash_usd=Decimal("1000"),
        )
        d = stack["engine"].evaluate(make_intent(761), stack["producer"], symbol=SYMBOL)
        assert any(r.startswith("NET_EXPOSURE_EXCEEDED") for r in d.reason_codes)

    def test_short_rejected_when_disallowed(self, stack):
        d = stack["engine"].evaluate(
            make_intent(762, desired="-50"), stack["producer"], symbol=SYMBOL
        )
        assert any(r.startswith("SHORT_NOT_ALLOWED") for r in d.reason_codes)

    def test_single_symbol_concentration_enforced(self, stack):
        from trading_lab.risk import ExposureState

        stack["engine"]._exposure_provider = lambda: ExposureState(
            gross_exposure_usd=Decimal("0"), net_exposure_usd=Decimal("0"),
            equity_usd=Decimal("1000"), settled_cash_usd=Decimal("1000"),
            symbol_exposure_usd={SYMBOL: Decimal("280")},
        )
        d = stack["engine"].evaluate(make_intent(763), stack["producer"], symbol=SYMBOL)
        assert any(r.startswith("SINGLE_SYMBOL_CONCENTRATION") for r in d.reason_codes)
