"""Approval sealing (M2-R1): a RiskDecision only authorizes a send when it
carries an HMAC seal over the exact intent+symbol+side+quantity+policy
binding, keyed by a runtime-minted secret shared ONLY with the OMS
assembly. Forged or parameter-substituted decisions cannot produce a valid
seal, and the OMS refuses them before any journal write or broker call.

MOCK_ONLY: the secret lives in one process (single trusted assembly).
Cross-process secret distribution is UNVERIFIED and must not be claimed.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets as _secrets
from dataclasses import dataclass

from .canonical import canonical_json_bytes


@dataclass(frozen=True)
class ApprovalSecrets:
    _key: bytes

    @classmethod
    def mint(cls) -> "ApprovalSecrets":
        return cls(_key=_secrets.token_bytes(32))

    def seal(self, binding: dict) -> str:
        return hmac.new(self._key, canonical_json_bytes(binding), hashlib.sha256).hexdigest()

    def verify(self, binding: dict, seal: str) -> bool:
        expected = hmac.new(self._key, canonical_json_bytes(binding), hashlib.sha256).digest()
        try:
            return hmac.compare_digest(expected, bytes.fromhex(seal))
        except ValueError:
            return False


def build_send_binding(
    intent_payload: dict,
    symbol: str,
    side: str,
    quantity: str,
    policy_hash: str,
    decision_at: str,
    expires_at: str,
) -> dict:
    """The single canonical approval binding, shared by the RiskEngine
    (sealing), the OMS (validation) and the egress (re-verification) — one
    construction, never three divergent ones."""
    return {
        "intent": intent_payload,
        "symbol": symbol,
        "side": side,
        "quantity": quantity,
        "policy_hash": policy_hash,
        "decision_at": decision_at,
        "expires_at": expires_at,
    }


def seal_is_valid(secrets: ApprovalSecrets, binding: dict, seal: str) -> bool:
    return secrets.verify(binding, seal)


__all__ = ["ApprovalSecrets", "build_send_binding", "seal_is_valid"]
