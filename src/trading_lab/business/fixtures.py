"""Deterministic synthetic demo dataset for the Business MVP (V0.1).

SYNTHETIC_OFFLINE_ONLY: this fixture fabricates a two-symbol daily
dataset (SPY/QQQ look-alikes) over a synthetic Mon-Fri calendar starting
2024-01-02. It is NOT the frozen NYSE calendar (no holiday gaps) and NOT
real market data: every bar carries ``source="SYNTHETIC"`` and quality
labels from {SYNTHETIC_OK, SYNTHETIC_STALE}.

Determinism contract: the same ``BusinessConfig`` produces byte-identical
bars and therefore the same ``dataset_hash``. All randomness comes from
seeded ``random.Random`` streams — one walk stream per symbol (seed +
stable symbol offset) plus one per-symbol anomaly stream for the
DATA_QUALITY segment; there is no wall-clock anywhere.

Timeline semantics (next-open availability):

- ``ts_event_utc``   = session date 21:00 UTC (synthetic close)
- ``ts_available_utc`` = NEXT session date 13:30 UTC; the final session's
  bar becomes available the next business day 13:30.

The DATA_QUALITY segment plants reproducible defects derived from the
seeded RNG (never hardcoded dates): scattered dropped SPY sessions, a
contiguous missing QQQ window, and a run of SPY stale bars whose close
equals the previous close. The ``qqq_gap`` flag rebuilds the same random
paths with only the QQQ window emitted — the sanctioned control construct
for per-symbol-independence tests (SPY's streams are untouched by the
flag; QQQ shares closes/volumes/timestamps on every emitted session).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import math
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from types import MappingProxyType

from trading_lab.backtest.arms import SyntheticDataset
from trading_lab.business.config import BusinessConfig, FixtureConfig
from trading_lab.business.series import (
    QUALITY_SYNTHETIC_OK,
    QUALITY_SYNTHETIC_STALE,
)
from trading_lab.contracts import AdjustmentKind, MarketBar

__all__ = [
    "DemoDataset",
    "SEGMENT_TAGS",
    "build_demo_dataset",
]

UTC = dt.timezone.utc
CENT = Decimal("0.01")
SESSION_EVENT_TIME = dt.time(21, 0)
SESSION_AVAILABLE_TIME = dt.time(13, 30)
CALENDAR_START = dt.date(2024, 1, 2)
INTERVAL = "1d"
SOURCE = "SYNTHETIC"
VOLUME_BASE = Decimal("1000000")
VOLUME_NOISE = Decimal("0.20")
TICK_PCT = Decimal("0.001")
MIN_TICK = CENT

N_DROP_SESSIONS = 6
STALE_RUN_LEN = 4
QQQ_GAP_LEN = 10
#: segment 7 (0-based index 6) carries the planted data-quality defects
DATA_QUALITY_SEGMENT_INDEX = 6

#: tags aligned 1:1 with ``FixtureConfig.sessions_per_segment`` order
SEGMENT_TAGS: tuple[str, ...] = (
    "WARMUP_RANGE", "UPTREND", "RANGE", "DOWNTREND",
    "HIGH_VOL", "MILD_UPTREND", "DATA_QUALITY", "RANGE_TAIL",
)
DATASET_NAME = "business_mvp_demo"

#: minimum DATA_QUALITY length that keeps every anomaly placement
#: satisfiable (stale run + predecessor protected, 6 drops, 10-session gap)
_MIN_DATA_QUALITY_LEN = 21


@dataclass(frozen=True)
class _SegmentSpec:
    """Fixed segment priors (declared here, never fitted on replay data)."""

    tag: str
    drift: Decimal
    vol: Decimal
    volume_mult: Decimal = Decimal("1")


_SEGMENT_SPECS: dict[str, _SegmentSpec] = {
    "WARMUP_RANGE": _SegmentSpec("WARMUP_RANGE", Decimal("0"), Decimal("0.007")),
    "UPTREND": _SegmentSpec("UPTREND", Decimal("0.004"), Decimal("0.008")),
    "RANGE": _SegmentSpec("RANGE", Decimal("0"), Decimal("0.007")),
    "DOWNTREND": _SegmentSpec("DOWNTREND", Decimal("-0.005"), Decimal("0.012")),
    "HIGH_VOL": _SegmentSpec("HIGH_VOL", Decimal("0"), Decimal("0.030"), Decimal("1.8")),
    "MILD_UPTREND": _SegmentSpec("MILD_UPTREND", Decimal("0.0015"), Decimal("0.008")),
    "DATA_QUALITY": _SegmentSpec("DATA_QUALITY", Decimal("0"), Decimal("0.007")),
    "RANGE_TAIL": _SegmentSpec("RANGE_TAIL", Decimal("0"), Decimal("0.007")),
}

_EMPTY_ANOMALIES = frozenset[int]()


@dataclass(frozen=True)
class DemoDataset:
    """The demo fixture: hash-bound dataset + reporting metadata.

    ``dataset.dataset_hash`` is recomputed by ``SyntheticDataset`` from the
    bars themselves — two builds from one config always agree.
    """

    dataset: SyntheticDataset
    scenario_tags: Mapping[str, str]             # "YYYY-MM-DD" -> segment tag
    session_dates: tuple[dt.date, ...]
    spy_drop_dates: tuple[dt.date, ...] = ()
    spy_stale_dates: tuple[dt.date, ...] = ()
    qqq_gap_dates: tuple[dt.date, ...] = ()

    def next_open_price(self, symbol: str, session_date: dt.date) -> Decimal | None:
        """Open of the symbol's first bar STRICTLY AFTER ``session_date``
        (next-open fill valuation for mock execution). None when no later
        bar exists (e.g. the final session) or the symbol is unknown."""
        for bar in self.dataset.bars.get(symbol, ()):
            if bar.ts_event_utc.date() > session_date:
                return bar.open
        return None


# ---------------------------------------------------------------------------
# calendar + time helpers (pure functions of the session index)
# ---------------------------------------------------------------------------


def _synthetic_calendar(n_sessions: int) -> list[dt.date]:
    """Mon-Fri only synthetic business days from CALENDAR_START."""
    if n_sessions <= 0:
        raise ValueError("n_sessions must be positive")
    dates: list[dt.date] = []
    day = CALENDAR_START
    while len(dates) < n_sessions:
        if day.weekday() < 5:
            dates.append(day)
        day += dt.timedelta(days=1)
    return dates


def _next_business_day(day: dt.date) -> dt.date:
    candidate = day + dt.timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += dt.timedelta(days=1)
    return candidate


def _event_ts(session_date: dt.date) -> dt.datetime:
    return dt.datetime.combine(session_date, SESSION_EVENT_TIME, tzinfo=UTC)


def _available_ts(dates: Sequence[dt.date], index: int) -> dt.datetime:
    """NEXT session date 13:30; the final bar lands next business day."""
    nxt = dates[index + 1] if index + 1 < len(dates) else _next_business_day(dates[-1])
    return dt.datetime.combine(nxt, SESSION_AVAILABLE_TIME, tzinfo=UTC)


def _stable_offset(symbol: str) -> int:
    """Run-to-run stable symbol offset (never ``hash()``, which is
    randomized per process for str)."""
    digest = hashlib.sha256(symbol.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def _normal(rng: random.Random) -> float:
    """Standard normal from two uniforms (Box-Muller) — deterministic
    given the seeded stream; independent of ``random.gauss`` internals."""
    u1 = 1.0 - rng.random()          # in (0, 1]
    u2 = rng.random()
    return math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)


def _tick(close: Decimal) -> Decimal:
    candidate = (close * TICK_PCT).quantize(CENT, rounding=ROUND_HALF_EVEN)
    return candidate if candidate >= MIN_TICK else MIN_TICK


# ---------------------------------------------------------------------------
# config validation + segment map
# ---------------------------------------------------------------------------


def _start_price(fixture: FixtureConfig, symbol: str) -> Decimal:
    starts = {"SPY": fixture.start_price_spy, "QQQ": fixture.start_price_qqq}
    price = starts.get(symbol)
    if price is None or price <= 0:
        raise ValueError(
            f"symbol {symbol!r} has no positive start price in FixtureConfig")
    return price


def _validate_fixture(fixture: FixtureConfig) -> None:
    if not fixture.symbols or len(set(fixture.symbols)) != len(fixture.symbols):
        raise ValueError("fixture symbols must be non-empty and unique")
    lengths = fixture.sessions_per_segment
    if len(lengths) != len(SEGMENT_TAGS):
        raise ValueError(
            f"sessions_per_segment must have {len(SEGMENT_TAGS)} entries, "
            f"got {len(lengths)}")
    if any(n <= 0 for n in lengths):
        raise ValueError("every segment needs at least one session")
    if lengths[DATA_QUALITY_SEGMENT_INDEX] < _MIN_DATA_QUALITY_LEN:
        raise ValueError(
            f"DATA_QUALITY segment must have >= {_MIN_DATA_QUALITY_LEN} "
            "sessions to host the planted anomalies")


def _segment_of_index(
    lengths: tuple[int, ...],
) -> tuple[_SegmentSpec, ...]:
    """Per-SESSION segment specs (one entry per session, segments expanded)."""
    return tuple(
        _SEGMENT_SPECS[SEGMENT_TAGS[i]]
        for i, n in enumerate(lengths) for _ in range(n)
    )


# ---------------------------------------------------------------------------
# DATA_QUALITY anomaly placement (RNG-derived, never hardcoded dates)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Anomalies:
    """Global session indices whose bars are dropped or stale."""

    skip: frozenset[int] = _EMPTY_ANOMALIES
    stale: frozenset[int] = _EMPTY_ANOMALIES


def _anomaly_placements(
    seed: int,
    symbols: tuple[str, ...],
    seg_len: int,
    seg_offset: int,
) -> dict[str, _Anomalies]:
    """Draw anomaly positions from per-symbol anomaly streams.

    The QQQ gap window is ALWAYS drawn (so downstream streams and SPY's
    drop placement are independent of whether the gap is applied); the
    ``qqq_gap`` flag only decides whether QQQ emits those bars.
    SPY drops never land on gap-window sessions, so the shared union
    calendar keeps every gap session visible (clean staleness signal).
    """
    placements: dict[str, _Anomalies] = {}
    gap_window: frozenset[int] = _EMPTY_ANOMALIES
    if "QQQ" in symbols:
        rng_qqq = random.Random(f"{seed}:QQQ:anomalies")
        gap_start = rng_qqq.randint(0, seg_len - QQQ_GAP_LEN)
        gap_window = frozenset(
            seg_offset + i for i in range(gap_start, gap_start + QQQ_GAP_LEN))
        placements["QQQ"] = _Anomalies(skip=gap_window)
    if "SPY" in symbols:
        rng_spy = random.Random(f"{seed}:SPY:anomalies")
        run_start = rng_spy.randint(1, seg_len - STALE_RUN_LEN - 1)
        stale = frozenset(
            seg_offset + i for i in range(run_start, run_start + STALE_RUN_LEN))
        protected = set(range(run_start - 1, run_start + STALE_RUN_LEN))
        eligible = [
            i for i in range(seg_len)
            if i not in protected and (seg_offset + i) not in gap_window
        ]
        if len(eligible) < N_DROP_SESSIONS:
            raise ValueError("not enough eligible sessions for SPY drops")
        drops = sorted(rng_spy.sample(eligible, N_DROP_SESSIONS))
        placements["SPY"] = _Anomalies(
            skip=frozenset(seg_offset + i for i in drops), stale=stale)
    return placements


def _dates_of(dates: Sequence[dt.date], indices: frozenset[int]) -> tuple[dt.date, ...]:
    return tuple(sorted(dates[i] for i in indices))


# ---------------------------------------------------------------------------
# per-symbol path + bar emission
# ---------------------------------------------------------------------------


def _walk_closes(
    fixture: FixtureConfig,
    symbol: str,
    segments: tuple[_SegmentSpec, ...],
    rng: random.Random,
) -> tuple[list[Decimal], list[Decimal]]:
    """Full-path geometric walk: one (return, volume-noise) draw pair per
    session, computed for EVERY session even when the bar is later
    dropped — the internal path is continuous; dropped sessions are
    missing records, not missing path points."""
    closes: list[Decimal] = []
    volumes: list[Decimal] = []
    prev = _start_price(fixture, symbol)
    for spec in segments:
        z_ret = _normal(rng)
        # volume noise is clamped so volumes stay positive-bounded
        # (factor in [1 - 2*VOLUME_NOISE, 1 + 2*VOLUME_NOISE])
        z_vol = max(-2.0, min(2.0, _normal(rng)))
        factor = Decimal(1) + spec.drift + spec.vol * Decimal(repr(z_ret))
        new_close = (prev * factor).quantize(CENT, rounding=ROUND_HALF_EVEN)
        if new_close <= 0:                      # degenerate guard, not expected
            new_close = prev.quantize(CENT, rounding=ROUND_HALF_EVEN)
        closes.append(new_close)
        prev = new_close
        volume = VOLUME_BASE * (Decimal(1) + VOLUME_NOISE * Decimal(repr(z_vol)))
        if spec.volume_mult != Decimal(1):
            volume = volume * spec.volume_mult
        volumes.append(volume.to_integral_value(rounding=ROUND_HALF_EVEN))
    return closes, volumes


def _build_symbol_bars(
    fixture: FixtureConfig,
    symbol: str,
    dates: list[dt.date],
    segments: tuple[_SegmentSpec, ...],
    anomalies: _Anomalies,
) -> tuple[MarketBar, ...]:
    rng = random.Random(fixture.seed + _stable_offset(symbol))
    closes, volumes = _walk_closes(fixture, symbol, segments, rng)
    bars: list[MarketBar] = []
    prev_close_recorded = _start_price(fixture, symbol)
    for i, session_date in enumerate(dates):
        if i in anomalies.skip:
            continue
        # gapless synthetic opens: every emitted bar opens at the previous
        # emitted bar's close; stale bars additionally freeze the close
        close_i = prev_close_recorded if i in anomalies.stale else closes[i]
        open_i = prev_close_recorded
        tick = _tick(close_i)
        high_i = max(open_i, close_i) + tick
        low_i = max(min(open_i, close_i) - tick, MIN_TICK)
        quality = QUALITY_SYNTHETIC_STALE if i in anomalies.stale \
            else QUALITY_SYNTHETIC_OK
        bars.append(MarketBar(
            asset_id=symbol,
            ts_event_utc=_event_ts(session_date),
            ts_available_utc=_available_ts(dates, i),
            interval=INTERVAL,
            open=open_i,
            high=high_i,
            low=low_i,
            close=close_i,
            volume=volumes[i],
            source=SOURCE,
            adjustment=AdjustmentKind.RAW,
            quality=quality,
        ))
        prev_close_recorded = close_i
    return tuple(bars)


# ---------------------------------------------------------------------------
# public builder
# ---------------------------------------------------------------------------


def build_demo_dataset(
    config: BusinessConfig,
    *,
    qqq_gap: bool = True,
) -> DemoDataset:
    """Deterministically build the demo dataset from ``config``.

    ``qqq_gap=False`` restores ONLY the QQQ missing window (the sanctioned
    control construct for per-symbol-independence tests). Both builds draw
    identical random streams, so SPY's bars are identical and QQQ shares
    the same underlying price path (identical closes, volumes and
    timestamps on every shared session); only opens of bars following the
    window differ, because gapless opens anchor to the last EMITTED close.
    ``DemoDataset.qqq_gap_dates`` reports the DRAWN gap window in both
    builds — the window that was emitted or withheld, respectively.
    """
    fixture = config.fixture
    _validate_fixture(fixture)
    dates = _synthetic_calendar(sum(fixture.sessions_per_segment))
    segments = _segment_of_index(fixture.sessions_per_segment)
    dq_offset = sum(fixture.sessions_per_segment[:DATA_QUALITY_SEGMENT_INDEX])
    dq_len = fixture.sessions_per_segment[DATA_QUALITY_SEGMENT_INDEX]
    placements = _anomaly_placements(
        fixture.seed, fixture.symbols, dq_len, dq_offset)
    spy = placements.get("SPY", _Anomalies())
    emitted = dict(placements)
    if not qqq_gap:
        # control build: the gap window was still DRAWN above (keeping SPY
        # placement and every random stream untouched) but QQQ emits it
        emitted["QQQ"] = _Anomalies()
    bars_by_symbol = {
        symbol: _build_symbol_bars(
            fixture, symbol, dates, segments,
            emitted.get(symbol, _Anomalies()))
        for symbol in fixture.symbols
    }
    dataset = SyntheticDataset(name=DATASET_NAME, bars=bars_by_symbol)
    tags: dict[str, str] = {
        session_date.isoformat(): spec.tag
        for session_date, spec in zip(dates, segments)
    }
    return DemoDataset(
        dataset=dataset,
        scenario_tags=MappingProxyType(tags),
        session_dates=tuple(dates),
        spy_drop_dates=_dates_of(dates, spy.skip),
        spy_stale_dates=_dates_of(dates, spy.stale),
        qqq_gap_dates=_dates_of(dates, placements.get("QQQ", _Anomalies()).skip),
    )
