"""LiveRelease verifier negative matrix — maps architecture §6.5 rows to
assertions. Every rejected release must be fail_closed with an explicit
reason, and every rejection must land in the audit log."""

from __future__ import annotations

import datetime as dt
import json
import sys
from decimal import Decimal
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from trading_lab.contracts import Environment
from trading_lab.security import (
    AuditLog,
    LiveReleaseVerifier,
    NonceLedger,
    RevocationLedger,
    TrustedKeyStore,
)
from trading_lab.security.verifier import _signable_payload  # noqa: SLF001 - test seam

from conftest import FRESH, NOW, ACCOUNT, OWNER_IDENTITY, expected_binding, fixed_now, signed_release


def audit_path(tmp_path):
    return AuditLog(tmp_path / "audit.jsonl", "TEST")


def audit_event_types(log: AuditLog) -> list[str]:
    return [json.loads(l)["event_type"] for l in log.path.read_text(encoding="utf-8").splitlines() if l.strip()]


class TestPositivePath:
    def test_valid_release_verifies(self, owner_key, verifier_factory, tmp_ledgers):
        v = verifier_factory()
        release = signed_release(owner_key.private_pem)
        decision = v.verify(release, expected_binding())
        assert decision.allow and not decision.fail_closed
        assert audit_event_types(AuditLog(tmp_ledgers["root"] / "audit.jsonl", "TEST"))[-1] == "LIVE_RELEASE_VERIFIED"

    def test_nonce_recorded_prevents_replay(self, owner_key, verifier_factory):
        v = verifier_factory()
        release = signed_release(owner_key.private_pem)
        assert v.verify(release, expected_binding()).allow
        replay = v.verify(release, expected_binding())
        assert not replay.allow
        assert any(r.startswith("NONCE_REPLAY") for r in replay.reason_codes)


class TestIdentityAndForgery:
    def test_self_built_key_rejected(self, attacker_key, verifier_factory):
        """§6.5 身份/授权: Agent 自建公钥替换信任根 -> 拒绝。"""
        v = verifier_factory()
        release = signed_release(attacker_key.private_pem)  # not in trust root
        decision = v.verify(release, expected_binding())
        assert not decision.allow and decision.fail_closed
        assert "SIGNATURE_INVALID_OR_TRUST_ROOT_UNRECOGNIZED" in decision.reason_codes

    def test_tampered_payload_rejected(self, owner_key, verifier_factory):
        """§6.5 不可伪造: 修改载荷(hash/额度) -> 拒绝。"""
        v = verifier_factory()
        release = signed_release(owner_key.private_pem)
        tampered = release.model_copy(update={"policy_hash": "9" * 32})
        decision = v.verify(tampered, expected_binding())
        assert not decision.allow
        assert "POLICY_HASH_MISMATCH" in decision.reason_codes
        assert "SIGNATURE_INVALID_OR_TRUST_ROOT_UNRECOGNIZED" in decision.reason_codes

    def test_garbage_signature_fail_closed(self, owner_key, verifier_factory):
        v = verifier_factory()
        release = signed_release(owner_key.private_pem)
        broken = release.model_copy(update={"signature": "AAAA"})
        decision = v.verify(broken, expected_binding())
        assert not decision.allow and "SIGNATURE_INVALID_OR_TRUST_ROOT_UNRECOGNIZED" in decision.reason_codes

    def test_wrong_algorithm_rejected(self, owner_key, verifier_factory):
        v = verifier_factory()
        release = signed_release(owner_key.private_pem)
        bad = release.model_copy(update={"signature_algorithm": "RSA"})
        decision = v.verify(bad, expected_binding())
        assert any(r.startswith("UNSUPPORTED_SIGNATURE_ALGORITHM") for r in decision.reason_codes)

    def test_approval_identity_mismatch(self, owner_key, verifier_factory):
        v = verifier_factory()
        release = signed_release(owner_key.private_pem, approval_identity="SOMEONE_ELSE")
        decision = v.verify(release, expected_binding())
        assert not decision.allow
        assert any(r.startswith("APPROVAL_IDENTITY_MISMATCH") for r in decision.reason_codes)


