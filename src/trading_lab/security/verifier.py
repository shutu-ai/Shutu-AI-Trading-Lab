"""LiveRelease verifier — the fail-closed validation chain for human-signed
approval artifacts (architecture §6.4/§6.5).

Trust model (M0, mock-only):

- Trusted public keys are pinned by key_id and deployed **out-of-band**
  (never through the research/agent channel). A release is acceptable only
  if its signature verifies against one of the pinned keys; a self-built
  key can never substitute the trust root.
- Every failing check yields a fail-closed decision. The verifier never
  raises on malformed input — it returns ``allow=False`` with reason codes
  and writes an audit event, so a fault is indistinguishable from an
  attack at the risk-decision layer.
- Revocation status must be provably fresh: a denylist hit, a superseded
  revocation epoch, an unreachable revocation source or a stale freshness
  record all fail closed (no "probably not revoked" path exists).
- The nonce is anti-replay for approval *operations*: replaying an old
  release/nonce is rejected. It is not a per-order token (§6.4).
- Signature validity alone never authorizes trading; callers must still
  pass independent risk and OMS decisions (§6.4).
"""

from __future__ import annotations

import base64
import binascii
import datetime as dt
import json
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from ..contracts import Environment, LiveRelease
from .audit import AuditLog
from .canonical import canonical_json_bytes

NowFn = Callable[[], dt.datetime]


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _signable_payload(release: LiveRelease) -> dict[str, Any]:
    """The canonical dict that the signature covers: every field except the
    signature itself."""
    payload = release.model_dump(mode="json")
    payload.pop("signature")
    return payload


# --------------------------------------------------------------------------
# Trust stores & ledgers (files outside Git: runtime state directories)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class TrustedKey:
    key_id: str
    public_pem: bytes


class TrustedKeyStore:
    """Backed by a JSON file ``[{"key_id": "...", "public_pem": "..."}]``
    deployed out-of-band. Load faults surface at load time so a broken trust
    root stops the runtime instead of silently weakening it."""

    def __init__(self, keys: list[TrustedKey]) -> None:
        if not keys:
            raise ValueError("trusted key store must contain at least one key")
        self._keys = {k.key_id: k for k in keys}
        if len(self._keys) != len(keys):
            raise ValueError("duplicate key_id in trusted key store")

    @classmethod
    def from_json_file(cls, path: str | Path) -> "TrustedKeyStore":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        keys = [TrustedKey(key_id=e["key_id"], public_pem=e["public_pem"].encode("utf-8")) for e in raw]
        return cls(keys)

    def verify_against_any(self, payload: dict[str, Any], signature_b64: str) -> bool:
        sig = None
        try:
            sig = base64.b64decode(signature_b64, validate=True)
        except (binascii.Error, ValueError):
            return False
        message = canonical_json_bytes(payload)
        for key in self._keys.values():
            try:
                pub = serialization.load_pem_public_key(key.public_pem)
                if not isinstance(pub, Ed25519PublicKey):
                    continue
                pub.verify(sig, message)
                return True
            except (InvalidSignature, ValueError):
                continue
        return False

    def key_ids(self) -> list[str]:
        return sorted(self._keys)


