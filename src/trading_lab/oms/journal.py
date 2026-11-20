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
from decimal import Decimal
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
    filled_qty TEXT NOT NULL DEFAULT '0',
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


class _SimulatedCrash(RuntimeError):
    """Internal rollback trigger for crash-window simulation."""


class OrderJournal:
    def __init__(self, path: str | Path, check_same_thread: bool = True) -> None:
        # Thread-locked by default; the R6 race test explicitly opens a
        # cross-thread connection to simulate an in-flight egress call from
        # another thread. Real multi-process runs use one connection per
        # process and never need this.
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._conn = sqlite3.connect(str(self._path), isolation_level=None,
                                         check_same_thread=check_same_thread)
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

    def record_intent_and_submitting(
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
        fence_epoch: int,
        simulate_crash_before_commit: bool = False,
    ) -> str:
        """ONE atomic transaction (R4): the full intent AND its SUBMITTING
        attempt commit together, before any egress call is possible. A crash
        before commit leaves neither row (rollback) — there is no observable
        intermediate state, and the egress is only ever called after this
        method returns. Returns the attempt id."""
        import uuid

        now = dt.datetime.now(dt.timezone.utc).isoformat()
        attempt_id = uuid.uuid4().hex
        payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        decision_json = json.dumps(risk_decision, sort_keys=True, separators=(",", ":"))
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            self._conn.execute(
                "INSERT INTO intents (intent_id, client_order_id, environment, account_id,"
                " symbol, side, quantity, payload_json, payload_hash, risk_decision_json,"
                " state, version, filled_qty, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,'SUBMITTING',1,'0',?,?)",
                (
                    intent_id, client_order_id, environment, account_id, symbol, side,
                    quantity, payload_json, sha256_hex(payload_json.encode("utf-8")),
                    decision_json, now, now,
                ),
            )
            self._conn.execute(
                "INSERT INTO attempts (attempt_id, intent_id, fence_epoch, state, started_at)"
                " VALUES (?,?,?,?,?)",
                (attempt_id, intent_id, fence_epoch, "SUBMITTING", now),
            )
            if simulate_crash_before_commit:
                raise _SimulatedCrash("simulated crash before commit")
            self._conn.execute("COMMIT")
        except _SimulatedCrash:
            self._conn.execute("ROLLBACK")
            raise  # crash simulation propagates; nothing was committed
        except sqlite3.Error as exc:
            try:
                self._conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise JournalError(f"intent+attempt persist failed: {exc}") from exc
        return attempt_id

    def finish_attempt(self, attempt_id: str, state: str, result: dict[str, Any]) -> None:
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            self._conn.execute(
                "UPDATE attempts SET state=?, finished_at=?, result_json=? WHERE attempt_id=?",
                (state, now, json.dumps(result, sort_keys=True), attempt_id),
            )
            self._conn.execute("COMMIT")
        except sqlite3.Error as exc:
            try:
                self._conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise JournalError(f"attempt finish persist failed: {exc}") from exc

    def transition_state(self, intent_id: str, expected: str, target: str,
                         bump_version: bool = False) -> None:
        """CAS state transition persisted at the storage layer (R4 + R3):
        the state machine itself is enforced here (validate_transition) AND
        the update only lands when the current state equals ``expected`` —
        so illegal or raced transitions never touch the database."""
        from .states import IllegalTransition, validate_transition

        try:
            validate_transition(expected, target)  # illegal shapes never reach SQL
        except IllegalTransition as exc:
            raise JournalError(f"illegal transition: {exc}") from exc
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            if bump_version:
                cur = self._conn.execute(
                    "UPDATE intents SET state=?, version=version+1, updated_at=?"
                    " WHERE intent_id=? AND state=?",
                    (target, now, intent_id, expected),
                )
            else:
                cur = self._conn.execute(
                    "UPDATE intents SET state=?, updated_at=?"
                    " WHERE intent_id=? AND state=?",
                    (target, now, intent_id, expected),
                )
            if cur.rowcount == 0:
                self._conn.execute("ROLLBACK")
                raise JournalError(
                    f"CAS transition failed: {intent_id} expected state {expected!r}"
                )
            self._conn.execute("COMMIT")
        except JournalError:
            raise
        except sqlite3.Error as exc:
            try:
                self._conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise JournalError(f"state persist failed: {exc}") from exc

    def get_send_eligibility(
        self,
        client_order_id: str,
        fence_epoch: int,
        symbol: str,
        side: str,
        quantity: str,
        environment: str,
        account_id: str,
    ) -> dict[str, Any] | None:
        """R2: authoritative send-eligibility lookup. Returns the joined
        intent+attempt row ONLY when a SUBMITTING intent with this exact
        coid/env/account/symbol/side/quantity carries a SUBMITTING attempt
        at THIS fence epoch — otherwise None (caller refuses)."""
        row = self._conn.execute(
            "SELECT i.intent_id, i.state, i.symbol, i.side, i.quantity, i.environment,"
            " i.account_id, i.payload_json, i.risk_decision_json"
            " FROM intents i WHERE i.client_order_id=?", (client_order_id,),
        ).fetchone()
        if row is None:
            return None
        intent_id, state, sym, side_, qty, env, acct = row[0], row[1], row[2], row[3], row[4], row[5], row[6]
        if state != "SUBMITTING":
            return None
        if (sym, side_, qty, env, acct) != (symbol, side, quantity, environment, account_id):
            return None
        attempt = self._conn.execute(
            "SELECT 1 FROM attempts WHERE intent_id=? AND state='SUBMITTING' AND fence_epoch=?",
            (intent_id, fence_epoch),
        ).fetchone()
        if attempt is None:
            return None
        return {
            "intent_id": intent_id,
            "state": state, "symbol": sym, "side": side_, "quantity": qty,
            "payload_json": row[7], "risk_decision_json": row[8],
        }

    def intent_exists(self, client_order_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM intents WHERE client_order_id=?", (client_order_id,),
        ).fetchone()
        return row is not None

    def unresolved_count(self) -> int:
        """Non-terminal, non-reconciled intents — any of them blocks an
        operator unlock (R3)."""
        row = self._conn.execute(
            "SELECT COUNT(*) FROM intents WHERE state NOT IN"
            " ('FILLED','CANCELLED','REJECTED','RECONCILED')"
        ).fetchone()
        return int(row[0])

    def apply_fill(self, intent_id: str, broker_event_id: str, qty: Decimal) -> tuple[bool, str]:
        """Atomic fill application (R5): event dedupe + cumulative quantity +
        state transition in ONE transaction. Returns (recorded, reason)."""
        # R4: strictly positive, finite Decimal — zero/negative/NaN/Infinity/
        # float/int/bool are refused before ANY event or state is touched.
        if isinstance(qty, bool) or not isinstance(qty, Decimal):
            return False, "INVALID_FILL_TYPE"
        if not qty.is_finite() or qty <= 0:
            return False, "INVALID_FILL_VALUE"
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            cur = self._conn.execute(
                "INSERT OR IGNORE INTO events (intent_id, broker_event_id, kind,"
                " payload_json, received_at) VALUES (?,?,?,?,?)",
                (intent_id, broker_event_id, "FILL", json.dumps({"qty": str(qty)}), now),
            )
            if cur.rowcount == 0:
                self._conn.execute("ROLLBACK")
                return False, "DUPLICATE_EVENT"
            row = self._conn.execute(
                "SELECT state, quantity, filled_qty FROM intents WHERE intent_id=?",
                (intent_id,),
            ).fetchone()
            if row is None:
                self._conn.execute("ROLLBACK")
                return False, "UNKNOWN_INTENT"
            state, quantity, filled = row[0], Decimal(row[1]), Decimal(row[2])
            if state not in ("ACKED", "PARTIALLY_FILLED"):
                self._conn.execute("ROLLBACK")
                return False, f"FILL_REJECTED_STATE:{state}"
            new_filled = filled + qty
            if new_filled > quantity:
                self._conn.execute("ROLLBACK")
                return False, "OVERFILL"
            target = "FILLED" if new_filled == quantity else "PARTIALLY_FILLED"
            self._conn.execute(
                "UPDATE intents SET state=?, filled_qty=?, updated_at=? WHERE intent_id=?",
                (target, str(new_filled), now, intent_id),
            )
            self._conn.execute("COMMIT")
            return True, target
        except sqlite3.Error as exc:
            try:
                self._conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise JournalError(f"fill persist failed: {exc}") from exc

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
            self._conn.execute("BEGIN IMMEDIATE")
            cur = self._conn.execute(
                "INSERT OR IGNORE INTO events (intent_id, broker_event_id, kind,"
                " payload_json, received_at) VALUES (?,?,?,?,?)",
                (intent_id, broker_event_id, kind, json.dumps(payload, sort_keys=True), now),
            )
            self._conn.execute("COMMIT")
            return cur.rowcount > 0
        except sqlite3.Error as exc:
            try:
                self._conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise JournalError(f"event persist failed: {exc}") from exc

    def seen_broker_event(self, broker_event_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM events WHERE broker_event_id=?", (broker_event_id,)
        ).fetchone()
        return row is not None


__all__ = ["JournalError", "OrderJournal"]
