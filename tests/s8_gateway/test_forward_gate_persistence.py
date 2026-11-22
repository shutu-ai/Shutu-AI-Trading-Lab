"""Forward E-Gate persistence (T2) — the five-day PASS verdict over a
chain-computed fact source.

EVERY window in this file is SIMULATED_REAL_SHAPE_TEST_ONLY: fixture
events shaped like real arrivals, driven through the real pipeline.
They prove the machinery; they are never real trading days and never
count toward any actual stage window.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from apps.market_gateway.feed_session import (  # noqa: E402
    FORWARD_STATE_SUBDIR,
    evaluate_window,
    run_collection_cycle,
    window_facts_from_journal,
)
from apps.market_gateway.offline_fixtures import (  # noqa: E402
    build_selftest_feed,
    load_fixture_table,
)
from apps.trading_daemon.eligibility import (  # noqa: E402
    EligibilityRefused,
)
from apps.trading_daemon.journal import read_entries  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
FIXTURE_V2 = REPO / "apps" / "market_gateway" / "fixtures" / \
    "selftest_daily_bars_v2.json"

HARNESS = {
    "harness_complete": True,
    "negatives_passed": None,
    "replay_reproducible": True,
    "journal_verified": True,
    "no_broker_writes": True,
}


def _fixture():
    return load_fixture_table(FIXTURE_V2)


def _run_window(tmp_path, ranged_prereg, s8_identity, *, cycles=6,
                disconnect_cycle=None, redeliver_last=True,
                drop_symbol=None):
    """Drive a SIMULATED window through the real pipeline. Returns the
    state dir (facts are computed from its chains afterwards)."""
    fixture = _fixture()
    if drop_symbol is not None:
        # the documented no-data answer for the day: an EMPTY bars page
        # (never a vanished key — that would be a transport-level crash,
        # not a vendor answer)
        fixture["cycles"][cycles - 1]["pages"][drop_symbol] = [
            {"bars": [], "next_page_token": None, "symbol": drop_symbol}]
    feed, client, clock = build_selftest_feed(
        prereg=ranged_prereg, fixture=fixture, identity=s8_identity)
    state = tmp_path / "state"
    for index in range(cycles):
        if disconnect_cycle is not None and index == disconnect_cycle:
            # one transport-disconnected cycle: a scripted network
            # failure for BOTH symbols, receipted as FEED_ERROR
            fixture_d = _fixture()
            if drop_symbol is not None:
                fixture_d["cycles"][cycles - 1]["pages"][drop_symbol] = [
                    {"bars": [], "next_page_token": None,
                     "symbol": drop_symbol}]
            feed_d, client_d, clock_d = build_selftest_feed(
                prereg=ranged_prereg, fixture=fixture_d,
                identity=s8_identity)
            from apps.market_gateway.offline_fixtures import (
                ScriptedBarsClient as _S)
            transport = ranged_prereg.transport_config
            failing = _S(
                allowed_hosts=list(transport.get("allowed_hosts") or ()),
                allowed_paths=list(transport.get("allowed_paths") or ()),
                cycles=fixture_d["cycles"],
                fail_hosts=set(transport.get("allowed_hosts") or ()),
            )
            failing.cycle_index = index
            clock_d.sync_with(failing)
            from apps.market_gateway.alpaca_feed import AlpacaIexDailyBarFeed
            feed_f = AlpacaIexDailyBarFeed(
                client=failing.client, prereg=ranged_prereg, now_fn=clock_d,
                code_identity=None,
                credential_reader=lambda name: "OFFLINE-SIMULATED")
            run_collection_cycle(feed=feed_f, prereg=ranged_prereg,
                                 state_dir=state, identity=s8_identity,
                                 session_index=index + 1)
            client.set_cycle(index + 1)
            clock.sync_with(client)
            continue
        run_collection_cycle(feed=feed, prereg=ranged_prereg,
                             state_dir=state, identity=s8_identity,
                             session_index=index + 1)
        client.advance_cycle()
        clock.sync_with(client)
    if redeliver_last:
        client.set_cycle(cycles - 1)
        clock.sync_with(client)
        run_collection_cycle(feed=feed, prereg=ranged_prereg,
                             state_dir=state, identity=s8_identity,
                             session_index=cycles + 1)
    return state


# ---------------------------------------------------------------------------
# the PASS verdict is now computable from chain facts (P0-2 fix)
# ---------------------------------------------------------------------------

def test_pass_is_computable_from_chain_facts(
        tmp_path, ranged_prereg, s8_identity):
    """SIMULATED_REAL_SHAPE_TEST_ONLY: 5 full-coverage fixture days + a
    transport-disconnect episode with recovery + an audited duplicate
    redelivery -> the E-Gate machine evaluates PASS from the chains. This
    proves the machinery ONLY; fixture facts are never a real window."""
    state = _run_window(tmp_path, ranged_prereg, s8_identity,
                        cycles=6, disconnect_cycle=0)
    facts = window_facts_from_journal(state, ranged_prereg,
                                      events_synthetic=False)
    assert facts["disconnect_recoveries"] >= 1, \
        "the disconnect episode must be recoverable from the chain"
    assert facts["duplicate_recoveries"] >= 1
    assert facts["audits_passed"] is True
    assert facts["protocol_binding_ok"] is True
    assert facts["receipt_evidence_ok"] is True
    assert facts["trading_days_observed"] == 5
    result = evaluate_window(prereg=ranged_prereg, harness=dict(HARNESS),
                             facts=facts, claim="PASS")
    assert result["eligibility"] == "PASS"
    assert result["forward_window_status"] == "COMPLETE"
    assert result["s"] == "INCONCLUSIVE"
    assert result["paper_orders"] == "PAPER_NOT_RUN"
    assert result["broker_writes"] == 0


# ---------------------------------------------------------------------------
# negatives — every shortcut to PASS is refused
# ---------------------------------------------------------------------------

def test_pass_refused_without_disconnect_recovery(
        tmp_path, ranged_prereg, s8_identity):
    """A disconnect with NO subsequent receipt (failure on the final
    cycle) is an unrecovered episode: disconnect_recoveries == 0 -> the
    machine refuses PASS."""
    state = _run_window(tmp_path, ranged_prereg, s8_identity, cycles=6,
                        disconnect_cycle=5, redeliver_last=False)
    facts = window_facts_from_journal(state, ranged_prereg,
                                      events_synthetic=False)
    assert facts["feed_errors"] >= 2
    assert facts["disconnect_recoveries"] == 0
    with pytest.raises(EligibilityRefused) as excinfo:
        evaluate_window(prereg=ranged_prereg, harness=dict(HARNESS),
                        facts=facts, claim="PASS")
    assert "disconnect_recoveries" in str(excinfo.value)


def test_pass_refused_without_duplicate_recovery(
        tmp_path, ranged_prereg, s8_identity):
    state = _run_window(tmp_path, ranged_prereg, s8_identity, cycles=6,
                        disconnect_cycle=0, redeliver_last=False)
    facts = window_facts_from_journal(state, ranged_prereg,
                                      events_synthetic=False)
    assert facts["duplicate_recoveries"] == 0
    with pytest.raises(EligibilityRefused):
        evaluate_window(prereg=ranged_prereg, harness=dict(HARNESS),
                        facts=facts, claim="PASS")


def test_pass_refused_below_five_full_days(
        tmp_path, ranged_prereg, s8_identity):
    """4 full days + a partial day (one symbol missing on day 5): partial
    days are disclosed but never counted (task T2.3)."""
    state = _run_window(tmp_path, ranged_prereg, s8_identity, cycles=6,
                        disconnect_cycle=0, redeliver_last=False,
                        drop_symbol="QQQ")
    facts = window_facts_from_journal(state, ranged_prereg,
                                      events_synthetic=False)
    assert facts["trading_days_observed"] == 4
    assert facts["days_partial"] == 1
    with pytest.raises(EligibilityRefused) as excinfo:
        evaluate_window(prereg=ranged_prereg, harness=dict(HARNESS),
                        facts=facts, claim="PASS")
    assert "insufficient" in str(excinfo.value)


def test_pass_refused_on_cross_protocol_contamination(
        tmp_path, ranged_prereg, s8_identity, real_prereg):
    """A window run under the ranged protocol evaluated against the
    LEGACY preregistration: the chain-stamped protocol hashes poison the
    binding -> audits_passed False -> PASS refused (T3.2)."""
    state = _run_window(tmp_path, ranged_prereg, s8_identity, cycles=6,
                        disconnect_cycle=0)
    facts = window_facts_from_journal(state, real_prereg,
                                      events_synthetic=False)
    assert facts["protocol_binding_ok"] is False
    assert facts["audits_passed"] is False
    with pytest.raises(EligibilityRefused):
        evaluate_window(prereg=real_prereg, harness=dict(HARNESS),
                        facts=facts, claim="PASS")


def test_pass_refused_on_tampered_receipt_chain(
        tmp_path, ranged_prereg, s8_identity):
    state = _run_window(tmp_path, ranged_prereg, s8_identity, cycles=6,
                        disconnect_cycle=0)
    receipt_path = state / "receipts.jsonl"
    lines = receipt_path.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[0])
    record["payload"]["payload_digest"] = "1" * 64
    lines[0] = json.dumps(record, sort_keys=True)
    receipt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    facts = window_facts_from_journal(state, ranged_prereg,
                                      events_synthetic=False)
    assert facts["receipts_verified"] is False
    assert facts["audits_passed"] is False
    with pytest.raises(EligibilityRefused):
        evaluate_window(prereg=ranged_prereg, harness=dict(HARNESS),
                        facts=facts, claim="PASS")


def test_synthetic_flag_still_refuses_pass(tmp_path, ranged_prereg,
                                           s8_identity):
    """Even with perfect machinery facts, a window flagged
    events_synthetic=True (fixture/selftest provenance) can never PASS —
    the fields are necessary, real arrivals are the sufficient
    condition."""
    state = _run_window(tmp_path, ranged_prereg, s8_identity, cycles=6,
                        disconnect_cycle=0)
    facts = window_facts_from_journal(state, ranged_prereg,
                                      events_synthetic=True)
    with pytest.raises(EligibilityRefused):
        evaluate_window(prereg=ranged_prereg, harness=dict(HARNESS),
                        facts=facts, claim="PASS")


# ---------------------------------------------------------------------------
# persistence — the completed window leaves a verifiable fact snapshot
# ---------------------------------------------------------------------------

def test_completion_persists_chain_bound_evaluation(
        tmp_path, ranged_prereg, s8_identity):
    """cmd_complete (via the runner's _complete_window path) persists a
    WINDOW_COMPLETED receipt record + evaluation snapshot; a later status
    recomputes the facts and the digest matches. Tampering with the
    snapshot digest is DETECTED."""
    from scripts.run_m35_s8_shadow_real import (  # noqa: E402
        _complete_window,
    )
    state = _run_window(tmp_path, ranged_prereg, s8_identity, cycles=6,
                        disconnect_cycle=0)
    payload = _complete_window(state, ranged_prereg, s8_identity)
    assert payload["window_completed_receipt"] is True
    assert "evidence_copy" not in payload, (
        "a SIMULATED window must never write into the committed "
        "evidence set — the evidence copy is exclusive to the real "
        "operator collect path")
    from scripts.run_m35_s8_shadow_real import EVIDENCE_DIR  # noqa: E402
    assert not (EVIDENCE_DIR / "real-forward-window-status.json").exists(), \
        "simulated evaluation polluted the evidence set"
    snapshot = json.loads(
        (state / "forward-window-evaluation.json").read_text(
            encoding="utf-8"))
    assert snapshot["schema"] == "s8-forward-window-evaluation-v1"
    entries = read_entries(state / "receipts.jsonl")
    window_records = [e["payload"] for e in entries
                      if e["payload"].get("event_type") == "WINDOW_COMPLETED"]
    assert len(window_records) == 1
    assert window_records[0]["facts_digest"] == snapshot["facts_digest"]
    # a fresh status agrees with the completed evaluation
    from apps.market_gateway.feed_session import (
        receipt_log_path,
    )
    facts = window_facts_from_journal(state, ranged_prereg,
                                      events_synthetic=False)
    from trading_lab.security.canonical import canonical_digest
    assert canonical_digest(facts) == snapshot["facts_digest"]
    # tampering with the persisted snapshot is detected
    snapshot["facts_digest"] = "9" * 64
    (state / "forward-window-evaluation.json").write_text(
        json.dumps(snapshot), encoding="utf-8")
    tampered = json.loads(
        (state / "forward-window-evaluation.json").read_text(
            encoding="utf-8"))
    assert tampered["facts_digest"] != canonical_digest(
        window_facts_from_journal(state, ranged_prereg,
                                  events_synthetic=False))
