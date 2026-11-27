"""Mock execution stack for the Business MVP: FAKE_BROKER / MOCK_ONLY.

Assembles the EXISTING security planes — SchemaGate, RiskEngine, OmsEngine,
FakeBroker — around a fictional account with no keys and no network. This
module reuses the real implementations; it never re-implements a second
ledger, risk engine or OMS. Every object it builds is the production class
wired to a deterministic fixture clock.

Honesty labels (must surface in every report):
    EXECUTION_BACKEND = "FAKE_BROKER"
    BROKER_BEHAVIOR   = "MOCK_ONLY"
The Environment enum only offers PAPER/LIVE, so the mock account binds
PAPER while every artifact carries the MOCK_ONLY labels above. A mock fill
is never a Paper-order fact and never feeds the backtest equity curve.

Fill valuation: the FakeBroker does not price fills (M2 semantics), so the
mock ledger values each fill at the caller-supplied fixture next-open
price plus a fixed mock commission. Cash/position conservation is asserted
on that ledger (``MockAccountLedger.conservation_report``).
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Callable, Mapping

from trading_lab.brokers import FakeBroker
from trading_lab.business.config import MockExecutionConfig
from trading_lab.business.types import ExecutionOutcome
from trading_lab.contracts import (
    Environment,
    MarketSnapshot,
    RiskDecision,
    TradeIntent,
)
from trading_lab.oms import (
    BrokerEgress,
    FenceCoordinator,
    OmsEngine,
    OrderJournal,
    RecoveryReport,
)
from trading_lab.risk import (
    ExposureState,
    RiskEngine,
    RiskPolicy,
    TrustedProducer,
)
from trading_lab.security import (
    ApprovalSecrets,
    AuditLog,
    GateDecision,
    KillSwitch,
    SchemaGate,
    TrustedProducerContext,
)
from trading_lab.security.canonical import canonical_digest

__all__ = [
    "EXECUTION_BACKEND",
    "BROKER_BEHAVIOR",
    "RISK_BUDGET_ID",
    "PORTFOLIO_PRODUCER_ID",
    "MOCK_INITIAL_CASH",
    "demo_build_hash",
    "MockAccountLedger",
    "MockExecutionStack",
]

EXECUTION_BACKEND = "FAKE_BROKER"
BROKER_BEHAVIOR = "MOCK_ONLY"
RISK_BUDGET_ID = "BUSINESS_DEMO_RISK_BUDGET"
PORTFOLIO_PRODUCER_ID = "business_mvp_orchestrator_v1"

# Mock accounts are sized UNDER the pinned order cap so a full-allocation
# decision fits one compliant intent (documented demo prior, not tuning).
MOCK_INITIAL_CASH = Decimal("40000.00")

MOCK_COMMISSION_PER_FILL = Decimal("1.00")
# One synthetic session of snapshot/account freshness headroom: replay
# decisions at close T consume bars made available at T's open.
_SESSION_FRESHNESS_SECONDS = 24 * 3600

NowFn = Callable[[], dt.datetime]
SnapshotProvider = Callable[[], MarketSnapshot | None]
MarksProvider = Callable[[], Mapping[str, Decimal]]


def demo_build_hash(name: str) -> str:
    """Deterministic reviewed-build hash for a demo producer/strategy."""
    return canonical_digest({"demo_build": name})


def _jsonable(obj: object) -> object:
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    return obj


class MockAccountLedger:
    """Fictional cash/position ledger valued from mock fills.

    This is the demo's account view ONLY — it is not a second OMS journal
    (the OrderJournal remains the single order truth) and its valuations
    never enter the backtest equity curve.
    """

    def __init__(self, initial_cash: Decimal) -> None:
        self.initial_cash = Decimal(initial_cash)
        self.cash = Decimal(initial_cash)
        self.positions: dict[str, Decimal] = {}
        self.fill_log: list[dict[str, str]] = []

    def apply_mock_fill(self, *, symbol: str, side: str, qty: Decimal,
                        price: Decimal) -> None:
        if qty <= 0:
            raise ValueError(f"fill qty must be positive (got {qty})")
        notional = (qty * price).quantize(Decimal("0.01"))
        signed = notional if side == "buy" else -notional
        self.cash = (self.cash - signed - MOCK_COMMISSION_PER_FILL).quantize(
            Decimal("0.01"))
        delta = qty if side == "buy" else -qty
        new_pos = self.positions.get(symbol, Decimal("0")) + delta
        if new_pos < 0:
            raise ValueError(
                f"mock ledger would go short {symbol}: refuse (long-only demo)")
        self.positions[symbol] = new_pos
        self.fill_log.append({
            "symbol": symbol, "side": side, "qty": str(qty),
            "price": str(price), "notional": str(notional),
            "commission": str(MOCK_COMMISSION_PER_FILL),
        })

    def equity(self, marks: Mapping[str, Decimal]) -> Decimal:
        total = self.cash
        for symbol, qty in self.positions.items():
            if qty == 0:
                continue
            mark = marks.get(symbol)
            if mark is None:
                raise ValueError(
                    f"no mark for held symbol {symbol} — fail closed")
            total += qty * mark
        return total.quantize(Decimal("0.01"))

    def exposure_state(self, marks: Mapping[str, Decimal]) -> ExposureState:
        gross = Decimal("0")
        net = Decimal("0")
        for symbol, qty in self.positions.items():
            mark = marks.get(symbol, Decimal("0"))
            gross += abs(qty * mark)
            net += qty * mark
        return ExposureState(
            gross_exposure_usd=gross.quantize(Decimal("0.01")),
            net_exposure_usd=net.quantize(Decimal("0.01")),
            equity_usd=self.equity(marks),
            settled_cash_usd=self.cash.quantize(Decimal("0.01")),
        )

    def conservation_report(self) -> dict:
        net_notional = Decimal("0")
        for f in self.fill_log:
            signed = Decimal(f["notional"])
            net_notional += signed if f["side"] == "buy" else -signed
        fees = MOCK_COMMISSION_PER_FILL * len(self.fill_log)
        lhs = self.cash
        rhs = self.initial_cash - net_notional - fees
        return {
            "ok": lhs == rhs,
            "identity_delta": str(lhs - rhs),
            "initial_cash": str(self.initial_cash),
            "cash": str(self.cash),
            "positions": {k: str(v) for k, v in sorted(self.positions.items())},
            "fills": len(self.fill_log),
            "fees": str(fees),
        }


@dataclass(frozen=True)
class _StackRefs:
    audit: AuditLog
    journal: OrderJournal
    fence: FenceCoordinator
    broker: FakeBroker
    ks: KillSwitch
    risk: RiskEngine
    oms: OmsEngine
    gate: SchemaGate
    producer: TrustedProducer
    secrets: ApprovalSecrets
    policy: RiskPolicy


class MockExecutionStack:
    """One fictional PAPER-named account wired through the real planes.

    Deterministic: the fixture clock enters through ``now_fn``; no wall
    clock is consulted anywhere in this class.
    """

    def __init__(
        self,
        *,
        config: MockExecutionConfig,
        initial_cash: Decimal,
        state_dir: Path,
        now_fn: NowFn,
        snapshot_provider: SnapshotProvider,
        strategy_build_hashes: Mapping[str, str],
        allowed_symbols: tuple[str, ...],
    ) -> None:
        if config.environment != "PAPER":
            raise ValueError(
                "mock execution binds Environment.PAPER only; other "
                "environments are out of scope for MOCK_ONLY demos")
        state_dir.mkdir(parents=True, exist_ok=True)
        audit = AuditLog(state_dir / "audit.jsonl", config.environment)
        journal = OrderJournal(state_dir / "journal.sqlite3",
                               check_same_thread=False)
        fence = FenceCoordinator(state_dir / "fence.sqlite3",
                                 Environment.PAPER, config.account_id,
                                 check_same_thread=False)
        secrets = ApprovalSecrets.mint()
        broker = FakeBroker()
        egress = BrokerEgress(broker, fence, audit, now_fn=now_fn,
                              journal=journal, approval_secrets=secrets)
        ks = KillSwitch(Environment.PAPER, config.account_id,
                        state_dir / "ks", audit)
        policy = self._build_policy(config, initial_cash, allowed_symbols)
        producer = TrustedProducer.mint(PORTFOLIO_PRODUCER_ID,
                                        demo_build_hash(PORTFOLIO_PRODUCER_ID))
        risk = RiskEngine(
            policy=policy, kill_switch=ks, audit=audit,
            trusted_producer=producer, now_fn=now_fn,
            snapshot_provider=snapshot_provider,
            exposure_provider=self._exposure_provider,
            approval_secrets=secrets,
        )
        oms = OmsEngine(
            environment=Environment.PAPER, account_id=config.account_id,
            journal=journal, egress=egress, fence=fence, audit=audit,
            kill_switch=ks, now_fn=now_fn,
            expected_policy_hash=policy.policy_hash,
            approval_secrets=secrets,
        )
        gate = SchemaGate(
            reviewed_builds={k: {v} for k, v in strategy_build_hashes.items()},
            allowed_symbols=set(allowed_symbols),
            audit=audit, now_fn=now_fn,
            portfolio_context=TrustedProducerContext(
                runtime_account_id=config.account_id,
                allowed_risk_budget_ids=frozenset({RISK_BUDGET_ID}),
                reviewed_portfolio_producers={
                    PORTFOLIO_PRODUCER_ID: demo_build_hash(PORTFOLIO_PRODUCER_ID),
                },
                max_portfolio_age_seconds=_SESSION_FRESHNESS_SECONDS,
            ),
        )
        self._refs = _StackRefs(audit=audit, journal=journal, fence=fence,
                                broker=broker, ks=ks, risk=risk, oms=oms,
                                gate=gate, producer=producer,
                                secrets=secrets, policy=policy)
        self._config = config
        self.ledger = MockAccountLedger(initial_cash)
        self._now_fn = now_fn
        self._marks_provider: MarksProvider = dict
        self._intent_seq = 0

    # -- wiring helpers ------------------------------------------------------

    @staticmethod
    def _build_policy(config: MockExecutionConfig, initial_cash: Decimal,
                      allowed_symbols: tuple[str, ...]) -> RiskPolicy:
        """Demo risk policy priors from pinned notionals. Percent fields are
        % of initial equity, quantized; the loose daily-loss/drawdown
        numbers are DEMO priors (fixture paths exceed realistic daily
        limits), not production tuning."""
        gross_pct = (config.max_gross_notional / initial_cash * 100).quantize(
            Decimal("0.01"))
        position_pct = (config.max_position_notional / initial_cash * 100).quantize(
            Decimal("0.01"))
        policy_dict = {
            "version": 1,
            "environment": Environment.PAPER,
            "account_id": config.account_id,
            "max_gross_exposure_pct": gross_pct,
            "max_net_exposure_pct": gross_pct,
            "max_single_symbol_pct": position_pct,
            "max_single_order_notional_usd": config.max_order_notional,
            "max_daily_loss_pct": Decimal("50"),               # demo prior
            "max_peak_to_trough_drawdown_pct": Decimal("50"),  # demo prior
            "max_abnormal_orders_per_minute": 8,
            "max_market_bar_age_seconds": _SESSION_FRESHNESS_SECONDS,
            "max_account_snapshot_age_seconds": _SESSION_FRESHNESS_SECONDS,
            "max_broker_order_ack_wait_seconds": 3600,
            "require_settled_funds": True,
            "allow_margin": False,
            "allow_short": False,
            "allowed_symbols": tuple(allowed_symbols),
            "recovery_requires": (
                "broker_orders_positions_cash_reconciled",
                "operator_release_after_incident",
            ),
        }
        policy_dict["policy_hash"] = canonical_digest(
            {k: str(v) for k, v in sorted(policy_dict.items())})
        return RiskPolicy.model_validate(policy_dict)

    def set_marks_provider(self, provider: MarksProvider) -> None:
        """Fixture mark prices for exposure/equity (PIT-respecting marks
        supplied by the replay loop or the scenario driver)."""
        self._marks_provider = provider

    def _exposure_provider(self) -> ExposureState:
        return self.ledger.exposure_state(self._marks_provider())

    # -- admission paths -------------------------------------------------------

    def evaluate_signal_admission(self, signal_payload: Mapping[str, object],
                                  ) -> GateDecision:
        """StrategySignal JSON through the gate (trust-boundary demo)."""
        return self._refs.gate.evaluate_signal(
            json.dumps(_jsonable(dict(signal_payload))))

    def evaluate_portfolio_admission(self, portfolio_dump: Mapping[str, object],
                                     ) -> GateDecision:
        return self._refs.gate.evaluate_portfolio(
            json.dumps(_jsonable(dict(portfolio_dump))),
            PORTFOLIO_PRODUCER_ID)

    # -- risk + execution --------------------------------------------------------

    def next_intent(self, *, asof: dt.datetime, desired_change: Decimal,
                    release_id: str) -> TradeIntent:
        self._intent_seq += 1
        env = Environment.PAPER
        account = self._config.account_id
        return TradeIntent(
            intent_id=f"biz-{self._intent_seq:06d}",
            release_id=release_id,
            account_id=account,
            environment=env,
            desired_change=desired_change,
            source_hash=demo_build_hash(PORTFOLIO_PRODUCER_ID),
            expires_at_utc=asof + dt.timedelta(hours=1),
            deterministic_client_order_id=f"{env.value}:{account}:BIZ{self._intent_seq:08d}",
        )

    def evaluate_risk(self, intent: TradeIntent,
                      symbol: str, side: str | None = None) -> RiskDecision:
        return self._refs.risk.evaluate(intent, self._refs.producer,
                                        symbol=symbol, side=side)

    def submit(self, *, intent: TradeIntent, asof: dt.datetime,
               symbol: str, side: str, quantity: Decimal,
               ) -> ExecutionOutcome:
        """Full real path: risk evaluation -> sealed decision -> OMS submit
        (journal-first, fence, egress, FakeBroker)."""
        decision = self.evaluate_risk(intent, symbol, side=side)
        verdict = "APPROVE" if decision.allow else (
            "HALT" if any("HALT" in r or r == "KILL_SWITCH_ENGAGED"
                          for r in decision.reason_codes) else "REJECT")
        token = self._refs.fence.acquire(self._now_fn())
        outcome = self._refs.oms.submit(intent, decision, symbol, side,
                                        quantity, token)
        return ExecutionOutcome(
            decision_asof_utc=asof,
            intent_id=outcome.intent_id,
            client_order_id=intent.deterministic_client_order_id,
            outcome_state=outcome.state,
            delivered=outcome.delivered,
            acknowledged=outcome.acknowledged,
            risk_verdict=verdict,
            risk_reasons=tuple(decision.reason_codes),
            notes=(f"backend={EXECUTION_BACKEND}",
                   f"behavior={BROKER_BEHAVIOR}"),
        )

    def apply_mock_fill(self, outcome: ExecutionOutcome, *, symbol: str,
                        side: str, qty: Decimal,
                        price: Decimal) -> ExecutionOutcome:
        """Deliver the fill through the real broker/OMS path, then value it
        on the mock ledger at the caller-supplied fill price and SIDE (the
        FakeBroker itself is side-agnostic; the ledger is not)."""
        if outcome.outcome_state != "ACKED" or not outcome.delivered:
            raise ValueError(
                f"cannot fill intent {outcome.intent_id} in state "
                f"{outcome.outcome_state}")
        if side not in ("buy", "sell"):
            raise ValueError(f"side must be buy/sell (got {side!r})")
        coid = outcome.client_order_id
        event_id = self._refs.broker.apply_fill(coid, abs(qty))
        recorded = self._refs.oms.process_fill(outcome.intent_id, event_id,
                                               abs(qty))
        if not recorded:
            raise ValueError(
                f"OMS refused fill for {outcome.intent_id} (event {event_id})")
        self.ledger.apply_mock_fill(symbol=symbol, side=side,
                                    qty=abs(qty), price=price)
        return ExecutionOutcome(
            decision_asof_utc=outcome.decision_asof_utc,
            intent_id=outcome.intent_id,
            client_order_id=outcome.client_order_id,
            outcome_state="FILLED",
            delivered=True,
            acknowledged=True,
            risk_verdict=outcome.risk_verdict,
            risk_reasons=outcome.risk_reasons,
            fill_qty=qty,
            fill_price=price,
            notes=outcome.notes,
        )

    # -- recovery / halt demos ------------------------------------------------

    def recover(self) -> RecoveryReport:
        return self._refs.oms.recover(self._now_fn())

    def operator_unlock(self, operator_id: str,
                        authorization_ref: str) -> None:
        self._refs.oms.operator_unlock(operator_id, authorization_ref)

    @property
    def kill_switch(self) -> KillSwitch:
        return self._refs.ks

    @property
    def fake_broker(self) -> FakeBroker:
        """The underlying FakeBroker (fault scheduling for recovery demos;
        never a network client)."""
        return self._refs.broker

    def broker_created_order_count(self, coid: str) -> int:
        return self._refs.broker.created_orders_by_intent(coid)

    def close(self) -> None:
        self._refs.journal.close()
        self._refs.fence.close()


def side_of(qty: Decimal) -> str:
    return "buy" if qty > 0 else "sell"
