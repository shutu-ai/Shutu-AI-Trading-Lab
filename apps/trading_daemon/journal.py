"""Forward journal — the durable forward-event state store.

Backbone: :class:`trading_lab.security.audit.AuditLog` (append-only
JSONL, hash chain, ``.head`` record detecting tail truncation, built-in
``verify()``). This module adds ONLY the forward semantics:

- a slot state machine rebuilt from the chain on every open
  (LOCKED -> OBSERVED -> SCORED, or LOCKED -> EXPIRED);
- an EVENT_CONSUMED record per consumed event, from which the rebuilt
  duplicate index, PIT close series and per-source frontiers are derived
  (the chain is the single source of truth for restarts);
- an external anchor file (``journal-anchor.json``, mirroring the M3
  ledger-anchor pattern) that detects whole-file replacement — the one
  hole an in-file chain cannot close;
- fail-closed consistency rules: an observation without a matching
  locked prediction, a scored slot without an observation, or a double
  score is an integrity error on the next open, never a silent repair.

Why this is not ExperimentLedger: the ledger is the research-batch
instrument (budget counters, arm registrations). The forward journal is
the operational event store for the daemon's own recovery; it copies no
budget semantics, and it reuses (not reimplements) the audit chain.
"""

from __future__ import annotations

import datetime as dt
import json
from collections import Counter
from decimal import Decimal
from pathlib import Path
from typing import Any

from trading_lab.security.audit import AuditLog

ANCHOR_NAME = "journal-anchor.json"
ANCHOR_SCHEMA = "forward-journal-anchor-v1"

__all__ = [
    "ANCHOR_NAME",
    "ForwardJournal",
    "ForwardState",
    "JournalIntegrityError",
    "read_entries",
    "verify_journal_file",
]


class JournalIntegrityError(RuntimeError):
    """The journal cannot be trusted — refuse to run, never repair."""


def read_entries(path: Path | str) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        return []
    out: list[dict[str, Any]] = []
    with p.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def verify_journal_file(path: Path | str) -> tuple[bool, str]:
    """Chain + head verification of a journal file (no state rebuild)."""
    p = Path(path)
    if not p.exists():
        return False, "journal file missing"
    return _verify_with_head(p)


def _verify_with_head(p: Path) -> tuple[bool, str]:
    try:
        log = AuditLog(p, environment_tag="SYNTHETIC_REPLAY")
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        return False, f"journal unreadable: {exc}"
    ok, first_bad = log.verify()
    if not ok:
        return False, (
            f"chain/head mismatch at entry {first_bad} — history was "
            "edited or truncated (the head record protects the tail)")
    return True, f"{log._seq} entries verified"


class ForwardState:
    """Rebuilt-from-chain forward state."""

    def __init__(self) -> None:
        self.slots: dict[str, dict[str, Any]] = {}
        self.events: dict[str, dict[str, Any]] = {}
        # PIT close series in chain (processing) order
        self.consumed_closes: list[tuple[dt.datetime, Decimal]] = []
        self.source_frontier: dict[str, dt.datetime] = {}
        self.counters: Counter[str] = Counter()
        self.sessions: int = 0
        self.last_status: dict[str, Any] = {}

    @property
    def open_slot(self) -> dict[str, Any] | None:
        for slot in self.slots.values():
            if slot["stage"] == "LOCKED":
                return slot
        return None


