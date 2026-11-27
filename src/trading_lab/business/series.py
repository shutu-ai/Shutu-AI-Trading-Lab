"""Per-symbol validated PIT series store for the Business MVP (B1).

The store admits ``MarketBar`` contract objects and exposes ONLY
information-availability accessors: a bar exists for decisions at
``asof`` when ``ts_available_utc <= asof`` (next-open availability —
``ts_event_utc`` alone is NOT enough; information that cannot yet be
acted on must not enter features). Series are stored per symbol and are
NEVER crossed or concatenated: no accessor mixes symbols.

Validation is fail-closed on build: strictly-increasing ``ts_event``,
no duplicates, positive prices, ``low <= high`` and a fixed quality
vocabulary. ``admission_summary()`` recomputes a content digest over the
admitted bar fields themselves — no manifest is trusted.

``load_bars_jsonl`` accepts future local-snapshot input: strict
per-line contract validation (unknown keys / missing fields / float
prices refused), never best-effort.
"""

from __future__ import annotations

import datetime as dt
from bisect import bisect_right
from collections.abc import Mapping, Sequence
from pathlib import Path

from pydantic import ValidationError

from trading_lab.backtest.arms import SyntheticDataset
from trading_lab.contracts import MarketBar
from trading_lab.security.canonical import canonical_digest

__all__ = [
    "PIT_LEVEL",
    "PURPOSE_LABEL",
    "QUALITY_SYNTHETIC_OK",
    "QUALITY_SYNTHETIC_STALE",
    "QUALITY_VOCABULARY",
    "SeriesStore",
    "SeriesStoreError",
    "ensure_utc_instant",
    "load_bars_jsonl",
]

#: fixed quality vocabulary for the demo pipeline — anything else is
#: refused at admission (fail closed, never "pass through unknown labels")
QUALITY_SYNTHETIC_OK = "SYNTHETIC_OK"
QUALITY_SYNTHETIC_STALE = "SYNTHETIC_STALE"
QUALITY_VOCABULARY = frozenset({QUALITY_SYNTHETIC_OK, QUALITY_SYNTHETIC_STALE})

PURPOSE_LABEL = "BUSINESS_MVP_DEMO"
PIT_LEVEL = "SYNTHETIC"

_BAR_FIELDS: tuple[str, ...] = (
    "asset_id", "ts_event_utc", "ts_available_utc", "interval",
    "open", "high", "low", "close", "volume", "source",
    "adjustment", "quality",
)

_PRICE_FIELDS = ("open", "high", "low", "close")


class SeriesStoreError(ValueError):
    """Series admission / access failure — fail closed."""


def ensure_utc_instant(asof: dt.datetime) -> dt.datetime:
    """Accept only timezone-aware instants; normalize to UTC."""
    if not isinstance(asof, dt.datetime):
        raise SeriesStoreError(f"asof must be a datetime, got {type(asof)!r}")
    if asof.tzinfo is None or asof.tzinfo.utcoffset(asof) is None:
        raise SeriesStoreError("asof must be timezone-aware (naive refused)")
    return asof.astimezone(dt.timezone.utc)


def load_bars_jsonl(path: Path) -> tuple[MarketBar, ...]:
    """Load a JSONL file of MarketBar contracts, one JSON object per line.

    Strict per-line validation: unknown keys, missing fields, float
    financial values or any malformed line raise :class:`SeriesStoreError`
    with the offending line number. Blank lines are skipped; everything
    else must parse or the whole load fails (never best-effort).
    """
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SeriesStoreError(f"cannot read bars file {path}: {exc}") from exc
    bars: list[MarketBar] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            bars.append(MarketBar.model_validate_json(line))
        except ValidationError as exc:
            raise SeriesStoreError(
                f"{path}: line {lineno}: invalid MarketBar JSON: {exc}"
            ) from exc
    return tuple(bars)


def _validate_series(symbol: str, series: Sequence[MarketBar]) -> None:
    """Admission checks over one symbol's series (defense-in-depth on top
    of the MarketBar contract itself; contract-valid input can still be
    series-invalid)."""
    if not series:
        raise SeriesStoreError(f"symbol {symbol!r}: empty series refused")
    prev_event: dt.datetime | None = None
    for bar in series:
        if bar.quality not in QUALITY_VOCABULARY:
            raise SeriesStoreError(
                f"symbol {symbol!r}: quality {bar.quality!r} outside fixed "
                f"vocabulary {sorted(QUALITY_VOCABULARY)}")
        if bar.asset_id != symbol:
            raise SeriesStoreError(
                f"symbol {symbol!r}: bar asset_id {bar.asset_id!r} mismatch")
        if prev_event is not None and bar.ts_event_utc <= prev_event:
            raise SeriesStoreError(
                f"symbol {symbol!r}: ts_event_utc not strictly increasing "
                f"({bar.ts_event_utc} after {prev_event})")
        prev_event = bar.ts_event_utc
        if bar.low > bar.high:
            raise SeriesStoreError(f"symbol {symbol!r}: low > high at {bar.ts_event_utc}")
        for field in _PRICE_FIELDS:
            if getattr(bar, field) <= 0:
                raise SeriesStoreError(
                    f"symbol {symbol!r}: non-positive {field} at {bar.ts_event_utc}")


