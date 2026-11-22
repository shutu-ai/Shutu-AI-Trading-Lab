"""Real preregistration v2 loader — fail-closed scope validation.

The loader accepts ONLY the signed read-only scope; every test here is a
boundary: a configuration that would widen it (paid feed, extra symbols,
trading hosts, write methods, followable redirects, disabled window,
sub-5-day threshold, unattested license...) must be REFUSED at load."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from apps.market_gateway.prereg_real import (  # noqa: E402
    PreregistrationReal,
    PreregistrationRealRefused,
)
from apps.trading_daemon.prereg import (  # noqa: E402
    Preregistration,
    PreregistrationRefused,
)

REPO = Path(__file__).resolve().parents[2]
PREREG_PATH = REPO / "configs" / "forward_observation_s8_real.yaml"


def write_variant_prereg(tmp_path: Path, overrides: dict) -> Path:
    """A v2 variant with top-level overrides — used ONLY to prove the
    loader REFUSES out-of-scope configurations."""
    payload = yaml.safe_load(PREREG_PATH.read_text(encoding="utf-8"))
    payload.update(overrides)
    p = tmp_path / "forward_observation_s8_variant.yaml"
    p.write_text(yaml.safe_dump(payload, sort_keys=True), encoding="utf-8")
    return p


def test_valid_real_preregistration_loads(real_prereg):
    assert real_prereg.forward_protocol_id == "m35-s8-real-shadow-readonly-v1"
    assert real_prereg.environment == "REAL_SHADOW_READ_ONLY"
    assert real_prereg.symbols == ("SPY", "QQQ")
    assert real_prereg.dataset_admission == "receipt_content_hash"
    assert real_prereg.admitted_symbols == ("SPY", "QQQ")
    assert real_prereg.admitted_dataset_hashes == ()
    assert real_prereg.min_trading_days == 5
    assert real_prereg.feed == "iex"
    assert real_prereg.plan == "basic_free"


def test_v2_protocol_hash_differs_from_v1(real_prereg):
    v1 = Preregistration.load(
        Path(__file__).resolve().parents[2] /
        "configs" / "forward_observation.yaml")
    assert real_prereg.hash != v1.hash
    assert v1.dataset_admission == "pinned"
    assert real_prereg.dataset_admission == "receipt_content_hash"


def test_v1_loader_refuses_v2_file():
    with pytest.raises(PreregistrationRefused):
        Preregistration.load(PREREG_PATH)


def _variants():
    return {
        "mode_not_real": {"mode": "SYNTHETIC_REPLAY_ONLY"},
        "schema_not_v2": {"schema": "forward-observation-preregistration-v1"},
        "env_not_real": {"environment_must_equal": "SYNTHETIC_REPLAY"},
        "source_none": {"source_authorization": {
            "real_market_data": "NONE"}},
        "source_sip": {"source_authorization": {
            "real_market_data": "ALPACA_IEX_BASIC_READ_ONLY",
            "provider": "alpaca", "feed": "sip", "plan": "basic_free",
            "broker_credentials": "FORBIDDEN",
            "vendor_capability_claims_accepted": False,
            "admitted_sources": ["alpaca_iex"],
            "license_attestation": {
                "operator_confirmed": True,
                "approval_record": "artifacts/x.md"}}},
        "source_paid_plan": {"source_authorization": {
            "real_market_data": "ALPACA_IEX_BASIC_READ_ONLY",
            "provider": "alpaca", "feed": "iex", "plan": "algo_trader_plus",
            "broker_credentials": "FORBIDDEN",
            "vendor_capability_claims_accepted": False,
            "admitted_sources": ["alpaca_iex"],
            "license_attestation": {
                "operator_confirmed": True,
                "approval_record": "artifacts/x.md"}}},
        "broker_credentials_allowed": {"source_authorization": {
            "real_market_data": "ALPACA_IEX_BASIC_READ_ONLY",
            "provider": "alpaca", "feed": "iex", "plan": "basic_free",
            "broker_credentials": "PAPER_ALLOWED",
            "vendor_capability_claims_accepted": False,
            "admitted_sources": ["alpaca_iex"],
            "license_attestation": {
                "operator_confirmed": True,
                "approval_record": "artifacts/x.md"}}},
        "vendor_claims_accepted": {"source_authorization": {
            "real_market_data": "ALPACA_IEX_BASIC_READ_ONLY",
            "provider": "alpaca", "feed": "iex", "plan": "basic_free",
            "broker_credentials": "FORBIDDEN",
            "vendor_capability_claims_accepted": True,
            "admitted_sources": ["alpaca_iex"],
            "license_attestation": {
                "operator_confirmed": True,
                "approval_record": "artifacts/x.md"}}},
        "license_unattested": {"source_authorization": {
            "real_market_data": "ALPACA_IEX_BASIC_READ_ONLY",
            "provider": "alpaca", "feed": "iex", "plan": "basic_free",
            "broker_credentials": "FORBIDDEN",
            "vendor_capability_claims_accepted": False,
            "admitted_sources": ["alpaca_iex"],
            "license_attestation": {
                "operator_confirmed": False,
                "approval_record": "artifacts/x.md"}}},
    }


@pytest.mark.parametrize("name", sorted(_variants()))
def test_out_of_scope_authorization_refused(tmp_path, name):
    path = write_variant_prereg(tmp_path, _variants()[name])
    with pytest.raises(PreregistrationRealRefused):
        PreregistrationReal.load(path)


def _dataset_variants():
    base = {"symbols": ["SPY", "QQQ"], "interval": "1d",
            "source": "alpaca_iex", "dataset_admission":
                "receipt_content_hash"}
    return {
        "four_symbols": {**base, "symbols": ["SPY", "QQQ", "DIA", "IWM"]},
        "lowercase_symbol": {**base, "symbols": ["spy", "QQQ"]},
        "duplicate_symbols": {**base, "symbols": ["SPY", "SPY"]},
        "wrong_interval": {**base, "interval": "1h"},
        "pinned_hash_forbidden": {**base, "dataset_hash": "a" * 64},
        "pinned_admission": {**base,
                             "dataset_admission": "pinned_hashes"},
    }


@pytest.mark.parametrize("name", sorted(_dataset_variants()))
def test_out_of_scope_dataset_refused(tmp_path, name):
    import yaml
    payload = yaml.safe_load(PREREG_PATH.read_text(encoding="utf-8"))
    payload["admitted_datasets"][0].update(_dataset_variants()[name])
    p = tmp_path / "variant.yaml"
    p.write_text(yaml.safe_dump(payload, sort_keys=True), encoding="utf-8")
    with pytest.raises(PreregistrationRealRefused):
        PreregistrationReal.load(p)


def _window_variants():
    return {
        "window_disabled": {"real_window": {
            "enabled": False, "min_trading_days": 5,
            "paper_orders": "PAPER_NOT_RUN",
            "day_counting_rule": "full_coverage"}},
        "threshold_below_five": {"real_window": {
            "enabled": True, "min_trading_days": 4,
            "paper_orders": "PAPER_NOT_RUN",
            "day_counting_rule": "full_coverage"}},
        "paper_enabled": {"real_window": {
            "enabled": True, "min_trading_days": 5,
            "paper_orders": "LIMITED_TEST",
            "day_counting_rule": "full_coverage"}},
        "partial_day_counting": {"real_window": {
            "enabled": True, "min_trading_days": 5,
            "paper_orders": "PAPER_NOT_RUN",
            "day_counting_rule": "any_symbol"}},
    }


@pytest.mark.parametrize("name", sorted(_window_variants()))
def test_out_of_scope_window_refused(tmp_path, name):
    path = write_variant_prereg(tmp_path, _window_variants()[name])
    with pytest.raises(PreregistrationRealRefused):
        PreregistrationReal.load(path)


def _transport_variants():
    base = {
        "scheme": "https",
        "allowed_hosts": ["data.alpaca.markets"],
        "allowed_paths": ["^/v2/stocks/[A-Z]{1,5}/bars/latest$"],
        "methods": ["GET"],
        "redirects": "forbidden",
        "body": "forbidden",
    }
    return {
        "trading_host_live": {**base,
                              "allowed_hosts": ["api.alpaca.markets"]},
        "trading_host_paper": {**base,
                               "allowed_hosts":
                                   ["paper-api.alpaca.markets"]},
        "both_hosts": {**base, "allowed_hosts": [
            "data.alpaca.markets", "api.alpaca.markets"]},
        "post_allowed": {**base, "methods": ["GET", "POST"]},
        "redirects_follow": {**base, "redirects": "follow"},
        "orders_path": {**base,
                        "allowed_paths": ["^/v2/orders$"]},
        "positions_path": {**base,
                           "allowed_paths":
                               ["^/v2/positions/[A-Z]{1,5}$"]},
        "invalid_regex": {**base,
                          "allowed_paths": ["^/v2/stocks/([A-Z]+/"]},
        "empty_hosts": {**base, "allowed_hosts": []},
    }


@pytest.mark.parametrize("name", sorted(_transport_variants()))
def test_out_of_scope_transport_refused(tmp_path, name):
    import yaml
    payload = yaml.safe_load(PREREG_PATH.read_text(encoding="utf-8"))
    payload["collection"]["transport"] = _transport_variants()[name]
    p = tmp_path / "variant.yaml"
    p.write_text(yaml.safe_dump(payload, sort_keys=True), encoding="utf-8")
    with pytest.raises(PreregistrationRealRefused):
        PreregistrationReal.load(p)


def _calendar_variants():
    return {
        "holiday_outside_coverage": {"holidays": ["2027-02-15"],
                                     "half_days": []},
        "weekend_holiday": {"holidays": ["2026-11-28"], "half_days": []},
        "half_day_and_holiday": {"holidays": ["2026-11-27"],
                                 "half_days": ["2026-11-27"]},
        "inverted_coverage": {"calendar_valid_from": "2027-01-08",
                              "calendar_valid_until": "2026-11-23"},
        "inferred_calendar": {"calendar_source": "INFERRED_FROM_FIXTURE"},
    }


@pytest.mark.parametrize("name", sorted(_calendar_variants()))
def test_out_of_scope_calendar_refused(tmp_path, name):
    import yaml
    payload = yaml.safe_load(PREREG_PATH.read_text(encoding="utf-8"))
    payload["market_clock"].update(_calendar_variants()[name])
    p = tmp_path / "variant.yaml"
    p.write_text(yaml.safe_dump(payload, sort_keys=True), encoding="utf-8")
    with pytest.raises(PreregistrationRealRefused):
        PreregistrationReal.load(p)


def test_declared_calendar_is_frozen_correctly(real_prereg):
    """The operator-declared table matches the NYSE rules cited at the
    freeze date (DOCUMENTED tier — see source-license-and-feed.md)."""
    holidays = {d.isoformat() for d in real_prereg.holidays}
    half_days = {d.isoformat() for d in real_prereg.half_days}
    assert holidays == {"2026-11-26", "2026-12-25", "2027-01-01"}
    assert half_days == {"2026-11-27", "2026-12-24"}
