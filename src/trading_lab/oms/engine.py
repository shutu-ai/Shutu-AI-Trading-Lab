"""The single OMS: durable intents, journal-before-send, UNKNOWN semantics,
recovery with reconciliation.

Invariants (fault-injection suite asserts each):

- INV-1 journal-before-send: an intent + SUBMITTING attempt commit atomically
  BEFORE the egress call; journal failure => zero sends.
- INV-2 UNKNOWN never resends: any submit fault (ack lost / timeout / later
  get_order None) leaves the intent UNKNOWN + HALT_NEW_RISK; there is no
  resend path, no substitute intent, no coid replacement, no UNKNOWN cleanup.
- INV-3 single writer: every egress write validates the fence; stale
  executors get zero accepted broker writes.
- INV-4 fills are idempotent by broker event id; duplicates never double-count.
- INV-5 recovery reconciles against the broker before any new risk; operator
  unlock is mandatory after UNKNOWN/HALT.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Callable

from ..brokers.port import BrokerError
from ..contracts import Environment, RiskDecision, TradeIntent
from ..security.audit import AuditLog
from ..security.kill_switch import KillSwitch
from .egress import BrokerEgress
from .fence import FenceCoordinator, FenceError, FenceToken
from .journal import JournalError, OrderJournal
from .states import validate_transition

NowFn = Callable[[], dt.datetime]


class OmsError(RuntimeError):
    pass


@dataclass(frozen=True)
class SubmitOutcome:
    intent_id: str
    state: str                # ACKED / REJECTED / UNKNOWN / HALT_NEW_RISK / FAILED_PERSISTENCE
    delivered: bool
    acknowledged: bool | None
    halted: bool


@dataclass(frozen=True)
class RecoveryReport:
    reconciled: tuple[str, ...]        # intent_ids adopted from broker state
    still_unknown: tuple[str, ...]     # intents left UNKNOWN (no proof either way)
    halted: bool


class OmsEngine:
    def __init__(
        self,
        environment: Environment,
        account_id: str,
        journal: OrderJournal,
        egress: BrokerEgress,
        fence: FenceCoordinator,
        audit: AuditLog,
        kill_switch: KillSwitch,
        now_fn: NowFn,
    ) -> None:
        self._env = environment
        self._account = account_id
        self._journal = journal
        self._egress = egress
        self._fence = fence
        self._audit = audit
        self._ks = kill_switch
        self._now_fn = now_fn

    # ------------------------------------------------------------------
    # submit path (INV-1, INV-2)
    # ------------------------------------------------------------------

    def submit(
        self,
        intent: TradeIntent,
        decision: RiskDecision,
        symbol: str,
        side: str,
        quantity: Decimal,
        token: FenceToken,
    ) -> SubmitOutcome:
        intent_id = intent.intent_id
        coid = intent.deterministic_client_order_id

        # Defense in depth: the risk engine gates normally, but the OMS also
        # refuses outright while a halt is engaged (fault class "kill switch").
        if self._ks.is_halted():
            self._audit.append(
                "OMS_SUBMIT_REFUSED_HALTED",
                {"intent_id": intent_id, "client_order_id": coid},
            )
            return SubmitOutcome(intent_id, "HALT_NEW_RISK", False, None, halted=True)

        # INV-1: journal-first. Any persistence failure => zero sends.
        try:
            self._journal.record_intent(
                intent_id=intent_id,
                client_order_id=coid,
                environment=str(intent.environment),
                account_id=intent.account_id,
                symbol=symbol,
                side=side,
                quantity=str(quantity),
                payload=intent.model_dump(mode="json"),
                risk_decision=decision.model_dump(mode="json"),
                state="NEW_INTENT",
            )
            validate_transition("NEW_INTENT", "PERSISTED")
            self._journal.set_state(intent_id, "PERSISTED")
            attempt_id = uuid.uuid4().hex
            validate_transition("PERSISTED", "SUBMITTING")
            self._journal.mark_submitting(intent_id, attempt_id, token.epoch)
        except JournalError as exc:
            self._audit.append(
                "OMS_PERSISTENCE_FAULT",
                {"intent_id": intent_id, "error": str(exc)},
            )
            return SubmitOutcome(intent_id, "FAILED_PERSISTENCE", False, None, halted=True)

        # Fence re-validation inside the egress (INV-3); the token was acquired
        # by the caller through the coordinator.
        try:
            receipt = self._egress.submit(token, coid, symbol, quantity, side)
        except FenceError:
            # provably never reached the broker; intent stays PERSISTED/
            # SUBMITTING in journal — reconciliation decides its fate.
            self._journal.set_state(intent_id, "HALT_NEW_RISK")
            return SubmitOutcome(intent_id, "HALT_NEW_RISK", False, None, halted=True)
        except BrokerError:
            # INV-2: answer lost / timeout / delivery unknown => UNKNOWN,
            # HALT_NEW_RISK; absolutely no resend from here.
            validate_transition("SUBMITTING", "UNKNOWN")
            self._journal.set_state(intent_id, "UNKNOWN")
            validate_transition("UNKNOWN", "HALT_NEW_RISK")
            self._journal.set_state(intent_id, "HALT_NEW_RISK")
            self._ks.set(reason=f"UNKNOWN outcome for {coid}", operator_id="oms-engine")
            self._audit.append(
                "OMS_UNKNOWN_HALT",
                {"intent_id": intent_id, "client_order_id": coid},
            )
            try:
                self._journal.finish_attempt(attempt_id, "UNKNOWN", {"outcome": "unknown"})
            except JournalError:
                pass  # audit already records the fault; recovery reconciles
            return SubmitOutcome(intent_id, "UNKNOWN", False, None, halted=True)

        if receipt.acknowledged is True:
            validate_transition("SUBMITTING", "ACKED")
            self._journal.set_state(intent_id, "ACKED", bump_version=True)
            self._journal.finish_attempt(attempt_id, "SENT", {"receipt": receipt.raw or {}})
            return SubmitOutcome(intent_id, "ACKED", True, True, halted=False)
        if receipt.acknowledged is False:
            # provably delivered AND refused by the broker: terminal rejection.
            validate_transition("SUBMITTING", "REJECTED")
            self._journal.set_state(intent_id, "REJECTED")
            self._journal.finish_attempt(attempt_id, "SENT", {"rejected": True})
            return SubmitOutcome(intent_id, "REJECTED", True, False, halted=False)
        # acknowledged None with delivered True is not produced by the fake
        # port; treat defensively as UNKNOWN.
        validate_transition("SUBMITTING", "UNKNOWN")
        self._journal.set_state(intent_id, "UNKNOWN")
        return SubmitOutcome(intent_id, "UNKNOWN", True, None, halted=True)

    # ------------------------------------------------------------------
    # fills (INV-4): idempotent by broker event id
    # ------------------------------------------------------------------

    def process_fill(self, intent_id: str, broker_event_id: str, qty: Decimal) -> bool:
        if self._journal.seen_broker_event(broker_event_id):
            self._audit.append(
                "OMS_DUPLICATE_FILL_IGNORED",
                {"intent_id": intent_id, "broker_event_id": broker_event_id},
            )
            return False
        state = self._journal.state_of(intent_id)
        target = "FILLED" if state == "ACKED" or state == "PARTIALLY_FILLED" else state
        if target != state:
            validate_transition(state, target)
        self._journal.record_broker_event(intent_id, broker_event_id, "FILL", {"qty": str(qty)})
        return True

    # ------------------------------------------------------------------
    # recovery (INV-2/INV-5)
    # ------------------------------------------------------------------

    def recover(self, now: dt.datetime) -> RecoveryReport:
        """Acquire a fresh fence (invalidating all older instances), halt new
        risk, then reconcile every open intent against the broker.

        A missing broker order is NOT proof of non-delivery: such intents
        stay UNKNOWN/HALT pending operator unlock. Only broker-confirmed
        states are adopted."""
        token = self._fence.acquire(now)  # fresh epoch: old executors invalidated
        self._ks.set(reason="recovery: reconciliation required", operator_id="oms-engine")
        reconciled: list[str] = []
        still_unknown: list[str] = []
        for row in self._journal.open_intents():
            intent_id, coid = row["intent_id"], row["client_order_id"]
            if row["state"] in ("FILLED", "CANCELLED", "REJECTED", "RECONCILED"):
                continue
            lookup = self._egress.get_order(coid)
            if lookup.found and lookup.state in ("FILLED", "CANCELLED", "ACKED"):
                validate_transition(row["state"], "RECONCILED")
                self._journal.set_state(intent_id, "RECONCILED", bump_version=True)
                reconciled.append(intent_id)
            else:
                # get_order not found is NOT proof of non-delivery.
                still_unknown.append(intent_id)
        self._audit.append(
            "OMS_RECOVERY",
            {"reconciled": reconciled, "still_unknown": still_unknown,
             "new_epoch": token.epoch},
        )
        return RecoveryReport(reconciled=tuple(reconciled), still_unknown=tuple(still_unknown), halted=True)

    def operator_unlock(self, operator_id: str, authorization_ref: str) -> None:
        """After reconciliation, only an explicit human unlock resumes risk."""
        self._ks.clear(operator_id=operator_id, authorization_ref=authorization_ref)


__all__ = ["OmsEngine", "OmsError", "RecoveryReport", "SubmitOutcome"]
