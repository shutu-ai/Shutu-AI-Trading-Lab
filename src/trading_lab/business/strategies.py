"""Fixed, reviewed candidate strategy set (Business MVP V0.1, MOCK_ONLY).

Long-only, SPY/QQQ/CASH universe. Every candidate below is a transparent
fixed rule reviewed in this file — no fitting, no AI-generated
strategies, no HMM/RL, and no claim of any kind about real markets.

Candidates emit internal :class:`StrategyProposal` objects ONLY: no order
construction, no broker calls, and no ``StrategySignal`` contract
construction (crossing into the trust boundary happens exclusively in
``decision.py``). Information-plane input flows into strategies only
indirectly, through the regime labels and the router's veto — therefore
``info_refs_used`` stays empty here by design.

Candidates are stateless and deterministic: ``propose`` receives the
caller-maintained ``virtual_state`` (the candidate's OWN virtual
position, symbol -> exposure Decimal, carried by the router/replay) and
returns the NEW intended exposure map. Residual weight not named in the
map is cash.

Natural-regime declaration (used by the router's regime-fit score):

====================  =========  ===========================================
strategy_id           reference  natural_regimes
====================  =========  ===========================================
cash_baseline         True       TREND_UP, TREND_DOWN, RANGE, HIGH_VOL
buy_hold              True       TREND_UP
ma_cross_trend        False      TREND_UP, TREND_DOWN, RANGE
mean_reversion        False      RANGE
high_vol_defensive    False      HIGH_VOL
====================  =========  ===========================================

``cash_baseline`` fits every regime because staying in cash is always a
viable arm; ``ma_cross_trend`` operates (long or deliberately flat) on
every trend state; ``mean_reversion`` is only sensible in ``RANGE``;
``high_vol_defensive`` exists for ``HIGH_VOL`` sessions; ``buy_hold`` is
a pure long-equity reference.
"""

from __future__ import annotations

import datetime as dt
from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from typing import ClassVar, Mapping, Sequence

from trading_lab.business.regime import (
    LABEL_HIGH_VOL,
    LABEL_RANGE,
    LABEL_TREND_DOWN,
    LABEL_TREND_UP,
    LABEL_UNKNOWN,
    PRIMARY_SYMBOL,
    InformationAssessmentView,
)
from trading_lab.business.types import STATUS_OK, FeatureVector, StrategyProposal
from trading_lab.contracts.events import RegimeAssessment

__all__ = [
    "CandidateStrategy",
    "CashBaselineStrategy",
    "BuyHoldStrategy",
    "MaCrossTrendStrategy",
    "MeanReversionStrategy",
    "HighVolDefensiveStrategy",
    "default_candidates",
]

STRATEGY_VERSION = "V1"

# Fixed mean-reversion thresholds (declared priors, not fitted).
RSI_ENTRY_BELOW = Decimal(30)   # RSI strictly below -> enter 0.5 SPY
RSI_EXIT_ABOVE = Decimal(55)    # RSI at/above -> exit to flat
MEAN_REVERSION_ENTRY_EXPOSURE = Decimal("0.5")
FULL_EXPOSURE = Decimal(1)
FLAT_EXPOSURE = Decimal(0)


class CandidateStrategy(ABC):
    """Common interface for the fixed candidate set.

    Concrete candidates are frozen dataclasses; all behavior is a pure
    function of the arguments (no internal mutable state).
    """

    strategy_id: ClassVar[str]
    reference: ClassVar[bool] = False
    natural_regimes: ClassVar[tuple[str, ...]] = ()

    @abstractmethod
    def propose(
        self,
        asof_utc: dt.datetime,
        features: Mapping[str, FeatureVector],
        regime: RegimeAssessment,
        info_assessments: Sequence[InformationAssessmentView],
        virtual_state: Mapping[str, Decimal],
    ) -> StrategyProposal:
        """Return the NEW intended exposure map for this session."""

    def _build(
        self,
        asof_utc: dt.datetime,
        target_exposure: Mapping[str, Decimal],
        rationale: str,
        regime: RegimeAssessment,
        reject_reasons: tuple[str, ...] = (),
    ) -> StrategyProposal:
        exposure = dict(target_exposure)
        for symbol, weight in exposure.items():
            if not (Decimal(0) <= weight <= Decimal(1)):
                raise ValueError(
                    f"{self.strategy_id}: exposure for {symbol} must be within [0, 1], "
                    f"got {weight}"
                )
        return StrategyProposal(
            strategy_id=self.strategy_id,
            strategy_version=STRATEGY_VERSION,
            asof_utc=asof_utc,
            target_exposure=exposure,
            rationale=rationale,
            regime_labels_used=tuple(regime.labels),
            info_refs_used=(),
            reject_reasons=reject_reasons,
        )

    @staticmethod
    def _primary_unusable(features: Mapping[str, FeatureVector]) -> bool:
        fv = features.get(PRIMARY_SYMBOL)
        return fv is None or fv.status != STATUS_OK

    @staticmethod
    def _held_exposure(virtual_state: Mapping[str, Decimal]) -> dict[str, Decimal]:
        """Fresh copy of the caller-maintained virtual position (never
        mutated, never shared)."""
        return dict(virtual_state)


