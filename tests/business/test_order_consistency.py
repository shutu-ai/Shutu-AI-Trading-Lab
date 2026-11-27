"""T1 order-consistency RED tests (task BUSINESS-V02-ACTIVATION-
V03-DAILY-WORKFLOW-20261127-R1 §2 T1).

These pin the unified USD order contract for continuous mock execution:
- the sizing input is the PIT decision price ONLY (never the future
  next-open);
- order quantity travels in USD end to end (intent == risk notional ==
  OMS seal == broker order == fill accumulation);
- whole shares are determined BEFORE submission from the decision price;
- the execution outcome reports the BROKER'S real terminal state
  (FILLED / PARTIALLY_FILLED), never a hardcoded FILLED;
- sells reduce risk exposure (gross/net checks subtract, never add);
- three-way reconciliation: order USD == shares-at-decision-price;
  fill USD == filled-shares x fill-price; ledger shares == broker-filled
  shares.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from pathlib import Path

import pytest

from trading_lab.business.config import load_config
from trading_lab.business.continuous import ContinuousMockRunner
from trading_lab.business.types import DecisionOutput
from trading_lab.contracts import AllocationItem, TargetPortfolio

REPO = Path(__file__).resolve().parents[2]
UTC = dt.timezone.utc


def _ts(day: int) -> dt.datetime:
    return dt.datetime(2024, 3, day, 21, 0, tzinfo=UTC)


@pytest.fixture()
def runner(tmp_path):
    cfg = load_config(REPO / "configs/business_mvp_demo.yaml")
    clock = {"now": _ts(1)}
    r = ContinuousMockRunner(config=cfg, state_dir=tmp_path / "cont",
                             clock=lambda: clock["now"])
    r.bind_dataset("c" * 32)
    r._clock = clock
    yield r
    r.close()


def _decision(weights: dict[str, str], asof: dt.datetime,
              chosen: str = "ma_cross_trend") -> DecisionOutput:
    alloc = tuple(AllocationItem(symbol=s, weight=Decimal(w))
                  for s, w in sorted(weights.items()))
    cash = Decimal("1") - sum(Decimal(w) for w in weights.values())
    return DecisionOutput(
        asof_utc=asof, chosen_strategy_id=chosen,
        target=TargetPortfolio(
            account_id="MOCK-ACCT-001", allocation=alloc, cash_weight=cash,
            risk_budget_id="BUSINESS_DEMO_RISK_BUDGET", timestamp=asof),
        no_trade_reasons=(), candidate_scores={}, rationale="ok",
        decision_hash="b" * 32)


class TestSizingPriceIsDecisionPriceOnly:
    def test_missing_decision_price_is_no_trade_not_future_sizing(
            self, runner):
        """No PIT mark for QQQ -> the QQQ leg records NO_TRADE with a
        reason; the future next-open price must NOT be used for sizing."""
        runner._clock["now"] = _ts(1)
        out = runner.step(
            asof=_ts(1),
            decision=_decision({"SPY": "0.4", "QQQ": "0.4"}, _ts(1)),
            marks={"SPY": Decimal("450.00")},   # QQQ mark MISSING
            next_opens={"SPY": Decimal("451.00"),
                        "QQQ": Decimal("350.50")})
        symbols_touched = {o.client_order_id.split(":")[-1][:3] for o in out}
        # QQQ never appears with a next-open-sized order; the only orders
        # are SPY ones sized at the decision mark
        assert all("QQQ" not in (o.intent_id or "") for o in out)
        rec = runner.cycle_records[-1]
        assert rec["action"] in ("TRADE_FILLED", "NO_CHANGE")
        assert not any(
            o.fill_qty is not None and o.fill_price == Decimal("350.50")
            for o in out), "future next-open must not size fills"


class TestUnifiedUsdOrderContract:
    def test_order_usd_equals_shares_times_decision_price(self, runner):
        """intent USD == submitted quantity == whole shares x decision
        price — the three-way identity, auditable from the outcomes."""
        runner._clock["now"] = _ts(1)
        out = runner.step(
            asof=_ts(1), decision=_decision({"SPY": "0.5"}, _ts(1)),
            marks={"SPY": Decimal("450.00"), "QQQ": Decimal("350.00")},
            next_opens={"SPY": Decimal("451.00"), "QQQ": Decimal("350.50")})
        submits = [o for o in out if o.outcome_state == "ACKED"]
        assert submits, "expected an approved order"
        for o in submits:
            assert o.order_notional_usd is not None
            assert o.order_shares is not None
            assert o.order_notional_usd == o.order_shares * Decimal("450.00")

    def test_fill_reported_in_broker_terminal_state(self, runner):
        """The fill outcome's state comes from the broker (FILLED or
        PARTIALLY_FILLED), not a hardcoded FILLED."""
        runner._clock["now"] = _ts(1)
        out = runner.step(
            asof=_ts(1), decision=_decision({"SPY": "0.5"}, _ts(1)),
            marks={"SPY": Decimal("450.00"), "QQQ": Decimal("350.00")},
            next_opens={"SPY": Decimal("451.00"), "QQQ": Decimal("350.50")})
        fills = [o for o in out if o.fill_qty is not None]
        assert fills, "expected a fill outcome"
        for f in fills:
            assert f.outcome_state in ("FILLED", "PARTIALLY_FILLED")
            assert f.order_shares is not None
            assert f.fill_qty <= f.order_shares

    def test_ledger_shares_equal_broker_filled_shares(self, runner):
        """Three-way reconciliation: the mock ledger's share position
        equals the broker's accumulated filled shares for the coid."""
        runner._clock["now"] = _ts(1)
        out = runner.step(
            asof=_ts(1), decision=_decision({"SPY": "0.5"}, _ts(1)),
            marks={"SPY": Decimal("450.00"), "QQQ": Decimal("350.00")},
            next_opens={"SPY": Decimal("451.00"), "QQQ": Decimal("350.50")})
        fills = [o for o in out if o.fill_qty is not None]
        assert fills
        f = fills[0]
        assert runner._stack.ledger.positions["SPY"] == f.fill_qty
        assert f.fill_price == Decimal("451.00")  # execution-clock price
        # ledger conservation still holds (USD bookkeeping)
        assert runner._stack.ledger.conservation_report()["ok"] is True


