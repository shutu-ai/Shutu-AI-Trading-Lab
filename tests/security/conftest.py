"""Shared fixtures for the security test suite.

Everything here uses mock test keys and fictional accounts — the M0 rule
(architecture §6.5). No real credentials exist anywhere in this suite.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from decimal import Decimal
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from trading_lab.contracts import Environment, LiveRelease  # noqa: E402
from trading_lab.security import (  # noqa: E402
    AuditLog,
    ExpectedBinding,
    LiveReleaseVerifier,
    NonceLedger,
    RevocationLedger,
    TrustedKeyStore,
    generate_test_keypair,
    sign_payload,
)

# ---------------------------------------------------------------- clocks ---

NOW = dt.datetime(2026, 11, 20, 12, 0, 0, tzinfo=dt.timezone.utc)
FRESH = NOW - dt.timedelta(seconds=30)


def fixed_now() -> dt.datetime:
    return NOW


# ------------------------------------------------------------ release ------

ACCOUNT = "MOCK_ACCOUNT_0001"
OWNER_IDENTITY = "OWNER_MOCK"

VALID_RELEASE = {
    "release_id": "rel-mock-0001",
    "environment": Environment.LIVE,
    "account_id": ACCOUNT,
    "strategy_hashes": ("c" * 32,),
    "build_digest": "d" * 32,
    "protocol_hash": "e" * 32,
    "policy_hash": "f" * 32,
    "capital_cap": Decimal("1000.00"),
    "max_order_cap": Decimal("100.00"),
    "valid_from": NOW - dt.timedelta(minutes=1),
    "expires_at": NOW + dt.timedelta(hours=1),
    "approval_identity": OWNER_IDENTITY,
    "nonce": "1" * 32,
    "revocation_epoch": 0,
    "signature_algorithm": "Ed25519",
}


def signed_release(owner_private_pem: bytes, **overrides) -> LiveRelease:
    """Sign the canonical payload (everything except the signature field
    itself — ``signature_algorithm`` is part of the signed content)."""
    payload = {**VALID_RELEASE, **overrides}
    sig = sign_payload(owner_private_pem, payload)
    return LiveRelease.model_validate({**payload, "signature": sig})


def expected_binding(**overrides) -> ExpectedBinding:
    defaults = dict(
        environment=Environment.LIVE,
        account_id=ACCOUNT,
        approval_identity=OWNER_IDENTITY,
        strategy_hashes=frozenset({"c" * 32}),
        build_digest="d" * 32,
        protocol_hash="e" * 32,
        policy_hash="f" * 32,
    )
    defaults.update(overrides)
    return ExpectedBinding(**defaults)


# ------------------------------------------------------------- fixtures ----


@pytest.fixture()
def owner_key():
    return generate_test_keypair()


@pytest.fixture()
def attacker_key():
    return generate_test_keypair()


@pytest.fixture()
def tmp_ledgers(tmp_path):
    """Revocation + nonce ledgers primed with fresh, empty revocation state."""
    rev_path = tmp_path / "revocations.jsonl"
    fresh_path = tmp_path / "freshness.json"
    rev_path.write_text("", encoding="utf-8")
    fresh_path.write_text(json.dumps({"last_checked_at": FRESH.isoformat()}), encoding="utf-8")
    return {
        "revocations": rev_path,
        "freshness": fresh_path,
        "nonces": tmp_path / "nonces.jsonl",
        "root": tmp_path,
    }


@pytest.fixture()
def verifier_factory(owner_key, tmp_ledgers):
    def make(now_fn=fixed_now, max_staleness: int = 300) -> LiveReleaseVerifier:
        return LiveReleaseVerifier(
            trusted_keys=TrustedKeyStore.from_json_file(_trusted_keys_file(tmp_ledgers["root"], owner_key)),
            nonce_ledger=NonceLedger(tmp_ledgers["nonces"]),
            revocation_ledger=RevocationLedger(
                tmp_ledgers["revocations"],
                tmp_ledgers["freshness"],
                max_staleness_seconds=max_staleness,
                now_fn=now_fn,
            ),
            audit=AuditLog(tmp_ledgers["root"] / "audit.jsonl", "TEST"),
            now_fn=now_fn,
        )

    return make


def _trusted_keys_file(root: Path, keypair) -> Path:
    path = root / "trusted.json"
    path.write_text(
        json.dumps([{"key_id": keypair.key_id, "public_pem": keypair.public_pem.decode()}]),
        encoding="utf-8",
    )
    return path
