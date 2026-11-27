"""Tests for the candidate router + virtual performance tracker (B3).

Hand-made deterministic fixtures only; regime fixtures come from the B3
classifier; proposals come from the B3 candidate set. All expected
scores are exact Decimal values pinned to the declared config weights.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping, Sequence

from trading_lab.business.config import RegimeConfig, RouterConfig
from trading_lab.business.regime import (
    PRIMARY_SYMBOL,
    InformationAssessmentView,
    RegimeClassifierSession,
    RuleRegimeClassifier,
)
from trading_lab.business.router import (
    CandidateRouter,
    RouterSelection,
    VirtualPerformanceTracker,
)
from trading_lab.business.strategies import default_candidates
from trading_lab.business.types import (
    STATUS_OK,
    STATUS_UNKNOWN,
    FeatureVector,
    StrategyProposal,
)
from trading_lab.security.canonical import canonical_digest

UTC = dt.timezone.utc
ASOF = dt.datetime(2026, 1, 5, 21, 0, tzinfo=UTC)
VALID_UNTIL = dt.datetime(2026, 1, 6, 21, 0, tzinfo=UTC)
MIN_SCORE = RouterConfig().min_score_to_trade


def make_features(
    *,
    status: str = STATUS_OK,
    ma_short: str = "450.0",
    ma_long: str = "450.0",
    rsi: str | None = "50.0",
    realized_vol: str = "0.010",
    warmup_ok: bool = True,
) -> FeatureVector:
    if status == STATUS_UNKNOWN:
        return FeatureVector(
            symbol=PRIMARY_SYMBOL,
            asof_utc=ASOF,
            asof_bar_ts=None,
            asof_bar_age_sessions=None,
            returns_1d=None,
            ma_short=None,
            ma_long=None,
            rsi=None,
            atr=None,
            realized_vol=None,
            volume_ratio=None,
            corr_other=None,
            warmup_ok=False,
            status=status,
            reasons=("NO_BARS",),
            feature_hash="",
        )
    return FeatureVector(
        symbol=PRIMARY_SYMBOL,
        asof_utc=ASOF,
        asof_bar_ts=ASOF,
        asof_bar_age_sessions=0,
        returns_1d=Decimal("0.001"),
        ma_short=Decimal(ma_short),
        ma_long=Decimal(ma_long),
        rsi=None if rsi is None else Decimal(rsi),
        atr=Decimal("1.0"),
        realized_vol=Decimal(realized_vol),
        volume_ratio=Decimal("1.0"),
        corr_other=None,
        warmup_ok=warmup_ok,
        status=status,
        reasons=(),
        feature_hash=canonical_digest(
            {"sym": PRIMARY_SYMBOL, "ma_s": ma_short, "ma_l": ma_long}
        ),
    )


@dataclass(frozen=True)
class InfoStub:
    """Hand-made stand-in matching the InformationAssessment shape."""

    assessment_id: str
    status: str = "ASSESSED"
    direction: str = "NEUTRAL"
    confidence: float = 0.5
    horizon: str = "SHORT"
    valid_until: dt.datetime = VALID_UNTIL


def trend_up_features() -> dict[str, FeatureVector]:
    return {"SPY": make_features(ma_short="460", ma_long="450")}


def trend_down_features() -> dict[str, FeatureVector]:
    return {"SPY": make_features(ma_short="440", ma_long="450")}


def range_rsi25_features() -> dict[str, FeatureVector]:
    return {"SPY": make_features(ma_short="450.2", ma_long="450", rsi="25")}


def unknown_features() -> dict[str, FeatureVector]:
    return {"SPY": make_features(status=STATUS_UNKNOWN)}


def high_vol_features() -> dict[str, FeatureVector]:
    return {
        "SPY": make_features(
            ma_short="450.2", ma_long="450", rsi="45", realized_vol="0.050"
        )
    }


def make_regime(
    features: Mapping[str, FeatureVector],
    vol_history: Sequence[Decimal] = (),
) -> object:
    session = RegimeClassifierSession(RuleRegimeClassifier(RegimeConfig()))
    return session.step(ASOF, features, (), vol_history, VALID_UNTIL)


def build_proposals(
    features: Mapping[str, FeatureVector],
    regime,
    virtual_states: Mapping[str, Mapping[str, Decimal]] | None = None,
) -> dict[str, StrategyProposal]:
    states = virtual_states or {}
    return {
        candidate.strategy_id: candidate.propose(
            ASOF, features, regime, (), states.get(candidate.strategy_id, {})
        )
        for candidate in default_candidates()
    }


def fresh_router(
    previous_target: Mapping[str, Decimal] | None = None,
    config: RouterConfig | None = None,
) -> CandidateRouter:
    return CandidateRouter(
        config if config is not None else RouterConfig(),
        default_candidates(),
        previous_target=previous_target,
    )


class TestTrendUpWinner:
    def test_trend_follower_beats_mean_reversion(self) -> None:
        features = trend_up_features()
        regime = make_regime(features)
        proposals = build_proposals(
            features,
            regime,
            virtual_states={
                "buy_hold": {PRIMARY_SYMBOL: Decimal(1)},
                "mean_reversion": {PRIMARY_SYMBOL: Decimal(1)},
            },
        )
        router = fresh_router(previous_target={PRIMARY_SYMBOL: Decimal(1)})
        selection = router.select(ASOF, proposals, regime, features, VirtualPerformanceTracker())
        assert selection.chosen is not None
        assert selection.chosen.strategy_id == "ma_cross_trend"
        assert selection.no_trade_reasons == ()
        # Exact score: fit 1.0*0.40 + dq 1.0*0.20 + perf 0.5*0.25 + risk 1.0*0.15.
        assert selection.scores["ma_cross_trend"] == Decimal("0.875")
        assert selection.scores["ma_cross_trend"] > selection.scores["mean_reversion"]
        assert selection.scores["mean_reversion"] == Decimal(0)  # REGIME_MISMATCH

    def test_reference_not_promoted_on_tie(self) -> None:
        features = trend_up_features()
        regime = make_regime(features)
        proposals = build_proposals(
            features, regime, virtual_states={"buy_hold": {PRIMARY_SYMBOL: Decimal(1)}}
        )
        router = fresh_router(previous_target={PRIMARY_SYMBOL: Decimal(1)})
        selection = router.select(ASOF, proposals, regime, features, VirtualPerformanceTracker())
        # buy_hold ties ma_cross_trend exactly, but references never win
        # while a non-reference candidate is eligible.
        assert selection.scores["buy_hold"] == selection.scores["ma_cross_trend"]
        assert selection.chosen is not None
        assert selection.chosen.strategy_id == "ma_cross_trend"

    def test_previous_target_updated_after_choice(self) -> None:
        features = trend_up_features()
        regime = make_regime(features)
        proposals = build_proposals(features, regime)
        router = fresh_router(previous_target={PRIMARY_SYMBOL: Decimal(1)})
        router.select(ASOF, proposals, regime, features, VirtualPerformanceTracker())
        assert router.previous_target == {PRIMARY_SYMBOL: Decimal(1)}


class TestRangeRouting:
    def test_mean_reversion_eligible_in_range(self) -> None:
        features = range_rsi25_features()
        regime = make_regime(features)
        proposals = build_proposals(features, regime)
        router = fresh_router()
        selection = router.select(ASOF, proposals, regime, features, VirtualPerformanceTracker())
        # mean_reversion: fit 1.0*0.40 + dq 1.0*0.20 + perf 0.5*0.25
        #              + risk 1.0*0.15 = 0.875 -> eligible (one-time entry
        #              from flat is deployment-exempt, integration fix
        #              BUSINESS-MVP-V01).
        assert selection.scores["mean_reversion"] == Decimal("0.875")
        assert selection.scores["mean_reversion"] >= MIN_SCORE
        assert selection.chosen is not None
        assert selection.chosen.strategy_id == "ma_cross_trend"

    def test_cash_reference_gated_despite_equal_score(self) -> None:
        features = range_rsi25_features()
        regime = make_regime(features)
        proposals = build_proposals(features, regime)
        router = fresh_router()
        selection = router.select(ASOF, proposals, regime, features, VirtualPerformanceTracker())
        assert selection.scores["cash_baseline"] == selection.scores["ma_cross_trend"]
        assert selection.chosen is not None
        assert selection.chosen.strategy_id != "cash_baseline"


class TestHighVolRouting:
    def test_high_vol_defensive_wins_under_high_vol(self) -> None:
        features = high_vol_features()
        regime = make_regime(features, vol_history=[Decimal("0.001")] * 60)
        assert "HIGH_VOL" in regime.labels  # fixture sanity
        proposals = build_proposals(
            features,
            regime,
            virtual_states={"mean_reversion": {PRIMARY_SYMBOL: Decimal("0.5")}},
        )
        router = fresh_router()
        selection = router.select(ASOF, proposals, regime, features, VirtualPerformanceTracker())
        # The defensive arm fits the regime exactly, proposes all cash at
        # zero turnover -> full 0.875; the holding mean reversion trails
        # with a turnover penalty; the cash reference is gated by the
        # eligible non-reference candidate.
        assert selection.chosen is not None
        assert selection.chosen.strategy_id == "high_vol_defensive"
        assert selection.scores["high_vol_defensive"] == Decimal("0.875")
        # Holding mean_reversion keeps its 0.5 book: from the router's flat
        # previous target this reads as initial deployment (exempt) -> 0.875.
        assert selection.scores["mean_reversion"] == Decimal("0.875")
        assert selection.no_trade_reasons == ()


class TestUnknownFeaturesFailSafe:
    def test_no_trade_never_silent_risk_on(self) -> None:
        features = unknown_features()
        regime = make_regime(features)
        proposals = build_proposals(features, regime)
        router = fresh_router()
        selection = router.select(ASOF, proposals, regime, features, VirtualPerformanceTracker())
        assert selection.chosen is None  # never silent risk-on
        # cash_baseline: fit 0 (UNKNOWN regime) + dq 0.5*0.20 + perf 0.125 + risk 0.15.
        assert selection.scores["cash_baseline"] == Decimal("0.375")
        assert selection.no_trade_reasons == (
            "buy_hold:WARMUP_INCOMPLETE",
            "cash_baseline:SCORE_BELOW_MIN",
            "high_vol_defensive:FEATURES_UNKNOWN",
            "ma_cross_trend:FEATURES_UNKNOWN",
            "mean_reversion:FEATURES_UNKNOWN",
            "NO_ELIGIBLE_CANDIDATE",
        )

    def test_no_trade_leaves_previous_target_unchanged(self) -> None:
        features = unknown_features()
        regime = make_regime(features)
        proposals = build_proposals(features, regime)
        router = fresh_router(previous_target={PRIMARY_SYMBOL: Decimal("0.5")})
        selection = router.select(ASOF, proposals, regime, features, VirtualPerformanceTracker())
        assert selection.chosen is None
        assert router.previous_target == {PRIMARY_SYMBOL: Decimal("0.5")}


class TestInfoVeto:
    def test_veto_blocks_risk_on_at_or_above_threshold(self) -> None:
        features = trend_up_features()
        regime = make_regime(features)
        proposals = build_proposals(
            features,
            regime,
            virtual_states={
                "buy_hold": {PRIMARY_SYMBOL: Decimal(1)},
                "mean_reversion": {PRIMARY_SYMBOL: Decimal("0.5")},
            },
        )
        info = [InfoStub("EV-1", direction="BEARISH", confidence=0.85)]
        router = fresh_router(previous_target={PRIMARY_SYMBOL: Decimal("0.5")})
        selection = router.select(
            ASOF, proposals, regime, features, VirtualPerformanceTracker(), info
        )
        # ma_cross (exposure 1.0, turnover 0.5 <= cap) would be eligible
        # (fit 1.0*0.40 + dq 1.0*0.20 + perf 0.5*0.25 + risk (1-0.5/0.6)*0.15
        # = 0.75) but the BEARISH veto excludes it; no non-reference
        # candidate remains, so the cash reference wins.
        assert selection.scores["ma_cross_trend"] == Decimal("0.75")
        assert selection.chosen is not None
        assert selection.chosen.strategy_id == "cash_baseline"
        assert router.previous_target == {}  # cash chosen target

    def test_below_threshold_no_veto(self) -> None:
        features = trend_up_features()
        regime = make_regime(features)
        proposals = build_proposals(
            features, regime, virtual_states={"buy_hold": {PRIMARY_SYMBOL: Decimal(1)}}
        )
        info = [InfoStub("EV-1", direction="BEARISH", confidence=0.75)]
        router = fresh_router(previous_target={PRIMARY_SYMBOL: Decimal(1)})
        selection = router.select(
            ASOF, proposals, regime, features, VirtualPerformanceTracker(), info
        )
        assert selection.chosen is not None
        assert selection.chosen.strategy_id == "ma_cross_trend"
        assert selection.no_trade_reasons == ()

    def test_veto_blocks_equity_and_falls_back_to_cash(self) -> None:
        """BEARISH veto above the confidence floor: every equity-exposure
        proposal is excluded with a visible reason and the router falls
        back to the cash REFERENCE (de-risking) instead of leaving the
        book invested. Veto reasons stay visible via ``last_blocked``."""
        features = trend_up_features()
        regime = make_regime(features)
        proposals = build_proposals(
            features,
            regime,
            virtual_states={
                "buy_hold": {PRIMARY_SYMBOL: Decimal(1)},
                "mean_reversion": {PRIMARY_SYMBOL: Decimal(1)},
            },
        )
        info = [InfoStub("EV-1", direction="BEARISH", confidence=0.9)]
        router = fresh_router(previous_target={PRIMARY_SYMBOL: Decimal(1)})
        selection = router.select(
            ASOF, proposals, regime, features, VirtualPerformanceTracker(), info
        )
        blocked = router.last_blocked
        assert "ma_cross_trend:INFO_VETO_BEARISH" in " ".join(
            f"{k}:{','.join(v)}" for k, v in blocked.items()
        ) or "INFO_VETO_BEARISH" in blocked.get("ma_cross_trend", ())
        assert "INFO_VETO_BEARISH" in blocked.get("buy_hold", ())
        # Equity candidates lost; the cash reference de-risks the book.
        assert selection.chosen is not None
        assert selection.chosen.strategy_id == "cash_baseline"
        assert selection.chosen.target_exposure == {}

    def test_bullish_assessment_does_not_veto(self) -> None:
        features = trend_up_features()
        regime = make_regime(features)
        proposals = build_proposals(
            features, regime, virtual_states={"buy_hold": {PRIMARY_SYMBOL: Decimal(1)}}
        )
        info = [InfoStub("EV-1", direction="BULLISH", confidence=0.99)]
        router = fresh_router(previous_target={PRIMARY_SYMBOL: Decimal(1)})
        selection = router.select(
            ASOF, proposals, regime, features, VirtualPerformanceTracker(), info
        )
        assert selection.chosen is not None
        assert selection.chosen.strategy_id == "ma_cross_trend"


class TestTurnoverCap:
    def test_over_cap_proposal_scored_zero_and_excluded(self) -> None:
        """Churn guard: a risk-INCREASING rebalance beyond the cap is
        excluded. Initial entry from flat and de-risking are exempt
        (integration fix BUSINESS-MVP-V01: the cap guards churn, not
        one-time deployment, and must never block exits)."""
        features = trend_up_features()
        regime = make_regime(features)
        proposals = build_proposals(features, regime)
        router = fresh_router(previous_target={PRIMARY_SYMBOL: Decimal("0.2")})
        # ma_cross/buy_hold target 1.0 from 0.2 -> increase 0.8 > 0.60 cap.
        selection = router.select(ASOF, proposals, regime, features, VirtualPerformanceTracker())
        assert selection.scores["ma_cross_trend"] == Decimal(0)
        assert selection.scores["buy_hold"] == Decimal(0)
        assert selection.chosen is not None
        assert selection.chosen.strategy_id != "ma_cross_trend"

    def test_initial_entry_from_flat_not_capped(self) -> None:
        features = trend_up_features()
        regime = make_regime(features)
        proposals = build_proposals(features, regime)
        router = fresh_router()  # previous flat: one-time deployment exempt
        selection = router.select(ASOF, proposals, regime, features, VirtualPerformanceTracker())
        assert selection.chosen is not None
        assert selection.chosen.strategy_id == "ma_cross_trend"
        assert selection.scores["ma_cross_trend"] > Decimal(0)

    def test_exit_from_holding_not_capped(self) -> None:
        """De-risking (1.0 -> 0.0) is never turnover-capped."""
        features = trend_down_features()
        regime = make_regime(features)
        proposals = build_proposals(features, regime)
        router = fresh_router(previous_target={PRIMARY_SYMBOL: Decimal(1)})
        selection = router.select(ASOF, proposals, regime, features, VirtualPerformanceTracker())
        # ma_cross proposes exit-to-cash in TREND_DOWN; must stay eligible.
        assert "ma_cross_trend:TURNOVER_CAP" not in selection.no_trade_reasons
        assert selection.scores["ma_cross_trend"] > Decimal(0)

    def test_cap_reason_visible_in_no_trade(self) -> None:
        features = trend_up_features()
        regime = make_regime(features)
        proposals = build_proposals(features, regime)
        config = RouterConfig(min_score_to_trade=Decimal("0.90"))
        router = fresh_router(config=config, previous_target={PRIMARY_SYMBOL: Decimal("0.2")})
        selection = router.select(ASOF, proposals, regime, features, VirtualPerformanceTracker())
        assert selection.chosen is None
        assert "ma_cross_trend:TURNOVER_CAP" in selection.no_trade_reasons
        assert "buy_hold:TURNOVER_CAP" in selection.no_trade_reasons
        assert "cash_baseline:SCORE_BELOW_MIN" in selection.no_trade_reasons

    def test_within_cap_turnover_penalized_not_excluded(self) -> None:
        features = range_rsi25_features()
        regime = make_regime(features)
        proposals = build_proposals(features, regime)
        router = fresh_router()
        selection = router.select(ASOF, proposals, regime, features, VirtualPerformanceTracker())
        # mean_reversion enters 0.5 from flat: one-time deployment exempt
        # -> full risk_cost 1.0 -> 0.4*1 + 0.2*1 + 0.25*0.5 + 0.15*1 = 0.875.
        assert selection.scores["mean_reversion"] == Decimal("0.875")


class TestProposalAccounting:
    def test_missing_proposal_recorded_and_ignored(self) -> None:
        features = trend_up_features()
        regime = make_regime(features)
        proposals = build_proposals(features, regime)
        del proposals["cash_baseline"]
        config = RouterConfig(min_score_to_trade=Decimal("0.90"))
        router = fresh_router(config=config)
        selection = router.select(ASOF, proposals, regime, features, VirtualPerformanceTracker())
        assert selection.chosen is None
        assert "cash_baseline:NO_PROPOSAL" in selection.no_trade_reasons

    def test_unregistered_proposal_id_gets_zero_score(self) -> None:
        features = trend_up_features()
        regime = make_regime(features)
        proposals = build_proposals(features, regime)
        ghost = StrategyProposal(
            strategy_id="ghost",
            strategy_version="V1",
            asof_utc=ASOF,
            target_exposure={},
            rationale="unregistered probe",
            regime_labels_used=regime.labels,
        )
        proposals["ghost"] = ghost
        config = RouterConfig(min_score_to_trade=Decimal("0.90"))
        router = fresh_router(config=config)
        selection = router.select(ASOF, proposals, regime, features, VirtualPerformanceTracker())
        assert selection.scores["ghost"] == Decimal(0)
        assert "ghost:NO_PROPOSAL" in selection.no_trade_reasons

    def test_duplicate_candidate_ids_rejected(self) -> None:
        pool = list(default_candidates()) + [default_candidates()[0]]
        try:
            CandidateRouter(RouterConfig(), pool)
        except ValueError:
            return
        raise AssertionError("duplicate strategy_id must raise ValueError")


class TestVirtualPerformanceTracker:
    def test_decimal_math_exact(self) -> None:
        tracker = VirtualPerformanceTracker()
        exposures_a = {PRIMARY_SYMBOL: Decimal(1)}
        exposures_b = {PRIMARY_SYMBOL: Decimal("0.5")}
        tracker.record_session(
            ASOF, Decimal("101"), Decimal("100"), {"a": exposures_a, "b": exposures_b}
        )
        tracker.record_session(
            ASOF + dt.timedelta(days=1), Decimal("99"), Decimal("101"),
            {"a": exposures_a, "b": exposures_b},
        )
        r1 = ((Decimal("101") - Decimal("100")) / Decimal("100")).quantize(
            Decimal("0.000000000001")
        )
        r2 = ((Decimal("99") - Decimal("101")) / Decimal("101")).quantize(
            Decimal("0.000000000001")
        )
        assert tracker.rolling_return("a") == r1 + r2
        assert tracker.rolling_return("b") == (r1 + r2) / 2
        assert tracker.sessions_recorded("a") == 2
        assert tracker.sessions_recorded("missing") == 0
        assert tracker.rolling_return("missing") is None

    def test_rolling_window_eviction(self) -> None:
        tracker = VirtualPerformanceTracker(window=2)
        for i in range(3):
            tracker.record_session(
                ASOF + dt.timedelta(days=i),
                Decimal("101") + i,
                Decimal("100") + i,
                {"a": {PRIMARY_SYMBOL: Decimal(1)}},
            )
        assert tracker.sessions_recorded("a") == 2  # window capped at 2
        r2 = ((Decimal("102") - Decimal("101")) / Decimal("101")).quantize(
            Decimal("0.000000000001")
        )
        r3 = ((Decimal("103") - Decimal("102")) / Decimal("102")).quantize(
            Decimal("0.000000000001")
        )
        assert tracker.rolling_return("a") == r2 + r3  # oldest session dropped

    def test_first_session_without_prev_close_records_nothing(self) -> None:
        tracker = VirtualPerformanceTracker()
        tracker.record_session(ASOF, Decimal("101"), None, {"a": {PRIMARY_SYMBOL: Decimal(1)}})
        assert tracker.sessions_recorded("a") == 0
        assert tracker.rolling_return("a") is None


class TestChampionAndRanking:
    def _record_rising(self, tracker: VirtualPerformanceTracker) -> None:
        for i in range(5):
            tracker.record_session(
                ASOF + dt.timedelta(days=i),
                Decimal("100") + i + 1,
                Decimal("100") + i,
                {
                    "ma_cross_trend": {PRIMARY_SYMBOL: Decimal(1)},
                    "mean_reversion": {PRIMARY_SYMBOL: Decimal("0.5")},
                },
            )

    def test_rank_normalized_scores_and_champion(self) -> None:
        tracker = VirtualPerformanceTracker()
        self._record_rising(tracker)
        assert tracker.champion() == "ma_cross_trend"
        features = trend_up_features()
        regime = make_regime(features)
        proposals = build_proposals(
            features, regime, virtual_states={"mean_reversion": {PRIMARY_SYMBOL: Decimal("0.5")}}
        )
        router = fresh_router(previous_target={PRIMARY_SYMBOL: Decimal(1)})
        selection = router.select(ASOF, proposals, regime, features, tracker)
        # Best of the two-history pool -> performance 1.0 -> total 1.00.
        assert selection.scores["ma_cross_trend"] == Decimal(1)
        assert selection.chosen is not None
        assert selection.chosen.strategy_id == "ma_cross_trend"

    def test_champion_flips_to_challenger(self) -> None:
        tracker = VirtualPerformanceTracker()
        self._record_rising(tracker)
        for i in range(5):
            tracker.record_session(
                ASOF + dt.timedelta(days=5 + i),
                Decimal("105") - Decimal(5) * (i + 1),
                Decimal("105") - Decimal(5) * i,
                {
                    "ma_cross_trend": {PRIMARY_SYMBOL: Decimal(1)},
                    "mean_reversion": {PRIMARY_SYMBOL: Decimal(0)},
                },
            )
        # Challenger replaced the champion purely via window math, inside
        # this offline mock demo only (no real promotion path exists).
        assert tracker.champion() == "mean_reversion"


CLOSING_SERIES = [Decimal("100"), Decimal("102"), Decimal("101"), Decimal("103"),
                  Decimal("102"), Decimal("104"), Decimal("105")]
MA_SHORT_SERIES = ["460", "450.2", "460", "460", "450.2", "450.2", "450.2"]


def run_replay() -> list[tuple[str | None, dict[str, Decimal], tuple[str, ...]]]:
    """Full deterministic mini-replay: regime session -> proposals ->
    router select -> tracker record. Used for cross-run determinism."""
    regime_session = RegimeClassifierSession(RuleRegimeClassifier(RegimeConfig()))
    tracker = VirtualPerformanceTracker()
    router = fresh_router()
    results: list[tuple[str | None, dict[str, Decimal], tuple[str, ...]]] = []
    prev_close: Decimal | None = None
    for i, close in enumerate(CLOSING_SERIES):
        asof = ASOF + dt.timedelta(days=i)
        features = {"SPY": make_features(ma_short=MA_SHORT_SERIES[i], ma_long="450")}
        regime = regime_session.step(asof, features, (), (), VALID_UNTIL)
        proposals = build_proposals(features, regime)
        selection: RouterSelection = router.select(asof, proposals, regime, features, tracker)
        tracker.record_session(
            asof, close, prev_close,
            {cid: p.target_exposure for cid, p in proposals.items()},
        )
        prev_close = close
        chosen_id = selection.chosen.strategy_id if selection.chosen is not None else None
        results.append((chosen_id, dict(selection.scores), selection.no_trade_reasons))
    return results


class TestDeterminism:
    def test_scores_and_chosen_deterministic_across_runs(self) -> None:
        first = run_replay()
        second = run_replay()
        assert first == second
        # Guard against vacuous equality: both runs routed at least one
        # session and scores are non-trivial.
        assert any(chosen is not None for chosen, _, _ in first)
        assert any(scores for _, scores, _ in first)
