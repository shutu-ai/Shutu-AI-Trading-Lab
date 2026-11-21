"""Sealed Holdout gate (M3-R1-T5, v2.1 §4.5).

The one-shot M9 instrument. In M3 the real holdout is
``SEALED_NOT_MATERIALIZED`` (real data is BLOCKED_DATA): this module
implements the ACCESS CONTROL STATE MACHINE over synthetic fixtures so
the behavior is testable before any real sample exists.

Roles:
- RESEARCH: no direct read, no statistical aggregation, no query
  differencing, no repeated probing — every attempt is refused AND
  audited.
- GOVERNANCE: may unlock ONCE (M9, by pre-registered rule) — the first
  unlock emits an immutable HoldoutAccess event and sets
  ``polluted_for_future_selection = True``; a second unlock and any
  subsequent champion selection are refused unconditionally.
- AUDITOR: may read the audit trail and the sealing manifest, never the
  samples.

Honest boundary (recorded, not hidden): this is an application-level
permission simulation in-process. It is NOT an OS-level sandbox; hard
isolation of the eventual real holdout (separate process, separate
credentials, read-only storage) belongs to M4.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Sequence

__all__ = [
    "HoldoutError",
    "HoldoutRole",
    "SealedHoldout",
    "VERDICT_STATES",
]

VERDICT_STATES = ("PASS", "FAILED", "INCONCLUSIVE", "INVALIDATED")


class HoldoutError(PermissionError):
    """A refused holdout access/operation — always audited by the vault."""


@dataclass(frozen=True)
class HoldoutRole:
    RESEARCH = "RESEARCH"
    GOVERNANCE = "GOVERNANCE"
    AUDITOR = "AUDITOR"


@dataclass
class _AuditEntry:
    ts: dt.datetime
    actor: str
    role: str
    action: str
    allowed: bool
    detail: str


@dataclass
class SealedHoldout:
    """State machine: SEALED -> (M9 single unlock) -> verdict, then dead."""

    holdout_id: str
    sealing_manifest_hash: str     # digest of the pre-registered manifest
    created_at: dt.datetime
    max_unlocks: int = 1
    status: str = field(default="SEALED", init=False)
    polluted_for_future_selection: bool = field(default=False, init=False)
    unlock_count: int = field(default=0, init=False)
    final_holdout_status: str = field(default="SEALED", init=False)
    audit: list[_AuditEntry] = field(default_factory=list, init=False)

    # ------------------------------------------------------------------
    # role-guarded operations
    # ------------------------------------------------------------------

    def _log(self, actor: str, role: str, action: str, allowed: bool,
             detail: str, ts: dt.datetime) -> None:
        self.audit.append(_AuditEntry(ts=ts, actor=actor, role=role,
                                      action=action, allowed=allowed,
                                      detail=detail))

    def read_samples(self, actor: str, role: str, *, now: dt.datetime) -> str:
        self._log(actor, role, "READ_SAMPLES", False, "refused", now)
        raise HoldoutError(
            "direct sample access is refused for every role through this "
            "gate; only the independent governance unlock evaluates it")

    def aggregate(self, actor: str, role: str, *, now: dt.datetime) -> str:
        self._log(actor, role, "AGGREGATE", False, "refused", now)
        raise HoldoutError(
            "statistical aggregation over holdout samples is refused")

    def query_difference(self, actor: str, role: str, probe: str, *,
                         now: dt.datetime) -> str:
        self._log(actor, role, "QUERY_DIFFERENCE", False,
                  f"probe={probe!r}", now)
        raise HoldoutError(
            "query differencing (membership/interval probes) is refused")

    def probe_repeatedly(self, actor: str, role: str, count: int, *,
                         now: dt.datetime) -> int:
        """Simulated repeated probing: every probe refused and audited."""
        for _ in range(count):
            self._log(actor, role, "PROBE", False, "refused", now)
        raise HoldoutError(
            f"{count} repeated probes all refused (reconnaissance denied)")

    def read_manifest(self, actor: str, role: str, *,
                      now: dt.datetime) -> str:
        if role != HoldoutRole.AUDITOR:
            self._log(actor, role, "READ_MANIFEST", False,
                      "role lacks auditor clearance", now)
            raise HoldoutError("manifest read requires AUDITOR role")
        self._log(actor, role, "READ_MANIFEST", True, "ok", now)
        return self.sealing_manifest_hash

    def read_audit(self, actor: str, role: str, *,
                   now: dt.datetime) -> Sequence[_AuditEntry]:
        if role not in (HoldoutRole.AUDITOR, HoldoutRole.GOVERNANCE):
            self._log(actor, role, "READ_AUDIT", False, "refused", now)
            raise HoldoutError("audit read requires AUDITOR/GOVERNANCE role")
        self._log(actor, role, "READ_AUDIT", True, "ok", now)
        return tuple(self.audit)

    # ------------------------------------------------------------------
    # the one-shot unlock (M9 only)
    # ------------------------------------------------------------------

    def unlock(self, actor: str, role: str, *, now: dt.datetime,
               unlock_note: str) -> str:
        if role != HoldoutRole.GOVERNANCE:
            self._log(actor, role, "UNLOCK", False,
                      "role lacks governance clearance", now)
            raise HoldoutError("unlock requires GOVERNANCE role")
        if self.status != "SEALED":
            self._log(actor, role, "UNLOCK", False,
                      f"status={self.status}; holdout already "
                      f"unlocked {self.unlock_count}x", now)
            raise HoldoutError(
                "second unlock refused — the holdout is polluted for "
                "future selection after its single unlock")
        if self.unlock_count + 1 > self.max_unlocks:
            self._log(actor, role, "UNLOCK", False, "max_unlocks exceeded",
                      now)
            raise HoldoutError("max_unlocks exceeded — fail closed")
        self.unlock_count += 1
        self.status = "UNLOCKED"
        self.polluted_for_future_selection = True
        self._log(actor, role, "UNLOCK", True, unlock_note, now)
        self._log("system", "SYSTEM", "HOLDOUT_ACCESS_EVENT", True,
                  f"unlock#{self.unlock_count}; "
                  "polluted_for_future_selection=true", now)
        return f"HOLDOUT_ACCESS_EVENT#{self.unlock_count}"

    def record_verdict(self, actor: str, role: str, verdict: str, *,
                       now: dt.datetime) -> str:
        if role != HoldoutRole.GOVERNANCE:
            self._log(actor, role, "RECORD_VERDICT", False, "role refused",
                      now)
            raise HoldoutError("verdict requires GOVERNANCE role")
        if self.status != "UNLOCKED":
            self._log(actor, role, "RECORD_VERDICT", False,
                      f"status={self.status}", now)
            raise HoldoutError(
                "verdict requires the single pre-registered unlock")
        if verdict not in VERDICT_STATES:
            self._log(actor, role, "RECORD_VERDICT", False,
                      f"unknown verdict {verdict}", now)
            raise HoldoutError(
                f"verdict must be one of {VERDICT_STATES}")
        self.final_holdout_status = verdict
        self.status = "CONSUMED"
        self._log(actor, role, "RECORD_VERDICT", True, verdict, now)
        return verdict

    def select_champion(self, actor: str, role: str, *, now: dt.datetime) -> str:
        """Any champion selection referencing this holdout: legal only
        pre-unlock is impossible by design (selection never sees the
        holdout), and after unlock it is unconditionally refused."""
        self._log(actor, role, "SELECT_CHAMPION", False,
                  "holdout may never inform champion selection", now)
        raise HoldoutError(
            "champion selection via the holdout is refused unconditionally "
            "(pre-registered rule selects the candidate WITHOUT it)")

    # ------------------------------------------------------------------
    # manifest
    # ------------------------------------------------------------------

    def manifest_digest(self) -> str:
        """The pre-registered sealing manifest hash (auditor-readable)."""
        return self.sealing_manifest_hash
