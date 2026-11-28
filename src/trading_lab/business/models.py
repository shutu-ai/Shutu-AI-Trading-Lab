"""Business-internal information models (NOT §2.2 cross-plane contracts).

The Business MVP's information-analysis objects live INSIDE the business
package on purpose: the M3-R2 frozen research evidence binds a code
identity over the formal ``trading_lab.contracts`` package, so anything
added there permanently forks that identity (the identity regression
tests fail loudly — by design). Only the business plane consumes these
models; they reuse the contract TYPE ALIASES (UtcDatetime / HexHash /
NonEmptyStr, imported without modifying the frozen package) and the same
contract style, but carry no §2.2 standing. If information contracts are
ever promoted to cross-plane contracts, that is a formal contract-change
process decision — not a business-layer edit.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

from trading_lab.contracts.events import HexHash, NonEmptyStr, UtcDatetime

__all__ = [
    "InformationDirection",
    "InformationHorizon",
    "InformationStatus",
    "InformationUncertainty",
    "InformationEvent",
    "InformationAssessment",
]


class InformationDirection(StrEnum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"
    UNKNOWN = "UNKNOWN"


class InformationUncertainty(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    UNKNOWN = "UNKNOWN"


class InformationHorizon(StrEnum):
    SHORT = "SHORT"
    MEDIUM = "MEDIUM"
    LONG = "LONG"
    UNKNOWN = "UNKNOWN"


class InformationStatus(StrEnum):
    ASSESSED = "ASSESSED"
    UNKNOWN = "UNKNOWN"
    REFUSED = "REFUSED"


class _BusinessContract(BaseModel):
    """Same closed-world style as §2.2 contracts (frozen/strict/strict-extra)."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True,
                              validate_default=True)


class InformationEvent(_BusinessContract):
    event_id: NonEmptyStr
    asset: NonEmptyStr
    source: NonEmptyStr
    source_url: NonEmptyStr
    event_at_utc: UtcDatetime
    published_at_utc: UtcDatetime
    available_at_utc: UtcDatetime
    received_at_utc: UtcDatetime
    content: Annotated[str, Field(min_length=1)]
    content_hash: HexHash

    @model_validator(mode="after")
    def _pit_order(self) -> "InformationEvent":
        if self.published_at_utc < self.event_at_utc:
            raise ValueError("published_at must not precede event_at")
        if self.available_at_utc < self.published_at_utc:
            raise ValueError("available_at must not precede published_at")
        if self.received_at_utc < self.available_at_utc:
            raise ValueError("received_at must not precede available_at")
        return self


class InformationAssessment(_BusinessContract):
    assessment_id: NonEmptyStr
    event_id: NonEmptyStr
    asset: NonEmptyStr
    category: NonEmptyStr  # EARNINGS / MACRO / ANNOUNCEMENT / OTHER
    direction: InformationDirection
    uncertainty: InformationUncertainty
    horizon: InformationHorizon
    confidence: float
    evidence_ref: NonEmptyStr
    analyzer: NonEmptyStr          # e.g. "RULE:v1" / "LLM:mock:v1"
    analyzer_version: NonEmptyStr
    valid_until: UtcDatetime
    assessed_at: UtcDatetime
    status: InformationStatus

    @model_validator(mode="after")
    def _window(self) -> "InformationAssessment":
        if self.assessed_at > self.valid_until:
            raise ValueError("assessed_at must not exceed valid_until")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be within [0, 1]")
        return self
