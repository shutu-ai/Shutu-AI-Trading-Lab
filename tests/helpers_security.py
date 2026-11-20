"""Shared security-suite helpers (unique module name: avoids pytest
conftest module-name collisions across directories)."""

from __future__ import annotations

import datetime as dt
import json
import sys
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from trading_lab.contracts import Environment, LiveRelease  # noqa: E402
from trading_lab.security import (  # noqa: E402
    AuditLog,
    ExpectedBinding,
    NonceLedger,
    RevocationLedger,
    TrustedKeyStore,
    sign_payload,
)

NOW = dt.datetime(2026, 11, 20, 12, 0, 0, tzinfo=dt.timezone.utc)
FRESH = NOW - dt.timedelta(seconds=30)
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


def signed_release(owner_private_pem: bytes, **overrides):
    payload = {**VALID_RELEASE, **overrides}
    sig = sign_payload(owner_private_pem, payload)
    return LiveRelease.model_validate({**payload, "signature": sig})


def expected_binding(**overrides):
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


def fixed_now():
    return NOW


def audit_path(tmp_path):
    return AuditLog(tmp_path / "audit.jsonl", "TEST")


def audit_event_types(log):
    return [
        json.loads(line)["event_type"]
        for line in log.path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