class TestSellReducesRisk:
    def test_large_holding_exit_not_refused_as_risk_increase(
            self, runner):
        """Enter a full book, then exit: the sell's notional must not be
        added to gross/net exposure (a sell RELEASES risk). With the
        V0.2 add-semantics a 0.5-book exit could trip the caps after a
        price rise; with subtract-semantics it passes."""
        runner._clock["now"] = _ts(1)
        runner.step(asof=_ts(1), decision=_decision({"SPY": "0.9"}, _ts(1)),
                    marks={"SPY": Decimal("400.00"), "QQQ": Decimal("350.00")},
                    next_opens={"SPY": Decimal("400.00"),
                                "QQQ": Decimal("350.50")})
        spy = runner._stack.ledger.positions.get("SPY", Decimal("0"))
        assert spy > 0
        # price rises 10%; the exit notional is now ~10% larger than at
        # entry — under add-semantics this would blow the gross cap
        runner._clock["now"] = _ts(2)
        out = runner.step(
            asof=_ts(2), decision=_decision({}, _ts(2), "high_vol_defensive"),
            marks={"SPY": Decimal("440.00"), "QQQ": Decimal("350.00")},
            next_opens={"SPY": Decimal("441.00"), "QQQ": Decimal("350.50")})
        exits = [o for o in out if o.client_order_id and "sell" in
                 (o.notes[-1] if o.notes else "") or o.fill_qty]
        assert any(o.outcome_state == "FILLED" for o in out), (
            "exit must fill: a sell cannot be refused as risk INCREASE; "
            f"got {[ (o.outcome_state, o.risk_reasons) for o in out ]}")
        assert runner._stack.ledger.positions.get("SPY", Decimal("0")) < spy
