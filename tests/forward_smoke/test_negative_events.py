"""Abnormal-event negatives: every anomaly is rejected or conservatively
held — never silently repaired (task S3)."""

from __future__ import annotations

import copy
import datetime as dt
from decimal import Decimal
from pathlib import Path

from apps.trading_daemon.engine import ShadowForwardEngine
from apps.trading_daemon.fixture import build_fixture_events
from apps.trading_daemon.identity import build_forward_identity
from apps.trading_daemon.journal import ForwardJournal, read_entries
from apps.trading_daemon.rule import B2ForwardRule

REPO_ROOT = Path(__file__).resolve().parents[2]


def _kind_seq(entries, kind):
    return [e for e in entries if e["event_type"] == kind]


def _reject_reasons(entries):
    return [e["payload"]["reason"] for e in _kind_seq(entries, "REJECTED")]


def _held_reasons(entries):
    return [e["payload"]["reason"] for e in _kind_seq(entries, "HELD")]


def _fresh_engine(tmp_path, prereg):
    state = tmp_path / "state"
    state.mkdir(exist_ok=True)
    journal = ForwardJournal.open(state / "journal.jsonl", prereg=prereg)
    identity = build_forward_identity(repo_root=REPO_ROOT)
    return ShadowForwardEngine(
        journal=journal, prereg=prereg, rule=B2ForwardRule(2, 4),
        code_identity=identity), state


def _drive(engine, events):
    return [engine.process_event(dict(e)) for e in events]


def test_unadmitted_source_rejected(tmp_path, prereg, fixture_events):
    engine, state = _fresh_engine(tmp_path, prereg)
    ev = copy.deepcopy(fixture_events[0])
    ev["source"] = "unlicensed-vendor-x"
    engine.process_event(ev)
    assert "SOURCE_NOT_ADMITTED" in _reject_reasons(
        read_entries(state / "journal.jsonl"))


def test_unadmitted_dataset_hash_rejected(tmp_path, prereg, fixture_events):
    engine, state = _fresh_engine(tmp_path, prereg)
    ev = copy.deepcopy(fixture_events[0])
    ev["dataset_hash"] = "1" * 64
    engine.process_event(ev)
    assert "DATASET_NOT_ADMITTED" in _reject_reasons(
        read_entries(state / "journal.jsonl"))


def test_weekend_session_clock_rejected(tmp_path, prereg, fixture_events):
    engine, state = _fresh_engine(tmp_path, prereg)
    ev = copy.deepcopy(fixture_events[4])   # Friday 2026-03-06
    ev["event_id"] = "weekend-1"
    sat = ev["ts_event"] + dt.timedelta(days=1)  # 2026-03-07 is a Saturday
    assert sat.weekday() == 5
    ev["ts_event"] = sat
    ev["ts_available"] = sat
    ev["received_at"] = sat + dt.timedelta(minutes=5)
    engine.process_event(ev)
    assert "MARKET_CLOCK" in _reject_reasons(
        read_entries(state / "journal.jsonl"))


def test_off_session_clock_rejected(tmp_path, prereg, fixture_events):
    """A trading-day timestamp outside the declared session window is an
    illegal market clock."""
    engine, state = _fresh_engine(tmp_path, prereg)
    ev = copy.deepcopy(fixture_events[0])
    ev["event_id"] = "after-hours-1"
    ev["ts_event"] = ev["ts_event"] + dt.timedelta(hours=3)  # 19:00 ET
    ev["ts_available"] = ev["ts_event"]
    ev["received_at"] = ev["ts_event"] + dt.timedelta(minutes=5)
    engine.process_event(ev)
    assert "MARKET_CLOCK" in _reject_reasons(
        read_entries(state / "journal.jsonl"))


def test_environment_mismatch_rejected(tmp_path, prereg, fixture_events):
    engine, state = _fresh_engine(tmp_path, prereg)
    ev = copy.deepcopy(fixture_events[0])
    ev["environment"] = "PAPER"
    engine.process_event(ev)
    assert "ENV_MISMATCH" in _reject_reasons(
        read_entries(state / "journal.jsonl"))


