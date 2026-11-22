"""Preregistration loader: out-of-scope configurations are refused."""

from __future__ import annotations

import pytest
import yaml

from apps.trading_daemon.fixture import FIXTURE_DATASET_HASH
from apps.trading_daemon.prereg import Preregistration, PreregistrationRefused

from conftest import PREREG_PATH, write_variant_prereg


def test_real_prereg_loads_and_hash_is_stable(prereg):
    again = Preregistration.load(PREREG_PATH)
    assert prereg.hash == again.hash
    assert prereg.payload["mode"] == "SYNTHETIC_REPLAY_ONLY"
    assert prereg.hash  # 64-hex canonical digest
    assert len(prereg.hash) == 64


def test_prereg_payload_is_frozen(prereg):
    with pytest.raises(Exception):
        prereg.payload["mode"] = "PAPER"  # type: ignore[index]


def test_real_data_authorization_refused(tmp_path):
    p = write_variant_prereg(tmp_path, {
        "source_authorization": {
            "real_market_data": "LICENSED_PROVIDER_X",
            "broker_credentials": "FORBIDDEN",
            "vendor_capability_claims_accepted": False,
            "admitted_sources": ["synthetic"],
        }})
    with pytest.raises(PreregistrationRefused):
        Preregistration.load(p)


def test_broker_credentials_allowed_refused(tmp_path):
    p = write_variant_prereg(tmp_path, {
        "source_authorization": {
            "real_market_data": "NONE",
            "broker_credentials": "PAPER_KEY_OK",
            "vendor_capability_claims_accepted": False,
            "admitted_sources": ["synthetic"],
        }})
    with pytest.raises(PreregistrationRefused):
        Preregistration.load(p)


def test_vendor_capability_claims_refused(tmp_path):
    """U-1 stays UNRESOLVED: a preregistration that would admit fabricated
    VendorFacts-style capability claims is refused outright."""
    p = write_variant_prereg(tmp_path, {
        "source_authorization": {
            "real_market_data": "NONE",
            "broker_credentials": "FORBIDDEN",
            "vendor_capability_claims_accepted": True,
            "admitted_sources": ["synthetic"],
        }})
    with pytest.raises(PreregistrationRefused):
        Preregistration.load(p)


def test_non_replay_mode_refused(tmp_path):
    p = write_variant_prereg(tmp_path, {"mode": "SHADOW_REAL_OBSERVED"})
    with pytest.raises(PreregistrationRefused):
        Preregistration.load(p)


def test_real_window_cannot_be_enabled(tmp_path):
    p = write_variant_prereg(tmp_path, {"real_window": {"enabled": True}})
    with pytest.raises(PreregistrationRefused):
        Preregistration.load(p)


def test_admitted_fixture_hash_matches_computed_fixture(prereg):
    admitted = prereg.payload["admitted_datasets"][0]
    assert admitted["dataset_hash"] == FIXTURE_DATASET_HASH
    assert admitted["sessions"] == 30
