"""US market calendar primitives — UTC/America/New_York with correct DST,
weekend/holiday session classification, half-day sessions, and the
point-in-time rule ``available_at <= decision_cutoff``.

Holidays are **supplied data** (vendor calendar or operator-maintained
table), not hardcoded guesses: the calendar class validates the supplied
table (dates sorted, unique) and applies weekends on top of it. This keeps
the calendar deterministic and testable without pretending to know vendor
holiday feeds we have not licensed.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
UTC = dt.timezone.utc

REGULAR_OPEN = dt.time(9, 30)
REGULAR_CLOSE = dt.time(16, 0)
HALF_DAY_CLOSE = dt.time(13, 0)


class CalendarError(ValueError):
    """Raised for invalid calendar inputs (bad holiday table, naive times)."""


@dataclass(frozen=True)
class SessionInfo:
    """One trading session in Exchange time (ET) with DST-correct offsets."""

    date: dt.date
    is_trading_day: bool
    is_half_day: bool
    open_et: dt.time | None
    close_et: dt.time | None

    def open_utc(self) -> dt.datetime | None:
        if self.open_et is None:
            return None
        return dt.datetime.combine(self.date, self.open_et, tzinfo=ET).astimezone(UTC)

    def close_utc(self) -> dt.datetime | None:
        if self.close_et is None:
            return None
        return dt.datetime.combine(self.date, self.close_et, tzinfo=ET).astimezone(UTC)


class MarketCalendar:
    """Deterministic session classification over a supplied holiday table."""

    def __init__(self, holidays: set[dt.date], half_days: set[dt.date] | None = None) -> None:
        if len(holidays) != len({d.isoformat() for d in holidays}):
            raise CalendarError("duplicate holidays")
        for d in holidays:
            if d.weekday() >= 5:
                raise CalendarError(f"holiday {d} falls on a weekend (redundant entry)")
        self._holidays = frozenset(holidays)
        self._half_days = frozenset(half_days or set())
        overlap = self._holidays & self._half_days
        if overlap:
            raise CalendarError(f"dates marked both holiday and half-day: {sorted(overlap)}")

    # -- classification ------------------------------------------------------

    def session(self, day: dt.date) -> SessionInfo:
        if day.weekday() >= 5 or day in self._holidays:
            return SessionInfo(day, False, False, None, None)
        if day in self._half_days:
            return SessionInfo(day, True, True, REGULAR_OPEN, HALF_DAY_CLOSE)
        return SessionInfo(day, True, False, REGULAR_OPEN, REGULAR_CLOSE)

    def is_trading_day(self, day: dt.date) -> bool:
        return self.session(day).is_trading_day

    # -- time conversion (DST-correct via zoneinfo) --------------------------

    @staticmethod
    def to_utc(et_time: dt.datetime) -> dt.datetime:
        """Convert an ET wall-clock (tz-aware in ET, or naive treated as ET)
        to UTC. Naive inputs are treated as ET — the exchange timezone — and
        DST is resolved by zoneinfo."""
        if et_time.tzinfo is None:
            et_time = et_time.replace(tzinfo=ET)
        return et_time.astimezone(UTC)

    @staticmethod
    def to_et(utc_time: dt.datetime) -> dt.datetime:
        if utc_time.tzinfo is None:
            raise CalendarError("naive UTC datetime rejected (timezone-aware required)")
        return utc_time.astimezone(ET)

    # -- point-in-time rule ---------------------------------------------------

    @staticmethod
    def is_available(available_at: dt.datetime, decision_cutoff: dt.datetime) -> bool:
        """The point-in-time gate: data may drive a decision only if its
        availability timestamp is at or before the decision cutoff. Naive
        datetimes are rejected — an availability fact without a timezone is
        not a fact."""
        if available_at.tzinfo is None or decision_cutoff.tzinfo is None:
            raise CalendarError("available_at/decision_cutoff must be timezone-aware")
        return available_at <= decision_cutoff


__all__ = [
    "CalendarError",
    "ET",
    "HALF_DAY_CLOSE",
    "MarketCalendar",
    "REGULAR_CLOSE",
    "REGULAR_OPEN",
    "SessionInfo",
    "UTC",
]
