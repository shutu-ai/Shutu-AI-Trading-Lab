"""Trusted producer binding (M2-T1): the producer identity consumed by the
risk engine comes from a runtime-minted object that external JSON cannot
forge — not from self-reported text.

MOCK_ONLY / UNVERIFIED: the binding holds within one process. Real
cross-process producer attestation is not implemented in M2 and must not be
claimed as production isolation.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field

from ..contracts import HexHash


@dataclass(frozen=True)
class TrustedProducer:
    """Minted only via :meth:`mint` by the trusted runtime entrypoint.
    Instances compare by their random token, so a test cannot fabricate one
    by re-typing the fields."""

    producer_id: str
    reviewed_build_hash: HexHash
    _token: str = field(repr=False, compare=True, default="")

    @classmethod
    def mint(cls, producer_id: str, reviewed_build_hash: str) -> "TrustedProducer":
        if not producer_id.strip():
            raise ValueError("producer_id must be non-empty")
        return cls(producer_id=producer_id, reviewed_build_hash=reviewed_build_hash,
                   _token=secrets.token_hex(16))

    def matches_binding(self, other: object) -> bool:
        """The only sanctioned comparison: object identity via random token."""
        return isinstance(other, TrustedProducer) and self._token == other._token and (
            self.producer_id == other.producer_id
        )


__all__ = ["TrustedProducer"]
