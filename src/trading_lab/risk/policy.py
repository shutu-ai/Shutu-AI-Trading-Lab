"""Risk policy model — the §6.2 mandatory fields, all required, non-null,
Decimal for money. A policy missing any field fails validation (fail-closed
config): Live must never boot without a complete, hash-pinned policy.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..contracts import Environment


class RiskPolicy(BaseModel):
    """Frozen risk contract per (environment, account). Mirrors architecture
    §6.2: every mandatory key present, finite and positive."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    version: int
    environment: Environment
    account_id: str
    policy_hash: str                                    # pinned by the loader

    max_gross_exposure_pct: Decimal
    max_net_exposure_pct: Decimal
    max_single_symbol_pct: Decimal
    max_single_order_notional_usd: Decimal
    max_daily_loss_pct: Decimal
    max_peak_to_trough_drawdown_pct: Decimal
    max_abnormal_orders_per_minute: int = Field(ge=1)
    max_market_bar_age_seconds: int = Field(ge=1)
    max_account_snapshot_age_seconds: int = Field(ge=1)
    max_broker_order_ack_wait_seconds: int = Field(ge=1)
    require_settled_funds: bool
    allow_margin: bool
    allow_short: bool
    allowed_symbols: tuple[str, ...] = Field(min_length=1)
    recovery_requires: tuple[str, ...] = Field(min_length=1)

    @field_validator("account_id", "policy_hash")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must be non-empty")
        return v

    @field_validator(
        "max_gross_exposure_pct",
        "max_net_exposure_pct",
        "max_single_symbol_pct",
        "max_single_order_notional_usd",
        "max_daily_loss_pct",
        "max_peak_to_trough_drawdown_pct",
    )
    @classmethod
    def _finite_positive(cls, v: Decimal) -> Decimal:
        if not v.is_finite() or v <= 0:
            raise ValueError("risk thresholds must be finite and > 0")
        return v

    @field_validator("allowed_symbols")
    @classmethod
    def _symbols(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(s.strip().upper() for s in v)
        if any(not s for s in cleaned):
            raise ValueError("allowed_symbols must be non-empty strings")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("allowed_symbols contains duplicates")
        return cleaned


_DECIMAL_FIELDS = (
    "max_gross_exposure_pct",
    "max_net_exposure_pct",
    "max_single_symbol_pct",
    "max_single_order_notional_usd",
    "max_daily_loss_pct",
    "max_peak_to_trough_drawdown_pct",
)


def load_risk_policy(path: str | Path, policy_hash: str) -> RiskPolicy:
    """Load + validate the policy YAML. ``policy_hash`` is pinned by the
    caller and stored verbatim. YAML scalars are normalized to exact types
    BEFORE strict validation: environment string -> enum, numbers -> Decimal
    via their string form (never float)."""
    import yaml

    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    raw["environment"] = Environment(raw["environment"])
    for field in _DECIMAL_FIELDS:
        raw[field] = Decimal(str(raw[field]))
    raw["policy_hash"] = policy_hash
    return RiskPolicy.model_validate(raw)


__all__ = ["RiskPolicy", "load_risk_policy"]
