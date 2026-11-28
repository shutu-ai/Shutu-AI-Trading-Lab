"""Fixed, reviewed candidate strategy set (Business MVP V0.2, MOCK_ONLY).

Long-only SPY/QQQ/CASH universe. Every candidate below is a transparent
fixed rule reviewed in this file — no fitting, no AI-generated
strategies, no HMM/RL, and no claim of any kind about real markets.

V0.2 (B2): SPY and QQQ are BOTH first-class traded symbols. Every equity
candidate evaluates the two symbols independently — per-symbol features
and, where the rule reads a trend state, per-symbol MA crosses — and
emits ONE unified multi-symbol exposure map ``target_exposure: mapping
symbol -> Decimal in [0, 1]``. Weight conservation holds by construction
and is enforced in ``_build``: the map's weights sum to at most 1.0; the
residual weight is cash, and all-cash proposals are legal.

Regime labels are PORTFOLIO-LEVEL (computed from the routing primary
SPY). They are used as (a) the UNKNOWN fail-safe gate, (b) the
RANGE / HIGH_VOL gates documented per candidate below, and (c) the
router's regime-fit score. They are NOT per-symbol trend reads:
candidates that need a trend state compute it from that symbol's OWN
features (``_own_trend_label``).

Per-symbol semantics table (normative for this module):

==================  ==========================  ==============================
strategy            regime gate                 per-symbol leg rule
==================  ==========================  ==============================
cash_baseline       none                        none — always all cash
buy_hold (ref)      none                        warm symbols only: both
                                                warm -> 0.5/0.5 split;
                                                single warm -> that symbol
                                                at 1.0
ma_cross_trend      UNKNOWN -> all-cash         leg long iff THAT symbol's
                    reject FEATURES_UNKNOWN     own MA spread > +band;
                                                qualifying legs share the
                                                book equally (1.0 / 0.5);
                                                every other leg deliberate 0
mean_reversion      RANGE required (the same    RSI < 30 -> enter 0.5;
                    portfolio gate applies to   RSI >= 55 -> exit 0;
                    BOTH legs); non-RANGE ->    mid-band -> hold that
                    held legs exit with         symbol's virtual book;
                    REGIME_MISMATCH             unknown RSI -> leg 0, never
                                                silently held
high_vol_defensive  HIGH_VOL -> all cash for    otherwise hold the caller's
                    BOTH legs                   virtual book as-is
                                                (portfolio-label-driven)
==================  ==========================  ==============================

Declared-prior constants (reviewed here, never fitted):

- ``PER_SYMBOL_TREND_BAND_PCT`` mirrors ``RegimeConfig.trend_band_pct``
  (0.001). Candidates stay config-free by design, so the band is a fixed
  reviewed constant; changing one without the other must be a reviewed
  event.
- ``RSI_ENTRY_BELOW`` / ``RSI_EXIT_ABOVE`` /
  ``MEAN_REVERSION_ENTRY_EXPOSURE`` and the buy-hold 0.5/0.5 split are
  the V0.1 declared priors, now applied PER SYMBOL.

Conflict netting: divergent per-symbol signals resolve per leg (long a
symbol's own confirmed uptrend, deliberately flat the rest) — the
unified map IS the netted book. The ``{0, 1}`` leg states apply whenever
a single leg qualifies; when BOTH ma_cross legs qualify they split
0.5/0.5 so the unified map conserves weight (B2 目标权重守恒).

Insufficient / stale / UNKNOWN per-symbol data NEVER expands risk: the
affected leg goes to 0 with the reason recorded as a per-symbol segment
in the proposal ``rationale`` (``qqq=FEATURES_UNKNOWN``). A leg the rule
can no longer evaluate WHILE IT IS HELD is flattened visibly via
``reject_reasons`` (data loss never silently keeps or drops a position),
and a proposal whose every symbol is undecidable rejects entirely
(V0.1 fail-closed parity).

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
viable arm; ``ma_cross_trend`` operates (per leg: long or deliberately
flat) on every trend state; ``mean_reversion`` is only sensible in
``RANGE``; ``high_vol_defensive`` exists for ``HIGH_VOL`` sessions;
``buy_hold`` is a pure long-equity reference.

Candidates emit internal :class:`StrategyProposal` objects ONLY: no order
construction, no broker calls, and no ``StrategySignal`` contract
construction (crossing into the trust boundary happens exclusively in
``decision.py``). Information-plane input flows into strategies only
indirectly, through the regime labels and the router's veto — therefore
``info_refs_used`` stays empty here by design.

Candidates are stateless and deterministic: ``propose`` receives the
caller-maintained ``virtual_state`` (the candidate's OWN virtual
position, symbol -> exposure Decimal, carried by the router/replay) and
returns the NEW intended exposure map. Per-symbol virtual_state keys are
unchanged from V0.1 (``"SPY"``, ``"QQQ"``).
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
    "TRADED_SYMBOLS",
    "STRATEGY_VERSION",
    "CandidateStrategy",
    "CashBaselineStrategy",
    "BuyHoldStrategy",
    "MaCrossTrendStrategy",
    "MeanReversionStrategy",
    "HighVolDefensiveStrategy",
    "default_candidates",
]

# V2: unified per-symbol SPY/QQQ exposure maps (Business MVP V0.2 B2).
STRATEGY_VERSION = "V2"

# The traded equity universe (residual weight is cash). Kept here because
# strategies cannot import router.py (router imports this module).
TRADED_SYMBOLS: tuple[str, str] = ("SPY", "QQQ")

# Fixed mean-reversion thresholds (declared priors, not fitted).
RSI_ENTRY_BELOW = Decimal(30)   # RSI strictly below -> enter that symbol at 0.5
RSI_EXIT_ABOVE = Decimal(55)    # RSI at/above -> exit that symbol to flat
MEAN_REVERSION_ENTRY_EXPOSURE = Decimal("0.5")
BUY_HOLD_SPLIT = Decimal("0.5")  # reference book split across SPY/QQQ
FULL_EXPOSURE = Decimal(1)
FLAT_EXPOSURE = Decimal(0)
# Per-symbol trend band, mirroring RegimeConfig.trend_band_pct (declared
# prior; candidates are config-free by design — see module docstring).
PER_SYMBOL_TREND_BAND_PCT = Decimal("0.001")


def _ma_usable(fv: FeatureVector) -> bool:
    return fv.ma_short is not None and fv.ma_long is not None and fv.ma_long != 0


def _own_trend_label(fv: FeatureVector) -> str:
    """Trend state read from THIS symbol's own MA cross (portfolio regime
    labels are not per-symbol). Same band shape as the regime classifier;
    deterministic Decimal math."""
    assert fv.ma_short is not None and fv.ma_long is not None and fv.ma_long != 0
    spread = (fv.ma_short - fv.ma_long) / fv.ma_long
    if abs(spread) <= PER_SYMBOL_TREND_BAND_PCT:
        return LABEL_RANGE
    return LABEL_TREND_UP if spread > 0 else LABEL_TREND_DOWN


def _segments(parts: Mapping[str, str]) -> str:
    """Deterministic per-symbol reason segments for rationale strings,
    e.g. ``qqq=NO_UPTREND,spy=long@1.0`` (sorted by symbol)."""
    return ",".join(f"{symbol.lower()}={parts[symbol]}" for symbol in sorted(parts))


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
        """Return the NEW unified multi-symbol exposure map for this session."""

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
        total = sum(exposure.values(), Decimal(0))
        if total > FULL_EXPOSURE:
            # B2 weight conservation: the unified map must leave a
            # non-negative cash residual.
            raise ValueError(
                f"{self.strategy_id}: target weights must conserve "
                f"(sum {total} > 1); residual weight is cash"
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
    """Reference arm B1: splits the fixed 0.5/0.5 reference book across
    SPY and QQQ once BOTH symbols have warmed up. While only one symbol
    is warm the arm deploys the full book on that warmed symbol only
    (documented V0.2 choice: the reference stays fully invested in what
    it can honestly see); before ANY symbol is warm it rejects
    (cannot size honestly)."""

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
        warm: list[str] = []
        for symbol in TRADED_SYMBOLS:
            fv = features.get(symbol)
            if fv is not None and fv.status == STATUS_OK and fv.warmup_ok:
                warm.append(symbol)
        if not warm:
            return self._build(
                asof_utc,
                {},
                "reference buy-and-hold arm: no symbol warm",
                regime,
                reject_reasons=("WARMUP_INCOMPLETE",),
            )
        entering = [
            symbol for symbol in warm
            if virtual_state.get(symbol, FLAT_EXPOSURE) <= FLAT_EXPOSURE
        ]
        action = "entering" if entering else "holding"
        if len(warm) == len(TRADED_SYMBOLS):
            target = {symbol: BUY_HOLD_SPLIT for symbol in TRADED_SYMBOLS}
            rationale = (
                f"reference buy-and-hold arm: {action} 0.5/0.5 SPY/QQQ split"
            )
        else:
            symbol = warm[0]
            target = {symbol: FULL_EXPOSURE}
            rationale = (
                f"reference buy-and-hold arm: {action} {symbol} "
                "(single-symbol warmup)"
            )
        return self._build(asof_utc, target, rationale, regime)


@dataclass(frozen=True)
class MaCrossTrendStrategy(CandidateStrategy):
    """Trend follower, per symbol: a leg goes long iff THAT symbol's own
    MA cross is above the band (its features usable); every other leg is
    deliberately flat with the reason recorded. Qualifying legs share the
    book equally (one leg -> 1.0, both legs -> 0.5/0.5) so the unified
    map conserves weight. Portfolio regime UNKNOWN fail-safes to an
    all-cash reject; no symbol is ever silently held through unknown
    features."""

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
        if LABEL_UNKNOWN in regime.labels:
            return self._build(
                asof_utc,
                {},
                "trend rule unusable: regime unknown",
                regime,
                reject_reasons=("FEATURES_UNKNOWN",),
            )
        parts: dict[str, str] = {}
        qualifying: list[str] = []
        unknown_legs = 0
        for symbol in TRADED_SYMBOLS:
            fv = features.get(symbol)
            if fv is None or fv.status != STATUS_OK or not _ma_usable(fv):
                parts[symbol] = "FEATURES_UNKNOWN"
                unknown_legs += 1
                continue
            if _own_trend_label(fv) == LABEL_TREND_UP:
                qualifying.append(symbol)
            else:
                parts[symbol] = "NO_UPTREND"
        if unknown_legs == len(TRADED_SYMBOLS):
            return self._build(
                asof_utc,
                {},
                "trend rule unusable: all symbol features unknown",
                regime,
                reject_reasons=("FEATURES_UNKNOWN",),
            )
        share = (
            FULL_EXPOSURE / Decimal(len(qualifying)) if qualifying else FLAT_EXPOSURE
        )
        target = {
            symbol: (share if symbol in qualifying else FLAT_EXPOSURE)
            for symbol in TRADED_SYMBOLS
        }
        for symbol in qualifying:
            parts[symbol] = f"long@{share}"
        header = "trend rule long: " if qualifying else "no uptrend, trend rule flat: "
        return self._build(asof_utc, target, header + _segments(parts), regime)


@dataclass(frozen=True)
class MeanReversionStrategy(CandidateStrategy):
    """Range trader, per symbol under ONE shared RANGE gate: the regime
    labels are portfolio-level, so the SAME RANGE gate applies to both
    legs (documented V0.2 choice — there is no per-symbol regime read).
    In RANGE each symbol decides on its own RSI: below 30 enters that
    symbol at the fixed 0.5, at/above 55 exits it, mid-band holds its
    virtual book. Outside RANGE any held leg exits with a visible
    REGIME_MISMATCH reject; unknown RSI never silently holds a leg."""

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
        def _rsi_unknown(symbol: str) -> bool:
            fv = features.get(symbol)
            return fv is None or fv.status != STATUS_OK or fv.rsi is None

        if all(_rsi_unknown(symbol) for symbol in TRADED_SYMBOLS):
            # V0.1 fail-closed parity: when EVERY traded symbol is
            # undecidable the proposal rejects regardless of regime.
            return self._build(
                asof_utc,
                {},
                "mean reversion unusable: RSI unknown",
                regime,
                reject_reasons=("FEATURES_UNKNOWN",),
            )
        in_range = LABEL_RANGE in regime.labels and LABEL_UNKNOWN not in regime.labels
        if not in_range:
            return self._exit_out_of_range(asof_utc, regime, virtual_state)
        return self._trade_in_range(asof_utc, features, regime, virtual_state)

    def _exit_out_of_range(
        self,
        asof_utc: dt.datetime,
        regime: RegimeAssessment,
        virtual_state: Mapping[str, Decimal],
    ) -> StrategyProposal:
        held = [
            symbol
            for symbol in TRADED_SYMBOLS
            if virtual_state.get(symbol, FLAT_EXPOSURE) > FLAT_EXPOSURE
        ]
        if held:
            target = {symbol: FLAT_EXPOSURE for symbol in held}
            return self._build(
                asof_utc,
                target,
                "outside RANGE: mean reversion exits held legs",
                regime,
                reject_reasons=("REGIME_MISMATCH",),
            )
        return self._build(
            asof_utc,
            self._held_exposure(virtual_state),
            "outside RANGE and already flat: hold cash",
            regime,
        )

    def _trade_in_range(
        self,
        asof_utc: dt.datetime,
        features: Mapping[str, FeatureVector],
        regime: RegimeAssessment,
        virtual_state: Mapping[str, Decimal],
    ) -> StrategyProposal:
        target: dict[str, Decimal] = {}
        parts: dict[str, str] = {}
        undecidable: list[str] = []
        for symbol in TRADED_SYMBOLS:
            fv = features.get(symbol)
            if fv is None or fv.status != STATUS_OK or fv.rsi is None:
                undecidable.append(symbol)
                # unknown RSI: leg to 0, never silently held
                target[symbol] = FLAT_EXPOSURE
                parts[symbol] = "FEATURES_UNKNOWN"
                continue
            if fv.rsi < RSI_ENTRY_BELOW:
                target[symbol] = MEAN_REVERSION_ENTRY_EXPOSURE
                parts[symbol] = f"enter@{MEAN_REVERSION_ENTRY_EXPOSURE}"
            elif fv.rsi >= RSI_EXIT_ABOVE:
                target[symbol] = FLAT_EXPOSURE
                parts[symbol] = "exit"
            else:
                current = virtual_state.get(symbol, FLAT_EXPOSURE)
                if current > FLAT_EXPOSURE:
                    target[symbol] = current
                    parts[symbol] = f"hold@{current}"
                # flat mid-band: leg stays out of the map (residual cash)
        # all-undecidable was already rejected in propose(); here at least
        # one leg is decidable.
        held_undecidable = any(
            virtual_state.get(symbol, FLAT_EXPOSURE) > FLAT_EXPOSURE
            for symbol in undecidable
        )
        reject: tuple[str, ...] = ("FEATURES_UNKNOWN",) if held_undecidable else ()
        header = (
            "mean reversion RANGE (unknown leg flattened): "
            if held_undecidable
            else "mean reversion RANGE: "
        )
        return self._build(asof_utc, target, header + _segments(parts), regime, reject)


@dataclass(frozen=True)
class HighVolDefensiveStrategy(CandidateStrategy):
    """Defensive arm: all cash for BOTH symbols while HIGH_VOL is active;
    otherwise holds the caller-maintained virtual book per symbol. The
    arm is portfolio-label-driven — it consumes only the regime label,
    never per-symbol features — so the routing primary's unusable
    features still force the honest full reject (the HIGH_VOL label
    itself cannot be confirmed from unknown primary data)."""

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
        fv = features.get(PRIMARY_SYMBOL)
        if fv is None or fv.status != STATUS_OK:
            return self._build(
                asof_utc,
                {},
                "defensive arm unusable: primary features unknown",
                regime,
                reject_reasons=("FEATURES_UNKNOWN",),
            )
        if LABEL_HIGH_VOL in regime.labels:
            return self._build(
                asof_utc, {}, "defensive: HIGH_VOL active, all cash (both legs)", regime
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
