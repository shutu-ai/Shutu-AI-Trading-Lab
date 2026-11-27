"""Shared in-memory pipeline types for the Business MVP vertical slice.

These are INTERNAL research-plane objects (frozen dataclasses), NOT §2.2
contracts. Contract-typed objects (``MarketBar``, ``RegimeAssessment``,
``StrategySignal``, ``TargetPortfolio``, ``TradeIntent``, ...) remain the
only surfaces that cross security boundaries (SchemaGate / RiskEngine /
OMS / brokers). Everything defined here stays inside the replay process.

Determinism rules for every derived numeric field:

- ``decimal.Decimal`` only (never ``float``), quantized to a fixed number
  of decimal places so ``feature_hash`` / ``decision_hash`` digests are
  stable across runs and platforms.
- Missing / not-yet-decidable values are ``None`` plus a reason code —
  never zero, never a future value, never a cross-symbol patch.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Mapping, Sequence

__all__ = [
    "FeatureVector",
    "StrategyProposal",
    "DecisionOutput",
    "SessionRecord",
    "ExecutionOutcome",
    "NO_TRADE",
    "STATUS_OK",
    "STATUS_UNKNOWN",
]

STATUS_OK = "OK"
STATUS_UNKNOWN = "UNKNOWN"
NO_TRADE = "NO_TRADE"

_Q = Decimal("0.00000001")


def _q(value: Decimal | None) -> Decimal | None:
    return None if value is None else value.quantize(_Q)


@dataclass(frozen=True)
class FeatureVector:
    """PIT features for ONE symbol at one decision clock.

    ``None`` + reason codes is the honest representation of "cannot
    decide"; consumers (regime/strategies/router) must treat any
    ``status == UNKNOWN`` vector as unusable for that symbol.
    """

    symbol: str
    asof_utc: dt.datetime
    asof_bar_ts: dt.datetime | None      # ts_event_utc of last usable bar
    asof_bar_age_sessions: int | None    # sessions since that bar (staleness)
    returns_1d: Decimal | None
    ma_short: Decimal | None
    ma_long: Decimal | None
    rsi: Decimal | None                  # 0..100
    atr: Decimal | None
    realized_vol: Decimal | None         # per-session sigma of log-approx returns
    volume_ratio: Decimal | None         # last volume / mean(volume window)
    corr_other: Decimal | None           # vs the other symbol, common sample only
    warmup_ok: bool
    status: str                          # STATUS_OK / STATUS_UNKNOWN
    reasons: tuple[str, ...] = ()
    feature_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "returns_1d", _q(self.returns_1d))
        object.__setattr__(self, "ma_short", _q(self.ma_short))
        object.__setattr__(self, "ma_long", _q(self.ma_long))
        object.__setattr__(self, "rsi", _q(self.rsi))
        object.__setattr__(self, "atr", _q(self.atr))
        object.__setattr__(self, "realized_vol", _q(self.realized_vol))
        object.__setattr__(self, "volume_ratio", _q(self.volume_ratio))
        object.__setattr__(self, "corr_other", _q(self.corr_other))


@dataclass(frozen=True)
class StrategyProposal:
    """A candidate strategy's intended exposure BEFORE the trust boundary.

    ``target_exposure`` maps symbol -> Decimal in [0, 1] (long-only);
    residual weight is cash. Crossing into a ``StrategySignal`` contract
    happens only via the gate boundary in ``decision.py``.
    """

    strategy_id: str
    strategy_version: str
    asof_utc: dt.datetime
    target_exposure: Mapping[str, Decimal]
    rationale: str
    regime_labels_used: tuple[str, ...] = ()
    info_refs_used: tuple[str, ...] = ()     # InformationAssessment ids
    reject_reasons: tuple[str, ...] = ()     # non-empty => unusable this session


@dataclass(frozen=True)
class DecisionOutput:
    """What the orchestrator chose at one clock, with full explanation."""

    asof_utc: dt.datetime
    chosen_strategy_id: str | None          # None => NO_TRADE
    target: object | None                   # TargetPortfolio contract, or None
    no_trade_reasons: tuple[str, ...]
    candidate_scores: Mapping[str, Decimal]
    rationale: str
    decision_hash: str


@dataclass(frozen=True)
class ExecutionOutcome:
    """Mock-execution demo result for one decision (FAKE_BROKER path).

    Order units (V0.2 activation T1): ``desired_change``/risk notional/
    OMS seal/broker order/fill accumulation all travel in USD; whole
    ``order_shares`` are determined BEFORE submission from the PIT
    decision price, and the ledger records filled shares at the
    execution-clock price. ``outcome_state`` is the BROKER's real
    terminal state (FILLED / PARTIALLY_FILLED), never assumed.
    """

    decision_asof_utc: dt.datetime
    intent_id: str
    client_order_id: str
    outcome_state: str                      # SubmitOutcome.state / broker terminal
    delivered: bool
    acknowledged: bool | None
    risk_verdict: str                       # APPROVE / REJECT / HALT
    risk_reasons: tuple[str, ...] = ()
    order_notional_usd: Decimal | None = None   # intent USD (sealed quantity)
    order_shares: Decimal | None = None         # whole shares pre-computed
    fill_qty: Decimal | None = None             # SHARES actually filled
    fill_price: Decimal | None = None           # execution-clock price
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class SessionRecord:
    """Per-session pipeline trace (serialized to JSONL in the report)."""

    asof_utc: dt.datetime
    session_date: str
    features: Mapping[str, FeatureVector]
    regime_labels: tuple[str, ...]
    regime_confidence: Decimal | None
    regime_feature_hash: str
    info_assessments: Sequence[Mapping[str, object]]
    proposals: Mapping[str, StrategyProposal]
    decision: DecisionOutput
    scenario_tag: str = ""                  # fixture segment tag, reporting only
