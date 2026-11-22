"""M1 U-1 — VendorFacts closed capability vocabularies (S8-T1, RED->GREEN).

Defect (RED reproduction archived in
``artifacts/evidence/M3.5/s8/u1-red-reproduction.txt``, against pre-fix
code): illegal vocabulary values — vendor marketing strings, case
variants, ``None`` — constructed fine and slipped past every ``==``
comparison in ``evaluate_purpose`` into ``ACCEPT`` with zero reasons.

Fix under the S8 read-only approval of 2026-11-22
(``artifacts/evidence/M3.5/s8/authorization-check.md``): the four
capability fields are closed vocabularies enforced at construction,
fail-closed, with no optimistic fallback. This fix does NOT unlock the
full-market historical research ``BLOCKED_DATA``: it only closes the
malformed-input hole in the admission vocabulary.

Positive cases keep the frozen semantics: ``unknown`` -> BLOCKED_DATA,
known-absent -> ``on_fail``, fully-satisfied facts -> ACCEPT.
"""

from __future__ import annotations

import datetime as dt
import sys
from decimal import Decimal
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from trading_lab.data.acceptance import (  # noqa: E402
    COVERAGE_FACT_VALUES,
    PIT_AVAILABILITY_VALUES,
    VERDICT_ACCEPT,
    VERDICT_BLOCKED_DATA,
    VendorFacts,
    VendorFactsError,
    evaluate_purpose,
    load_acceptance_config,
)
from trading_lab.data.quality import (  # noqa: E402
    MetricResult,
    QualityReport,
    field_coverage_metrics,
    latency_stats,
)

CONFIG_PATH = REPO_ROOT / "configs" / "data_acceptance.yaml"
U = dt.timezone.utc

LEGAL_COVERAGE = sorted(COVERAGE_FACT_VALUES)
LEGAL_PIT = sorted(PIT_AVAILABILITY_VALUES)


def good_facts(**over) -> VendorFacts:
    base = dict(
        license_scope="personal_research",
        license_confirmed=True,
        history_membership_coverage="yes",
        delisting_coverage="yes",
        corporate_actions_coverage="yes",
        pit_availability="event_level",
    )
    base.update(over)
    return VendorFacts(**base)


def passing_quality() -> QualityReport:
    t = dt.datetime(2026, 1, 1, tzinfo=U)
    rows = [{"close": Decimal("100"), "ts_available_utc": t,
             "ts_event_utc": t} for _ in range(10)]
    return QualityReport(
        field_coverage=field_coverage_metrics(
            rows, ["close", "ts_available_utc"]),
        bar_completeness=MetricResult(
            name="bar_completeness", denominator=10, missing=0,
            observed=10, rate=1.0),
        duplicate_or_out_of_order=0,
        latency=latency_stats(rows),
        unknown_availability_count=0,
        license_status="personal_research",
    )


# ---------------------------------------------------------------------------
# positives — legal vocabularies construct; frozen semantics unchanged
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("coverage", LEGAL_COVERAGE)
@pytest.mark.parametrize("field_name", [
    "history_membership_coverage", "delisting_coverage",
    "corporate_actions_coverage",
])
def test_legal_coverage_values_construct(field_name, coverage):
    assert getattr(good_facts(**{field_name: coverage}), field_name) == coverage


@pytest.mark.parametrize("pit", LEGAL_PIT)
def test_legal_pit_values_construct(pit):
    assert good_facts(pit_availability=pit).pit_availability == pit


def test_frozen_semantics_unchanged_legal_accept_path():
    """Fully-satisfied legal facts still reach ACCEPT — the fix closes the
    malformed-input hole, it does not tighten legal admission."""
    cfg = load_acceptance_config(CONFIG_PATH)
    decision = evaluate_purpose(
        cfg.purpose("historical_research_daily"), passing_quality(),
        good_facts())
    assert decision.verdict == VERDICT_ACCEPT


def test_frozen_semantics_unchanged_unknown_blocked():
    cfg = load_acceptance_config(CONFIG_PATH)
    decision = evaluate_purpose(
        cfg.purpose("historical_research_daily"), passing_quality(),
        good_facts(pit_availability="unknown"))
    assert decision.verdict == VERDICT_BLOCKED_DATA


# ---------------------------------------------------------------------------
# negatives — every malformed value fails closed at construction
# ---------------------------------------------------------------------------

ILLEGAL_VALUES = [
    "partially",
    "PIT-ready (vendor marketing claim)",
    "YES",                       # case-erroneous
    "yes ",                      # whitespace-padded
    "",                          # empty
    None,                        # None is not 'unknown'
    123,                         # non-string type
    "unknown\n",                 # trailing newline
]


@pytest.mark.parametrize("bad", ILLEGAL_VALUES)
@pytest.mark.parametrize("field_name", [
    "history_membership_coverage", "delisting_coverage",
    "corporate_actions_coverage",
])
def test_illegal_coverage_value_fails_closed(field_name, bad):
    with pytest.raises(VendorFactsError):
        good_facts(**{field_name: bad})


@pytest.mark.parametrize("bad", [
    *ILLEGAL_VALUES,
    "eod-level",                 # near-miss of a legal value
    "event-level",               # hyphen variant
])
def test_illegal_pit_value_fails_closed(bad):
    with pytest.raises(VendorFactsError):
        good_facts(pit_availability=bad)


def test_missing_capability_field_is_a_type_error():
    """A missing field never constructs (dataclass arity) — no silent
    partial VendorFacts exists."""
    with pytest.raises(TypeError):
        VendorFacts(
            license_scope="personal_research",
            license_confirmed=True,
            history_membership_coverage="yes",
            delisting_coverage="yes",
            corporate_actions_coverage="yes",
        )  # pit_availability missing


def test_vendor_facts_error_is_data_acceptance_config_error():
    """Callers that already catch DataAcceptanceConfigError keep working:
    the new error is its subclass, not a parallel type."""
    assert issubclass(VendorFactsError, Exception)
    from trading_lab.data.acceptance import DataAcceptanceConfigError
    assert issubclass(VendorFactsError, DataAcceptanceConfigError)


# ---------------------------------------------------------------------------
# end-to-end — the admission surface can no longer be fooled
# ---------------------------------------------------------------------------

def test_marketing_claim_cannot_reach_accept_anymore():
    """The exact RED scenario (archived): legal 'yes' coverage + a
    marketing-claim PIT string flowed to ACCEPT pre-fix. Post-fix the
    facts object cannot exist, so no evaluate_purpose call can be fooled."""
    with pytest.raises(VendorFactsError):
        good_facts(pit_availability="PIT-ready (vendor marketing claim)")


def test_historical_research_blocked_data_unchanged():
    """The U-1 fix does not unlock BLOCKED_DATA: unknown facts still block
    the full-research purpose exactly as before."""
    cfg = load_acceptance_config(CONFIG_PATH)
    decision = evaluate_purpose(
        cfg.purpose("historical_research_daily"), passing_quality(),
        good_facts(history_membership_coverage="unknown",
                   delisting_coverage="unknown",
                   corporate_actions_coverage="unknown"))
    assert decision.verdict == VERDICT_BLOCKED_DATA
    assert any(r.endswith("_COVERAGE_UNKNOWN") for r in decision.reasons)
