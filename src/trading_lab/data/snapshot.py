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


# ---------------------------------------------------------------------------
# R5 (M1-REVIEW-REMEDIATION-001): integrity is NOT research admission.
#
# ``verify()`` proves the bytes were not altered — an orthogonal property
# from "this snapshot may drive research". A hash-perfect manifest whose
# entries carry UNKNOWN availability or availability facts AFTER the
# knowledge cutoff is intact evidence of unusable data, not usable data.
# Research admission additionally requires the purpose-level acceptance
# verdict (acceptance.evaluate_purpose) — this gate covers only the
# manifest-internal time facts.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PitGateResult:
    ok: bool
    reasons: tuple[str, ...]


def research_admissible(manifest: SnapshotManifest) -> PitGateResult:
    """Explicit research-usability gate over a manifest:

    - hash integrity must hold (verify()) — a broken chain is unusable;
    - every entry's availability fact must be KNOWN (not
      ``UNKNOWN_AVAILABILITY``);
    - every entry's ``available_at`` must be <= the manifest's knowledge
      cutoff.

    Note: passing this gate is necessary, NOT sufficient — purpose-level
    license/coverage/quality admission is acceptance.evaluate_purpose's
    verdict, which must also be consulted before research use.
    """
    reasons: list[str] = []
    if not manifest.verify():
        reasons.append("INTEGRITY_FAILURE:manifest_hash_mismatch")
    for entry in manifest.entries:
        rec = entry.source
        if not rec.availability_known:
            reasons.append(f"UNKNOWN_AVAILABILITY:{entry.name}")
            continue
        available_at = rec.available_at_utc
        assert isinstance(available_at, dt.datetime)
        if available_at.tzinfo is None:
            reasons.append(f"NAIVE_AVAILABILITY:{entry.name}")
        elif available_at > manifest.knowledge_cutoff_utc:
            reasons.append(
                f"AVAILABLE_AFTER_CUTOFF:{entry.name}:"
                f"{available_at.isoformat()}>{manifest.knowledge_cutoff_utc.isoformat()}"
            )
    return PitGateResult(ok=not reasons, reasons=tuple(reasons))


__all__ = [
    "DatasetEntry",
    "PitGateResult",
    "SnapshotError",
    "SnapshotManifest",
    "build_snapshot",
    "content_hash_of_rows",
    "research_admissible",
]
