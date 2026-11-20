"""Core event contracts (Pydantic v2), per architecture plan §2.2.

Safety invariants enforced at the type level:

- Money, quantities, prices, weights and factors are ``Decimal`` (never
  ``float``); all such fields reject NaN/Infinity.
- Timestamps must be timezone-aware and are normalized to UTC; naive
  datetimes are rejected.
- Unknown fields are rejected (``extra="forbid"``) so an unreviewed
  producer cannot smuggle extra data through the Schema Gate.
- Models are frozen: a validated contract object is immutable evidence.
- TradeIntent's ``deterministic_client_order_id`` must carry the
  environment/account namespace (architecture §6.3).
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Annotated, Any

from pydantic import (
    AfterValidator,
    BeforeValidator,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from .enums import (
    AdjustmentKind,
    DeploymentState,
    Environment,
    EvidenceState,
    FinalHoldoutStatus,
    OrderState,
    StrategyRole,
)

# --------------------------------------------------------------------------
# Building blocks
# --------------------------------------------------------------------------


def _ensure_utc(value: Any) -> Any:
    """Reject naive datetimes; normalize aware ones to UTC."""
    if not isinstance(value, dt.datetime):
        return value  # let pydantic produce its own type error
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError("timestamp must be timezone-aware (naive datetimes rejected)")
    return value.astimezone(dt.timezone.utc)


def _to_decimal(value: Any) -> Any:
    """Financial values: never binary floats (precision loss is the
    money-safety hole); strings and integers are exact decimal forms and
    are converted here so both JSON-mode and Python-mode validation accept
    the same wire format (financial values travel as JSON strings)."""
    if isinstance(value, bool) or isinstance(value, float):
        raise ValueError(
            "bool/float is not accepted for financial values; use a string or Decimal"
        )
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, str)):
        return Decimal(value)
    return value  # wrong type entirely: let pydantic raise its own error


def _check_finite(value: Decimal) -> Decimal:
    if not value.is_finite():
        raise ValueError("decimal value must be finite (NaN/Infinity rejected)")
    return value


def _check_non_negative(value: Decimal) -> Decimal:
    if value < 0:
        raise ValueError("value must be >= 0")
    return value


def _check_positive(value: Decimal) -> Decimal:
    if value <= 0:
        raise ValueError("value must be > 0")
    return value


def _check_unit_interval(value: Decimal) -> Decimal:
    if not (Decimal(0) <= value <= Decimal(1)):
        raise ValueError("value must be within [0, 1]")
    return value


UtcDatetime = Annotated[dt.datetime, AfterValidator(_ensure_utc)]
"""Parsed as an ISO-8601 string in JSON mode or a ``datetime`` in Python
mode, then validated timezone-aware and normalized to UTC; naive datetimes
are rejected in both modes."""

FiniteDecimal = Annotated[Decimal, BeforeValidator(_to_decimal), AfterValidator(_check_finite)]
NonNegativeDecimal = Annotated[
    Decimal, BeforeValidator(_to_decimal), AfterValidator(_check_finite), AfterValidator(_check_non_negative)
]
PositiveDecimal = Annotated[
    Decimal, BeforeValidator(_to_decimal), AfterValidator(_check_finite), AfterValidator(_check_positive)
]
UnitIntervalDecimal = Annotated[
    Decimal,
    BeforeValidator(_to_decimal),
    AfterValidator(_check_finite),
    AfterValidator(_check_unit_interval),
]

HexHash = Annotated[str, Field(min_length=16, max_length=64, pattern=r"^[0-9a-fA-F]{16,64}$")]
NonEmptyStr = Annotated[str, Field(min_length=1)]


class _Contract(BaseModel):
    """Base for all §2.2 contracts: immutable, closed-world, strict.

    Strict mode means Python-side construction must pass exact types
    (Decimal fields reject float/int; datetime fields reject strings) —
    the money-safety boundary. JSON mode still parses ISO-8601 strings for
    timestamps and strings for Decimals (JSON has no Decimal literal; the
    wire format for financial values is a string)."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, validate_default=True)


# --------------------------------------------------------------------------
# §2.2 contracts, in plan order
# --------------------------------------------------------------------------


class MarketBar(_Contract):
    asset_id: NonEmptyStr
    ts_event_utc: UtcDatetime
    ts_available_utc: UtcDatetime
    interval: NonEmptyStr
    open: PositiveDecimal
    high: PositiveDecimal
    low: PositiveDecimal
    close: PositiveDecimal
    volume: NonNegativeDecimal
    source: NonEmptyStr
    adjustment: AdjustmentKind
    quality: NonEmptyStr

    @model_validator(mode="after")
    def _sanity(self) -> "MarketBar":
        if self.ts_available_utc < self.ts_event_utc:
            raise ValueError("ts_available_utc must not precede ts_event_utc")
        if self.low > self.high:
            raise ValueError("low must not exceed high")
        return self


