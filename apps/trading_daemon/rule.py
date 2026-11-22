"""The frozen transparent B2 rule as a forward decision function.

Semantics (frozen, v2.1 §4.3 + m3-r2-batch-1 ``b2_params_frozen=[2,4]``):
hold LONG while MA(short_n) > MA(long_n), FLAT otherwise. The forward
form is a PURE function of the closes handed to it — the engine owns the
PIT window; this module keeps no history and cannot sense extra data.

Decision-equivalence with the historical simulator
(``trading_lab.backtest.arms._run_ma_cross``) is enforced by a regression
test in tests/forward_smoke: the same close sequence must yield the same
above-state flips, so the forward rule cannot drift from the backtest
definition of B2.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Sequence

from trading_lab.security.canonical import canonical_digest

LONG = "LONG"
FLAT = "FLAT"
WARMUP = "WARMUP"

__all__ = ["B2ForwardRule", "LONG", "FLAT", "WARMUP"]


class B2ForwardRule:
    """Frozen MA-cross above-state rule (stateless, deterministic)."""

    def __init__(self, short_n: int, long_n: int) -> None:
        if short_n < 1 or long_n < 1 or short_n >= long_n:
            raise ValueError("require 1 <= short_n < long_n")
        self.short_n = short_n
        self.long_n = long_n
        self.params_digest = canonical_digest(
            {"rule": "B2_MA_CROSS_ABOVE_STATE",
             "short_n": short_n, "long_n": long_n})

    def decide(self, closes: Sequence[Decimal]) -> str:
        """Above-state over the given PIT window. ``WARMUP`` until at
        least ``long_n`` closes are available."""
        if len(closes) < self.long_n:
            return WARMUP
        tail = closes[-self.long_n:]
        ma_long = sum(tail, Decimal("0")) / self.long_n
        ma_short = sum(tail[-self.short_n:], Decimal("0")) / self.short_n
        return LONG if ma_short > ma_long else FLAT
