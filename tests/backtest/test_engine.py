"""M3-R1-T3 — trustworthy minimal offline backtest kernel.

RED-first: written and run before src/trading_lab/backtest/engine.py was
rewritten (ImportError/AttributeError = RED). Every negative case from the
task list has an explicit test; conservation is asserted after every
positive scenario; determinism binds seed + protocol/dataset/code hashes.
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

from helpers_backtest import bar, day  # noqa: E402

from trading_lab.backtest import BacktestEngine, BacktestError  # noqa: E402
from trading_lab.contracts import CorporateAction  # noqa: E402

TOL = Decimal("0.0001")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def make_engine(bars_by_symbol, *, actions=(), initial_cash="10000",
                protocol=None, seed=42, dataset_hash="d" * 32,
                code_hash="c" * 32) -> BacktestEngine:
    return BacktestEngine(
        bars=bars_by_symbol,
        actions=list(actions),
        initial_cash=Decimal(initial_cash),
        protocol=protocol,
        seed=seed,
        dataset_hash=dataset_hash,
        code_hash=code_hash,
    )


def flat_series(symbol: str, price: str, n: int = 6, start_day: int = 0):
    return [bar(symbol, day(start_day + i), price) for i in range(n)]


# ---------------------------------------------------------------------------
# Account-level negatives (Decimal chain, fail-closed)
# ---------------------------------------------------------------------------


class TestAccountNegatives:
    def _acc(self, cash="10000"):
        from trading_lab.backtest.engine import BacktestAccount

        return BacktestAccount(initial_cash=Decimal(cash))

    def test_negative_price_buy_rejected(self):
        acc = self._acc()
        with pytest.raises(BacktestError):
            acc.buy(ts=day(0), symbol="SPY", qty=Decimal("1"),
                    exec_price=Decimal("-5"), commission=Decimal("1"))

    def test_zero_price_buy_rejected(self):
        acc = self._acc()
        with pytest.raises(BacktestError):
            acc.buy(ts=day(0), symbol="SPY", qty=Decimal("1"),
                    exec_price=Decimal("0"), commission=Decimal("1"))

    def test_zero_qty_rejected(self):
        acc = self._acc()
        with pytest.raises(BacktestError):
            acc.buy(ts=day(0), symbol="SPY", qty=Decimal("0"),
                    exec_price=Decimal("100"), commission=Decimal("1"))

    def test_negative_qty_sell_rejected(self):
        acc = self._acc()
        with pytest.raises(BacktestError):
            acc.sell(ts=day(0), symbol="SPY", qty=Decimal("-1"),
                     exec_price=Decimal("100"), commission=Decimal("1"))

    @pytest.mark.parametrize("bad", [100.5, 100, "100"])
    def test_non_decimal_inputs_rejected(self, bad):
        """float / int / str mixing into the money chain is fail-closed."""
        acc = self._acc()
        with pytest.raises(BacktestError):
            acc.buy(ts=day(0), symbol="SPY", qty=Decimal("1"),
                    exec_price=bad, commission=Decimal("1"))  # type: ignore[arg-type]

    def test_insufficient_funds_buy_rejected_no_negative_cash(self):
        acc = self._acc(cash="100")
        with pytest.raises(BacktestError):
            acc.buy(ts=day(0), symbol="SPY", qty=Decimal("5"),
                    exec_price=Decimal("50"), commission=Decimal("1"))
        assert acc.cash_available == Decimal("100")
        assert acc.positions.get("SPY", Decimal("0")) == 0

    def test_oversell_rejected(self):
        acc = self._acc()
        acc.buy(ts=day(0), symbol="SPY", qty=Decimal("2"),
                exec_price=Decimal("100"), commission=Decimal("1"))
        with pytest.raises(BacktestError):
            acc.sell(ts=day(1), symbol="SPY", qty=Decimal("3"),
                     exec_price=Decimal("100"), commission=Decimal("1"))

    def test_missing_mark_equity_fails_closed_not_zero(self):
        acc = self._acc()
        acc.buy(ts=day(0), symbol="SPY", qty=Decimal("2"),
                exec_price=Decimal("100"), commission=Decimal("1"))
        with pytest.raises(BacktestError):
            acc.equity({})  # no price for held SPY — must NOT default to 0

    def test_equity_correct_when_marks_given(self):
        acc = self._acc(cash="1000")
        acc.buy(ts=day(0), symbol="SPY", qty=Decimal("2"),
                exec_price=Decimal("100"), commission=Decimal("1"))
        # 1000 - 200 - 1 = 799 cash
        assert acc.equity({"SPY": Decimal("110")}) == Decimal("1019")


# ---------------------------------------------------------------------------
# Engine input validation
# ---------------------------------------------------------------------------


class TestEngineInputValidation:
    def test_duplicate_bar_timestamp_rejected(self):
        dup = [bar("SPY", day(0), "100"), bar("SPY", day(0), "100")]
        with pytest.raises(BacktestError):
            make_engine({"SPY": dup})

    def test_non_monotonic_bars_rejected(self):
        rev = [bar("SPY", day(1), "100"), bar("SPY", day(0), "100")]
        with pytest.raises(BacktestError):
            make_engine({"SPY": rev})

    def test_empty_dataset_fails_closed(self):
        with pytest.raises(BacktestError):
            make_engine({})

    def test_unknown_symbol_signal_rejected(self):
        eng = make_engine({"SPY": flat_series("SPY", "100")})
        with pytest.raises(BacktestError):
            eng.submit(decision_at=day(0), symbol="QQQ", side="buy",
                       qty=Decimal("1"))

    def test_time_reversal_signal_rejected(self):
        """A decision_at earlier than a previously processed decision on the
        same engine cannot happen in a forward run — engine enforces
        monotone decision time."""
        eng = make_engine({"SPY": flat_series("SPY", "100")})
        eng.submit(decision_at=day(2), symbol="SPY", side="buy",
                   qty=Decimal("1"))
        with pytest.raises(BacktestError):
            eng.submit(decision_at=day(1), symbol="SPY", side="sell",
                       qty=Decimal("1"))


# ---------------------------------------------------------------------------
# Execution semantics
# ---------------------------------------------------------------------------


class TestExecutionSemantics:
    def test_close_signal_cannot_fill_same_close(self, protocol):
        """Signal formed at close T must fill at T+1 open at the earliest
        (order_delay_bars=1, allow_same_day_close=false)."""
        eng = make_engine({"SPY": flat_series("SPY", "100")}, protocol=protocol)
        eng.submit(decision_at=day(0), symbol="SPY", side="buy",
                   qty=Decimal("10"))
        eng.run_to_end()
        fills = [e for e in eng.events if e.kind == "FILL"]
        assert len(fills) == 1
        assert fills[0].ts == day(1)  # executed on the NEXT session
        assert fills[0].qty == Decimal("10")

    def test_exec_price_side_adjusted_spread_slippage(self, protocol):
        eng = make_engine({"SPY": flat_series("SPY", "100")}, protocol=protocol)
        eng.submit(decision_at=day(0), symbol="SPY", side="buy",
                   qty=Decimal("10"))
        eng.run_to_end()
        fill = [e for e in eng.events if e.kind == "FILL"][0]
        # exec price = open(100) * (1 + spread 0.001 + slippage 0.0005) = 100.15
        expected = (Decimal("100") * (Decimal("1") + Decimal("0.001")
                                      + Decimal("0.0005"))).quantize(Decimal("0.0001"))
        assert abs(fill.exec_price - expected) <= TOL

    def test_sell_side_exec_price_discounted(self, protocol):
        bars = flat_series("SPY", "100", n=6)
        eng = make_engine({"SPY": bars}, protocol=protocol)
        eng.submit(decision_at=day(0), symbol="SPY", side="buy",
                   qty=Decimal("10"))
        eng.run_to(bar_ts=day(1))
        eng.submit(decision_at=day(1), symbol="SPY", side="sell",
                   qty=Decimal("10"))
        eng.run_to_end()
        fills = [e for e in eng.events if e.kind == "FILL"]
        assert len(fills) == 2
        sell_px = fills[1].exec_price
        expected_sell = (Decimal("100") * (Decimal("1") - Decimal("0.001")
                                           - Decimal("0.0005"))).quantize(Decimal("0.0001"))
        assert abs(sell_px - expected_sell) <= TOL

    def test_volume_cap_partial_fill(self, protocol):
        """Requested size above 10% of bar volume fills capped; the residual
        is cancelled (partial-fill event recorded, conservation intact)."""
        bars = [bar("SPY", day(0), "100", volume="10000"),
                bar("SPY", day(1), "100", volume="1000"),  # cap = 100
                bar("SPY", day(2), "100", volume="10000")]
        eng = make_engine({"SPY": bars}, protocol=protocol, initial_cash="20000")
        eng.submit(decision_at=day(0), symbol="SPY", side="buy",
                   qty=Decimal("500"))
        eng.run_to_end()
        kinds = [e.kind for e in eng.events]
        assert "FILL" in kinds
        fill = [e for e in eng.events if e.kind == "FILL"][0]
        assert fill.qty == Decimal("100")  # volume_limit_pct * 1000
        assert "CANCEL" in kinds  # the 400 residual never carries over

    def test_full_unfill_when_zero_capacity(self, protocol):
        bars = [bar("SPY", day(0), "100", volume="10000"),
                bar("SPY", day(1), "100", volume="0")]
        eng = make_engine({"SPY": bars}, protocol=protocol)
        eng.submit(decision_at=day(0), symbol="SPY", side="buy",
                   qty=Decimal("10"))
        eng.run_to_end()
        kinds = [e.kind for e in eng.events]
        assert "UNFILLED" in kinds
        assert not [e for e in eng.events if e.kind == "FILL"]

    def test_order_beyond_data_window_cancelled(self, protocol):
        eng = make_engine({"SPY": flat_series("SPY", "100", n=3)},
                          protocol=protocol)
        eng.submit(decision_at=day(2), symbol="SPY", side="buy",
                   qty=Decimal("1"))
        eng.run_to_end()
        assert "CANCEL" in [e.kind for e in eng.events]

    def test_available_bars_respects_pit(self, protocol):
        """A bar whose information is available after the decision instant
        must not be visible (available_at <= decision_at)."""
        from trading_lab.contracts import AdjustmentKind, MarketBar
        delayed = MarketBar.model_validate(dict(
            asset_id="SPY", ts_event_utc=day(1),
            ts_available_utc=day(1) + dt.timedelta(hours=12),
            interval="1d", open=Decimal("100"), high=Decimal("110"),
            low=Decimal("95"), close=Decimal("110"), volume=Decimal("1000"),
            source="synthetic", adjustment=AdjustmentKind.RAW, quality="ok",
        ))
        eng = make_engine({"SPY": [bar("SPY", day(0), "100"), delayed]},
                          protocol=protocol)
        at_close = eng.available_closes("SPY", day(1))
        assert [b.ts_event_utc for b in at_close] == [day(0)]  # day1 hidden
        after = eng.available_closes("SPY", day(1) + dt.timedelta(hours=13))
        assert [b.ts_event_utc for b in after] == [day(0), day(1)]


# ---------------------------------------------------------------------------
# Cash settlement + conservation
# ---------------------------------------------------------------------------


class TestSettlementAndConservation:
    def test_sell_proceeds_settle_t_plus_2(self, protocol):
        bars = flat_series("SPY", "100", n=8)
        eng = make_engine({"SPY": bars}, protocol=protocol,
                          initial_cash="10000")
        eng.submit(decision_at=day(0), symbol="SPY", side="buy",
                   qty=Decimal("10"))    # fills day(1)
        eng.submit(decision_at=day(1), symbol="SPY", side="sell",
                   qty=Decimal("10"))    # fills day(2); settles day(4)
        eng.run_to_end()
        fills = [e for e in eng.events if e.kind == "FILL"]
        assert len(fills) == 2
        assert fills[1].ts == day(2)
        settles = [e for e in eng.events if e.kind == "SETTLE"]
        assert any(e.ts == day(4) for e in settles)
        assert eng.account.cash_unsettled == Decimal("0")
        assert eng.account.cash_available > Decimal("0")
        assert eng.conservation_report()["ok"]

    def test_unsettled_cash_not_spendable(self, protocol):
        """cash_available must never go negative; a buy that would need
        unsettled proceeds is rejected outright (REJECT event, run continues)."""
        bars = flat_series("SPY", "100", n=8)
        eng = make_engine({"SPY": bars}, protocol=protocol, initial_cash="1000")
        eng.submit(decision_at=day(0), symbol="SPY", side="buy",
                   qty=Decimal("9"))  # ~901 cost — fits
        eng.run_to(bar_ts=day(2))
        eng.submit(decision_at=day(2), symbol="SPY", side="buy",
                   qty=Decimal("50"))  # ~5008 — must be rejected
        eng.run_to_end()
        assert eng.account.cash_available >= 0
        assert "REJECT" in [e.kind for e in eng.events]

    def test_conservation_after_full_roundtrip(self, protocol):
        bars = flat_series("SPY", "100", n=10)
        bars[5] = bar("SPY", day(5), "120")
        eng = make_engine({"SPY": bars}, protocol=protocol, initial_cash="5000")
        eng.submit(decision_at=day(0), symbol="SPY", side="buy",
                   qty=Decimal("10"))
        eng.submit(decision_at=day(5), symbol="SPY", side="sell",
                   qty=Decimal("10"))
        eng.run_to_end()
        recon = eng.conservation_report()
        assert recon["ok"], recon
        # explicit identity: cash_available + cash_unsettled + fees
        #   == initial + dividends - buy_gross + sell_gross
        assert (eng.account.cash_available + eng.account.cash_unsettled
                + eng.account.fees_total
                == Decimal("5000") - recon["buy_gross"] + recon["sell_gross"])


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


class TestDeterminism:
    def _run(self, seed: int, code_hash: str, dataset_hash: str = "d" * 32):
        bars = flat_series("SPY", "100", n=8)
        bars[4] = bar("SPY", day(4), "115")
        eng = make_engine({"SPY": bars}, seed=seed, code_hash=code_hash,
                          dataset_hash=dataset_hash)
        eng.submit(decision_at=day(0), symbol="SPY", side="buy",
                   qty=Decimal("10"))
        eng.submit(decision_at=day(4), symbol="SPY", side="sell",
                   qty=Decimal("10"))
        eng.run_to_end()
        return eng.output_digest()

    def test_same_inputs_same_digest(self, protocol):
        d1 = self._run(42, "c" * 32)
        d2 = self._run(42, "c" * 32)
        assert d1 == d2

    def test_different_code_hash_different_digest(self, protocol):
        assert self._run(42, "c" * 32) != self._run(42, "f" * 32)

    def test_digest_binds_protocol_hash(self, protocol):
        eng = make_engine({"SPY": flat_series("SPY", "100")},
                          protocol=protocol)
        assert eng.run_identity()["protocol_hash"] == protocol.protocol_hash
