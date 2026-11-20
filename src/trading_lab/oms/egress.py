"""The single trusted Broker Egress — every order write in the platform
passes through this class; it validates the fencing token BEFORE calling
the port, so a stale executor can never reach the broker even if the
downstream mock would accept anything.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Callable

from ..brokers.port import BrokerError, BrokerPort, CancelReceipt, OrderLookup, SubmitReceipt
from ..contracts import Environment
from ..security.audit import AuditLog
from .fence import FenceCoordinator, FenceError, FenceToken

NowFn = Callable[[], dt.datetime]


class BrokerEgress:
    def __init__(
        self,
        port: BrokerPort,
        fence: FenceCoordinator,
        audit: AuditLog,
        now_fn: NowFn,
    ) -> None:
        self._port = port
        self._fence = fence
        self._audit = audit
        self._now_fn = now_fn

    def _validated(self, token: FenceToken, action: str, coid: str) -> None:
        try:
            self._fence.validate(token, self._now_fn())
        except FenceError as exc:
            self._audit.append(
                "EGRESS_WRITE_REFUSED",
                {"action": action, "client_order_id": coid, "reason": str(exc)},
            )
            raise

    def submit(
        self,
        token: FenceToken,
        client_order_id: str,
        symbol: str,
        quantity: Decimal,
        side: str,
    ) -> SubmitReceipt:
        self._validated(token, "submit", client_order_id)
        try:
            receipt = self._port.submit_order(client_order_id, symbol, quantity, side, token.epoch)
        except BrokerError as exc:
            self._audit.append(
                "EGRESS_SUBMIT_FAULT",
                {"client_order_id": client_order_id, "error": str(exc)},
            )
            raise
        self._audit.append(
            "EGRESS_SUBMIT",
            {"client_order_id": client_order_id, "delivered": receipt.delivered,
             "acknowledged": receipt.acknowledged},
        )
        return receipt

    def get_order(self, client_order_id: str) -> OrderLookup:
        """Read-only: no fence required (retry budget applies to reads)."""
        return self._port.get_order(client_order_id)

    def cancel(self, token: FenceToken, client_order_id: str) -> CancelReceipt:
        self._validated(token, "cancel", client_order_id)
        try:
            receipt = self._port.cancel_order(client_order_id, token.epoch)
        except BrokerError as exc:
            self._audit.append(
                "EGRESS_CANCEL_FAULT",
                {"client_order_id": client_order_id, "error": str(exc)},
            )
            raise
        self._audit.append(
            "EGRESS_CANCEL",
            {"client_order_id": client_order_id, "cancelled": receipt.cancelled},
        )
        return receipt


__all__ = ["BrokerEgress"]
