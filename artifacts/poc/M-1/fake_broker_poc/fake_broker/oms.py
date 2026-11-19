"""MinimalOMS — persist-then-send protocol with recovery/fencing (M-1 POC).

Protocol:
  1. validate intent + fencing token + account halt state
  2. record_intent (PREPARED)  — COMMITTED DURABILITY POINT (before any send)
  3. mark_submitting (SUBMITTING + attempt row) — COMMITTED
  4. broker.submit_order(...)  — the network boundary
  5. persist outcome + broker events (dedup by broker event id)

Order-state truth rules:
- UNKNOWN (sent, unconfirmed): reconcile by client_order_id BEFORE anything
  else. If the broker shows the order → adopt broker state, never resend.
  If broker confirms NO order exists and the crash point was before the send →
  send ONCE under the fresh fencing epoch (first send, not a resend; broker-side
  client_order_id idempotency remains the second line of defense). If broker
  reachability or outcome remains unprovable → HALT_NEW_RISK (no new risk).
- No blind resends, ever.

Crash model: injected exceptions at the two boundaries
  CrashBeforeSend — after durability commit, before the broker call
  CrashAfterSend  — broker processed/returned a snapshot, before local persist
Recovery = fresh MinimalOMS on the same journal + NEW fencing epoch.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from .contracts import (BrokerAdapter, BrokerOrderSnapshot, Environment,
                        OrderIntent, OrderState, deterministic_client_order_id)
from .fake_broker import (ConnRefusedError, EnvironmentMismatchError,
                          FenceRejectedError, TransientRejectError,
                          UnknownStateError)
from .fencing import FencingToken
from .journal import DurableJournal


class CrashBeforeSend(Exception):
    """Injected: process dies after durability point, before network call."""


class CrashAfterSend(Exception):
    """Injected: dies after broker accepted the order, before local persist."""


class HaltedError(Exception):
    pass


class MinimalOMS:
    def __init__(self, environment: Environment, account_id: str, journal: DurableJournal):
        self.environment = environment
        self.account_id = account_id
        self.journal = journal
        self.now_counter = 0

    def _now(self) -> str:
        self.now_counter += 1
        return f"2026-01-02T15:00:{self.now_counter:02d}Z"

    # ---------------- main path ----------------
    def submit(self, intent: OrderIntent, token: FencingToken, broker: BrokerAdapter,
               inject: Optional[str] = None) -> str:
        """Returns final local state value. inject: 'crash_before_send' |
        'crash_after_send' simulates a process crash at those points."""
        if intent.environment != self.environment or intent.account_id != self.account_id:
            raise EnvironmentMismatchError("intent/OMS namespace mismatch")
        if self.journal.is_halted(self.environment.value, self.account_id):
            raise HaltedError("HALT_NEW_RISK active; operator release required")
        expected = deterministic_client_order_id(self.environment, self.account_id, intent.intent_id)
        if intent.client_order_id != expected:
            raise ValueError("client_order_id is not the deterministic value for this intent")
        intent.validate()
        if self.journal.get_intent_state(intent.intent_id) is not None:
            return "DUPLICATE_INTENT"  # never re-record; reconcile instead

        # durability point
        self.journal.record_intent(intent, self._now())
        attempt_id = self.journal.mark_submitting(intent, token.epoch, self._now())

        if inject == "crash_before_send":
            raise CrashBeforeSend(intent.client_order_id)

        try:
            state = self._send_once(intent, token.epoch, broker, attempt_id)
        except CrashAfterSend:
            raise
        return state

    # ---------------- recovery ----------------
    def recover(self, token: FencingToken, broker: BrokerAdapter,
                operator_release_halt: bool = False) -> dict:
        """Journal-first reconciliation for every non-terminal intent.
        Returns an audit dict; every action is recorded, nothing is blind."""
        actions = []
        for row in self.journal.open_intents():
            intent_id, coid = row["intent_id"], row["client_order_id"]
            local_state = OrderState(row["state"])
            snap = broker.get_order(coid)
            if snap is not None:
                # broker is the truth; adopt, dedupe by event id, never resend
                self._adopt_snapshot(intent_id, snap)
                actions.append({"intent_id": intent_id, "coid": coid,
                                "from": local_state.value, "to": snap.state.value,
                                "action": "ADOPTED_BROKER_STATE", "sent": False})
                continue

            # broker has no such order
            unresolved = [a for a in self.journal.pending_attempts_before_send()
                          if a["intent_id"] == intent_id]
            if local_state == OrderState.PREPARED or (
                    local_state == OrderState.SUBMITTING and unresolved):
                # crash window before/at the send; broker confirms absence →
                # complete the send ONCE under the fresh fence
                attempt_id = unresolved[0]["attempt_id"] if unresolved else None
                try:
                    new_state = self._send_once(self._load_intent(row), token.epoch,
                                                broker, attempt_id)
                except UnknownStateError:
                    actions.append({"intent_id": intent_id, "coid": coid,
                                    "from": local_state.value, "to": OrderState.UNKNOWN.value,
                                    "action": "SEND_ONCE_GOT_UNKNOWN_HALT", "sent": True})
                    continue
                actions.append({"intent_id": intent_id, "coid": coid,
                                "from": local_state.value, "to": new_state,
                                "action": "COMPLETED_SEND_ONCE", "sent": True})
            elif local_state in (OrderState.UNKNOWN, OrderState.SUBMITTING):
                self.journal.halt_new_risk(self.environment.value, self.account_id,
                                           f"unresolvable {coid}")
                actions.append({"intent_id": intent_id, "coid": coid,
                                "from": local_state.value, "to": local_state.value,
                                "action": "HALT_NEW_RISK", "sent": False})
            else:
                actions.append({"intent_id": intent_id, "coid": coid,
                                "from": local_state.value, "to": local_state.value,
                                "action": "NO_BROKER_RECORD", "sent": False})

        if operator_release_halt and self.journal.is_halted(self.environment.value, self.account_id):
            self.journal.clear_halt(self.environment.value, self.account_id,
                                    operator="explicit-operator-release")
        return {"recovered": len(actions), "actions": actions}

    # ---------------- internals ----------------
    def _send_once(self, intent: OrderIntent, epoch: int, broker: BrokerAdapter,
                   attempt_id: Optional[int]) -> str:
        """The single network send of this intent's lifecycle. All outcomes are
        persisted before returning/raising."""
        try:
            snapshot = broker.submit_order(intent, epoch)
        except UnknownStateError:
            if attempt_id is not None:
                self.journal.resolve_attempt(attempt_id, "UNKNOWN", self._now())
            self.journal.set_state(intent.intent_id, OrderState.UNKNOWN, self._now())
            self.journal.halt_new_risk(self.environment.value, self.account_id,
                                       f"unresolved submission {intent.client_order_id}")
            return OrderState.UNKNOWN.value
        except ConnRefusedError:
            if attempt_id is not None:
                self.journal.resolve_attempt(attempt_id, "CONN_REFUSED", self._now())
            self.journal.set_state(intent.intent_id, OrderState.CANCELED, self._now())
            return OrderState.CANCELED.value  # provably not at broker
        except TransientRejectError:
            if attempt_id is not None:
                self.journal.resolve_attempt(attempt_id, "REJECTED", self._now())
            self.journal.set_state(intent.intent_id, OrderState.REJECTED, self._now())
            return OrderState.REJECTED.value
        except (FenceRejectedError, EnvironmentMismatchError):
            # refused BEFORE reaching the broker: provable absence → safe abort
            if attempt_id is not None:
                self.journal.resolve_attempt(attempt_id, "GATEWAY_REJECTED", self._now())
            self.journal.set_state(intent.intent_id, OrderState.CANCELED, self._now())
            raise

        # broker accepted; persist adopted state before telling the caller
        self._adopt_snapshot(intent.intent_id, snapshot)
        if attempt_id is not None:
            self.journal.resolve_attempt(attempt_id, "OK", self._now())
        return snapshot.state.value

    def _load_intent(self, row: dict) -> OrderIntent:
        # journal rows carry everything needed to rebuild a sendable intent
        detail = self.journal.conn.execute(
            "SELECT intent_id, environment, account_id, symbol, side, qty, created_at_utc"
            " FROM intents WHERE intent_id=?", (row["intent_id"],)).fetchone()
        return OrderIntent(
            intent_id=detail[0], environment=Environment(detail[1]), account_id=detail[2],
            symbol=detail[3], side=detail[4], qty=Decimal(detail[5]),
            created_at_utc=detail[6],
        )

    def _adopt_snapshot(self, intent_id: str, snap: BrokerOrderSnapshot) -> None:
        current = self.journal.get_intent_state(intent_id)
        for ev in snap.events:
            self.journal.record_event(ev.event_id, ev.client_order_id, ev.new_state.value,
                                      str(ev.filled_qty),
                                      str(ev.avg_price) if ev.avg_price is not None else None,
                                      self._now())
        if snap.state.value != current:
            # reconciliation adopts broker truth directly (evidence-backed write,
            # bypasses single-step legality; broker event order preserved by seq)
            self.journal.conn.execute("BEGIN IMMEDIATE")
            self.journal.conn.execute(
                "UPDATE intents SET state=?, updated_at_utc=? WHERE intent_id=?",
                (snap.state.value, self._now(), intent_id),
            )
            self.journal.conn.commit()
