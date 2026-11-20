"""Machine-checkable data quality reports — explicit denominators.

Every metric reports its denominator, missing count, observed rate and
sample size; a zero denominator is ``INCONCLUSIVE``, never 100%. Latency
statistics (``available_at - ts_event``) include their sample count and
explicitly count records with unknown availability instead of hiding them.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from statistics import median


@dataclass(frozen=True)
class MetricResult:
    name: str
    denominator: int
    missing: int
    observed: int
    rate: float | None  # None when denominator == 0

    @property
    def is_inconclusive(self) -> bool:
        return self.denominator == 0


@dataclass(frozen=True)
class LatencyStats:
    sample_count: int
    unknown_availability_count: int
    min_seconds: float | None
    median_seconds: float | None
    max_seconds: float | None

    @property
    def is_inconclusive(self) -> bool:
        return self.sample_count == 0


@dataclass(frozen=True)
class QualityReport:
    """Quality facts for one dataset partition, each with its denominator."""

    field_coverage: tuple[MetricResult, ...]
    bar_completeness: MetricResult          # expected sessions vs received bars
    duplicate_or_out_of_order: int          # violations found
    latency: LatencyStats
    unknown_availability_count: int
    license_status: str                     # passthrough from the vendor record
    notes: tuple[str, ...] = field(default_factory=tuple)

    def failures(self, max_missing_rate: float, max_latency_seconds: float | None) -> list[str]:
        """Evaluate against pre-declared thresholds. Zero denominators are
        failures here (the acceptance layer decides BLOCKED vs FAIL)."""
        problems: list[str] = []
        for metric in self.field_coverage:
            if metric.is_inconclusive:
                problems.append(f"INCONCLUSIVE:{metric.name}:denominator=0")
            elif metric.missing / metric.denominator > max_missing_rate:
                problems.append(
                    f"MISSING_RATE_EXCEEDED:{metric.name}:"
                    f"{metric.missing}/{metric.denominator}"
                )
        if self.bar_completeness.is_inconclusive:
            problems.append("INCONCLUSIVE:bar_completeness:denominator=0")
        elif self.bar_completeness.missing > 0:
            problems.append(
                f"BARS_MISSING:{self.bar_completeness.missing}/"
                f"{self.bar_completeness.denominator}"
            )
        if self.duplicate_or_out_of_order > 0:
            problems.append(f"DUPLICATE_OR_OUT_OF_ORDER:{self.duplicate_or_out_of_order}")
        if not self.latency.is_inconclusive and max_latency_seconds is not None:
            if self.latency.max_seconds is not None and (
                self.latency.max_seconds > max_latency_seconds
            ):
                problems.append(f"LATENCY_EXCEEDED:max={self.latency.max_seconds:.0f}s")
        problems.append(f"LATENCY_SAMPLES:{self.latency.sample_count}")
        problems.append(f"UNKNOWN_AVAILABILITY:{self.unknown_availability_count}")
        return problems


def field_coverage_metrics(
    rows: list[dict[str, object]], required_fields: list[str]
) -> tuple[MetricResult, ...]:
    """Per-field denominator/missing/coverage over the received rows."""
    results: list[MetricResult] = []
    denominator = len(rows)
    for name in required_fields:
        missing = sum(1 for r in rows if r.get(name) in (None, ""))
        observed = denominator - missing
        rate = (observed / denominator) if denominator else None
        results.append(
            MetricResult(name=name, denominator=denominator, missing=missing, observed=observed, rate=rate)
        )
    return tuple(results)


def count_duplicate_or_out_of_order(
    rows: list[dict[str, object]], time_field: str = "ts_event_utc"
) -> int:
    stamps = [r[time_field] for r in rows if time_field in r]
    violations = 0
    for a, b in zip(stamps, stamps[1:]):
        if not (b > a):
            violations += 1
    return violations


def latency_stats(
    rows: list[dict[str, object]],
    event_field: str = "ts_event_utc",
    available_field: str = "ts_available_utc",
) -> LatencyStats:
    """Observed publication latency per row; unknown availability is counted,
    never imputed."""
    deltas: list[float] = []
    unknown = 0
    for r in rows:
        avail = r.get(available_field)
        event = r.get(event_field)
        if not isinstance(avail, dt.datetime) or not isinstance(event, dt.datetime):
            unknown += 1
            continue
        deltas.append((avail - event).total_seconds())
    if not deltas:
        return LatencyStats(0, unknown, None, None, None)
    return LatencyStats(
        sample_count=len(deltas),
        unknown_availability_count=unknown,
        min_seconds=min(deltas),
        median_seconds=median(deltas),
        max_seconds=max(deltas),
    )


def bar_completeness(
    received_dates: set[dt.date], expected_sessions: list[dt.date]
) -> MetricResult:
    expected = len(expected_sessions)
    missing = sum(1 for d in expected_sessions if d not in received_dates)
    observed = expected - missing
    rate = (observed / expected) if expected else None
    return MetricResult(
        name="bar_completeness", denominator=expected, missing=missing, observed=observed, rate=rate
    )


__all__ = [
    "LatencyStats",
    "MetricResult",
    "QualityReport",
    "bar_completeness",
    "count_duplicate_or_out_of_order",
    "field_coverage_metrics",
    "latency_stats",
]
