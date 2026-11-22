"""Single-writer session lease lock (daemon scope).

Deliberately NOT ``oms.fence.FenceCoordinator``: the fence binds to
``Environment ∈ {PAPER, LIVE}`` (broker environments); the synthetic
daemon must never borrow those labels — forcing PAPER would falsify the
``account_environment`` evidence field. This is a minimal lease-file
primitive:

- held, unexpired lock -> ``LockHeldError`` (conservative refusal);
- expired lease -> takeover allowed, but only with an audited takeover
  record (facts handed to ``on_takeover`` and journaled by the driver);
- crash leftovers are exactly the expired-lease case: a restart waits
  out the lease (tests use seconds) and takes over with a record.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import uuid
from pathlib import Path
from typing import Callable

__all__ = ["LockHeldError", "SessionLock"]


class LockHeldError(RuntimeError):
    """Another live writer holds the session lease — refuse, don't share."""


class SessionLock:
    def __init__(self, path: Path | str, lease_seconds: int = 300) -> None:
        self.path = Path(path)
        self.lease_seconds = lease_seconds
        self.owner_instance_id = uuid.uuid4().hex
        self._held = False

    def acquire(self, on_takeover: Callable[[dict], None] | None = None,
                *, now: dt.datetime | None = None) -> dict | None:
        """Take the lease. Returns takeover facts when a stale lease was
        broken (also passed to ``on_takeover``); None on a fresh acquire.
        Raises :class:`LockHeldError` when a live, unexpired lease exists."""
        now = now or dt.datetime.now(dt.timezone.utc)
        if self._held:
            raise LockHeldError("this instance already holds the lease")
        takeover_facts: dict | None = None
        if self.path.exists():
            existing = json.loads(
                self.path.read_text(encoding="utf-8"))
            expires_at = dt.datetime.fromisoformat(existing["expires_at"])
            if expires_at > now:
                raise LockHeldError(
                    f"session lock held by instance "
                    f"{existing.get('owner_instance_id')} (pid "
                    f"{existing.get('pid')}) until {existing['expires_at']}"
                    " — refusing (conservative suspend)")
            takeover_facts = {
                "reason": "STALE_LEASE_TAKEOVER",
                "stale_owner_instance_id": existing.get("owner_instance_id"),
                "stale_pid": existing.get("pid"),
                "stale_expires_at": existing.get("expires_at"),
                "taken_over_at": now.isoformat(),
                "new_owner_instance_id": self.owner_instance_id,
            }
            if on_takeover is not None:
                on_takeover(takeover_facts)
            # the audited stale record is replaced; the journal (not this
            # file) carries the takeover history
            self.path.unlink()
        record = {
            "owner_instance_id": self.owner_instance_id,
            "pid": os.getpid(),
            "acquired_at": now.isoformat(),
            "expires_at": (
                now + dt.timedelta(seconds=self.lease_seconds)).isoformat(),
        }
        # 'x' mode: refuse to clobber between the stale check and create
        with self.path.open("x", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True))
        self._held = True
        return takeover_facts

    def release(self) -> None:
        if not self._held:
            return
        # only the holder removes the file, and only if it still names us
        if self.path.exists():
            existing = json.loads(
                self.path.read_text(encoding="utf-8"))
            if existing.get("owner_instance_id") == self.owner_instance_id:
                self.path.unlink()
        self._held = False

    def renew(self, *, now: dt.datetime | None = None) -> None:
        if not self._held:
            raise LockHeldError("renew requires the held lease")
        now = now or dt.datetime.now(dt.timezone.utc)
        record = {
            "owner_instance_id": self.owner_instance_id,
            "pid": os.getpid(),
            "acquired_at": now.isoformat(),
            "expires_at": (
                now + dt.timedelta(seconds=self.lease_seconds)).isoformat(),
            "took_over_stale": False,
        }
        self.path.write_text(json.dumps(record, sort_keys=True),
                             encoding="utf-8")
