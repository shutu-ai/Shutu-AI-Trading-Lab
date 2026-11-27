"""Candidate router + virtual performance tracker (Business MVP V0.1).

MOCK_ONLY: scores are transparent fixed-rule combinations over declared
config weights. Nothing here is a backtest fill, a claimable performance
number, or any kind of real-market claim.

Champion/Challenger lite: :class:`VirtualPerformanceTracker` reports
which candidate currently leads its rolling window (``champion``).
Challengers may replace the champion ONLY through ordinary score
selection inside THIS offline mock demo — there is no real promotion
path, no Paper/Live implication, and no human-approval bypass of any
kind. The champion label is a reporting/diagnostic value.

Scoring (per ``RouterConfig`` weights, all components in [0, 1]):

- ``regime_fit`` — 1.0 when the candidate's declared ``natural_regimes``
  intersect the current regime labels, else 0.0; an UNKNOWN regime
  scores 0.0 for everyone.
- ``data_quality`` — 1.0 when the proposal has no reject_reasons and the
  primary features are OK; 0.5 partial (no rejects but primary features
  unusable); 0.0 when the proposal carries reject_reasons.
- ``virtual_performance`` — rank-normalized rolling virtual return within
  the candidate pool (fraction of pool candidates strictly below; ties
  share the score); fewer than ``min_sessions_for_rank`` sessions of
  history -> neutral 0.5.
- ``risk_cost`` — 1.0 - turnover penalty, where turnover is the gross
  |delta exposure| versus the previous chosen target and the penalty is
  capped by ``max_turnover_per_session``; proposals exceeding the cap
  are excluded entirely (score floored to 0, reason recorded).

Selection: highest score wins only if >= ``min_score_to_trade`` and the
proposal has no reject_reasons; otherwise NO_TRADE with reasons.
References (``reference=True``) participate in scoring but can win only
when NO non-reference candidate is eligible — references never
auto-promote. The information veto excludes any proposal with positive
equity exposure while a sufficiently confident BEARISH assessment is
active.
"""

from __future__ import annotations

import datetime as dt
from collections import deque
from decimal import Decimal
from typing import Mapping, NamedTuple, Sequence

from trading_lab.business.config import RouterConfig
from trading_lab.business.regime import (
    LABEL_UNKNOWN,
    PRIMARY_SYMBOL,
    InformationAssessmentView,
)
from trading_lab.business.strategies import CandidateStrategy, default_candidates
from trading_lab.business.types import STATUS_OK, FeatureVector, StrategyProposal
from trading_lab.contracts.events import RegimeAssessment

__all__ = [
    "EQUITY_SYMBOLS",
    "ROUTER_WINDOW_SESSIONS",
    "MIN_SESSIONS_FOR_RANK",
    "RouterSelection",
    "VirtualPerformanceTracker",
    "CandidateRouter",
]

# V0.1 equity universe (residual weight is cash; only these symbols can
# carry exposure and therefore trigger the information veto).
EQUITY_SYMBOLS: tuple[str, ...] = ("SPY", "QQQ")

ROUTER_WINDOW_SESSIONS = 60
MIN_SESSIONS_FOR_RANK = 5

# Fixed quantization for virtual per-session returns (12 dp) so rolling
# sums are stable and byte-reproducible.
_RETURN_Q = Decimal("0.000000000001")

_REASON_NO_PROPOSAL = "NO_PROPOSAL"
_REASON_TURNOVER_CAP = "TURNOVER_CAP"
_REASON_INFO_VETO = "INFO_VETO_BEARISH"
_REASON_BELOW_MIN = "SCORE_BELOW_MIN"
_REASON_NO_ELIGIBLE = "NO_ELIGIBLE_CANDIDATE"


class RouterSelection(NamedTuple):
    """Result of one router selection (tuple-unpackable per the task
    signature: chosen, scores, no_trade_reasons)."""

    chosen: StrategyProposal | None
    scores: Mapping[str, Decimal]
    no_trade_reasons: tuple[str, ...]


