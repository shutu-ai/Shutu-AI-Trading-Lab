"""Experiment ledger (M3-R1-T5, hardened in M3-R2-T3; v2.1 §4.2/§4.5) —
append-only, hash-chained, budget fail-closed, verify-before-replay,
single-writer, externally anchorable.

Every research action that could inflate evidence — trials, queries,
failures, retries, cancels, holdout-unlock attempts — is registered with
its code/protocol/dataset hashes and seed. Rules:

- **append-only**: entries are appended to a JSONL file; there is no
  update or delete API. Each entry carries ``prev`` (the chained digest
  of the previous entry) so deletion or retro-editing of any line breaks
  the chain and is detected by ``verify_chain``/``verify_ledger_file``.
- **verify BEFORE replay (R2-P1-2)**: opening an existing ledger parses
  and verifies the whole chain (well-formed lines, prev pointers,
  digests, protocol/code/batch identity binding, ``counters_after`` vs
  replayed counters) BEFORE any counter is applied and BEFORE the ledger
  becomes writable. A tampered, truncated, identity-mismatched or
  counter-lying file is a LedgerIntegrityError — research can never
  continue on top of unverified history, and counts can never be
  resurrected by retrying.
- **budget fail-closed**: registering past a budget limit raises
  BudgetExceeded AND records the refusal (the refusal itself is billed —
  counts can never be "cleaned" by retrying).
- **monotone counters**: failures/retries/cancels bill exactly like
  successes (``failure_retry_billing: ALL_BILLED``).
- **single writer**: construction takes an exclusive lock file
  (``<ledger>.lock``, O_CREAT|O_EXCL). A second writer — same process or
  another process — is refused (LedgerLockedError) instead of two appends
  racing against the same ``prev``. A crash without ``close()`` leaves
  the lock in place BY DESIGN: every subsequent open refuses until an
  operator removes the stale lock after forensic review.
- **external anchor (honest capability boundary)**: the hash chain alone
  detects retained-head-and-tail middle deletion/edits ONLY. Tail
  truncation, whole-file replacement and full clearing are NOT detectable
  from the file alone — a re-chained or shortened chain can be perfectly
  self-consistent. Detection requires an externally stored
  ``LedgerAnchor`` (head/tail digest + entry count + protocol/code/batch
  identity) produced by ``export_anchor``/``read_ledger_anchor`` and kept
  OUTSIDE the ledger file (separate committed evidence record); opening
  with ``anchor=`` compares it before continuing. The anchor is trusted
  exactly as much as its storage location: an attacker who can rewrite
  both the ledger AND the anchor store defeats the scheme — no JSONL
  file, anchored or not, is tamper-proof or non-repudiable in the
  cryptographic-signature sense, and this module never claims otherwise.
- **batch binding**: a ledger file belongs to ONE batch identity
  (``batch_id`` + protocol/code hashes). Legitimate protocol version
  migration is a NEW file whose first entry is an explicit BATCH_INIT
  referencing its predecessor — never a silent identity switch mid-file.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import os
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from trading_lab.security.canonical import sha256_hex

__all__ = [
    "ANCHOR_SCHEMA",
    "BudgetExceeded",
    "ExperimentLedger",
    "HALTED",
    "LedgerAnchor",
    "LedgerIntegrityError",
    "LedgerLockedError",
    "read_ledger_anchor",
    "verify_ledger_file",
]

HALTED = "HALT"

ANCHOR_SCHEMA = "experiment-ledger-anchor-v1"


class BudgetExceeded(RuntimeError):
    """A budget limit would be exceeded — the action is refused."""


class LedgerIntegrityError(RuntimeError):
    """The ledger file failed verification — research is refused (fail
    closed); never load, count or append on top of unverified history."""


class LedgerLockedError(RuntimeError):
    """Another writer holds this ledger — refused (single-writer rule)."""


_ENTRY_KINDS = ("TRIAL", "QUERY", "FAILURE", "RETRY", "CANCEL",
                "UNLOCK_ATTEMPT", "BUDGET_REFUSAL", "HYPOTHESIS",
                "BATCH_INIT")


@dataclasses.dataclass(frozen=True)
class LedgerAnchor:
    """External integrity anchor for one ledger state. Store it OUTSIDE
    the ledger file (separate committed record); its trust equals its
    storage — see module docstring for the honest boundary."""

    schema: str
    entry_count: int
    head_digest: str | None
    tail_digest: str | None
    protocol_hash: str
    code_hash: str
    batch_id: str | None
    created_ts: str


def _now_utc_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace(
        "+00:00", "Z")


def _parse_entries(path: Path) -> list[dict[str, Any]]:
    """Read every well-formed entry; malformed/incomplete JSON fails
    closed (a crash-truncated write is never silently dropped)."""
    entries: list[dict[str, Any]] = []
    for lineno, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            raise LedgerIntegrityError(
                f"malformed/incomplete JSON at line {lineno} "
                f"(possible crash-truncated write): {exc.msg}") from None
        if not isinstance(entry, dict) or "digest" not in entry \
                or "prev" not in entry:
            raise LedgerIntegrityError(
                f"non-entry content at line {lineno} of {path.name}")
        entries.append(entry)
    return entries


def _verify_entries(entries: list[dict[str, Any]]) -> tuple[bool, str]:
    """Chain integrity over already-parsed entries: prev pointers and
    digests of the retained lines. Middle deletion/edits (head and tail
    retained) are detected; tail truncation/replacement/clearing are NOT
    (they need an external anchor — see module docstring)."""
    prev: str | None = None
    n = 0
    for entry in entries:
        if entry.get("prev") != prev:
            return (False, f"chain break at entry #{n + 1} "
                           "(deleted or edited history)")
        body = {k: v for k, v in entry.items() if k != "digest"}
        if sha256_hex(canonical_json_entry(body)) != entry["digest"]:
            return (False, f"digest mismatch at entry #{n + 1}")
        prev = entry["digest"]
        n += 1
    return (True, f"{n} entries verified")


def verify_ledger_file(path: Path | str) -> tuple[bool, str]:
    """Standalone verification of a ledger file (no lock, no counters):
    well-formedness + chain. This is the plain-chain view — use a real
    anchor for tail-truncation coverage."""
    p = Path(path)
    if not p.exists():
        return (False, "ledger file missing")
    try:
        entries = _parse_entries(p)
    except LedgerIntegrityError as exc:
        return (False, str(exc))
    return _verify_entries(entries)


def read_ledger_anchor(path: Path | str) -> LedgerAnchor:
    """Anchor the CURRENT state of a (verified) ledger file, for external
    storage. Refuses broken or empty files — an anchor over unverified
    content is meaningless."""
    p = Path(path)
    if not p.exists():
        raise LedgerIntegrityError(f"cannot anchor a missing file: {p}")
    entries = _parse_entries(p)
    ok, msg = _verify_entries(entries)
    if not ok:
        raise LedgerIntegrityError(f"cannot anchor a broken ledger: {msg}")
    if not entries:
        raise LedgerIntegrityError("cannot anchor an empty ledger")
    first = entries[0]
    return LedgerAnchor(
        schema=ANCHOR_SCHEMA, entry_count=len(entries),
        head_digest=entries[0]["digest"], tail_digest=entries[-1]["digest"],
        protocol_hash=str(first.get("protocol_hash", "")),
        code_hash=str(first.get("code_hash", "")),
        batch_id=first.get("batch_id"), created_ts=_now_utc_iso())


class ExperimentLedger:
    def __init__(self, path: Path | str, *, limits: Mapping[str, Any],
                 protocol_hash: str, code_hash: str,
                 batch_id: str | None = None,
                 anchor: LedgerAnchor | None = None) -> None:
        self.path = Path(path)
        self.protocol_hash = protocol_hash
        self.code_hash = code_hash
        self.batch_id = batch_id
        self._limits = dict(limits)
        self._counters: dict[str, int] = {
            "trials": 0, "queries": 0, "failures": 0, "retries": 0,
            "cancels": 0, "unlock_attempts": 0, "hypotheses": 0,
        }
        self._arm_trials: dict[str, int] = {}
        self._prev: str | None = None
        self._head: str | None = None
        self._entry_count = 0
        self._halted = False
        self._closed = False
        self._lock_path = Path(str(self.path) + ".lock")
        self._acquire_lock()
        try:
            self._verify_and_replay(anchor)
        except BaseException:
            self._closed = True  # half-built; nothing further to release
            self._release_lock()
            raise
        self._halt_if_needed()  # a restarted ledger resumes a prior halt
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.path, "a", encoding="utf-8")

    # ------------------------------------------------------------------
    # single-writer lock
    # ------------------------------------------------------------------

    def _acquire_lock(self) -> None:
        try:
            fd = os.open(str(self._lock_path),
                         os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            raise LedgerLockedError(
                f"ledger {self.path} is locked by another writer "
                f"({self._lock_path.name}) — the single-writer rule "
                "refuses a second concurrent writer; if no writer process "
                "is alive, remove the stale lock only after forensic "
                "review and record an audit note") from None
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"pid": os.getpid(), "ts": _now_utc_iso()}))

    def _release_lock(self) -> None:
        try:
            os.unlink(self._lock_path)
        except FileNotFoundError:
            pass

    # ------------------------------------------------------------------
    # verify BEFORE replay
    # ------------------------------------------------------------------

    def _verify_and_replay(self, anchor: LedgerAnchor | None) -> None:
        entries = (_parse_entries(self.path)
                   if self.path.exists() else [])
        ok, msg = _verify_entries(entries)
        if not ok:
            raise LedgerIntegrityError(
                f"refusing to load ledger {self.path.name}: {msg}")
        # identity binding: one file is one batch under one identity
        for entry in entries:
            if entry.get("protocol_hash") != self.protocol_hash \
                    or entry.get("code_hash") != self.code_hash:
                raise LedgerIntegrityError(
                    f"refusing to load ledger {self.path.name}: recorded "
                    "protocol/code hash differs from the identity this "
                    "ledger is opened under (mismatch) — start a NEW "
                    "batch file for a new protocol/code version")
            entry_batch = entry.get("batch_id")
            if entry_batch != self.batch_id:
                raise LedgerIntegrityError(
                    f"refusing to load ledger {self.path.name}: batch "
                    f"mismatch (entry batch {entry_batch!r} vs opened "
                    f"{self.batch_id!r}) — a legitimate version migration "
                    "is a new file with an explicit BATCH_INIT")
        # replay counters, cross-checking each entry's claimed snapshot
        for entry in entries:
            self._apply(entry)
            self._prev = entry["digest"]
            if self._head is None:
                self._head = entry["digest"]
            self._entry_count += 1
            claimed = entry.get("counters_after")
            if claimed is not None \
                    and dict(claimed) != dict(self._counters):
                raise LedgerIntegrityError(
                    f"refusing to load ledger {self.path.name}: "
                    f"counters_after inconsistent with replay at entry "
                    f"#{self._entry_count} ({claimed} vs "
                    f"{dict(self._counters)})")
        if anchor is not None:
            self._check_anchor(anchor, entries)

    def _check_anchor(self, anchor: LedgerAnchor,
                      entries: list[dict[str, Any]]) -> None:
        if anchor.protocol_hash != self.protocol_hash \
                or anchor.code_hash != self.code_hash \
                or (anchor.batch_id or None) != (self.batch_id or None):
            raise LedgerIntegrityError(
                f"refusing to load ledger {self.path.name}: external "
                "anchor identity mismatch — the anchor belongs to a "
                "different ledger")
        if anchor.entry_count != len(entries):
            raise LedgerIntegrityError(
                f"refusing to load ledger {self.path.name}: external "
                f"anchor mismatch — anchor records {anchor.entry_count} "
                f"entries, file has {len(entries)}; possible tail "
                "truncation, whole-file replacement or clearing")
        head = entries[0]["digest"] if entries else None
        tail = entries[-1]["digest"] if entries else None
        if anchor.head_digest != head or anchor.tail_digest != tail:
            raise LedgerIntegrityError(
                f"refusing to load ledger {self.path.name}: external "
                "anchor mismatch — head/tail digest differs from the "
                "anchored state; possible tail truncation or history "
                "replacement")

    # ------------------------------------------------------------------
    # persistence
    # ------------------------------------------------------------------

    def _append(self, kind: str, detail: Mapping[str, Any], *,
                billed: bool = True) -> dict[str, Any]:
        if kind not in _ENTRY_KINDS:
            raise ValueError(f"unknown ledger entry kind {kind}")
        if self._halted and kind not in ("BUDGET_REFUSAL",):
            raise BudgetExceeded(
                "ledger is HALTED (max_failures_before_halt exceeded); "
                "new research actions are frozen")
        entry: dict[str, Any] = {
            "ts": dt.datetime.now(dt.timezone.utc),
            "kind": kind,
            "protocol_hash": self.protocol_hash,
            "code_hash": self.code_hash,
            "batch_id": self.batch_id,
            "detail": dict(detail),
            "counters_after": None,  # filled below
            "prev": self._prev,
        }
        if billed:
            self._apply(kind, detail)
        entry["counters_after"] = dict(self._counters)
        # digest covers everything (counters included) so any counter
        # edit breaks the chain
        body = {k: v for k, v in entry.items() if k != "digest"}
        entry["digest"] = sha256_hex(canonical_json_entry(body))
        self._fh.write(json.dumps(entry, sort_keys=True,
                                  default=_json_default) + "\n")
        self._fh.flush()
        self._prev = entry["digest"]
        if self._head is None:
            self._head = entry["digest"]
        self._entry_count += 1
        return entry

    def _apply(self, kind_or_entry: Any, detail: Mapping[str, Any] | None = None) -> None:
        """Update in-memory counters from a kind/detail pair or a replayed
        entry (counters derived from detail fields are authoritative)."""
        if isinstance(kind_or_entry, dict):
            entry = kind_or_entry
            kind, detail = entry["kind"], entry.get("detail", {})
        else:
            kind, detail = kind_or_entry, (detail or {})
        if kind == "TRIAL":
            self._counters["trials"] += 1
            arm = detail.get("arm")
            if arm:
                self._arm_trials[arm] = self._arm_trials.get(arm, 0) + 1
        elif kind == "QUERY":
            self._counters["queries"] += 1
        elif kind == "FAILURE":
            self._counters["failures"] += 1
            arm = detail.get("arm")
            if arm:
                self._arm_trials[arm] = self._arm_trials.get(arm, 0) + 1
        elif kind == "RETRY":
            self._counters["retries"] += 1
            arm = detail.get("arm")
            if arm:
                self._arm_trials[arm] = self._arm_trials.get(arm, 0) + 1
        elif kind == "CANCEL":
            self._counters["cancels"] += 1
        elif kind == "UNLOCK_ATTEMPT":
            self._counters["unlock_attempts"] += 1
        elif kind == "HYPOTHESIS":
            self._counters["hypotheses"] += 1
        elif kind == "BATCH_INIT":
            pass  # registration record, not billed research action

    # ------------------------------------------------------------------
    # budget enforcement (fail closed)
    # ------------------------------------------------------------------

    def _check_budget(self, kind: str, arm: str | None) -> None:
        limits = MappingProxyType(self._limits)
        if kind in ("TRIAL", "FAILURE", "RETRY"):
            if self._counters["trials"] + 1 > limits["max_total_trials"]:
                raise BudgetExceeded(
                    f"max_total_trials={limits['max_total_trials']} would "
                    "be exceeded — refused and billed as BUDGET_REFUSAL")
            if self._counters["failures"] + 1 > \
                    limits["max_failures_before_halt"]:
                raise BudgetExceeded(
                    f"max_failures_before_halt="
                    f"{limits['max_failures_before_halt']} exceeded — "
                    "research is frozen (HALT)")
        if kind == "QUERY" and \
                self._counters["queries"] + 1 > limits["max_search_queries"]:
            raise BudgetExceeded(
                f"max_search_queries={limits['max_search_queries']} would "
                "be exceeded — refused")
        if kind == "HYPOTHESIS" and \
                self._counters["hypotheses"] + 1 > limits["max_hypotheses"]:
            raise BudgetExceeded(
                f"max_hypotheses={limits['max_hypotheses']} exceeded")
        if arm is not None:
            per_arm = limits.get("per_arm_trials") or {}
            budget = per_arm.get(arm)
            if budget is not None and \
                    self._arm_trials.get(arm, 0) + 1 > budget:
                raise BudgetExceeded(
                    f"arm {arm} exhausted its per-arm trial budget "
                    f"({budget}) — equal-trial fairness is fail-closed")

    def _halt_if_needed(self) -> None:
        limit = self._limits.get("max_failures_before_halt")
        if limit is not None and self._counters["failures"] >= limit:
            self._halted = True

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def register_trial(self, arm: str, *, seed: int, dataset_hash: str,
                       note: str = "") -> dict[str, Any]:
        return self._billed("TRIAL", arm, seed=seed,
                            dataset_hash=dataset_hash, note=note)

    def register_query(self, *, note: str = "") -> dict[str, Any]:
        return self._billed("QUERY", None, note=note)

    def register_failure(self, arm: str, *, seed: int,
                         dataset_hash: str, error: str) -> dict[str, Any]:
        return self._billed("FAILURE", arm, seed=seed,
                            dataset_hash=dataset_hash, error=error)

    def register_retry(self, arm: str, *, seed: int,
                       dataset_hash: str, note: str = "") -> dict[str, Any]:
        return self._billed("RETRY", arm, seed=seed,
                            dataset_hash=dataset_hash, note=note)

    def register_cancel(self, *, note: str = "") -> dict[str, Any]:
        return self._billed("CANCEL", None, note=note)

    def register_unlock_attempt(self, *, actor: str, allowed: bool) -> dict[str, Any]:
        return self._billed("UNLOCK_ATTEMPT", None, actor=actor,
                            allowed=allowed)

    def register_hypothesis(self, *, hypothesis_id: str) -> dict[str, Any]:
        return self._billed("HYPOTHESIS", None, hypothesis_id=hypothesis_id)

    def register_batch_init(self, batch_id: str, **detail: Any) -> dict[str, Any]:
        """First entry of a FRESH ledger: registers the batch identity and
        its lineage (e.g. the predecessor batch's hashes and consumption).
        Illegal on an existing file — version migration means a new file."""
        if batch_id != self.batch_id:
            raise LedgerIntegrityError(
                f"register_batch_init({batch_id!r}) does not match the "
                f"opened batch {self.batch_id!r}")
        non_empty = self._entry_count > 0 or (
            self.path.exists() and self.path.stat().st_size > 0)
        if non_empty:
            raise LedgerIntegrityError(
                "BATCH_INIT is only legal as the first entry of a fresh "
                "ledger file")
        return self._append("BATCH_INIT", dict(detail), billed=False)

    def _billed(self, kind: str, arm: str | None, **detail: Any) -> dict[str, Any]:
        try:
            self._check_budget(kind, arm)
        except BudgetExceeded:
            self._append("BUDGET_REFUSAL",
                         {"refused_kind": kind, "arm": arm, **detail})
            raise
        entry = self._append(kind, {"arm": arm, **detail})
        self._halt_if_needed()
        return entry

    # ------------------------------------------------------------------
    # inspection + integrity
    # ------------------------------------------------------------------

    def counters(self) -> Mapping[str, int]:
        return MappingProxyType(dict(self._counters))

    def arm_trials(self) -> Mapping[str, int]:
        return MappingProxyType(dict(self._arm_trials))

    @property
    def halted(self) -> bool:
        return self._halted

    def export_anchor(self) -> LedgerAnchor:
        """Anchor the current in-memory state for EXTERNAL storage (a
        committed evidence record separate from this file)."""
        return LedgerAnchor(
            schema=ANCHOR_SCHEMA, entry_count=self._entry_count,
            head_digest=self._head, tail_digest=self._prev,
            protocol_hash=self.protocol_hash, code_hash=self.code_hash,
            batch_id=self.batch_id, created_ts=_now_utc_iso())

    def verify_chain(self) -> tuple[bool, str]:
        """Recompute the chained digests over the file; any deletion,
        reordering or edit of a historical line breaks the chain. (Plain
        chain view: tail truncation needs an external anchor.)"""
        if not self.path.exists():
            return (False, "ledger file missing")
        try:
            entries = _parse_entries(self.path)
        except LedgerIntegrityError as exc:
            return (False, str(exc))
        return _verify_entries(entries)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._fh.close()
        self._release_lock()

    def __del__(self) -> None:  # best-effort; os._exit skips this by design
        try:
            if not getattr(self, "_closed", True):
                self.close()
        except Exception:
            pass


def _json_default(obj: Any) -> Any:
    if isinstance(obj, dt.datetime):
        return obj.isoformat().replace("+00:00", "Z")
    raise TypeError(f"cannot serialize {type(obj)!r}")


def canonical_json_entry(payload: Any) -> bytes:
    """Ledger-local canonicalization for the digest chain: sorted keys,
    compact separators, datetimes as UTC Z strings. (The ledger digest is
    an internal integrity chain, not a signed contract payload — the
    protocol hash itself still uses security.canonical.)"""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False,
                      default=_json_default).encode("utf-8")