@dataclass(frozen=True)
class CashBaselineStrategy(CandidateStrategy):
    """Reference arm B0: always all cash, never rejects."""

    strategy_id: ClassVar[str] = "cash_baseline"
    reference: ClassVar[bool] = True
    natural_regimes: ClassVar[tuple[str, ...]] = (
        LABEL_TREND_UP,
        LABEL_TREND_DOWN,
        LABEL_RANGE,
        LABEL_HIGH_VOL,
    )

    def propose(
        self,
        asof_utc: dt.datetime,
        features: Mapping[str, FeatureVector],
        regime: RegimeAssessment,
        info_assessments: Sequence[InformationAssessmentView],
        virtual_state: Mapping[str, Decimal],
    ) -> StrategyProposal:
        return self._build(asof_utc, {}, "reference cash arm", regime)


@dataclass(frozen=True)
class BuyHoldStrategy(CandidateStrategy):
    """Reference arm B1: once the primary symbol is warm, hold SPY at
    full exposure forever; before that, reject (cannot size honestly)."""

    strategy_id: ClassVar[str] = "buy_hold"
    reference: ClassVar[bool] = True
    natural_regimes: ClassVar[tuple[str, ...]] = (LABEL_TREND_UP,)

    def propose(
        self,
        asof_utc: dt.datetime,
        features: Mapping[str, FeatureVector],
        regime: RegimeAssessment,
        info_assessments: Sequence[InformationAssessmentView],
        virtual_state: Mapping[str, Decimal],
    ) -> StrategyProposal:
        fv = features.get(PRIMARY_SYMBOL)
        if fv is None or fv.status != STATUS_OK or not fv.warmup_ok:
            return self._build(
                asof_utc,
                {},
                "reference buy-and-hold arm: primary warmup incomplete",
                regime,
                reject_reasons=("WARMUP_INCOMPLETE",),
            )
        holding = virtual_state.get(PRIMARY_SYMBOL, FLAT_EXPOSURE) > FLAT_EXPOSURE
        rationale = (
            "reference buy-and-hold arm: holding SPY"
            if holding
            else "reference buy-and-hold arm: entering SPY"
        )
        return self._build(asof_utc, {PRIMARY_SYMBOL: FULL_EXPOSURE}, rationale, regime)


@dataclass(frozen=True)
class MaCrossTrendStrategy(CandidateStrategy):
    """Trend follower: long SPY in TREND_UP; deliberately flat (exit)
    in TREND_DOWN or RANGE; rejects when the primary features are
    unusable."""

    strategy_id: ClassVar[str] = "ma_cross_trend"
    natural_regimes: ClassVar[tuple[str, ...]] = (
        LABEL_TREND_UP,
        LABEL_TREND_DOWN,
        LABEL_RANGE,
    )

    def propose(
        self,
        asof_utc: dt.datetime,
        features: Mapping[str, FeatureVector],
        regime: RegimeAssessment,
        info_assessments: Sequence[InformationAssessmentView],
        virtual_state: Mapping[str, Decimal],
    ) -> StrategyProposal:
        if self._primary_unusable(features) or LABEL_UNKNOWN in regime.labels:
            return self._build(
                asof_utc,
                {},
                "trend rule unusable: primary features unknown",
                regime,
                reject_reasons=("FEATURES_UNKNOWN",),
            )
        if LABEL_TREND_UP in regime.labels:
            return self._build(
                asof_utc,
                {PRIMARY_SYMBOL: FULL_EXPOSURE},
                "ma_short above ma_long band: trend-follow long SPY",
                regime,
            )
        # TREND_DOWN, RANGE (and the unreachable no-trend-label fallthrough)
        # all resolve to a deliberate exit.
        return self._build(
            asof_utc,
            {PRIMARY_SYMBOL: FLAT_EXPOSURE},
            "no uptrend: trend rule exits SPY",
            regime,
        )


