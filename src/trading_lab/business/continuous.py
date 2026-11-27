"""Continuous mock execution: one persistent fictional account driven
session-by-session through the REAL SchemaGate -> RiskEngine -> OMS ->
FakeBroker chain (V0.2 B3).

Differences from V0.1's ``_run_mock_scenarios`` (which runs isolated
representative scenarios on throwaway accounts):

- ONE account persists across the whole replay: positions and cash carry
  forward, sizing sees the live book.
- EVERY decision cycle flows through execution (or records NO_TRADE /
  risk-refusal with reasons) — not one hand-picked intent.
- Deterministic client order ids embed the session counter and symbol,
  so replaying the same cycle cannot create duplicate broker orders
  (idempotency by construction), and re-running the demo reproduces the
  same ledger.
- The continuous MOCK ledger (``ledger``) stays a SEPARATE, labeled book
  from the formal backtest account; the report shows both curves
  independently and never mixes them.

Execution timing per cycle (deterministic fixture clock): decision at
session close ``asof`` -> intents evaluated at ``asof`` -> fills at the
fixture NEXT OPEN price (whole shares). A risk refusal is recorded and
NOT retried or bypassed; a same-session re-invocation of an already
submitted intent is refused downstream by the OMS journal (duplicate
protection).
"""

from __future__ import annotations

import datetime as dt
from decimal import ROUND_DOWN, Decimal
from pathlib import Path
from typing import Callable, Mapping, Sequence

from trading_lab.business.config import BusinessConfig
from trading_lab.business.decision import demo_strategy_build_hashes
from trading_lab.business.mockexec import (
    MOCK_INITIAL_CASH,
    MockExecutionStack,
)
from trading_lab.business.types import DecisionOutput, ExecutionOutcome
from trading_lab.contracts import MarketSnapshot
from dataclasses import replace

__all__ = ["ContinuousMockRunner", "MIN_ORDER_NOTIONAL"]

MIN_ORDER_NOTIONAL = Decimal("100.00")   # ignore dust rebalances
NowFn = Callable[[], dt.datetime]


