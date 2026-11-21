"""Deterministic offline backtest kernel (M3-R1-T3) — pure computation.

Trust rules (ADR-004 §4):

- **Single bar semantics**: consumes ``contracts.MarketBar`` — no second
  bar type. Bars are validated for strict per-symbol timestamp monotonicity
  and duplicate rejection; the contract layer already rejects float prices,
  negatives, NaN and naive timestamps.
- **Decimal end-to-end**: every money/quantity argument must be a finite
  ``Decimal`` (float/int/str are rejected fail-closed).
- **Cash discipline**: fees are paid at trade time from settled cash; sell
  proceeds enter ``cash_unsettled`` and become available after the
  protocol's T+N settlement assumption (a protocol assumption — never a
  claim about real broker behavior). ``cash_available`` can never go
  negative; a buy that cannot be funded is rejected outright.
- **Future-information isolation**: a close-formed signal fills at the
  earliest on a later bar's open (``order_delay_bars``), and facts are only
  visible once ``ts_available_utc <= decision instant``.
- **Execution realism**: side-adjusted spread+slippage on the reachable
  open price, flat commission, per-order volume cap with partial fill and
  explicit UNFILLED/CANCEL events.
- **Corporate actions**: SPLIT (position factor), DIVIDEND (cash per share
  credited), DELISTING (forced liquidation at last reachable close; later
  bars or orders on the symbol are rejected — ticker reuse is fail-closed).
- **Determinism**: no wall clock, no implicit randomness. The output
  digest canonically binds seed + protocol/dataset/code hashes + every
  event + final state; identical inputs reproduce it exactly.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_EVEN
from typing import Mapping, Sequence

from trading_lab.contracts import CorporateAction, MarketBar
from trading_lab.security.canonical import canonical_digest
from trading_lab.validation import EvaluationProtocol

__all__ = [
    "BacktestAccount",
    "BacktestEngine",
    "BacktestError",
    "BacktestEvent",
    "CostModel",
    "ExecutionConfig",
    "SUPPORTED_ACTION_KINDS",
]


class BacktestError(ValueError):
    """Any fail-closed backtest violation (invalid input or broken invariant)."""


SUPPORTED_ACTION_KINDS = ("SPLIT", "DIVIDEND", "DELISTING")

_PRICE_QUANT = Decimal("0.0001")


def _require_decimal(v: object, name: str) -> None:
    if not isinstance(v, Decimal):
        raise BacktestError(
            f"{name} must be Decimal, got {type(v).__name__} "
            "(float/int/str are rejected: decimal chain is exact)")
    if not v.is_finite():
        raise BacktestError(f"{name} must be finite")


def _require_tz(ts: dt.datetime, name: str) -> None:
    if not isinstance(ts, dt.datetime) or ts.tzinfo is None:
        raise BacktestError(f"{name} must be timezone-aware")


@dataclass(frozen=True)
class CostModel:
    commission_per_trade: Decimal
    spread_pct: Decimal
    slippage_pct: Decimal

    def __post_init__(self) -> None:
        for name in ("commission_per_trade", "spread_pct", "slippage_pct"):
            v = getattr(self, name)
            _require_decimal(v, name)
            if v < 0:
                raise BacktestError(f"{name} must be >= 0")


@dataclass(frozen=True)
class ExecutionConfig:
    order_delay_bars: int
    allow_same_day_close: bool
    volume_limit_pct: Decimal
    partial_fill_threshold_pct: Decimal
    settlement_days: int

    def __post_init__(self) -> None:
        if self.order_delay_bars < 1:
            raise BacktestError("order_delay_bars must be >= 1")
        if self.settlement_days < 0:
            raise BacktestError("settlement_days must be >= 0")
        for name in ("volume_limit_pct", "partial_fill_threshold_pct"):
            v = getattr(self, name)
            _require_decimal(v, name)
            if not Decimal("0") <= v <= Decimal("1"):
                raise BacktestError(f"{name} must be within [0, 1]")


#: Defaults mirroring the frozen evaluation protocol (see drift test).
DEFAULT_COST = CostModel(
    commission_per_trade=Decimal("1.00"),
    spread_pct=Decimal("0.001"),
    slippage_pct=Decimal("0.0005"),
)
DEFAULT_EXECUTION = ExecutionConfig(
    order_delay_bars=1,
    allow_same_day_close=False,
    volume_limit_pct=Decimal("0.10"),
    partial_fill_threshold_pct=Decimal("0.50"),
    settlement_days=2,
)


@dataclass(frozen=True)
class BacktestEvent:
    ts: dt.datetime
    kind: str  # DECISION / FILL / UNFILLED / CANCEL / REJECT / SETTLE / DIVIDEND / SPLIT / DELIST
    symbol: str | None = None
    qty: Decimal | None = None
    exec_price: Decimal | None = None
    commission: Decimal | None = None
    detail: str = ""

    def as_dict(self) -> dict:
        return {
            "ts": self.ts, "kind": self.kind, "symbol": self.symbol,
            "qty": self.qty, "exec_price": self.exec_price,
            "commission": self.commission, "detail": self.detail,
        }


# ---------------------------------------------------------------------------
# Account primitive (strict, unit-testable)
# ---------------------------------------------------------------------------


@dataclass
class _SettleLot:
    amount: Decimal
    settle_at: dt.datetime


class BacktestAccount:
    """Cash/position ledger with exact conservation semantics."""

    def __init__(self, initial_cash: Decimal, settlement_days: int = 2) -> None:
        _require_decimal(initial_cash, "initial_cash")
        if initial_cash < 0:
            raise BacktestError("initial_cash must be >= 0")
        if settlement_days < 0:
            raise BacktestError("settlement_days must be >= 0")
        self.initial_cash = initial_cash
        self.cash_available = initial_cash
        self.cash_unsettled = Decimal("0")
        self.fees_total = Decimal("0")
        self.dividends_total = Decimal("0")
        self.settlement_days = settlement_days
        self.positions: dict[str, Decimal] = {}
        self._lots: list[_SettleLot] = []

    # -- primitives -----------------------------------------------------

    def buy(self, *, ts: dt.datetime, symbol: str, qty: Decimal,
            exec_price: Decimal, commission: Decimal) -> Decimal:
        _require_tz(ts, "ts")
        _require_decimal(qty, "qty")
        _require_decimal(exec_price, "exec_price")
        _require_decimal(commission, "commission")
        if qty <= 0:
            raise BacktestError(f"qty must be > 0 (got {qty})")
        if exec_price <= 0:
            raise BacktestError(f"exec_price must be > 0 (got {exec_price})")
        if commission < 0:
            raise BacktestError("commission must be >= 0")
        gross = (qty * exec_price).quantize(_PRICE_QUANT, ROUND_HALF_EVEN)
        fee = commission.quantize(_PRICE_QUANT, ROUND_HALF_EVEN)
        cost = gross + fee
        if cost > self.cash_available:
            raise BacktestError(
                f"insufficient funds: need {cost}, available "
                f"{self.cash_available}")
        self.cash_available -= cost
        self.fees_total += fee
        self.positions[symbol] = self.positions.get(symbol, Decimal("0")) + qty
        return gross

    def sell(self, *, ts: dt.datetime, symbol: str, qty: Decimal,
             exec_price: Decimal, commission: Decimal) -> Decimal:
        _require_tz(ts, "ts")
        _require_decimal(qty, "qty")
        _require_decimal(exec_price, "exec_price")
        _require_decimal(commission, "commission")
        if qty <= 0:
            raise BacktestError(f"qty must be > 0 (got {qty})")
        if exec_price <= 0:
            raise BacktestError(f"exec_price must be > 0 (got {exec_price})")
        if commission < 0:
            raise BacktestError("commission must be >= 0")
        held = self.positions.get(symbol, Decimal("0"))
        if held < qty:
            raise BacktestError(
                f"oversell: hold {held} {symbol}, tried {qty}")
        fee = commission.quantize(_PRICE_QUANT, ROUND_HALF_EVEN)
        if fee > self.cash_available:
            raise BacktestError("insufficient settled cash for commission")
        gross = (qty * exec_price).quantize(_PRICE_QUANT, ROUND_HALF_EVEN)
        self.cash_available -= fee
        self.fees_total += fee
        self.positions[symbol] = held - qty
        settle_at = ts + dt.timedelta(days=self.settlement_days)
        self._lots.append(_SettleLot(amount=gross, settle_at=settle_at))
        self.cash_unsettled += gross
        return gross

    def credit_cash(self, amount: Decimal) -> None:
        _require_decimal(amount, "amount")
        if amount < 0:
            raise BacktestError("credit must be >= 0")
        self.cash_available += amount
        self.dividends_total += amount

    def apply_split(self, symbol: str, factor: Decimal) -> None:
        _require_decimal(factor, "factor")
        if factor <= 0:
            raise BacktestError("split factor must be > 0")
        held = self.positions.get(symbol)
        if held:
            self.positions[symbol] = held * factor

    def settle_due(self, asof: dt.datetime) -> Decimal:
        """Move matured settlement lots into available cash; returns total."""
        _require_tz(asof, "asof")
        moved = Decimal("0")
        remaining: list[_SettleLot] = []
        for lot in self._lots:
            if lot.settle_at <= asof:
                moved += lot.amount
            else:
                remaining.append(lot)
        self._lots = remaining
        self.cash_unsettled -= moved
        self.cash_available += moved
        return moved

    # -- valuation ------------------------------------------------------

    def equity(self, prices: Mapping[str, Decimal]) -> Decimal:
        """Mark-to-market; a held symbol without an explicit mark is a
        fail-closed error — missing prices are NEVER treated as zero."""
        total = self.cash_available + self.cash_unsettled
        for symbol, qty in self.positions.items():
            if qty == 0:
                continue
            mark = prices.get(symbol)
            if mark is None:
                raise BacktestError(
                    f"missing mark for held symbol {symbol} — refusing to "
                    "value equity (no implicit zero)")
            _require_decimal(mark, f"mark[{symbol}]")
            if mark < 0:
                raise BacktestError(f"mark for {symbol} must be >= 0")
            total += qty * mark
        return total

    def state_dict(self) -> dict:
        return {
            "cash_available": self.cash_available,
            "cash_unsettled": self.cash_unsettled,
            "fees_total": self.fees_total,
            "dividends_total": self.dividends_total,
            "positions": dict(sorted(self.positions.items())),
        }


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


@dataclass
class _PendingOrder:
    decision_at: dt.datetime
    symbol: str
    side: str
    qty: Decimal
    exec_bar_index: int | None  # None => beyond data window (cancel at end)


class BacktestEngine:
    """Event-driven, deterministic, offline execution simulator."""

    def __init__(
        self,
        *,
        bars: Mapping[str, Sequence[MarketBar]],
        initial_cash: Decimal,
        protocol: EvaluationProtocol | None = None,
        actions: Sequence[CorporateAction] = (),
        seed: int = 0,
        dataset_hash: str = "",
        code_hash: str = "",
    ) -> None:
        if not bars:
            raise BacktestError("empty dataset — fail closed")
        _require_decimal(initial_cash, "initial_cash")

        # ---- derive cost/execution config from protocol or defaults ----
        if protocol is not None:
            self.cost, self.execution = self._config_from_protocol(protocol)
            self._protocol = protocol
        else:
            self.cost, self.execution = DEFAULT_COST, DEFAULT_EXECUTION
            self._protocol = None

        # ---- validate + index bars ----
        self._bars: dict[str, list[MarketBar]] = {}
        for symbol, series in bars.items():
            if not series:
                raise BacktestError(f"empty bar series for {symbol}")
            series = list(series)
            # validate the RAW input order — sorting first would silently
            # "repair" a reversed series
            for a, b in zip(series, series[1:]):
                if a.ts_event_utc >= b.ts_event_utc:
                    raise BacktestError(
                        f"duplicate/non-monotonic bar timestamps for "
                        f"{symbol}: {a.ts_event_utc} then {b.ts_event_utc}")
            self._bars[symbol] = series

        # ---- validate actions ----
        self._actions = sorted(actions, key=lambda a: a.effective_at)
        for action in self._actions:
            if action.kind not in SUPPORTED_ACTION_KINDS:
                raise BacktestError(
                    f"unsupported corporate action kind: {action.kind}")
            if action.asset_id not in self._bars:
                raise BacktestError(
                    f"action references unknown symbol {action.asset_id}")
            if action.kind in ("SPLIT", "DELISTING") and action.factor <= 0:
                raise BacktestError(
                    f"{action.kind} factor must be > 0 (got {action.factor})")
            if action.kind == "DIVIDEND" and action.factor < 0:
                raise BacktestError(
                    f"DIVIDEND cash factor must be >= 0 (got {action.factor})")
        # ticker reuse after delisting is fail-closed at dataset level
        for action in self._actions:
            if action.kind == "DELISTING":
                late = [b for b in self._bars[action.asset_id]
                        if b.ts_event_utc > action.effective_at]
                if late:
                    raise BacktestError(
                        f"{action.asset_id} has bars after DELISTING "
                        f"{action.effective_at} (ticker reuse unsupported)")

        # ---- run identity + state ----
        self.run_id = {"protocol_hash": self._protocol.protocol_hash
                       if self._protocol else "NONE",
                       "seed": seed, "dataset_hash": dataset_hash,
                       "code_hash": code_hash}
        self.account = BacktestAccount(
            initial_cash=initial_cash,
            settlement_days=self.execution.settlement_days)
        self.events: list[BacktestEvent] = []
        self._pending: list[_PendingOrder] = []
        self._cursor = 0
        self._clock: dt.datetime | None = None
        self._last_decision_at: dt.datetime | None = None
        self._timeline: list[dt.datetime] = sorted(
            {b.ts_event_utc for series in self._bars.values()
             for b in series})
        self._next_action = 0
        self._delisted: set[str] = set()
        self._buy_gross = Decimal("0")
        self._sell_gross = Decimal("0")
        self._finished = False

    # ------------------------------------------------------------------
    # config
    # ------------------------------------------------------------------

    @staticmethod
    def _config_from_protocol(
            protocol: EvaluationProtocol) -> tuple[CostModel, ExecutionConfig]:
        cm = protocol.cost_model
        ex = protocol.execution
        cost = CostModel(
            commission_per_trade=Decimal(str(cm["commission_per_trade"])),
            spread_pct=Decimal(str(cm["spread_pct"])),
            slippage_pct=Decimal(str(cm["slippage_pct"])),
        )
        execution = ExecutionConfig(
            order_delay_bars=int(ex["order_delay_bars"]),
            allow_same_day_close=bool(ex["allow_same_day_close"]),
            volume_limit_pct=Decimal(str(ex["volume_limit_pct"])),
            partial_fill_threshold_pct=Decimal(
                str(ex["partial_fill_threshold_pct"])),
            settlement_days=int(ex["settlement_days"]),
        )
        if execution.allow_same_day_close:
            raise BacktestError(
                "allow_same_day_close=true is forbidden by ADR-004 (a "
                "close-formed signal may never fill at that same close)")
        return cost, execution

    # ------------------------------------------------------------------
    # PIT visibility
    # ------------------------------------------------------------------

    def available_closes(self, symbol: str,
                         asof: dt.datetime) -> list[MarketBar]:
        """Bars of ``symbol`` whose information is available at ``asof``
        (ts_available_utc <= asof). Signal logic must consume facts only
        through this accessor."""
        _require_tz(asof, "asof")
        if symbol not in self._bars:
            raise BacktestError(f"unknown symbol {symbol}")
        return [b for b in self._bars[symbol] if b.ts_available_utc <= asof]

    @property
    def timeline(self) -> tuple[dt.datetime, ...]:
        """The sorted union of all bar timestamps (the run clock)."""
        return tuple(self._timeline)

    def mark_prices(self, asof: dt.datetime) -> dict[str, Decimal]:
        """Last known close per symbol at ``asof`` (PIT-respecting). Symbols
        with no bar available yet are absent — equity() treats a held
        symbol without a mark as fail-closed."""
        marks: dict[str, Decimal] = {}
        for symbol, series in self._bars.items():
            for b in reversed(series):
                if b.ts_event_utc <= asof and b.ts_available_utc <= asof:
                    marks[symbol] = b.close
                    break
        return marks

    # ------------------------------------------------------------------
    # signal intake
    # ------------------------------------------------------------------

    def submit(self, *, decision_at: dt.datetime, symbol: str, side: str,
               qty: Decimal) -> None:
        if symbol not in self._bars:
            raise BacktestError(f"unknown symbol {symbol}")
        if side not in ("buy", "sell"):
            raise BacktestError(f"side must be buy/sell (got {side!r})")
        _require_decimal(qty, "qty")
        if qty <= 0:
            raise BacktestError(f"qty must be > 0 (got {qty})")
        _require_tz(decision_at, "decision_at")
        if self._clock is not None and decision_at < self._clock:
            raise BacktestError(
                f"decision_at {decision_at} precedes engine clock "
                f"{self._clock} — time reversal is fail-closed")
        if self._last_decision_at is not None \
                and decision_at < self._last_decision_at:
            raise BacktestError(
                f"decision_at {decision_at} precedes a previous decision "
                f"{self._last_decision_at} — time reversal is fail-closed")
        self._last_decision_at = decision_at
        if symbol in self._delisted:
            raise BacktestError(f"{symbol} is delisted; orders rejected")

        series = self._bars[symbol]
        exec_index: int | None = None
        for i, b in enumerate(series):
            if b.ts_event_utc > decision_at:
                exec_index = i + (self.execution.order_delay_bars - 1)
                break
        if exec_index is not None and exec_index >= len(series):
            exec_index = None  # beyond data window
        self._pending.append(_PendingOrder(
            decision_at=decision_at, symbol=symbol, side=side, qty=qty,
            exec_bar_index=exec_index))
        self.events.append(BacktestEvent(
            ts=decision_at, kind="DECISION", symbol=symbol, qty=qty,
            detail=f"side={side}"))

    # ------------------------------------------------------------------
    # timeline processing
    # ------------------------------------------------------------------

    def run_to(self, bar_ts: dt.datetime) -> None:
        """Process every timeline event up to and including ``bar_ts``."""
        _require_tz(bar_ts, "bar_ts")
        while self._cursor < len(self._timeline) \
                and self._timeline[self._cursor] <= bar_ts:
            self._step(self._timeline[self._cursor])
            self._cursor += 1

    def run_to_end(self) -> None:
        for ts in self._timeline[self._cursor:]:
            self._step(ts)
            self._cursor += 1
        if not self._finished:
            self._finished = True
            for order in self._pending:
                self.events.append(BacktestEvent(
                    ts=self._timeline[-1], kind="CANCEL", symbol=order.symbol,
                    qty=order.qty, detail="end_of_data"))
            self._pending.clear()

    def _step(self, ts: dt.datetime) -> None:
        self._clock = ts
        # 1. cash settlements matured by this instant
        moved = self.account.settle_due(ts)
        if moved > 0:
            self.events.append(BacktestEvent(ts=ts, kind="SETTLE",
                                             qty=moved))
        # 2. corporate actions effective by this instant
        while (self._next_action < len(self._actions)
               and self._actions[self._next_action].effective_at <= ts):
            self._apply_action(self._actions[self._next_action])
            self._next_action += 1
        # 3. orders due at this bar
        due = [o for o in self._pending if o.exec_bar_index is not None
               and self._bar_ts(o) == ts]
        for order in due:
            self._pending.remove(order)
            self._execute(order, ts)

    def _bar_ts(self, order: _PendingOrder) -> dt.datetime:
        return self._bars[order.symbol][order.exec_bar_index].ts_event_utc

    def _apply_action(self, action: CorporateAction) -> None:
        symbol = action.asset_id
        if action.kind == "SPLIT":
            self.account.apply_split(symbol, action.factor)
            self.events.append(BacktestEvent(
                ts=action.effective_at, kind="SPLIT", symbol=symbol,
                qty=action.factor))
        elif action.kind == "DIVIDEND":
            held = self.account.positions.get(symbol, Decimal("0"))
            amount = (held * action.factor).quantize(
                _PRICE_QUANT, ROUND_HALF_EVEN)
            self.account.credit_cash(amount)
            self.events.append(BacktestEvent(
                ts=action.effective_at, kind="DIVIDEND", symbol=symbol,
                qty=amount))
        elif action.kind == "DELISTING":
            held = self.account.positions.get(symbol, Decimal("0"))
            if held > 0:
                px = self._last_close(symbol, action.effective_at)
                liq_px = self._side_price(px, "sell")
                try:
                    self.account.sell(
                        ts=action.effective_at, symbol=symbol, qty=held,
                        exec_price=liq_px,
                        commission=self.cost.commission_per_trade)
                    self._sell_gross += (held * liq_px).quantize(
                        _PRICE_QUANT, ROUND_HALF_EVEN)
                    self.events.append(BacktestEvent(
                        ts=action.effective_at, kind="DELIST", symbol=symbol,
                        qty=held, exec_price=liq_px,
                        commission=self.cost.commission_per_trade,
                        detail="forced_liquidation"))
                except BacktestError as exc:
                    self.events.append(BacktestEvent(
                        ts=action.effective_at, kind="REJECT", symbol=symbol,
                        qty=held, detail=f"delist_liquidation_failed:{exc}"))
            self._delisted.add(symbol)

    def _last_close(self, symbol: str, asof: dt.datetime) -> Decimal:
        prior = [b for b in self._bars[symbol]
                 if b.ts_event_utc <= asof and b.ts_available_utc <= asof]
        if not prior:
            raise BacktestError(
                f"no reachable price for {symbol} at {asof} — cannot "
                "liquidate against unknown value")
        return prior[-1].close

    # ------------------------------------------------------------------
    # execution
    # ------------------------------------------------------------------

    def _side_price(self, base: Decimal, side: str) -> Decimal:
        factor = Decimal("1") + self.cost.spread_pct + self.cost.slippage_pct
        if side == "sell":
            factor = Decimal("1") - self.cost.spread_pct - self.cost.slippage_pct
        return (base * factor).quantize(_PRICE_QUANT, ROUND_HALF_EVEN)

    def _execute(self, order: _PendingOrder, ts: dt.datetime) -> None:
        bar = self._bars[order.symbol][order.exec_bar_index]
        if bar.ts_event_utc <= order.decision_at \
                and not self.execution.allow_same_day_close:
            # structural guarantee; kept as defense in depth
            self.events.append(BacktestEvent(
                ts=ts, kind="REJECT", symbol=order.symbol, qty=order.qty,
                detail="same_close_fill_forbidden"))
            return
        cap = (self.execution.volume_limit_pct * bar.volume).quantize(
            _PRICE_QUANT, ROUND_HALF_EVEN)
        fill_qty = min(order.qty, cap)
        if fill_qty <= 0:
            self.events.append(BacktestEvent(
                ts=ts, kind="UNFILLED", symbol=order.symbol, qty=order.qty,
                detail="volume_cap_zero"))
            return
        exec_price = self._side_price(bar.open, order.side)
        try:
            if order.side == "buy":
                gross = self.account.buy(
                    ts=ts, symbol=order.symbol, qty=fill_qty,
                    exec_price=exec_price,
                    commission=self.cost.commission_per_trade)
                self._buy_gross += gross
            else:
                gross = self.account.sell(
                    ts=ts, symbol=order.symbol, qty=fill_qty,
                    exec_price=exec_price,
                    commission=self.cost.commission_per_trade)
                self._sell_gross += gross
        except BacktestError as exc:
            self.events.append(BacktestEvent(
                ts=ts, kind="REJECT", symbol=order.symbol, qty=fill_qty,
                detail=str(exc)))
            return
        self.events.append(BacktestEvent(
            ts=ts, kind="FILL", symbol=order.symbol, qty=fill_qty,
            exec_price=exec_price,
            commission=self.cost.commission_per_trade,
            detail=f"side={order.side}"))
        if fill_qty < order.qty:
            self.events.append(BacktestEvent(
                ts=ts, kind="CANCEL", symbol=order.symbol,
                qty=order.qty - fill_qty, detail="volume_cap_residual"))

    # ------------------------------------------------------------------
    # audit + determinism
    # ------------------------------------------------------------------

    def conservation_report(self) -> dict:
        """Exact cash identity (Decimal, no tolerance):
        available + unsettled + fees == initial + dividends − buy_gross + sell_gross
        (sell proceeds enter unsettled; settlements are internal moves)."""
        acc = self.account
        lhs = acc.cash_available + acc.cash_unsettled + acc.fees_total
        rhs = (acc.initial_cash + acc.dividends_total
               - self._buy_gross + self._sell_gross)
        return {
            "ok": lhs == rhs,
            "identity_delta": lhs - rhs,
            "initial_cash": acc.initial_cash,
            "dividends": acc.dividends_total,
            "buy_gross": self._buy_gross,
            "sell_gross": self._sell_gross,
            "fees": acc.fees_total,
        }

    def run_identity(self) -> dict:
        return dict(self.run_id)

    def output_digest(self) -> str:
        payload = {
            "run": self.run_id,
            "events": [e.as_dict() for e in self.events],
            "final": {
                k: (str(v) if isinstance(v, Decimal) else v)
                for k, v in self.account.state_dict().items()
            },
        }
        return canonical_digest(payload)
