"""Durable order journal on SQLite (WAL, synchronous=FULL).

Durability contract (Architecture doc §6.1-1):
- an intent and its submit attempt are COMMITTED before any broker network call
- every state write is an explicit committed transaction
- synchronous=FULL is asserted at open time; tests fail if the pragma is lost
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

from .contracts import OrderIntent, OrderState


class DurableJournal:
    def __init__(self, db_path: Path):
        db_path = Path(db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path), isolation_level=None)  # autocommit; explicit BEGIN
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=FULL")
        mode = self.conn.execute("PRAGMA journal_mode").fetchone()[0]
        sync = self.conn.execute("PRAGMA synchronous").fetchone()[0]
        if str(mode).lower() != "wal":
            raise RuntimeError(f"journal_mode is {mode}, expected WAL")
        if int(sync) != 2:  # 2 == FULL
            raise RuntimeError(f"synchronous is {sync}, expected 2 (FULL)")
        self._create_schema()

    def _create_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS intents (
              intent_id TEXT PRIMARY KEY,
              client_order_id TEXT UNIQUE NOT NULL,
              environment TEXT NOT NULL,
              account_id TEXT NOT NULL,
              symbol TEXT NOT NULL,
              side TEXT NOT NULL,
              qty TEXT NOT NULL,
              payload_hash TEXT NOT NULL,
              state TEXT NOT NULL,
              halt_new_risk INTEGER NOT NULL DEFAULT 0,
              created_at_utc TEXT NOT NULL,
              updated_at_utc TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS submit_attempts (
              attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
              intent_id TEXT NOT NULL,
              client_order_id TEXT NOT NULL,
              fence_epoch INTEGER NOT NULL,
              phase TEXT NOT NULL,           -- PREPARED | SUBMITTING | RESOLVED
              outcome TEXT NOT NULL,         -- OK | UNKNOWN | CONN_REFUSED | REJECTED | CRASHED_BEFORE_SEND
              created_at_utc TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS order_events (
              event_id TEXT PRIMARY KEY,     -- broker event id, dedupe key
              client_order_id TEXT NOT NULL,
              new_state TEXT NOT NULL,
              filled_qty TEXT NOT NULL,
              avg_price TEXT,
              received_at_utc TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS account_state (
              environment TEXT NOT NULL,
              account_id TEXT NOT NULL,
              halted INTEGER NOT NULL DEFAULT 0,
              halt_reason TEXT,
              PRIMARY KEY (environment, account_id)
            );
            """
        )

    # ---- intents ----
    def record_intent(self, intent: OrderIntent, now: str) -> None:
        """PREPARED: the durability point BEFORE any network call."""
        cur = self.conn.execute("SELECT 1 FROM intents WHERE intent_id=?", (intent.intent_id,))
        if cur.fetchone():
            raise ValueError(f"duplicate intent_id {intent.intent_id}")
        self.conn.execute("BEGIN IMMEDIATE")
        self.conn.execute(
            "INSERT INTO intents (intent_id, client_order_id, environment, account_id, symbol,"
            " side, qty, payload_hash, state, created_at_utc, updated_at_utc)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (intent.intent_id, intent.client_order_id, intent.environment.value, intent.account_id,
             intent.symbol, intent.side, str(intent.qty), intent.payload_hash,
             OrderState.PREPARED.value, now, now),
        )
        self.conn.execute(
            "INSERT OR IGNORE INTO account_state (environment, account_id) VALUES (?,?)",
            (intent.environment.value, intent.account_id),
        )
        self.conn.commit()

    def mark_submitting(self, intent: OrderIntent, fence_epoch: int, now: str) -> int:
        """Persisted BEFORE the broker call; returns attempt_id."""
        self.conn.execute("BEGIN IMMEDIATE")
        self.conn.execute(
            "INSERT INTO submit_attempts (intent_id, client_order_id, fence_epoch, phase,"
            " outcome, created_at_utc) VALUES (?,?,?,?,?,?)",
            (intent.intent_id, intent.client_order_id, fence_epoch, "SUBMITTING", "PENDING", now),
        )
        attempt_id = self.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        self._set_state(intent.intent_id, OrderState.SUBMITTING, now, in_tx=True)
        self.conn.commit()
        return int(attempt_id)

    def resolve_attempt(self, attempt_id: int, outcome: str, now: str) -> None:
        self.conn.execute("BEGIN IMMEDIATE")
        self.conn.execute(
            "UPDATE submit_attempts SET phase='RESOLVED', outcome=? WHERE attempt_id=?",
            (outcome, attempt_id),
        )
        self.conn.commit()
        _ = now  # recorded via order_events / state updates; kept for interface symmetry

    def set_state(self, intent_id: str, new_state: OrderState, now: str) -> None:
        self._set_state(intent_id, new_state, now, in_tx=False)

    def _set_state(self, intent_id: str, new_state: OrderState, now: str, in_tx: bool) -> None:
        if not in_tx:
            self.conn.execute("BEGIN IMMEDIATE")
        old = self.get_intent_state(intent_id)
        if old is not None and not new_state == old:
            from .contracts import is_legal_transition
            if not is_legal_transition(OrderState(old), new_state):
                raise RuntimeError(f"illegal transition {old} -> {new_state.value} for {intent_id}")
        self.conn.execute(
            "UPDATE intents SET state=?, updated_at_utc=? WHERE intent_id=?",
            (new_state.value, now, intent_id),
        )
        if not in_tx:
            self.conn.commit()

    def get_intent_state(self, intent_id: str) -> Optional[str]:
        row = self.conn.execute("SELECT state FROM intents WHERE intent_id=?", (intent_id,)).fetchone()
        return row[0] if row else None

    def get_intent_by_coid(self, coid: str) -> Optional[dict]:
        row = self.conn.execute(
            "SELECT intent_id, client_order_id, environment, account_id, state FROM intents"
            " WHERE client_order_id=?", (coid,)).fetchone()
        if not row:
            return None
        keys = ["intent_id", "client_order_id", "environment", "account_id", "state"]
        return dict(zip(keys, row))

    def open_intents(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT intent_id, client_order_id, environment, account_id, state FROM intents"
            " WHERE state NOT IN ('FILLED','CANCELED','REJECTED')").fetchall()
        keys = ["intent_id", "client_order_id", "environment", "account_id", "state"]
        return [dict(zip(keys, r)) for r in rows]

    def pending_attempts_before_send(self) -> list[dict]:
        """Attempts in SUBMITTING phase that never got resolved — crash candidates."""
        rows = self.conn.execute(
            "SELECT attempt_id, intent_id, client_order_id, fence_epoch, outcome"
            " FROM submit_attempts WHERE phase!='RESOLVED'").fetchall()
        keys = ["attempt_id", "intent_id", "client_order_id", "fence_epoch", "outcome"]
        return [dict(zip(keys, r)) for r in rows]

    # ---- broker events (dedupe by broker event id) ----
    def record_event(self, event_id: str, coid: str, new_state: str, filled_qty: str,
                     avg_price: Optional[str], now: str) -> bool:
        """Returns True if newly recorded, False if duplicate (idempotent replay)."""
        cur = self.conn.execute("SELECT 1 FROM order_events WHERE event_id=?", (event_id,))
        if cur.fetchone():
            return False
        self.conn.execute("BEGIN IMMEDIATE")
        cur2 = self.conn.execute("SELECT 1 FROM order_events WHERE event_id=?", (event_id,))
        if cur2.fetchone():
            self.conn.rollback()
            return False
        self.conn.execute(
            "INSERT INTO order_events (event_id, client_order_id, new_state, filled_qty,"
            " avg_price, received_at_utc) VALUES (?,?,?,?,?,?)",
            (event_id, coid, new_state, filled_qty, avg_price, now),
        )
        self.conn.commit()
        return True

    def event_ids_for(self, coid: str) -> set[str]:
        rows = self.conn.execute(
            "SELECT event_id FROM order_events WHERE client_order_id=?", (coid,)).fetchall()
        return {r[0] for r in rows}

    # ---- account-level risk halt ----
    def halt_new_risk(self, environment: str, account_id: str, reason: str) -> None:
        self.conn.execute("BEGIN IMMEDIATE")
        self.conn.execute(
            "INSERT INTO account_state (environment, account_id, halted, halt_reason)"
            " VALUES (?,?,1,?) ON CONFLICT(environment, account_id)"
            " DO UPDATE SET halted=1, halt_reason=excluded.halt_reason",
            (environment, account_id, reason),
        )
        self.conn.commit()

    def clear_halt(self, environment: str, account_id: str, operator: str) -> None:
        """Only ever called with explicit operator authorization (no auto-clear)."""
        self.conn.execute("BEGIN IMMEDIATE")
        self.conn.execute(
            "UPDATE account_state SET halted=0, halt_reason=NULL WHERE environment=? AND account_id=?",
            (environment, account_id),
        )
        self.conn.commit()

    def is_halted(self, environment: str, account_id: str) -> bool:
        row = self.conn.execute(
            "SELECT halted FROM account_state WHERE environment=? AND account_id=?",
            (environment, account_id)).fetchone()
        return bool(row and row[0])
