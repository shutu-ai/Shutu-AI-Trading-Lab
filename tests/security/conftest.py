"""Security-suite fixtures (constants/factories live in helpers_security)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

from helpers_security import fixed_now, ACCOUNT  # noqa: E402

from trading_lab.security import (  # noqa: E402
    AuditLog,
    LiveReleaseVerifier,
    NonceLedger,
    RevocationLedger,
    TrustedKeyStore,
    generate_test_keypair,
)
from trading_lab.security.verifier import RevocationLedger as _RevLedger  # noqa: E402,F401


@pytest.fixture()
def owner_key():
    return generate_test_keypair()


@pytest.fixture()
def attacker_key():
    return generate_test_keypair()


@pytest.fixture()
def tmp_ledgers(tmp_path):
    rev_path = tmp_path / "revocations.jsonl"
    fresh_path = tmp_path / "freshness.json"
    from helpers_security import FRESH

    rev_path.write_text("", encoding="utf-8")
    fresh_path.write_text(json.dumps({"last_checked_at": FRESH.isoformat()}), encoding="utf-8")
    return {
        "revocations": rev_path,
        "freshness": fresh_path,
        "nonces": tmp_path / "nonces.jsonl",
        "root": tmp_path,
    }


def _trusted_keys_file(root: Path, keypair) -> Path:
    path = root / "trusted.json"
    path.write_text(
        json.dumps([{"key_id": keypair.key_id, "public_pem": keypair.public_pem.decode()}]),
        encoding="utf-8",
    )
    return path


@pytest.fixture()
def verifier_factory(owner_key, tmp_ledgers):
    def make(now_fn=fixed_now, max_staleness: int = 300):
        from helpers_security import FRESH

        return LiveReleaseVerifier(
            trusted_keys=TrustedKeyStore.from_json_file(
                _trusted_keys_file(tmp_ledgers["root"], owner_key)
            ),
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
