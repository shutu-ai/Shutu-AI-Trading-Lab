"""Purpose-based data acceptance: evaluate quality + vendor facts against
pre-declared per-purpose thresholds from ``configs/data_acceptance.yaml``.

Verdicts follow the frozen vocabulary: ``ACCEPT`` / ``RESTRICT_SCOPE`` /
``REJECT`` / ``BLOCKED_DATA`` / ``INCONCLUSIVE``. Missing required config
fields are validation errors (thresholds must be declared *before* running,
never lowered after a failure). Every required threshold field must be
present and non-null — an absent threshold is a config defect, not a pass.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .quality import QualityReport

VERDICT_ACCEPT = "ACCEPT"
VERDICT_RESTRICT_SCOPE = "RESTRICT_SCOPE"
VERDICT_REJECT = "REJECT"
VERDICT_BLOCKED_DATA = "BLOCKED_DATA"
VERDICT_INCONCLUSIVE = "INCONCLUSIVE"


class DataAcceptanceConfigError(ValueError):
    pass


class PurposeRequirements(BaseModel):
    """One purpose's pre-declared requirements. Every threshold field is
    mandatory (``...`` defaults) — the config cannot be vague."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    purpose_id: str
    description: str
    data_scope: str                                  # e.g. "us_equities_daily"
    requires_daily_bars: bool
    requires_minute_bars: bool
    requires_corporate_actions: bool
    requires_history_membership: bool
    requires_delisting: bool
    available_at_rule: str                           # e.g. "bar_ts_plus_5min"
    max_missing_rate: float = Field(ge=0.0, le=1.0)
    min_coverage_rate: float = Field(ge=0.0, le=1.0)
    max_latency_seconds: int = Field(ge=0)
    required_license_scope: str                      # e.g. "personal_research"
    on_fail: str                                     # RESTRICT_SCOPE / REJECT / BLOCKED_DATA

    @field_validator("on_fail")
    @classmethod
    def _on_fail_vocabulary(cls, v: str) -> str:
        if v not in {VERDICT_RESTRICT_SCOPE, VERDICT_REJECT, VERDICT_BLOCKED_DATA}:
            raise DataAcceptanceConfigError(f"on_fail must be one of RESTRICT_SCOPE/REJECT/BLOCKED_DATA (got {v!r})")
        return v


class DataAcceptanceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: int
    purposes: tuple[PurposeRequirements, ...]

    def purpose(self, purpose_id: str) -> PurposeRequirements:
        for p in self.purposes:
            if p.purpose_id == purpose_id:
                return p
        raise DataAcceptanceConfigError(f"unknown purpose_id {purpose_id!r}")


def load_acceptance_config(path: str | Path) -> DataAcceptanceConfig:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    try:
        cfg = DataAcceptanceConfig.model_validate(raw)
    except ValidationError as exc:
        # Every config fault (missing threshold, wrong vocabulary, unknown
        # field) is one error type so callers fail closed uniformly.
        raise DataAcceptanceConfigError(f"invalid data_acceptance config: {exc}") from exc
    if not cfg.purposes:
        raise DataAcceptanceConfigError("data_acceptance.yaml must declare at least one purpose")
    return cfg


@dataclass(frozen=True)
class VendorFacts:
    """Trusted, evidence-backed answers about a vendor for the required
    coverage dimensions — sourced from data-vendors.md, not from marketing."""

    license_scope: str                       # e.g. "personal_research" / "unknown"
    license_confirmed: bool                  # False = terms not verified
    history_membership_coverage: str         # yes / no / unknown
    delisting_coverage: str                  # yes / no / unknown
    corporate_actions_coverage: str          # yes / no / unknown
    pit_availability: str                    # event_level / eod_only / none / unknown


@dataclass(frozen=True)
class AcceptanceDecision:
    purpose_id: str
    verdict: str
    reasons: tuple[str, ...]