class TestScope:
    def test_wrong_account_rejected(self, owner_key, verifier_factory):
        v = verifier_factory()
        release = signed_release(owner_key.private_pem, account_id="OTHER_ACCOUNT")
        decision = v.verify(release, expected_binding())
        assert any(r.startswith("ACCOUNT_MISMATCH") for r in decision.reason_codes)

    def test_paper_release_used_for_live_rejected(self, owner_key, verifier_factory):
        v = verifier_factory()
        release = signed_release(owner_key.private_pem, environment=Environment.PAPER)
        decision = v.verify(release, expected_binding(environment=Environment.LIVE))
        assert any(r.startswith("ENVIRONMENT_MISMATCH") for r in decision.reason_codes)

    def test_over_capital_cap_rejected(self, owner_key, verifier_factory):
        v = verifier_factory()
        release = signed_release(owner_key.private_pem)
        binding = expected_binding(requested_capital_cap=Decimal("5000.00"))
        decision = v.verify(release, binding)
        assert any(r.startswith("CAPITAL_CAP_EXCEEDED") for r in decision.reason_codes)

    def test_over_order_cap_rejected(self, owner_key, verifier_factory):
        v = verifier_factory()
        release = signed_release(owner_key.private_pem)
        binding = expected_binding(requested_max_order_cap=Decimal("999.00"))
        decision = v.verify(release, binding)
        assert any(r.startswith("ORDER_CAP_EXCEEDED") for r in decision.reason_codes)

    def test_strategy_hash_mismatch_rejected(self, owner_key, verifier_factory):
        v = verifier_factory()
        release = signed_release(owner_key.private_pem, strategy_hashes=("8" * 32,))
        decision = v.verify(release, expected_binding())
        assert "STRATEGY_HASH_MISMATCH" in decision.reason_codes

    def test_build_digest_mismatch_rejected(self, owner_key, verifier_factory):
        v = verifier_factory()
        release = signed_release(owner_key.private_pem, build_digest="8" * 32)
        decision = v.verify(release, expected_binding())
        assert "BUILD_DIGEST_MISMATCH" in decision.reason_codes


class TestTimeliness:
    def test_not_yet_valid_rejected(self, owner_key, verifier_factory):
        # The document is internally consistent; the *verification clock* sits
        # before valid_from (e.g. replayed old approval).
        v = verifier_factory(now_fn=lambda: NOW - dt.timedelta(hours=1))
        release = signed_release(owner_key.private_pem)
        decision = v.verify(release, expected_binding())
        assert any(r.startswith("NOT_YET_VALID") for r in decision.reason_codes)

    def test_expired_rejected(self, owner_key, verifier_factory):
        # Verification clock two hours past signing: the window has elapsed.
        v = verifier_factory(now_fn=lambda: NOW + dt.timedelta(hours=2))
        release = signed_release(owner_key.private_pem)
        decision = v.verify(release, expected_binding())
        assert any(r.startswith("EXPIRED") for r in decision.reason_codes)

    def test_naive_clock_rejected(self, owner_key, verifier_factory):
        v = verifier_factory(now_fn=lambda: NOW.replace(tzinfo=None))
        release = signed_release(owner_key.private_pem)
        decision = v.verify(release, expected_binding())
        assert any(r.startswith("CLOCK_ANOMALY") for r in decision.reason_codes)

    def test_nonce_replay_of_old_approval_rejected(self, owner_key, verifier_factory):
        v = verifier_factory()
        release = signed_release(owner_key.private_pem)
        assert v.verify(release, expected_binding()).allow
        # same nonce, new document (attacker re-signs a different release with
        # the owner's leaked key material — still a replayed approval nonce)
        second = signed_release(owner_key.private_pem, release_id="rel-mock-0002")
        decision = v.verify(second, expected_binding())
        assert any(r.startswith("NONCE_REPLAY") for r in decision.reason_codes)


