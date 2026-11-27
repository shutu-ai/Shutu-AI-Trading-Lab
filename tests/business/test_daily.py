"""V0.3 daily workflow tests (task §3 minimum business acceptance).

Fixture choice (documented, per the task's "pick ONE"): the SHORT
collector-shaped probe snapshot pattern from
``tests/business/test_snapshot_source.py`` — a tiny hand-built
``historical_research`` namespace (12 sessions per symbol, FAKE_TRANSPORT
probe bars, collector manifest with real hashes), loaded through the REAL
``build_snapshot_view``. The daily engine is the production path
end-to-end (features -> info -> regime -> orchestrator ->
ContinuousMockRunner -> OMS/FakeBroker); only the snapshot itself is
offline fixture data, labeled HISTORICAL_EXPLORATORY /
SYNTHETIC_OFFLINE_ONLY in every record.

Feature windows are reduced (test-only config prior, same shape as
``test_replay.py``'s reduced fixture) so ~12 sessions warm the pipeline.

Accepted scenarios (task §3): >=5 consecutive offline daily cycles with
evolving positions; overnight PENDING -> next-cycle execution;
NO_INFORMATION cycle; missing-mark cycle (no future-price sizing); risk
refusal; mid-sequence restart with idempotent re-run; duplicate fill
event delivery; reconciliation failure -> HALT; determinism of records.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import shutil
import sys
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Iterator

import pytest
import yaml

from trading_lab.business.config import (
    BusinessConfig,
    FeaturesConfig,
    load_config,
)
from trading_lab.business.daily import (
    ACTION_CALENDAR_BLOCKED,
    ACTION_EXECUTED,
    ACTION_NO_TRADE,
    ACTION_PENDING,
    ACTION_REJECTED,
    DailyWorkflow,
    DailyWorkflowHalt,
    daily_cycle_id,
)
from trading_lab.business.information import content_hash_of
from trading_lab.business.series import QUALITY_PIT_ASSUMED_NEXT_OPEN
from trading_lab.business.snapshot_source import (
    ADMISSION_RESTRICTED,
    COLLECTED_STATUS,
    LICENSE_UNVERIFIED,
    MANIFEST_SCHEMA,
    NAMESPACE_MARKER,
    PIT_LEVEL_ASSUMED,
    SOURCE_PROBE,
    TRANSPORT_MODE_PROBE,
)
from trading_lab.business.types import DecisionOutput
from trading_lab.contracts import (
    AdjustmentKind,
    AllocationItem,
    MarketBar,
    TargetPortfolio,
)

REPO = Path(__file__).resolve().parents[2]
UTC = dt.timezone.utc

SESSION_DATES = [dt.date(2024, 1, d)
                 for d in (2, 3, 4, 5, 8, 9, 10, 11, 12, 15, 16, 17)]
# SPY rises for 8 sessions then falls (its own MA cross flips the leg
# flat); QQQ rises throughout — the book ENTERS, holds, trims, EXITS.
SPY_CLOSES = [Decimal(c) for c in
              ("100.00", "101.00", "102.00", "103.00", "104.00", "105.00",
               "106.00", "107.00", "104.00", "101.00", "98.00", "95.00")]
QQQ_CLOSES = [Decimal("2%02d.00" % i) for i in range(12)]

DAILY_FEATURES = FeaturesConfig(
    ma_short=2, ma_long=3, rsi_period=3, atr_period=3,
    realized_vol_window=4, volume_window=3, corr_window=6,
    corr_min_common=3, stale_after_sessions=3)


def daily_config() -> BusinessConfig:
    base = load_config(REPO / "configs/business_mvp_demo.yaml")
    return base.model_copy(update={"features": DAILY_FEATURES})


def session_asof(index: int) -> dt.datetime:
    """Decision instant for the i-th (1-based) session: its close, UTC."""
    return dt.datetime.combine(SESSION_DATES[index - 1], dt.time(21, 0),
                               tzinfo=UTC)


# ---------------------------------------------------------------------------
# collector-shaped probe snapshot (same layout as the V0.2 collector)
# ---------------------------------------------------------------------------


def _bar(symbol: str, index: int, close: Decimal) -> MarketBar:
    session_date = SESSION_DATES[index - 1]
    return MarketBar(
        asset_id=symbol,
        ts_event_utc=dt.datetime.combine(session_date, dt.time(21, 0),
                                         tzinfo=UTC),
        ts_available_utc=dt.datetime.combine(
            session_date + dt.timedelta(days=1), dt.time(13, 30), tzinfo=UTC),
        interval="1Day",
        open=close,
        high=close + Decimal("1.00"),
        low=close - Decimal("1.00"),
        close=close,
        volume=Decimal("1000000"),
        source=SOURCE_PROBE,
        adjustment=AdjustmentKind.RAW,
        quality=QUALITY_PIT_ASSUMED_NEXT_OPEN,
    )


def _write_snapshot(root: Path, specs: dict[str, list[MarketBar]]) -> Path:
    """Write a collector-shaped namespace root (manifest + per-symbol
    bars.jsonl with real hashes), exactly like the V0.2 probe output."""
    root.mkdir(parents=True, exist_ok=True)
    all_dates = [b.ts_event_utc.date() for bars in specs.values()
                 for b in bars]
    symbols: dict[str, object] = {}
    for symbol, bars in specs.items():
        directory = root / symbol
        directory.mkdir(parents=True, exist_ok=True)
        payload = "\n".join(b.model_dump_json() for b in bars) + "\n"
        bars_path = directory / "bars.jsonl"
        bars_path.write_text(payload, encoding="utf-8")
        symbols[symbol] = {"row_count": len(bars),
                           "bars_sha256": hashlib.sha256(
                               bars_path.read_bytes()).hexdigest()}
    manifest: dict[str, object] = {
        "schema": MANIFEST_SCHEMA,
        "status": COLLECTED_STATUS,
        "namespace": NAMESPACE_MARKER,
        "window": {"start": min(all_dates).isoformat(),
                   "end": max(all_dates).isoformat()},
        "transport": {"mode": TRANSPORT_MODE_PROBE,
                      "label": "FAKE_TRANSPORT",
                      "real_network_used": False},
        "calendar_supply": {"version": "NYSE-2017-2025-TEST-v1",
                            "hash": "a" * 64, "hash_frozen": "b" * 64},
        "symbols": symbols,
        "license": {"status": LICENSE_UNVERIFIED},
        "pit": {"level": PIT_LEVEL_ASSUMED,
                "rule": "daily_close_available_next_open"},
        "admission": {"status": ADMISSION_RESTRICTED},
    }
    (root / "collection_manifest.json").write_text(
        json.dumps(manifest, sort_keys=True), encoding="utf-8")
    return root


def _default_specs(qqq_from: int = 1) -> dict[str, list[MarketBar]]:
    return {
        "SPY": [_bar("SPY", i, c) for i, c in enumerate(SPY_CLOSES, 1)],
        "QQQ": [_bar("QQQ", i, c)
                for i, c in enumerate(QQQ_CLOSES, 1) if i >= qqq_from],
    }


@contextmanager
def workflow(state_dir: Path, snapshot: Path,
             info_file: Path | None = None) -> Iterator[DailyWorkflow]:
    wf = DailyWorkflow.open(config=daily_config(), snapshot_dir=snapshot,
                            state_dir=state_dir, info_file=info_file)
    try:
        yield wf
    finally:
        wf.close()


def _run_cycles(wf: DailyWorkflow, first: int, last: int) -> list[dict]:
    return [wf.run_daily_cycle(asof=session_asof(i)).record
            for i in range(first, last + 1)]


def _fills(rec: dict) -> list[dict]:
    return [o for block in rec["execution"] for o in block["outcomes"]
            if o["state"] in ("FILLED", "PARTIALLY_FILLED")]


def _constructed_decision(weights: dict[str, str],
                          asof: dt.datetime) -> DecisionOutput:
    alloc = tuple(AllocationItem(symbol=s, weight=Decimal(w))
                  for s, w in sorted(weights.items()))
    cash = Decimal(1) - sum(Decimal(w) for w in weights.values())
    target = TargetPortfolio(
        account_id="MOCK-ACCT-001", allocation=alloc, cash_weight=cash,
        risk_budget_id="BUSINESS_DEMO_RISK_BUDGET", timestamp=asof)
    return DecisionOutput(
        asof_utc=asof, chosen_strategy_id="operator_override",
        target=target, no_trade_reasons=(), candidate_scores={},
        rationale="constructed test decision", decision_hash="c" * 64)


@pytest.fixture()
def snapshot(tmp_path: Path) -> Path:
    return _write_snapshot(tmp_path / "snapshot", _default_specs())


# ---------------------------------------------------------------------------
# >=5 consecutive cycles, overnight PENDING -> next-cycle execution
# ---------------------------------------------------------------------------


class TestConsecutiveCycles:
    def test_twelve_cycles_pending_then_executed(
            self, tmp_path: Path, snapshot: Path) -> None:
        with workflow(tmp_path / "state", snapshot) as wf:
            records = _run_cycles(wf, 1, 12)
        assert len(records) == 12
        # warmup cycles honestly NO_TRADE (features UNKNOWN early)
        assert all(r["action"] == ACTION_NO_TRADE for r in records[:3])
        # a first executable decision is recorded PENDING: target persisted,
        # rationale/hash kept, NO orders
        first_pending = next(r for r in records
                             if r["action"] == ACTION_PENDING)
        assert first_pending["decision_status"] == "PENDING"
        assert first_pending["target"]["allocation"]
        assert first_pending["target"]["decision_hash"]
        assert first_pending["execution"] == []
        assert "PENDING_NEXT_SESSION_OPEN" in first_pending["reasons"]
        # the NEXT cycle executes the overnight pending (fills land)
        executed = records[records.index(first_pending) + 1]
        assert executed["action"] == ACTION_EXECUTED
        fills = _fills(executed)
        assert len(fills) >= 1
        assert all(Decimal(o["fill_price"]) > 0 for o in fills)
        assert all(Decimal(o["order_shares"]) > 0 for o in fills)
        # positions EVOLVE: entry first, then >=5 consecutive cycles on a
        # live book, and the SPY leg fully exits once its trend flips
        with_positions = [r for r in records if r["positions"] not in
                          ({}, {"SPY": "0", "QQQ": "0"})]
        assert len(with_positions) >= 5
        exit_cycle = [r for r in records
                      if r["positions"].get("SPY", "0") == "0"
                      and r["positions"] not in ({}, {"SPY": "0", "QQQ": "0"})]
        assert exit_cycle, "SPY leg never exits after the trend flip"

    def test_ledger_conservation_and_no_information(
            self, tmp_path: Path, snapshot: Path) -> None:
        with workflow(tmp_path / "state", snapshot) as wf:
            records = _run_cycles(wf, 1, 12)
            summary = wf.close()
        assert summary["ledger"]["ok"] is True
        assert summary["ledger"]["identity_delta"] == "0.00"
        assert summary["cycles"] == 12
        assert summary["halted"] is None
        for rec in records:
            assert rec["info_status"] == "NO_INFORMATION"
            assert rec["data"]["data_quality"] == "HISTORICAL_EXPLORATORY"
            assert rec["data"]["research_admitted"] is False
            assert rec["data"]["data_cut_utc"]


# ---------------------------------------------------------------------------
# operator-supplied information file
# ---------------------------------------------------------------------------


class TestInformationFile:
    def test_usable_event_recorded(self, tmp_path: Path,
                                   snapshot: Path) -> None:
        content = ("Company earnings beat estimates and raise full-year "
                   "guidance for the quarter.")
        row = {
            "event_id": "EVT-DAILY-001", "asset": "SPY",
            "source": "operator", "source_url": "local://fixture",
            "event_at_utc": "2024-01-08T14:00:00+00:00",
            "published_at_utc": "2024-01-08T14:05:00+00:00",
            "available_at_utc": "2024-01-08T14:10:00+00:00",
            "received_at_utc": "2024-01-08T14:15:00+00:00",
            "content": content, "content_hash": content_hash_of(content),
        }
        info_file = tmp_path / "info.jsonl"
        info_file.write_text(json.dumps(row) + "\n", encoding="utf-8")
        with workflow(tmp_path / "state", snapshot, info_file) as wf:
            records = _run_cycles(wf, 6, 7)
        assert records[0]["info_status"] == "USABLE_EVENTS:1"
        assert records[0]["info_events"] == ["EVT-DAILY-001"]


# ---------------------------------------------------------------------------
# missing mark -> NO_TRADE, never future-price sizing
# ---------------------------------------------------------------------------


class TestMissingMark:
    def test_missing_mark_cycle_no_orders(self, tmp_path: Path) -> None:
        snap = _write_snapshot(tmp_path / "snapshot",
                               _default_specs(qqq_from=3))
        asof = session_asof(2)   # SPY bar s1 available; QQQ has NO bar yet
        with workflow(tmp_path / "state", snap) as wf:
            result = wf.apply_decision(
                asof=asof, decision=_constructed_decision(
                    {"SPY": "0.5", "QQQ": "0.5"}, asof))
        rec = result.record
        assert rec["action"] == ACTION_NO_TRADE
        assert rec["decision_status"] == "NO_TRADE"
        assert "MISSING_MARK:QQQ" in rec["reasons"]
        assert "NO_FUTURE_PRICE_SIZING" in rec["reasons"]
        assert rec["positions"] == {}
        assert rec["target"] is not None   # decision recorded, never executed
        assert wf.pending_count == 0


# ---------------------------------------------------------------------------
# risk refusal (target weight 1.0 on a book with almost no settled cash)
# ---------------------------------------------------------------------------


class TestRiskRefusal:
    def test_refusal_recorded_never_bypassed(self, tmp_path: Path,
                                             snapshot: Path) -> None:
        with workflow(tmp_path / "state", snapshot) as wf:
            held = _run_cycles(wf, 1, 8)   # entry filled; book ~fully held
            assert held[-1]["positions"], "book never entered"
            asof = session_asof(9)
            # 1) natural settled-funds refusal: the drained rebalance wants
            #    the missing leg but settled cash is almost zero
            natural = wf.apply_decision(
                asof=asof, decision=_constructed_decision(
                    {"QQQ": "1.0"}, asof))
            natural_rejected = [o for b in natural.record["execution"]
                                for o in b["outcomes"]
                                if o["state"] == "REJECTED"]
            assert natural_rejected, "natural settled-funds refusal missing"
            assert any("INSUFFICIENT_SETTLED_FUNDS" in o["risk_reasons"]
                       for o in natural_rejected)
            # 2) forced refusal via an oversized target weight on an
            #    over-cap book (ledger seeded directly, the same MOCK drill
            #    as test_continuous.py): BOTH legs must be refused through
            #    the real RiskEngine — no bypass, no partial send
            wf.runner.ledger.positions["QQQ"] = Decimal("300")
            wf.runner.ledger.cash = Decimal("10.00")
            forced_asof = session_asof(11)
            forced = wf.apply_decision(
                asof=forced_asof, decision=_constructed_decision(
                    {"SPY": "1.0"}, forced_asof))
            assert forced.record["decision_status"] == "PENDING"
            executed = wf.run_daily_cycle(asof=session_asof(12))
        rec = executed.record
        assert rec["action"] == ACTION_REJECTED
        block = rec["execution"][0]
        assert block["fills"] == 0 and block["refusals"] == 2
        for outcome in block["outcomes"]:
            assert outcome["state"] == "REJECTED"
            assert any(r.startswith("ORDER_NOTIONAL_EXCEEDED")
                       for r in outcome["risk_reasons"])
        assert any(r.startswith("REJECTED:ORDER_NOTIONAL_EXCEEDED")
                   for r in rec["reasons"])
        assert rec["positions"].get("QQQ") == "300"   # refused order never
        assert rec["positions"].get("SPY", "0") == "0"  # became a position


# ---------------------------------------------------------------------------
# restart mid-sequence + idempotent replay + determinism
# ---------------------------------------------------------------------------


class TestRestartAndDeterminism:
    def test_restart_restores_state_and_replays_idempotently(
            self, tmp_path: Path, snapshot: Path) -> None:
        state_dir = tmp_path / "state"
        with workflow(state_dir, snapshot) as wf:
            _run_cycles(wf, 1, 6)   # first decision pending, nothing filled
            saved_cash = wf.runner.ledger.cash
            saved_positions = dict(wf.runner.ledger.positions)
        with workflow(state_dir, snapshot) as wf:
            assert wf.runner.ledger.cash == saved_cash
            assert wf.runner.ledger.positions == saved_positions
            assert wf.pending_count == 1   # the pending decision restored
            broker = wf.runner.stack.fake_broker
            created_before = broker.total_created()
            replay = wf.run_daily_cycle(asof=session_asof(6))
            assert replay.replayed is True
            assert broker.total_created() == created_before  # no new orders
            seventh = wf.run_daily_cycle(asof=session_asof(7))
        assert seventh.record["action"] == ACTION_EXECUTED
        assert len(_fills(seventh.record)) >= 1   # restored pending filled

    def test_restarted_run_equals_uninterrupted_run(
            self, tmp_path: Path, snapshot: Path) -> None:
        state_dir = tmp_path / "restarted"
        with workflow(state_dir, snapshot) as wf:
            _run_cycles(wf, 1, 6)
        with workflow(state_dir, snapshot) as wf:
            _run_cycles(wf, 7, 8)
            restarted = wf.records
            restarted_state = (wf.runner.ledger.cash,
                               dict(wf.runner.ledger.positions))
        with workflow(tmp_path / "uninterrupted", snapshot) as wf:
            _run_cycles(wf, 1, 8)
            uninterrupted = wf.records
            uninterrupted_state = (wf.runner.ledger.cash,
                                   dict(wf.runner.ledger.positions))
        assert json.dumps(restarted, sort_keys=True, default=str) == \
            json.dumps(uninterrupted, sort_keys=True, default=str)
        assert restarted_state == uninterrupted_state

    def test_cycle_ids_stable_fields_only(self) -> None:
        expect = daily_cycle_id(
            account_id="MOCK-ACCT-001", session_key="2024-01-05",
            dataset_hash="d" * 32, strategy_version="V2")
        again = daily_cycle_id(
            account_id="MOCK-ACCT-001", session_key="2024-01-05",
            dataset_hash="d" * 32, strategy_version="V2")
        other = daily_cycle_id(
            account_id="MOCK-ACCT-001", session_key="2024-01-08",
            dataset_hash="d" * 32, strategy_version="V2")
        assert expect == again and expect != other
        assert expect.startswith("dcy-")


# ---------------------------------------------------------------------------
# duplicate fill-event delivery (process_fill idempotency)
# ---------------------------------------------------------------------------


class TestDuplicateFillEvent:
    def test_same_event_twice_refused(self, tmp_path: Path,
                                      snapshot: Path) -> None:
        with workflow(tmp_path / "state", snapshot) as wf:
            records = _run_cycles(wf, 1, 8)   # entry filled along the way
            filled = [o for r in records for o in _fills(r)]
            assert filled, "no fill available to replay"
            target = filled[0]
            broker = wf.runner.stack.fake_broker
            ledger_fills = len(wf.runner.ledger.fill_log)
            # the SAME broker event id delivered a second time
            dup_event = broker.apply_fill(
                target["client_order_id"], Decimal("1"), duplicate=True)
            recorded = wf.runner.stack._refs.oms.process_fill(  # noqa: SLF001
                target["intent_id"], dup_event, Decimal("1"))
        assert recorded is False   # OMS refuses the duplicate delivery
        assert len(wf.runner.ledger.fill_log) == ledger_fills


# ---------------------------------------------------------------------------
# reconciliation failure -> HALT (operator decision needed)
# ---------------------------------------------------------------------------


class TestReconciliationHalt:
    def test_corrupt_positions_halts_and_latches(
            self, tmp_path: Path, snapshot: Path) -> None:
        state_dir = tmp_path / "state"
        with workflow(state_dir, snapshot) as wf:
            _run_cycles(wf, 1, 8)
        corrupt_dir = tmp_path / "corrupt"
        shutil.copytree(state_dir, corrupt_dir)
        state_path = corrupt_dir / "daily_state.json"
        raw = json.loads(state_path.read_text(encoding="utf-8"))
        raw["exec"]["positions"]["SPY"] = "999"   # vs the replayed fill log
        state_path.write_text(json.dumps(raw), encoding="utf-8")
        with pytest.raises(DailyWorkflowHalt) as excinfo:
            DailyWorkflow.open(config=daily_config(), snapshot_dir=snapshot,
                               state_dir=corrupt_dir)
        assert "POSITIONS_DIVERGE_FROM_FILL_LOG" in str(excinfo.value)
        latched = json.loads(state_path.read_text(encoding="utf-8"))
        assert latched["halted"] is not None
        assert latched["halted"]["phase"] == "RELOAD_RECONCILIATION"
        # the latch refuses every later run until the operator intervenes
        with pytest.raises(DailyWorkflowHalt):
            DailyWorkflow.open(config=daily_config(), snapshot_dir=snapshot,
                               state_dir=corrupt_dir)


# ---------------------------------------------------------------------------
# calendar coverage honesty
# ---------------------------------------------------------------------------


class TestCalendarCoverage:
    def test_asof_beyond_snapshot_blocked(
            self, tmp_path: Path, snapshot: Path) -> None:
        with workflow(tmp_path / "state", snapshot) as wf:
            far = dt.datetime(2026, 11, 27, 21, 0, tzinfo=UTC)
            result = wf.run_daily_cycle(asof=far)
            again = wf.run_daily_cycle(asof=far)
            before = wf.run_daily_cycle(
                asof=dt.datetime(2024, 1, 1, 21, 0, tzinfo=UTC))
        rec = result.record
        assert rec["action"] == ACTION_CALENDAR_BLOCKED
        assert rec["reasons"][0].startswith("CALENDAR_COVERAGE_BLOCKED:")
        assert "ASOF_BEYOND_LAST_SESSION" in rec["reasons"][0]
        assert rec["session_date"] is None
        assert rec["execution"] == []
        assert again.replayed is True   # blocked re-run is idempotent
        assert before.record["reasons"][0].startswith(
            "CALENDAR_COVERAGE_BLOCKED:ASOF_BEFORE_FIRST_SESSION")

    def test_naive_asof_refused(self, tmp_path: Path,
                                snapshot: Path) -> None:
        with workflow(tmp_path / "state", snapshot) as wf:
            with pytest.raises(ValueError):
                wf.run_daily_cycle(
                    asof=dt.datetime(2024, 1, 4, 21, 0))   # naive: refused


# ---------------------------------------------------------------------------
# CLI wiring (mode=daily)
# ---------------------------------------------------------------------------


def _write_reduced_config(path: Path) -> Path:
    payload = {"business_mvp": {"mode": "replay", "features": {
        "ma_short": 2, "ma_long": 3, "rsi_period": 3, "atr_period": 3,
        "realized_vol_window": 4, "volume_window": 3, "corr_window": 6,
        "corr_min_common": 3, "stale_after_sessions": 3}}}
    path.write_text(yaml.safe_dump(payload, sort_keys=False),
                    encoding="utf-8")
    return path


class TestCliDaily:
    def test_cli_daily_end_to_end(self, tmp_path: Path, snapshot: Path,
                                  capsys) -> None:
        from scripts.run_business_mvp import main as cli_main
        config = _write_reduced_config(tmp_path / "config_daily.yaml")
        argv = ["--mode", "daily",
                "--asof", "2024-01-17T21:00:00+00:00",
                "--snapshot-dir", str(snapshot),
                "--state-dir", str(tmp_path / "state"),
                "--output-dir", str(tmp_path / "out"),
                "--config", str(config)]
        assert cli_main(argv) == 0
        summary = json.loads(
            (tmp_path / "out" / "summary.json").read_text(encoding="utf-8"))
        assert summary["action"] == ACTION_PENDING
        assert summary["honesty_labels"]["BROKER_BEHAVIOR"] == "MOCK_ONLY"
        assert (tmp_path / "out" / "cycles.jsonl").is_file()
        assert "FAKE_BROKER" in capsys.readouterr().out
        # same asof again: idempotent replay, exit 0
        assert cli_main(argv) == 0
        summary2 = json.loads(
            (tmp_path / "out" / "summary.json").read_text(encoding="utf-8"))
        assert summary2["idempotent_replay"] is True

    def test_cli_daily_fail_closed(self, tmp_path: Path,
                                   snapshot: Path) -> None:
        from scripts.run_business_mvp import main as cli_main
        base = ["--mode", "daily",
                "--snapshot-dir", str(snapshot),
                "--state-dir", str(tmp_path / "state"),
                "--output-dir", str(tmp_path / "out")]
        assert cli_main(base) == 2                        # no asof
        assert cli_main(base + ["--asof", "2024-01-05T21:00:00"]) == 2
        assert cli_main(base + ["--asof", "not-a-timestamp"]) == 2
        assert cli_main([
            "--mode", "daily",
            "--asof", "2024-01-05T21:00:00+00:00",
            "--snapshot-dir", str(snapshot),
            "--output-dir", str(tmp_path / "out")]) == 2   # no state-dir
