"""V0.3 daily workflow engine (task §3): one decision instant per call,
PIT-strict, restartable, MOCK_ONLY.

    python scripts/run_business_mvp.py --mode daily --asof <ISO-8601> \
        --snapshot-dir <dir> [--info-file <f>] --state-dir <dir> --output-dir <dir>

One cycle = one ``--asof`` instant: PIT features, usable information
events, one regime hysteresis step, the DecisionOrchestrator decide(),
then execution bookkeeping. Analysis/routing/decision logic is the
EXISTING business plane (``replay.py`` is never duplicated); execution
flows through the REAL SchemaGate -> RiskEngine -> OMS -> FakeBroker
chain via ONE persistent :class:`ContinuousMockRunner` stack directory.

Decision/execution separation (structural): a freshly made decision is
ALWAYS ``PENDING`` — target, rationale and ``decision_hash`` persist, NO
order is sent (the next session's open is not reached yet). A pending
executes only at a LATER cycle whose resolved session is strictly after
the pending's decision session, via ``ContinuousMockRunner.step``
semantics: sizing from the ORIGINAL decision-time marks (never a future
price), fills at the fill session's open, and the risk engine re-checks
EVERY leg through the real chain — a pending never bypasses risk.

Restartability: ``daily_state.json`` holds the ledger, open pendings,
processed sessions, regime hysteresis and the decision-plane state
(router/tracker) so a restart reproduces the same next cycle; the OMS
journal/fence sqlite files persist in the state dir and are REUSED (one
stack dir per account). Cycle ids derive ONLY from stable fields
(account + session date + dataset-hash prefix + strategy version +
workflow version) — re-running an already-processed session is an
idempotent no-op returning the stored record. On reload the state is
reconciled (cash conservation, positions vs fill-log replay,
filled-outcome count vs fill-log size) BEFORE anything runs; any
inconsistency raises :class:`DailyWorkflowHalt` and latches ``halted``
into the state file — operator decision required. Honest limit: the
in-memory FakeBroker's order counts are reconciled against PERSISTED
evidence, not the restarted process's broker book.

Calendar coverage honesty: the cycle's session is the last snapshot
session on or before the ``asof`` ET date; an asof before the first
session close or beyond the snapshot's last session is recorded
``CALENDAR_BLOCKED`` with reason ``CALENDAR_COVERAGE_BLOCKED:...`` — no
session is invented, no historical backfill is presented as M3.5 forward
data; offline fixture snapshots stay explicitly labeled in every record.

Action vocabulary: ``PENDING`` / ``EXECUTED`` / ``NO_TRADE`` /
``REJECTED`` / ``CALENDAR_BLOCKED``. Records are JSON-safe dicts.
"""

from __future__ import annotations

import datetime as dt
import json
from collections import deque
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Mapping, Sequence

from trading_lab.business.analyzers import (
    LLMInformationAnalyzer,
    RuleInformationAnalyzer,
)
from trading_lab.business.config import BusinessConfig
from trading_lab.business.continuous import ContinuousMockRunner
from trading_lab.business.data_source import (
    MarketDataView,
    build_snapshot_view,
)
from trading_lab.business.decision import DecisionOrchestrator
from trading_lab.business.features import FeatureEngine
from trading_lab.business.info_fixtures import MockLLMClient
from trading_lab.business.information import InfoBundle, load_info_events
from trading_lab.business.mockexec import (
    MOCK_COMMISSION_PER_FILL,
    RISK_BUDGET_ID,
)
from trading_lab.business.regime import (
    PRIMARY_SYMBOL,
    RegimeClassifierSession,
    RuleRegimeClassifier,
)
from trading_lab.business.strategies import STRATEGY_VERSION
from trading_lab.business.types import (
    STATUS_OK,
    DecisionOutput,
    ExecutionOutcome,
)
from trading_lab.contracts import (
    AllocationItem,
    RegimeAssessment,
    TargetPortfolio,
)
from trading_lab.data.calendar import ET
from trading_lab.security.canonical import canonical_digest

__all__ = [
    "DAILY_WORKFLOW_VERSION", "STATE_FILE_NAME", "STATE_SCHEMA",
    "ACTION_PENDING", "ACTION_EXECUTED", "ACTION_NO_TRADE",
    "ACTION_REJECTED", "ACTION_CALENDAR_BLOCKED", "CycleResult",
    "DailyWorkflow", "DailyWorkflowHalt",
]

