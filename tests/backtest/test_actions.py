"""M3-R1-T3 — corporate actions, delisting, settlement, protocol drift.

Corporate-action events reuse ``contracts.CorporateAction`` (the contract
layer's action semantics) — the backtest applies them in execution space:
SPLIT scales the position, DIVIDEND credits cash per share, DELISTING
force-liquidates and blocks the symbol afterwards (ticker reuse is
fail-closed at dataset level).
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

from trading_lab.backtest import BacktestEngine, BacktestError  # noqa: E402
from trading_lab.contracts import CorporateAction  # noqa: E402

NOW = dt.datetime(2026, 1, 4, 21, 0, tzinfo=dt.timezone.utc)


def action(kind: str, effective: dt.datetime, factor: str,
           symbol: str = "SPY") -> CorporateAction:
    return CorporateAction.model_validate(dict(
        asset_id=symbol, effective_at=effective, announced_at=NOW,
        available_at=NOW, kind=kind, factor=Decimal(factor),
        source="synthetic",
    ))


def flat(n: int = 8, price: str = "100"):
    return [bar("SPY", day(i), price) for i in range(n)]


class TestSplits:
    def test_split_scales_position_no_cash(self, protocol):
        bars = flat()
        eng = BacktestEngine(
            bars={"SPY": bars}, initial_cash=Decimal("10000"),
            protocol=protocol, actions=[action("SPLIT", day(3), "2")],
            seed=42, dataset_hash="d" * 32, code_hash="c" * 32)
        eng.submit(decision_at=day(0), symbol="SPY", side="buy",
                   qty=Decimal("10"))  # fills day(1)
        eng.run_to_end()
        assert eng.account.positions["SPY"] == Decimal("20")
        splits = [e for e in eng.events if e.kind == "SPLIT"]
        assert len(splits) == 1 and splits[0].ts == day(3)
        assert eng.account.cash_available + eng.account.cash_unsettled \
            == Decimal("10000") - (Decimal("10") * Decimal("100.15") + 1)
        assert eng.conservation_report()["ok"]

    def test_split_factor_must_be_positive(self, protocol):
        with pytest.raises(BacktestError):
            BacktestEngine(
                bars={"SPY": flat()}, initial_cash=Decimal("10000"),
                protocol=protocol, actions=[action("SPLIT", day(3), "0")],
                seed=42, dataset_hash="d" * 32, code_hash="c" * 32)


class TestDividends:
    def test_dividend_credits_cash_per_share(self, protocol):
        eng = BacktestEngine(
            bars={"SPY": flat()}, initial_cash=Decimal("10000"),
            protocol=protocol, actions=[action("DIVIDEND", day(3), "0.50")],
            seed=42, dataset_hash="d" * 32, code_hash="c" * 32)
        eng.submit(decision_at=day(0), symbol="SPY", side="buy",
                   qty=Decimal("10"))
        eng.run_to_end()
        divs = [e for e in eng.events if e.kind == "DIVIDEND"]
        assert len(divs) == 1
        assert divs[0].qty == Decimal("5.0000")  # 10 shares × 0.50
        assert eng.account.dividends_total == Decimal("5.0000")
        assert eng.conservation_report()["ok"]

    def test_dividend_without_position_credits_nothing(self, protocol):
        eng = BacktestEngine(
            bars={"SPY": flat()}, initial_cash=Decimal("10000"),
            protocol=protocol, actions=[action("DIVIDEND", day(3), "0.50")],
            seed=42, dataset_hash="d" * 32, code_hash="c" * 32)
        eng.run_to_end()
        assert eng.account.dividends_total == Decimal("0")


class TestDelisting:
    def test_delist_force_liquidates_and_blocks_symbol(self, protocol):
        bars = flat(n=7)                   # day(0)..day(6); no bars after delist
        bars[6] = bar("SPY", day(6), "80")  # price drop at the last session
        eng = BacktestEngine(
            bars={"SPY": bars}, initial_cash=Decimal("10000"),
            protocol=protocol,
            actions=[action("DELISTING", day(6), "1")],
            seed=42, dataset_hash="d" * 32, code_hash="c" * 32)
        eng.submit(decision_at=day(0), symbol="SPY", side="buy",
                   qty=Decimal("10"))
        eng.run_to_end()
        delists = [e for e in eng.events if e.kind == "DELIST"]
        assert len(delists) == 1
        assert delists[0].qty == Decimal("10")
        assert delists[0].exec_price == (
            Decimal("80") * (Decimal("1") - Decimal("0.001")
                             - Decimal("0.0005"))).quantize(Decimal("0.0001"))
        assert eng.account.positions.get("SPY", Decimal("0")) == 0
        assert eng.conservation_report()["ok"]
        with pytest.raises(BacktestError, match="delisted"):
            eng.submit(decision_at=day(6), symbol="SPY", side="buy",
                       qty=Decimal("1"))

    def test_ticker_reuse_after_delist_rejected(self, protocol):
        bars = flat(n=8)
        bars[7] = bar("SPY", day(7), "90")  # reuse AFTER delist
        with pytest.raises(BacktestError, match="ticker reuse"):
            BacktestEngine(
                bars={"SPY": bars}, initial_cash=Decimal("10000"),
                protocol=protocol,
                actions=[action("DELISTING", day(6), "1")],
                seed=42, dataset_hash="d" * 32, code_hash="c" * 32)

    def test_unknown_action_kind_rejected(self, protocol):
        with pytest.raises(BacktestError, match="unsupported corporate"):
            BacktestEngine(
                bars={"SPY": flat()}, initial_cash=Decimal("10000"),
                protocol=protocol,
                actions=[action("MERGER_TENDER", day(3), "1")],
                seed=42, dataset_hash="d" * 32, code_hash="c" * 32)


class TestProtocolDriftGuard:
    def test_engine_config_matches_protocol(self, protocol):
        """The module DEFAULTS must equal the frozen protocol's derived
        config — if the YAML is re-frozen, this test forces the defaults
        (and this file's scenario arithmetic) to be re-reviewed."""
        eng_no_protocol = BacktestEngine(
            bars={"SPY": flat(n=2)}, initial_cash=Decimal("1000"),
            seed=42, dataset_hash="d" * 32, code_hash="c" * 32)
        eng_protocol = BacktestEngine(
            bars={"SPY": flat(n=2)}, initial_cash=Decimal("1000"),
            protocol=protocol, seed=42, dataset_hash="d" * 32,
            code_hash="c" * 32)
        assert eng_no_protocol.cost == eng_protocol.cost
        assert eng_no_protocol.execution == eng_protocol.execution

    def test_same_day_close_config_refused(self, protocol):
        """allow_same_day_close=true violates ADR-004; engine refuses even
        if a future protocol edit tried to enable it (duck-typed stub keeps
        the real code path — no internal patching)."""
        from trading_lab.backtest import engine as eng_mod

        real_exec = dict(protocol.execution)

        class _StubProtocol:
            protocol_hash = "stub"
            cost_model = dict(protocol.cost_model)
            execution = {**real_exec, "allow_same_day_close": True}

        with pytest.raises(BacktestError, match="same_day_close"):
            BacktestEngine(
                bars={"SPY": flat(n=2)}, initial_cash=Decimal("1000"),
                protocol=_StubProtocol(), seed=42, dataset_hash="d" * 32,
                code_hash="c" * 32)
