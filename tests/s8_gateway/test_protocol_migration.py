"""Protocol migration discipline (T3): the legacy contract is pinned,
the ranged contract is the only production path, and the frozen files
never move."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from apps.market_gateway.prereg_real import (  # noqa: E402
    PreregistrationReal,
    PreregistrationRealRefused,
)

REPO = Path(__file__).resolve().parents[2]
SYNTHETIC_PATH = REPO / "configs" / "forward_observation.yaml"
LEGACY_PATH = REPO / "configs" / "forward_observation_s8_real.yaml"
RANGED_PATH = REPO / "configs" / "forward_observation_s8_real_v2.yaml"

# byte-freeze pins (recorded in artifacts/evidence/M3.5/s8-contract-r1/
# baseline.md at remediation start; a change to either file is a NEW
# protocol version, never an in-place edit). Pins are computed over
# LF-NORMALIZED content — the same platform-independent discipline as
# the code-identity scheme — because raw working-copy bytes are
# checkout-dependent (git translates LF->CRLF on Windows checkouts,
# which first surfaced as CI run 45018794107 failing these two pins on
# windows-latest while ubuntu-latest passed).
SYNTHETIC_SHA256 = \
    "ad287c600e2be1223aaf0f4b70f6f811eedb145f0ccabe900c1b818b9d622a01"
LEGACY_SHA256 = \
    "c1a65ffb926169504aeae755452f0490bf79490d2508a228a4e9aa58bcfcf54e"


def _sha256(path: Path) -> str:
    """SHA-256 over LF-normalized UTF-8 text (BOM stripped) — invariant
    across LF and CRLF checkouts, so the pin freezes LOGICAL content,
    not a platform's line endings."""
    text = path.read_bytes().decode("utf-8")
    if text.startswith("﻿"):
        text = text[1:]
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def test_frozen_synthetic_preregistration_is_byte_identical():
    assert _sha256(SYNTHETIC_PATH) == SYNTHETIC_SHA256


def test_frozen_legacy_real_preregistration_is_byte_identical():
    assert _sha256(LEGACY_PATH) == LEGACY_SHA256


def test_legacy_contract_is_flagged_and_pinned():
    prereg = PreregistrationReal.load(LEGACY_PATH)
    assert prereg.contract_legacy is True
    assert prereg.data_contract == {}
    assert prereg.forward_protocol_id == "m35-s8-real-shadow-readonly-v1"


def test_ranged_contract_is_the_production_path():
    prereg = PreregistrationReal.load(RANGED_PATH)
    assert prereg.contract_legacy is False
    contract = prereg.data_contract
    assert contract["bars_endpoint"] == "ranged_daily_bars"
    assert contract["timeframe"] == "1Day"
    assert contract["adjustment"] == "raw"
    assert contract["window_bounds"] == "session_midnight_et_to_received_at"
    assert prereg.bars_limit == 10000
    assert prereg.page_cap == 5
    assert prereg.forward_protocol_id == "m35-s8-real-shadow-readonly-v2"
    # a NEW protocol hash — distinct from the pinned legacy protocol
    legacy = PreregistrationReal.load(LEGACY_PATH)
    assert prereg.hash != legacy.hash


def test_v3_without_data_contract_is_refused(tmp_path):
    payload = yaml.safe_load(RANGED_PATH.read_text(encoding="utf-8"))
    del payload["data_contract"]
    p = tmp_path / "no_contract.yaml"
    p.write_text(yaml.safe_dump(payload, sort_keys=True), encoding="utf-8")
    with pytest.raises(PreregistrationRealRefused):
        PreregistrationReal.load(p)


def test_v3_with_latest_bar_endpoint_is_refused(tmp_path):
    """The minute-bar endpoint can never re-enter production through a
    v3 preregistration — not as the endpoint, not via a stray path."""
    payload = yaml.safe_load(RANGED_PATH.read_text(encoding="utf-8"))
    payload["data_contract"]["bars_endpoint"] = "latest_minute_bar"
    p = tmp_path / "latest_contract.yaml"
    p.write_text(yaml.safe_dump(payload, sort_keys=True), encoding="utf-8")
    with pytest.raises(PreregistrationRealRefused):
        PreregistrationReal.load(p)


def test_v3_paths_must_admit_the_ranged_endpoint(tmp_path):
    payload = yaml.safe_load(RANGED_PATH.read_text(encoding="utf-8"))
    payload["collection"]["transport"]["allowed_paths"] = [
        "^/v2/stocks/[A-Z]{1,5}/bars/latest$"]
    p = tmp_path / "latest_paths.yaml"
    p.write_text(yaml.safe_dump(payload, sort_keys=True), encoding="utf-8")
    with pytest.raises(PreregistrationRealRefused):
        PreregistrationReal.load(p)


@pytest.mark.parametrize("field,value", [
    ("timeframe", "1Min"),
    ("adjustment", "split"),
    ("window_bounds", "unbounded_history"),
    ("limit", 10001),
    ("page_cap", 0),
])
def test_v3_data_contract_hard_constraints(field, value, tmp_path):
    payload = yaml.safe_load(RANGED_PATH.read_text(encoding="utf-8"))
    payload["data_contract"][field] = value
    p = tmp_path / "drift.yaml"
    p.write_text(yaml.safe_dump(payload, sort_keys=True), encoding="utf-8")
    with pytest.raises(PreregistrationRealRefused):
        PreregistrationReal.load(p)
