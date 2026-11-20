"""Ed25519 signing: canonical-JSON determinism and tamper detection."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from trading_lab.security import (
    canonical_digest,
    canonical_json_bytes,
    generate_test_keypair,
    sign_payload,
    verify_signature,
)


class TestCanonicalization:
    def test_key_order_irrelevant_for_digest(self):
        a = {"x": 1, "y": {"b": 2, "a": 1}}
        b = {"y": {"a": 1, "b": 2}, "x": 1}
        assert canonical_digest(a) == canonical_digest(b)

    def test_byte_difference_changes_digest(self):
        assert canonical_json_bytes({"a": 1, "b": 2}) == b'{"a":1,"b":2}'
        assert canonical_digest({"a": 1}) != canonical_digest({"a": "1"})

    def test_nan_rejected(self):
        import math

        try:
            canonical_json_bytes({"x": float("nan")})
            raise AssertionError("NaN must not canonicalize")
        except (ValueError, TypeError):
            pass

    def test_decimal_renders_as_string(self):
        from decimal import Decimal

        assert canonical_json_bytes({"v": Decimal("1.50")}) == b'{"v":"1.50"}'


class TestSigning:
    def test_roundtrip(self):
        kp = generate_test_keypair()
        payload = {"release_id": "rel-1", "capital_cap": "1000"}
        sig = sign_payload(kp.private_pem, payload)
        assert verify_signature(kp.public_pem, payload, sig)

    def test_any_payload_tamper_rejected(self):
        kp = generate_test_keypair()
        payload = {"a": "1"}
        sig = sign_payload(kp.private_pem, payload)
        for tampered in ({"a": "2"}, {"a": "1", "b": 0}):
            assert not verify_signature(kp.public_pem, tampered, sig)

    def test_wrong_key_rejected(self):
        kp1 = generate_test_keypair()
        kp2 = generate_test_keypair()
        payload = {"a": "1"}
        sig = sign_payload(kp1.private_pem, payload)
        assert not verify_signature(kp2.public_pem, payload, sig)

    def test_garbage_signature_rejected(self):
        kp = generate_test_keypair()
        assert not verify_signature(kp.public_pem, {"a": "1"}, "not-base64!!")
        assert not verify_signature(kp.public_pem, {"a": "1"}, "")

    def test_key_id_binds_public_bytes(self):
        kp1 = generate_test_keypair()
        kp2 = generate_test_keypair()
        assert kp1.key_id != kp2.key_id
        assert len(kp1.key_id) == 16
