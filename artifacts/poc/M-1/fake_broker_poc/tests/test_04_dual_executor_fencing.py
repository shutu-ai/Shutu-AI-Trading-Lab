"""Scenario 4 — dual-executor conflict: fencing epochs are monotonic, expired
leases cannot write, stale epochs are refused by the broker gateway, and
takeover after a frozen executor produces zero double-writes."""
import pytest
from conftest import ACCOUNT, PAPER, make_intent

from fake_broker import (DurableJournal, FakeBroker, LeaseStore,
                         MinimalOMS)
from fake_broker.fake_broker import FenceRejectedError
from fake_broker.fencing import FencingToken


def _setup(tmp_path, clock):
    journal = DurableJournal(tmp_path / "journal.sqlite3")
    leases = LeaseStore(tmp_path / "leases.sqlite3", lease_seconds=60.0, clock=clock)
    broker = FakeBroker(PAPER, ACCOUNT, tmp_path / "broker.json", clock=lambda: "2026-01-02T15:00:00Z")
    return journal, leases, broker, MinimalOMS(PAPER, ACCOUNT, journal)


def test_stale_epoch_write_refused_by_gateway(tmp_path, clock):
    journal, leases, broker, oms = _setup(tmp_path, clock)
    token_a = leases.acquire(PAPER.value, ACCOUNT, "executor-A")
    broker.valid_fences = {token_a.epoch}

    # executor B takes over → epoch advances, A's token is stale
    token_b = leases.acquire(PAPER.value, ACCOUNT, "executor-B")
    assert token_b.epoch == token_a.epoch + 1
    broker.valid_fences = {token_b.epoch}

    with pytest.raises(FenceRejectedError):
        oms.submit(make_intent("i-fence-a"), token_a, broker)  # A tries with stale epoch
    assert broker.submission_count() == 0, "stale executor must not create orders"

    # B's write with the current epoch succeeds
    final = oms.submit(make_intent("i-fence-b"), token_b, broker)
    assert final == "FILLED"
    assert broker.submission_count() == 1


def test_expired_lease_invalidates_token(tmp_path, clock):
    journal, leases, broker, oms = _setup(tmp_path, clock)
    token_a = leases.acquire(PAPER.value, ACCOUNT, "executor-A")
    broker.valid_fences = {token_a.epoch}

    assert leases.validate(token_a) is True
    clock.advance(61)  # lease_seconds=60 → expired
    assert leases.validate(token_a) is False

    # gateway also refuses expired-epoch writes once B holds a newer epoch
    token_b = leases.acquire(PAPER.value, ACCOUNT, "executor-B")
    broker.valid_fences = {token_b.epoch}
    with pytest.raises(FenceRejectedError):
        oms.submit(make_intent("i-fence-exp"), token_a, broker)
    assert broker.submission_count() == 0


def test_takeover_after_frozen_executor_zero_double_writes(tmp_path, clock):
    """B submitted an order then froze (lease expired). A takes over with a new
    epoch, reconciles, completes. Broker ends with exactly one submission per
    intent and only epoch-2/3 writes succeed afterwards."""
    journal, leases, broker, oms = _setup(tmp_path, clock)
    token_b = leases.acquire(PAPER.value, ACCOUNT, "executor-B")
    broker.valid_fences = {token_b.epoch}

    # B submits successfully then 'freezes' (simulated: never releases)
    intent = make_intent("i-takeover-1")
    assert oms.submit(intent, token_b, broker) == "FILLED"
    assert broker.submission_count() == 1

    # lease window passes; B is presumed dead; A acquires the new epoch
    clock.advance(120)
    token_a = leases.acquire(PAPER.value, ACCOUNT, "executor-A")
    assert token_a.epoch == token_b.epoch + 1
    broker.valid_fences = {token_a.epoch}

    # frozen B wakes up and tries to submit with its stale token → refused by
    # the gateway BEFORE reaching the broker → intent safely parked CANCELED
    with pytest.raises(FenceRejectedError):
        oms.submit(make_intent("i-takeover-2"), token_b, broker)
    assert broker.submission_count() == 1  # no write got through from B
    assert journal.get_intent_state("i-takeover-2") == "CANCELED"

    # A reconciles: i-takeover-1 is already terminal locally (FILLED adopted at
    # submit time), i-takeover-2 was never at the broker — nothing open remains
    oms_a = MinimalOMS(PAPER, ACCOUNT, journal)
    report = oms_a.recover(token_a, broker)
    assert report["recovered"] == 0
    assert broker.submission_count() == 1  # STILL exactly one for the intent

    # A is now the only writer: new orders go through under epoch 3
    assert oms_a.submit(make_intent("i-takeover-3"), token_a, broker) == "FILLED"
    assert broker.submission_count() == 2


def test_epoch_strictly_monotonic_owner_binding(tmp_path, clock):
    journal, leases, broker, oms = _setup(tmp_path, clock)
    epochs = [leases.acquire(PAPER.value, ACCOUNT, f"exec-{i}").epoch for i in range(5)]
    assert epochs == sorted(epochs) and len(set(epochs)) == 5
    assert epochs == [0, 1, 2, 3, 4]

    latest = leases.acquire(PAPER.value, ACCOUNT, "exec-current")  # epoch 5
    assert leases.validate(latest) is True

    # forged token: same epoch as current, wrong owner → invalid
    forged = FencingToken(PAPER.value, ACCOUNT, "exec-imposter", latest.epoch,
                          latest.lease_expires_at)
    assert leases.validate(forged) is False

    # stale epoch from a previous holder → invalid
    stale = FencingToken(PAPER.value, ACCOUNT, "exec-3", epochs[3], latest.lease_expires_at)
    assert leases.validate(stale) is False