class VirtualPerformanceTracker:
    """Per-candidate VIRTUAL close-to-close PnL over the primary symbol.

    The caller records one session at a time AFTER each replay session
    with fixture closes. Returns are pure Decimal math on close ratios
    scaled by the candidate's virtual primary exposure; cash exposure
    earns 0. This is a VIRTUAL bookkeeping series only — not backtest
    fills, not claimable performance, and never a real-market claim.
    """

    def __init__(
        self,
        window: int = ROUTER_WINDOW_SESSIONS,
        min_sessions_for_rank: int = MIN_SESSIONS_FOR_RANK,
    ) -> None:
        if window < 1 or min_sessions_for_rank < 1:
            raise ValueError("window and min_sessions_for_rank must be >= 1")
        self._window = window
        self._min_sessions = min_sessions_for_rank
        self._returns: dict[str, deque[Decimal]] = {}

    def record_session(
        self,
        asof: dt.datetime,
        primary_close: Decimal,
        prev_close: Decimal | None,
        per_candidate_exposure: Mapping[str, Mapping[str, Decimal]],
    ) -> None:
        """Record one session of virtual returns for every candidate that
        has a virtual exposure. A session without a previous close (the
        first fixture session) contributes no return."""
        if prev_close is None or prev_close == 0:
            return
        session_return = ((primary_close - prev_close) / prev_close).quantize(_RETURN_Q)
        for candidate_id, exposure in per_candidate_exposure.items():
            history = self._returns.setdefault(
                candidate_id, deque(maxlen=self._window)
            )
            scaled = (session_return * exposure.get(PRIMARY_SYMBOL, Decimal(0))).quantize(
                _RETURN_Q
            )
            history.append(scaled)

    @property
    def min_sessions(self) -> int:
        return self._min_sessions

    def rolling_return(self, candidate_id: str) -> Decimal | None:
        """Arithmetic sum of the candidate's rolling virtual per-session
        returns (None when there is no history)."""
        history = self._returns.get(candidate_id)
        if not history:
            return None
        return sum(history, Decimal(0))

    def sessions_recorded(self, candidate_id: str) -> int:
        history = self._returns.get(candidate_id)
        return 0 if history is None else len(history)

    def champion(self) -> str | None:
        """Candidate currently leading the rolling window (highest rolling
        virtual return among candidates with at least
        ``min_sessions_for_rank`` sessions; ties broken lexicographically
        for determinism). Demo-scoped diagnostic only — see module doc."""
        leaders = [
            (cid, tracker_return)
            for cid, history in sorted(self._returns.items())
            if len(history) >= self._min_sessions
            and (tracker_return := self.rolling_return(cid)) is not None
        ]
        if not leaders:
            return None
        return max(leaders, key=lambda item: (item[1], item[0]))[0]


