"""The single OMS: durable intents, journal-before-send, UNKNOWN semantics,
recovery with reconciliation.

Invariants (fault-injection + remediation suites assert each):

- INV-1 journal-before-send: the full intent AND its SUBMITTING attempt
  commit in ONE transaction before the egress call; persistence failure
  (or a simulated crash) => zero sends.
- INV-2 UNKNOWN never resends: any submit fault (ack lost / timeout / later
  get_order None) leaves the intent UNKNOWN + HALT_NEW_RISK; there is no
  resend path, no substitute intent, no coid replacement, no UNKNOWN cleanup.
- INV-3 single writer: every egress write validates the fence before AND
  after the port call; a superseded writer's result is never adopted.
- INV-4 fills are atomic (event dedupe + cumulative quantity + state in one
  transaction); duplicates never double-count; overfills/cancelled fills
  refuse fail-closed.
- INV-5 recovery reconciles against the broker before any new risk; operator
  unlock additionally requires ZERO unresolved intents in the journal — an
  authorization string alone never clears the halt (R3).
- INV-6 (R1): a submit requires a risk decision that (a) allows, (b) is for
  THIS intent, (c) matches the pinned policy hash, (d) is time-valid, and
  (e) carries an HMAC seal binding intent+symbol+side+quantity minted by the
  RiskEngine — forged/mismatched/substituted approvals yield ZERO sends and
  are never journaled.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from typing import Callable

from ..brokers.port import BrokerError
from ..contracts import Environment, RiskDecision, TradeIntent
from ..security.audit import AuditLog
from ..security.kill_switch import KillSwitch
from ..security.approval import ApprovalSecrets, build_send_binding, seal_is_valid
from .egress import BrokerEgress, EgressRefusalError
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
        expected_policy_hash: str,
        approval_secrets: ApprovalSecrets,
    ) -> None:
        if not expected_policy_hash.strip():
            raise OmsError("OmsEngine requires a pinned expected_policy_hash (fail-closed)")
        if approval_secrets is None:
            raise OmsError("OmsEngine requires approval_secrets (fail-closed)")
        self._env = environment
        self._account = account_id
        self._journal = journal
        self._egress = egress
        self._fence = fence
        self._audit = audit
        self._ks = kill_switch
        self._now_fn = now_fn
        self._expected_policy_hash = expected_policy_hash
        self._approval_secrets = approval_secrets

    # ------------------------------------------------------------------
    # R1: decision validation — refuse BEFORE any journal write
    # ------------------------------------------------------------------

    def _validate_decision(
        self,
        intent: TradeIntent,
        decision: RiskDecision,
        symbol: str,
        side: str,
        quantity: Decimal,
    ) -> str | None:
        if not decision.allow:
            return "DECISION_NOT_APPROVED"
        if decision.intent_id != intent.intent_id:
            return "DECISION_INTENT_MISMATCH"
        if self._expected_policy_hash and decision.policy_hash != self._expected_policy_hash:
            return "DECISION_POLICY_MISMATCH"
        now = self._now_fn()
        if decision.decision_at > now:
            return "DECISION_FROM_FUTURE"
        snap = decision.limits_snapshot
        for key in ("bound_symbol", "bound_side", "bound_quantity",
                    "decision_expires_at", "approval_seal"):
            if key not in snap:
                return "DECISION_UNSEALED"
        try:
            expires = dt.datetime.fromisoformat(snap["decision_expires_at"])
        except ValueError:
            return "DECISION_UNSEALED"
        if now > expires:
            return "DECISION_EXPIRED"
        if snap["bound_symbol"] != symbol:
            return "DECISION_BINDING_MISMATCH:symbol"
        if snap["bound_side"] != side:
            return "DECISION_BINDING_MISMATCH:side"
        if Decimal(snap["bound_quantity"]) != abs(quantity):
            return "DECISION_BINDING_MISMATCH:quantity"
        if self._approval_secrets is None:
            return "DECISION_UNSEALED"
        binding = build_send_binding(
            intent_payload=intent.model_dump(mode="json"),
            symbol=symbol,
            side=side,
            quantity=str(quantity),
            policy_hash=decision.policy_hash,
            decision_at=decision.decision_at.isoformat(),
            expires_at=snap["decision_expires_at"],
        )
        if not seal_is_valid(self._approval_secrets, binding, snap["approval_seal"]):
            return "DECISION_SEAL_INVALID"
        return None

    # ------------------------------------------------------------------
    # submit path (INV-1/2/3 + INV-6)
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

        # Defense in depth: halted => refuse outright (fault class "kill switch").
        if self._ks.is_halted():
            self._audit.append(
                "OMS_SUBMIT_REFUSED_HALTED",
                {"intent_id": intent_id, "client_order_id": coid},
            )
            return SubmitOutcome(intent_id, "HALT_NEW_RISK", False, None, halted=True)

        # R5: the intent must belong to THIS OMS's assembled environment and
        # account — mis-wired assemblies refuse instead of trusting callers.
        if intent.environment is not self._env:
            self._audit.append(
                "OMS_ENVIRONMENT_MISMATCH",
                {"intent_id": intent_id, "intent_env": str(intent.environment),
                 "oms_env": str(self._env)},
            )
            return SubmitOutcome(intent_id, "REJECTED", False, None, halted=False)
        if intent.account_id != self._account:
            self._audit.append(
                "OMS_ACCOUNT_MISMATCH",
                {"intent_id": intent_id, "intent_account": intent.account_id,
                 "oms_account": self._account},
            )
            return SubmitOutcome(intent_id, "REJECTED", False, None, halted=False)

        # INV-6 (R1): an invalid/forged/mismatched approval is refused BEFORE
        # any journal write or broker call — zero sends, audited.
        validation_error = self._validate_decision(intent, decision, symbol, side, quantity)
        if validation_error is not None:
            self._audit.append(
                "OMS_APPROVAL_REFUSED",
                {"intent_id": intent_id, "client_order_id": coid,
                 "reason": validation_error},
            )
            return SubmitOutcome(intent_id, "REJECTED", False, None, halted=False)

        # INV-1: journal-first, ONE atomic transaction. Any persistence
        # failure => zero sends.
        try:
            attempt_id = self._journal.record_intent_and_submitting(
                intent_id=intent_id,
                client_order_id=coid,
                environment=str(intent.environment),
                account_id=intent.account_id,
                symbol=symbol,
                side=side,
                quantity=str(quantity),
                payload=intent.model_dump(mode="json"),
                risk_decision=decision.model_dump(mode="json"),
                fence_epoch=token.epoch,
            )
        except JournalError as exc:
            self._audit.append(
                "OMS_PERSISTENCE_FAULT",
                {"intent_id": intent_id, "error": str(exc)},
            )
            return SubmitOutcome(intent_id, "FAILED_PERSISTENCE", False, None, halted=True)

        # INV-3: the egress re-validates the fence itself; a FenceError after
        # the port call (R6 TOCTOU) also lands here — the superseded writer's
        # result is never adopted.
        try:
            receipt = self._egress.submit(token, coid, symbol, quantity, side)
        except FenceError:
            # R1: fence loss is an ACCOUNT-GLOBAL event, not intent-level —
            # trip the persistent KillSwitch so no further sealed intent can
            # be sent until recovery + operator unlock.
            self._ks.set(reason=f"fence lost during submit of {coid}",
                         operator_id="oms-engine")
            self._journal.transition_state(intent_id, "SUBMITTING", "HALT_NEW_RISK")
            self._audit.append(
                "OMS_FENCE_LOSS_GLOBAL_HALT",
                {"intent_id": intent_id, "client_order_id": coid},
            )
            return SubmitOutcome(intent_id, "HALT_NEW_RISK", False, None, halted=True)
        except EgressRefusalError as exc:
            # R2: egress refused for missing/invalid journal eligibility —
            # internal inconsistency => fail closed.
            self._ks.set(reason=f"egress eligibility refused for {coid}",
                         operator_id="oms-engine")
            self._journal.transition_state(intent_id, "SUBMITTING", "HALT_NEW_RISK")
            self._audit.append(
                "OMS_EGRESS_REFUSAL_HALT",
                {"intent_id": intent_id, "client_order_id": coid, "reason": str(exc)},
            )
            return SubmitOutcome(intent_id, "HALT_NEW_RISK", False, None, halted=True)
        except BrokerError:
            # INV-2: answer lost / timeout / delivery unknown => UNKNOWN,
            # HALT_NEW_RISK; absolutely no resend from here.
            self._journal.transition_state(intent_id, "SUBMITTING", "UNKNOWN")
            self._journal.transition_state(intent_id, "UNKNOWN", "HALT_NEW_RISK")
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
            self._journal.transition_state(intent_id, "SUBMITTING", "ACKED", bump_version=True)
            self._journal.finish_attempt(attempt_id, "SENT", {"receipt": receipt.raw or {}})
            return SubmitOutcome(intent_id, "ACKED", True, True, halted=False)
        if receipt.acknowledged is False:
            # provably delivered AND refused by the broker: terminal rejection.
            self._journal.transition_state(intent_id, "SUBMITTING", "REJECTED")
            self._journal.finish_attempt(attempt_id, "SENT", {"rejected": True})
            return SubmitOutcome(intent_id, "REJECTED", True, False, halted=False)
        # acknowledged None with delivered True is not produced by the fake
        # port; treat defensively as UNKNOWN — and R1: a globally unknown
        # outcome trips the persistent KillSwitch like any other uncertainty.
        self._journal.transition_state(intent_id, "SUBMITTING", "UNKNOWN")
        self._ks.set(reason=f"acknowledgment unknown for {coid}", operator_id="oms-engine")
        self._audit.append(
            "OMS_UNKNOWN_HALT",
            {"intent_id": intent_id, "client_order_id": coid, "variant": "ack_none"},
        )
        return SubmitOutcome(intent_id, "UNKNOWN", True, None, halted=True)

    # ------------------------------------------------------------------
    # fills (INV-4): atomic application in the journal
    # ------------------------------------------------------------------

    def process_fill(self, intent_id: str, broker_event_id: str, qty: Decimal) -> bool:
        recorded, reason = self._journal.apply_fill(intent_id, broker_event_id, qty)
        self._audit.append(
            "OMS_FILL_APPLIED" if recorded else "OMS_FILL_REFUSED",
            {"intent_id": intent_id, "broker_event_id": broker_event_id, "reason": reason},
        )
        return recorded

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
                self._journal.transition_state(intent_id, row["state"], "RECONCILED", bump_version=True)
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
        """R3: unlock requires BOTH an explicit human authorization AND a
        journal with zero unresolved intents (every open intent reconciled
        or terminal). Authorization text alone is not reconciliation
        evidence; unknown orders are never treated as undelivered."""
        unresolved = self._journal.unresolved_count()
        if unresolved > 0:
            self._audit.append(
                "OMS_UNLOCK_REFUSED_UNRECONCILED",
                {"operator_id": operator_id, "unresolved": unresolved},
            )
            raise OmsError(
                f"unlock refused: {unresolved} unresolved intent(s) — broker "
                f"orders/positions/cash reconciliation is incomplete"
            )
        self._ks.clear(operator_id=operator_id, authorization_ref=authorization_ref)
        # MOCK_ONLY note: M2 reconciliation covers ORDER-level facts via the
        # fake broker; no positions/cash ledger exists yet, so this unlock is
        # a mock-scoped recovery and must never be read as production-ready.
        self._audit.append(
            "OMS_UNLOCK_MOCK_ONLY",
            {"operator_id": operator_id,
             "note": "order-level reconciliation only; positions/cash proof pending"},
        )


__all__ = ["OmsEngine", "OmsError", "RecoveryReport", "SubmitOutcome"]