class ForwardJournal:
    @classmethod
    def open(cls, path: Path | str, prereg=None) -> "ForwardJournal":
        """Open (or create) a journal, verifying chain, head record and
        external anchor before any use — fail closed."""
        return cls(path, prereg=prereg)

    def __init__(self, path: Path | str, prereg=None) -> None:
        self._path = Path(path)
        self._anchor_path = self._path.parent / ANCHOR_NAME
        self._log = AuditLog(self._path, environment_tag="SYNTHETIC_REPLAY")
        ok, msg = self.verify()
        if not ok:
            raise JournalIntegrityError(f"journal failed verification: {msg}")
        self.state = self._rebuild()
        self._check_anchor()

    # -- audit surface -------------------------------------------------------

    def append(self, event_type: str, payload: dict[str, Any]) -> dict:
        return self._log.append(event_type, payload)

    def verify(self) -> tuple[bool, str]:
        return _verify_with_head(self._path)

    @property
    def path(self) -> Path:
        return self._path

    # -- rebuild -------------------------------------------------------------

    def _rebuild(self) -> ForwardState:
        state = ForwardState()
        for entry in read_entries(self._path):
            kind = entry.get("event_type", "")
            payload = entry.get("payload", {}) or {}
            state.counters[kind] += 1
            if kind == "SESSION_STARTED":
                state.sessions += 1
            elif kind == "EVENT_CONSUMED":
                state.events[payload["event_id"]] = {
                    "digest": payload["payload_digest"],
                    "stage": "CONSUMED"}
                state.consumed_closes.append((
                    dt.datetime.fromisoformat(payload["ts_available"]),
                    Decimal(payload["close"])))
                prev = state.source_frontier.get(payload["source"])
                ts_event = dt.datetime.fromisoformat(payload["ts_event"])
                state.source_frontier[payload["source"]] = (
                    ts_event if prev is None else max(prev, ts_event))
            elif kind == "PREDICTION_LOCKED":
                slot_id = payload.get("slot_id", "")
                if slot_id in state.slots:
                    raise JournalIntegrityError(
                        f"slot {slot_id} locked twice in chain history")
                state.slots[slot_id] = {
                    "stage": "LOCKED", "prediction": payload,
                    "seq": entry["seq"]}
            elif kind == "OBSERVATION_RECEIVED":
                slot = state.slots.get(payload.get("slot_id", ""))
                if slot is None:
                    raise JournalIntegrityError(
                        f"observation for unknown/never-locked slot "
                        f"{payload.get('slot_id')!r} — hindsight guard")
                if slot["stage"] != "LOCKED":
                    raise JournalIntegrityError(
                        f"slot {payload.get('slot_id')!r} observed at "
                        f"stage {slot['stage']}")
                slot["stage"] = "OBSERVED"
                slot["observation"] = payload
            elif kind == "SCORED":
                slot = state.slots.get(payload.get("slot_id", ""))
                if slot is None or slot["stage"] != "OBSERVED":
                    raise JournalIntegrityError(
                        f"score for slot {payload.get('slot_id')!r} without "
                        "a stored observation")
                slot["stage"] = "SCORED"
                slot["score"] = payload
            elif kind == "EXPIRED":
                slot = state.slots.get(payload.get("slot_id", ""))
                if slot is None or slot["stage"] != "LOCKED":
                    raise JournalIntegrityError(
                        f"expiry for slot {payload.get('slot_id')!r} at "
                        f"stage {slot['stage'] if slot else 'missing'}")
                slot["stage"] = "EXPIRED"
                slot["expired_reason"] = payload.get("reason", "")
        return state

    # -- external anchor -------------------------------------------------------

    def write_anchor(self, session_id: str) -> dict[str, Any]:
        entries = read_entries(self._path)
        if not entries:
            raise JournalIntegrityError("cannot anchor an empty journal")
        ok, msg = self.verify()
        if not ok:
            raise JournalIntegrityError(f"cannot anchor broken journal: {msg}")
        anchor = {
            "schema": ANCHOR_SCHEMA,
            "session_id": session_id,
            "entry_count": len(entries),
            "head_digest": entries[0]["event_hash"],
            "tail_digest": entries[-1]["event_hash"],
        }
        self._anchor_path.write_text(
            json.dumps(anchor, indent=2, sort_keys=True), encoding="utf-8")
        return anchor

    def _check_anchor(self) -> None:
        if not self._anchor_path.exists():
            return
        anchor = json.loads(
            self._anchor_path.read_text(encoding="utf-8"))
        entries = read_entries(self._path)
        if not entries:
            raise JournalIntegrityError(
                "journal is empty but an anchor exists — the file was "
                "cleared or replaced")
        if len(entries) < int(anchor["entry_count"]):
            raise JournalIntegrityError(
                f"journal holds {len(entries)} entries but the external "
                f"anchor recorded {anchor['entry_count']} — tail truncation")
        if entries[0]["event_hash"] != anchor["head_digest"]:
            raise JournalIntegrityError(
                "journal head digest differs from the external anchor — "
                "the file was replaced wholesale")
        if len(entries) == int(anchor["entry_count"]) and \
                entries[-1]["event_hash"] != anchor["tail_digest"]:
            raise JournalIntegrityError(
                "journal tail digest differs from the external anchor — "
                "the tail was rewritten")