class ContinuousMockRunner:
    """Session-loop execution adapter over one persistent mock account."""

    def __init__(
        self,
        *,
        config: BusinessConfig,
        state_dir: Path,
        clock: NowFn,
        labels: Mapping[str, str] | None = None,
    ) -> None:
        self._config = config
        quality = labels.get("data_quality", "SYNTHETIC_OFFLINE_DEMO") \
            if labels else "SYNTHETIC_OFFLINE_DEMO"
        self._dataset_hash = "d" * 32
        self._stack = MockExecutionStack(
            config=config.mock_execution,
            initial_cash=MOCK_INITIAL_CASH,
            state_dir=state_dir,
            now_fn=clock,
            snapshot_provider=lambda: MarketSnapshot(
                snapshot_id=f"continuous-{clock().date().isoformat()}",
                asof_utc=clock() - dt.timedelta(hours=8),
                knowledge_cutoff_utc=clock() - dt.timedelta(hours=8),
                dataset_hash=self._dataset_hash,
                data_quality=quality),
            strategy_build_hashes=demo_strategy_build_hashes(),
            allowed_symbols=tuple(config.fixture.symbols),
        )
        self._session_index = 0
        self.outcomes: list[ExecutionOutcome] = []
        self.cycle_records: list[dict[str, object]] = []
        self._marks: dict[str, Decimal] = {}
        self._stack.set_marks_provider(lambda: dict(self._marks))

    def bind_dataset(self, dataset_hash: str) -> None:
        """Pin the run's dataset identity into the snapshot provider."""
        self._dataset_hash = dataset_hash

    # -- the per-session step ------------------------------------------------

    def step(
        self,
        *,
        asof: dt.datetime,
        decision: DecisionOutput,
        marks: Mapping[str, Decimal],
        next_opens: Mapping[str, Decimal],
    ) -> list[ExecutionOutcome]:
        """Execute one decision cycle on the persistent account.

        ``marks``: PIT-respecting prices for account valuation at
        ``asof``. ``next_opens``: next-open prices per symbol for fill
        valuation (symbol -> price; missing = no fill possible this
        cycle). Returns per-symbol ExecutionOutcomes plus a NO_TRADE
        cycle record when the decision produced no orders.
        """
        self._session_index += 1
        self._marks = dict(marks)
        outcomes: list[ExecutionOutcome] = []

        if decision.target is None or decision.chosen_strategy_id is None:
            self.cycle_records.append(self._record(
                asof, decision, [], "NO_TRADE",
                list(decision.no_trade_reasons)))
            self.outcomes.extend(outcomes)
            return outcomes

        weights = {a.symbol: a.weight for a in decision.target.allocation}
        symbols = sorted(set(weights) | set(self._stack.ledger.positions))
        equity = self._stack.ledger.equity(self._marks)
        min_notional = min(MIN_ORDER_NOTIONAL, equity * Decimal("0.01"))
        for symbol in symbols:
            # SIZING PRICE: the PIT decision mark ONLY. The future
            # next-open never sizes an order; without a legal decision
            # price the leg records a NO_PRICE reason and no order.
            decision_price = marks.get(symbol)
            if decision_price is None or decision_price <= 0:
                continue
            weight = weights.get(symbol, Decimal("0"))
            held_shares = self._stack.ledger.positions.get(
                symbol, Decimal("0"))
            held_notional = held_shares * decision_price
            desired_notional = (weight * equity).quantize(Decimal("0.01"))
            delta = desired_notional - held_notional
            if abs(delta) < min_notional:
                continue
            side = "buy" if delta > 0 else "sell"
            # WHOLE SHARES, determined BEFORE submission at the decision
            # price (never at the future open)
            shares = (abs(delta) / decision_price).quantize(
                Decimal("1"), rounding=ROUND_DOWN)
            if side == "sell":
                shares = min(shares, held_shares)
            if shares <= 0:
                continue
            # unified USD order contract: intent desired_change == risk
            # notional == OMS sealed quantity == broker order == fill
            # accumulation, all in USD; shares travel separately for
            # reconciliation and the ledger
            order_notional = (shares * decision_price).quantize(
                Decimal("0.01"))
            intent = self._intent_for(asof, symbol, order_notional)
            out = self._stack.submit(intent=intent, asof=asof,
                                     symbol=symbol, side=side,
                                     quantity=order_notional)
            out = replace(out, order_notional_usd=order_notional,
                          order_shares=shares)
            outcomes.append(out)
            if out.outcome_state == "ACKED":
                fill_price = next_opens.get(symbol)
                if fill_price is not None and shares > 0:
                    outcomes.append(self._stack.apply_mock_fill(
                        out, symbol=symbol, side=side, shares=shares,
                        price=fill_price))
        filled = any(o.outcome_state == "FILLED" for o in outcomes)
        refused = any(o.outcome_state in ("REJECTED", "HALT_NEW_RISK")
                      for o in outcomes)
        action = ("TRADE_FILLED" if filled
                  else "RECORDED_REFUSAL" if refused else "NO_CHANGE")
        self.cycle_records.append(self._record(
            asof, decision, outcomes, action,
            list(decision.no_trade_reasons)))
        self.outcomes.extend(outcomes)
        return outcomes

    # -- helpers -----------------------------------------------------------

    def _intent_for(self, asof: dt.datetime, symbol: str,
                    delta: Decimal):
        """Deterministic per-(session, symbol) intent — replay-safe."""
        return self._stack.next_intent(
            asof=asof,
            desired_change=delta.quantize(Decimal("0.01")),
            release_id=f"rel-cont-{self._session_index:06d}-{symbol}",
        )

    def _record(self, asof: dt.datetime, decision: DecisionOutput,
                outcomes: Sequence[ExecutionOutcome], action: str,
                reasons: list[str]) -> dict[str, object]:
        ledger = self._stack.ledger
        return {
            "asof_utc": asof.isoformat(),
            "session_index": self._session_index,
            "chosen": decision.chosen_strategy_id,
            "action": action,
            "reasons": reasons,
            "outcomes": [
                {"intent_id": o.intent_id, "state": o.outcome_state,
                 "risk_verdict": o.risk_verdict,
                 "risk_reasons": list(o.risk_reasons),
                 "fill_qty": o.fill_qty, "fill_price": o.fill_price}
                for o in outcomes],
            "cash": str(ledger.cash),
            "positions": {k: str(v)
                          for k, v in sorted(ledger.positions.items())},
            "equity": str(ledger.equity(self._marks)),
        }

    # -- teardown ------------------------------------------------------------

    def close(self) -> dict[str, object]:
        conservation = self._stack.ledger.conservation_report()
        self._stack.close()
        return {
            "mode": "CONTINUOUS_MOCK_ACCOUNT",
            "ledger": conservation,
            "cycles": len(self.cycle_records),
            "cycle_records": self.cycle_records,
        }
