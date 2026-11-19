"""Deterministic fake broker with configurable fault injection.

Persists order state to a JSON file so that a "broker restart" (fresh instance
on the same file) preserves orders — reconciliation tests are then meaningful.
Faults are injected via an explicit per-client_order_id schedule (deterministic,
seeded by the test, never random at runtime).

Fault vocabulary (applied at submit_order time):
  before_ack_drop      : order IS processed server-side, response never delivered
  conn_refused         : request never reaches the processing layer
  transient_5xx        : broker rejects before creating any order
  partial_then_stall   : ACK + partial fill delivered, remainder stalls until
                         deliver_pending_fills() is called
"""
from __future__ import annotations

import json
import threading
from decimal import Decimal
from pathlib import Path
from typing import Optional

from .contracts import (BrokerEvent, BrokerOrderSnapshot, Environment,
                        OrderIntent, OrderState)


class FakeBrokerError(Exception):
    pass


class UnknownStateError(FakeBrokerError):
    """Raised when the outcome of a submission cannot be confirmed locally."""


class ConnRefusedError(FakeBrokerError):
    """Raised when the broker provably did not process the request."""


class TransientRejectError(FakeBrokerError):
    """5xx-style transient rejection; no order was created."""


class EnvironmentMismatchError(FakeBrokerError):
    pass


class FenceRejectedError(FakeBrokerError):
    pass


