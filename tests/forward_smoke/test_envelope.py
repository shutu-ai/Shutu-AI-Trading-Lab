"""Envelope validation negatives (task S1: reject or suspend, never
silently repair into a good-looking result)."""

from __future__ import annotations

import copy
import datetime as dt
from decimal import Decimal

import pytest

from apps.trading_daemon.envelope import EnvelopeError, ForwardEvent, payload_digest
from apps.trading_daemon.fixture import build_fixture_events


@pytest.fixture()
def valid_payload(fixture_events) -> dict:
    return copy.deepcopy(fixture_events[0])


def test_valid_payload_accepted(valid_payload):
    ev = ForwardEvent.model_validate(valid_payload)
    assert ev.event_id == valid_payload["event_id"]
    assert ev.close == Decimal(str(valid_payload["close"]))
    assert ev.ts_event.tzinfo is not None


def test_naive_timestamps_rejected(valid_payload):
    for field in ("ts_event", "ts_available", "received_at"):
        payload = copy.deepcopy(valid_payload)
        payload[field] = payload[field].replace(tzinfo=None)
        with pytest.raises(EnvelopeError):
            ForwardEvent.model_validate(payload)


def test_available_before_event_rejected(valid_payload):
    payload = copy.deepcopy(valid_payload)
    payload["ts_available"] = payload["ts_event"] - dt.timedelta(minutes=1)
    with pytest.raises(EnvelopeError):
        ForwardEvent.model_validate(payload)


def test_missing_required_field_rejected(valid_payload):
    for field in ("event_id", "source", "dataset_hash", "symbol",
                  "interval", "ts_event", "ts_available", "received_at",
                  "close"):
        payload = copy.deepcopy(valid_payload)
        del payload[field]
        with pytest.raises(EnvelopeError):
            ForwardEvent.model_validate(payload)


def test_bad_dataset_hash_rejected(valid_payload):
    payload = copy.deepcopy(valid_payload)
    payload["dataset_hash"] = "not-a-hash"
    with pytest.raises(EnvelopeError):
        ForwardEvent.model_validate(payload)
    payload["dataset_hash"] = "0" * 63  # wrong length
    with pytest.raises(EnvelopeError):
        ForwardEvent.model_validate(payload)


def test_non_positive_close_rejected(valid_payload):
    for bad in ("0", "-1"):
        payload = copy.deepcopy(valid_payload)
        payload["close"] = bad
        with pytest.raises(EnvelopeError):
            ForwardEvent.model_validate(payload)


def test_empty_identity_fields_rejected(valid_payload):
    for field in ("event_id", "source", "symbol"):
        payload = copy.deepcopy(valid_payload)
        payload[field] = "  "
        with pytest.raises(EnvelopeError):
            ForwardEvent.model_validate(payload)


def test_float_close_rejected_imprecise_decimal(valid_payload):
    payload = copy.deepcopy(valid_payload)
    payload["close"] = 100.5  # float: imprecise decimal chain is banned
    with pytest.raises(EnvelopeError):
        ForwardEvent.model_validate(payload)


def test_string_close_coerced_to_decimal(valid_payload):
    payload = copy.deepcopy(valid_payload)
    payload["close"] = "100.25"
    ev = ForwardEvent.model_validate(payload)
    assert ev.close == Decimal("100.25")


def test_payload_digest_excludes_transport_metadata(valid_payload):
    a = ForwardEvent.model_validate(valid_payload)
    other = copy.deepcopy(valid_payload)
    other["received_at"] = other["received_at"] + dt.timedelta(hours=3)
    b = ForwardEvent.model_validate(other)
    assert payload_digest(a) == payload_digest(b)  # redelivery, same logic

    changed = copy.deepcopy(valid_payload)
    changed["close"] = "101"
    c = ForwardEvent.model_validate(changed)
    assert payload_digest(a) != payload_digest(c)  # different logical payload


def test_malformed_payload_is_rejected_class():
    with pytest.raises(EnvelopeError) as exc:
        ForwardEvent.model_validate({})
    assert exc.value.reason == "MALFORMED"
