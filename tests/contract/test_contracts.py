"""Contract tests for the §2.2 event contracts: acceptance of valid data and
rejection of every invalid shape that could smuggle risk past a gate."""

from __future__ import annotations

import datetime as dt
import sys
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from trading_lab.contracts import (  # noqa: E402
    AdjustmentKind,
    Environment,
    LiveRelease,
    MarketBar,
    StrategySignal,
    TargetPortfolio,
    TradeIntent,
)

NOW = dt.datetime(2026, 11, 20, tzinfo=dt.timezone.utc)


def valid_bar(**over):
    base = dict(
        asset_id="SPY",
        ts_event_utc=NOW,
        ts_available_utc=NOW,
        interval="1d",
        open=Decimal("100"),
        high=Decimal("110"),
        low=Decimal("95"),
        close=Decimal("105"),
        volume=Decimal("1000000"),
        source="vendor",
        adjustment=AdjustmentKind.RAW,
        quality="ok",
    )
    base.update(over)
    return base


def valid_signal(**over):
    base = dict(
        schema_version="1",
        strategy_id="demo",
        strategy_version="1.0.0",
        reviewed_build_hash="a" * 32,
        snapshot_id="snap-1",
        target_exposure=Decimal("0.5"),
        expires_at_utc=NOW + dt.timedelta(minutes=1),
        rationale_hash="b" * 32,
    )
    base.update(over)
    return base


class TestMarketBar:
    def test_valid(self):
        bar = MarketBar.model_validate(valid_bar())
        assert bar.ts_available_utc.tzinfo is not None

    def test_float_price_rejected(self):
        with pytest.raises(ValidationError):
            MarketBar.model_validate(valid_bar(open=100.5))  # type: ignore[arg-type]

    def test_nan_decimal_rejected(self):
        with pytest.raises(ValidationError):
            MarketBar.model_validate(valid_bar(close=Decimal("NaN")))

    def test_infinite_decimal_rejected(self):
        with pytest.raises(ValidationError):
            MarketBar.model_validate(valid_bar(high=Decimal("Infinity")))

    def test_negative_price_rejected(self):
        with pytest.raises(ValidationError):
            MarketBar.model_validate(valid_bar(open=Decimal("-1")))

    def test_naive_timestamp_rejected(self):
        with pytest.raises(ValidationError):
            MarketBar.model_validate(valid_bar(ts_event_utc=dt.datetime(2026, 1, 1)))

    def test_available_before_event_rejected(self):
        with pytest.raises(ValidationError):
            MarketBar.model_validate(
                valid_bar(
                    ts_event_utc=NOW + dt.timedelta(hours=1),
                    ts_available_utc=NOW,
                )
            )

    def test_unknown_field_rejected(self):
        bad = valid_bar()
        bad["leak"] = "insider info"
        with pytest.raises(ValidationError):
            MarketBar.model_validate(bad)

    def test_frozen(self):
        bar = MarketBar.model_validate(valid_bar())
        with pytest.raises(Exception):
            bar.close = Decimal("1")  # type: ignore[misc]

    def test_utc_normalized(self):
        est = dt.timezone(dt.timedelta(hours=-5))
        bar = MarketBar.model_validate(valid_bar(ts_event_utc=NOW.astimezone(est)))
        assert bar.ts_event_utc.utcoffset() == dt.timedelta(0)


class TestStrategySignal:
    def test_valid(self):
        StrategySignal.model_validate(valid_signal())

    def test_exposure_above_one_rejected(self):
        with pytest.raises(ValidationError):
            StrategySignal.model_validate(valid_signal(target_exposure=Decimal("1.5")))

    def test_negative_exposure_rejected(self):
        with pytest.raises(ValidationError):
            StrategySignal.model_validate(valid_signal(target_exposure=Decimal("-0.1")))

    def test_hash_field_rejects_free_text(self):
        with pytest.raises(ValidationError):
            StrategySignal.model_validate(valid_signal(rationale_hash="DROP TABLE users"))

    def test_short_hash_rejected(self):
        with pytest.raises(ValidationError):
            StrategySignal.model_validate(valid_signal(reviewed_build_hash="abc"))


