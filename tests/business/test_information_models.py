"""Model tests for the business-internal information models
(``InformationEvent`` / ``InformationAssessment`` in
``trading_lab.business.models``): round-trip acceptance, validator
refusals for every shape that could smuggle look-ahead or unbounded
reads past the replay layer, and the enum vocabulary. These are
business-plane internal objects — deliberately NOT §2.2 contracts, so
that the frozen M3-R2 research code identity over ``contracts`` stays
reproducible.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import math
from pathlib import Path

import pytest
from pydantic import ValidationError

from trading_lab.business.models import (  # noqa: E402
    InformationAssessment,
    InformationDirection,
    InformationEvent,
    InformationHorizon,
    InformationStatus,
    InformationUncertainty,
)

EVENT_AT = dt.datetime(2026, 9, 8, 14, 0, tzinfo=dt.timezone.utc)
PUBLISHED_AT = EVENT_AT + dt.timedelta(minutes=15)
AVAILABLE_AT = EVENT_AT + dt.timedelta(minutes=35)
RECEIVED_AT = EVENT_AT + dt.timedelta(minutes=40)

CONTENT = "Acme beats quarterly expectations and raises guidance."
NOW = dt.datetime(2026, 9, 8, 21, 5, tzinfo=dt.timezone.utc)
VALID_UNTIL = NOW + dt.timedelta(hours=6)


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def valid_event(**over):
    base = dict(
        event_id="EVT-TEST-001",
        asset="SPY",
        source="unit-fixture",
        source_url="https://fixture.invalid/acme",
        event_at_utc=EVENT_AT,
        published_at_utc=PUBLISHED_AT,
        available_at_utc=AVAILABLE_AT,
        received_at_utc=RECEIVED_AT,
        content=CONTENT,
        content_hash=content_hash(CONTENT),
    )
    base.update(over)
    return base


def valid_assessment(**over):
    base = dict(
        assessment_id="EVT-TEST-001::RULE:v1",
        event_id="EVT-TEST-001",
        asset="SPY",
        category="EARNINGS",
        direction=InformationDirection.BULLISH,
        uncertainty=InformationUncertainty.LOW,
        horizon=InformationHorizon.UNKNOWN,
        confidence=0.65,
        evidence_ref="EVT-TEST-001#offset0-32",
        analyzer="RULE:v1",
        analyzer_version="v1",
        valid_until=VALID_UNTIL,
        assessed_at=NOW,
        status=InformationStatus.ASSESSED,
    )
    base.update(over)
    return base


class TestInformationEvent:
    def test_valid_construction_and_utc_normalization(self):
        event = InformationEvent(**valid_event())
        assert event.received_at_utc.utcoffset() == dt.timedelta(0)

    def test_json_round_trip(self):
        event = InformationEvent(**valid_event())
        restored = InformationEvent.model_validate_json(event.model_dump_json())
        assert restored == event
        assert restored.available_at_utc == AVAILABLE_AT

    def test_non_utc_offset_normalized(self):
        est = dt.timezone(dt.timedelta(hours=-4))
        event = InformationEvent(
            **valid_event(event_at_utc=EVENT_AT.astimezone(est)))
        assert event.event_at_utc == EVENT_AT

    def test_published_before_event_rejected(self):
        with pytest.raises(ValidationError):
            InformationEvent(**valid_event(
                published_at_utc=EVENT_AT - dt.timedelta(minutes=1)))

    def test_available_before_published_rejected(self):
        with pytest.raises(ValidationError):
            InformationEvent(**valid_event(
                available_at_utc=EVENT_AT))

    def test_received_before_available_rejected(self):
        with pytest.raises(ValidationError):
            InformationEvent(**valid_event(
                received_at_utc=EVENT_AT + dt.timedelta(minutes=30)))

    def test_empty_content_rejected(self):
        with pytest.raises(ValidationError):
            InformationEvent(**valid_event(content=""))

    def test_unknown_field_rejected(self):
        bad = valid_event()
        bad["leak"] = "insider hint"
        with pytest.raises(ValidationError):
            InformationEvent(**bad)

    def test_naive_timestamp_rejected(self):
        with pytest.raises(ValidationError):
            InformationEvent(
                **valid_event(event_at_utc=dt.datetime(2026, 9, 8, 14, 0)))

    def test_frozen(self):
        event = InformationEvent(**valid_event())
        with pytest.raises(Exception):
            event.content = "mutated"  # type: ignore[misc]


class TestInformationAssessment:
    def test_valid_construction(self):
        assessment = InformationAssessment(**valid_assessment())
        assert assessment.direction is InformationDirection.BULLISH
        assert assessment.status is InformationStatus.ASSESSED

    def test_json_round_trip_preserves_enums(self):
        assessment = InformationAssessment(**valid_assessment())
        restored = InformationAssessment.model_validate_json(
            assessment.model_dump_json())
        assert restored == assessment
        assert restored.status is InformationStatus.ASSESSED
        assert restored.direction is InformationDirection.BULLISH

    @pytest.mark.parametrize("confidence", [1.5, -0.1, float("nan")])
    def test_bad_confidence_rejected(self, confidence):
        with pytest.raises(ValidationError):
            InformationAssessment(
                **valid_assessment(confidence=confidence))

    def test_confidence_boundary_values_accepted(self):
        for value in (0.0, 1.0):
            InformationAssessment(**valid_assessment(confidence=value))

    def test_valid_until_before_assessed_at_rejected(self):
        with pytest.raises(ValidationError):
            InformationAssessment(**valid_assessment(
                valid_until=NOW - dt.timedelta(minutes=1)))

    def test_valid_until_equal_assessed_at_accepted(self):
        InformationAssessment(**valid_assessment(valid_until=NOW))

    def test_unknown_direction_value_rejected(self):
        with pytest.raises(ValidationError):
            InformationAssessment(**valid_assessment(direction="SIDEWAYS"))

    def test_unknown_field_rejected(self):
        bad = valid_assessment()
        bad["model_text"] = "you should buy now"
        with pytest.raises(ValidationError):
            InformationAssessment(**bad)

    def test_frozen(self):
        assessment = InformationAssessment(**valid_assessment())
        with pytest.raises(Exception):
            assessment.confidence = 0.99  # type: ignore[misc]


class TestEnumVocabulary:
    def test_direction_vocab(self):
        assert {m.value for m in InformationDirection} == {
            "BULLISH", "BEARISH", "NEUTRAL", "UNKNOWN"}

    def test_uncertainty_vocab(self):
        assert {m.value for m in InformationUncertainty} == {
            "LOW", "MEDIUM", "HIGH", "UNKNOWN"}

    def test_horizon_vocab(self):
        assert {m.value for m in InformationHorizon} == {
            "SHORT", "MEDIUM", "LONG", "UNKNOWN"}

    def test_status_vocab(self):
        assert {m.value for m in InformationStatus} == {
            "ASSESSED", "UNKNOWN", "REFUSED"}

    def test_nan_confidence_is_rejected_not_compared(self):
        assert math.isnan(float("nan"))
        with pytest.raises(ValidationError):
            InformationAssessment(
                **valid_assessment(confidence=float("nan")))
