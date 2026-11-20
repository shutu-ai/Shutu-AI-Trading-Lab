"""Local FakeBroker — deterministic, offline, fault-injectable.

Test evidence only: its dedupe/behavior proves NOTHING about real Alpaca
(BROKER_BEHAVIOR_UNVERIFIED). Fault schedules let tests inject, per
client_order_id / call ordinal:

- ``ack_lost``      : order created, answer lost (submit raises BrokerError)
- ``submit_timeout``: request may have arrived, no answer (BrokerError)
- ``get_none``      : get_order暂时查无 (delivery state genuinely unknown)
- ``get_5xx``       : get_order raises BrokerError
- ``cancel_lost``   : cancel delivered, answer lost
- ``late_order``    : order only visible in get_order after N get calls
- ``duplicate_fill``: emit an extra fill event for the same order

The broker records ``created_orders_by_intent`` — the fault-injection
suite's core counter (OMS must never push this above 1 per intent).
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from .port import BrokerError, BrokerPort, CancelReceipt, OrderLookup, SubmitReceipt


class FakeBroker(BrokerPort):
    def __init__(self) -> None:
        # coid -> {"state": ..., "filled": Decimal, "events": [event_id...]}
        self._orders: dict[str, dict[str, Any]] = {}
        self._created: dict[str, int] = {}
        self._faults: dict[tuple[str, str], list[Any]] = {}
        self._call_ordinal: dict[str, int] = {}
        self._get_calls = 0
        self._event_seq = 0

    # -- fault scheduling ----------------------------------------------------

    _OP_FOR_FAULT = {
        "ack_lost": "submit",
        "submit_timeout": "submit",
        "reject": "submit",
        "none": "get",
        "5xx": "get",
        "cancel_lost": "cancel",
    }

    def schedule_fault(self, fault_kind: str, coid: str, at_ordinal: int = 1) -> None:
        """Schedule a fault for the coid's Nth call of the owning operation."""
        op = self._OP_FOR_FAULT[fault_kind]
        self._faults.setdefault((op, coid), []).append((at_ordinal, fault_kind))

    def _pop_fault(self, op: str, coid: str, ordinal: int) -> str | None:
        queue = self._faults.get((op, coid), [])
        for i, (at, fault_kind) in enumerate(queue):
            if at <= ordinal:
                queue.pop(i)
                return fault_kind
        return None

    def _ordinal(self, coid: str, op: str) -> int:
        key = f"{op}:{coid}"
        self._call_ordinal[key] = self._call_ordinal.get(key, 0) + 1
        return self._call_ordinal[key]

    # -- port implementation ---------------------------------------------------

    def submit_order(
        self,
        client_order_id: str,
        symbol: str,
        quantity: Decimal,
        side: str,
        fence_epoch: int,
    ) -> SubmitReceipt:
        ordinal = self._ordinal(client_order_id, "submit")
        fault = self._pop_fault("submit", client_order_id, ordinal)
        if fault == "ack_lost":
            # Order IS created broker-side; the answer is lost in transit.
            self._create(client_order_id, symbol, quantity, side)
            raise BrokerError("ack lost in transit (order may exist broker-side)")
        if fault == "submit_timeout":
            # Unknown whether the broker received it.
            raise BrokerError("submit timeout (delivery state unknown)")
        if fault == "reject":
            return SubmitReceipt(delivered=True, acknowledged=False, broker_order_id=None,
                                 raw={"reason": "synthetic_reject"})
        self._create(client_order_id, symbol, quantity, side)
        return SubmitReceipt(
            delivered=True,
            acknowledged=True,
            broker_order_id=f"BRK-{client_order_id}",
            raw={"epoch_seen": fence_epoch},
        )

    def _create(self, coid: str, symbol: str, quantity: Decimal, side: str) -> None:
        self._created[coid] = self._created.get(coid, 0) + 1
        self._orders[coid] = {
            "state": "ACKED",
            "filled": Decimal(0),
            "symbol": symbol,
            "side": side,
            "qty": quantity,
            "events": [self._event("ACK")],
        }

    def _event(self, kind: str) -> str:
        self._event_seq += 1
        return f"EVT-{self._event_seq}-{kind}"

    def get_order(self, client_order_id: str) -> OrderLookup:
        self._get_calls += 1
        ordinal = self._ordinal(client_order_id, "get")
        fault = self._pop_fault("get", client_order_id, ordinal)
        if fault == "none":
            return OrderLookup(found=False)  # 暂时查无 — NOT proof of non-delivery
        if fault == "5xx":
            raise BrokerError("get_order 5xx")
        order = self._orders.get(client_order_id)
        if order is None:
            return OrderLookup(found=False)
        return OrderLookup(found=True, state=order["state"], filled_qty=order["filled"])

    def cancel_order(self, client_order_id: str, fence_epoch: int) -> CancelReceipt:
        ordinal = self._ordinal(client_order_id, "cancel")
        fault = self._pop_fault("cancel", client_order_id, ordinal)
        order = self._orders.get(client_order_id)
        if order is None:
            return CancelReceipt(delivered=True, acknowledged=False, cancelled=False)
        if fault == "cancel_lost":
            order["state"] = "CANCEL_PENDING"
            order["events"].append(self._event("CANCEL_PENDING"))
            raise BrokerError("cancel ack lost")
        order["state"] = "CANCELLED"
        order["events"].append(self._event("CANCELLED"))
        return CancelReceipt(delivered=True, acknowledged=True, cancelled=True)

    # -- test helpers --------------------------------------------------------

    def apply_fill(self, client_order_id: str, qty: Decimal, duplicate: bool = False) -> str:
        """Simulate an execution report (optionally a duplicate event)."""
        order = self._orders[client_order_id]
        if duplicate:
            event_id = order["events"][-1]  # same event id replayed
            return event_id
        self._event_seq += 1
        event_id = f"EVT-{self._event_seq}-FILL"
        order["filled"] += qty
        if order["filled"] >= order["qty"]:
            order["state"] = "FILLED"
        else:
            order["state"] = "PARTIALLY_FILLED"
        order["events"].append(event_id)
        return event_id

    def late_order_appears(self, client_order_id: str, symbol: str, quantity: Decimal, side: str) -> None:
        """A 'lost' submit turns out to have been received after all."""
        if client_order_id not in self._orders:
            self._create(client_order_id, symbol, quantity, side)

    @property
    def get_call_count(self) -> int:
        return self._get_calls

    def created_orders_by_intent(self, client_order_id: str) -> int:
        return self._created.get(client_order_id, 0)

    def total_created(self) -> int:
        return sum(self._created.values())


__all__ = ["FakeBroker"]