class CorporateAction(_Contract):
    asset_id: NonEmptyStr
    effective_at: UtcDatetime
    announced_at: UtcDatetime
    available_at: UtcDatetime
    kind: NonEmptyStr  # SPLIT / DIVIDEND / DELISTING / ... (taxonomy fixed in M1)
    factor: FiniteDecimal
    source: NonEmptyStr

    @model_validator(mode="after")
    def _sanity(self) -> "CorporateAction":
        if self.announced_at > self.effective_at:
            raise ValueError("effective_at must not precede announced_at")
        return self


class MarketSnapshot(_Contract):
    snapshot_id: NonEmptyStr
    asof_utc: UtcDatetime
    knowledge_cutoff_utc: UtcDatetime
    dataset_hash: HexHash
    data_quality: NonEmptyStr


class RegimeAssessment(_Contract):
    labels: tuple[NonEmptyStr, ...]
    confidence: Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)]
    asof_utc: UtcDatetime
    model_version: NonEmptyStr
    feature_hash: HexHash
    valid_until: UtcDatetime


class StrategyArtifact(_Contract):
    strategy_id: NonEmptyStr
    strategy_version: NonEmptyStr
    source_hash: HexHash
    dependency_lock_hash: HexHash
    family: NonEmptyStr
    reviewed_build_hash: HexHash
    sandbox_policy_hash: HexHash
    approved_regimes: tuple[NonEmptyStr, ...]
    evidence_id: NonEmptyStr


class StrategySignal(_Contract):
    """The *only* data object a strategy subprocess may emit to the Schema
    Gate (architecture §2.6)."""

    schema_version: NonEmptyStr
    strategy_id: NonEmptyStr
    strategy_version: NonEmptyStr
    reviewed_build_hash: HexHash
    snapshot_id: NonEmptyStr
    target_exposure: UnitIntervalDecimal
    expires_at_utc: UtcDatetime
    rationale_hash: HexHash


class AllocationItem(_Contract):
    symbol: NonEmptyStr
    weight: NonNegativeDecimal  # finiteness + non-negativity: no leverage via negatives


class TargetPortfolio(_Contract):
    account_id: NonEmptyStr
    allocation: tuple[AllocationItem, ...]
    cash_weight: UnitIntervalDecimal
    risk_budget_id: NonEmptyStr
    timestamp: UtcDatetime

    @model_validator(mode="after")
    def _weights_sum(self) -> "TargetPortfolio":
        total = self.cash_weight + sum((a.weight for a in self.allocation), Decimal(0))
        if total != Decimal(1):
            raise ValueError(
                f"allocation weights + cash_weight must sum to exactly 1 (got {total})"
            )
        return self


class TradeIntent(_Contract):
    intent_id: NonEmptyStr
    release_id: NonEmptyStr
    account_id: NonEmptyStr
    environment: Environment
    desired_change: FiniteDecimal  # signed: positive buy / negative sell
    source_hash: HexHash
    expires_at_utc: UtcDatetime
    deterministic_client_order_id: NonEmptyStr

    @field_validator("deterministic_client_order_id")
    @classmethod
    def _namespaced_coid(cls, v: str, info: Any) -> str:
        env = info.data.get("environment")
        account = info.data.get("account_id")
        if env is not None and account is not None:
            prefix = f"{str(env)}:{account}:"
            if not v.startswith(prefix):
                raise ValueError(
                    "deterministic_client_order_id must embed the environment/account "
                    f"namespace prefix '{prefix}...' (architecture §6.3)"
                )
        return v


class DurableOrderIntent(_Contract):
    intent_id: NonEmptyStr
    environment: Environment
    account_id: NonEmptyStr
    payload_hash: HexHash
    release_hash: HexHash
    risk_policy_hash: HexHash
    journal_seq: Annotated[int, Field(ge=0)]
    persist_committed_at: UtcDatetime


class ExecutorFence(_Contract):
    environment: Environment
    account_id: NonEmptyStr
    owner_instance_id: NonEmptyStr
    monotonic_epoch: Annotated[int, Field(ge=1)]
    lease_expires_at: UtcDatetime
    lock_version: Annotated[int, Field(ge=0)]