class FakeBroker:
    def __init__(self, environment: Environment, account_id: str, store_path: Path,
                 clock=None, valid_fences: Optional[set[int]] = None):
        """valid_fences: set of epochs the (single-writer gateway) accepts.
        In production this is the Broker Gateway holding the current fencing
        epoch; here tests pass the current epoch(s) explicitly.
        (environment, account) is immutable after construction — there is no
        boolean Paper→Live promotion path on the adapter."""
        self._environment = environment
        self._account_id = account_id
        self.store_path = Path(store_path)
        self.clock = clock or (lambda: "2026-01-02T15:00:00Z")
        self.valid_fences = valid_fences  # None => gateway disabled (single host mode)
        self._lock = threading.Lock()
        self._state: dict = {"orders": {}, "events": [], "event_seq": 0, "submissions": 0,
                             "stalled": {}}
        if self.store_path.exists():
            self._state = json.loads(self.store_path.read_text())
        self.fault_schedule: dict[str, list[str]] = {}
        self._stalled: dict[str, int] = {k: int(v) for k, v in self._state.get("stalled", {}).items()}

    @property
    def environment(self) -> Environment:
        return self._environment

    @property
    def account_id(self) -> str:
        return self._account_id

    # ---- persistence (server-side, survives "broker restart") ----
    def _persist(self) -> None:
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.store_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._state))
        tmp.replace(self.store_path)

    def _load_order(self, coid: str) -> Optional[dict]:
        return self._state["orders"].get(coid)

    # ---- fault helpers ----
    def schedule_fault(self, client_order_id: str, faults: list[str]) -> None:
        self.fault_schedule[client_order_id] = list(faults)

    def _pop_fault(self, coid: str) -> Optional[str]:
        faults = self.fault_schedule.get(coid)
        if faults:
            return faults.pop(0)
        return None

    # ---- gateway checks ----
    def _check_fence(self, fence_epoch: int) -> None:
        if self.valid_fences is not None and fence_epoch not in self.valid_fences:
            raise FenceRejectedError(f"stale/expired fence epoch {fence_epoch} not in {self.valid_fences}")

    # ---- adapter surface ----
    def submit_order(self, intent: OrderIntent, fence_epoch: int) -> BrokerOrderSnapshot:
        if intent.environment != self.environment or intent.account_id != self.account_id:
            raise EnvironmentMismatchError(
                f"intent targets {intent.environment.value}/{intent.account_id}, "
                f"broker is {self.environment.value}/{self.account_id}")
        self._check_fence(fence_epoch)
        fault = self._pop_fault(intent.client_order_id)

        with self._lock:
            if fault == "conn_refused":
                # provably not processed: no order created, no submission counted
                raise ConnRefusedError(f"conn refused for {intent.client_order_id}")
            if fault == "transient_5xx":
                raise TransientRejectError("503 service unavailable (no order created)")

            existing = self._load_order(intent.client_order_id)
            if existing is None:
                self._state["submissions"] += 1
                order = {
                    "client_order_id": intent.client_order_id,
                    "symbol": intent.symbol,
                    "side": intent.side,
                    "qty": str(intent.qty),
                    "state": OrderState.ACK.value,
                    "filled_qty": "0",
                    "avg_price": None,
                }
                self._state["orders"][intent.client_order_id] = order
                self._add_event(order, OrderState.ACK, Decimal("0"), None)
            else:
                order = existing

            if fault == "before_ack_drop":
                # realistic semantics: a market order fills server-side, THEN the
                # response is lost — the client must reconcile to learn the fill
                self._apply_fill(order, Decimal(intent.qty), Decimal("100.00"))
                self._persist()
                raise UnknownStateError(f"response lost for {intent.client_order_id}")

            if fault == "partial_then_stall":
                total = Decimal(intent.qty)
                half = (total / 2).quantize(Decimal("0.000001"))
                self._apply_fill(order, half, Decimal("100.00"))
                self._stalled[intent.client_order_id] = int(total - half)
                self._state["stalled"] = {k: v for k, v in self._stalled.items()}
                self._persist()
                return self._snapshot(order)

            self._apply_fill(order, Decimal(intent.qty), Decimal("100.00"))
            self._persist()
            return self._snapshot(order)

    def deliver_pending_fills(self) -> None:
        """Time passes: stalled orders finish filling."""
        with self._lock:
            for coid, remaining in list(self._stalled.items()):
                order = self._load_order(coid)
                if order is None:
                    continue
                self._apply_fill(order, Decimal(remaining), Decimal("101.00"))
            self._stalled.clear()
            self._state["stalled"] = {}
            self._persist()

    def get_order(self, client_order_id: str) -> Optional[BrokerOrderSnapshot]:
        with self._lock:
            order = self._load_order(client_order_id)
            return self._snapshot(order) if order else None

    def submission_count(self) -> int:
        with self._lock:
            return int(self._state["submissions"])

    def event_count(self) -> int:
        with self._lock:
            return len(self._state["events"])

    # ---- internals ----
    def _add_event(self, order: dict, new_state: OrderState, filled: Decimal,
                   avg_price: Optional[Decimal]) -> None:
        self._state["event_seq"] += 1
        ev = BrokerEvent(
            event_id=f"{self.environment.value}-{self._state['event_seq']:06d}",
            client_order_id=order["client_order_id"],
            new_state=new_state,
            filled_qty=filled,
            avg_price=avg_price,
            event_time_utc=self.clock(),
        )
        self._state["events"].append({
            "event_id": ev.event_id,
            "client_order_id": ev.client_order_id,
            "new_state": ev.new_state.value,
            "filled_qty": str(ev.filled_qty),
            "avg_price": str(ev.avg_price) if ev.avg_price is not None else None,
            "event_time_utc": ev.event_time_utc,
        })

    def _apply_fill(self, order: dict, fill_qty: Decimal, price: Decimal) -> None:
        prev_filled = Decimal(order["filled_qty"])
        total = Decimal(order["qty"])
        new_filled = min(prev_filled + fill_qty, total)
        prev_price = Decimal(order["avg_price"]) if order["avg_price"] else None
        if prev_price is not None and new_filled > prev_filled:
            avg = ((prev_price * prev_filled) + (price * (new_filled - prev_filled))) / new_filled
        else:
            avg = price
        order["filled_qty"] = str(new_filled)
        order["avg_price"] = str(avg)
        if new_state := (OrderState.FILLED if new_filled >= total else OrderState.PARTIALLY_FILLED):
            order["state"] = new_state.value
            self._add_event(order, new_state, new_filled, avg)

    def _snapshot(self, order: dict) -> BrokerOrderSnapshot:
        events = [
            BrokerEvent(
                event_id=e["event_id"],
                client_order_id=e["client_order_id"],
                new_state=OrderState(e["new_state"]),
                filled_qty=Decimal(e["filled_qty"]),
                avg_price=Decimal(e["avg_price"]) if e["avg_price"] else None,
                event_time_utc=e["event_time_utc"],
            )
            for e in self._state["events"] if e["client_order_id"] == order["client_order_id"]
        ]
        return BrokerOrderSnapshot(
            client_order_id=order["client_order_id"],
            state=OrderState(order["state"]),
            filled_qty=Decimal(order["filled_qty"]),
            avg_price=Decimal(order["avg_price"]) if order["avg_price"] else None,
            events=events,
        )