class TestRevocation:
    def test_denylist_hit_rejected(self, owner_key, verifier_factory, tmp_ledgers):
        tmp_ledgers["revocations"].write_text(
            json.dumps({"release_id": "rel-mock-0001", "epoch": 1, "revoked_at": NOW.isoformat()}) + "\n",
            encoding="utf-8",
        )
        v = verifier_factory()
        release = signed_release(owner_key.private_pem)
        decision = v.verify(release, expected_binding())
        assert not decision.allow
        assert "RELEASE_REVOKED" in decision.reason_codes

    def test_superseded_revocation_epoch_rejected(self, owner_key, verifier_factory, tmp_ledgers):
        tmp_ledgers["revocations"].write_text(
            json.dumps({"release_id": "rel-other", "epoch": 5, "revoked_at": NOW.isoformat()}) + "\n",
            encoding="utf-8",
        )
        v = verifier_factory()
        release = signed_release(owner_key.private_pem, revocation_epoch=0)
        decision = v.verify(release, expected_binding())
        assert "REVOCATION_EPOCH_SUPERSEDED" in decision.reason_codes

    def test_unreachable_revocation_source_fails_closed(self, owner_key, verifier_factory, tmp_ledgers):
        tmp_ledgers["revocations"].unlink()
        v = verifier_factory()
        release = signed_release(owner_key.private_pem)
        decision = v.verify(release, expected_binding())
        assert not decision.allow
        assert any(r.startswith("REVOCATION_SOURCE_UNAVAILABLE") for r in decision.reason_codes)

    def test_stale_revocation_status_fails_closed(self, owner_key, verifier_factory, tmp_ledgers):
        stale = NOW - dt.timedelta(seconds=3600)
        tmp_ledgers["freshness"].write_text(
            json.dumps({"last_checked_at": stale.isoformat()}), encoding="utf-8"
        )
        v = verifier_factory()
        release = signed_release(owner_key.private_pem)
        decision = v.verify(release, expected_binding())
        assert any(r.startswith("REVOCATION_STATUS_STALE") for r in decision.reason_codes)

    def test_future_freshness_beyond_tolerance_fails_closed(self, owner_key, verifier_factory, tmp_ledgers):
        future = NOW + dt.timedelta(seconds=3600)  # clock rolled back?
        tmp_ledgers["freshness"].write_text(
            json.dumps({"last_checked_at": future.isoformat()}), encoding="utf-8"
        )
        v = verifier_factory()
        release = signed_release(owner_key.private_pem)
        decision = v.verify(release, expected_binding())
        assert any(r.startswith("REVOCATION_STATUS_STALE") for r in decision.reason_codes)


class TestFaults:
    def test_missing_trust_root_stops_construction(self, tmp_ledgers):
        """故障: 信任根不可读 -> 构造即失败（不得静默弱化）。"""
        with pytest.raises(Exception):
            TrustedKeyStore.from_json_file(tmp_ledgers["root"] / "does_not_exist.json")

    def test_empty_trust_root_rejected(self, tmp_ledgers):
        empty = tmp_ledgers["root"] / "empty.json"
        empty.write_text("[]", encoding="utf-8")
        with pytest.raises(ValueError):
            TrustedKeyStore.from_json_file(empty)

    def test_corrupt_nonce_ledger_fails_closed_on_record(self, owner_key, tmp_ledgers):
        """故障: 验签器/账本故障 -> FAIL_CLOSED，绝不允许。"""
        (tmp_ledgers["root"] / "trusted.json").write_text(
            json.dumps([{"key_id": owner_key.key_id, "public_pem": owner_key.public_pem.decode()}]),
            encoding="utf-8",
        )
        nonce_path = tmp_ledgers["nonces"]
        nonce_path.write_text("{corrupt json\n", encoding="utf-8")
        decision = None
        try:
            v = LiveReleaseVerifier(
                trusted_keys=TrustedKeyStore.from_json_file(tmp_ledgers["root"] / "trusted.json"),
                nonce_ledger=NonceLedger(nonce_path),
                revocation_ledger=RevocationLedger(
                    tmp_ledgers["revocations"], tmp_ledgers["freshness"], 300, now_fn=fixed_now
                ),
                audit=audit_path(tmp_ledgers["root"]),
                now_fn=fixed_now,
            )
            release = signed_release(owner_key.private_pem)
            decision = v.verify(release, expected_binding())
        except Exception:
            # A corrupt ledger may refuse construction outright — that is
            # fail-closed too; the runtime must not start on a broken ledger.
            decision = None
        assert decision is None or not decision.allow


class TestAuditTrail:
    def test_every_rejection_is_audited(self, attacker_key, owner_key, verifier_factory, tmp_ledgers):
        v = verifier_factory()
        v.verify(signed_release(attacker_key.private_pem), expected_binding())
        types = audit_event_types(AuditLog(tmp_ledgers["root"] / "audit.jsonl", "TEST"))
        assert "LIVE_RELEASE_REJECTED" in types

    def test_verifier_decision_carries_no_key_material(self, owner_key, verifier_factory):
        v = verifier_factory()
        decision = v.verify(signed_release(owner_key.private_pem), expected_binding())
        blob = json.dumps(decision.details)
        assert "PRIVATE KEY" not in blob
        assert owner_key.private_pem.decode() not in blob
