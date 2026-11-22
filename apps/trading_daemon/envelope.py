"""Forward event envelope — the validated admission boundary.

Every event entering the daemon passes through :class:`ForwardEvent`.
Fail-closed rules (task S1/S3: reject or suspend, never silently repair):

- all three timestamps must be timezone-aware (a naive availability fact
  is not a fact);
- ``ts_available >= ts_event`` (no retroactively-available history);
- ``dataset_hash`` must be 64 hex chars;
- ``close`` must be a finite positive Decimal — floats are rejected
  (imprecise decimal chains are banned platform-wide);
- identity fields are non-empty.

The *logical identity* of an event (:func:`payload_digest`) excludes
``received_at``: a redelivery of the same logical payload is an
idempotent duplicate whose ORIGINAL receipt time stands; any change to a
logical field is a different payload and a conflict.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
from decimal import Decimal
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    ValidationError,
    field_validator,
    model_validator,
)

from trading_lab.security.canonical import canonical_json_bytes

_HEX64 = re.compile(r"^[0-9a-f]{64}$")

__all__ = ["EnvelopeError", "ForwardEvent", "payload_digest"]


class EnvelopeError(Exception):
    """The event cannot be admitted — fail closed.

    Deliberately NOT a ``ValueError``: pydantic v2 wraps ValueError
    subclasses raised inside validators into its own ValidationError,
    which would hide the machine-readable ``reason``. Non-ValueError
    exceptions propagate through pydantic unchanged.
    """

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


def _require_tz(value: dt.datetime, name: str) -> dt.datetime:
    if not isinstance(value, dt.datetime):
        raise EnvelopeError("MALFORMED", f"{name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise EnvelopeError(
            "NAIVE_TIMESTAMP",
            f"{name} must be timezone-aware; a naive timestamp is not a "
            "fact")
    return value


class ForwardEvent(BaseModel):
    """One forward observation-event envelope (validated, frozen)."""

    model_config = ConfigDict(frozen=True)

    event_id: str
    source: str
    dataset_hash: str
    symbol: str
    interval: str
    ts_event: dt.datetime
    ts_available: dt.datetime
    received_at: dt.datetime
    close: Decimal
    environment: str | None = None

    @field_validator("event_id", "source", "symbol", "interval")
    @classmethod
    def _non_empty(cls, v: str, info) -> str:
        if not isinstance(v, str) or not v.strip():
            raise EnvelopeError(
                "MALFORMED", f"{info.field_name} must be a non-empty string")
        return v

    @field_validator("dataset_hash")
    @classmethod
    def _hex64(cls, v: str) -> str:
        if not isinstance(v, str) or not _HEX64.match(v):
            raise EnvelopeError(
                "BAD_HASH", "dataset_hash must be 64 hex chars")
        return v

    @field_validator("ts_event")
    @classmethod
    def _tz_event(cls, v: dt.datetime) -> dt.datetime:
        return _require_tz(v, "ts_event")

    @field_validator("ts_available")
    @classmethod
    def _tz_available(cls, v: dt.datetime, info) -> dt.datetime:
        _require_tz(v, "ts_available")
        return v

    @field_validator("received_at")
    @classmethod
    def _tz_received(cls, v: dt.datetime) -> dt.datetime:
        return _require_tz(v, "received_at")

    @field_validator("close", mode="before")
    @classmethod
    def _decimal_close(cls, v: Any) -> Any:
        if isinstance(v, float):
            raise EnvelopeError(
                "MALFORMED",
                "close must be Decimal/str/int — float is an imprecise "
                "decimal and is rejected")
        return v

    @field_validator("close")
    @classmethod
    def _positive_close(cls, v: Decimal) -> Decimal:
        if not v.is_finite() or v <= 0:
            raise EnvelopeError(
                "MALFORMED", "close must be a finite positive Decimal")
        return v

    @model_validator(mode="after")
    def _sanity(self) -> "ForwardEvent":
        if self.ts_available < self.ts_event:
            raise EnvelopeError(
                "AVAILABLE_BEFORE_EVENT",
                "ts_available must not precede ts_event")
        return self

    @classmethod
    def model_validate(cls, obj: Any, **kwargs: Any) -> "ForwardEvent":
        """Validate with fail-closed error translation: structural
        problems (missing fields, wrong types) become ``MALFORMED``
        instead of a bare pydantic ValidationError."""
        try:
            return super().model_validate(obj, **kwargs)
        except ValidationError as exc:
            raise EnvelopeError("MALFORMED", str(exc)) from exc


# pydantic v2 model_validator imported at module top; the sanity validator
# below runs after all field validators.


def payload_digest(ev: ForwardEvent) -> str:
    """Canonical digest of the LOGICAL event (received_at excluded — it
    is transport metadata; first receipt wins on redelivery)."""
    payload = {
        "event_id": ev.event_id,
        "source": ev.source,
        "dataset_hash": ev.dataset_hash,
        "symbol": ev.symbol,
        "interval": ev.interval,
        "ts_event": ev.ts_event,
        "ts_available": ev.ts_available,
        "close": str(ev.close),
    }
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