def test_out_of_order_held_not_consumed(tmp_path, prereg, fixture_events):
    engine, state = _fresh_engine(tmp_path, prereg)
    outcomes = _drive(engine, fixture_events[:8])
    frontier_event = fixture_events[7]
    late = copy.deepcopy(fixture_events[5])
    late["event_id"] = "late-backfill-1"
    outcome = engine.process_event(late)
    assert outcome.kind == "HELD"
    assert outcome.reason == "OUT_OF_ORDER"
    assert outcome.details.get("late_backfill") is True
    # frontier unchanged: the late event is not a rule input
    assert engine.frontier_ts == frontier_event["ts_event"]


def test_future_stamp_beyond_horizon_held(tmp_path, prereg, fixture_events):
    engine, state = _fresh_engine(tmp_path, prereg)
    _drive(engine, fixture_events[:6])
    far = copy.deepcopy(fixture_events[6])
    far["event_id"] = "future-1"
    far["ts_event"] = far["ts_event"] + dt.timedelta(days=365 * 5)
    far["ts_available"] = far["ts_event"]
    far["received_at"] = far["ts_event"] + dt.timedelta(minutes=5)
    outcome = engine.process_event(far)
    assert outcome.kind == "HELD"
    assert outcome.reason == "FUTURE_STAMP"
    # engine remains usable for well-ordered events
    ok = engine.process_event(fixture_events[6])
    assert ok.kind in {"LOCKED", "OBSERVED_SCORED"}


def test_empty_and_corrupt_payloads_rejected(tmp_path, prereg):
    engine, state = _fresh_engine(tmp_path, prereg)
    engine.process_event({})
    engine.process_event({"event_id": "x", "close": "not-a-decimal"})
    reasons = _reject_reasons(read_entries(state / "journal.jsonl"))
    assert reasons.count("MALFORMED") == 2


def test_unadmitted_symbol_rejected(tmp_path, prereg, fixture_events):
    engine, state = _fresh_engine(tmp_path, prereg)
    ev = copy.deepcopy(fixture_events[0])
    ev["symbol"] = "OTHER-SYM"
    engine.process_event(ev)
    assert "SYMBOL_NOT_ADMITTED" in _reject_reasons(
        read_entries(state / "journal.jsonl"))


def test_ttl_expiry_of_open_slot(tmp_path, prereg, fixture_events):
    """An open slot that keeps not receiving an eligible observation
    expires at the preregistered TTL (audit recorded, denominator
    counted)."""
    engine, state = _fresh_engine(tmp_path, prereg)
    _drive(engine, fixture_events[:8])   # slots open normally
    # force out-of-order arrivals so no observation can be consumed
    stalled = copy.deepcopy(fixture_events[5])
    for i in range(4):
        dup_ts = copy.deepcopy(stalled)
        dup_ts["event_id"] = f"stall-{i}"
        dup_ts["ts_event"] = dup_ts["ts_event"] - dt.timedelta(days=7)
        dup_ts["ts_available"] = dup_ts["ts_event"]
        dup_ts["received_at"] = dup_ts["ts_event"] + dt.timedelta(minutes=5)
        engine.process_event(dup_ts)
    entries = read_entries(state / "journal.jsonl")
    expired = _kind_seq(entries, "EXPIRED")
    assert expired, "open slot was not expired at TTL"
    assert any(e["payload"]["reason"] == "TTL_EVENTS" for e in expired)


def test_vendor_capability_claim_cannot_bypass_admission(
        tmp_path, prereg, fixture_events):
    """U-1 stays UNRESOLVED: an event presenting VendorFacts-style
    capability claims from a non-admitted source is refused; no shadow
    admission path upgrades research data access."""
    engine, state = _fresh_engine(tmp_path, prereg)
    ev = copy.deepcopy(fixture_events[0])
    ev["source"] = "vendor-x"
    ev["pit_capability"] = "event_level"
    ev["license_scope"] = "full-market-history"
    engine.process_event(ev)
    assert "SOURCE_NOT_ADMITTED" in _reject_reasons(
        read_entries(state / "journal.jsonl"))
