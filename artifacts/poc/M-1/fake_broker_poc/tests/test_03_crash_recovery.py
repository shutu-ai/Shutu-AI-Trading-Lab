"""Scenario 3 — crash recovery across the two crash windows plus partial
fills, against a broker whose own state survives restarts (file-backed)."""
import pytest
from conftest import ACCOUNT, PAPER, make_intent

from fake_broker import (DurableJournal, FakeBroker, LeaseStore,
                         MinimalOMS)
from fake_broker.oms import CrashBeforeSend, CrashAfterSend


def _fresh_runtime(tmp_path, clock, epoch_owner="executor-r"):
    """A brand-new OMS + lease epoch on the same persistent files (the broker
    store file simulates broker-side persistence across restarts)."""
    journal = DurableJournal(tmp_path / "journal.sqlite3")
    leases = LeaseStore(tmp_path / "leases.sqlite3", lease_seconds=60.0, clock=clock)
    broker = FakeBroker(PAPER, ACCOUNT, tmp_path / "broker.json", clock=lambda: "2026-01-02T15:00:00Z")
    token = leases.acquire(PAPER.value, ACCOUNT, epoch_owner)
    broker.valid_fences = {token.epoch}
    return journal, broker, token, MinimalOMS(PAPER, ACCOUNT, journal)


def test_crash_before_send_recovered_by_single_completion_send(tmp_path, clock):
    # first runtime: crash right after durability commit
    journal, broker, token1, oms1 = _fresh_runtime(tmp_path, clock, "executor-A")
    intent = make_intent("i-crash-1")
    with pytest.raises(CrashBeforeSend):
        oms1.submit(intent, token1, broker, inject="crash_before_send")
    assert broker.submission_count() == 0

    # process restarts: fresh OMS + fresh epoch, SAME journal + broker store
    journal2, broker2, token2, oms2 = _fresh_runtime(tmp_path, clock, "executor-B")
    assert broker2.submission_count() == 0  # broker store reloaded, still empty

    report = oms2.recover(token2, broker2, operator_release_halt=True)
    assert report["actions"][0]["action"] == "COMPLETED_SEND_ONCE"
    assert report["actions"][0]["sent"] is True
    # exactly ONE broker submission across the entire crash+recovery lifecycle
    assert broker2.submission_count() == 1
    assert journal2.get_intent_state(intent.intent_id) == "FILLED"


def test_crash_after_send_recovered_without_resend(tmp_path, clock):
    journal, broker, token1, oms1 = _fresh_runtime(tmp_path, clock, "executor-A")
    intent = make_intent("i-crash-2")

    # inject crash_after_send: broker returns snapshot then we die before persist
    # simulated by monkeypatching adoption to raise
    orig = MinimalOMS._adopt_snapshot
    def boom(self, intent_id, snap):
        raise CrashAfterSend("died before persisting ack")
    MinimalOMS._adopt_snapshot = boom
    try:
        with pytest.raises(CrashAfterSend):
            oms1.submit(intent, token1, broker, inject="crash_after_send")
    finally:
        MinimalOMS._adopt_snapshot = orig

    # broker processed the order; local journal is stale (SUBMITTING)
    assert broker.submission_count() == 1
    assert journal.get_intent_state(intent.intent_id) == "SUBMITTING"

    journal2, broker2, token2, oms2 = _fresh_runtime(tmp_path, clock, "executor-B")
    report = oms2.recover(token2, broker2, operator_release_halt=True)
    act = report["actions"][0]
    assert act["action"] == "ADOPTED_BROKER_STATE"
    assert act["sent"] is False, "order confirmed at broker must never be resent"
    assert broker2.submission_count() == 1  # still exactly one
    assert journal2.get_intent_state(intent.intent_id) == "FILLED"


def test_partial_fill_then_crash_reconciles_and_completes(tmp_path, clock):
    journal, broker, token1, oms1 = _fresh_runtime(tmp_path, clock, "executor-A")
    intent = make_intent("i-crash-3", qty="2")
    broker.schedule_fault(intent.client_order_id, ["partial_then_stall"])

    final = oms1.submit(intent, token1, broker)
    assert final == "PARTIALLY_FILLED"
    assert journal.get_intent_state(intent.intent_id) == "PARTIALLY_FILLED"
    filled_so_far = broker.get_order(intent.client_order_id).filled_qty

    # crash + restart, broker finishes the fills while we were down
    clock.advance(120)
    journal2, broker2, token2, oms2 = _fresh_runtime(tmp_path, clock, "executor-B")
    broker2.deliver_pending_fills()
    report = oms2.recover(token2, broker2, operator_release_halt=False)

    assert report["actions"][0]["action"] == "ADOPTED_BROKER_STATE"
    assert journal2.get_intent_state(intent.intent_id) == "FILLED"
    assert broker2.get_order(intent.client_order_id).filled_qty == __import__("decimal").Decimal("2")
    assert broker2.submission_count() == 1
    # events deduped by broker event id across both adoptions
    ids = journal2.event_ids_for(intent.client_order_id)
    assert len(ids) == len(broker2.get_order(intent.client_order_id).events)


def test_broker_restart_preserves_orders_for_reconciliation(tmp_path, clock):
    """The broker's own persistence is a precondition for meaningful
    reconciliation — prove the fake broker reloads its state."""
    journal, broker, token, oms = _fresh_runtime(tmp_path, clock, "executor-A")
    intent = make_intent("i-crash-4")
    oms.submit(intent, token, broker)
    state_before = broker.get_order(intent.client_order_id)

    # 'broker restart': fresh FakeBroker instance on the same store file
    broker2 = FakeBroker(PAPER, ACCOUNT, tmp_path / "broker.json",
                         clock=lambda: "2026-01-02T15:00:00Z")
    state_after = broker2.get_order(intent.client_order_id)
    assert state_after is not None
    assert state_after.state == state_before.state
    assert state_after.filled_qty == state_before.filled_qty
    assert broker2.submission_count() == broker.submission_count()
