"""Historical membership, delisting and ticker-mapping model.

Point-in-time universes come **only** from historical membership records:
(today's constituent list is never substituted for a past date). Delisted
symbols never silently disappear; ticker reuse (same symbol with
non-contiguous listing intervals) is detected and surfaced, never merged.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass


class MembershipError(ValueError):
    pass


def _require_utc(value: object, label: str) -> dt.datetime:
    if not isinstance(value, dt.datetime) or value.tzinfo is None:
        raise MembershipError(f"{label} must be a timezone-aware datetime")
    return value


@dataclass(frozen=True)
class MembershipRecord:
    """One interval of index membership: ``symbol`` was a member of
    ``index_id`` from ``effective_from`` until ``effective_to`` (open end =
    still a member). ``announced_at``/``available_at`` capture when the
    change became usable, independently of its effective date."""

    index_id: str
    symbol: str
    effective_from: dt.datetime
    effective_to: dt.datetime | None
    announced_at: dt.datetime
    available_at: dt.datetime
    source: str

    def __post_init__(self) -> None:
        _require_utc(self.effective_from, "effective_from")
        _require_utc(self.announced_at, "announced_at")
        _require_utc(self.available_at, "available_at")
        if self.effective_to is not None:
            _require_utc(self.effective_to, "effective_to")
            if self.effective_to < self.effective_from:
                raise MembershipError(f"effective_to before effective_from for {self.symbol}")


@dataclass(frozen=True)
class DelistingRecord:
    """A symbol's listing interval ending in delisting (or still active).
    ``successor_ticker`` records renames/mappings; ticker reuse shows up as
    two DelistingRecords with the same symbol and non-contiguous intervals."""

    symbol: str
    venue: str
    listed_from: dt.datetime
    listed_to: dt.datetime | None
    delisted_at: dt.datetime | None
    successor_ticker: str | None
    source: str

    def __post_init__(self) -> None:
        _require_utc(self.listed_from, "listed_from")
        if self.listed_to is not None:
            _require_utc(self.listed_to, "listed_to")
        if self.delisted_at is not None:
            _require_utc(self.delisted_at, "delisted_at")
        if self.delisted_at is not None and self.listed_to is None:
            raise MembershipError(f"delisted_at without listed_to for {self.symbol}")


class MembershipTable:
    """In-memory, immutable-after-build membership + delisting store."""

    def __init__(
        self,
        membership: list[MembershipRecord],
        delistings: list[DelistingRecord],
    ) -> None:
        self._membership = tuple(membership)
        self._delistings = tuple(delistings)
        self._validate()

    def _validate(self) -> None:
        seen: set[tuple[str, str, dt.datetime]] = set()
        for rec in self._membership:
            key = (rec.index_id, rec.symbol, rec.effective_from)
            if key in seen:
                raise MembershipError(f"duplicate membership interval: {key}")
            seen.add(key)
        for rec in self._delistings:
            if rec.delisted_at is None and rec.listed_to is None:
                continue  # active listing — fine
        self._reused_tickers = self._detect_ticker_reuse()

    def _detect_ticker_reuse(self) -> dict[str, list[DelistingRecord]]:
        by_symbol: dict[str, list[DelistingRecord]] = {}
        for rec in self._delistings:
            by_symbol.setdefault(rec.symbol, []).append(rec)
        reused: dict[str, list[DelistingRecord]] = {}
        for symbol, recs in by_symbol.items():
            if len(recs) < 2:
                continue
            recs = sorted(recs, key=lambda r: r.listed_from)
            for earlier, later in zip(recs, recs[1:]):
                end = earlier.listed_to
                if end is not None and later.listed_from < end:
                    raise MembershipError(
                        f"overlapping listing intervals for reused ticker {symbol}"
                    )
            reused[symbol] = recs
        return reused

    # -- queries ---------------------------------------------------------------

    @property
    def reused_tickers(self) -> dict[str, list[DelistingRecord]]:
        """Symbols whose ticker was assigned more than once over time."""
        return dict(self._reused_tickers)

    def universe_asof(self, asof: dt.datetime, index_id: str) -> frozenset[str]:
        """Members of ``index_id`` as visible at ``asof``.

        Point-in-time rule: a membership interval counts only if the change
        was already *available* (``available_at <= asof``) and the effective
        interval covers ``asof``. Today's composition is never consulted.
        """
        _require_utc(asof, "asof")
        members: set[str] = set()
        for rec in self._membership:
            if rec.index_id != index_id:
                continue
            if rec.available_at > asof:
                continue  # not yet usable at the decision time
            if rec.effective_from > asof:
                continue
            if rec.effective_to is not None and rec.effective_to <= asof:
                continue
            members.add(rec.symbol)
        return frozenset(members)

    def delisted_symbols(self, asof: dt.datetime) -> frozenset[str]:
        """Symbols delisted on or before ``asof`` — they must remain part of
        any historical universe; silently dropping them is survivorship bias."""
        _require_utc(asof, "asof")
        return frozenset(
            rec.symbol
            for rec in self._delistings
            if rec.delisted_at is not None and rec.delisted_at <= asof
        )

    def mapping_for(self, symbol: str, asof: dt.datetime) -> str | None:
        """Successor ticker mapping known as of ``asof`` (renames, rebrands)."""
        _require_utc(asof, "asof")
        result: str | None = None
        for rec in self._delistings:
            if rec.symbol != symbol or rec.delisted_at is None or rec.delisted_at > asof:
                continue
            if rec.successor_ticker is not None:
                result = rec.successor_ticker
        return result


__all__ = [
    "DelistingRecord",
    "MembershipError",
    "MembershipRecord",
    "MembershipTable",
]