DAILY_WORKFLOW_VERSION = "business-daily-v0.3"
STATE_SCHEMA = "daily_workflow_state_v1"
STATE_FILE_NAME = "daily_state.json"
EXEC_STACK_DIRNAME = "exec"

ACTION_PENDING = "PENDING"
ACTION_EXECUTED = "EXECUTED"
ACTION_NO_TRADE = "NO_TRADE"
ACTION_REJECTED = "REJECTED"
ACTION_CALENDAR_BLOCKED = "CALENDAR_BLOCKED"

REASON_PENDING = "PENDING_NEXT_SESSION_OPEN"
REASON_COVERED_BLOCKED = "CALENDAR_COVERAGE_BLOCKED"

EVENT_VALIDITY_DAYS = 5   # assessment validity; expiry is checked per cycle

# _decide() result: (decision, regime, info_status, event ids, vol history)
DecideResult = tuple[DecisionOutput, RegimeAssessment, str, list[str],
                     list[str]]


class DailyWorkflowHalt(RuntimeError):
    """Reconciliation failed or HALT latched — operator decision required."""


@dataclass(frozen=True)
class CycleResult:
    """One cycle's JSON-safe record + whether it was an idempotent replay."""

    record: dict[str, object]
    replayed: bool


class _CycleClock:
    """Cycle-asof-driven clock — the only time source behind the stack."""

    def __init__(self) -> None:
        self.now: dt.datetime | None = None

    def __call__(self) -> dt.datetime:
        if self.now is None:
            raise RuntimeError("cycle clock used before the first cycle")
        return self.now


def daily_cycle_id(*, account_id: str, session_key: str, dataset_hash: str,
                   strategy_version: str) -> str:
    """Stable cycle identity from stable fields ONLY (account + session +
    data version + strategy version + workflow version)."""
    digest = canonical_digest({
        "kind": "daily-cycle", "workflow_version": DAILY_WORKFLOW_VERSION,
        "account_id": account_id, "session_key": session_key,
        "dataset_hash_prefix": dataset_hash[:16],
        "strategy_version": strategy_version,
    })
    return "dcy-" + digest[:16]


def _decision_to_pending(decision: DecisionOutput,
                         marks: Mapping[str, Decimal], *,
                         cycle_id: str,
                         session_date: dt.date) -> dict[str, object]:
    """Freeze a decision (target + rationale + hash) for later execution."""
    target = decision.target
    assert target is not None and decision.chosen_strategy_id is not None
    return {
        "cycle_id": cycle_id,
        "asof_utc": decision.asof_utc.isoformat(),
        "session_date": session_date.isoformat(),
        "chosen_strategy_id": decision.chosen_strategy_id,
        "decision_hash": decision.decision_hash,
        "rationale": decision.rationale,
        "allocation": {a.symbol: str(a.weight) for a in target.allocation},
        "marks": {k: str(v) for k, v in sorted(marks.items())},
    }


def _pending_to_decision(pending: Mapping[str, object], *,
                         account_id: str,
                         executable_symbols: Sequence[str]) -> DecisionOutput:
    """Rebuild the frozen decision for execution; ``executable_symbols``
    restricts it to legs that can actually fill this cycle (no fill
    price = never submitted), with dropped legs visible in the record."""
    allocation = dict(pending["allocation"])
    kept = {s: Decimal(str(w)) for s, w in allocation.items()
            if s in executable_symbols}
    asof = dt.datetime.fromisoformat(str(pending["asof_utc"]))
    cash = (Decimal(1) - sum(kept.values(), Decimal(0))).quantize(
        Decimal("0.00000001"))
    target = TargetPortfolio(
        account_id=account_id,
        allocation=tuple(AllocationItem(symbol=s, weight=w)
                         for s, w in sorted(kept.items())),
        cash_weight=cash, risk_budget_id=RISK_BUDGET_ID, timestamp=asof)
    return DecisionOutput(
        asof_utc=asof,
        chosen_strategy_id=str(pending["chosen_strategy_id"]),
        target=target, no_trade_reasons=(), candidate_scores={},
        rationale=str(pending["rationale"]),
        decision_hash=str(pending["decision_hash"]))


