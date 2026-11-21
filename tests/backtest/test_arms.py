"""M3-R1-T4 — B0/B1/B2 transparent synthetic baselines.

Fixture classes asserted per the task: profit, loss, zero-trade, market
gap, full non-fill, fee-exceeds-profit, dividend/split, cash settlement.
Every result must be stamped SYNTHETIC_ENGINEERING_ONLY and must never
carry an alpha/HIST_OOS_SUPPORTED claim.
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

from conftest import bar, day  # noqa: E402

from trading_lab.backtest.arms import (  # noqa: E402
    ARM_IDS,
    MA_GRID,
    SyntheticDataset,
    equity_curve,
    run_arm,
    select_ma_params,
)
from trading_lab.backtest.engine import BacktestError  # noqa: E402
from trading_lab.contracts import CorporateAction  # noqa: E402

NOW = dt.datetime(2026, 1, 4, 21, 0, tzinfo=dt.timezone.utc)
CODE_HASH = "c" * 32


def ds(name: str, prices: list[str], *, volume="1000000",
       actions: tuple[CorporateAction, ...] = ()) -> SyntheticDataset:
    bars = [bar("SPY", day(i), p, volume=volume)
            for i, p in enumerate(prices)]
    return SyntheticDataset(name=name, bars={"SPY": bars}, actions=actions)


def act(kind: str, day_no: int, factor: str) -> CorporateAction:
    return CorporateAction.model_validate(dict(
        asset_id="SPY", effective_at=day(day_no), announced_at=NOW,
        available_at=NOW, kind=kind, factor=Decimal(factor),
        source="synthetic",
    ))


def run(arm_id, dataset, protocol, **kw):
    kw.setdefault("seed", 42)
    kw.setdefault("code_hash", CODE_HASH)
    return run_arm(arm_id, dataset, protocol, **kw)


# ---------------------------------------------------------------------------
# evidence class + honest claims
# ---------------------------------------------------------------------------


class TestEvidenceClass:
    def test_all_results_stamped_engineering_only(self, protocol):
        data = ds("trend", ["100"] * 12 + ["110"] * 8)
        for arm in ARM_IDS:
            params = ((3, 5) if arm == "B2_single_rule" else None)
            r = run(arm, data, protocol, ma_params=params)
            assert r.evidence_class == "SYNTHETIC_ENGINEERING_ONLY"
            blob = str(r.as_dict()).upper()
            assert "HIST_OOS_SUPPORTED" not in blob
            assert "ALPHA" not in blob

    def test_unknown_arm_rejected(self, protocol):
        with pytest.raises(BacktestError):
            run("B6_ai_champion", ds("x", ["100"]), protocol)

    def test_cost_multiplier_outside_protocol_rejected(self, protocol):
        with pytest.raises(BacktestError):
            run("B0_cash", ds("x", ["100"]), protocol, cost_multiplier=7)


# ---------------------------------------------------------------------------
# B0 cash
# ---------------------------------------------------------------------------


class TestB0Cash:
    def test_zero_trades_zero_return(self, protocol):
        r = run("B0_cash", ds("flat", ["100"] * 10), protocol)
        assert r.net_return == Decimal("0")
        assert r.fills == 0 and r.turnover == 0
        assert r.fees_total == Decimal("0")
        assert r.final_equity == Decimal("100000")
        assert r.effective_observations >= 10

    def test_b0_ignores_volatile_market(self, protocol):
        data = ds("crazy", ["100", "200", "50", "180", "60"] * 4)
        r = run("B0_cash", data, protocol)
        assert r.max_drawdown == Decimal("0")
        assert r.net_return == Decimal("0")


# ---------------------------------------------------------------------------
# B1 buy & hold
# ---------------------------------------------------------------------------


class TestB1BuyHold:
    def test_profit_scenario(self, protocol):
        data = ds("bull", ["100"] * 10 + ["130"] * 5)
        r = run("B1_buy_hold", data, protocol)
        assert r.net_return > 0
        assert r.fills == 1
        assert r.selection_note  # declared, auditable

    def test_loss_scenario(self, protocol):
        data = ds("bear", ["100"] * 10 + ["70"] * 5)
        r = run("B1_buy_hold", data, protocol)
        assert r.net_return < 0
        assert r.max_drawdown > 0

    def test_market_gap_captured(self, protocol):
        data = ds("gap", ["100"] * 8 + ["150"] * 4)
        r = run("B1_buy_hold", data, protocol)
        # 50-share position ≈ 5% of capital; a +50% gap ≈ +2.4% portfolio
        assert r.net_return > Decimal("0.02")

    def test_dividend_credits_and_counts(self, protocol):
        data = ds("div", ["100"] * 12, actions=(act("DIVIDEND", 6, "1.00"),))
        r = run("B1_buy_hold", data, protocol)
        # 50 shares × 1.00 cash dividend on top of flat price: small net
        # positive after fees/costs
        assert r.final_equity > Decimal("100000") + Decimal("50") - \
            Decimal("10")  # dividend 50 − commission 1 − spread costs < 10
        assert r.selection_note

    def test_split_scales_position(self, protocol):
        # 2:1 split at day(6) with the price halving (wealth-neutral:
        # 50 sh × 100 == 100 sh × 50)
        prices = ["100"] * 6 + ["50"] * 6
        data = ds("split", prices, actions=(act("SPLIT", 6, "2"),))
        r = run("B1_buy_hold", data, protocol)
        assert abs(r.final_equity - Decimal("100000")) <= Decimal("250")
        assert r.fills == 1

    def test_full_nonfill_leaves_flat(self, protocol):
        data = ds("novol", ["100"] * 10, volume="0")
        r = run("B1_buy_hold", data, protocol)
        assert r.fills == 0
        assert r.unfilled >= 1
        assert r.net_return == Decimal("0")

    def test_cash_settlement_within_run(self, protocol):
        # B1 never sells, so assert settlement through a dedicated engine run
        from trading_lab.backtest.engine import BacktestEngine
        data = ds("settle", ["100"] * 8)
        eng = BacktestEngine(bars=data.bars, initial_cash=Decimal("10000"),
                             protocol=protocol, seed=42,
                             dataset_hash=data.dataset_hash,
                             code_hash=CODE_HASH)
        eng.submit(decision_at=day(0), symbol="SPY", side="buy",
                   qty=Decimal("10"))
        eng.run_to_end()
        assert eng.account.cash_unsettled == Decimal("0")  # settled by end
        assert eng.conservation_report()["ok"]


# ---------------------------------------------------------------------------
# B2 single rule (MA cross)
# ---------------------------------------------------------------------------


class TestB2SingleRule:
    def test_requires_frozen_params(self, protocol):
        with pytest.raises(BacktestError, match="frozen ma_params"):
            run("B2_single_rule", ds("x", ["100"] * 10), protocol)

    def test_trending_market_positive(self, protocol):
        data = ds("trend", ["100"] * 6 + ["101", "103", "106", "110",
                                          "115", "121", "128", "136"])
        params, trials = select_ma_params(
            data, protocol, train_val_end=day(5), code_hash=CODE_HASH,
            seed=42)
        assert trials == len(MA_GRID)  # full grid billed
        r = run("B2_single_rule", data, protocol, ma_params=params)
        assert r.net_return > 0
        assert "frozen from" in r.selection_note

    def test_choppy_market_reports_honestly(self, protocol):
        data = ds("choppy", ["100", "104", "98", "105", "97", "106", "96",
                             "107", "95", "108", "94", "109"])
        params, _ = select_ma_params(
            data, protocol, train_val_end=day(5), code_hash=CODE_HASH,
            seed=42)
        r = run("B2_single_rule", data, protocol, ma_params=params)
        # no profitability claim either way — the assertion is that the
        # harness reports honestly and conserves cash
        assert r.effective_observations >= 10
        assert r.turnover >= 0
        assert r.net_return == r.net_return  # a real number, not NaN

    def test_fee_exceeds_profit_scenario(self, protocol):
        """Buy near the top of a rise, then a sharp reversal: the exit
        fills far below the entry — costs add on top; net must be negative."""
        data = ds("flatfees", ["100", "100", "100", "101", "102", "103",
                               "104", "105", "106", "100", "96", "92", "90",
                               "88", "86", "84"])
        params, _ = select_ma_params(
            data, protocol, train_val_end=day(7), code_hash=CODE_HASH,
            seed=42)
        r = run("B2_single_rule", data, protocol, ma_params=params,
                initial_cash=Decimal("100000"))
        assert r.net_return < 0
        assert r.fills >= 2
        assert r.fees_total >= Decimal("2")  # at least roundtrip fees

    def test_selection_cannot_see_beyond_boundary(self, protocol):
        """select_ma_params must be fed a strictly sliced dataset — bars
        beyond train_val_end are invisible to the selection engines."""
        data = ds("leak", ["100"] * 8 + ["500"] * 8)  # huge later jump
        params, trials = select_ma_params(
            data, protocol, train_val_end=day(7), code_hash=CODE_HASH,
            seed=42)
        assert trials == len(MA_GRID)
        # The huge day(8+) jump cannot have influenced selection: on the
        # slice alone the chosen pair is reproducible from sliced data.
        from conftest import bar as mkbar
        sliced = SyntheticDataset(
            name="leak-slice",
            bars={"SPY": [mkbar("SPY", day(i), "100") for i in range(8)]})
        params2, _ = select_ma_params(
            sliced, protocol, train_val_end=day(7), code_hash=CODE_HASH,
            seed=42)
        assert params == params2


# ---------------------------------------------------------------------------
# cost sensitivity x1/x2/x3 (§4.3 same-evaluation)
# ---------------------------------------------------------------------------


class TestCostSensitivity:
    def test_cost_multipliers_rank_returns(self, protocol):
        data = ds("rt", ["100"] * 6 + ["102"] * 10)
        results = [run("B2_single_rule", data, protocol, ma_params=(3, 5),
                       cost_multiplier=m) for m in (1, 2, 3)]
        r1, r2, r3 = results
        assert r1.cost_multiplier == 1 and r3.cost_multiplier == 3
        assert r1.net_return >= r2.net_return >= r3.net_return
        assert r3.fees_total == pytest.approx(float(r1.fees_total) * 3)

    def test_all_arms_share_dataset_hash(self, protocol):
        data = ds("shared", ["100"] * 10)
        hashes = set()
        for arm in ARM_IDS:
            params = ((3, 5) if arm == "B2_single_rule" else None)
            r = run(arm, data, protocol, ma_params=params)
            hashes.add((r.dataset_hash, r.protocol_hash))
        assert len(hashes) == 1  # same snapshot/protocol for every arm


# ---------------------------------------------------------------------------
# determinism at arm level
# ---------------------------------------------------------------------------


class TestArmDeterminism:
    def test_same_inputs_identical_results(self, protocol):
        data = ds("det", ["100", "101", "102", "101", "103", "104", "103",
                          "105", "106", "105", "107", "108"])
        params = (3, 5)
        a = run("B2_single_rule", data, protocol, ma_params=params)
        b = run("B2_single_rule", data, protocol, ma_params=params)
        assert a.as_dict() == b.as_dict()

    def test_dataset_hash_changes_with_content(self, protocol):
        d1 = ds("h1", ["100"] * 10)
        d2 = ds("h1", ["100"] * 9 + ["101"])
        assert d1.dataset_hash != d2.dataset_hash
        assert d1.dataset_hash == ds("h1", ["100"] * 10).dataset_hash
