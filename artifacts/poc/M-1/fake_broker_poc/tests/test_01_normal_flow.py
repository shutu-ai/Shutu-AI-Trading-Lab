"""Scenario 1 — normal flow: submit → ACK → FILLED, journal durability,
deterministic client_order_id, duplicate intent rejection."""
from decimal import Decimal

from conftest import ACCOUNT, PAPER, make_intent

from fake_broker import (DurableJournal, Environment, FakeBroker,
                         LeaseStore, MinimalOMS)


def _omss(tmp_path, clock):
    journal = DurableJournal(tmp_path / "journal.sqlite3")
    leases = LeaseStore(tmp_path / "leases.sqlite3", lease_seconds=60.0, clock=clock)
    broker = FakeBroker(PAPER, ACCOUNT, tmp_path / "broker.json", clock=lambda: "2026-01-02T15:00:00Z")
    token = leases.acquire(PAPER.value, ACCOUNT, "executor-A")
    broker.valid_fences = {token.epoch}
    oms = MinimalOMS(PAPER, ACCOUNT, journal)
    return journal, broker, token, oms


def test_happy_path_full_fill(tmp_path, clock):
    journal, broker, token, oms = _omss(tmp_path, clock)
    intent = make_intent("i-happy-1")

    final = oms.submit(intent, token, broker)

    assert final == "FILLED"
    # broker received exactly one submission for this intent
    assert broker.submission_count() == 1
    # local journal adopted the broker truth
    assert journal.get_intent_state(intent.intent_id) == "FILLED"
    snap = broker.get_order(intent.client_order_id)
    assert snap is not None and snap.state.value == "FILLED"
    assert snap.filled_qty == Decimal("1")
    # broker events were journaled with dedupe by broker event id
    local_event_ids = journal.event_ids_for(intent.client_order_id)
    assert local_event_ids == {e.event_id for e in snap.events}
    assert len(local_event_ids) == 2  # ACK + FILLED


def test_durability_pragmas_enforced(tmp_path):
    journal = DurableJournal(tmp_path / "j.sqlite3")
    assert str(journal.conn.execute("PRAGMA journal_mode").fetchone()[0]).lower() == "wal"
    assert int(journal.conn.execute("PRAGMA synchronous").fetchone()[0]) == 2  # FULL


def test_intent_persisted_before_send(tmp_path, clock):
    """crash_before_send: the intent + attempt are already durable — a fresh
    OMS on the same journal sees them (nothing lost)."""
    import pytest
    from fake_broker.oms import CrashBeforeSend

    journal, broker, token, oms = _omss(tmp_path, clock)
    intent = make_intent("i-persist-1")

    with pytest.raises(CrashBeforeSend):
        oms.submit(intent, token, broker, inject="crash_before_send")

    # broker never saw it
    assert broker.submission_count() == 0
    # journal HAS the intent (durability point proven)
    assert journal.get_intent_state(intent.intent_id) == "SUBMITTING"
    assert len(journal.pending_attempts_before_send()) == 1


def test_deterministic_client_order_id_and_duplicate_rejection(tmp_path, clock):
    journal, broker, token, oms = _omss(tmp_path, clock)
    intent = make_intent("i-dup-1")

    first = oms.submit(intent, token, broker)
    second = oms.submit(intent, token, broker)  # same intent replayed

    assert first == "FILLED"
    assert second == "DUPLICATE_INTENT"
    assert broker.submission_count() == 1  # no second broker order
    assert intent.client_order_id.startswith(f"TBL-{PAPER.value}-")
    # determinism: same inputs → same id
    again = make_intent("i-dup-1")
    assert again.client_order_id == intent.client_order_id


def test_negative_qty_rejected_at_intent_validation(tmp_path, clock):
    """The alpaca-py SDK accepts negative qty (see evidence); our contract
    must reject it before any persistence/send."""
    import pytest

    journal, broker, token, oms = _omss(tmp_path, clock)
    bad = make_intent("i-neg-1", qty="-1")
    with pytest.raises(ValueError):
        oms.submit(bad, token, broker)
    assert broker.submission_count() == 0
    assert journal.get_intent_state("i-neg-1") is None  # never even persisted