def evaluate_purpose(
    requirements: PurposeRequirements,
    quality: QualityReport,
    vendor: VendorFacts,
) -> AcceptanceDecision:
    """Judge one purpose. Order of assessment:

    1. structural data failures (zero denominators etc.) -> INCONCLUSIVE
       when the data itself could not be observed at all;
    2. unconfirmed license -> BLOCKED_DATA (never guess permission);
    3. required coverage dimensions unknown -> BLOCKED_DATA;
    4. required coverage absent -> the declared ``on_fail`` verdict;
    5. quality thresholds violated -> the declared ``on_fail`` verdict;
    6. everything satisfied -> ACCEPT.
    """
    reasons: list[str] = []

    inconclusive = any(m.is_inconclusive for m in quality.field_coverage) or (
        quality.bar_completeness.is_inconclusive
    )
    if inconclusive and quality.bar_completeness.denominator == 0:
        return AcceptanceDecision(
            requirements.purpose_id,
            VERDICT_INCONCLUSIVE,
            ("ZERO_DENOMINATOR:bar_completeness",) + tuple(quality.failures(
                requirements.max_missing_rate, requirements.max_latency_seconds
            )),
        )

    if not vendor.license_confirmed:
        reasons.append(f"LICENSE_UNCONFIRMED:{vendor.license_scope}")
    if requirements.required_license_scope != vendor.license_scope:
        if vendor.license_confirmed:
            reasons.append(
                f"LICENSE_SCOPE_MISMATCH:required={requirements.required_license_scope},"
                f"vendor={vendor.license_scope}"
            )

    coverage_map = {
        "requires_history_membership": ("history_membership_coverage", "HISTORY_MEMBERSHIP"),
        "requires_delisting": ("delisting_coverage", "DELISTING"),
        "requires_corporate_actions": ("corporate_actions_coverage", "CORPORATE_ACTIONS"),
    }
    for req_field, (vendor_field, label) in coverage_map.items():
        if not getattr(requirements, req_field):
            continue
        value = getattr(vendor, vendor_field)
        if value == "unknown":
            reasons.append(f"{label}_COVERAGE_UNKNOWN")
        elif value != "yes":
            reasons.append(f"{label}_COVERAGE_ABSENT")

    if requirements.available_at_rule != "bar_ts_plus_0" and (
        quality.unknown_availability_count > 0
    ):
        reasons.append(
            f"UNKNOWN_AVAILABILITY_PRESENT:{quality.unknown_availability_count}"
        )

    # Hard blockers first: license/coverage unknowns are BLOCKED_DATA by
    # definition — we cannot even test them.
    hard_blockers = (
        "LICENSE_UNCONFIRMED",
        "HISTORY_MEMBERSHIP_COVERAGE_UNKNOWN",
        "DELISTING_COVERAGE_UNKNOWN",
        "CORPORATE_ACTIONS_COVERAGE_UNKNOWN",
    )
    if any(r.startswith(hard_blockers) for r in reasons):
        return AcceptanceDecision(requirements.purpose_id, VERDICT_BLOCKED_DATA, tuple(reasons))

    failures = [
        f for f in quality.failures(
            requirements.max_missing_rate, requirements.max_latency_seconds
        )
        if not f.startswith(("LATENCY_SAMPLES", "UNKNOWN_AVAILABILITY"))
    ]
    if requirements.max_latency_seconds is not None:
        lat = quality.latency
        if lat.is_inconclusive:
            reasons.append("LATENCY_INCONCLUSIVE:no_samples")
        elif lat.max_seconds is not None and lat.max_seconds > requirements.max_latency_seconds:
            pass  # already inside failures via QualityReport
    if failures:
        reasons.extend(failures)
        return AcceptanceDecision(requirements.purpose_id, requirements.on_fail, tuple(reasons))

    if reasons:
        return AcceptanceDecision(requirements.purpose_id, requirements.on_fail, tuple(reasons))

    return AcceptanceDecision(requirements.purpose_id, VERDICT_ACCEPT, ())


__all__ = [
    "AcceptanceDecision",
    "DataAcceptanceConfig",
    "DataAcceptanceConfigError",
    "PurposeRequirements",
    "VendorFacts",
    "evaluate_purpose",
    "load_acceptance_config",
]