def _outcome_record(outcome: ExecutionOutcome) -> dict[str, object]:
    def _s(value) -> str | None:
        return None if value is None else str(value)

    return {
        "intent_id": outcome.intent_id,
        "client_order_id": outcome.client_order_id,
        "state": outcome.outcome_state,
        "risk_verdict": outcome.risk_verdict,
        "risk_reasons": list(outcome.risk_reasons),
        "order_notional_usd": _s(outcome.order_notional_usd),
        "order_shares": _s(outcome.order_shares),
        "fill_qty": _s(outcome.fill_qty),
        "fill_price": _s(outcome.fill_price),
    }


def _reconcile_problems(raw: Mapping[str, object]) -> list[str]:
    """Persisted-state consistency checks run BEFORE any restore."""
    problems: list[str] = []
    exec_state = dict(raw.get("exec") or {})
    fill_log = list(exec_state.get("fill_log") or [])
    try:
        cash = Decimal(str(exec_state["cash"]))
        initial = Decimal(str(exec_state["initial_cash"]))
        positions = {k: Decimal(str(v)) for k, v in
                     dict(exec_state.get("positions") or {}).items()}
        net_notional = Decimal(0)
        net_shares: dict[str, Decimal] = {}
        for fill in fill_log:
            sign = 1 if fill["side"] == "buy" else -1
            net_notional += sign * Decimal(str(fill["notional"]))
            sym = str(fill["symbol"])
            net_shares[sym] = (net_shares.get(sym, Decimal(0))
                               + sign * Decimal(str(fill["qty"])))
    except (KeyError, ArithmeticError, TypeError) as exc:
        return [f"EXEC_STATE_UNREADABLE:{type(exc).__name__}"]
    fees = MOCK_COMMISSION_PER_FILL * len(fill_log)
    if cash != initial - net_notional - fees:
        problems.append(
            f"LEDGER_CONSERVATION_BROKEN:cash={cash} vs "
            f"initial-net-fees={initial - net_notional - fees}")
    for sym in sorted(set(net_shares) | set(positions)):
        expected = net_shares.get(sym, Decimal(0))
        actual = positions.get(sym, Decimal(0))
        if actual != expected:
            problems.append(f"POSITIONS_DIVERGE_FROM_FILL_LOG:{sym}:"
                            f"state={actual},replayed={expected}")
    filled_outcomes = sum(
        1 for record in raw.get("completed_cycles") or ()
        for block in record.get("execution") or ()
        for o in block.get("outcomes", [])
        if o.get("state") in ("FILLED", "PARTIALLY_FILLED"))
    if filled_outcomes != len(fill_log):
        problems.append(f"FILL_LOG_COUNT_MISMATCH:records={filled_outcomes},"
                        f"fill_log={len(fill_log)}")
    return problems


