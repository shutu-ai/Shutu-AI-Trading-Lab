"""Versioned calendar supply for historical research (H1A, M3-H workstream).

``MarketCalendar`` classifies sessions from a SUPPLIED holiday/half-day
table, but its ``session()`` answers weekday-only facts for any date it
is handed — correct inside its data's coverage, silently assumed
outside. Historical point-in-time rules need the opposite: a calendar
that REFUSES to answer for any date its versioned supply does not
certify (no coverage, no source, no window -> no positive conclusion).

``VersionedMarketCalendar`` composes (never modifies) ``MarketCalendar``
with a :class:`CalendarSupply` — an explicitly versioned, sourced,
windowed holiday/half-day table — and adds the next-session-open rule
the H1 purpose row is built on:

    available_at(daily close bar) := OPEN of the next valid US trading
    session, STRICTLY AFTER the bar's close moment.

This is a declared MODEL ASSUMPTION (``pit_evidence_level=ASSUMED``,
never ``VERIFIED``). All arithmetic resolves America/New_York wall-clock
through zoneinfo, so DST transitions come from the tz database, not
from offset math. Weekend/holiday chains (65.5h Friday->Monday, 41.5h
Thanksgiving-eve->Friday, 92.5h Christmas-eve->Monday) are legal spans,
never latency violations — the calendar-driven per-row gate lives in
:mod:`trading_lab.data.historical`.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from .calendar import CalendarError, ET, MarketCalendar, SessionInfo

__all__ = ["CalendarSupply", "VersionedMarketCalendar"]


@dataclass(frozen=True)
class CalendarSupply:
    """One explicitly versioned calendar supply: who certifies which days
    are holidays / early-close days, for which date window, retrieved when.

    Fail-closed validation: empty version/source, naive retrieval time,
    an inverted window, or any holiday/half-day outside
    ``[valid_from, valid_until]`` is refused at construction. (Weekend
    holiday entries and holiday/half-day overlap are rejected by
    ``MarketCalendar`` itself in :meth:`VersionedMarketCalendar.from_supply`.)"""

    version: str
    source: str
    source_url: str
    retrieved_utc: dt.datetime
    valid_from: dt.date
    valid_until: dt.date
    holidays: frozenset[dt.date]
    half_days: frozenset[dt.date]

    def __post_init__(self) -> None:
        if not self.version or not self.source or not self.source_url:
            raise CalendarError(
                "calendar supply must record a non-empty version, source and source_url"
            )
        if self.retrieved_utc.tzinfo is None:
            raise CalendarError("calendar supply retrieved_utc must be timezone-aware")
        if self.valid_from > self.valid_until:
            raise CalendarError("calendar supply window inverted (valid_from > valid_until)")
        for name, days in (("holiday", self.holidays), ("half_day", self.half_days)):
            for day in days:
                if not (self.valid_from <= day <= self.valid_until):
                    raise CalendarError(
                        f"{name} {day.isoformat()} outside supply window "
                        f"[{self.valid_from.isoformat()}, {self.valid_until.isoformat()}]"
                    )

    def covers(self, day: dt.date) -> bool:
        return self.valid_from <= day <= self.valid_until


class VersionedMarketCalendar:
    """A ``MarketCalendar`` bound to its supply: dates outside the supply
    window are refused outright (fail-closed — never a weekday-only
    assumption), and the next-session-open rule is answered only when
    BOTH the moment's own date and the answer session sit inside the
    supply coverage."""

    def __init__(self, supply: CalendarSupply, calendar: MarketCalendar) -> None:
        self._supply = supply
        self._cal = calendar

    @classmethod
    def from_supply(cls, supply: CalendarSupply) -> "VersionedMarketCalendar":
        calendar = MarketCalendar(
            holidays=set(supply.holidays), half_days=set(supply.half_days)
        )
        return cls(supply, calendar)

    @property
    def supply(self) -> CalendarSupply:
        return self._supply

    def _require_covered(self, day: dt.date) -> None:
        if not self._supply.covers(day):
            raise CalendarError(
                f"date {day.isoformat()} outside calendar supply coverage "
                f"[{self._supply.valid_from.isoformat()}, "
                f"{self._supply.valid_until.isoformat()}] "
                f"(version={self._supply.version!r}) — refusing to assume a session"
            )

    # -- classification (coverage-gated) -------------------------------------

    def session(self, day: dt.date) -> SessionInfo:
        self._require_covered(day)
        return self._cal.session(day)

    def is_trading_day(self, day: dt.date) -> bool:
        return self.session(day).is_trading_day

    def expected_sessions(self, start: dt.date, end: dt.date) -> list[dt.date]:
        """Trading sessions in ``[start, end]``; the whole range must be
        inside the supply window (completeness denominators outside the
        window are unknowable, not zero)."""
        if start > end:
            raise CalendarError("expected_sessions: start after end")
        self._require_covered(start)
        self._require_covered(end)
        sessions: list[dt.date] = []
        day = start
        while day <= end:
            if self._cal.session(day).is_trading_day:
                sessions.append(day)
            day += dt.timedelta(days=1)
        return sessions

    # -- the H1 next-open rule -------------------------------------------------

    def session_open_after(self, moment_utc: dt.datetime) -> dt.datetime:
        """OPEN of the next valid trading session STRICTLY AFTER
        ``moment_utc`` (timezone-aware required; any aware instant works,
        ET instants are compared by absolute time).

        The moment's own ET date AND the answer session must both be
        inside the supply window: a bar whose next session the supply
        cannot certify gets NO availability answer (CalendarError with a
        coverage reason — the caller can never mistake refusal for a
        positive PIT conclusion)."""
        if moment_utc.tzinfo is None:
            raise CalendarError("session_open_after requires a timezone-aware moment")
        moment_date = moment_utc.astimezone(ET).date()
        self._require_covered(moment_date)
        day = moment_date
        while day <= self._supply.valid_until:
            info = self._cal.session(day)
            if info.is_trading_day and info.open_et is not None:
                open_utc = info.open_utc()
                if open_utc is not None and open_utc > moment_utc:
                    return open_utc
            day += dt.timedelta(days=1)
        raise CalendarError(
            f"no trading-session open after {moment_utc.isoformat()} within "
            f"calendar supply coverage [{self._supply.valid_from.isoformat()}, "
            f"{self._supply.valid_until.isoformat()}] "
            f"(version={self._supply.version!r}) — refusing to assume one"
        )
