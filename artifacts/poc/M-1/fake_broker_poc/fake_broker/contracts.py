"""Order/broker contracts for the M-1 fake-broker POC.

These mirror the semantics the production system needs (Architecture doc §6.1),
scaled down to the minimum needed to evaluate open-source choices:
- explicit order state machine with legal transitions only,
- deterministic client_order_id derived from a durable intent,
- (environment, account) namespace binding so a Paper executor can never
  address a Live account and vice versa.

Money/quantity types are Decimal per §2.2.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Optional, Protocol


class Environment(str, Enum):
    PAPER = "PAPER"
    LIVE = "LIVE"  # never instantiated in M-1 except as an isolated mock


class OrderState(str, Enum):
    PREPARED = "PREPARED"
    SUBMITTING = "SUBMITTING"
    ACK = "ACK"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCEL_PENDING = "CANCEL_PENDING"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"

    @property
    def terminal(self) -> bool:
        return self in (OrderState.FILLED, OrderState.CANCELED, OrderState.REJECTED)


#: legal forward transitions (single-step). Reconciliation may adopt any broker
#: snapshot; local writes must follow these edges.
LEGAL_TRANSITIONS: dict[OrderState, set[OrderState]] = {
    OrderState.PREPARED: {OrderState.SUBMITTING, OrderState.REJECTED, OrderState.CANCELED},
    OrderState.SUBMITTING: {OrderState.ACK, OrderState.REJECTED, OrderState.UNKNOWN,
                            OrderState.CANCELED},  # provably-never-reached-broker abort
    OrderState.UNKNOWN: {OrderState.ACK, OrderState.PARTIALLY_FILLED, OrderState.FILLED,
                         OrderState.CANCELED, OrderState.REJECTED},  # only via reconciliation evidence
    OrderState.ACK: {OrderState.PARTIALLY_FILLED, OrderState.FILLED, OrderState.CANCEL_PENDING,
                     OrderState.CANCELED, OrderState.REJECTED},
    OrderState.PARTIALLY_FILLED: {OrderState.PARTIALLY_FILLED, OrderState.FILLED,
                                  OrderState.CANCEL_PENDING, OrderState.CANCELED, OrderState.REJECTED},
    OrderState.CANCEL_PENDING: {OrderState.CANCELED, OrderState.FILLED, OrderState.PARTIALLY_FILLED,
                                OrderState.REJECTED},
    # terminal states have no outgoing edges
    OrderState.FILLED: set(),
    OrderState.CANCELED: set(),
    OrderState.REJECTED: set(),
}


def is_legal_transition(old: OrderState, new: OrderState) -> bool:
    return new in LEGAL_TRANSITIONS.get(old, set())


def deterministic_client_order_id(environment: Environment, account_id: str, intent_id: str) -> str:
    """Deterministic per (environment, account, intent) — replay-safe."""
    digest = hashlib.sha256(f"{environment.value}|{account_id}|{intent_id}".encode()).hexdigest()[:24]
    return f"TBL-{environment.value}-{digest}"


@dataclass(frozen=True)
class OrderIntent:
    intent_id: str
    environment: Environment
    account_id: str
    symbol: str
    side: str  # BUY / SELL
    qty: Decimal
    created_at_utc: str  # ISO-8601, injected clock (deterministic tests)
    payload_hash: str = ""
    client_order_id: str = ""

    def __post_init__(self) -> None:
        if not self.client_order_id:
            object.__setattr__(self, "client_order_id",
                               deterministic_client_order_id(self.environment, self.account_id, self.intent_id))
        if not self.payload_hash:
            payload = f"{self.symbol}|{self.side}|{self.qty}|{self.intent_id}"
            object.__setattr__(self, "payload_hash", hashlib.sha256(payload.encode()).hexdigest())

    def validate(self) -> None:
        if self.qty <= 0:
            raise ValueError(f"qty must be > 0, got {self.qty}")  # SDK does not validate this (see alpaca finding)


@dataclass(frozen=True)
class BrokerEvent:
    event_id: str            # broker-assigned, globally unique per broker
    client_order_id: str
    new_state: OrderState
    filled_qty: Decimal
    avg_price: Optional[Decimal]
    event_time_utc: str


@dataclass
class BrokerOrderSnapshot:
    client_order_id: str
    state: OrderState
    filled_qty: Decimal
    avg_price: Optional[Decimal]
    events: list[BrokerEvent] = field(default_factory=list)


class SubmitOutcome:
    OK = "OK"
    UNKNOWN = "UNKNOWN"            # sent, no confirmation (response lost / timeout)
    CONN_REFUSED = "CONN_REFUSED"  # not processed by broker (safe-failed)
    REJECTED = "REJECTED"          # broker rejected the order (terminal)
    FENCE_REJECTED = "FENCE_REJECTED"
    ENV_MISMATCH = "ENV_MISMATCH"
    DUPLICATE = "DUPLICATE"        # OMS-side duplicate intent


class BrokerAdapter(Protocol):
    """The seam the production system will implement against Alpaca (ADR-001)."""

    def submit_order(self, intent: OrderIntent, fence_epoch: int) -> BrokerOrderSnapshot:
        ...

    def get_order(self, client_order_id: str) -> Optional[BrokerOrderSnapshot]:
        ...

    def submission_count(self) -> int:
        ...
