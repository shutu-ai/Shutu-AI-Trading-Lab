"""Deterministic offline backtest — pure computation, no broker access."""
from __future__ import annotations
import datetime as dt
from decimal import Decimal
from dataclasses import dataclass

@dataclass(frozen=True)
class Bar:
    symbol: str
    ts: dt.datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal

class BacktestAccount:
    def __init__(self, initial_cash: Decimal, commission: Decimal = Decimal("1")):
        self.cash = initial_cash
        self.positions: dict[str, Decimal] = {}
        self.total_commission = Decimal("0")
        self._commission = commission
        self.trades: list[dict] = []

    def buy(self, symbol: str, qty: Decimal, price: Decimal) -> None:
        cost = qty * price + self._commission
        self.cash -= cost
        self.positions[symbol] = self.positions.get(symbol, Decimal("0")) + qty
        self.total_commission += self._commission

    def sell(self, symbol: str, qty: Decimal, price: Decimal) -> None:
        held = self.positions.get(symbol, Decimal("0"))
        if held < qty:
            raise ValueError(f"insufficient {symbol}")
        self.cash += qty * price - self._commission
        self.positions[symbol] = held - qty
        self.total_commission += self._commission

    def equity(self, prices: dict[str, Decimal]) -> Decimal:
        return self.cash + sum(q * prices.get(s, Decimal("0")) for s, q in self.positions.items())

__all__ = ["Bar", "BacktestAccount"]
