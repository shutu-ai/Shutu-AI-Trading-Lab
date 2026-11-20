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

    def __post_init__(self) -> None:
        if not self.source or not self.dataset_version or not self.raw_hash:
            raise ValueError("source/dataset_version/raw_hash must be non-empty")
        if self.available_at_utc == MARKER_UNKNOWN_AVAILABILITY:
            return
        if not isinstance(self.available_at_utc, dt.datetime):
            raise ValueError("available_at_utc must be tz-aware datetime or UNKNOWN_AVAILABILITY")
        if self.available_at_utc.tzinfo is None:
            raise ValueError("available_at_utc must be timezone-aware")

    @property
    def availability_known(self) -> bool:
        return self.available_at_utc != MARKER_UNKNOWN_AVAILABILITY


__all__ = ["MARKER_UNKNOWN_AVAILABILITY", "SourceRecord"]
