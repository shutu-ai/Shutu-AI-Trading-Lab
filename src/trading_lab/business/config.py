"""Business MVP configuration: typed, closed-world, fail-closed.

Loaded from a pinned YAML file (``configs/business_mvp_demo.yaml`` for
V0.1). Unknown keys are refused; every threshold is a FIXED prior declared
before execution (AGENTS.md #8) — none of them is fitted on replay data.
Wall-clock time never enters this config; the replay clock comes from the
fixture timeline only.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel, ConfigDict, field_validator

__all__ = ["BusinessConfig", "load_config"]


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FeaturesConfig(_Closed):
    ma_short: int = 10
    ma_long: int = 30
    rsi_period: int = 14
    atr_period: int = 14
    realized_vol_window: int = 20
    volume_window: int = 20
    corr_window: int = 60
    corr_min_common: int = 40
    stale_after_sessions: int = 5

    @field_validator("ma_short", "ma_long", "rsi_period", "atr_period")
    @classmethod
    def _positive(cls, v: int) -> int:
        if v < 2:
            raise ValueError("feature windows must be >= 2")
        return v


class RegimeConfig(_Closed):
    trend_band_pct: Decimal = Decimal("0.001")     # |ma_s/ma_l - 1| band for RANGE
    high_vol_lookback: int = 120
    high_vol_percentile: Decimal = Decimal("0.80")  # fixed prior, not fitted
    min_history_for_vol_percentile: int = 60
    hysteresis_sessions: int = 3
    confidence_floor: Decimal = Decimal("0.55")
    confidence_base: Decimal = Decimal("0.60")
    confidence_strength_gain: Decimal = Decimal("0.20")
    event_validity_fallback_sessions: int = 5


class RouterConfig(_Closed):
    weight_regime_fit: Decimal = Decimal("0.40")
    weight_data_quality: Decimal = Decimal("0.20")
    weight_virtual_performance: Decimal = Decimal("0.25")
    weight_risk_cost: Decimal = Decimal("0.15")
    min_score_to_trade: Decimal = Decimal("0.50")
    info_veto_confidence: Decimal = Decimal("0.80")
    max_turnover_per_session: Decimal = Decimal("0.60")  # gross weight change


class BacktestCostConfig(_Closed):
    commission_per_trade: Decimal = Decimal("1.00")
    spread_pct: Decimal = Decimal("0.0005")
    slippage_pct: Decimal = Decimal("0.0005")
    order_delay_bars: int = 1
    allow_same_day_close: bool = False     # ADR-004: never true
    volume_limit_pct: Decimal = Decimal("0.05")
    partial_fill_threshold_pct: Decimal = Decimal("0.50")
    settlement_days: int = 1
    initial_cash: Decimal = Decimal("100000.00")

    @field_validator("allow_same_day_close")
    @classmethod
    def _adr004(cls, v: bool) -> bool:
        if v:
            raise ValueError("allow_same_day_close must stay false (ADR-004)")
        return v


class MockExecutionConfig(_Closed):
    account_id: str = "MOCK-ACCT-001"
    environment: str = "PAPER"             # enum reuse; backend stays FAKE_BROKER
    max_order_notional: Decimal = Decimal("50000.00")
    max_position_notional: Decimal = Decimal("200000.00")
    max_gross_notional: Decimal = Decimal("250000.00")
    fill_price_source: str = "next_open"   # fixture next-open, MOCK_ONLY valuation


class FixtureConfig(_Closed):
    name: str = "demo"
    seed: int = 20261127
    symbols: tuple[str, ...] = ("SPY", "QQQ")
    start_price_spy: Decimal = Decimal("450.00")
    start_price_qqq: Decimal = Decimal("350.00")
    sessions_per_segment: tuple[int, ...] = (40, 80, 60, 60, 60, 60, 30, 30)


class BusinessConfig(_Closed):
    mode: str = "replay"                   # only "replay" is authorized in V0.1
    fixture: FixtureConfig = FixtureConfig()
    features: FeaturesConfig = FeaturesConfig()
    regime: RegimeConfig = RegimeConfig()
    router: RouterConfig = RouterConfig()
    backtest: BacktestCostConfig = BacktestCostConfig()
    mock_execution: MockExecutionConfig = MockExecutionConfig()

    @field_validator("mode")
    @classmethod
    def _mode_offline_only(cls, v: str) -> str:
        if v != "replay":
            raise ValueError(
                f"mode {v!r} is not authorized in V0.1 (only 'replay'; "
                "other modes must fail closed)")
        return v


def load_config(path: Path) -> BusinessConfig:
    """Load + validate a pinned YAML config. Fail closed on any unknown key
    or unauthorized mode."""
    import yaml

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"config {path} must be a mapping")
    payload = raw.get("business_mvp", raw)
    return BusinessConfig.model_validate(payload)
