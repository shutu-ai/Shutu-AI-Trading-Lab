"""Replay market clock — DST-correct session validation over the
PREREGISTERED SYNTHETIC calendar table.

This is fixture-scope validation only. The daemon must never infer real
US market hours from a synthetic fixture: real holiday feeds and real
session calendars require separately authorized data (S8). All checks go
through :class:`trading_lab.data.calendar.MarketCalendar` — the single
calendar authority.
"""

from __future__ import annotations

import datetime as dt

from trading_lab.data.calendar import ET, MarketCalendar

__all__ = ["ClockError", "ReplayClock"]


class ClockError(ValueError):
    """The event timestamp is an illegal market clock."""


class ReplayClock:
    def __init__(self, holidays: set[dt.date] | None = None,
                 half_days: set[dt.date] | None = None,
                 session_window_et: tuple[str, str] = ("09:30", "16:00")) -> None:
        self._calendar = MarketCalendar(
            holidays=holidays or set(), half_days=half_days or set())
        self._open = self._parse(session_window_et[0])
        self._close = self._parse(session_window_et[1])

    @staticmethod
    def _parse(hhmm: str) -> dt.time:
        parts = hhmm.split(":")
        return dt.time(int(parts[0]), int(parts[1]))

    def check_event_time(self, ts: dt.datetime) -> None:
        """Fail closed unless ``ts`` lands in a declared trading session
        window (inclusive of the close)."""
        if ts.tzinfo is None:
            raise ClockError("naive timestamp is not a fact")
        local = ts.astimezone(ET)
        session = self._calendar.session(local.date())
        if not session.is_trading_day:
            raise ClockError(
                f"{local.date()} is not a declared trading day")
        if not (self._open <= local.time() <= self._close):
            raise ClockError(
                f"{local.time()} outside declared session window "
                f"{self._open}-{self._close} ET")

    @staticmethod
    def session_close_utc(day: dt.date) -> dt.datetime:
        """DST-correct UTC instant of the ET session close (fixture and
        runner helper)."""
        return MarketCalendar.to_utc(
            dt.datetime.combine(day, dt.time(16, 0), tzinfo=ET))