class CandidateRouter:
    """Fixed-weight scorer and selector over the reviewed candidate pool.

    The router keeps minimal cross-session state: the previous chosen
    target exposure (for the turnover penalty). Seed it via
    ``previous_target`` for tests/replay warm-starts; NO_TRADE sessions
    leave it unchanged (a no-trade session does not liquidate the virtual
    book — that remains the replay executor's decision).
    """

    def __init__(
        self,
        config: RouterConfig,
        candidates: Sequence[CandidateStrategy] | None = None,
        previous_target: Mapping[str, Decimal] | None = None,
    ) -> None:
        self._config = config
        pool = tuple(candidates) if candidates is not None else default_candidates()
        ids = [c.strategy_id for c in pool]
        if len(set(ids)) != len(ids):
            raise ValueError(f"duplicate candidate strategy_id in pool: {ids}")
        self._candidates = pool
        self._previous_target: dict[str, Decimal] = (
            dict(previous_target) if previous_target is not None else {}
        )
        self._last_blocked: dict[str, tuple[str, ...]] = {}

    @property
    def previous_target(self) -> Mapping[str, Decimal]:
        return dict(self._previous_target)

    @property
    def last_blocked(self) -> Mapping[str, tuple[str, ...]]:
        """Per-candidate exclusion reasons from the most recent ``select``
        (veto / turnover cap / reject reasons) — the decision layer reads
        this for the NO_TRADE / veto explanation trail."""
        return dict(self._last_blocked)

    def select(
        self,
        asof_utc: dt.datetime,
        proposals: Mapping[str, StrategyProposal],
        regime: RegimeAssessment,
        features: Mapping[str, FeatureVector],
        tracker: VirtualPerformanceTracker,
        info_assessments: Sequence[InformationAssessmentView] = (),
    ) -> RouterSelection:
        """Score every candidate and pick a winner, or NO_TRADE with
        reasons. Deterministic in all inputs. ``asof_utc`` is carried for
        signature symmetry with the replay loop (proposals already embed
        their own asof)."""
        primary_ok = self._primary_ok(features)
        veto_active = self._info_veto_active(info_assessments)

        scored: dict[str, Decimal] = {}
        turnover: dict[str, Decimal] = {}
        blocked: dict[str, tuple[str, ...]] = {}
        for candidate in self._candidates:
            cid = candidate.strategy_id
            proposal = proposals.get(cid)
            candidate_turnover, risk_cost, cap_reasons = self._risk_component(proposal)
            turnover[cid] = candidate_turnover
            blocked[cid] = cap_reasons
            if proposal is None:
                scored[cid] = Decimal(0)
                blocked[cid] = blocked[cid] + (_REASON_NO_PROPOSAL,)
                continue
            if proposal.reject_reasons:
                scored[cid] = Decimal(0)
                blocked[cid] = blocked[cid] + proposal.reject_reasons
                continue
            fit = self._regime_fit(candidate, regime)
            quality = self._data_quality(proposal, primary_ok)
            performance = self._virtual_performance(tracker, cid)
            score = (
                self._config.weight_regime_fit * fit
                + self._config.weight_data_quality * quality
                + self._config.weight_virtual_performance * performance
                + self._config.weight_risk_cost * risk_cost
            )
            if cap_reasons:
                score = Decimal(0)  # turnover cap: score floor 0
            if veto_active and self._has_equity_exposure(proposal):
                blocked[cid] = blocked[cid] + (_REASON_INFO_VETO,)
            scored[cid] = score

        for extra_id in sorted(set(proposals) - {c.strategy_id for c in self._candidates}):
            scored[extra_id] = Decimal(0)
            blocked[extra_id] = (_REASON_NO_PROPOSAL,)

        chosen = self._choose(proposals, scored, blocked, turnover)
        if chosen is not None:
            self._previous_target = dict(chosen.target_exposure)
        self._last_blocked = dict(blocked)
        return RouterSelection(
            chosen, scored, self._no_trade_reasons(chosen, scored, blocked)
        )

    # -- components --------------------------------------------------------

    @staticmethod
    def _primary_ok(features: Mapping[str, FeatureVector]) -> bool:
        fv = features.get(PRIMARY_SYMBOL)
        return fv is not None and fv.status == STATUS_OK

    @staticmethod
    def _regime_fit(candidate: CandidateStrategy, regime: RegimeAssessment) -> Decimal:
        if LABEL_UNKNOWN in regime.labels:
            return Decimal(0)
        active = set(regime.labels)
        if active & set(candidate.natural_regimes):
            return Decimal(1)
        return Decimal(0)

    @staticmethod
    def _data_quality(proposal: StrategyProposal, primary_ok: bool) -> Decimal:
        if proposal.reject_reasons:
            return Decimal(0)
        return Decimal(1) if primary_ok else Decimal("0.5")

    def _virtual_performance(
        self, tracker: VirtualPerformanceTracker, candidate_id: str
    ) -> Decimal:
        """Rank-normalized rolling return within the pool: fraction of
        pool candidates with strictly lower rolling return (ties share a
        score); neutral 0.5 below the minimum-session threshold."""
        pool_returns: list[tuple[str, Decimal]] = []
        for candidate in self._candidates:
            if tracker.sessions_recorded(candidate.strategy_id) < tracker.min_sessions:
                continue
            value = tracker.rolling_return(candidate.strategy_id)
            if value is not None:
                pool_returns.append((candidate.strategy_id, value))
        mine = next((v for cid, v in pool_returns if cid == candidate_id), None)
        if mine is None:
            return Decimal("0.5")
        if len(pool_returns) == 1:
            return Decimal(1)
        below = sum(1 for _, v in pool_returns if v < mine)
        return Decimal(below) / Decimal(len(pool_returns) - 1)

    def _risk_component(
        self, proposal: StrategyProposal | None
    ) -> tuple[Decimal, Decimal, tuple[str, ...]]:
        """(turnover, risk_cost, cap_exclusion_reasons) for one proposal;
        a missing proposal carries zero turnover and no risk signal."""
        if proposal is None:
            return Decimal(0), Decimal(1), ()
        turnover = self._turnover(proposal.target_exposure)
        cap = self._config.max_turnover_per_session
        if cap <= 0:
            return turnover, Decimal(1), ()
        if not self._previous_target:
            # Initial capital deployment from the all-cash book: the cap
            # guards CHURN between targets, not the one-time entry (a
            # long-only full entry from flat is turnover 1.0 by
            # construction, so a 0.60 cap would otherwise bar every
            # equity candidate from ever entering).
            return turnover, Decimal(1), ()
        increase = self._risk_increasing_turnover(proposal.target_exposure)
        if increase <= 0:
            # Holds and de-risking (exits/partial exits) are never capped:
            # a churn guard must not block risk-REDUCING moves (e.g. a
            # trend exit in a downturn).
            return turnover, Decimal(1), ()
        penalty = min(Decimal(1), increase / cap)
        if increase > cap:
            return turnover, Decimal(0), (_REASON_TURNOVER_CAP,)
        return turnover, Decimal(1) - penalty, ()

    def _risk_increasing_turnover(
            self, target: Mapping[str, Decimal]) -> Decimal:
        """Gross weight INCREASES only (risk-reducing moves are exempt)."""
        keys = set(target) | set(self._previous_target)
        total = Decimal(0)
        for key in keys:
            delta = (target.get(key, Decimal(0))
                     - self._previous_target.get(key, Decimal(0)))
            if delta > 0:
                total += delta
        return total

    def _turnover(self, target: Mapping[str, Decimal]) -> Decimal:
        keys = set(target) | set(self._previous_target)
        total = Decimal(0)
        for key in keys:
            total += abs(target.get(key, Decimal(0)) - self._previous_target.get(key, Decimal(0)))
        return total

    def _info_veto_active(self, info_assessments: Sequence[InformationAssessmentView]) -> bool:
        threshold = self._config.info_veto_confidence
        for assessment in info_assessments:
            if assessment.status != "ASSESSED":
                continue
            if assessment.direction != "BEARISH":
                continue
            if Decimal(str(assessment.confidence)) >= threshold:
                return True
        return False

    @staticmethod
    def _has_equity_exposure(proposal: StrategyProposal) -> bool:
        return any(
            weight > 0
            for symbol, weight in proposal.target_exposure.items()
            if symbol in EQUITY_SYMBOLS
        )

    # -- selection ---------------------------------------------------------

    def _eligible(
        self,
        candidate: CandidateStrategy,
        scored: Mapping[str, Decimal],
        blocked: Mapping[str, tuple[str, ...]],
    ) -> bool:
        return not blocked[candidate.strategy_id] and (
            scored[candidate.strategy_id] >= self._config.min_score_to_trade
        )

    def _choose(
        self,
        proposals: Mapping[str, StrategyProposal],
        scored: Mapping[str, Decimal],
        blocked: Mapping[str, tuple[str, ...]],
        turnover: Mapping[str, Decimal],
    ) -> StrategyProposal | None:
        candidates_by_id = {c.strategy_id: c for c in self._candidates}
        non_refs = [
            c
            for c in self._candidates
            if not c.reference and self._eligible(c, scored, blocked)
        ]
        refs = [
            c for c in self._candidates if c.reference and self._eligible(c, scored, blocked)
        ]
        # References never auto-promote: they can win only when no
        # non-reference candidate is eligible.
        pool = non_refs if non_refs else refs
        if not pool:
            return None
        best_id = min(
            (c.strategy_id for c in pool),
            key=lambda cid: (-scored[cid], turnover[cid], cid),
        )
        return proposals.get(best_id) if best_id in candidates_by_id else None

    def _no_trade_reasons(
        self,
        chosen: StrategyProposal | None,
        scored: Mapping[str, Decimal],
        blocked: Mapping[str, tuple[str, ...]],
    ) -> tuple[str, ...]:
        if chosen is not None:
            return ()
        reasons: list[str] = []
        veto_caused = False
        for cid in sorted(scored):
            if blocked[cid]:
                for reason in blocked[cid]:
                    reasons.append(f"{cid}:{reason}")
                    if reason == _REASON_INFO_VETO:
                        veto_caused = True
            elif scored[cid] < self._config.min_score_to_trade:
                reasons.append(f"{cid}:{_REASON_BELOW_MIN}")
        if veto_caused:
            reasons.append(_REASON_INFO_VETO)
        reasons.append(_REASON_NO_ELIGIBLE)
        return tuple(reasons)