class RiskDecision(_Contract):
    intent_id: NonEmptyStr
    policy_hash: HexHash
    allow: bool
    reason_codes: tuple[NonEmptyStr, ...]
    limits_snapshot: dict[str, str]
    decision_at: UtcDatetime


class OrderEvent(_Contract):
    client_order_id: NonEmptyStr
    broker_order_id: NonEmptyStr
    account_id: NonEmptyStr
    order_state: OrderState
    filled_qty: NonNegativeDecimal
    avg_price: NonNegativeDecimal
    received_at: UtcDatetime


class ExperimentRecord(_Contract):
    experiment_id: NonEmptyStr
    protocol_hash: HexHash
    all_trials: tuple[dict[str, Any], ...]
    total_search_budget: Annotated[int, Field(ge=0)]
    trials_including_failures: Annotated[int, Field(ge=0)]
    cost_model_version: NonEmptyStr
    dataset_hash: HexHash
    sealed_holdout_access_log: tuple[NonEmptyStr, ...]
    results: dict[str, Any]


class EvidenceRecord(_Contract):
    strategy_hash: HexHash
    historical_oos_result: NonEmptyStr
    final_holdout_result: NonEmptyStr
    forward_cohort_id: NonEmptyStr
    evidence_state: EvidenceState
    measured_at: UtcDatetime
    protocol_hash: HexHash
    contamination_flag: bool


class FinalHoldoutResult(_Contract):
    holdout_id: NonEmptyStr
    strategy_hash: HexHash
    protocol_hash: HexHash
    status: FinalHoldoutStatus
    tested_at: UtcDatetime
    contamination_event: str = ""
    overlap_disclosure_hash: HexHash


class StrategyPlacement(_Contract):
    strategy_hash: HexHash
    evidence_state: EvidenceState
    deployment_state: DeploymentState
    strategy_role: StrategyRole
    authorization_id: NonEmptyStr
    observed_at: UtcDatetime


class HoldoutAccess(_Contract):
    holdout_id: NonEmptyStr
    unlock_event_id: NonEmptyStr
    access_time: UtcDatetime
    unlock_reason: NonEmptyStr
    polluted_for_future_selection: bool
    analyst_id: NonEmptyStr


class DataVendorAssessment(_Contract):
    provider_id: NonEmptyStr
    licensed_uses: tuple[NonEmptyStr, ...]
    universe_history_coverage: NonEmptyStr
    delisting_coverage: NonEmptyStr
    corporate_actions_coverage: NonEmptyStr
    point_in_time_quality: NonEmptyStr
    monthly_cost: NonNegativeDecimal
    rejection_reasons: tuple[NonEmptyStr, ...]


class LiveRelease(_Contract):
    """Human-signed approval artifact authorizing a Live release package.

    M0 verifies this object with **mock test keys and fictional accounts
    only** (architecture §6.5). ``signature`` covers the canonical JSON of
    every other field; ``signature_algorithm`` must be ``Ed25519``.
    """

    release_id: NonEmptyStr
    environment: Environment
    account_id: NonEmptyStr
    strategy_hashes: tuple[HexHash, ...]
    build_digest: HexHash
    protocol_hash: HexHash
    policy_hash: HexHash
    capital_cap: PositiveDecimal
    max_order_cap: PositiveDecimal
    valid_from: UtcDatetime
    expires_at: UtcDatetime
    approval_identity: NonEmptyStr
    nonce: HexHash
    revocation_epoch: Annotated[int, Field(ge=0)]
    signature: NonEmptyStr
    signature_algorithm: NonEmptyStr

    @model_validator(mode="after")
    def _window(self) -> "LiveRelease":
        if self.expires_at <= self.valid_from:
            raise ValueError("expires_at must be after valid_from")
        return self


class CapitalFlow(_Contract):
    flow_id: NonEmptyStr
    deposit_or_withdrawal: bool
    settled_amount: NonNegativeDecimal
    external_approval_id: NonEmptyStr
    timestamp: UtcDatetime


__all__ = [
    "AllocationItem",
    "CapitalFlow",
    "CorporateAction",
    "DataVendorAssessment",
    "EvidenceRecord",
    "ExperimentRecord",
    "ExecutorFence",
    "FinalHoldoutResult",
    "FiniteDecimal",
    "HexHash",
    "HoldoutAccess",
    "LiveRelease",
    "MarketBar",
    "MarketSnapshot",
    "OrderEvent",
    "RegimeAssessment",
    "RiskDecision",
    "StrategyArtifact",
    "StrategyPlacement",
    "StrategySignal",
    "TargetPortfolio",
    "TradeIntent",
    "DurableOrderIntent",
]
