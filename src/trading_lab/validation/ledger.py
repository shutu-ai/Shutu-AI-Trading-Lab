"""Experiment ledger (M3-R1-T5, v2.1 §4.2/§4.5) — append-only, hash-chained,
budget fail-closed.

Every research action that could inflate evidence — trials, queries,
failures, retries, cancels, holdout-unlock attempts — is registered with
its code/protocol/dataset hashes and seed. Rules:

- **append-only**: entries are appended to a JSONL file; there is no
  update or delete API. Each entry carries ``prev`` (the chained digest
  of the previous entry) so deletion or retro-editing of any line breaks
  the chain and is detected by ``verify_chain``.
- **budget fail-closed**: registering past a budget limit raises
  BudgetExceeded AND records the refusal (the refusal itself is billed —
  counts can never be "cleaned" by retrying).
- **monotone counters**: failures/retries/cancels bill exactly like
  successes (``failure_retry_billing: ALL_BILLED``).
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from trading_lab.security.canonical import sha256_hex

__all__ = [
    "BudgetExceeded",
    "ExperimentLedger",
    "HALTED",
]

HALTED = "HALT"


class BudgetExceeded(RuntimeError):
    """A budget limit would be exceeded — the action is refused."""


_ENTRY_KINDS = ("TRIAL", "QUERY", "FAILURE", "RETRY", "CANCEL",
                "UNLOCK_ATTEMPT", "BUDGET_REFUSAL", "HYPOTHESIS")


class ExperimentLedger:
    def __init__(self, path: Path | str, *, limits: Mapping[str, Any],
                 protocol_hash: str, code_hash: str) -> None:
        self.path = Path(path)
        self.protocol_hash = protocol_hash
        self.code_hash = code_hash
        self._limits = dict(limits)
        self._counters: dict[str, int] = {
            "trials": 0, "queries": 0, "failures": 0, "retries": 0,
            "cancels": 0, "unlock_attempts": 0, "hypotheses": 0,
        }
        self._arm_trials: dict[str, int] = {}
        self._prev: str | None = None
        self._halted = False
        self._load_existing()
        self._halt_if_needed()  # a restarted ledger resumes a prior halt
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.path, "a", encoding="utf-8")

    # ------------------------------------------------------------------
    # persistence
    # ------------------------------------------------------------------

    def _load_existing(self) -> None:
        """Replay an existing chain so counters survive process restarts
        and cannot be decremented by re-opening a fresh ledger."""
        if not self.path.exists():
            return
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            entry = json.loads(line)
            self._apply(entry)
            self._prev = entry["digest"]

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
            "detail": dict(detail),
            "counters_after": None,  # filled below when billed
            "prev": self._prev,
        }
        body = {k: v for k, v in entry.items()
                if k not in ("counters_after", "digest")}
        entry["digest"] = sha256_hex(canonical_json_entry(body))
        if billed:
            self._apply(kind, detail)
            entry["counters_after"] = dict(self._counters)
            # re-digest with counters so any counter edit breaks the chain
            body2 = {k: v for k, v in entry.items()
                     if k != "digest"}
            entry["digest"] = sha256_hex(canonical_json_entry(body2))
        self._fh.write(json.dumps(entry, sort_keys=True,
                                  default=_json_default) + "\n")
        self._fh.flush()
        self._prev = entry["digest"]
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

    def verify_chain(self) -> tuple[bool, str]:
        """Recompute the chained digests over the file; any deletion,
        reordering or edit of a historical line breaks the chain."""
        if not self.path.exists():
            return (False, "ledger file missing")
        prev: str | None = None
        n = 0
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            entry = json.loads(line)
            if entry.get("prev") != prev:
                return (False, f"chain break at entry #{n + 1} "
                               "(deleted or edited history)")
            body = {k: v for k, v in entry.items() if k != "digest"}
            if sha256_hex(canonical_json_entry(body)) != entry["digest"]:
                return (False, f"digest mismatch at entry #{n + 1}")
            prev = entry["digest"]
            n += 1
        return (True, f"{n} entries verified")

    def close(self) -> None:
        self._fh.close()


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
