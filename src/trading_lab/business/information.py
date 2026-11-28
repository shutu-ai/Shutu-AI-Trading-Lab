"""Information-event ingestion for the Business MVP replay (B2): load,
verify, deduplicate, PIT-filter — strictly offline, fail-closed.

Invariants:

- Records come from offline fixture files only (``.jsonl`` / ``.json`` /
  ``.csv``, read with the stdlib). No network, no vendor SDK, no wall clock.
- Every record is pre-checked against the exact key set, then validated
  against the ``InformationEvent`` contract in JSON mode. Unknown keys and
  missing PIT timestamps are refused with precise, machine-readable
  reasons.
- ``content_hash`` is verified by recomputation (SHA-256 hex over the
  UTF-8 content bytes — :func:`content_hash_of` is the single documented
  recipe). A claimed hash that does not match refuses the record.
- A record that fails any check NEVER enters the bundle; it is listed in
  ``InfoBundle.rejected``. An event without a parseable
  ``available_at``/``received_at`` therefore cannot reach a decision.
- Duplicate content (same ``content_hash``) is counted, not loaded; the
  first occurrence in file order wins.
- Events are stored in the deterministic order
  ``(available_at_utc, event_id)``; ``usable(asof_utc)`` keeps that order.
- PIT gate: an event participates in a decision only once
  ``max(available_at, received_at) <= asof``. Assessment expiry is the
  assessment layer's job (``valid_until``), not this module's.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import json
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from trading_lab.business.models import InformationEvent
from trading_lab.security.canonical import sha256_hex

__all__ = [
    "InfoBundle",
    "RejectedRecord",
    "content_hash_of",
    "load_info_events",
]

_EVENT_KEYS = frozenset({
    "event_id",
    "asset",
    "source",
    "source_url",
    "event_at_utc",
    "published_at_utc",
    "available_at_utc",
    "received_at_utc",
    "content",
    "content_hash",
})

_MAX_REASON = 240


def content_hash_of(content: str) -> str:
    """The one canonical content-hash recipe (documented, recomputable):
    SHA-256 hex over the UTF-8 bytes of the content string."""
    return sha256_hex(content.encode("utf-8"))


@dataclass(frozen=True)
class RejectedRecord:
    """One refused input record, kept for honest accounting (AGENTS.md #7):
    refusals are reported, never silently dropped."""

    source: str      # path string as given to the loader
    line: int | None  # 1-based line (jsonl/csv); None for .json records
    event_id: str    # claimed event_id if extractable, else ""
    reason: str      # stable, machine-readable refusal reason


@dataclass(frozen=True)
class InfoBundle:
    """Loaded + verified information events, plus refusal accounting."""

    events: tuple[InformationEvent, ...]
    rejected: tuple[RejectedRecord, ...]
    duplicate_count: int  # extra same-content occurrences, not loaded

    def usable(self, asof_utc: dt.datetime) -> tuple[InformationEvent, ...]:
        """Events visible at ``asof_utc``: both PIT gates passed
        (``max(available_at, received_at) <= asof``), in bundle order.

        Fail-closed: a naive ``asof`` raises instead of comparing silently
        against UTC."""
        if asof_utc.tzinfo is None or asof_utc.utcoffset() is None:
            raise ValueError("asof_utc must be timezone-aware")
        return tuple(
            e for e in self.events
            if max(e.available_at_utc, e.received_at_utc) <= asof_utc
        )


@dataclass(frozen=True)
class _RawRecord:
    """One raw input record, either parsed or carrying its own error."""

    source: str
    line: int | None
    record: dict[str, object] | None = None
    error: str | None = None


def load_info_events(paths: Sequence[Path]) -> InfoBundle:
    """Load information events from offline fixture files.

    Per-record problems (unknown/missing keys, unparsable timestamps,
    contract violations, content-hash mismatch) refuse that record into
    ``InfoBundle.rejected``. File-level breakage (unreadable file, unknown
    suffix, ``.json`` that is not an array) raises ``ValueError`` — the
    file, not a record, is broken, and silently skipping it would hide
    data loss.
    """
    if not paths:
        raise ValueError("load_info_events requires at least one path")
    events: list[InformationEvent] = []
    rejected: list[RejectedRecord] = []
    seen_hashes: set[str] = set()
    duplicates = 0
    for path in paths:
        path = Path(path)
        for raw in _read_records(path):
            if raw.error is not None:
                rejected.append(RejectedRecord(raw.source, raw.line, "", raw.error))
                continue
            record = raw.record or {}
            event_id = _claimed_event_id(record)
            reason = _refusal_reason(record)
            if reason is not None:
                rejected.append(RejectedRecord(raw.source, raw.line, event_id, reason))
                continue
            try:
                event = InformationEvent.model_validate_json(json.dumps(record))
            except ValidationError as exc:
                rejected.append(RejectedRecord(
                    raw.source, raw.line, event_id,
                    _clip("CONTRACT_INVALID:" + _brief_errors(exc))))
                continue
            digest = event.content_hash.lower()
            if digest in seen_hashes:
                duplicates += 1
                continue
            seen_hashes.add(digest)
            events.append(event)
    ordered = tuple(sorted(events, key=lambda e: (e.available_at_utc, e.event_id)))
    return InfoBundle(events=ordered, rejected=tuple(rejected),
                      duplicate_count=duplicates)


def _read_records(path: Path) -> Iterator[_RawRecord]:
    suffix = path.suffix.lower()
    if suffix not in (".jsonl", ".json", ".csv"):
        raise ValueError(
            f"unsupported information-event file type: {path} "
            "(use .jsonl / .json / .csv)")
    text = path.read_text(encoding="utf-8")
    if suffix == ".jsonl":
        yield from _read_jsonl(path, text)
    elif suffix == ".json":
        yield from _read_json_doc(path, text)
    else:
        yield from _read_csv(path, text)


def _read_jsonl(path: Path, text: str) -> Iterator[_RawRecord]:
    for line_no, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue  # blank line: not a record
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            yield _RawRecord(str(path), line_no,
                             error=_clip(f"JSON_LINE_UNPARSABLE:{exc.msg}"))
            continue
        if isinstance(obj, dict):
            yield _RawRecord(str(path), line_no, record=obj)
        else:
            yield _RawRecord(str(path), line_no, error=_clip(
                "RECORD_NOT_AN_OBJECT:" + type(obj).__name__))


def _read_json_doc(path: Path, text: str) -> Iterator[_RawRecord]:
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"information file {path} is not valid JSON: "
                         f"{exc.msg}") from exc
    if not isinstance(obj, list):
        raise ValueError(
            f"information file {path} must contain a JSON array of records")
    for item in obj:
        if isinstance(item, dict):
            yield _RawRecord(str(path), None, record=item)
        else:
            yield _RawRecord(str(path), None, error=_clip(
                "RECORD_NOT_AN_OBJECT:" + type(item).__name__))


def _read_csv(path: Path, text: str) -> Iterator[_RawRecord]:
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise ValueError(f"information file {path} has no header row")
    for row in reader:
        line_no: int | None = reader.line_num or None
        if None in row:  # extra, unnamed columns (restkey)
            yield _RawRecord(str(path), line_no, error="CSV_EXTRA_COLUMNS")
            continue
        record: dict[str, object] = dict(row)
        missing = sorted(k for k, v in record.items() if v is None)
        if missing:
            yield _RawRecord(str(path), line_no, error=_clip(
                "CSV_MISSING_COLUMNS:" + ",".join(missing)))
            continue
        yield _RawRecord(str(path), line_no, record=record)


def _refusal_reason(record: Mapping[str, object]) -> str | None:
    """Pre-contract checks with precise reasons: key set, content type,
    content-hash recomputation."""
    keys = set(record.keys())
    missing = sorted(_EVENT_KEYS - keys)
    unknown = sorted(keys - _EVENT_KEYS)
    if missing:
        return _clip("MISSING_KEYS:" + ",".join(missing))
    if unknown:
        return _clip("UNKNOWN_KEYS:" + ",".join(unknown))
    content = record["content"]
    if not isinstance(content, str):
        return _clip("CONTENT_NOT_STRING:" + type(content).__name__)
    claimed = str(record["content_hash"]).strip().lower()
    computed = content_hash_of(content)
    if claimed != computed:
        return _clip(f"CONTENT_HASH_MISMATCH:claimed={claimed},"
                     f"computed={computed}")
    return None


def _claimed_event_id(record: Mapping[str, object]) -> str:
    value = record.get("event_id")
    return str(value)[:120] if value is not None else ""


def _brief_errors(exc: ValidationError) -> str:
    parts = []
    for err in exc.errors()[:3]:
        loc = ".".join(str(p) for p in err.get("loc", ()))
        parts.append(f"{loc or '<root>'}: {err.get('msg', 'invalid')}")
    return "; ".join(parts)


def _clip(reason: str) -> str:
    return reason[:_MAX_REASON]
