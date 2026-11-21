"""B0/B1/B2 transparent synthetic baselines (M3-R1-T4, v2.1 §4.3).

All three arms share the SAME engine, cost model, funding and time
semantics; they differ only in signal logic:

- B0_cash: no trades; return 0 (the protocol registers no cash yield —
  reporting 0.0 is the honest choice, not a fabricated carry).
- B1_buy_hold: one buy of a synthetic broad ETF at the first executable
  open; dividends/splits via corporate actions; never sold.
- B2_single_rule: one pre-declared transparent MA-cross. Parameter
  selection happens ONLY on a caller-supplied Train/Validation slice
  (``select_ma_params``), then the chosen pair is frozen for the OOS run.

Every result is stamped ``evidence_class=SYNTHETIC_ENGINEERING_ONLY``:
these numbers are engineering proofs of the harness, never alpha or
HIST_OOS_SUPPORTED claims.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping, Sequence

from trading_lab.contracts import CorporateAction, MarketBar
from trading_lab.security.canonical import canonical_digest
from trading_lab.validation import EvaluationProtocol

from trading_lab.backtest.engine import (
    BacktestEngine,
    BacktestError,
)

__all__ = [
    "ARM_IDS",
    "ArmResult",
    "SyntheticDataset",
    "equity_curve",
    "run_arm",
    "select_ma_params",
    "MA_GRID",
]

ARM_IDS = ("B0_cash", "B1_buy_hold", "B2_single_rule")
EVIDENCE_CLASS = "SYNTHETIC_ENGINEERING_ONLY"


@dataclass(frozen=True)
class ArmResult:
    arm_id: str
    seed: int
    protocol_hash: str
    dataset_hash: str
    code_hash: str
    cost_multiplier: int
    net_return: Decimal            # final_equity / initial_cash - 1
    max_drawdown: Decimal          # positive fraction, peak-to-trough
    tail_loss: Decimal             # mean of worst 5% step returns (<= 0)
    turnover: Decimal              # Σ(fill qty × exec price) / initial cash
    effective_observations: int    # equity-curve points
    calendar_span_days: int
    fills: int
    unfilled: int
    cancelled: int
    rejected: int
    fees_total: Decimal
    final_equity: Decimal
    selection_note: str
    evidence_class: str = EVIDENCE_CLASS

    def as_dict(self) -> dict:
        d = {
            "arm_id": self.arm_id, "seed": self.seed,
            "net_return": str(self.net_return),
            "max_drawdown": str(self.max_drawdown),
            "tail_loss": str(self.tail_loss),
            "turnover": str(self.turnover),
            "effective_observations": self.effective_observations,
            "calendar_span_days": self.calendar_span_days,
            "fills": self.fills, "unfilled": self.unfilled,
            "cancelled": self.cancelled, "rejected": self.rejected,
            "fees_total": str(self.fees_total),
            "final_equity": str(self.final_equity),
            "selection_note": self.selection_note,
            "evidence_class": self.evidence_class,
            "cost_multiplier": self.cost_multiplier,
            "protocol_hash": self.protocol_hash,
            "dataset_hash": self.dataset_hash,
            "code_hash": self.code_hash,
        }
        return d


@dataclass(frozen=True)
class SyntheticDataset:
    """A fully synthetic, hash-bound dataset for the backtest kernel."""

    name: str
    bars: Mapping[str, Sequence[MarketBar]]
    actions: tuple[CorporateAction, ...] = ()

    @property
    def dataset_hash(self) -> str:
        payload = {
            "name": self.name,
            "bars": sorted(
                ({k: getattr(b, k) for k in
                  ("asset_id", "ts_event_utc", "ts_available_utc", "interval",
                   "open", "high", "low", "close", "volume", "source",
                   "adjustment", "quality")}
                 for series in self.bars.values() for b in series),
                key=lambda r: (r["asset_id"], str(r["ts_event_utc"])),
            ),
            "actions": sorted(
                {"asset_id": a.asset_id, "effective_at": a.effective_at,
                 "kind": a.kind, "factor": a.factor, "source": a.source}
                for a in self.actions),
        }
        return canonical_digest(payload)

    def calendar_span_days(self) -> int:
        stamps = [b.ts_event_utc for series in self.bars.values()
                  for b in series]
        span = max(stamps) - min(stamps)
        return span.days + 1


# ---------------------------------------------------------------------------
# shared metric helpers
# ---------------------------------------------------------------------------


def equity_curve(eng: BacktestEngine) -> list[tuple[dt.datetime, Decimal]]:
    """Walk the engine clock stepwise so the account state at each stamp is
    the true post-processing state (settlements/actions/fills applied)."""
    curve: list[tuple[dt.datetime, Decimal]] = []
    for ts in eng.timeline:
        eng.run_to(ts)
        curve.append((ts, eng.account.equity(eng.mark_prices(ts))))
    eng.run_to_end()
    curve.append((eng.timeline[-1], eng.account.equity(
        eng.mark_prices(eng.timeline[-1]))))
    return curve


def _drawdown_and_tail(curve: list[tuple[Decimal]]) -> tuple[Decimal, Decimal]:
    peak = curve[0]
    max_dd = Decimal("0")
    for v in curve:
        if v > peak:
            peak = v
        dd = (peak - v) / peak
        if dd > max_dd:
            max_dd = dd
    if len(curve) < 2:
        return max_dd, Decimal("0")
    rets = [(b - a) / a for a, b in zip(curve, curve[1:])]
    ordered = sorted(rets)
    k = max(1, len(ordered) * 5 // 100) if len(ordered) >= 20 else max(
        1, len(ordered) // 10)
    tail = sum(ordered[:k], Decimal("0")) / k
    return max_dd, tail


def _event_counts(eng: BacktestEngine) -> dict[str, int]:
    counts = {"fills": 0, "unfilled": 0, "cancelled": 0, "rejected": 0}
    for e in eng.events:
        if e.kind == "FILL":
            counts["fills"] += 1
        elif e.kind == "UNFILLED":
            counts["unfilled"] += 1
        elif e.kind == "CANCEL":
            counts["cancelled"] += 1
        elif e.kind == "REJECT":
            counts["rejected"] += 1
    return counts


def _turnover(eng: BacktestEngine, initial_cash: Decimal) -> Decimal:
    notional = sum(
        (e.qty * e.exec_price for e in eng.events if e.kind == "FILL"),
        Decimal("0"))
    return (notional / initial_cash).quantize(Decimal("0.0001"))


def _finish(eng: BacktestEngine, arm_id: str, dataset: SyntheticDataset,
            protocol: EvaluationProtocol, seed: int, code_hash: str,
            cost_multiplier: int, initial_cash: Decimal,
            selection_note: str) -> ArmResult:
    curve_pts = [v for _, v in equity_curve(eng)]
    max_dd, tail = _drawdown_and_tail(curve_pts)
    counts = _event_counts(eng)
    final_equity = curve_pts[-1]
    return ArmResult(
        arm_id=arm_id, seed=seed,
        protocol_hash=protocol.protocol_hash,
        dataset_hash=dataset.dataset_hash,
        code_hash=code_hash,
        cost_multiplier=cost_multiplier,
        net_return=((final_equity - initial_cash) / initial_cash).quantize(
            Decimal("0.0001")),
        max_drawdown=max_dd.quantize(Decimal("0.0001")),
        tail_loss=tail.quantize(Decimal("0.0001")),
        turnover=_turnover(eng, initial_cash),
        effective_observations=len(curve_pts),
        calendar_span_days=dataset.calendar_span_days(),
        **counts,
        fees_total=eng.account.fees_total,
        final_equity=final_equity.quantize(Decimal("0.0001")),
        selection_note=selection_note,
    )


def _scaled_cost(protocol: EvaluationProtocol,
                 multiplier: int):
    """Cost model × multiplier (protocol cost_multipliers x1/x2/x3)."""
    from trading_lab.backtest.engine import CostModel
    cm = protocol.cost_model
    m = Decimal(multiplier)
    return CostModel(
        commission_per_trade=(Decimal(str(cm["commission_per_trade"])) * m),
        spread_pct=(Decimal(str(cm["spread_pct"])) * m),
        slippage_pct=(Decimal(str(cm["slippage_pct"])) * m),
    )


# ---------------------------------------------------------------------------
# arm runners
# ---------------------------------------------------------------------------


def run_arm(
    arm_id: str,
    dataset: SyntheticDataset,
    protocol: EvaluationProtocol,
    *,
    seed: int,
    code_hash: str,
    initial_cash: Decimal = Decimal("100000"),
    cost_multiplier: int = 1,
    ma_params: tuple[int, int] | None = None,
) -> ArmResult:
    """Run one arm on one synthetic dataset under the frozen protocol.

    B2 requires either pre-selected ``ma_params`` (OOS/frozen mode) or a
    prior ``select_ma_params`` call on the Train/Validation slice.
    """
    if arm_id not in ARM_IDS:
        raise BacktestError(f"unknown arm {arm_id}")
    if cost_multiplier not in protocol.cost_multipliers:
        raise BacktestError(
            f"cost multiplier {cost_multiplier} not in protocol "
            f"{protocol.cost_multipliers}")

    # identical execution semantics for every arm (engine derives them from
    # the protocol); cost scaled by the protocol multiplier (x1/x2/x3)
    eng = BacktestEngine(
        bars=dataset.bars, actions=list(dataset.actions),
        initial_cash=initial_cash, protocol=protocol,
        seed=seed, dataset_hash=dataset.dataset_hash,
        code_hash=code_hash)
    eng.cost = _scaled_cost(protocol, cost_multiplier)

    if arm_id == "B0_cash":
        note = "cash: no trades; no cash-yield registered in protocol"
        selection_note = note
        eng.run_to_end()
    elif arm_id == "B1_buy_hold":
        selection_note = "buy-and-hold: no parameters to select"
        first_ts = eng.timeline[0]
        eng.run_to(first_ts)
        eng.submit(decision_at=first_ts, symbol=_single_symbol(dataset),
                   side="buy", qty=Decimal("50"))
        eng.run_to_end()
    else:  # B2_single_rule
        if ma_params is None:
            raise BacktestError(
                "B2 requires frozen ma_params from select_ma_params() — "
                "selection on Train/Validation is a separate, budgeted step")
        short_n, long_n = ma_params
        selection_note = (f"MA cross ({short_n},{long_n}) frozen from "
                          "Train/Validation selection")
        _run_ma_cross(eng, dataset, short_n, long_n)
    return _finish(eng, arm_id, dataset, protocol, seed, code_hash,
                   cost_multiplier, initial_cash, selection_note)


def _single_symbol(dataset: SyntheticDataset) -> str:
    if len(dataset.bars) != 1:
        raise BacktestError("B1/B2 arms run on a single-symbol dataset")
    return next(iter(dataset.bars))


def _run_ma_cross(eng: BacktestEngine, dataset: SyntheticDataset,
                  short_n: int, long_n: int) -> None:
    """Pre-declared transparent rule: hold while MA(short) > MA(long);
    enter on the first decidable above-state and on every upward cross,
    exit on every downward cross. Decisions at session closes via the
    PIT-respecting accessor; fills next open (engine). Position state is
    read from the account ledger (truth), not a shadow flag — a rejected
    fill can never desync the rule."""
    symbol = _single_symbol(dataset)
    decided_above: bool | None = None
    for ts in eng.timeline:
        eng.run_to(ts)
        closes = [b.close for b in eng.available_closes(symbol, ts)]
        if len(closes) < long_n:
            continue
        ma_long = sum(closes[-long_n:], Decimal("0")) / long_n
        ma_short = sum(closes[-short_n:], Decimal("0")) / short_n
        above = ma_short > ma_long
        held = eng.account.positions.get(symbol, Decimal("0")) > 0
        entry = decided_above is None or above != decided_above
        if entry and above and not held:
            eng.submit(decision_at=ts, symbol=symbol, side="buy",
                       qty=Decimal("50"))
        elif entry and not above and held:
            eng.submit(decision_at=ts, symbol=symbol, side="sell",
                       qty=Decimal("50"))
        decided_above = above


# ---------------------------------------------------------------------------
# B2 Train/Validation-only parameter selection (budgeted, declared grid)
# ---------------------------------------------------------------------------

MA_GRID: tuple[tuple[int, int], ...] = ((2, 4), (2, 6), (3, 5), (3, 8))


def select_ma_params(
    dataset: SyntheticDataset,
    protocol: EvaluationProtocol,
    *,
    train_val_end: dt.datetime,
    code_hash: str,
    seed: int,
    initial_cash: Decimal = Decimal("100000"),
) -> tuple[tuple[int, int], int]:
    """Pick the best MA pair on the Train/Validation slice ONLY.

    Returns ((short, long), trials_used). Every grid entry consumes one
    trial from the arm's equal-trial budget (the caller registers
    trials_used in the experiment ledger — failures count too).
    """
    if train_val_end.tzinfo is None:
        raise BacktestError("train_val_end must be timezone-aware")
    # slice the dataset strictly at the boundary (PIT: no bar beyond it)
    sliced_bars = {
        sym: [b for b in series if b.ts_event_utc <= train_val_end]
        for sym, series in dataset.bars.items()
    }
    if any(not s for s in sliced_bars.values()):
        raise BacktestError("empty Train/Validation slice")
    best: tuple[tuple[int, int], Decimal] | None = None
    trials = 0
    for pair in MA_GRID:
        trials += 1
        eng = BacktestEngine(
            bars=sliced_bars, actions=list(dataset.actions),
            initial_cash=initial_cash, protocol=protocol, seed=seed,
            dataset_hash=dataset.dataset_hash, code_hash=code_hash)
        _run_ma_cross(eng, dataset, pair[0], pair[1])
        curve = equity_curve(eng)
        final = curve[-1][1]
        ret = (final - initial_cash) / initial_cash
        if best is None or ret > best[1]:
            best = (pair, ret)
    assert best is not None
    return best[0], trials
