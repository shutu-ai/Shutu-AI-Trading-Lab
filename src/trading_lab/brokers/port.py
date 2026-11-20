"""Broker write port — the ONLY interface through which orders reach a
broker. M2 ships exactly one implementation: the local FakeBroker. Real
Alpaca adapters are out of scope and remain BROKER_BEHAVIOR_UNVERIFIED.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from typing import Any


class BrokerError(RuntimeError):
    """Transport-level fault surfaced by the port (timeout, 5xx, partition)."""


@dataclass(frozen=True)
class SubmitReceipt:
    """What the broker returned for one submit attempt. ``delivered``
    distinguishes provable facts (the broker accepted/acknowledged) from
    unknown outcomes (request may have arrived, answer lost)."""

    delivered: bool                       # False = request never reached broker (provable)
    acknowledged: bool | None             # True/False when answer received; None = unknown
    broker_order_id: str | None
    raw: dict[str, Any] | None = None     # raw ack payload (test evidence)


@dataclass(frozen=True)
class OrderLookup:
    found: bool                           # False =暂时查无 (NOT proof of non-delivery)
    state: str | None = None              # ACKED/FILLED/... when found
    filled_qty: Decimal | None = None


@dataclass(frozen=True)
class CancelReceipt:
    delivered: bool
    acknowledged: bool | None
    cancelled: bool | None = None


class BrokerPort:
    """Abstract port; concrete impls must be deterministic and offline."""

    def submit_order(
        self,
        client_order_id: str,
        symbol: str,
        quantity: Decimal,
        side: str,
        fence_epoch: int,
    ) -> SubmitReceipt:  # pragma: no cover - interface
        raise NotImplementedError

    def get_order(self, client_order_id: str) -> OrderLookup:  # pragma: no cover
        raise NotImplementedError

    def cancel_order(self, client_order_id: str, fence_epoch: int) -> CancelReceipt:  # pragma: no cover
        raise NotImplementedError

    def created_orders_by_intent(self, client_order_id: str) -> int:  # pragma: no cover
        """Test-observability: how many times THIS coid actually created a
        broker order. The OMS is forbidden from relying on broker-side
        dedupe — tests assert this count is <= 1 per intent."""
        raise NotImplementedError


__all__ = ["BrokerError", "BrokerPort", "CancelReceipt", "OrderLookup", "SubmitReceipt"]
