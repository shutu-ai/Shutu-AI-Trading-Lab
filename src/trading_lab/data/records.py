"""Source provenance records — the evidence chain every M1 dataset entry
must carry (task §M1-T2): ``source + dataset_version + acquisition_time +
available_at + raw_hash + transform_version``.

A :class:`SourceRecord` is metadata only: it never contains the data rows
themselves, which stay raw bytes/canonical structures hashed at ingestion.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

MARKER_UNKNOWN_AVAILABILITY = "UNKNOWN_AVAILABILITY"

#: H1A (M3-H): WHY a SourceRecord's ``available_at_utc`` is what it is.
#: ``vendor_fact`` (default) — a vendor-published availability fact, the
#: only basis that can support VERIFIED pit evidence. ``assumed_next_open``
#: — derived from the frozen calendar's next-session-open rule (a declared
#: MODEL ASSUMPTION, never VERIFIED). ``unknown`` — no availability answer
#: exists; never silently promoted to an assumption.
AVAILABILITY_BASIS_VENDOR_FACT = "vendor_fact"
AVAILABILITY_BASIS_ASSUMED_NEXT_OPEN = "assumed_next_open"
AVAILABILITY_BASIS_UNKNOWN = "unknown"
AVAILABILITY_BASES = frozenset(
    {
        AVAILABILITY_BASIS_VENDOR_FACT,
        AVAILABILITY_BASIS_ASSUMED_NEXT_OPEN,
        AVAILABILITY_BASIS_UNKNOWN,
    }
)


@dataclass(frozen=True)
class SourceRecord:
    """Immutable provenance for one ingested dataset partition."""

    source: str                      # vendor / origin identifier
    dataset_version: str             # vendor-side version or snapshot label
    acquisition_time_utc: dt.datetime  # when WE received the bytes (tz-aware)
    available_at_utc: object         # tz-aware datetime, or the literal
                                     # UNKNOWN_AVAILABILITY marker when the
                                     # vendor provides no availability fact
    raw_hash: str                    # sha256 of the raw bytes as received
    transform_version: str           # version of the deterministic transform
                                     # applied downstream (e.g. "adj-1")
    availability_basis: str = AVAILABILITY_BASIS_VENDOR_FACT  # H1A: why
                                     # available_at_utc is what it is
                                     # (vendor fact / next-open assumption
                                     # / unknown) — see AVAILABILITY_BASES

    def __post_init__(self) -> None:
        if not self.source or not self.dataset_version or not self.raw_hash:
            raise ValueError("source/dataset_version/raw_hash must be non-empty")
        if self.availability_basis not in AVAILABILITY_BASES:
            raise ValueError(
                f"availability_basis {self.availability_basis!r} outside the "
                f"closed vocabulary {sorted(AVAILABILITY_BASES)}"
            )
        if self.available_at_utc == MARKER_UNKNOWN_AVAILABILITY:
            if self.availability_basis == AVAILABILITY_BASIS_ASSUMED_NEXT_OPEN:
                raise ValueError(
                    "availability_basis 'assumed_next_open' requires an "
                    "assumed availability datetime, not UNKNOWN_AVAILABILITY"
                )
            return
        if not isinstance(self.available_at_utc, dt.datetime):
            raise ValueError("available_at_utc must be tz-aware datetime or UNKNOWN_AVAILABILITY")
        if self.available_at_utc.tzinfo is None:
            raise ValueError("available_at_utc must be timezone-aware")
        if self.availability_basis == AVAILABILITY_BASIS_UNKNOWN:
            raise ValueError(
                "availability_basis 'unknown' requires the UNKNOWN_AVAILABILITY "
                "marker — a concrete datetime is a claim, not an unknown"
            )

    @property
    def availability_known(self) -> bool:
        return self.available_at_utc != MARKER_UNKNOWN_AVAILABILITY


__all__ = [
    "AVAILABILITY_BASES",
    "AVAILABILITY_BASIS_ASSUMED_NEXT_OPEN",
    "AVAILABILITY_BASIS_UNKNOWN",
    "AVAILABILITY_BASIS_VENDOR_FACT",
    "MARKER_UNKNOWN_AVAILABILITY",
    "SourceRecord",
]
