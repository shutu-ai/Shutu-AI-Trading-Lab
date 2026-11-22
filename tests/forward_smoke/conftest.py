"""Shared fixtures for the M3.5 forward smoke tests (SYNTHETIC_REPLAY)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from apps.trading_daemon.fixture import (  # noqa: E402
    FIXTURE_DATASET_HASH, build_fixture_events, fixture_dataset_hash)
from apps.trading_daemon.prereg import Preregistration  # noqa: E402

PREREG_PATH = REPO_ROOT / "configs" / "forward_observation.yaml"


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def prereg() -> Preregistration:
    """The REAL frozen preregistration from configs/."""
    return Preregistration.load(PREREG_PATH)


@pytest.fixture()
def fixture_events():
    return build_fixture_events()


@pytest.fixture()
def fixture_hash() -> str:
    return FIXTURE_DATASET_HASH


def write_variant_prereg(tmp_path: Path, overrides: dict) -> Path:
    """A preregistration variant with top-level section overrides — used
    only to prove the loader REFUSES out-of-scope configurations."""
    payload = yaml.safe_load(PREREG_PATH.read_text(encoding="utf-8"))
    payload.update(overrides)
    p = tmp_path / "forward_observation_variant.yaml"
    p.write_text(yaml.safe_dump(payload, sort_keys=True), encoding="utf-8")
    return p


def variant_hash_mismatch_prereg(tmp_path: Path) -> Path:
    payload = yaml.safe_load(PREREG_PATH.read_text(encoding="utf-8"))
    payload["admitted_datasets"][0]["dataset_hash"] = "0" * 64
    p = tmp_path / "forward_observation_badhash.yaml"
    p.write_text(yaml.safe_dump(payload, sort_keys=True), encoding="utf-8")
    return p
