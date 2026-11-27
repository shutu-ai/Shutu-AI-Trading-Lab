"""Tests for the fixed candidate strategy set (B3, MOCK_ONLY).

Hand-made deterministic fixtures only — no dependency on the concurrent
features/information-plane workstreams. Regime fixtures are produced by
the B3 classifier itself so label plumbing is exercised end to end.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping, Sequence

from trading_lab.business.config import RegimeConfig
from trading_lab.business.regime import (
    LABEL_HIGH_VOL,
    LABEL_TREND_UP,
    PRIMARY_SYMBOL,
    InformationAssessmentView,
    RuleRegimeClassifier,
)
from trading_lab.business.strategies import (
    CashBaselineStrategy,
    BuyHoldStrategy,
    HighVolDefensiveStrategy,
    MaCrossTrendStrategy,
    MeanReversionStrategy,
    default_candidates,
)
from trading_lab.business.types import STATUS_OK, STATUS_UNKNOWN, FeatureVector, StrategyProposal
from trading_lab.contracts.events import RegimeAssessment
from trading_lab.security.canonical import canonical_digest

UTC = dt.timezone.utc
ASOF = dt.datetime(2026, 1, 5, 21, 0, tzinfo=UTC)
VALID_UNTIL = dt.datetime(2026, 1, 6, 21, 0, tzinfo=UTC)


def make_features(
    *,
    status: str = STATUS_OK,
    ma_short: str = "450.0",
    ma_long: str = "450.0",
    rsi: str | None = "50.0",
    realized_vol: str = "0.010",
    warmup_ok: bool = True,
    reasons: tuple[str, ...] = (),
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
            reasons=reasons,
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
        reasons=reasons,
        feature_hash=canonical_digest({"sym": PRIMARY_SYMBOL, "ma_s": ma_short, "ma_l": ma_long}),
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


def make_regime(
    features: Mapping[str, FeatureVector],
    *,
    info: Sequence[InformationAssessmentView] = (),
    vol_history: Sequence[Decimal] = (),
) -> RegimeAssessment:
    classifier = RuleRegimeClassifier(RegimeConfig())
    return classifier.classify(ASOF, features, info, None, vol_history, VALID_UNTIL)


def propose(
    strategy,
    features: Mapping[str, FeatureVector],
    regime: RegimeAssessment,
    virtual_state: Mapping[str, Decimal] | None = None,
) -> StrategyProposal:
    return strategy.propose(ASOF, features, regime, (), virtual_state or {})


# -- fixture regimes --------------------------------------------------------


def trend_up() -> RegimeAssessment:
    return make_regime({"SPY": make_features(ma_short="460", ma_long="450")})


def trend_down() -> RegimeAssessment:
    return make_regime({"SPY": make_features(ma_short="440", ma_long="450")})


def range_low_rsi() -> RegimeAssessment:
    return make_regime({"SPY": make_features(ma_short="450.2", ma_long="450", rsi="25")})


def range_mid_rsi() -> RegimeAssessment:
    return make_regime({"SPY": make_features(ma_short="450.2", ma_long="450", rsi="45")})


def range_high_rsi() -> RegimeAssessment:
    return make_regime({"SPY": make_features(ma_short="450.2", ma_long="450", rsi="60")})


def high_vol() -> RegimeAssessment:
    features = make_features(realized_vol="0.050")
    history = [Decimal("0.001")] * 60
    return make_regime({"SPY": features}, vol_history=history)


class TestNaturalRegimesTable:
    """The declared per-candidate natural_regimes table (scoring input)."""

    def test_table_matches_declaration(self) -> None:
        assert CashBaselineStrategy().natural_regimes == (
            "TREND_UP",
            "TREND_DOWN",
            "RANGE",
            "HIGH_VOL",
        )
        assert BuyHoldStrategy().natural_regimes == ("TREND_UP",)
        assert MaCrossTrendStrategy().natural_regimes == (
            "TREND_UP",
            "TREND_DOWN",
            "RANGE",
        )
        assert MeanReversionStrategy().natural_regimes == ("RANGE",)
        assert HighVolDefensiveStrategy().natural_regimes == ("HIGH_VOL",)

    def test_reference_flags(self) -> None:
        assert CashBaselineStrategy().reference is True
        assert BuyHoldStrategy().reference is True
        assert MaCrossTrendStrategy().reference is False
        assert MeanReversionStrategy().reference is False
        assert HighVolDefensiveStrategy().reference is False

    def test_default_candidate_order_is_fixed(self) -> None:
        assert [c.strategy_id for c in default_candidates()] == [
            "cash_baseline",
            "buy_hold",
            "ma_cross_trend",
            "mean_reversion",
            "high_vol_defensive",
        ]


class TestCashBaseline:
    def test_always_all_cash_never_rejects(self) -> None:
        strategy = CashBaselineStrategy()
        for regime in (trend_up(), high_vol()):
            proposal = propose(strategy, {"SPY": make_features()}, regime)
            assert proposal.target_exposure == {}
            assert proposal.reject_reasons == ()
            assert proposal.rationale == "reference cash arm"
            assert proposal.strategy_id == "cash_baseline"
            assert proposal.strategy_version == "V1"
            assert proposal.regime_labels_used == regime.labels


class TestBuyHold:
    def test_enters_full_spy_when_warm(self) -> None:
        strategy = BuyHoldStrategy()
        proposal = propose(strategy, {"SPY": make_features()}, trend_up())
        assert proposal.target_exposure == {PRIMARY_SYMBOL: Decimal(1)}
        assert proposal.reject_reasons == ()
        assert "reference" in proposal.rationale

    def test_holds_forever_with_virtual_state(self) -> None:
        strategy = BuyHoldStrategy()
        proposal = propose(
            strategy, {"SPY": make_features()}, trend_up(), {PRIMARY_SYMBOL: Decimal(1)}
        )
        assert proposal.target_exposure == {PRIMARY_SYMBOL: Decimal(1)}
        assert "holding" in proposal.rationale

    def test_rejects_before_warmup(self) -> None:
        strategy = BuyHoldStrategy()
        proposal = propose(
            strategy, {"SPY": make_features(warmup_ok=False)}, trend_up()
        )
        assert proposal.target_exposure == {}
        assert proposal.reject_reasons == ("WARMUP_INCOMPLETE",)

    def test_rejects_unknown_features(self) -> None:
        strategy = BuyHoldStrategy()
        proposal = propose(strategy, {"SPY": make_features(status=STATUS_UNKNOWN)}, trend_up())
        assert proposal.reject_reasons == ("WARMUP_INCOMPLETE",)


class TestMaCrossTrend:
    def test_long_in_trend_up(self) -> None:
        proposal = propose(MaCrossTrendStrategy(), {"SPY": make_features()}, trend_up())
        assert proposal.target_exposure == {PRIMARY_SYMBOL: Decimal(1)}
        assert proposal.reject_reasons == ()

    def test_exit_in_trend_down(self) -> None:
        proposal = propose(MaCrossTrendStrategy(), {"SPY": make_features()}, trend_down())
        assert proposal.target_exposure == {PRIMARY_SYMBOL: Decimal(0)}
        assert proposal.reject_reasons == ()

    def test_exit_in_range(self) -> None:
        proposal = propose(MaCrossTrendStrategy(), {"SPY": make_features()}, range_mid_rsi())
        assert proposal.target_exposure == {PRIMARY_SYMBOL: Decimal(0)}
        assert proposal.reject_reasons == ()

    def test_rejects_unknown_features(self) -> None:
        features = {"SPY": make_features(status=STATUS_UNKNOWN, reasons=("NO_BARS",))}
        proposal = propose(MaCrossTrendStrategy(), features, make_regime(features))
        assert proposal.reject_reasons == ("FEATURES_UNKNOWN",)
        assert proposal.target_exposure == {}


class TestMeanReversion:
    def test_enters_half_on_oversold(self) -> None:
        proposal = propose(MeanReversionStrategy(), {"SPY": make_features(rsi="25")}, range_low_rsi())
        assert proposal.target_exposure == {PRIMARY_SYMBOL: Decimal("0.5")}
        assert proposal.reject_reasons == ()

    def test_exits_through_exit_band(self) -> None:
        proposal = propose(MeanReversionStrategy(), {"SPY": make_features(rsi="60")}, range_high_rsi())
        assert proposal.target_exposure == {PRIMARY_SYMBOL: Decimal(0)}
        assert proposal.reject_reasons == ()

    def test_mid_band_holds_virtual_exposure(self) -> None:
        proposal = propose(
            MeanReversionStrategy(),
            {"SPY": make_features(rsi="45")},
            range_mid_rsi(),
            {PRIMARY_SYMBOL: Decimal("0.5")},
        )
        assert proposal.target_exposure == {PRIMARY_SYMBOL: Decimal("0.5")}
        assert proposal.reject_reasons == ()

    def test_mid_band_flat_stays_flat(self) -> None:
        proposal = propose(MeanReversionStrategy(), {"SPY": make_features(rsi="45")}, range_mid_rsi())
        assert proposal.target_exposure == {}

    def test_regime_mismatch_exits_with_reject(self) -> None:
        proposal = propose(
            MeanReversionStrategy(),
            {"SPY": make_features()},
            trend_up(),
            {PRIMARY_SYMBOL: Decimal("0.5")},
        )
        assert proposal.target_exposure == {PRIMARY_SYMBOL: Decimal(0)}
        assert proposal.reject_reasons == ("REGIME_MISMATCH",)

    def test_regime_mismatch_flat_is_plain_hold(self) -> None:
        proposal = propose(MeanReversionStrategy(), {"SPY": make_features()}, trend_up())
        assert proposal.target_exposure == {}
        assert proposal.reject_reasons == ()

    def test_rejects_unknown_rsi(self) -> None:
        proposal = propose(
            MeanReversionStrategy(), {"SPY": make_features(rsi=None)}, range_mid_rsi()
        )
        assert proposal.reject_reasons == ("FEATURES_UNKNOWN",)


class TestHighVolDefensive:
    def test_all_cash_under_high_vol(self) -> None:
        proposal = propose(HighVolDefensiveStrategy(), {"SPY": make_features()}, high_vol())
        assert proposal.target_exposure == {}
        assert proposal.reject_reasons == ()
        assert "defensive" in proposal.rationale
        assert LABEL_HIGH_VOL in proposal.regime_labels_used

    def test_holds_virtual_exposure_when_not_high_vol(self) -> None:
        proposal = propose(
            HighVolDefensiveStrategy(),
            {"SPY": make_features()},
            trend_up(),
            {PRIMARY_SYMBOL: Decimal("0.5")},
        )
        assert proposal.target_exposure == {PRIMARY_SYMBOL: Decimal("0.5")}
        assert proposal.reject_reasons == ()

    def test_rejects_unknown_features(self) -> None:
        features = {"SPY": make_features(status=STATUS_UNKNOWN)}
        proposal = propose(HighVolDefensiveStrategy(), features, make_regime(features))
        assert proposal.reject_reasons == ("FEATURES_UNKNOWN",)


class TestProposalInvariants:
    def test_exposure_bounds_and_labels_on_every_candidate(self) -> None:
        for regime in (trend_up(), range_mid_rsi(), high_vol()):
            for strategy in default_candidates():
                proposal = propose(strategy, {"SPY": make_features()}, regime)
                for weight in proposal.target_exposure.values():
                    assert Decimal(0) <= weight <= Decimal(1)
                assert proposal.strategy_version == "V1"
                assert proposal.regime_labels_used == regime.labels
                assert proposal.asof_utc == ASOF
                assert proposal.info_refs_used == ()

    def test_propose_is_deterministic(self) -> None:
        for strategy in default_candidates():
            first = propose(strategy, {"SPY": make_features(rsi="25")}, range_low_rsi())
            second = propose(strategy, {"SPY": make_features(rsi="25")}, range_low_rsi())
            assert first == second
            assert first.target_exposure is not second.target_exposure  # fresh copies
