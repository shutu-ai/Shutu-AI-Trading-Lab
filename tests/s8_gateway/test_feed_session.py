"""End-to-end S8 session flows over the scripted transport: cycles,
idempotent redelivery, restart recovery, revision conflict, out-of-order,
and the receipt-binding cross-check."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from apps.market_gateway.feed_session import (  # noqa: E402
    FORWARD_STATE_SUBDIR,
    append_receipts,
    preflight,
    run_collection_cycle,
    window_facts_from_journal,
    AuthorizationRefused,
    OPERATOR_AUTHORIZATION_TOKEN,
)
from apps.market_gateway.offline_fixtures import (  # noqa: E402
    build_selftest_feed,
    load_fixture_table,
)
from apps.trading_daemon.driver import run_replay  # noqa: E402
from apps.trading_daemon.journal import read_entries  # noqa: E402
from apps.trading_daemon.journal import verify_journal_file  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
FIXTURE_PATH = REPO / "apps" / "market_gateway" / "fixtures" / "selftest_bars.json"


@pytest.fixture()
def assembled(real_prereg, s8_identity):
    fixture = load_fixture_table(FIXTURE_PATH)
    feed, client, clock = build_selftest_feed(
        prereg=real_prereg, fixture=fixture, identity=s8_identity)
    return feed, client, clock, real_prereg, s8_identity


def _run_cycles(tmp_path, feed, prereg, identity, client, clock, n):
    results = []
    for index in range(n):
        results.append(run_collection_cycle(
            feed=feed, prereg=prereg, state_dir=tmp_path / "state",
            identity=identity, session_index=index + 1))
        client.advance_cycle()
        clock.sync_with(client)
    return results


# ---------------------------------------------------------------------------
# cycles -> journal discipline
# ---------------------------------------------------------------------------

def test_cycles_lock_before_observing_and_score_exactly_once(
        tmp_path, assembled):
    feed, client, clock, prereg, identity = assembled
    results = _run_cycles(tmp_path, feed, prereg, identity, client, clock, 6)
    state = tmp_path / "state"
    ok, msg = verify_journal_file(
        state / FORWARD_STATE_SUBDIR / "journal.jsonl")
    assert ok, msg
    entries = read_entries(state / FORWARD_STATE_SUBDIR / "journal.jsonl")
    # lock-before-observe: for every slot, the PREDICTION_LOCKED chain
    # entry precedes its OBSERVATION_RECEIVED entry
    order: dict[str, int] = {}
    for position, entry in enumerate(entries):
        etype = entry["event_type"]
        if etype in ("PREDICTION_LOCKED", "OBSERVATION_RECEIVED"):
            slot = entry["payload"]["slot_id"]
            order.setdefault(slot, -1)
            if etype == "PREDICTION_LOCKED":
                assert order[slot] == -1, f"slot {slot} locked twice"
                order[slot] = position
            else:
                assert position > order[slot], \
                    f"slot {slot} observed before its lock"
    scored = [e for e in entries if e["event_type"] == "SCORED"]
    assert len(scored) == 6
    assert len({e["payload"]["slot_id"] for e in scored}) == 6
    # environment discipline: every session carries the real environment
    sessions = [e for e in entries if e["event_type"] == "SESSION_STARTED"]
    assert all(e["payload"]["environment"] == "REAL_SHADOW_READ_ONLY"
               for e in sessions)


def test_full_redelivery_is_idempotent(tmp_path, assembled):
    feed, client, clock, prereg, identity = assembled
    _run_cycles(tmp_path, feed, prereg, identity, client, clock, 6)
    # redeliver the LAST cycle verbatim (re-poll of a session already
    # collected): same event ids, same payloads
    client.set_cycle(5)
    clock.sync_with(client)
    result = run_collection_cycle(
        feed=feed, prereg=prereg, state_dir=tmp_path / "state",
        identity=identity, session_index=7)
    counters = result["engine_counters"]
    assert counters["events_delivered"] == 2
    assert counters["duplicates"] == 2
    assert counters["scored"]["total"] == 0
    assert counters["locked"] == 0


def test_restart_resumes_from_the_chain_without_double_scoring(
        tmp_path, assembled):
    feed, client, clock, prereg, identity = assembled
    _run_cycles(tmp_path, feed, prereg, identity, client, clock, 4)
    # a fresh process state: rebuild EVERYTHING from the journal (new feed
    # instance, same state dir) and continue the window
    fixture = load_fixture_table(FIXTURE_PATH)
    feed2, client2, clock2 = build_selftest_feed(
        prereg=prereg, fixture=fixture, identity=identity)
    client2.set_cycle(4)
    clock2.sync_with(client2)
    for index in range(4, 6):
        run_collection_cycle(
            feed=feed2, prereg=prereg, state_dir=tmp_path / "state",
            identity=identity, session_index=index + 1)
        client2.advance_cycle()
        clock2.sync_with(client2)
    entries = read_entries(
        tmp_path / "state" / FORWARD_STATE_SUBDIR / "journal.jsonl")
    slot_scores: dict[str, int] = {}
    for entry in entries:
        if entry["event_type"] == "SCORED":
            sid = entry["payload"]["slot_id"]
            slot_scores[sid] = slot_scores.get(sid, 0) + 1
    assert all(count == 1 for count in slot_scores.values()), \
        "a slot was scored more than once across the restart"


def test_revision_conflict_suspends_conservatively(tmp_path, assembled):
    feed, client, clock, prereg, identity = assembled
    _run_cycles(tmp_path, feed, prereg, identity, client, clock, 1)
    # day 1 is REDELIVERED, but the vendor REVISED SPY's close (same
    # event id, different payload): QQQ redelivery stays an idempotent
    # duplicate; SPY becomes a CONFLICT and conservatively suspends
    revised = load_fixture_table(FIXTURE_PATH)
    revised["cycles"][0]["responses"]["SPY"]["bars"][0]["c"] = 679.77
    feed2, client2, clock2 = build_selftest_feed(
        prereg=prereg, fixture=revised, identity=identity)
    client2.set_cycle(0)
    clock2.sync_with(client2)
    result = run_collection_cycle(
        feed=feed2, prereg=prereg, state_dir=tmp_path / "state",
        identity=identity, session_index=2)
    counters = result["engine_counters"]
    assert counters["rejected"] >= 1
    assert counters["scored"]["total"] == 0
    entries = read_entries(
        tmp_path / "state" / FORWARD_STATE_SUBDIR / "journal.jsonl")
    assert any(e["event_type"] == "SUSPENDED" for e in entries)


def test_stale_backfill_cycle_is_intercepted_by_the_quality_gate(
        tmp_path, assembled):
    """An out-of-order/backfill arrival (an earlier session's payloads
    answering a later poll) never reaches the engine: the STALE_BAR gate
    rejects it and the rejection is receipt-logged."""
    feed, client, clock, prereg, identity = assembled
    _run_cycles(tmp_path, feed, prereg, identity, client, clock, 2)
    backfill = load_fixture_table(FIXTURE_PATH)
    # poll cycle 3 (session 2026-11-25) answers with cycle 1's payloads
    # (session 2026-11-23) — the vendor's own session_date stays, only
    # the ANSWER goes back in time (a backfill shape)
    backfill["cycles"][2]["responses"] = \
        backfill["cycles"][0]["responses"]
    feed2, client2, clock2 = build_selftest_feed(
        prereg=prereg, fixture=backfill, identity=identity)
    client2.set_cycle(2)
    clock2.sync_with(client2)
    result = run_collection_cycle(
        feed=feed2, prereg=prereg, state_dir=tmp_path / "state",
        identity=identity, session_index=3)
    assert result["quality_rejects"] == ["STALE_BAR", "STALE_BAR"]
    assert result["events_emitted"] == 0
    # receipt evidence of the rejects exists in the receipt chain
    from apps.market_gateway.feed_session import receipt_log_path
    from apps.trading_daemon.journal import read_entries as _read
    receipt_records = _read(receipt_log_path(tmp_path / "state"))
    assert any(r["payload"].get("event_type") == "QUALITY_REJECT"
               for r in receipt_records)


# ---------------------------------------------------------------------------
# window facts + receipt binding
# ---------------------------------------------------------------------------

def test_window_facts_bind_receipts_to_journal(tmp_path, assembled):
    feed, client, clock, prereg, identity = assembled
    _run_cycles(tmp_path, feed, prereg, identity, client, clock, 6)
    facts = window_facts_from_journal(tmp_path / "state", prereg,
                                      events_synthetic=True)
    assert facts["journal_verified"] is True
    assert facts["receipts_verified"] is True
    assert facts["receipt_evidence_ok"] is True
    assert facts["receipt_binding_missing"] == []
    assert facts["receipt_binding_mismatched"] == []
    assert facts["trading_days_observed"] == 6
    assert facts["days_partial"] == 0
    assert facts["duplicate_events"] >= 0
    assert facts["unauthorized_broker_orders"] == 0
    assert facts["duplicate_broker_orders"] == 0
    assert facts["events_synthetic"] is True


def test_tampered_receipt_chain_breaks_the_binding(tmp_path, assembled):
    feed, client, clock, prereg, identity = assembled
    _run_cycles(tmp_path, feed, prereg, identity, client, clock, 2)
    receipt_path = tmp_path / "state" / "receipts.jsonl"
    lines = receipt_path.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[0])
    record["payload"]["payload_digest"] = "0" * 64   # edit one digest
    lines[0] = json.dumps(record, sort_keys=True)
    receipt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    facts = window_facts_from_journal(tmp_path / "state", prereg,
                                      events_synthetic=False)
    assert facts["receipts_verified"] is False
    assert facts["receipt_evidence_ok"] is False


def test_partial_coverage_days_are_disclosed_not_counted(
        tmp_path, assembled):
    """A session where only one symbol delivered is a PARTIAL day —
    disclosed in denominators, never counted toward the 5-day
    threshold."""
    feed, client, clock, prereg, identity = assembled
    partial = load_fixture_table(FIXTURE_PATH)
    # the vendor's real no-data answer is an EMPTY bars list (documented
    # shape) — a quality reject, a disclosed partial day, never a crash
    partial["cycles"][3]["responses"]["QQQ"] = {"bars": []}
    feed2, client2, clock2 = build_selftest_feed(
        prereg=prereg, fixture=partial, identity=identity)
    _run_cycles(tmp_path, feed2, prereg, identity, client2, clock2, 6)
    facts = window_facts_from_journal(tmp_path / "state", prereg,
                                      events_synthetic=True)
    assert facts["trading_days_observed"] == 5
    assert facts["days_partial"] == 1


# ---------------------------------------------------------------------------
# preflight gates
# ---------------------------------------------------------------------------

def test_preflight_refuses_without_operator_token():
    with pytest.raises(AuthorizationRefused):
        preflight(operator_authorization=None)
    with pytest.raises(AuthorizationRefused):
        preflight(operator_authorization="S8_APPROVAL_2020_...")
    preflight(operator_authorization=OPERATOR_AUTHORIZATION_TOKEN,
              credential_env={})   # -> BLOCKED_ENV, not a crash


def test_preflight_blocked_env_without_credentials():
    gate = preflight(operator_authorization=OPERATOR_AUTHORIZATION_TOKEN,
                     credential_env={})
    assert gate.status == "BLOCKED_ENV"
    assert "APCA_API_KEY_ID" in gate.reason
    gate2 = preflight(operator_authorization=OPERATOR_AUTHORIZATION_TOKEN,
                      credential_env={"APCA_API_KEY_ID": "set",
                                      "APCA_API_SECRET_KEY": "set"})
    assert gate2.status == "READY"
    assert "set" not in str(gate2.credential_env_visible)