class TestTargetPortfolio:
    @staticmethod
    def _tp(**over):
        base = dict(
            account_id="A1",
            allocation=(
                {"symbol": "SPY", "weight": Decimal("0.60")},
                {"symbol": "QQQ", "weight": Decimal("0.30")},
            ),
            cash_weight=Decimal("0.10"),
            risk_budget_id="rb1",
            timestamp=NOW,
        )
        base.update(over)
        return base

    def test_valid_exact_sum(self):
        tp = TargetPortfolio.model_validate(self._tp())
        assert len(tp.allocation) == 2

    def test_sum_not_one_rejected(self):
        with pytest.raises(ValidationError):
            TargetPortfolio.model_validate(
                self._tp(allocation=({"symbol": "SPY", "weight": Decimal("0.60")},))
            )

    def test_negative_weight_leverage_rejected(self):
        with pytest.raises(ValidationError):
            TargetPortfolio.model_validate(
                self._tp(
                    allocation=({"symbol": "SPY", "weight": Decimal("-1.0")},),
                    cash_weight=Decimal("1.1"),
                )
            )

    def test_nan_weight_rejected(self):
        with pytest.raises(ValidationError):
            TargetPortfolio.model_validate(
                self._tp(
                    allocation=({"symbol": "SPY", "weight": Decimal("NaN")},),
                    cash_weight=Decimal("1.0"),
                )
            )

    def test_off_pool_symbol_is_data_valid(self):
        # Pool membership is the Schema Gate's job (needs whitelist context);
        # the contract only enforces numeric/structural rules.
        tp = TargetPortfolio.model_validate(
            self._tp(
                allocation=({"symbol": "DOGE", "weight": Decimal("1.0")},),
                cash_weight=Decimal("0"),
            )
        )
        assert tp.allocation[0].symbol == "DOGE"


class TestTradeIntent:
    def test_namespaced_coid_accepted(self):
        TradeIntent.model_validate(
            dict(
                intent_id="i1",
                release_id="rel-1",
                account_id="A1",
                environment=Environment.LIVE,
                desired_change=Decimal("10"),
                source_hash="a" * 32,
                expires_at_utc=NOW,
                deterministic_client_order_id="LIVE:A1:000001",
            )
        )

    def test_non_namespaced_coid_rejected(self):
        with pytest.raises(ValidationError):
            TradeIntent.model_validate(
                dict(
                    intent_id="i1",
                    release_id="rel-1",
                    account_id="A1",
                    environment=Environment.LIVE,
                    desired_change=Decimal("10"),
                    source_hash="a" * 32,
                    expires_at_utc=NOW,
                    deterministic_client_order_id="000001",
                )
            )

    def test_wrong_namespace_rejected(self):
        with pytest.raises(ValidationError):
            TradeIntent.model_validate(
                dict(
                    intent_id="i1",
                    release_id="rel-1",
                    account_id="A1",
                    environment=Environment.PAPER,
                    desired_change=Decimal("10"),
                    source_hash="a" * 32,
                    expires_at_utc=NOW,
                    deterministic_client_order_id="LIVE:A1:000001",
                )
            )


class TestLiveRelease:
    def valid_release(self, **over):
        base = dict(
            release_id="rel-1",
            environment=Environment.LIVE,
            account_id="A1",
            strategy_hashes=("c" * 32,),
            build_digest="d" * 32,
            protocol_hash="e" * 32,
            policy_hash="f" * 32,
            capital_cap=Decimal("1000"),
            max_order_cap=Decimal("100"),
            valid_from=NOW,
            expires_at=NOW + dt.timedelta(hours=1),
            approval_identity="OWNER",
            nonce="1" * 32,
            revocation_epoch=0,
            signature="x" * 88,
            signature_algorithm="Ed25519",
        )
        base.update(over)
        return base

    def test_valid(self):
        LiveRelease.model_validate(self.valid_release())

    def test_zero_cap_rejected(self):
        with pytest.raises(ValidationError):
            LiveRelease.model_validate(self.valid_release(capital_cap="0"))

    def test_window_inverted_rejected(self):
        with pytest.raises(ValidationError):
            LiveRelease.model_validate(
                self.valid_release(
                    valid_from=(NOW + dt.timedelta(hours=2)).isoformat(),
                    expires_at=(NOW + dt.timedelta(hours=1)).isoformat(),
                )
            )

    def test_missing_signature_rejected(self):
        base = self.valid_release()
        del base["signature"]
        with pytest.raises(ValidationError):
            LiveRelease.model_validate(base)


class TestWireFormatDecimals:
    """Financial values on the wire are strings; JSON floats must not become
    Decimals (float -> Decimal coercion is the money-safety hole)."""

    def test_json_float_price_rejected(self):
        raw = '{"asset_id":"SPY","ts_event_utc":"2026-11-20T12:00:00Z","ts_available_utc":"2026-11-20T12:00:00Z","interval":"1d","open":100.5,"high":"110","low":"95","close":"105","volume":"0","source":"v","adjustment":"RAW","quality":"ok"}'
        with pytest.raises(ValidationError):
            MarketBar.model_validate_json(raw)

    def test_json_string_price_accepted(self):
        raw = '{"asset_id":"SPY","ts_event_utc":"2026-11-20T12:00:00Z","ts_available_utc":"2026-11-20T12:00:00Z","interval":"1d","open":"100.5","high":"110","low":"95","close":"105","volume":"0","source":"v","adjustment":"RAW","quality":"ok"}'
        bar = MarketBar.model_validate_json(raw)
        assert bar.open == Decimal("100.5")