class NonceLedger:
    """Append-only JSONL of consumed approval nonces: {"nonce","release_id","used_at"}."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._used: dict[str, str] = {}
        if self._path.exists():
            with self._path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    rec = json.loads(line)
                    self._used[rec["nonce"]] = rec["release_id"]

    def is_used(self, nonce: str) -> bool:
        return nonce in self._used

    def record(self, nonce: str, release_id: str, used_at: str) -> None:
        if nonce in self._used:
            raise ValueError("nonce already recorded")
        self._used[nonce] = release_id
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    {"nonce": nonce, "release_id": release_id, "used_at": used_at},
                    sort_keys=True,
                )
                + "\n"
            )


@dataclass(frozen=True)
class RevocationCheck:
    ok: bool
    reason: str  # "" when ok


class RevocationLedger:
    """Denylist JSONL + freshness JSON, both maintained by the revocation
    source. Missing/unreadable files or stale freshness fail closed."""

    def __init__(
        self,
        denylist_path: str | Path,
        freshness_path: str | Path,
        max_staleness_seconds: int,
        now_fn: NowFn = _utc_now,
    ) -> None:
        self._denylist_path = Path(denylist_path)
        self._freshness_path = Path(freshness_path)
        self._max_staleness = max_staleness_seconds
        self._now_fn = now_fn

    def _load(self) -> tuple[list[dict[str, Any]], dt.datetime]:
        # Any fault here (missing file, bad JSON) raises -> caller fails closed.
        entries = [json.loads(l) for l in self._denylist_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        fresh = json.loads(self._freshness_path.read_text(encoding="utf-8"))
        last_checked = dt.datetime.fromisoformat(fresh["last_checked_at"])
        if last_checked.tzinfo is None:
            raise ValueError("revocation freshness timestamp must be timezone-aware")
        return entries, last_checked

    def check(self, release: LiveRelease) -> RevocationCheck:
        try:
            entries, last_checked = self._load()
        except Exception as exc:  # unreachable/corrupt revocation source
            return RevocationCheck(ok=False, reason=f"REVOCATION_SOURCE_UNAVAILABLE:{exc}")
        age = (self._now_fn() - last_checked).total_seconds()
        if age > self._max_staleness or age < -self._max_staleness:
            return RevocationCheck(
                ok=False,
                reason=f"REVOCATION_STATUS_STALE:age_seconds={age:.0f}",
            )
        ledger_epoch = 0
        for e in entries:
            ledger_epoch = max(ledger_epoch, int(e.get("epoch", 0)))
            if e.get("release_id") == release.release_id:
                return RevocationCheck(ok=False, reason="RELEASE_REVOKED")
        if ledger_epoch > release.revocation_epoch:
            return RevocationCheck(ok=False, reason="REVOCATION_EPOCH_SUPERSEDED")
        return RevocationCheck(ok=True, reason="")


# --------------------------------------------------------------------------
# Verifier
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ExpectedBinding:
    """What the runtime pins independently of the release document."""

    environment: Environment
    account_id: str
    approval_identity: str
    strategy_hashes: frozenset[str]
    build_digest: str
    protocol_hash: str
    policy_hash: str
    # Optional requested values; when present they must be within signed caps.
    requested_capital_cap: Decimal | None = None
    requested_max_order_cap: Decimal | None = None


@dataclass(frozen=True)
class VerifierDecision:
    allow: bool
    fail_closed: bool
    reason_codes: tuple[str, ...]
    release_id: str
    checked_at: str
    details: dict[str, Any] = field(default_factory=dict)


class LiveReleaseVerifier:
    def __init__(
        self,
        trusted_keys: TrustedKeyStore,
        nonce_ledger: NonceLedger,
        revocation_ledger: RevocationLedger,
        audit: AuditLog,
        now_fn: NowFn = _utc_now,
    ) -> None:
        self._keys = trusted_keys
        self._nonces = nonce_ledger
        self._revocations = revocation_ledger
        self._audit = audit
        self._now_fn = now_fn

    def verify(self, release: LiveRelease, expected: ExpectedBinding) -> VerifierDecision:
        reasons: list[str] = []
        details: dict[str, Any] = {"trusted_key_ids": self._keys.key_ids()}

        try:
            self._check(release, expected, reasons, details)
        except Exception as exc:  # internal fault -> fail closed, never allow
            reasons.append(f"VERIFIER_INTERNAL_FAULT:{type(exc).__name__}")

        allow = not reasons
        checked_at = self._now_fn().isoformat()
        if allow:
            used_at = checked_at
            try:
                self._nonces.record(release.nonce, release.release_id, used_at)
            except Exception as exc:
                allow = False
                reasons = [f"NONCE_RECORD_FAULT:{type(exc).__name__}"]
                details.clear()

        decision = VerifierDecision(
            allow=allow,
            fail_closed=not allow,
            reason_codes=tuple(reasons),
            release_id=release.release_id,
            checked_at=checked_at,
            details=details,
        )
        self._audit.append(
            "LIVE_RELEASE_VERIFIED" if allow else "LIVE_RELEASE_REJECTED",
            {
                "release_id": release.release_id,
                "reason_codes": list(decision.reason_codes),
                "environment": str(expected.environment),
                "account_id": expected.account_id,
            },
        )
        return decision

    # -- individual checks --------------------------------------------------

    def _check(
        self,
        release: LiveRelease,
        expected: ExpectedBinding,
        reasons: list[str],
        details: dict[str, Any],
    ) -> None:
        if release.signature_algorithm != "Ed25519":
            reasons.append(f"UNSUPPORTED_SIGNATURE_ALGORITHM:{release.signature_algorithm}")

        if not self._keys.verify_against_any(_signable_payload(release), release.signature):
            reasons.append("SIGNATURE_INVALID_OR_TRUST_ROOT_UNRECOGNIZED")

        if release.approval_identity != expected.approval_identity:
            reasons.append(
                f"APPROVAL_IDENTITY_MISMATCH:release={release.approval_identity},"
                f"expected={expected.approval_identity}"
            )
        if release.environment is not expected.environment:
            reasons.append(
                f"ENVIRONMENT_MISMATCH:release={release.environment},expected={expected.environment}"
            )
        if release.account_id != expected.account_id:
            reasons.append(
                f"ACCOUNT_MISMATCH:release={release.account_id},expected={expected.account_id}"
            )

        now = self._now_fn()
        if now.tzinfo is None or now.tzinfo.utcoffset(now) is None:
            reasons.append("CLOCK_ANOMALY:naive_now")
        else:
            if now < release.valid_from:
                reasons.append(f"NOT_YET_VALID:valid_from={release.valid_from.isoformat()}")
            if now > release.expires_at:
                reasons.append(f"EXPIRED:expires_at={release.expires_at.isoformat()}")

        if self._nonces.is_used(release.nonce):
            reasons.append(f"NONCE_REPLAY:nonce={release.nonce}")

        rev = self._revocations.check(release)
        if not rev.ok:
            reasons.append(rev.reason)
        details["revocation_epoch_release"] = release.revocation_epoch

        if frozenset(release.strategy_hashes) != expected.strategy_hashes:
            reasons.append("STRATEGY_HASH_MISMATCH")
        if release.build_digest != expected.build_digest:
            reasons.append("BUILD_DIGEST_MISMATCH")
        if release.protocol_hash != expected.protocol_hash:
            reasons.append("PROTOCOL_HASH_MISMATCH")
        if release.policy_hash != expected.policy_hash:
            reasons.append("POLICY_HASH_MISMATCH")

        if expected.requested_capital_cap is not None and (
            expected.requested_capital_cap > release.capital_cap
        ):
            reasons.append(
                f"CAPITAL_CAP_EXCEEDED:requested={expected.requested_capital_cap},"
                f"signed={release.capital_cap}"
            )
        if expected.requested_max_order_cap is not None and (
            expected.requested_max_order_cap > release.max_order_cap
        ):
            reasons.append(
                f"ORDER_CAP_EXCEEDED:requested={expected.requested_max_order_cap},"
                f"signed={release.max_order_cap}"
            )


__all__ = [
    "ExpectedBinding",
    "LiveReleaseVerifier",
    "NonceLedger",
    "RevocationCheck",
    "RevocationLedger",
    "TrustedKey",
    "TrustedKeyStore",
    "VerifierDecision",
]
