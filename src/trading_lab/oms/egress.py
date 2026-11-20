"""The single trusted Broker Egress — every order write in the platform
passes through this class, and (since M2-RESIDUAL-SAFETY-GATE-001 R2) a
write is only attempted when the authoritative journal proves a durable,
sealed, fence-matching send eligibility. Order of defence:

1. fencing token valid (epoch/lease/account, pre-call)
2. journal-backed send eligibility: SUBMITTING intent + SUBMITTING attempt
   at THIS fence epoch + exact field binding + approval seal re-verified
3. port call
4. fencing re-validation AFTER the port call (R6 TOCTOU): a superseded
   writer's result is never adopted — the OMS maps the raised FenceError to
   HALT_NEW_RISK.

Honest boundary: step 2 proves durable authorization in OUR journal; it is
not broker-side fencing. No network code exists here.
"""

from __future__ import annotations

import datetime as dt
import json
from decimal import Decimal
from typing import Any, Callable

from ..brokers.port import BrokerError, BrokerPort, CancelReceipt, OrderLookup, SubmitReceipt
from ..contracts import Environment
from ..security.approval import ApprovalSecrets, build_send_binding, seal_is_valid
from ..security.audit import AuditLog
from .fence import FenceCoordinator, FenceError, FenceToken
from .journal import OrderJournal

NowFn = Callable[[], dt.datetime]


class EgressRefusalError(RuntimeError):
    """Raised when a write lacks durable journal-backed send eligibility
    (R2): no persisted intent/attempt match, fields mismatch, the approval
    seal does not verify, or the journal is unavailable. Fail-closed — the
    port is never called."""


class BrokerEgress:
    def __init__(
        self,
        port: BrokerPort,
        fence: FenceCoordinator,
        audit: AuditLog,
        now_fn: NowFn,
        journal: OrderJournal | None = None,
        approval_secrets: ApprovalSecrets | None = None,
    ) -> None:
        self._port = port
        self._fence = fence
        self._audit = audit
        self._now_fn = now_fn
        # R2: journal + secrets are REQUIRED for write eligibility. Assembly
        # without them refuses every write (fail-closed by absence).
        self._journal = journal
        self._approval_secrets = approval_secrets

    def _validated(self, token: FenceToken, action: str, coid: str) -> None:
        try:
            self._fence.validate(token, self._now_fn())
        except FenceError as exc:
            self._audit.append(
                "EGRESS_WRITE_REFUSED",
                {"action": action, "client_order_id": coid, "reason": str(exc)},
            )
            raise

    def _assert_still_current(self, token: FenceToken, action: str, coid: str) -> None:
        """R6 TOCTOU: re-validate AFTER the port call returns. Another
        process acquiring a higher epoch during the call means this writer
        was superseded in flight — its result must not be adopted (the OMS
        maps the raised FenceError to HALT_NEW_RISK)."""
        try:
            self._fence.validate(token, self._now_fn())
        except FenceError as exc:
            self._audit.append(
                "EGRESS_FENCE_SUPERSEDED_DURING_CALL",
                {"action": action, "client_order_id": coid, "reason": str(exc)},
            )
            raise

    def _refuse(self, coid: str, reason: str) -> None:
        self._audit.append(
            "EGRESS_SEND_REFUSED_NO_INTENT",
            {"client_order_id": coid, "reason": reason},
        )
        raise EgressRefusalError(reason)

    def _check_send_eligibility(self, token: FenceToken, coid: str,
                                symbol: str, side: str, quantity: Decimal) -> dict[str, Any]:
        """R2: durable send eligibility from the authoritative journal."""
        if self._journal is None or self._approval_secrets is None:
            self._refuse(coid, "EGRESS_NOT_ASSEMBLED_WITH_JOURNAL")
        env_value = str(self._fence._env)  # noqa: SLF001 - own coordinator
        account_value = self._fence._account  # noqa: SLF001 - own coordinator
        try:
            row = self._journal.claim_send_attempt(
                coid, token.epoch, symbol, side, str(quantity),
                env_value, account_value,
            )
        except Exception as exc:  # journal unavailable => refuse, never bypass
            self._refuse(coid, f"JOURNAL_UNAVAILABLE:{type(exc).__name__}")
        if row is None:
            self._refuse(coid, "NO_ELIGIBLE_OR_ALREADY_CLAIMED")
        decision = json.loads(row["risk_decision_json"])
        snap = decision.get("limits_snapshot", {})
        for key in ("approval_seal", "decision_expires_at"):
            if key not in snap:
                self._refuse(coid, "DECISION_UNSEALED")
        binding = build_send_binding(
            intent_payload=json.loads(row["payload_json"]),
            symbol=symbol,
            side=side,
            quantity=str(quantity),
            # Normalize stored timestamps back to the engine's isoformat
            # (+00:00) convention — journal JSON stores Z-form.
            policy_hash=decision["policy_hash"],
            decision_at=dt.datetime.fromisoformat(decision["decision_at"]).isoformat(),
            expires_at=dt.datetime.fromisoformat(snap["decision_expires_at"]).isoformat(),
        )
        if not seal_is_valid(self._approval_secrets, binding, snap["approval_seal"]):
            self._refuse(coid, "DECISION_SEAL_INVALID")
        return row

    def submit(
        self,
        token: FenceToken,
        client_order_id: str,
        symbol: str,
        quantity: Decimal,
        side: str,
    ) -> SubmitReceipt:
        self._validated(token, "submit", client_order_id)
        self._check_send_eligibility(token, client_order_id, symbol, side, quantity)
        try:
            receipt = self._port.submit_order(client_order_id, symbol, quantity, side, token.epoch)
            self._assert_still_current(token, "submit", client_order_id)
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
        """Read-only: no fence or eligibility required."""
        return self._port.get_order(client_order_id)

    def cancel(
        self,
        token: FenceToken,
        client_order_id: str,
    ) -> CancelReceipt:
        self._validated(token, "cancel", client_order_id)
        # R2: cancels also require the intent to exist durably in the journal.
        if self._journal is None or not self._journal.intent_exists(client_order_id):
            self._refuse(client_order_id, "CANCEL_NO_PERSISTED_INTENT")
        try:
            receipt = self._port.cancel_order(client_order_id, token.epoch)
            self._assert_still_current(token, "cancel", client_order_id)
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
