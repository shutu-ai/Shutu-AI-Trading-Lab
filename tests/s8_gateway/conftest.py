"""Shared fixtures for the S8 gateway tests (read-only real shadow)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from apps.market_gateway.prereg_real import PreregistrationReal  # noqa: E402
from apps.trading_daemon.identity import build_s8_forward_identity  # noqa: E402

PREREG_PATH = REPO_ROOT / "configs" / "forward_observation_s8_real.yaml"
FIXTURE_PATH = REPO_ROOT / "apps" / "market_gateway" / "fixtures" / \
    "selftest_bars.json"

REPO_ROOT_EXPORT = REPO_ROOT


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def real_prereg() -> PreregistrationReal:
    """The REAL frozen v2 preregistration from configs/."""
    return PreregistrationReal.load(PREREG_PATH)


@pytest.fixture(scope="session")
def s8_identity():
    return build_s8_forward_identity(REPO_ROOT)


def write_variant_prereg(tmp_path: Path, overrides: dict) -> Path:
    """A v2 variant with top-level overrides — used ONLY to prove the
    loader REFUSES out-of-scope configurations."""
    import yaml
    payload = yaml.safe_load(PREREG_PATH.read_text(encoding="utf-8"))
    payload.update(overrides)
    p = tmp_path / "forward_observation_s8_variant.yaml"
    p.write_text(yaml.safe_dump(payload, sort_keys=True), encoding="utf-8")
    return p
