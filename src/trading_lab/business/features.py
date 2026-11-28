"""PIT feature computation for the Business MVP (B1).

``FeatureEngine.compute()`` derives one :class:`FeatureVector` per symbol
per decision clock, using ONLY bars whose ``ts_available_utc <= asof``
(next-open information availability — the no-lookahead property is
structural: nothing else is readable). All arithmetic is ``Decimal``;
every derived value is quantized to 8 decimal places (ROUND_HALF_EVEN)
so ``feature_hash`` is stable across runs and platforms.

Indicators are textbook definitions with fixed windows from
``FeaturesConfig`` — no fitting, no lookahead:

- MA(short/long): simple means of the last N closes.
- RSI(period): Wilder smoothing; 0..100.
- ATR(period): Wilder smoothing over the true range triple.
- realized_vol: sqrt of the mean of squared per-session simple returns.
- volume_ratio: last volume / mean(volume window).
- corr_other: Pearson over common session dates of both symbols'
  information-available closes within ``corr_window`` (per-symbol series
  are aligned by session date only — never concatenated).

Honesty rule: stale closes are still usable prices (a stale bar simply
produces a 0 return); staleness is reported via ``asof_bar_age_sessions``
and the ``STALE_DATA`` reason, never hidden. An ``UNKNOWN`` status vector
may carry decidable values, but consumers must not use it.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from decimal import ROUND_HALF_EVEN, Decimal

from trading_lab.business.config import FeaturesConfig
from trading_lab.business.series import SeriesStore, ensure_utc_instant
from trading_lab.business.types import (
    STATUS_OK,
    STATUS_UNKNOWN,
    FeatureVector,
)
from trading_lab.contracts import MarketBar
from trading_lab.security.canonical import canonical_digest

__all__ = [
    "REASON_INSUFFICIENT_CORR_SAMPLE",
    "REASON_NO_DATA",
    "REASON_STALE_DATA",
    "REASON_WARMUP_PENDING",
    "FeatureEngine",
]

REASON_WARMUP_PENDING = "WARMUP_PENDING"
REASON_STALE_DATA = "STALE_DATA"
REASON_NO_DATA = "NO_DATA"
REASON_INSUFFICIENT_CORR_SAMPLE = "INSUFFICIENT_CORR_SAMPLE"

_Q8 = Decimal("0.00000001")
_ZERO = Decimal(0)
_ONE = Decimal(1)
_HUNDRED = Decimal(100)


def _quant(value: Decimal) -> Decimal:
    return value.quantize(_Q8, rounding=ROUND_HALF_EVEN)


def _opt_str(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


# ---------------------------------------------------------------------------
# indicator primitives (pure Decimal functions, deterministic)
# ---------------------------------------------------------------------------


def _returns_1d(closes: Sequence[Decimal]) -> Decimal | None:
    if len(closes) < 2:
        return None
    return _quant(closes[-1] / closes[-2] - _ONE)


def _sma(closes: Sequence[Decimal], window: int) -> Decimal | None:
    if len(closes) < window:
        return None
    return _quant(sum(closes[-window:], _ZERO) / window)


def _rsi_wilder(closes: Sequence[Decimal], period: int) -> Decimal | None:
    if len(closes) < period + 1:
        return None
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [d if d > _ZERO else _ZERO for d in deltas]
    losses = [-d if d < _ZERO else _ZERO for d in deltas]
    avg_gain = sum(gains[:period], _ZERO) / period
    avg_loss = sum(losses[:period], _ZERO) / period
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == _ZERO:
        return _quant(_HUNDRED)
    rs = avg_gain / avg_loss
    return _quant(_HUNDRED - _HUNDRED / (_ONE + rs))


def _atr_wilder(bars: Sequence[MarketBar], period: int) -> Decimal | None:
    if len(bars) < period + 1:
        return None
    true_ranges = [
        max(bar.high - bar.low,
            abs(bar.high - prev.close),
            abs(bar.low - prev.close))
        for prev, bar in zip(bars, bars[1:])
    ]
    atr = sum(true_ranges[:period], _ZERO) / period
    for tr in true_ranges[period:]:
        atr = (atr * (period - 1) + tr) / period
    return _quant(atr)


def _realized_vol(closes: Sequence[Decimal], window: int) -> Decimal | None:
    if len(closes) < window + 1:
        return None
    rets = [closes[i] / closes[i - 1] - _ONE
            for i in range(len(closes) - window, len(closes))]
    mean_sq = sum((r * r for r in rets), _ZERO) / window
    return _quant(mean_sq.sqrt())


def _volume_ratio(bars: Sequence[MarketBar], window: int) -> Decimal | None:
    if len(bars) < window:
        return None
    volumes = [bar.volume for bar in bars[-window:]]
    mean_volume = sum(volumes, _ZERO) / window
    if mean_volume == _ZERO:
        return None
    return _quant(bars[-1].volume / mean_volume)


def _pearson(xs: Sequence[Decimal], ys: Sequence[Decimal]) -> Decimal | None:
    n = len(xs)
    if n < 2 or n != len(ys):
        return None
    mean_x = sum(xs, _ZERO) / n
    mean_y = sum(ys, _ZERO) / n
    sxy = sum(((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)), _ZERO)
    sxx = sum(((x - mean_x) ** 2 for x in xs), _ZERO)
    syy = sum(((y - mean_y) ** 2 for y in ys), _ZERO)
    if sxx == _ZERO or syy == _ZERO:
        return None                      # degenerate: zero variance series
    return _quant(sxy / (sxx * syy).sqrt())


# ---------------------------------------------------------------------------
# engine
# ---------------------------------------------------------------------------


class FeatureEngine:
    """Computes one FeatureVector per (symbol, asof) from PIT series."""

    def __init__(self, config: FeaturesConfig) -> None:
        self._cfg = config

    def compute(
        self,
        symbol: str,
        asof: dt.datetime,
        store: SeriesStore,
        other_store: SeriesStore | None = None,
    ) -> FeatureVector:
        """PIT features for ``symbol`` at decision clock ``asof``.

        Uses only ``store.available(symbol, asof)``; when ``other_store``
        is given, ``corr_other`` aligns the lexicographically-first other
        symbol's information-available closes by session date (unambiguous
        for the demo two-symbol universe).
        """
        asof_utc = ensure_utc_instant(asof)
        bars = store.available(symbol, asof_utc)
        reasons: list[str] = []
        if not bars:
            return self._assemble(
                symbol=symbol, asof_utc=asof_utc, last_ts=None, age=None,
                returns_1d=None, ma_short=None, ma_long=None, rsi=None,
                atr=None, realized_vol=None, volume_ratio=None,
                corr_other=None, warmup_ok=False, status=STATUS_UNKNOWN,
                reasons=(REASON_NO_DATA,))
        closes = [bar.close for bar in bars]
        age = store.sessions_since(symbol, asof_utc)
        warmup_ok = len(closes) >= self._cfg.ma_long
        stale = age is not None and age > self._cfg.stale_after_sessions
        if not warmup_ok:
            reasons.append(REASON_WARMUP_PENDING)
        if stale:
            reasons.append(REASON_STALE_DATA)
        corr_other, corr_reason = self._correlation(
            symbol, asof_utc, bars, other_store)
        if corr_reason is not None:
            reasons.append(corr_reason)
        status = STATUS_OK if (warmup_ok and not stale) else STATUS_UNKNOWN
        return self._assemble(
            symbol=symbol, asof_utc=asof_utc,
            last_ts=bars[-1].ts_event_utc, age=age,
            returns_1d=_returns_1d(closes),
            ma_short=_sma(closes, self._cfg.ma_short),
            ma_long=_sma(closes, self._cfg.ma_long),
            rsi=_rsi_wilder(closes, self._cfg.rsi_period),
            atr=_atr_wilder(bars, self._cfg.atr_period),
            realized_vol=_realized_vol(closes, self._cfg.realized_vol_window),
            volume_ratio=_volume_ratio(bars, self._cfg.volume_window),
            corr_other=corr_other, warmup_ok=warmup_ok, status=status,
            reasons=tuple(reasons))

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _correlation(
        self,
        symbol: str,
        asof_utc: dt.datetime,
        bars: Sequence[MarketBar],
        other_store: SeriesStore | None,
    ) -> tuple[Decimal | None, str | None]:
        if other_store is None:
            return None, None
        others = [s for s in other_store.symbols if s != symbol]
        if not others:
            return None, None
        other_symbol = others[0]
        mine = {b.ts_event_utc.date(): b.close for b in bars}
        theirs = {
            b.ts_event_utc.date(): b.close
            for b in other_store.available(other_symbol, asof_utc)
        }
        common = sorted(set(mine) & set(theirs))[-self._cfg.corr_window:]
        if len(common) < self._cfg.corr_min_common:
            return None, REASON_INSUFFICIENT_CORR_SAMPLE
        return _pearson(
            [mine[d] for d in common], [theirs[d] for d in common]), None

    @staticmethod
    def _feature_hash(
        symbol: str,
        asof_utc: dt.datetime,
        status: str,
        fields: dict[str, Decimal | None],
    ) -> str:
        """canonical_digest over the quantized non-None fields + status +
        asof (symbol included to bind the hash to the series it came from).
        Stable across runs: Decimals render via canonical str form."""
        payload = {
            "symbol": symbol,
            "asof_utc": asof_utc,
            "status": status,
            "features": {name: _opt_str(value)
                         for name, value in sorted(fields.items())},
        }
        return canonical_digest(payload)

    def _assemble(
        self,
        *,
        symbol: str,
        asof_utc: dt.datetime,
        last_ts: dt.datetime | None,
        age: int | None,
        returns_1d: Decimal | None,
        ma_short: Decimal | None,
        ma_long: Decimal | None,
        rsi: Decimal | None,
        atr: Decimal | None,
        realized_vol: Decimal | None,
        volume_ratio: Decimal | None,
        corr_other: Decimal | None,
        warmup_ok: bool,
        status: str,
        reasons: tuple[str, ...],
    ) -> FeatureVector:
        digest = self._feature_hash(symbol, asof_utc, status, {
            "returns_1d": returns_1d,
            "ma_short": ma_short,
            "ma_long": ma_long,
            "rsi": rsi,
            "atr": atr,
            "realized_vol": realized_vol,
            "volume_ratio": volume_ratio,
            "corr_other": corr_other,
        })
        return FeatureVector(
            symbol=symbol,
            asof_utc=asof_utc,
            asof_bar_ts=last_ts,
            asof_bar_age_sessions=age,
            returns_1d=returns_1d,
            ma_short=ma_short,
            ma_long=ma_long,
            rsi=rsi,
            atr=atr,
            realized_vol=realized_vol,
            volume_ratio=volume_ratio,
            corr_other=corr_other,
            warmup_ok=warmup_ok,
            status=status,
            reasons=reasons,
            feature_hash=digest,
        )
