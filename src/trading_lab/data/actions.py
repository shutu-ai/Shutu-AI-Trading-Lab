"""Corporate-action adjustments — deterministic, recomputable, versioned.

Adjusted prices are **recomputed** from raw prices + action factors with a
versioned transform; they are never accepted pre-adjusted without the
factor series. Every action carries ``announced_at``/``effective_at``/
``available_at`` as independent facts; a record without a usable
availability fact is marked ``UNKNOWN_AVAILABILITY`` and degrades its
series instead of silently pretending a K-line date is an announcement
date.

Point-in-time application: an action may only be applied to a series
viewed at ``asof`` if ``available_at <= asof`` — knowing a split "in
hindsight" and applying it retroactively to earlier decisions is the
classic lookahead leak, and is exactly what the ``asof`` parameter
prevents.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from .records import MARKER_UNKNOWN_AVAILABILITY

ADJUST_TRANSFORM_VERSION = "adj-1"


class ActionError(ValueError):
    pass


@dataclass(frozen=True)
class ActionRecord:
    """A split or dividend factor with its three independent time facts.

    ``factor``: for a split, shares_new / shares_old (2:1 split -> 2);
    price adjustment divides pre-split prices by the factor.
    """

    symbol: str
    kind: str  # SPLIT / DIVIDEND / ...
    factor: Decimal
    announced_at: dt.datetime | None
    effective_at: dt.datetime
    available_at: dt.datetime | object  # datetime or UNKNOWN_AVAILABILITY
    source: str

    def __post_init__(self) -> None:
        if self.factor <= 0 or not self.factor.is_finite():
            raise ActionError(f"factor must be finite and positive (got {self.factor})")
        if self.effective_at.tzinfo is None:
            raise ActionError("effective_at must be timezone-aware")
        if self.announced_at is not None and self.announced_at.tzinfo is None:
            raise ActionError("announced_at must be timezone-aware")
        if self.available_at == MARKER_UNKNOWN_AVAILABILITY:
            return
        if not isinstance(self.available_at, dt.datetime):
            raise ActionError("available_at must be tz-aware datetime or UNKNOWN_AVAILABILITY")
        if self.available_at.tzinfo is None:
            raise ActionError("available_at must be timezone-aware")

    @property
    def availability_known(self) -> bool:
        return self.available_at != MARKER_UNKNOWN_AVAILABILITY


@dataclass(frozen=True)
class AdjustmentResult:
    """The recomputation outcome, carrying its own provenance for snapshots."""

    symbol: str
    transform_version: str
    adjusted_closes: tuple[tuple[dt.datetime, Decimal], ...]
    applied_actions: tuple[ActionRecord, ...]
    unknown_availability_actions: tuple[ActionRecord, ...]
    future_known_actions: tuple[ActionRecord, ...]  # known at asof but effective later


def adjust_series(
    symbol: str,
    bars: list[tuple[dt.datetime, Decimal]],
    actions: list[ActionRecord],
    asof: dt.datetime,
) -> AdjustmentResult:
    """Recompute adjusted closes for ``bars`` (UTC timestamps, raw closes)
    under the knowledge available at ``asof``.

    Rules:
    - only actions with a known ``available_at <= asof`` are applied;
    - actions with ``UNKNOWN_AVAILABILITY`` are never silently applied —
      they are reported so the caller can degrade the series' use;
    - an action effective AFTER ``asof`` is reported in
      ``future_known_actions`` (it is knowledge, not yet applicable);
    - cumulative factor: price_adjusted = price_raw / prod(factors of all
      actions effective after the bar but at or before asof).
    """
    if asof.tzinfo is None:
        raise ActionError("asof must be timezone-aware")

    applied: list[ActionRecord] = []
    unknown: list[ActionRecord] = []
    future_known: list[ActionRecord] = []
    for act in actions:
        if act.symbol != symbol:
            continue
        if not act.availability_known:
            unknown.append(act)
            continue
        assert isinstance(act.available_at, dt.datetime)
        if act.available_at > asof:
            continue  # not knowable at the decision time at all
        if act.effective_at > asof:
            future_known.append(act)
            continue
        applied.append(act)

    def factor_after(bar_time: dt.datetime) -> Decimal:
        product = Decimal(1)
        for act in applied:
            if act.effective_at > bar_time:
                product *= act.factor
        return product

    adjusted = tuple(
        (t, (close / factor_after(t)).quantize(Decimal("0.0001")))
        for t, close in sorted(bars, key=lambda b: b[0])
    )
    return AdjustmentResult(
        symbol=symbol,
        transform_version=ADJUST_TRANSFORM_VERSION,
        adjusted_closes=adjusted,
        applied_actions=tuple(sorted(applied, key=lambda a: a.effective_at)),
        unknown_availability_actions=tuple(unknown),
        future_known_actions=tuple(sorted(future_known, key=lambda a: a.effective_at)),
    )


__all__ = [
    "ADJUST_TRANSFORM_VERSION",
    "ActionError",
    "ActionRecord",
    "AdjustmentResult",
    "adjust_series",
]
