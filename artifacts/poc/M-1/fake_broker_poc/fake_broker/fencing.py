"""Single-writer fencing tokens backed by SQLite (atomic epoch allocation).

Production contract (Architecture doc §6.1-3): each (environment, account) has
at most ONE valid executor; the epoch is monotonic; a lease that expires cannot
be used; a recovered executor must obtain a NEW epoch; stale epochs are refused
by the broker gateway.

A plain DB lock cannot stop a partitioned old instance from calling the broker
directly — the broker side must refuse stale epochs (tested in
test_04_dual_executor_fencing via FakeBroker.valid_fences).
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


class LeaseExpiredError(Exception):
    pass


@dataclass(frozen=True)
class FencingToken:
    environment: str
    account_id: str
    owner_instance_id: str
    epoch: int
    lease_expires_at: float  # injected monotonic clock seconds

    def is_expired(self, now: float) -> bool:
        return now >= self.lease_expires_at


class LeaseStore:
    def __init__(self, db_path: Path, lease_seconds: float = 30.0, clock=None):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path), isolation_level=None)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=FULL")
        self.lease_seconds = lease_seconds
        self.clock = clock  # callable -> float seconds (monotonic)
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS leases (
              environment TEXT NOT NULL,
              account_id TEXT NOT NULL,
              current_epoch INTEGER NOT NULL,
              owner_instance_id TEXT,
              lease_expires_at REAL,
              PRIMARY KEY (environment, account_id)
            );
            CREATE TABLE IF NOT EXISTS epoch_counter (
              environment TEXT NOT NULL,
              account_id TEXT NOT NULL,
              epoch INTEGER NOT NULL,
              PRIMARY KEY (environment, account_id)
            );
            """
        )

    def _now(self) -> float:
        return float(self.clock()) if self.clock else 0.0

    def acquire(self, environment: str, account_id: str, owner_instance_id: str) -> FencingToken:
        """Atomically bump the epoch and grant a fresh lease to the caller.
        Any previous holder's token becomes stale immediately (new epoch)."""
        now = self._now()
        self.conn.execute("BEGIN IMMEDIATE")
        self.conn.execute(
            "INSERT INTO epoch_counter (environment, account_id, epoch) VALUES (?,?,0)"
            " ON CONFLICT(environment, account_id) DO UPDATE SET epoch=epoch+1",
            (environment, account_id),
        )
        epoch = self.conn.execute(
            "SELECT epoch FROM epoch_counter WHERE environment=? AND account_id=?",
            (environment, account_id)).fetchone()[0]
        expires = now + self.lease_seconds
        self.conn.execute(
            "INSERT INTO leases (environment, account_id, current_epoch, owner_instance_id,"
            " lease_expires_at) VALUES (?,?,?,?,?) ON CONFLICT(environment, account_id)"
            " DO UPDATE SET current_epoch=excluded.current_epoch,"
            " owner_instance_id=excluded.owner_instance_id,"
            " lease_expires_at=excluded.lease_expires_at",
            (environment, account_id, epoch, owner_instance_id, expires),
        )
        self.conn.commit()
        return FencingToken(environment, account_id, owner_instance_id, epoch, expires)

    def validate(self, token: FencingToken) -> bool:
        """True iff token's epoch is still current AND its lease has not expired."""
        now = self._now()
        row = self.conn.execute(
            "SELECT current_epoch, lease_expires_at, owner_instance_id FROM leases"
            " WHERE environment=? AND account_id=?", (token.environment, token.account_id)).fetchone()
        if row is None:
            return False
        current_epoch, lease_expires, owner = row
        return (token.epoch == current_epoch
                and token.owner_instance_id == owner
                and now < float(lease_expires))

    def current_epoch(self, environment: str, account_id: str) -> Optional[int]:
        row = self.conn.execute(
            "SELECT current_epoch FROM leases WHERE environment=? AND account_id=?",
            (environment, account_id)).fetchone()
        return int(row[0]) if row else None
