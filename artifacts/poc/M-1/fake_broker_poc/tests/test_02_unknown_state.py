"""Scenario 2 — unknown state: response lost after broker processed the order.
Recovery must reconcile by client_order_id, adopt broker truth, and never
resend. Unresolvable outcomes freeze new risk (HALT_NEW_RISK)."""
from conftest import ACCOUNT, PAPER, make_intent

from fake_broker import (DurableJournal, FakeBroker, LeaseStore,
                         MinimalOMS, OrderState)


def _setup(tmp_path, clock):
    journal = DurableJournal(tmp_path / "journal.sqlite3")
    leases = LeaseStore(tmp_path / "leases.sqlite3", lease_seconds=60.0, clock=clock)
    broker = FakeBroker(PAPER, ACCOUNT, tmp_path / "broker.json", clock=lambda: "2026-01-02T15:00:00Z")
    token1 = leases.acquire(PAPER.value, ACCOUNT, "executor-A")
    broker.valid_fences = {token1.epoch}
    oms = MinimalOMS(PAPER, ACCOUNT, journal)
    return journal, leases, broker, token1, oms


def test_response_lost_then_reconciled_no_resend(tmp_path, clock):
    journal, leases, broker, token1, oms = _setup(tmp_path, clock)
    intent = make_intent("i-unk-1")
    broker.schedule_fault(intent.client_order_id, ["before_ack_drop"])

    final = oms.submit(intent, token1, broker)
    assert final == "UNKNOWN"
    # broker DID process the order (submission counted) but client is blind
    assert broker.submission_count() == 1
    # new risk is frozen immediately
    assert journal.is_halted(PAPER.value, ACCOUNT)
    # and a new submission is refused while unresolved
    try:
        oms.submit(make_intent("i-unk-2"), token1, broker)
        raised = False
    except Exception:
        raised = True
    assert raised, "HALT_NEW_RISK must refuse new submissions"
    assert broker.submission_count() == 1

    # ---- recovery with a fresh executor + fresh epoch ----
    token2 = leases.acquire(PAPER.value, ACCOUNT, "executor-B")
    broker.valid_fences = {token2.epoch}
    oms2 = MinimalOMS(PAPER, ACCOUNT, journal)
    report = oms2.recover(token2, broker, operator_release_halt=True)

    assert report["recovered"] == 1
    act = report["actions"][0]
    assert act["action"] == "ADOPTED_BROKER_STATE"
    assert act["sent"] is False
    # broker truth adopted: order was processed → state FILLED locally
    assert journal.get_intent_state(intent.intent_id) == "FILLED"
    # CRITICAL: broker still saw exactly ONE submission — no duplicate
    assert broker.submission_count() == 1
    # halt released only by explicit operator action
    assert not journal.is_halted(PAPER.value, ACCOUNT)


def test_conn_refused_is_safe_terminal_no_halt(tmp_path, clock):
    """Conn refused = provably not processed: safe terminal, no risk freeze
    needed, and definitely no blind resend."""
    journal, leases, broker, token, oms = _setup(tmp_path, clock)
    intent = make_intent("i-unk-2")
    broker.schedule_fault(intent.client_order_id, ["conn_refused"])

    final = oms.submit(intent, token, broker)
    assert final == "CANCELED"
    assert broker.submission_count() == 0
    assert not journal.is_halted(PAPER.value, ACCOUNT)
    assert journal.get_intent_state(intent.intent_id) == "CANCELED"
    # retrying the same intent is still a duplicate locally
    assert oms.submit(intent, token, broker) == "DUPLICATE_INTENT"


def test_transient_reject_is_terminal_rejected(tmp_path, clock):
    journal, leases, broker, token, oms = _setup(tmp_path, clock)
    intent = make_intent("i-unk-3")
    broker.schedule_fault(intent.client_order_id, ["transient_5xx"])

    final = oms.submit(intent, token, broker)
    assert final == "REJECTED"
    assert broker.submission_count() == 0  # 503 created no order
    assert not journal.is_halted(PAPER.value, ACCOUNT)


def test_unknown_halts_and_blocks_new_risk_until_operator_release(tmp_path, clock):
    journal, leases, broker, token1, oms = _setup(tmp_path, clock)
    intent = make_intent("i-unk-4")
    broker.schedule_fault(intent.client_order_id, ["before_ack_drop"])

    assert oms.submit(intent, token1, broker) == "UNKNOWN"
    assert journal.is_halted(PAPER.value, ACCOUNT)

    # recovery does NOT release halt unless operator explicitly does
    token2 = leases.acquire(PAPER.value, ACCOUNT, "executor-B")
    broker.valid_fences = {token2.epoch}
    report = MinimalOMS(PAPER, ACCOUNT, journal).recover(token2, broker,
                                                         operator_release_halt=False)
    assert journal.is_halted(PAPER.value, ACCOUNT), "operator release must be required"
