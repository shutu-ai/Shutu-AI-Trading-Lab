"""Canonical JSON serialization — the byte-exact representation that is
signed and verified (architecture §6.4: 签名覆盖规范化序列化后的完整内容).

Rules: UTF-8, sorted keys, no insignificant whitespace, no NaN/Infinity,
integers stay integers, Decimals render as strings (via the contract layer's
JSON mode). Any byte difference — including key order — changes the digest
and invalidates the signature.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from decimal import Decimal
from typing import Any

def _json_default(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, dt.datetime):
        # RFC 3339; UTC rendered with 'Z' to match the contract layer's
        # JSON serialization (pydantic v2 emits Z for UTC datetimes).
        return obj.isoformat().replace("+00:00", "Z")
    raise TypeError(f"cannot canonicalize object of type {type(obj)!r}")


_ENCODER = json.JSONEncoder(
    ensure_ascii=False,
    sort_keys=True,
    separators=(",", ":"),
    allow_nan=False,
    default=_json_default,
)


def canonical_json_bytes(payload: Any) -> bytes:
    """Serialize ``payload`` to its canonical JSON byte representation."""
    return _ENCODER.encode(payload).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_digest(payload: Any) -> str:
    """SHA-256 hex digest of the canonical JSON form of ``payload``."""
    return sha256_hex(canonical_json_bytes(payload))
