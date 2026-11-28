"""Tests for the fixed candidate strategy set (B2/B3, MOCK_ONLY).

Hand-made deterministic fixtures only — no dependency on the concurrent
features/information-plane workstreams. Regime fixtures are produced by
the B3 classifier itself so label plumbing is exercised end to end.
V0.2 (B2): every candidate emits a UNIFIED SPY/QQQ exposure map; the
multi-symbol test classes below pin the documented per-symbol semantics.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping, Sequence

import pytest

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
    TRADED_SYMBOLS,
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
    symbol: str = PRIMARY_SYMBOL,
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
            symbol=symbol,
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
        symbol=symbol,
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
        feature_hash=canonical_digest({"sym": symbol, "ma_s": ma_short, "ma_l": ma_long}),
    )


def spy_features(**overrides: Any) -> FeatureVector:
    """SPY fixture defaults (trend-neutral around 450)."""
    return make_features(symbol="SPY", **overrides)


def qqq_features(**overrides: Any) -> FeatureVector:
    """QQQ fixture defaults (trend-neutral around 350; own MA band)."""
    overrides.setdefault("ma_short", "350.2")
    overrides.setdefault("ma_long", "350")
    return make_features(symbol="QQQ", **overrides)


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
            assert proposal.strategy_version == "V2"  # V2: unified SPY/QQQ maps (B2)
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
    # V0.2 semantics: the unified map carries BOTH legs explicitly; a
    # single-symbol fixture leaves the QQQ leg unusable -> explicit 0 with
    # a recorded reason (no cross-symbol contamination, no silent hold).
    def test_long_in_trend_up(self) -> None:
        # V0.2: the leg follows the symbol's OWN MA state, so the fixture
        # features must match the regime fixture (both TREND_UP).
        features = {"SPY": make_features(ma_short="460", ma_long="450")}
        proposal = propose(MaCrossTrendStrategy(), features, trend_up())
        assert proposal.target_exposure == {"SPY": Decimal(1), "QQQ": Decimal(0)}
        assert proposal.reject_reasons == ()
        assert "spy=long@1" in proposal.rationale
        assert "qqq=FEATURES_UNKNOWN" in proposal.rationale

    def test_exit_in_trend_down(self) -> None:
        proposal = propose(MaCrossTrendStrategy(), {"SPY": make_features()}, trend_down())
        assert proposal.target_exposure == {"SPY": Decimal(0), "QQQ": Decimal(0)}
        assert proposal.reject_reasons == ()

    def test_exit_in_range(self) -> None:
        proposal = propose(MaCrossTrendStrategy(), {"SPY": make_features()}, range_mid_rsi())
        assert proposal.target_exposure == {"SPY": Decimal(0), "QQQ": Decimal(0)}
        assert proposal.reject_reasons == ()

    def test_rejects_unknown_features(self) -> None:
        features = {"SPY": make_features(status=STATUS_UNKNOWN, reasons=("NO_BARS",))}
        proposal = propose(MaCrossTrendStrategy(), features, make_regime(features))
        assert proposal.reject_reasons == ("FEATURES_UNKNOWN",)
        assert proposal.target_exposure == {}


class TestMeanReversion:
    # V0.2 semantics: per-symbol RSI decisions under the SHARED portfolio
    # RANGE gate; a symbol with unknown RSI gets an explicit 0 leg with a
    # recorded reason while a decidable symbol still trades.
    def test_enters_half_on_oversold(self) -> None:
        proposal = propose(MeanReversionStrategy(), {"SPY": make_features(rsi="25")}, range_low_rsi())
        assert proposal.target_exposure == {"SPY": Decimal("0.5"), "QQQ": Decimal(0)}
        assert proposal.reject_reasons == ()
        assert "spy=enter@0.5" in proposal.rationale
        assert "qqq=FEATURES_UNKNOWN" in proposal.rationale

    def test_exits_through_exit_band(self) -> None:
        proposal = propose(MeanReversionStrategy(), {"SPY": make_features(rsi="60")}, range_high_rsi())
        assert proposal.target_exposure == {"SPY": Decimal(0), "QQQ": Decimal(0)}
        assert proposal.reject_reasons == ()

    def test_mid_band_holds_virtual_exposure(self) -> None:
        proposal = propose(
            MeanReversionStrategy(),
            {"SPY": make_features(rsi="45")},
            range_mid_rsi(),
            {PRIMARY_SYMBOL: Decimal("0.5")},
        )
        assert proposal.target_exposure == {"SPY": Decimal("0.5"), "QQQ": Decimal(0)}
        assert proposal.reject_reasons == ()

    def test_mid_band_flat_stays_flat(self) -> None:
        # V0.2: the decidable flat SPY leg stays out of the map (cash);
        # the undecidable QQQ leg is an explicit 0 (never silently held).
        proposal = propose(MeanReversionStrategy(), {"SPY": make_features(rsi="45")}, range_mid_rsi())
        assert proposal.target_exposure == {"QQQ": Decimal(0)}

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
        # V0.1 parity: when EVERY traded symbol is undecidable the whole
        # proposal fails closed with FEATURES_UNKNOWN.
        proposal = propose(
            MeanReversionStrategy(), {"SPY": make_features(rsi=None)}, range_mid_rsi()
        )
        assert proposal.reject_reasons == ("FEATURES_UNKNOWN",)
        assert proposal.target_exposure == {}


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
                assert proposal.strategy_version == "V2"  # V2: unified maps (B2)
                assert proposal.regime_labels_used == regime.labels
                assert proposal.asof_utc == ASOF
                assert proposal.info_refs_used == ()

    def test_propose_is_deterministic(self) -> None:
        for strategy in default_candidates():
            first = propose(strategy, {"SPY": make_features(rsi="25")}, range_low_rsi())
            second = propose(strategy, {"SPY": make_features(rsi="25")}, range_low_rsi())
            assert first == second
            assert first.target_exposure is not second.target_exposure  # fresh copies


# -- V0.2 multi-symbol semantics (B2) -----------------------------------------


def two_symbol_features() -> dict[str, FeatureVector]:
    """Neutral warm SPY + QQQ fixture pair."""
    return {"SPY": spy_features(), "QQQ": qqq_features()}


def trend_up_with_qqq(qqq: FeatureVector) -> RegimeAssessment:
    """Portfolio regime TREND_UP (from SPY); QQQ features ride along."""
    return make_regime(
        {"SPY": spy_features(ma_short="460", ma_long="450"), "QQQ": qqq}
    )


def range_with_qqq(spy: FeatureVector, qqq: FeatureVector) -> RegimeAssessment:
    """Portfolio regime RANGE (SPY inside its band) with per-symbol RSI."""
    return make_regime({"SPY": spy, "QQQ": qqq})


class TestMaCrossTrendMultiSymbol:
    """B2 proofs (a) and (b): per-symbol trend legs, no contamination."""

    def test_spy_uptrend_qqq_range_holds_spy_only(self) -> None:
        # (a) SPY TREND_UP + QQQ own RANGE -> SPY leg 1.0, QQQ leg 0.
        qqq = qqq_features()  # 350.2 vs 350: inside the per-symbol band
        regime = trend_up_with_qqq(qqq)
        proposal = propose(
            MaCrossTrendStrategy(),
            {"SPY": spy_features(ma_short="460", ma_long="450"), "QQQ": qqq},
            regime,
        )
        assert proposal.target_exposure == {"SPY": Decimal(1), "QQQ": Decimal(0)}
        assert proposal.reject_reasons == ()
        assert "spy=long@1" in proposal.rationale
        assert "qqq=NO_UPTREND" in proposal.rationale

    def test_both_uptrend_split_half_conserving(self) -> None:
        # Both legs qualify -> 0.5/0.5 (weight conservation, B2).
        spy = spy_features(ma_short="460", ma_long="450")
        qqq = qqq_features(ma_short="360", ma_long="350")
        proposal = propose(MaCrossTrendStrategy(), {"SPY": spy, "QQQ": qqq},
                           trend_up_with_qqq(qqq))
        assert proposal.target_exposure == {"SPY": Decimal("0.5"), "QQQ": Decimal("0.5")}
        assert sum(proposal.target_exposure.values()) == Decimal(1)

    def test_qqq_unknown_leg_zero_spy_unaffected(self) -> None:
        # (b) QQQ features UNKNOWN -> QQQ leg 0 with a recorded reason;
        # the SPY leg trades and there is NO cross-symbol contamination
        # (no global reject).
        spy = spy_features(ma_short="460", ma_long="450")
        qqq = qqq_features(status=STATUS_UNKNOWN, reasons=("NO_BARS",))
        proposal = propose(MaCrossTrendStrategy(), {"SPY": spy, "QQQ": qqq},
                           trend_up_with_qqq(qqq))
        assert proposal.target_exposure == {"SPY": Decimal(1), "QQQ": Decimal(0)}
        assert proposal.reject_reasons == ()
        assert "qqq=FEATURES_UNKNOWN" in proposal.rationale

    def test_qqq_own_downtrend_leg_flat(self) -> None:
        # Portfolio TREND_UP, QQQ own MA cross DOWN -> QQQ leg 0.
        spy = spy_features(ma_short="460", ma_long="450")
        qqq = qqq_features(ma_short="340", ma_long="350")
        proposal = propose(MaCrossTrendStrategy(), {"SPY": spy, "QQQ": qqq},
                           trend_up_with_qqq(qqq))
        assert proposal.target_exposure == {"SPY": Decimal(1), "QQQ": Decimal(0)}
        assert "qqq=NO_UPTREND" in proposal.rationale

    def test_all_symbols_unknown_fails_closed(self) -> None:
        features = {
            "SPY": spy_features(status=STATUS_UNKNOWN),
            "QQQ": qqq_features(status=STATUS_UNKNOWN),
        }
        proposal = propose(MaCrossTrendStrategy(), features, make_regime(features))
        assert proposal.target_exposure == {}
        assert proposal.reject_reasons == ("FEATURES_UNKNOWN",)

    def test_regime_unknown_fails_closed(self) -> None:
        proposal = propose(
            MaCrossTrendStrategy(),
            two_symbol_features(),
            make_regime({"SPY": spy_features(status=STATUS_UNKNOWN)}),
        )
        assert proposal.target_exposure == {}
        assert proposal.reject_reasons == ("FEATURES_UNKNOWN",)

    def test_both_legs_always_explicit(self) -> None:
        # Usable sessions name every traded leg explicitly (never silent).
        spy = spy_features(ma_short="460", ma_long="450")
        qqq = qqq_features()
        proposal = propose(MaCrossTrendStrategy(), {"SPY": spy, "QQQ": qqq},
                           trend_up_with_qqq(qqq))
        assert set(proposal.target_exposure) == set(TRADED_SYMBOLS)


class TestMeanReversionMultiSymbol:
    """B2 proof (d): mean reversion enters only the oversold symbol."""

    def test_enters_only_oversold_symbol(self) -> None:
        spy = spy_features(ma_short="450.2", ma_long="450", rsi="25")
        qqq = qqq_features(rsi="50")
        proposal = propose(MeanReversionStrategy(), {"SPY": spy, "QQQ": qqq},
                           range_with_qqq(spy, qqq))
        assert proposal.target_exposure == {"SPY": Decimal("0.5")}
        assert "QQQ" not in proposal.target_exposure  # mid-band flat = cash
        assert proposal.reject_reasons == ()

    def test_second_symbol_oversold_enters(self) -> None:
        spy = spy_features(ma_short="450.2", ma_long="450", rsi="60")
        qqq = qqq_features(rsi="25")
        proposal = propose(MeanReversionStrategy(), {"SPY": spy, "QQQ": qqq},
                           range_with_qqq(spy, qqq))
        assert proposal.target_exposure == {"SPY": Decimal(0), "QQQ": Decimal("0.5")}
        assert proposal.reject_reasons == ()

    def test_both_oversold_conserve_weights(self) -> None:
        spy = spy_features(ma_short="450.2", ma_long="450", rsi="25")
        qqq = qqq_features(rsi="25")
        proposal = propose(MeanReversionStrategy(), {"SPY": spy, "QQQ": qqq},
                           range_with_qqq(spy, qqq))
        assert proposal.target_exposure == {"SPY": Decimal("0.5"), "QQQ": Decimal("0.5")}
        assert sum(proposal.target_exposure.values()) == Decimal(1)

    def test_mid_band_holds_each_virtual_leg(self) -> None:
        spy = spy_features(ma_short="450.2", ma_long="450", rsi="45")
        qqq = qqq_features(rsi="45")
        proposal = propose(
            MeanReversionStrategy(), {"SPY": spy, "QQQ": qqq},
            range_with_qqq(spy, qqq),
            {"SPY": Decimal("0.5"), "QQQ": Decimal("0.5")},
        )
        assert proposal.target_exposure == {"SPY": Decimal("0.5"), "QQQ": Decimal("0.5")}
        assert proposal.reject_reasons == ()

    def test_unknown_rsi_leg_zero_other_trades(self) -> None:
        spy = spy_features(ma_short="450.2", ma_long="450", rsi="25")
        qqq = qqq_features(rsi=None)
        proposal = propose(MeanReversionStrategy(), {"SPY": spy, "QQQ": qqq},
                           range_with_qqq(spy, qqq))
        assert proposal.target_exposure == {"SPY": Decimal("0.5"), "QQQ": Decimal(0)}
        assert proposal.reject_reasons == ()
        assert "qqq=FEATURES_UNKNOWN" in proposal.rationale

    def test_unknown_rsi_held_leg_flattens_with_reject(self) -> None:
        # Data loss on a HELD leg: flatten visibly (reject), keep the
        # decidable leg trading.
        spy = spy_features(ma_short="450.2", ma_long="450", rsi="45")
        qqq = qqq_features(rsi=None)
        proposal = propose(
            MeanReversionStrategy(), {"SPY": spy, "QQQ": qqq},
            range_with_qqq(spy, qqq),
            {"SPY": Decimal("0.5"), "QQQ": Decimal("0.5")},
        )
        assert proposal.target_exposure == {"SPY": Decimal("0.5"), "QQQ": Decimal(0)}
        assert proposal.reject_reasons == ("FEATURES_UNKNOWN",)

    def test_all_rsi_unknown_fails_closed(self) -> None:
        spy = spy_features(ma_short="450.2", ma_long="450", rsi=None)
        qqq = qqq_features(rsi=None)
        proposal = propose(MeanReversionStrategy(), {"SPY": spy, "QQQ": qqq},
                           range_with_qqq(spy, qqq))
        assert proposal.target_exposure == {}
        assert proposal.reject_reasons == ("FEATURES_UNKNOWN",)

    def test_outside_range_exits_only_held_leg(self) -> None:
        spy = spy_features(ma_short="460", ma_long="450")
        qqq = qqq_features()
        proposal = propose(
            MeanReversionStrategy(), {"SPY": spy, "QQQ": qqq},
            make_regime({"SPY": spy, "QQQ": qqq}),  # TREND_UP: outside RANGE
            {"QQQ": Decimal("0.5")},
        )
        assert proposal.target_exposure == {"QQQ": Decimal(0)}
        assert proposal.reject_reasons == ("REGIME_MISMATCH",)


class TestHighVolDefensiveMultiSymbol:
    """B2 proof (c): HIGH_VOL sends BOTH legs to cash."""

    def test_high_vol_flattens_both_legs(self) -> None:
        features = {
            "SPY": spy_features(realized_vol="0.050"),
            "QQQ": qqq_features(realized_vol="0.050"),
        }
        proposal = propose(
            HighVolDefensiveStrategy(), features, high_vol(),
            {"SPY": Decimal(1), "QQQ": Decimal("0.5")},
        )
        assert proposal.target_exposure == {}
        assert proposal.reject_reasons == ()
        assert "both legs" in proposal.rationale

    def test_holds_both_virtual_legs_when_not_high_vol(self) -> None:
        virtual = {"SPY": Decimal("0.5"), "QQQ": Decimal("0.5")}  # conserving book
        proposal = propose(
            HighVolDefensiveStrategy(), two_symbol_features(),
            trend_up_with_qqq(qqq_features()), virtual,
        )
        assert proposal.target_exposure == {"SPY": Decimal("0.5"), "QQQ": Decimal("0.5")}
        assert proposal.reject_reasons == ()

    def test_primary_unknown_still_fails_closed(self) -> None:
        features = {"SPY": spy_features(status=STATUS_UNKNOWN), "QQQ": qqq_features()}
        proposal = propose(HighVolDefensiveStrategy(), features, make_regime(features))
        assert proposal.reject_reasons == ("FEATURES_UNKNOWN",)
        assert proposal.target_exposure == {}


class TestBuyHoldMultiSymbol:
    def test_both_warm_split_half(self) -> None:
        proposal = propose(
            BuyHoldStrategy(), two_symbol_features(), trend_up_with_qqq(qqq_features())
        )
        assert proposal.target_exposure == {"SPY": Decimal("0.5"), "QQQ": Decimal("0.5")}
        assert proposal.reject_reasons == ()
        assert "0.5/0.5" in proposal.rationale

    def test_single_symbol_warm_deploys_that_symbol(self) -> None:
        # QQQ cold -> full book on the warmed symbol (documented choice);
        # SPY-only fixtures keep V0.1 parity ({SPY: 1}).
        features = {"SPY": spy_features(), "QQQ": qqq_features(status=STATUS_UNKNOWN)}
        proposal = propose(BuyHoldStrategy(), features, trend_up_with_qqq(features["QQQ"]))
        assert proposal.target_exposure == {"SPY": Decimal(1)}
        assert proposal.reject_reasons == ()
        assert "single-symbol warmup" in proposal.rationale

    def test_qqq_only_warm_deploys_qqq(self) -> None:
        features = {"SPY": spy_features(warmup_ok=False), "QQQ": qqq_features()}
        proposal = propose(BuyHoldStrategy(), features, trend_up_with_qqq(qqq_features()))
        assert proposal.target_exposure == {"QQQ": Decimal(1)}
        assert proposal.reject_reasons == ()

    def test_none_warm_rejects(self) -> None:
        features = {
            "SPY": spy_features(warmup_ok=False),
            "QQQ": qqq_features(warmup_ok=False),
        }
        proposal = propose(BuyHoldStrategy(), features, trend_up_with_qqq(qqq_features()))
        assert proposal.target_exposure == {}
        assert proposal.reject_reasons == ("WARMUP_INCOMPLETE",)


class TestMultiSymbolProposalInvariants:
    """B2 proof (g): per-symbol bounds, weight conservation, validation."""

    def test_weights_bounded_and_conserving_on_two_symbol_fixtures(self) -> None:
        regimes = (
            trend_up_with_qqq(qqq_features(ma_short="360", ma_long="350")),
            range_with_qqq(
                spy_features(ma_short="450.2", ma_long="450", rsi="25"),
                qqq_features(rsi="25"),
            ),
            trend_up_with_qqq(qqq_features(status=STATUS_UNKNOWN)),
        )
        for regime in regimes:
            for strategy in default_candidates():
                proposal = propose(strategy, two_symbol_features(), regime)
                for symbol, weight in proposal.target_exposure.items():
                    assert symbol in TRADED_SYMBOLS
                    assert Decimal(0) <= weight <= Decimal(1)
                assert sum(proposal.target_exposure.values()) <= Decimal(1)

    def test_conservation_is_enforced(self) -> None:
        # A non-conserving virtual book cannot be held: _build fails closed.
        with pytest.raises(ValueError, match="conserve"):
            propose(
                HighVolDefensiveStrategy(),
                two_symbol_features(),
                trend_up_with_qqq(qqq_features()),
                {"SPY": Decimal(1), "QQQ": Decimal(1)},
            )

    def test_propose_is_deterministic_multi_symbol(self) -> None:
        features = {
            "SPY": spy_features(ma_short="460", ma_long="450", rsi="25"),
            "QQQ": qqq_features(ma_short="360", ma_long="350", rsi="25"),
        }
        regime = make_regime(features)
        for strategy in default_candidates():
            first = propose(strategy, features, regime)
            second = propose(strategy, features, regime)
            assert first == second
            assert first.target_exposure is not second.target_exposure
