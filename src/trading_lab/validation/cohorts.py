"""Cohort hygiene (M3-R1-T5): non-overlapping evaluation segments,
Purge/Embargo, Walk-Forward, sealed-final and forward boundaries, overlap
reporting (v2.1 §4.2/§4.5).

Independence rules enforced here:

- SEALED_FINAL must not overlap ANY other cohort (date, symbol, event id,
  label interval) — it is the one-shot M9 instrument.
- FORWARD cohorts are scored only on predictions locked BEFORE the
  observation exists (prediction_locked_at < observation_available_at);
  re-using a scored forward interval for selection pollutes it.
- Train/Validation and rolling OOS boundaries apply Purge (drop training
  labels that overlap the evaluation interval) and Embargo (drop an
  additional gap) so a label that straddles the boundary cannot leak.
- Reverse-time cohorts (start after end) are fail-closed errors.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Iterable, Sequence

__all__ = [
    "CohortError",
    "CohortRole",
    "CohortSpec",
    "ForwardCohort",
    "OverlapReport",
    "apply_purge_embargo",
    "check_overlaps",
    "walk_forward_splits",
]

UTCDAY = dt.timedelta(days=1)


class CohortError(ValueError):
    """Cohort definition/boundary violation — fail closed."""


@dataclasses.dataclass(frozen=True)
class CohortRole:
    TRAIN = "TRAIN"
    VALIDATION = "VALIDATION"
    HIST_OOS = "HIST_OOS"
    SEALED_FINAL = "SEALED_FINAL"
    FORWARD = "FORWARD"


ROLES = (CohortRole.TRAIN, CohortRole.VALIDATION, CohortRole.HIST_OOS,
         CohortRole.SEALED_FINAL, CohortRole.FORWARD)


@dataclass(frozen=True)
class CohortSpec:
    role: str
    start: dt.datetime          # inclusive, tz-aware
    end: dt.datetime            # exclusive, tz-aware
    symbols: frozenset[str] = frozenset()
    event_ids: frozenset[str] = frozenset()
    label_intervals: tuple[tuple[dt.datetime, dt.datetime], ...] = ()
    available_ats: tuple[dt.datetime, ...] = ()

    def __post_init__(self) -> None:
        if self.role not in ROLES:
            raise CohortError(f"unknown cohort role {self.role}")
        for ts in (self.start, self.end):
            if not isinstance(ts, dt.datetime) or ts.tzinfo is None:
                raise CohortError(f"{self.role}: timestamps must be tz-aware")
        if self.start >= self.end:
            raise CohortError(
                f"{self.role}: reverse/empty interval {self.start}..{self.end}")
        for a, b in self.label_intervals:
            if a.tzinfo is None or b.tzinfo is None or a >= b:
                raise CohortError(
                    f"{self.role}: label intervals must be tz-aware and "
                    "start < end")
        for ts in self.available_ats:
            if not isinstance(ts, dt.datetime) or ts.tzinfo is None:
                raise CohortError(f"{self.role}: available_ats must be tz-aware")

    def overlaps_time(self, other: "CohortSpec") -> bool:
        return self.start < other.end and other.start < self.end

    def intersects(self, other: "CohortSpec") -> dict[str, bool]:
        """Dimension-wise intersection facts for the overlap report."""
        return {
            "time": self.overlaps_time(other),
            "symbols": bool(self.symbols & other.symbols)
            if self.symbols and other.symbols else False,
            "event_ids": bool(self.event_ids & other.event_ids)
            if self.event_ids and other.event_ids else False,
            "labels": any(a < ob and oa < b
                          for (a, b) in self.label_intervals
                          for (oa, ob) in other.label_intervals),
            "available_ats": any(abs((x - y)) < UTCDAY
                                 for x in self.available_ats
                                 for y in other.available_ats)
            if self.available_ats and other.available_ats else False,
        }


@dataclass(frozen=True)
class ForwardCohort:
    """A forward cohort: predictions are locked BEFORE observations exist
    (v2.1 §4.5). Scoring locks the cohort for future selection."""

    cohort_id: str
    prediction_locked_at: dt.datetime
    observation_available_at: dt.datetime
    polluted_for_future_selection: bool = field(
        default=False, init=False)

    def __post_init__(self) -> None:
        for ts in (self.prediction_locked_at, self.observation_available_at):
            if not isinstance(ts, dt.datetime) or ts.tzinfo is None:
                raise CohortError(f"{self.cohort_id}: timestamps tz-aware")
        if self.prediction_locked_at >= self.observation_available_at:
            raise CohortError(
                f"{self.cohort_id}: prediction must be locked BEFORE the "
                "observation exists (forward-only, no hindsight)")
        # frozen dataclass with init=False field — set via object hook
        object.__setattr__(self, "polluted_for_future_selection", False)

    def score(self, *, now: dt.datetime) -> str:
        """Score locked predictions once the observation exists. Scoring
        pollutes the interval for future selection (one-shot)."""
        if now.tzinfo is None:
            raise CohortError("now must be tz-aware")
        if now < self.observation_available_at:
            raise CohortError(
                f"{self.cohort_id}: observation not available yet — "
                "scoring before the fact is forbidden")
        if self.polluted_for_future_selection:
            raise CohortError(
                f"{self.cohort_id}: already scored; this interval cannot be "
                "re-used for selection")
        object.__setattr__(self, "polluted_for_future_selection", True)
        return "SCORED"


@dataclass(frozen=True)
class OverlapReport:
    pairwise: tuple[dict, ...]      # one entry per cohort pair
    independent: bool               # True when no illegal overlap exists

    def to_markdown(self, title: str = "Cohort overlap report") -> str:
        lines = [f"# {title}", "",
                 "| pair | time | symbols | event_ids | labels | "
                 "available_ats | verdict |",
                 "|---|---|---|---|---|---|---|"]
        for p in self.pairwise:
            verdict = "OK" if p["legal"] else "**OVERLAP**"
            lines.append(
                f"| {p['a']} vs {p['b']} | {p['time']} | {p['symbols']} | "
                f"{p['event_ids']} | {p['labels']} | {p['available_ats']} "
                f"| {verdict} |")
        lines += ["", f"**independent**: {self.independent}", ""]
        return "\n".join(lines)


def check_overlaps(cohorts: Sequence[CohortSpec]) -> OverlapReport:
    """Pairwise legality. SEALED_FINAL is the one-shot instrument: any
    overlap on a SAMPLE-DEFINING dimension (time window, event ids, label
    intervals) with any other cohort is illegal. Symbol-universe and
    available-at proximity overlaps are DISCLOSURES — an asset universe is
    naturally shared across cohorts; they degrade nothing by themselves
    but must appear in the report (v2.1 §4.5 逐条披露)."""
    pairwise: list[dict] = []
    independent = True
    for i, a in enumerate(cohorts):
        for j, b in enumerate(cohorts):
            if j <= i:
                continue
            inter = a.intersects(b)
            sealed_involved = CohortRole.SEALED_FINAL in (a.role, b.role)
            illegal = sealed_involved and (
                inter["time"] or inter["event_ids"] or inter["labels"])
            pairwise.append({
                "a": f"{a.role}#{i}", "b": f"{b.role}#{j}",
                **inter,
                "legal": not illegal,
            })
            if illegal:
                independent = False
    return OverlapReport(pairwise=tuple(pairwise), independent=independent)


def apply_purge_embargo(
    train: CohortSpec, evaluation: CohortSpec, *,
    label_horizon: dt.timedelta, embargo: dt.timedelta,
) -> tuple[CohortSpec, CohortSpec]:
    """Purge training labels that reach past the (embargoed) boundary.

    The train end moves back by ``embargo``; any training label interval
    whose completion (or whose start + ``label_horizon``) would cross the
    boundary is dropped. Fail-closed: a label that still crosses after the
    purge is an error, not a silent leak."""
    if train.overlaps_time(evaluation):
        raise CohortError("train and evaluation intervals must not overlap "
                          "before purge/embargo (sequential splits only)")
    new_train_end = evaluation.start - embargo
    if new_train_end <= train.start:
        raise CohortError(
            "embargo consumes the whole training window — fail closed")
    kept = tuple((a, b) for (a, b) in train.label_intervals
                 if b <= new_train_end)
    for (a, _b) in kept:
        if a + label_horizon > new_train_end:
            raise CohortError(
                "training label still crosses the embargoed boundary "
                "after purge — fail closed")
    adjusted_train = dataclasses.replace(
        train, end=new_train_end, label_intervals=kept)
    return adjusted_train, evaluation


def walk_forward_splits(
    start: dt.datetime, end: dt.datetime, *, n_folds: int,
    train_fraction: Decimal, embargo: dt.timedelta,
) -> list[tuple[CohortSpec, CohortSpec]]:
    """Deterministic rolling walk-forward folds.

    Fold i evaluates OOS on [split_i, split_i + step) where
    step = total / (n_folds + 1); its training window is the preceding
    ``train_len = step × f/(1−f)`` (truncated at ``start``), purged and
    embargoed from its own OOS. Successive OOS windows never overlap.
    """
    if start.tzinfo is None or end.tzinfo is None:
        raise CohortError("walk_forward timestamps must be tz-aware")
    if start >= end:
        raise CohortError("empty walk-forward window")
    if n_folds < 2:
        raise CohortError("walk-forward needs >= 2 folds")
    if not (Decimal("0") < train_fraction < Decimal("1")):
        raise CohortError("train_fraction must be within (0, 1)")
    total = end - start
    step = total / (n_folds + 1)
    ratio = float(train_fraction / (Decimal("1") - train_fraction))
    train_len = step * ratio
    folds: list[tuple[CohortSpec, CohortSpec]] = []
    last_oos_end: dt.datetime | None = None
    for i in range(1, n_folds + 1):
        split = start + step * i
        oos_end = min(split + step, end)
        train_start = max(start, split - train_len)
        train = CohortSpec(role=CohortRole.TRAIN, start=train_start,
                           end=split)
        oos = CohortSpec(role=CohortRole.HIST_OOS, start=split, end=oos_end)
        train, oos = apply_purge_embargo(
            train, oos, label_horizon=UTCDAY, embargo=embargo)
        if last_oos_end is not None and split < last_oos_end:
            raise CohortError("walk-forward OOS windows overlap — fail closed")
        last_oos_end = oos_end
        folds.append((train, oos))
    return folds