class SeriesStore:
    """Immutable per-symbol store of validated MarketBar series.

    Constructed once from admitted bars; no mutators exist. The internal
    reference calendar (union of admitted session dates) is metadata used
    only for staleness counting — it never feeds per-symbol feature data.
    """

    def __init__(self, bars_by_symbol: Mapping[str, Sequence[MarketBar]]) -> None:
        series_map: dict[str, tuple[MarketBar, ...]] = {}
        for symbol, series in bars_by_symbol.items():
            _validate_series(symbol, series)
            series_map[symbol] = tuple(series)
        if not series_map:
            raise SeriesStoreError("SeriesStore requires at least one symbol series")
        self._series: dict[str, tuple[MarketBar, ...]] = series_map
        calendar = sorted({
            bar.ts_event_utc.date()
            for series in series_map.values() for bar in series
        })
        self._calendar: tuple[dt.date, ...] = tuple(calendar)
        self._calendar_set: frozenset[dt.date] = frozenset(calendar)

    # ------------------------------------------------------------------
    # constructors
    # ------------------------------------------------------------------

    @classmethod
    def from_dataset(cls, dataset: SyntheticDataset) -> "SeriesStore":
        """Build from a ``SyntheticDataset`` (per-symbol bar series)."""
        return cls(dataset.bars)

    @classmethod
    def from_bars(cls, bars: Sequence[MarketBar]) -> "SeriesStore":
        """Build from a flat bar sequence, grouped by ``asset_id``."""
        grouped: dict[str, list[MarketBar]] = {}
        for bar in bars:
            grouped.setdefault(bar.asset_id, []).append(bar)
        return cls({sym: tuple(seq) for sym, seq in grouped.items()})

    # ------------------------------------------------------------------
    # read-only surface
    # ------------------------------------------------------------------

    @property
    def symbols(self) -> tuple[str, ...]:
        return tuple(sorted(self._series))

    @property
    def calendar_dates(self) -> tuple[dt.date, ...]:
        """Union session calendar (all admitted symbols), sorted."""
        return self._calendar

    def _series_of(self, symbol: str) -> tuple[MarketBar, ...]:
        """A symbol never admitted to the store reads as an empty series
        (an unadmitted symbol and a symbol with no data yet are the same
        honest state: NO_DATA downstream) — never an exception."""
        return self._series.get(symbol, ())

    def available(self, symbol: str, asof: dt.datetime) -> list[MarketBar]:
        """Bars INFORMATION-available at ``asof``: ts_available_utc <= asof.

        An unknown / never-admitted symbol yields an empty list (the
        honest no-data state); only a naive ``asof`` is refused."""
        asof_utc = ensure_utc_instant(asof)
        return [b for b in self._series_of(symbol) if b.ts_available_utc <= asof_utc]

    def last_available(self, symbol: str, asof: dt.datetime) -> MarketBar | None:
        """Most recent information-available bar, or None before any data."""
        avail = self.available(symbol, asof)
        return avail[-1] if avail else None

    def sessions_since(self, symbol: str, asof: dt.datetime) -> int | None:
        """Staleness in session dates: sessions strictly after the last
        available bar's session up to and including the asof session.

        Reference calendar = union of admitted session dates (plus the
        asof session itself, which is always an elapsed decision session).
        A date on which NO admitted symbol has a bar is invisible to this
        store — disclosed via ``admission_summary()["calendar_sessions"]``.
        Returns None when the symbol has no available bars at all.
        """
        asof_utc = ensure_utc_instant(asof)
        last = self.last_available(symbol, asof_utc)
        if last is None:
            return None
        last_date = last.ts_event_utc.date()
        asof_date = asof_utc.date()
        count = (bisect_right(self._calendar, asof_date)
                 - bisect_right(self._calendar, last_date))
        if asof_date > last_date and asof_date not in self._calendar_set:
            count += 1
        return max(count, 0)

    # ------------------------------------------------------------------
    # admission record
    # ------------------------------------------------------------------

    def admission_summary(self) -> dict[str, object]:
        """Recomputed admission record: content digest over the admitted
        bar fields themselves (no manifest trusted), purpose / PIT level
        labels, per-symbol counts and session span."""
        rows = [
            {field: getattr(bar, field) for field in _BAR_FIELDS}
            for symbol in sorted(self._series)
            for bar in self._series[symbol]
        ]
        rows.sort(key=lambda row: (row["asset_id"], row["ts_event_utc"]))
        quality_counts: dict[str, int] = {}
        for row in rows:
            quality = str(row["quality"])
            quality_counts[quality] = quality_counts.get(quality, 0) + 1
        calendar = self._calendar
        return {
            "purpose": PURPOSE_LABEL,
            "pit_level": PIT_LEVEL,
            "content_digest": canonical_digest(rows),
            "n_symbols": len(self._series),
            "bars_per_symbol": {
                symbol: len(self._series[symbol]) for symbol in sorted(self._series)
            },
            "calendar_sessions": len(calendar),
            "session_span": {
                "first": calendar[0].isoformat(),
                "last": calendar[-1].isoformat(),
            },
            "quality_counts": quality_counts,
        }
