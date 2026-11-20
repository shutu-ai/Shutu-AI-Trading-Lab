"""Durable order journal — SQLite WAL with synchronous=FULL.

Crash-consistency contract (ADR-002-addendum D1): an intent plus its
SUBMITTING attempt record commit in ONE transaction before any egress call;
a committed transaction survives process crash (SQLite WAL + full sync).
The journal is the single source of truth for recovery — the egress call is
only ever *attempted after* this commit succeeds, and a journal failure
means zero sends.
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
from pathlib import Path
from typing import Any

from trading_lab.security.canonical import sha256_hex

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS intents (
    intent_id TEXT PRIMARY KEY,
    client_order_id TEXT NOT NULL UNIQUE,
    environment TEXT NOT NULL,
    account_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    quantity TEXT NOT NULL,
    payload_json TEXT NOT NULL,          -- canonical full intent payload
    payload_hash TEXT NOT NULL,
    risk_decision_json TEXT NOT NULL,    -- full RiskDecision record
    state TEXT NOT NULL,
    version INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS attempts (
    attempt_id TEXT PRIMARY KEY,
    intent_id TEXT NOT NULL REFERENCES intents(intent_id),
    fence_epoch INTEGER NOT NULL,
    state TEXT NOT NULL,                 -- SUBMITTING / SENT / FAILED_UNREACHED
    started_at TEXT NOT NULL,
    finished_at TEXT,
    result_json TEXT);
CREATE INDEX IF NOT EXISTS idx_attempts_intent ON attempts(intent_id);
CREATE TABLE IF NOT EXISTS events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    intent_id TEXT NOT NULL,
    broker_event_id TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    received_at TEXT NOT NULL);
"""


class JournalError(RuntimeError):
    """Journal unusable — every caller must fail closed."""


class OrderJournal:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._conn = sqlite3.connect(str(self._path), isolation_level=None)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=FULL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.executescript(_SCHEMA)
        except sqlite3.Error as exc:
            raise JournalError(f"journal unavailable: {exc}") from exc

    def close(self) -> None:
        self._conn.close()

    @property
    def path(self) -> Path:
        return self._path

    # -- writes (each is one atomic transaction) ------------------------------

    def record_intent(
        self,
        intent_id: str,
        client_order_id: str,
        environment: str,
        account_id: str,
        symbol: str,
        side: str,
        quantity: str,
        payload: dict[str, Any],
        risk_decision: dict[str, Any],
        state: str = "NEW_INTENT",
    ) -> None:
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        decision_json = json.dumps(risk_decision, sort_keys=True, separators=(",", ":"))
        try:
            with self._conn:  # atomic
                self._conn.execute(
                    "INSERT INTO intents (intent_id, client_order_id, environment, account_id,"
                    " symbol, side, quantity, payload_json, payload_hash, risk_decision_json,"
                    " state, version, created_at, updated_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        intent_id, client_order_id, environment, account_id, symbol, side,
                        quantity, payload_json, sha256_hex(payload_json.encode("utf-8")),
                        decision_json, state, 1, now, now,
                    ),
                )
        except sqlite3.Error as exc:
            raise JournalError(f"intent persist failed: {exc}") from exc

    def mark_submitting(self, intent_id: str, attempt_id: str, fence_epoch: int) -> None:
        """One transaction: intent -> SUBMITTING + attempt row SUBMITTING.
        Must commit BEFORE the egress call is attempted."""
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        try:
            with self._conn:
                self._conn.execute(
                    "UPDATE intents SET state='SUBMITTING', updated_at=? WHERE intent_id=?",
                    (now, intent_id),
                )
                self._conn.execute(
                    "INSERT INTO attempts (attempt_id, intent_id, fence_epoch, state, started_at)"
                    " VALUES (?,?,?,?,?)",
                    (attempt_id, intent_id, fence_epoch, "SUBMITTING", now),
                )
        except sqlite3.Error as exc:
            raise JournalError(f"submitting persist failed: {exc}") from exc

    def finish_attempt(self, attempt_id: str, state: str, result: dict[str, Any]) -> None:
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        try:
            with self._conn:
                self._conn.execute(
                    "UPDATE attempts SET state=?, finished_at=?, result_json=? WHERE attempt_id=?",
                    (state, now, json.dumps(result, sort_keys=True), attempt_id),
                )
        except sqlite3.Error as exc:
            raise JournalError(f"attempt finish persist failed: {exc}") from exc

    def set_state(self, intent_id: str, state: str, bump_version: bool = False) -> None:
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        try:
            with self._conn:
                if bump_version:
                    self._conn.execute(
                        "UPDATE intents SET state=?, version=version+1, updated_at=? WHERE intent_id=?",
                        (state, now, intent_id),
                    )
                else:
                    self._conn.execute(
                        "UPDATE intents SET state=?, updated_at=? WHERE intent_id=?",
                        (state, now, intent_id),
                    )
        except sqlite3.Error as exc:
            raise JournalError(f"state persist failed: {exc}") from exc

    def state_of(self, intent_id: str) -> str | None:
        row = self._conn.execute(
            "SELECT state FROM intents WHERE intent_id=?", (intent_id,)
        ).fetchone()
        return row[0] if row else None

    # -- recovery / queries ----------------------------------------------------

    def open_intents(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT intent_id, client_order_id, environment, account_id, symbol, side,"
            " quantity, payload_json, risk_decision_json, state, version"
            " FROM intents WHERE state NOT IN"
            " ('FILLED','CANCELLED','REJECTED','RECONCILED')"
        ).fetchall()
        out = []
        for r in rows:
            out.append(
                {
                    "intent_id": r[0], "client_order_id": r[1], "environment": r[2],
                    "account_id": r[3], "symbol": r[4], "side": r[5],
                    "quantity": r[6], "payload": json.loads(r[7]),
                    "risk_decision": json.loads(r[8]), "state": r[9], "version": r[10],
                }
            )
        return out

    def record_broker_event(self, intent_id: str, broker_event_id: str, kind: str, payload: dict[str, Any]) -> bool:
        """Idempotent by broker_event_id; returns True when newly recorded."""
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        try:
            with self._conn:
                cur = self._conn.execute(
                    "INSERT OR IGNORE INTO events (intent_id, broker_event_id, kind,"
                    " payload_json, received_at) VALUES (?,?,?,?,?)",
                    (intent_id, broker_event_id, kind, json.dumps(payload, sort_keys=True), now),
                )
                return cur.rowcount > 0
        except sqlite3.Error as exc:
            raise JournalError(f"event persist failed: {exc}") from exc

    def seen_broker_event(self, broker_event_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM events WHERE broker_event_id=?", (broker_event_id,)
        ).fetchone()
        return row is not None


__all__ = ["JournalError", "OrderJournal"]