@dataclass(frozen=True)
class MeanReversionStrategy(CandidateStrategy):
    """Range trader: only sensible in RANGE. RSI below 30 enters SPY at
    0.5, RSI at/above 55 exits, mid-band keeps the current virtual
    exposure. Outside RANGE it exits to cash with a REGIME_MISMATCH
    reject unless already flat (then a plain hold with no reject)."""

    strategy_id: ClassVar[str] = "mean_reversion"
    natural_regimes: ClassVar[tuple[str, ...]] = (LABEL_RANGE,)

    def propose(
        self,
        asof_utc: dt.datetime,
        features: Mapping[str, FeatureVector],
        regime: RegimeAssessment,
        info_assessments: Sequence[InformationAssessmentView],
        virtual_state: Mapping[str, Decimal],
    ) -> StrategyProposal:
        fv = features.get(PRIMARY_SYMBOL)
        if fv is None or fv.status != STATUS_OK or fv.rsi is None:
            return self._build(
                asof_utc,
                {},
                "mean reversion unusable: RSI unknown",
                regime,
                reject_reasons=("FEATURES_UNKNOWN",),
            )
        current = virtual_state.get(PRIMARY_SYMBOL, FLAT_EXPOSURE)
        in_range = LABEL_RANGE in regime.labels and LABEL_UNKNOWN not in regime.labels
        if not in_range:
            if current > FLAT_EXPOSURE:
                return self._build(
                    asof_utc,
                    {PRIMARY_SYMBOL: FLAT_EXPOSURE},
                    "outside RANGE: mean reversion exits to cash",
                    regime,
                    reject_reasons=("REGIME_MISMATCH",),
                )
            return self._build(
                asof_utc,
                self._held_exposure(virtual_state),
                "outside RANGE and already flat: hold cash",
                regime,
            )
        if fv.rsi < RSI_ENTRY_BELOW:
            return self._build(
                asof_utc,
                {PRIMARY_SYMBOL: MEAN_REVERSION_ENTRY_EXPOSURE},
                "RANGE with RSI oversold: enter SPY at 0.5",
                regime,
            )
        if fv.rsi >= RSI_EXIT_ABOVE:
            return self._build(
                asof_utc,
                {PRIMARY_SYMBOL: FLAT_EXPOSURE},
                "RANGE with RSI through exit band: exit SPY",
                regime,
            )
        return self._build(
            asof_utc,
            self._held_exposure(virtual_state),
            "RANGE mid-band: hold current virtual exposure",
            regime,
        )


@dataclass(frozen=True)
class HighVolDefensiveStrategy(CandidateStrategy):
    """Defensive arm: all cash while HIGH_VOL is active; otherwise holds
    the current virtual exposure. Rejects when primary features are
    unusable."""

    strategy_id: ClassVar[str] = "high_vol_defensive"
    natural_regimes: ClassVar[tuple[str, ...]] = (LABEL_HIGH_VOL,)

    def propose(
        self,
        asof_utc: dt.datetime,
        features: Mapping[str, FeatureVector],
        regime: RegimeAssessment,
        info_assessments: Sequence[InformationAssessmentView],
        virtual_state: Mapping[str, Decimal],
    ) -> StrategyProposal:
        if self._primary_unusable(features):
            return self._build(
                asof_utc,
                {},
                "defensive arm unusable: primary features unknown",
                regime,
                reject_reasons=("FEATURES_UNKNOWN",),
            )
        if LABEL_HIGH_VOL in regime.labels:
            return self._build(
                asof_utc, {}, "defensive: HIGH_VOL active, all cash", regime
            )
        return self._build(
            asof_utc,
            self._held_exposure(virtual_state),
            "no HIGH_VOL: hold current virtual exposure",
            regime,
        )


def default_candidates() -> tuple[CandidateStrategy, ...]:
    """The fixed, reviewed candidate pool in deterministic order."""
    return (
        CashBaselineStrategy(),
        BuyHoldStrategy(),
        MaCrossTrendStrategy(),
        MeanReversionStrategy(),
        HighVolDefensiveStrategy(),
    )
