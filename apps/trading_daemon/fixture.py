"""Deterministic synthetic replay fixture for the M3.5 Shadow forward
harness (SYNTHETIC_REPLAY only).

This is the ONLY event source the daemon accepts in the offline scope:
hand-declared synthetic bars whose timestamps follow the preregistered
synthetic calendar (US-equity session closes in ET, converted to UTC with
correct DST handling via :class:`trading_lab.data.calendar.MarketCalendar`).

Honest boundaries:
- These events are fixture data. They are NEVER real forward observations
  and can never upgrade the run out of ``SYNTHETIC_REPLAY``.
- The calendar table below is a fixture convention, NOT a claim about real
  US market holidays.
- The dataset hash is the canonical digest of the full bar set; it is
  frozen into ``configs/forward_observation.yaml`` and asserted by the
  runner so a fixture change is a preregistration change.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from trading_lab.contracts import AdjustmentKind, MarketBar
from trading_lab.data.calendar import ET, MarketCalendar
from trading_lab.security.canonical import canonical_digest

FIXTURE_NAME = "m35-shadow-replay-v1"
SYMBOL = "SYN-ETF"
SOURCE = "synthetic"
INTERVAL = "1d"
N_SESSIONS = 30
START_DATE = dt.date(2026, 3, 2)          # Monday; window crosses DST start
SESSION_CLOSE_ET = dt.time(16, 0)         # regular close; fixture uses closes
RECEIPT_DELAY = dt.timedelta(minutes=5)   # deterministic synthetic receipt lag

# fixture convention: weekdays are sessions, no synthetic holidays/half days
CALENDAR_HOLIDAYS: frozenset[dt.date] = frozenset()
CALENDAR_HALF_DAYS: frozenset[dt.date] = frozenset()

_CALENDAR = MarketCalendar(
    holidays=set(CALENDAR_HOLIDAYS), half_days=set(CALENDAR_HALF_DAYS))


def fixture_closes(n_sessions: int = N_SESSIONS) -> list[Decimal]:
    """Deterministic closes: slow uptrend + period-10 triangle oscillation
    (amplitude 1.5). Pure Decimal, reproducible by hand from the formula."""
    closes: list[Decimal] = []
    for i in range(n_sessions):
        c = i % 10
        triangle = c if c <= 5 else 10 - c        # 0..5, period 10
        osc = (Decimal(triangle) - Decimal("2.5")) * Decimal("1.5")
        closes.append(Decimal("100") + Decimal("0.25") * i + osc)
    return closes


def session_dates(n_sessions: int = N_SESSIONS) -> list[dt.date]:
    """The first ``n_sessions`` weekdays starting at START_DATE (the
    declared synthetic calendar has no holidays)."""
    days: list[dt.date] = []
    day = START_DATE
    while len(days) < n_sessions:
        if day.weekday() < 5:
            days.append(day)
        day += dt.timedelta(days=1)
    return days


def session_close_utc(day: dt.date) -> dt.datetime:
    """DST-correct UTC instant of the ET session close (16:00 ET)."""
    return MarketCalendar.to_utc(
        dt.datetime.combine(day, SESSION_CLOSE_ET, tzinfo=ET))


def build_fixture_bars(
        n_sessions: int = N_SESSIONS) -> list[MarketBar]:
    bars: list[MarketBar] = []
    for i, (day, close) in enumerate(
            zip(session_dates(n_sessions), fixture_closes(n_sessions))):
        ts = session_close_utc(day)
        bars.append(MarketBar.model_validate(dict(
            asset_id=SYMBOL, ts_event_utc=ts, ts_available_utc=ts,
            interval=INTERVAL, open=close - Decimal("0.25"),
            high=close + Decimal("0.5"), low=close - Decimal("0.5"),
            close=close, volume=Decimal("5000000"), source=SOURCE,
            adjustment=AdjustmentKind.RAW, quality="ok")))
    return bars


def build_fixture_events(
        n_sessions: int = N_SESSIONS) -> list[dict[str, Any]]:
    """Envelope payloads for the replay driver, in arrival order.

    ``received_at`` is a deterministic fixture value (session close plus a
    fixed 5-minute receipt lag) so replays are reproducible; it is declared
    synthetic transport metadata, not a real arrival fact. ``environment``
    is stamped SYNTHETIC_REPLAY as the session requires.
    """
    payloads: list[dict[str, Any]] = []
    for i, bar in enumerate(build_fixture_bars(n_sessions)):
        payloads.append(dict(
            event_id=f"{FIXTURE_NAME}-{i:04d}",
            source=bar.source,
            dataset_hash=fixture_dataset_hash(n_sessions),
            symbol=bar.asset_id,
            interval=bar.interval,
            ts_event=bar.ts_event_utc,
            ts_available=bar.ts_available_utc,
            received_at=bar.ts_available_utc + RECEIPT_DELAY,
            close=bar.close,
            environment="SYNTHETIC_REPLAY",
        ))
    return payloads


def fixture_dataset_hash(n_sessions: int = N_SESSIONS) -> str:
    """Canonical digest of the full fixture bar set (documented recipe)."""
    payload = {
        "name": FIXTURE_NAME,
        "bars": sorted(
            ({
                "asset_id": b.asset_id,
                "ts_event_utc": b.ts_event_utc,
                "ts_available_utc": b.ts_available_utc,
                "interval": b.interval,
                "open": b.open, "high": b.high, "low": b.low,
                "close": b.close, "volume": b.volume,
                "source": b.source, "adjustment": b.adjustment.value,
                "quality": b.quality,
            }
            for b in build_fixture_bars(n_sessions)),
            key=lambda r: (r["asset_id"], str(r["ts_event_utc"]))),
        "actions": [],
    }
    return canonical_digest(payload)


FIXTURE_DATASET_HASH = fixture_dataset_hash()