class DailyWorkflow:
    """Restartable daily read-only analysis + virtual account engine."""

    def __init__(self, *, config: BusinessConfig, view: MarketDataView,
                 state_dir: Path, info_bundle: InfoBundle | None = None,
                 analyzers: Sequence[object] = ()) -> None:
        self._config = config
        self._view = view
        self._state_dir = Path(state_dir)
        self._state_dir.mkdir(parents=True, exist_ok=True)
        self._state_file = self._state_dir / STATE_FILE_NAME
        self._clock = _CycleClock()
        existing = self._state_file.exists()
        self._runner = ContinuousMockRunner(
            config=config, state_dir=self._state_dir / EXEC_STACK_DIRNAME,
            clock=self._clock, labels={"data_quality": view.data_quality},
            resume=existing)
        self._runner.bind_dataset(view.dataset_hash)
        self._features = FeatureEngine(config.features)
        self._regime = RegimeClassifierSession(
            RuleRegimeClassifier(config.regime))
        self._orchestrator = DecisionOrchestrator(
            config=config, stack=self._runner.stack)
        self._analyzers = tuple(analyzers)
        self._bundle = info_bundle
        self._state = self._fresh_state()
        if existing:
            try:
                self._load_and_restore()
            except BaseException:
                self._runner.close()   # no dangling sqlite handles on HALT
                raise

    @classmethod
    def open(cls, *, config: BusinessConfig, snapshot_dir: Path,
             state_dir: Path,
             info_file: Path | None = None) -> "DailyWorkflow":
        """Build from a collected snapshot (+ optional local information
        file). Strictly offline; the snapshot's admission truth travels
        unmodified into every record."""
        view = build_snapshot_view(Path(snapshot_dir))
        bundle = load_info_events([Path(info_file)]) \
            if info_file is not None else None
        analyzers = ((RuleInformationAnalyzer(),
                      LLMInformationAnalyzer(MockLLMClient({}), "mock:v1"))
                     if bundle is not None else ())
        return cls(config=config, view=view, state_dir=Path(state_dir),
                   info_bundle=bundle, analyzers=analyzers)

    # -- public surface ---------------------------------

    @property
    def runner(self) -> ContinuousMockRunner:
        """The persistent execution runner (ledger / stack access)."""
        return self._runner

    @property
    def records(self) -> tuple[dict[str, object], ...]:
        state = self._state
        return tuple([*state["completed_cycles"],
                      *state["blocked_cycles"]])  # type: ignore[list-item]

    @property
    def pending_count(self) -> int:
        return len(self._state["pending"])

    def run_daily_cycle(self, *, asof: dt.datetime) -> CycleResult:
        """One daily cycle at ``asof`` (the full analysis pipeline)."""
        return self._cycle(asof)

    def apply_decision(self, *, asof: dt.datetime,
                       decision: DecisionOutput) -> CycleResult:
        """One cycle with a SUPPLIED decision (operator/test seam for
        hand-built targets). Same frame: coverage, idempotency, pending
        drain, records, persistence. The decision is never executed in its
        own cycle — the PENDING rule applies unchanged."""
        return self._cycle(asof, override_decision=decision)

    def close(self) -> dict[str, object]:
        """Persist, then close the execution stack. Returns a summary."""
        self._save_state()
        conservation = self._runner.ledger.conservation_report()
        self._runner.close()
        state = self._state
        return {
            "mode": "DAILY_WORKFLOW", "ledger": conservation,
            "workflow_version": DAILY_WORKFLOW_VERSION,
            "cycles": len(state["completed_cycles"]),
            "blocked_cycles": len(state["blocked_cycles"]),
            "pending_open": len(state["pending"]),
            "halted": state["halted"],
        }

    # -- the cycle ---------------------------------------------------

    def _cycle(self, asof: dt.datetime,
               override_decision: DecisionOutput | None = None) -> CycleResult:
        if self._state["halted"] is not None:
            raise DailyWorkflowHalt(
                "state dir is HALT-latched: "
                f"{self._state['halted'].get('reasons')} — operator "
                "decision required")
        if asof.tzinfo is None or asof.utcoffset() is None:
            raise ValueError("asof must be timezone-aware (naive refused)")
        asof = asof.astimezone(dt.timezone.utc)
        asof_et_date = asof.astimezone(ET).date()
        sessions = self._view.session_dates
        session = next((d for d in reversed(sessions) if d <= asof_et_date),
                       None)
        if session is not None and asof_et_date > sessions[-1]:
            session = None   # beyond snapshot coverage: block, don't backfill
        if session is None:
            return self._blocked_cycle(asof, asof_et_date, sessions)
        self._clock.now = asof
        record = self._find_processed(session)
        if record is not None:
            return CycleResult(dict(record), True)   # idempotent no-op

        blocks = self._drain_pending(asof, session)
        decision, regime, info_status, event_ids, new_vol = \
            self._decide(asof, session)
        if override_decision is not None:
            decision = override_decision
        record = self._apply_decision(
            asof=asof, session=session, decision=decision, blocks=blocks,
            regime=regime, info_status=info_status, event_ids=event_ids)
        self._record_tracker_session(asof)
        state = self._state
        state["processed_sessions"] = sorted(
            set(state["processed_sessions"]) | {session.isoformat()})
        state["completed_cycles"] = list(state["completed_cycles"]) + [record]
        state["vol_history"] = new_vol
        state["cycle_counter"] = int(state["cycle_counter"]) + 1
        self._save_state()
        return CycleResult(record, False)

    # -- coverage-blocked cycles -------------------------------

    def _blocked_cycle(self, asof: dt.datetime, asof_et_date: dt.date,
                       sessions: Sequence[dt.date]) -> CycleResult:
        if not sessions:
            detail = "EMPTY_SNAPSHOT_CALENDAR"
        elif asof_et_date < sessions[0]:
            detail = (f"ASOF_BEFORE_FIRST_SESSION:"
                      f"first={sessions[0].isoformat()}")
        else:
            detail = (f"ASOF_BEYOND_LAST_SESSION:last={sessions[-1]},"
                      f"asof_et={asof_et_date} (no fabricated sessions; "
                      "historical supply is not forward data)")
        cycle_id = self._cycle_id_for(asof_et_date.isoformat())
        replayed = next((dict(s) for s in self._state["blocked_cycles"]
                         if s["cycle_id"] == cycle_id), None)
        if replayed is not None:
            return CycleResult(replayed, True)
        cash, positions, _ = self._account_snapshot({}, [])
        record = self._frame(asof, None, cycle_id) | {
            "action": ACTION_CALENDAR_BLOCKED, "decision_status": "NONE",
            "chosen_strategy": None, "target": None, "regime_labels": [],
            "info_status": self._info_status(0), "info_events": [],
            "execution": [],
            "reasons": [f"{REASON_COVERED_BLOCKED}:{detail}"],
            "cash": cash, "positions": positions, "equity": None,
        }
        blocked = self._state["blocked_cycles"]
        self._state["blocked_cycles"] = [*blocked, record]
        self._save_state()
        return CycleResult(record, False)

    # -- decision pipeline -------------------------------------

    def _decide(self, asof: dt.datetime, session: dt.date) -> DecideResult:
        symbols = sorted(self._view.stores)
        features = {}
        for symbol in symbols:
            other = next((self._view.stores[s] for s in symbols
                          if s != symbol), None)
            features[symbol] = self._features.compute(
                symbol, asof, self._view.stores[symbol], other_store=other)
        vol_history = [str(v) for v in self._state["vol_history"]]
        primary = features.get(PRIMARY_SYMBOL)
        if (primary is not None and primary.status == STATUS_OK
                and primary.realized_vol is not None):
            vol_history = vol_history + [str(primary.realized_vol)]
        usable = self._bundle.usable(asof) if self._bundle is not None else ()
        event_ids = [e.event_id for e in usable]
        assessments = []
        valid_until = asof + dt.timedelta(days=EVENT_VALIDITY_DAYS)
        for event in usable:
            event_valid = max(event.available_at_utc, event.received_at_utc) \
                + dt.timedelta(days=EVENT_VALIDITY_DAYS)
            if event_valid <= asof:   # fail-closed consumption
                continue
            for analyzer in self._analyzers:
                assessments.append(analyzer.assess(event, asof, event_valid))
        regime = self._regime.step(
            asof, features, assessments,
            tuple(Decimal(v) for v in vol_history), valid_until=valid_until)
        decision = self._orchestrator.decide(
            asof=asof, snapshot_id=f"daily-{session.isoformat()}",
            features=features, regime=regime, info_assessments=assessments,
            valid_until=valid_until)
        return (decision, regime, self._info_status(len(event_ids)),
                event_ids, vol_history)

    # -- execution bookkeeping -------------------------------

    def _drain_pending(self, asof: dt.datetime,
                       session: dt.date) -> list[dict[str, object]]:
        """Execute pendings whose fill session the market has reached."""
        blocks: list[dict[str, object]] = []
        still_pending: list[dict[str, object]] = []
        for pending in self._state["pending"]:
            decision_session = dt.date.fromisoformat(
                str(pending["session_date"]))
            fill_session = next(
                (d for d in self._view.session_dates if d > decision_session),
                None)
            reachable = (fill_session is not None
                         and fill_session <= session
                         and decision_session < session)
            if not reachable:
                still_pending.append(dict(pending))
                continue
            block, consumed = self._execute_pending(
                pending, asof=asof, fill_session=fill_session)
            blocks.append(block)
            if not consumed:
                still_pending.append(dict(pending))   # nothing was sent
        self._state["pending"] = still_pending
        return blocks

    def _execute_pending(self, pending: Mapping[str, object], *, asof,
                         fill_session: dt.date) -> tuple[dict[str, object],
                                                         bool]:
        """Execute one pending -> (record block, consumed). A pending
        with NO executable leg stays queued (nothing was submitted)."""
        decision_session = dt.date.fromisoformat(str(pending["session_date"]))
        marks = {k: Decimal(str(v))
                 for k, v in dict(pending["marks"]).items()}
        fill_prices = {s: self._view.next_open_price(s, decision_session)
                       for s in marks}
        executable = sorted(s for s, p in fill_prices.items() if p is not None)
        skipped = sorted(s for s in fill_prices if s not in set(executable))
        block: dict[str, object] = {
            "pending_cycle_id": pending["cycle_id"],
            "decision_session": decision_session.isoformat(),
            "fill_session": fill_session.isoformat(),
            "outcomes": [], "fills": 0, "refusals": 0,
            "skipped_legs": {s: "NO_FILL_PRICE_NO_ORDER" for s in skipped},
            "reasons": [f"NO_FILL_PRICE:{s}" for s in skipped],
        }
        if not executable:
            block["reasons"] = list(block["reasons"]) + \
                ["PENDING_KEPT_NO_EXECUTABLE_LEG"]
            return block, False
        decision = _pending_to_decision(
            pending, account_id=self._account_id,
            executable_symbols=executable)
        self._clock.now = asof
        outcomes = self._runner.step(
            asof=asof, decision=decision, marks=marks,
            next_opens={s: fill_prices[s] for s in executable})
        terminal = ("FILLED", "PARTIALLY_FILLED", "REJECTED", "HALT_NEW_RISK")
        filled = sum(1 for o in outcomes if o.outcome_state in terminal[:2])
        refused = sum(1 for o in outcomes if o.outcome_state in terminal[2:])
        reasons = [f"{o.outcome_state}:{','.join(o.risk_reasons) or 'broker'}"
                   for o in outcomes if o.outcome_state in terminal[2:]]
        block.update(outcomes=[_outcome_record(o) for o in outcomes],
                     fills=filled, refusals=refused, reasons=reasons)
        return block, True

    def _apply_decision(self, *, asof, session, decision: DecisionOutput,
                        blocks: Sequence[Mapping[str, object]], regime,
                        info_status: str,
                        event_ids: Sequence[str]) -> dict[str, object]:
        fills = sum(int(b["fills"]) for b in blocks)
        refusals = sum(int(b["refusals"]) for b in blocks)
        marks_now = self._pit_marks(asof)
        reasons: list[str] = [str(r) for block in blocks
                              for r in block["reasons"]]
        decision_status = "NONE"
        target_record: dict[str, object] | None = None
        if decision.target is None or decision.chosen_strategy_id is None:
            decision_status = "NO_TRADE"
            reasons.extend(decision.no_trade_reasons)
        else:
            allocation = {a.symbol: str(a.weight) for a in
                          sorted(decision.target.allocation,
                                 key=lambda a: a.symbol)}
            target_record = {"allocation": allocation,
                             "cash_weight": str(decision.target.cash_weight),
                             "decision_hash": decision.decision_hash}
            missing = sorted(s for s in allocation
                             if marks_now.get(s) is None)
            positions_now = self._runner.ledger.positions
            held_unmarked = sorted(s for s, q in positions_now.items()
                                   if q > 0 and marks_now.get(s) is None)
            if missing or held_unmarked:
                decision_status = "NO_TRADE"
                reasons.extend(f"MISSING_MARK:{s}" for s in missing)
                reasons.extend(f"HELD_SYMBOL_UNMARKED:{s}"
                               for s in held_unmarked)
                reasons.append("NO_FUTURE_PRICE_SIZING")
            else:
                decision_status = "PENDING"
                reasons.append(REASON_PENDING)
                cycle_id = self._cycle_id_for(session.isoformat())
                self._state["pending"] = [*self._state["pending"],
                                          _decision_to_pending(
                                              decision, marks_now,
                                              cycle_id=cycle_id,
                                              session_date=session)]
        action = (ACTION_EXECUTED if fills else
                  ACTION_REJECTED if refusals else
                  ACTION_NO_TRADE if decision_status == "NO_TRADE" else
                  ACTION_PENDING)
        cash, positions, equity = self._account_snapshot(marks_now, reasons)
        return self._frame(asof, session,
                           self._cycle_id_for(session.isoformat())) | {
            "action": action,
            "decision_status": decision_status,
            "chosen_strategy": decision.chosen_strategy_id,
            "target": target_record,
            "regime_labels": list(regime.labels),
            "info_status": info_status,
            "info_events": list(event_ids),
            "execution": [dict(b) for b in blocks],
            "reasons": reasons,
            "cash": cash, "positions": positions, "equity": equity,
        }

    # -- small helpers --------------------------------------

    @property
    def _account_id(self) -> str:
        return self._config.mock_execution.account_id

    @property
    def _strategy_version(self) -> str:
        return STRATEGY_VERSION

    def _cycle_id_for(self, session_key: str) -> str:
        return daily_cycle_id(
            account_id=self._account_id, session_key=session_key,
            dataset_hash=self._view.dataset_hash,
            strategy_version=self._strategy_version)

    def _info_status(self, usable_count: int) -> str:
        if self._bundle is None:
            return "NO_INFORMATION"
        return f"USABLE_EVENTS:{usable_count}" if usable_count \
            else "NO_USABLE_EVENTS_AT_ASOF"

    def _pit_marks(self, asof: dt.datetime) -> dict[str, Decimal]:
        marks: dict[str, Decimal] = {}
        for symbol, store in sorted(self._view.stores.items()):
            bar = store.last_available(symbol, asof)
            if bar is not None:
                marks[symbol] = bar.close
        return marks

    def _data_cut(self, asof: dt.datetime) -> dict[str, str | None]:
        cut: dict[str, str | None] = {}
        for symbol, store in sorted(self._view.stores.items()):
            bar = store.last_available(symbol, asof)
            cut[symbol] = None if bar is None else bar.ts_event_utc.isoformat()
        return cut

    def _equity(self, marks: Mapping[str, Decimal],
                reasons: list[str]) -> str | None:
        try:
            return str(self._runner.ledger.equity(marks))
        except ValueError as exc:
            reasons.append(f"EQUITY_UNVALUABLE:{exc}")
            return None

    def _account_snapshot(self, marks: Mapping[str, Decimal],
                          reasons: list[str]) -> tuple[str, dict[str, str],
                                                       str | None]:
        """(cash, positions, equity) for a cycle record."""
        ledger = self._runner.ledger
        return (str(ledger.cash),
                {k: str(v) for k, v in sorted(ledger.positions.items())},
                self._equity(marks, reasons))

    def _record_tracker_session(self, asof: dt.datetime) -> None:
        """Router virtual-tracker feedback on PIT-available closes (same
        convention as the replay loop); prev closes persist in state so a
        restart reproduces identical router scores."""
        closes: dict[str, Decimal | None] = {}
        for symbol, store in sorted(self._view.stores.items()):
            bars = store.available(symbol, asof)
            closes[symbol] = bars[-1].close if bars else None
        prev: dict[str, Decimal | None] = {
            s: None if v is None else Decimal(str(v))
            for s, v in (self._state.get("tracker_prev_closes") or {}).items()}
        self._orchestrator.tracker.record_session(
            asof, closes, prev, self._orchestrator.per_candidate_exposure())
        self._state["tracker_prev_closes"] = {
            s: (None if c is None else str(c)) for s, c in closes.items()}

    def _frame(self, asof: dt.datetime, session: dt.date | None,
               cycle_id: str) -> dict[str, object]:
        view = self._view
        sessions = view.session_dates
        return {
            "workflow_version": DAILY_WORKFLOW_VERSION,
            "cycle_id": cycle_id,
            "cycle_number": int(self._state["cycle_counter"]) + 1,
            "asof_utc": asof.isoformat(),
            "asof_date": asof.astimezone(ET).date().isoformat(),
            "session_date": None if session is None else session.isoformat(),
            "account_id": self._account_id,
            "data": {
                "dataset_hash": view.dataset_hash,
                "data_quality": view.data_quality,
                "source_mode": view.source_mode,
                "research_admitted": view.research_admitted,
                "admission_blockers": list(view.blockers),
                "last_snapshot_session": (None if not sessions else
                                          sessions[-1].isoformat()),
                "data_cut_utc": self._data_cut(asof),
            },
        }

    def _find_processed(self, session: dt.date) -> dict[str, object] | None:
        return next((r for r in self._state["completed_cycles"]
                     if r.get("session_date") == session.isoformat()), None)

    # -- state persistence ---------------------------------

    def _fresh_state(self) -> dict[str, object]:
        return {
            "schema": STATE_SCHEMA,
            "workflow_version": DAILY_WORKFLOW_VERSION,
            "account_id": self._account_id,
            "strategy_version": self._strategy_version,
            "dataset_hash": self._view.dataset_hash,
            "halted": None, "cycle_counter": 0,
            "processed_sessions": [], "completed_cycles": [],
            "blocked_cycles": [], "pending": [], "vol_history": [],
            "tracker_prev_closes": {},
            "regime": {"committed": None, "pending_labels": None,
                       "pending_count": 0},
            "decision_plane": {"tracker_returns": {},
                               "last_proposal_exposure": {},
                               "router_previous_target": {}},
            "exec": self._runner.export_state(),
        }

    def _save_state(self) -> None:
        self._state["exec"] = self._runner.export_state()
        self._state["regime"] = self._regime_snapshot()
        self._state["decision_plane"] = self._decision_plane_snapshot()
        self._state["dataset_hash"] = self._view.dataset_hash
        payload = json.dumps(self._state, sort_keys=True, ensure_ascii=False)
        self._state_file.write_text(payload, encoding="utf-8")

    def _load_and_restore(self) -> None:
        raw = json.loads(self._state_file.read_text(encoding="utf-8"))
        if raw.get("schema") != STATE_SCHEMA:
            raise ValueError(f"state file {self._state_file} schema "
                             f"{raw.get('schema')!r} != {STATE_SCHEMA} "
                             "— refusing to guess")
        halted = raw.get("halted")
        if halted is not None:
            raise DailyWorkflowHalt(f"state dir {self._state_dir} is "
                                    f"HALT-latched: {halted.get('reasons')}"
                                    " — operator decision required")
        problems = _reconcile_problems(raw)
        if problems:
            raw["halted"] = {"phase": "RELOAD_RECONCILIATION",
                             "reasons": problems}
            self._state_file.write_text(json.dumps(raw, sort_keys=True),
                                        encoding="utf-8")
            raise DailyWorkflowHalt("reconciliation failed on reload — "
                                    "HALT latched: " + "; ".join(problems))
        self._state = raw
        self._runner.restore_state(raw["exec"])
        self._restore_regime(raw["regime"])
        self._restore_decision_plane(raw["decision_plane"])

    # documented same-package persistence shims: these collaborators carry
    # cross-session state with no public setters; the attributes below are
    # their complete state and are restored verbatim from the state file.

    def _regime_snapshot(self) -> dict[str, object]:
        session = self._regime
        committed = getattr(session, "_committed", None)
        labels = getattr(session, "_pending_labels", None)
        return {
            "committed": (None if committed is None
                          else committed.model_dump(mode="json")),
            "pending_labels": None if labels is None else list(labels),
            "pending_count": int(getattr(session, "_pending_count", 0)),
        }

    def _restore_regime(self, snap: Mapping[str, object]) -> None:
        committed = snap.get("committed")
        regime = self._regime
        regime._committed = (None if committed is None  # noqa: SLF001
            else RegimeAssessment.model_validate_json(json.dumps(committed)))
        labels = snap.get("pending_labels")
        regime._pending_labels = (None if labels is None  # noqa: SLF001
                                  else tuple(str(x) for x in labels))
        pending_count = int(snap.get("pending_count") or 0)
        regime._pending_count = pending_count  # noqa: SLF001

    def _decision_plane_snapshot(self) -> dict[str, object]:
        orch = self._orchestrator
        return {
            "tracker_returns": {
                cid: [str(v) for v in history] for cid, history
                in getattr(orch.tracker, "_returns", {}).items()},
            "last_proposal_exposure": {
                cid: {s: str(w) for s, w in dict(exposure).items()}
                for cid, exposure in getattr(
                    orch, "_last_proposal_exposure", {}).items()},
            "router_previous_target": {
                s: str(w) for s, w
                in getattr(orch.router, "_previous_target", {}).items()},
        }

    def _restore_decision_plane(self, snap: Mapping[str, object]) -> None:
        orch = self._orchestrator
        window = int(getattr(orch.tracker, "_window", 60))
        orch.tracker._returns = {  # noqa: SLF001
            str(cid): deque((Decimal(str(v)) for v in values), maxlen=window)
            for cid, values in dict(snap.get("tracker_returns") or {}).items()}
        orch._last_proposal_exposure = {  # noqa: SLF001
            str(cid): {s: Decimal(str(w)) for s, w in dict(exposure).items()}
            for cid, exposure
            in dict(snap.get("last_proposal_exposure") or {}).items()}
        orch.router._previous_target = {  # noqa: SLF001
            str(s): Decimal(str(w)) for s, w
            in dict(snap.get("router_previous_target") or {}).items()}
