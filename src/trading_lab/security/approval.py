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


__all__ = ["ApprovalSecrets"]
