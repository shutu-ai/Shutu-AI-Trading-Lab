"""Tests for the rule-based regime classifier (B3, MOCK_ONLY).

All fixtures are hand-made deterministic ``FeatureVector`` objects — no
dependency on the concurrent features/information-plane workstreams.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping, Sequence

from trading_lab.business.config import RegimeConfig
from trading_lab.business.regime import (
    LABEL_EVENT_ACTIVE,
    LABEL_HIGH_VOL,
    LABEL_RANGE,
    LABEL_TREND_DOWN,
    LABEL_TREND_UP,
    LABEL_UNKNOWN,
    PRIMARY_SYMBOL,
    MODEL_VERSION,
    InformationAssessmentView,
    RegimeClassifierSession,
    RuleRegimeClassifier,
)
from trading_lab.business.types import STATUS_OK, STATUS_UNKNOWN, FeatureVector
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
    feature_hash: str | None = None,
) -> FeatureVector:
    """Hand-made deterministic primary-symbol feature fixture."""
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
        feature_hash=(
            feature_hash
            if feature_hash is not None
            else canonical_digest(
                {"sym": PRIMARY_SYMBOL, "ma_s": ma_short, "ma_l": ma_long, "asof": ASOF.isoformat()}
            )
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


def make_classifier() -> RuleRegimeClassifier:
    return RuleRegimeClassifier(RegimeConfig())


def classify(
    features: Mapping,
    *,
    info: Sequence[InformationAssessmentView] = (),
    vol_history: Sequence[Decimal] = (),
) -> RegimeAssessment:
    return make_classifier().classify(ASOF, features, info, None, vol_history, VALID_UNTIL)


class TestTrendRules:
    def test_trend_up_detected(self) -> None:
        assessment = classify({"SPY": make_features(ma_short="460", ma_long="450")})
        assert assessment.labels == (LABEL_TREND_UP,)
        # |spread|/band = 22.8 >> 1 -> full strength gain: 0.60 + 0.20.
        assert assessment.confidence == 0.8

    def test_trend_down_detected(self) -> None:
        assessment = classify({"SPY": make_features(ma_short="440", ma_long="450")})
        assert assessment.labels == (LABEL_TREND_DOWN,)
        assert assessment.confidence == 0.8

    def test_range_inside_band(self) -> None:
        assessment = classify({"SPY": make_features(ma_short="450.2", ma_long="450")})
        assert assessment.labels == (LABEL_RANGE,)

    def test_band_boundaries(self) -> None:
        # spread 0.0011111 > 0.001 -> TREND_UP; 0.0009893 <= 0.001 -> RANGE.
        up = classify({"SPY": make_features(ma_short="450.5", ma_long="450")})
        assert up.labels == (LABEL_TREND_UP,)
        inside = classify({"SPY": make_features(ma_short="450.4452", ma_long="450")})
        assert inside.labels == (LABEL_RANGE,)


class TestHighVolRule:
    def test_above_percentile_flags_high_vol(self) -> None:
        history = [Decimal("0.001") * i for i in range(1, 61)]  # 60 values
        features = make_features(realized_vol="0.050", ma_short="460", ma_long="450")
        assessment = classify({"SPY": features}, vol_history=history)
        # Nearest-rank p80 of 60 values -> sorted[47] = 0.048; 0.050 > 0.048.
        assert LABEL_HIGH_VOL in assessment.labels
        assert assessment.labels == (LABEL_TREND_UP, LABEL_HIGH_VOL)

    def test_at_percentile_does_not_flag(self) -> None:
        history = [Decimal("0.001") * i for i in range(1, 61)]
        features = make_features(realized_vol="0.048", ma_short="460", ma_long="450")
        assessment = classify({"SPY": features}, vol_history=history)
        assert LABEL_HIGH_VOL not in assessment.labels

    def test_insufficient_history_means_no_label_no_error(self) -> None:
        history = [Decimal("0.001")] * 59  # below min_history_for_vol_percentile=60
        features = make_features(realized_vol="1.0", ma_short="460", ma_long="450")
        assessment = classify({"SPY": features}, vol_history=history)
        assert LABEL_HIGH_VOL not in assessment.labels
        assert assessment.labels == (LABEL_TREND_UP,)

    def test_lookback_window_only_last_values(self) -> None:
        history = [Decimal("0.001") * (i + 1) for i in range(130)]  # 0.001 .. 0.130
        features = make_features(realized_vol="0.107", ma_short="460", ma_long="450")
        assessment = classify({"SPY": features}, vol_history=history)
        # Last 120 values are 0.011..0.130; p80 nearest rank -> 0.106.
        assert LABEL_HIGH_VOL in assessment.labels


class TestEventRule:
    def test_assessed_short_bearish_activates(self) -> None:
        info = [InfoStub("EV-1", direction="BEARISH", confidence=0.9)]
        assessment = classify({"SPY": make_features()}, info=info)
        assert assessment.labels == (LABEL_RANGE, LABEL_EVENT_ACTIVE)

    def test_below_confidence_floor_inactive(self) -> None:
        info = [InfoStub("EV-1", direction="BEARISH", confidence=0.54)]
        assessment = classify({"SPY": make_features()}, info=info)
        assert LABEL_EVENT_ACTIVE not in assessment.labels

    def test_unknown_direction_inactive(self) -> None:
        info = [InfoStub("EV-1", direction="UNKNOWN", confidence=0.9)]
        assessment = classify({"SPY": make_features()}, info=info)
        assert LABEL_EVENT_ACTIVE not in assessment.labels

    def test_non_short_horizon_inactive(self) -> None:
        info = [InfoStub("EV-1", direction="BEARISH", confidence=0.9, horizon="MEDIUM")]
        assessment = classify({"SPY": make_features()}, info=info)
        assert LABEL_EVENT_ACTIVE not in assessment.labels

    def test_unassessed_status_inactive(self) -> None:
        info = [InfoStub("EV-1", status="UNKNOWN", direction="BEARISH", confidence=0.9)]
        assessment = classify({"SPY": make_features()}, info=info)
        assert LABEL_EVENT_ACTIVE not in assessment.labels

    def test_bullish_direction_also_activates(self) -> None:
        info = [InfoStub("EV-1", direction="BULLISH", confidence=0.9)]
        assessment = classify({"SPY": make_features()}, info=info)
        assert LABEL_EVENT_ACTIVE in assessment.labels


class TestUnknownFailSafe:
    def test_unknown_features_fail_safe(self) -> None:
        features = {"SPY": make_features(status=STATUS_UNKNOWN, reasons=("NO_BARS",))}
        assessment = classify(features)
        assert assessment.labels == (LABEL_UNKNOWN,)
        assert assessment.confidence == 0.0
        assert assessment.model_version == MODEL_VERSION

    def test_missing_primary_symbol_fail_safe(self) -> None:
        assessment = classify({"QQQ": make_features()})
        assert assessment.labels == (LABEL_UNKNOWN,)
        assert assessment.confidence == 0.0

    def test_unknown_feature_hash_digests_reasons(self) -> None:
        features = {"SPY": make_features(status=STATUS_UNKNOWN, reasons=("NO_BARS",))}
        assessment = classify(features)
        expected = canonical_digest({"reasons": ["PRIMARY_FEATURES_UNUSABLE", "NO_BARS"]})
        assert assessment.feature_hash == expected
        assert re.fullmatch(r"[0-9a-f]{64}", assessment.feature_hash)


class TestContractConstruction:
    def test_ok_assessment_passes_pydantic_validation(self) -> None:
        assessment = classify({"SPY": make_features(ma_short="460", ma_long="450")})
        rebuilt = RegimeAssessment.model_validate(dict(assessment))
        assert rebuilt.labels == (LABEL_TREND_UP,)
        assert rebuilt.labels  # non-empty
        assert 0.0 <= rebuilt.confidence <= 1.0
        assert re.fullmatch(r"[0-9a-fA-F]{16,64}", rebuilt.feature_hash)
        assert rebuilt.model_version == MODEL_VERSION

    def test_unknown_assessment_passes_pydantic_validation(self) -> None:
        assessment = classify({"SPY": make_features(status=STATUS_UNKNOWN)})
        rebuilt = RegimeAssessment.model_validate(dict(assessment))
        assert rebuilt.labels == (LABEL_UNKNOWN,)
        assert rebuilt.confidence == 0.0

    def test_feature_hash_taken_from_feature_vector(self) -> None:
        features = make_features(feature_hash="abcdef0123456789")
        assessment = classify({"SPY": features})
        assert assessment.feature_hash == "abcdef0123456789"

    def test_fallback_hash_when_feature_hash_missing(self) -> None:
        features = make_features(feature_hash="")
        assessment = classify({"SPY": features})
        assert re.fullmatch(r"[0-9a-f]{64}", assessment.feature_hash)


class TestPurityAndDeterminism:
    def test_classify_is_deterministic(self) -> None:
        features = {"SPY": make_features(ma_short="460", ma_long="450")}
        first = classify(features)
        second = classify(features)
        assert first == second

    def test_previous_argument_does_not_change_output(self) -> None:
        features = {"SPY": make_features(ma_short="460", ma_long="450")}
        previous = classify({"SPY": make_features(ma_short="440", ma_long="450")})
        with_previous = make_classifier().classify(
            ASOF, features, (), previous, (), VALID_UNTIL
        )
        without_previous = classify(features)
        assert with_previous == without_previous


def up_features() -> dict[str, FeatureVector]:
    return {"SPY": make_features(ma_short="460", ma_long="450")}


def range_features() -> dict[str, FeatureVector]:
    return {"SPY": make_features(ma_short="450.2", ma_long="450")}


def lost_features() -> dict[str, FeatureVector]:
    return {"SPY": make_features(status=STATUS_UNKNOWN, reasons=("NO_BARS",))}


def run_sessions(
    classifier: RuleRegimeClassifier,
    sequence: Sequence[dict[str, FeatureVector]],
) -> list[RegimeAssessment]:
    session = RegimeClassifierSession(classifier)
    return [
        session.step(ASOF, features, (), (), VALID_UNTIL) for features in sequence
    ]


class TestHysteresis:
    def test_first_observation_commits_immediately(self) -> None:
        outputs = run_sessions(make_classifier(), [up_features()])
        assert outputs[0].labels == (LABEL_TREND_UP,)

    def test_single_session_flutter_does_not_flip(self) -> None:
        outputs = run_sessions(
            make_classifier(),
            [up_features(), range_features(), up_features(), range_features()],
        )
        assert all(out.labels == (LABEL_TREND_UP,) for out in outputs)

    def test_sustained_three_session_change_flips(self) -> None:
        outputs = run_sessions(
            make_classifier(),
            [up_features(), range_features(), range_features(), range_features()],
        )
        assert outputs[0].labels == (LABEL_TREND_UP,)
        assert outputs[1].labels == (LABEL_TREND_UP,)  # pending 1
        assert outputs[2].labels == (LABEL_TREND_UP,)  # pending 2
        assert outputs[3].labels == (LABEL_RANGE,)  # pending 3 -> committed

    def test_data_loss_flips_immediately_and_resets_pending(self) -> None:
        outputs = run_sessions(
            make_classifier(),
            [
                up_features(),
                range_features(),  # flutter starts pending
                lost_features(),  # data loss: immediate UNKNOWN
                range_features(),  # pending restarts at 1
                range_features(),
                range_features(),  # third consecutive -> RANGE commits
            ],
        )
        assert outputs[0].labels == (LABEL_TREND_UP,)
        assert outputs[1].labels == (LABEL_TREND_UP,)
        assert outputs[2].labels == (LABEL_UNKNOWN,)
        assert outputs[2].confidence == 0.0
        assert outputs[3].labels == (LABEL_UNKNOWN,)
        assert outputs[4].labels == (LABEL_UNKNOWN,)
        assert outputs[5].labels == (LABEL_RANGE,)

    def test_recovery_from_unknown_requires_sustained_data(self) -> None:
        outputs = run_sessions(
            make_classifier(),
            [
                lost_features(),
                up_features(),  # pending 1
                range_features(),  # flutter resets pending
                up_features(),  # pending 1 again
                up_features(),  # pending 2
                up_features(),  # pending 3 -> TREND_UP commits
            ],
        )
        assert outputs[0].labels == (LABEL_UNKNOWN,)
        assert outputs[1].labels == (LABEL_UNKNOWN,)
        assert outputs[2].labels == (LABEL_UNKNOWN,)
        assert outputs[3].labels == (LABEL_UNKNOWN,)
        assert outputs[4].labels == (LABEL_UNKNOWN,)
        assert outputs[5].labels == (LABEL_TREND_UP,)

    def test_held_regime_refreshes_timestamps_and_hash(self) -> None:
        classifier = make_classifier()
        session = RegimeClassifierSession(classifier)
        first = session.step(ASOF, up_features(), (), (), VALID_UNTIL)
        later_asof = ASOF + dt.timedelta(days=1)
        held = session.step(later_asof, range_features(), (), (), VALID_UNTIL)
        assert held.labels == (LABEL_TREND_UP,)  # held through flutter
        assert held.asof_utc == later_asof  # timestamps refreshed
        assert held.valid_until == VALID_UNTIL
        assert held.confidence == first.confidence  # held confidence

    def test_session_replay_is_deterministic(self) -> None:
        sequence = [
            up_features(),
            range_features(),
            lost_features(),
            range_features(),
            range_features(),
            range_features(),
        ]
        first = run_sessions(make_classifier(), sequence)
        second = run_sessions(make_classifier(), sequence)
        assert [out.labels for out in first] == [out.labels for out in second]
        assert [out.confidence for out in first] == [out.confidence for out in second]
        assert [out.feature_hash for out in first] == [out.feature_hash for out in second]
