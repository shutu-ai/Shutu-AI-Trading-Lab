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
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from .quality import QualityReport

VERDICT_ACCEPT = "ACCEPT"
VERDICT_RESTRICT_SCOPE = "RESTRICT_SCOPE"
VERDICT_REJECT = "REJECT"
VERDICT_BLOCKED_DATA = "BLOCKED_DATA"
VERDICT_INCONCLUSIVE = "INCONCLUSIVE"


class DataAcceptanceConfigError(ValueError):
    pass


class VendorFactsError(DataAcceptanceConfigError):
    """A VendorFacts capability field carries an illegal vocabulary value.

    Fail-closed by design (M1 U-1, fixed under the S8 read-only approval of
    2026-11-22): before this guard, an out-of-vocabulary string such as a
    vendor marketing claim (``"PIT-ready (marketing claim)"``, ``"partially"``,
    ``"YES"``) constructed fine and slipped past every ``==`` check in
    :func:`evaluate_purpose` into ``ACCEPT``. There is no fallback to
    "capable": an unparseable capability claim is a blocked/failed fact,
    never an optimistic one."""



class PurposeRequirements(BaseModel):
    """One purpose's pre-declared requirements. Every threshold field is
    mandatory (``...`` defaults) — the config cannot be vague.

    Threshold semantics (single authoritative formula, R2):
    ``coverage_rate = observed / denominator`` and
    ``missing_rate = missing / denominator`` with zero denominator ->
    INCONCLUSIVE. ``min_coverage_rate`` must be >= the complement of
    ``max_missing_rate`` (equal = same strictness, larger = stricter);
    a looser value would be dead/misleading config and is rejected at load.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    purpose_id: str
    description: str
    data_scope: str                                  # e.g. "us_equities_daily"
    requires_daily_bars: bool
    requires_minute_bars: bool
    requires_corporate_actions: bool
    requires_history_membership: bool
    requires_delisting: bool
    available_at_rule: str                           # vocabulary-validated below
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

    @field_validator("available_at_rule")
    @classmethod
    def _rule_vocabulary(cls, v: str) -> str:
        """Free-text rules silently widen admission on typos (R1); the rule
        must be one of the known vocabulary values."""
        if v not in AVAILABLE_AT_RULES:
            raise DataAcceptanceConfigError(
                f"available_at_rule must be one of {sorted(AVAILABLE_AT_RULES)} (got {v!r})"
            )
        return v

    @model_validator(mode="after")
    def _threshold_consistency(self) -> "PurposeRequirements":
        if self.min_coverage_rate + self.max_missing_rate < 1.0 - 1e-9:
            raise DataAcceptanceConfigError(
                f"inconsistent thresholds for {self.purpose_id}: min_coverage_rate="
                f"{self.min_coverage_rate} is looser than 1 - max_missing_rate="
                f"{1 - self.max_missing_rate:.6f} (dead/misleading config)"
            )
        return self


AVAILABLE_AT_RULES = frozenset({"bar_ts_plus_0", "bar_ts_plus_15min", "announced_or_published_before_use"})
_EVENT_LEVEL_RULES = frozenset({"announced_or_published_before_use"})

# M1 U-1: closed vocabularies for VendorFacts capability fields (S8-T1).
# These are the ONLY values evaluate_purpose's frozen comparison matrix
# understands; anything else is a malformed fact, not a capability.
COVERAGE_FACT_VALUES = frozenset({"yes", "no", "unknown"})
PIT_AVAILABILITY_VALUES = frozenset({"event_level", "eod_only", "none", "unknown"})


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
    coverage dimensions — sourced from data-vendors.md, not from marketing.

    The capability fields are **closed vocabularies** (M1 U-1 fix,
    S8-T1 RED->GREEN, approval record
    ``artifacts/evidence/M3.5/s8/authorization-check.md``):

    - ``history_membership_coverage`` / ``delisting_coverage`` /
      ``corporate_actions_coverage`` ∈ ``{yes, no, unknown}``
    - ``pit_availability`` ∈ ``{event_level, eod_only, none, unknown}``

    Any other value — including casing variants, marketing strings,
    whitespace padding, ``None`` or non-string types — raises
    :class:`VendorFactsError` at construction, before any admission
    decision can be influenced by it. ``evaluate_purpose`` keeps its
    frozen semantics: ``unknown`` -> BLOCKED_DATA, known-absent ->
    ``on_fail``."""

    license_scope: str                       # e.g. "personal_research" / "unknown"
    license_confirmed: bool                  # False = terms not verified
    history_membership_coverage: str         # yes / no / unknown
    delisting_coverage: str                  # yes / no / unknown
    corporate_actions_coverage: str          # yes / no / unknown
    pit_availability: str                    # event_level / eod_only / none / unknown

    def __post_init__(self) -> None:
        for name in ("history_membership_coverage",
                     "delisting_coverage",
                     "corporate_actions_coverage"):
            value = getattr(self, name)
            if value not in COVERAGE_FACT_VALUES:
                raise VendorFactsError(
                    f"VendorFacts.{name}={value!r} is outside the closed "
                    f"vocabulary {sorted(COVERAGE_FACT_VALUES)} — fail "
                    "closed, no optimistic fallback (M1 U-1)")
        if self.pit_availability not in PIT_AVAILABILITY_VALUES:
            raise VendorFactsError(
                f"VendorFacts.pit_availability={self.pit_availability!r} is "
                f"outside the closed vocabulary "
                f"{sorted(PIT_AVAILABILITY_VALUES)} — fail closed, no "
                "optimistic fallback (M1 U-1)")


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
    """Judge one purpose. The assessment order is **frozen** (R2: the same
    facts must always yield the same verdict regardless of check order):

    1. unconfirmed license -> BLOCKED_DATA (hard blocker);
    2. unknown PIT capability or unknown required coverage -> BLOCKED_DATA
       (untestable facts are never optimistic);
    3. zero denominators (fields / bars) or zero latency samples ->
       INCONCLUSIVE (nothing observed, nothing claimed);
    4. PIT capability matrix vs the purpose's time rule -> on_fail
       (known-absent or insufficient granularity);
    5. required coverage known-absent -> on_fail;
    6. quality thresholds violated -> on_fail;
    7. all satisfied -> ACCEPT.

    ALLOW_PORTFOLIO-style caveats apply here too: ACCEPT is a data-admission
    verdict for this purpose only, never a research-results claim.
    """
    reasons: list[str] = []

    # 1. license hard blocker
    if not vendor.license_confirmed:
        return AcceptanceDecision(
            requirements.purpose_id, VERDICT_BLOCKED_DATA, (f"LICENSE_UNCONFIRMED:{vendor.license_scope}",)
        )
    if requirements.required_license_scope != vendor.license_scope:
        reasons.append(
            f"LICENSE_SCOPE_MISMATCH:required={requirements.required_license_scope},"
            f"vendor={vendor.license_scope}"
        )

    # 2. unknown (untestable) facts -> BLOCKED_DATA
    if vendor.pit_availability == "unknown":
        reasons.append("PIT_CAPABILITY_UNKNOWN")
    coverage_map = {
        "requires_history_membership": ("history_membership_coverage", "HISTORY_MEMBERSHIP"),
        "requires_delisting": ("delisting_coverage", "DELISTING"),
        "requires_corporate_actions": ("corporate_actions_coverage", "CORPORATE_ACTIONS"),
    }
    for req_field, (vendor_field, label) in coverage_map.items():
        if getattr(requirements, req_field) and getattr(vendor, vendor_field) == "unknown":
            reasons.append(f"{label}_COVERAGE_UNKNOWN")
    if any(r.endswith("_UNKNOWN") for r in reasons):
        return AcceptanceDecision(requirements.purpose_id, VERDICT_BLOCKED_DATA, tuple(reasons))

    # 3. zero denominators / zero latency samples -> INCONCLUSIVE
    zero_field = any(m.is_inconclusive for m in quality.field_coverage)
    zero_bar = quality.bar_completeness.is_inconclusive
    zero_latency = quality.latency.is_inconclusive
    if zero_field or zero_bar or zero_latency:
        if zero_field:
            reasons.extend(
                f"INCONCLUSIVE:{m.name}:denominator=0" for m in quality.field_coverage if m.is_inconclusive
            )
        if zero_bar:
            reasons.append("INCONCLUSIVE:bar_completeness:denominator=0")
        if zero_latency:
            reasons.append("INCONCLUSIVE:latency:zero_samples")
        return AcceptanceDecision(requirements.purpose_id, VERDICT_INCONCLUSIVE, tuple(reasons))

    # 4. PIT capability matrix (R1): the purpose's time rule defines the
    # required granularity; marketing "PIT-ready" claims are not inputs here.
    rule = requirements.available_at_rule
    if rule in _EVENT_LEVEL_RULES:
        if vendor.pit_availability == "none":
            reasons.append("PIT_CAPABILITY_ABSENT:vendor_has_no_availability_facts")
        elif vendor.pit_availability == "eod_only":
            reasons.append("PIT_GRANULARITY_INSUFFICIENT:eod_only_vs_event_level_required")
    else:  # bar-level rules
        if vendor.pit_availability == "none":
            reasons.append("PIT_CAPABILITY_ABSENT:vendor_has_no_availability_facts")

    # 5. required coverage known-absent -> on_fail
    for req_field, (vendor_field, label) in coverage_map.items():
        if getattr(requirements, req_field) and getattr(vendor, vendor_field) == "no":
            reasons.append(f"{label}_COVERAGE_ABSENT")

    # 6. quality thresholds (single formula: rates vs the purpose thresholds)
    if requirements.available_at_rule != "bar_ts_plus_0" and quality.unknown_availability_count > 0:
        reasons.append(f"UNKNOWN_AVAILABILITY_PRESENT:{quality.unknown_availability_count}")
    for metric in quality.field_coverage:
        if metric.missing / metric.denominator > requirements.max_missing_rate:
            reasons.append(
                f"MISSING_RATE_EXCEEDED:{metric.name}:{metric.missing}/{metric.denominator}"
            )
        if metric.rate is not None and metric.rate < requirements.min_coverage_rate:
            reasons.append(
                f"COVERAGE_RATE_BELOW_MIN:{metric.name}:"
                f"{metric.rate:.4f}<{requirements.min_coverage_rate}"
            )
    bar = quality.bar_completeness
    if bar.missing / bar.denominator > requirements.max_missing_rate:
        reasons.append(f"BARS_MISSING:{bar.missing}/{bar.denominator}")
    if bar.rate is not None and bar.rate < requirements.min_coverage_rate:
        reasons.append(
            f"BAR_COVERAGE_RATE_BELOW_MIN:{bar.rate:.4f}<{requirements.min_coverage_rate}"
        )
    if quality.duplicate_or_out_of_order > 0:
        reasons.append(f"DUPLICATE_OR_OUT_OF_ORDER:{quality.duplicate_or_out_of_order}")
    lat = quality.latency
    if lat.max_seconds is not None and lat.max_seconds > requirements.max_latency_seconds:
        reasons.append(f"LATENCY_EXCEEDED:max={lat.max_seconds:.0f}s")

    if reasons:
        return AcceptanceDecision(requirements.purpose_id, requirements.on_fail, tuple(reasons))

    return AcceptanceDecision(requirements.purpose_id, VERDICT_ACCEPT, ())


__all__ = [
    "AcceptanceDecision",
    "COVERAGE_FACT_VALUES",
    "DataAcceptanceConfig",
    "DataAcceptanceConfigError",
    "PIT_AVAILABILITY_VALUES",
    "PurposeRequirements",
    "VendorFacts",
    "VendorFactsError",
    "evaluate_purpose",
    "load_acceptance_config",
]
