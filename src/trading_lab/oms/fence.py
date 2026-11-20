"""Single-writer fencing: monotonic epoch + lease per (environment,
account_id), stored in SQLite so contention between REAL processes is
serialized by transaction semantics (not in-memory locks).

The guarantee lives HERE (the trusted local egress), not in the downstream
broker: the FakeBroker does not understand epochs — the egress refuses
stale/expired/foreign fences before any port call.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path

from ..contracts import Environment


class FenceError(RuntimeError):
    """Fence acquisition/validation failed — no broker write may proceed."""


@dataclass(frozen=True)
class FenceToken:
    environment: Environment
    account_id: str
    epoch: int
    lease_expires_at: dt.datetime
    owner_instance_id: str

    def is_expired(self, now: dt.datetime) -> bool:
        return now >= self.lease_expires_at


class FenceCoordinator:
    """SQLite-backed monotonic fencing authority for one (environment,
    account). Cross-process safe: the epoch bump is a single transaction."""

    def __init__(self, path: str | Path, environment: Environment, account_id: str,
                 lease_seconds: int = 30) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._env = environment
        self._account = account_id
        self._lease_seconds = lease_seconds
        try:
            self._conn = sqlite3.connect(str(self._path), isolation_level=None, timeout=10)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=FULL")
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS fences ("
                " environment TEXT NOT NULL, account_id TEXT NOT NULL,"
                " epoch INTEGER NOT NULL DEFAULT 0,"
                " PRIMARY KEY (environment, account_id))"
            )
            self._conn.execute(
                "INSERT OR IGNORE INTO fences (environment, account_id, epoch) VALUES (?,?,0)",
                (self._env.value, self._account),
            )
        except sqlite3.Error as exc:
            raise FenceError(f"fence store unavailable: {exc}") from exc
        self._instance_id = uuid.uuid4().hex

    def acquire(self, now: dt.datetime) -> FenceToken:
        """Atomically bump the epoch and take a fresh lease."""
        try:
            with self._conn:
                row = self._conn.execute(
                    "UPDATE fences SET epoch = epoch + 1"
                    " WHERE environment=? AND account_id=?"
                    " RETURNING epoch",
                    (self._env.value, self._account),
                ).fetchone()
                epoch = int(row[0])
        except sqlite3.Error as exc:
            raise FenceError(f"epoch bump failed: {exc}") from exc
        return FenceToken(
            environment=self._env,
            account_id=self._account,
            epoch=epoch,
            lease_expires_at=now + dt.timedelta(seconds=self._lease_seconds),
            owner_instance_id=self._instance_id,
        )

    def validate(self, token: FenceToken, now: dt.datetime) -> None:
        """A token is valid only if: this instance still owns it, the lease
        has not expired, and the stored epoch still equals the token's epoch
        (a newer acquire by ANY instance invalidates older tokens)."""
        if token.environment is not self._env or token.account_id != self._account:
            raise FenceError("fence bound to a different environment/account")
        if token.owner_instance_id != self._instance_id:
            raise FenceError("stale executor: fence owned by another instance")
        if token.is_expired(now):
            raise FenceError("fence lease expired")
        row = self._conn.execute(
            "SELECT epoch FROM fences WHERE environment=? AND account_id=?",
            (self._env.value, self._account),
        ).fetchone()
        if row is None or int(row[0]) != token.epoch:
            raise FenceError(
                f"stale fence: token epoch {token.epoch} superseded "
                f"(current {row[0] if row else 'none'})"
            )


__all__ = ["FenceCoordinator", "FenceError", "FenceToken"]
