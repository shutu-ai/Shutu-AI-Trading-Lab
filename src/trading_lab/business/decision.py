"""Decision orchestrator: candidates -> gated signals -> router ->
TargetPortfolio (gated) with a full explanation trail.

Trust-boundary discipline (B4):

- Strategies never construct orders or touch brokers; they emit internal
  ``StrategyProposal`` objects.
- Each proposal crosses the SchemaGate as a ``StrategySignal`` contract
  (registered reviewed build hash required — self-approval impossible).
- The router selects among GATE-ALLOWED proposals only.
- The chosen proposal becomes a ``TargetPortfolio`` contract admitted
  through the gate's portfolio path with the registered mock producer
  identity; a refused portfolio means NO_TRADE, never a bypass.
- Order intents are built later (mock execution / backtest submission)
  from the admitted portfolio — this module never builds orders itself.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Mapping, Sequence

from trading_lab.business.config import BusinessConfig
from trading_lab.business.mockexec import (
    RISK_BUDGET_ID,
    MockExecutionStack,
    demo_build_hash,
)
from trading_lab.business.router import CandidateRouter, VirtualPerformanceTracker
from trading_lab.business.strategies import (
    STRATEGY_VERSION,
    CandidateStrategy,
    default_candidates,
)
from trading_lab.business.types import (
    NO_TRADE,
    STATUS_UNKNOWN,
    DecisionOutput,
    FeatureVector,
    StrategyProposal,
)
from trading_lab.business.models import InformationAssessment
from trading_lab.contracts import (
    AllocationItem,
    RegimeAssessment,
    StrategySignal,
    TargetPortfolio,
)
from trading_lab.security.canonical import canonical_digest

__all__ = [
    "DecisionOrchestrator",
    "demo_strategy_build_hashes",
    "SUPPORTED_SIGNAL_SCHEMA_VERSION",
]

SUPPORTED_SIGNAL_SCHEMA_VERSION = "1"
_WEIGHT_Q = Decimal("0.00000001")


def demo_strategy_build_hashes(
    candidates: Sequence[CandidateStrategy] | None = None,
) -> dict[str, str]:
    """Deterministic reviewed-build hash per demo candidate strategy."""
    pool = candidates if candidates is not None else default_candidates()
    return {c.strategy_id: demo_build_hash(
        f"{c.strategy_id}:{STRATEGY_VERSION}") for c in pool}


class DecisionOrchestrator:
    """One replay account's decision pipeline for a single session."""

    def __init__(
        self,
        *,
        config: BusinessConfig,
        stack: MockExecutionStack,
        candidates: Sequence[CandidateStrategy] | None = None,
        router: CandidateRouter | None = None,
        tracker: VirtualPerformanceTracker | None = None,
    ) -> None:
        self._config = config
        self._stack = stack
        self._candidates = tuple(
            candidates if candidates is not None else default_candidates())
        self._build_hashes = demo_strategy_build_hashes(self._candidates)
        self._router = router if router is not None else CandidateRouter(
            config.router)
        self._tracker = tracker if tracker is not None \
            else VirtualPerformanceTracker()
        self._last_proposal_exposure: dict[str, Mapping[str, Decimal]] = {}
        self._last_proposals: dict[str, StrategyProposal] = {}

    @property
    def last_proposals(self) -> dict[str, StrategyProposal]:
        """Proposals from the most recent ``decide`` (pipeline trace)."""
        return dict(self._last_proposals)

    # -- introspection -----------------------------------------------------

    @property
    def router(self) -> CandidateRouter:
        return self._router

    @property
    def tracker(self) -> VirtualPerformanceTracker:
        return self._tracker

    @property
    def candidates(self) -> tuple[CandidateStrategy, ...]:
        return self._candidates

    @property
    def build_hashes(self) -> dict[str, str]:
        return dict(self._build_hashes)

    def per_candidate_exposure(self) -> dict[str, dict[str, Decimal]]:
        """Last proposed exposure per candidate (virtual tracker input)."""
        return {k: dict(v) for k, v in self._last_proposal_exposure.items()}

    # -- the decision --------------------------------------------------------

    def decide(
        self,
        *,
        asof: dt.datetime,
        snapshot_id: str,
        features: Mapping[str, FeatureVector],
        regime: RegimeAssessment,
        info_assessments: Sequence[InformationAssessment],
        valid_until: dt.datetime,
    ) -> DecisionOutput:
        proposals: dict[str, StrategyProposal] = {}
        for candidate in self._candidates:
            proposals[candidate.strategy_id] = candidate.propose(
                asof, features, regime, info_assessments,
                self._last_proposal_exposure.get(candidate.strategy_id, {}))
            self._last_proposal_exposure[candidate.strategy_id] = dict(
                proposals[candidate.strategy_id].target_exposure)
        self._last_proposals = dict(proposals)

        # trust boundary 1: every proposal passes the gate as a signal
        allowed: dict[str, StrategyProposal] = {}
        refused: dict[str, str] = {}
        for sid, proposal in proposals.items():
            gate = self._stack.evaluate_signal_admission(
                self._signal_payload(proposal, snapshot_id, valid_until))
            if gate.allow:
                allowed[sid] = proposal
            else:
                refused[sid] = "SIGNAL_ADMISSION_REFUSED:" + ",".join(
                    gate.reason_codes)

        selection = self._router.select(
            asof, allowed, regime, features, self._tracker,
            info_assessments=info_assessments)
        blocked = self._router.last_blocked

        if selection.chosen is None:
            return self._no_trade(asof, proposals, selection, blocked,
                                  refused, regime)

        chosen = selection.chosen
        portfolio = self._build_portfolio(chosen, asof)
        gate = self._stack.evaluate_portfolio_admission(
            portfolio.model_dump(mode="json"))
        if not gate.allow:
            refused[chosen.strategy_id] = (
                "PORTFOLIO_ADMISSION_REFUSED:" + ",".join(gate.reason_codes))
            return self._no_trade(asof, proposals, selection, blocked,
                                  refused, regime)

        rationale = self._rationale(chosen, selection, blocked, refused,
                                    regime)
        decision_hash = canonical_digest({
            "asof": asof.isoformat(),
            "chosen": chosen.strategy_id,
            "exposure": {k: str(v)
                         for k, v in sorted(chosen.target_exposure.items())},
            "portfolio_hash": canonical_digest(
                portfolio.model_dump(mode="json")),
        })
        return DecisionOutput(
            asof_utc=asof,
            chosen_strategy_id=chosen.strategy_id,
            target=portfolio,
            no_trade_reasons=(),
            candidate_scores=dict(selection.scores),
            rationale=rationale,
            decision_hash=decision_hash,
        )

    # -- internals -----------------------------------------------------------

    def _signal_payload(
        self, proposal: StrategyProposal, snapshot_id: str,
        valid_until: dt.datetime,
    ) -> dict[str, object]:
        exposure = sum(proposal.target_exposure.values(), Decimal("0"))
        if exposure > Decimal("1"):
            exposure = Decimal("1")
        if exposure < Decimal("0"):
            exposure = Decimal("0")
        signal = StrategySignal(
            schema_version=SUPPORTED_SIGNAL_SCHEMA_VERSION,
            strategy_id=proposal.strategy_id,
            strategy_version=proposal.strategy_version,
            reviewed_build_hash=self._build_hashes[proposal.strategy_id],
            snapshot_id=snapshot_id,
            target_exposure=exposure.quantize(_WEIGHT_Q),
            expires_at_utc=valid_until,
            rationale_hash=canonical_digest(
                {"rationale": proposal.rationale}),
        )
        # the gate consumes JSON; build the payload from the contract dump
        return signal.model_dump(mode="json")

    def _build_portfolio(self, chosen: StrategyProposal,
                         asof: dt.datetime) -> TargetPortfolio:
        weights = {
            s: w.quantize(_WEIGHT_Q)
            for s, w in chosen.target_exposure.items() if w > 0
        }
        cash = (Decimal("1") - sum(weights.values(), Decimal("0")))
        allocation = tuple(
            AllocationItem(symbol=s, weight=w)
            for s, w in sorted(weights.items()))
        return TargetPortfolio(
            account_id=self._config.mock_execution.account_id,
            allocation=allocation,
            cash_weight=cash,
            risk_budget_id=RISK_BUDGET_ID,
            timestamp=asof,
        )

    def _no_trade(
        self,
        asof: dt.datetime,
        proposals: Mapping[str, StrategyProposal],
        selection,
        blocked: Mapping[str, tuple[str, ...]],
        refused: Mapping[str, str],
        regime: RegimeAssessment,
    ) -> DecisionOutput:
        reasons = list(selection.no_trade_reasons)
        for sid, why in sorted(refused.items()):
            reasons.append(f"{sid}:{why}")
        for sid, why in sorted(blocked.items()):
            if why and sid not in refused:
                reasons.append(f"{sid}:{','.join(why)}")
        # de-duplicate deterministically, keep order stable
        seen: set[str] = set()
        unique: list[str] = []
        for r in reasons:
            if r not in seen:
                seen.add(r)
                unique.append(r)
        rationale = (
            f"NO_TRADE regime={'/'.join(regime.labels)} "
            f"reasons={' | '.join(unique[:8])}")
        return DecisionOutput(
            asof_utc=asof,
            chosen_strategy_id=None,
            target=None,
            no_trade_reasons=tuple(unique),
            candidate_scores=dict(selection.scores),
            rationale=rationale,
            decision_hash=canonical_digest({
                "asof": asof.isoformat(),
                "no_trade": sorted(unique),
                "scores": {k: str(v)
                           for k, v in sorted(selection.scores.items())},
            }),
        )

    def _rationale(
        self,
        chosen: StrategyProposal,
        selection,
        blocked: Mapping[str, tuple[str, ...]],
        refused: Mapping[str, str],
        regime: RegimeAssessment,
    ) -> str:
        parts = [
            f"chosen={chosen.strategy_id}",
            f"regime={'/'.join(regime.labels)}",
            f"exposure=" + (
                ",".join(f"{s}:{w}" for s, w in
                         sorted(chosen.target_exposure.items())) or "cash"),
            f"score={selection.scores.get(chosen.strategy_id)}",
        ]
        vetoed = [sid for sid, why in sorted(blocked.items())
                  if any("INFO_VETO" in r for r in why)]
        if vetoed:
            parts.append("info_veto=" + ",".join(vetoed))
        if refused:
            parts.append("gate_refused=" + ",".join(sorted(refused)))
        return " ".join(parts)
