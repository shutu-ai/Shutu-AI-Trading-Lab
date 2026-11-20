"""Broker plane: the single write port and its M2 fake implementation.

No network code exists here. Real Alpaca adapters are out of M2 scope and
remain BROKER_BEHAVIOR_UNVERIFIED until a user-authorized Paper phase.
"""

from .fake import FakeBroker
from .port import (
    BrokerError,
    BrokerPort,
    CancelReceipt,
    OrderLookup,
    SubmitReceipt,
)

__all__ = [
    "BrokerError",
    "BrokerPort",
    "CancelReceipt",
    "FakeBroker",
    "OrderLookup",
    "SubmitReceipt",
]
