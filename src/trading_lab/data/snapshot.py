"""Deterministic snapshot manifests.

A snapshot pins exactly which dataset partitions (content hashes +
provenance) were used at a given knowledge cutoff. The manifest hash is
SHA-256 over the canonical JSON of the sorted entries — the same inputs and
versions always produce the same hash, and changing a single raw price,
timestamp or factor changes the hash (tamper detection is a property test,
not a hope).

Hashing reuses the platform's canonical serializer (security.canonical) so
contract objects, gate payloads and snapshots all share one byte-exact
representation.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from trading_lab.security.canonical import canonical_json_bytes, sha256_hex

from .records import MARKER_UNKNOWN_AVAILABILITY, SourceRecord


@dataclass(frozen=True)
class DatasetEntry:
    """One dataset partition inside a snapshot: identity + content digest +
    provenance. ``content_hash`` is the sha256 of the partition's canonical
    serialized content (rows), computed by the caller at ingestion."""

    name: str
    content_hash: str
    row_count: int
    source: SourceRecord


class SnapshotError(ValueError):
    pass


@dataclass(frozen=True)
class SnapshotManifest:
    knowledge_cutoff_utc: dt.datetime
    entries: tuple[DatasetEntry, ...]
    dataset_hash: str

    def verify(self) -> bool:
        expected = _manifest_hash(self.knowledge_cutoff_utc, self.entries)
        return expected == self.dataset_hash


def _entry_dict(entry: DatasetEntry) -> dict[str, object]:
    rec = entry.source
    avail: object
    if rec.availability_known:
        assert isinstance(rec.available_at_utc, dt.datetime)
        avail = rec.available_at_utc.isoformat()
    else:
        avail = MARKER_UNKNOWN_AVAILABILITY
    return {
        "name": entry.name,
        "content_hash": entry.content_hash,
        "row_count": entry.row_count,
        "source": {
            "source": rec.source,
            "dataset_version": rec.dataset_version,
            "acquisition_time_utc": rec.acquisition_time_utc.isoformat(),
            "available_at_utc": avail,
            "raw_hash": rec.raw_hash,
            "transform_version": rec.transform_version,
        },
    }


def _manifest_hash(knowledge_cutoff: dt.datetime, entries: tuple[DatasetEntry, ...]) -> str:
    payload = {
        "knowledge_cutoff_utc": knowledge_cutoff.isoformat(),
        "entries": sorted(
            (_entry_dict(e) for e in entries), key=lambda d: d["name"]  # type: ignore[arg-type,return-value]
        ),
    }
    return sha256_hex(canonical_json_bytes(payload))


def build_snapshot(
    knowledge_cutoff_utc: dt.datetime,
    entries: list[DatasetEntry],
) -> SnapshotManifest:
    """Build the manifest deterministically: entries sorted by name, hash
    over canonical JSON. Duplicate dataset names are rejected — a snapshot
    pins exactly one partition per dataset."""
    if knowledge_cutoff_utc.tzinfo is None:
        raise SnapshotError("knowledge_cutoff_utc must be timezone-aware")
    names = [e.name for e in entries]
    if len(names) != len(set(names)):
        raise SnapshotError(f"duplicate dataset names in snapshot: {names}")
    for e in entries:
        if len(e.content_hash) != 64:
            raise SnapshotError(f"content_hash for {e.name} is not a sha256 hex digest")
    entries_t = tuple(entries)
    return SnapshotManifest(
        knowledge_cutoff_utc=knowledge_cutoff_utc,
        entries=entries_t,
        dataset_hash=_manifest_hash(knowledge_cutoff_utc, entries_t),
    )


def content_hash_of_rows(rows: list[dict[str, object]]) -> str:
    """Content digest of a data partition: canonical JSON of the rows sorted
    by their canonical byte form (order-independent for equal content,
    sensitive to any value change)."""
    payload = sorted(canonical_json_bytes(r).decode("utf-8") for r in rows)
    return sha256_hex(canonical_json_bytes({"rows": payload}))


__all__ = ["DatasetEntry", "SnapshotError", "SnapshotManifest", "build_snapshot", "content_hash_of_rows"]
