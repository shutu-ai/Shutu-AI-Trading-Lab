"""The single Risk Engine — the independent decision point between an
admitted signal and the OMS.

Frozen check order (short-circuit, every outcome audited):

    1. audit sink available
    2. kill switch not engaged (HALT_NEW_RISK)
    3. producer identity bound by the trusted runtime (unforgeable object)
    4. account / environment binding
    5. allowed symbol pool
    6. price / quantity sanity (finite, positive, no leverage via negatives)
    7. notional within per-order cap; exposure/budget within policy
    8. data freshness (bar age, snapshot age), order TTL
    9. approval artifact validity for LIVE (Paper runs on the test template)

Verdicts: APPROVE / REJECT / HALT_NEW_RISK — structured reason codes, every
decision appended to the audit log before being returned.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from typing import Callable

from ..contracts import (
    Environment,
    MarketSnapshot,
    RiskDecision,
    TradeIntent,
)
from ..security.audit import AuditLog
from ..security.canonical import canonical_json_bytes, sha256_hex
from ..security.kill_switch import KillSwitch
from ..security.approval import ApprovalSecrets, build_send_binding
from .policy import RiskPolicy
from .producer import TrustedProducer

NowFn = Callable[[], dt.datetime]

VERDICT_APPROVE = "APPROVE"
VERDICT_REJECT = "REJECT"
VERDICT_HALT = "HALT_NEW_RISK"

DECISION_CHECK_ORDER = (
    "AUDIT", "KILL_SWITCH", "PRODUCER", "ACCOUNT_ENV", "SYMBOL", "SANITY",
    "NOTIONAL", "EXPOSURE", "FRESHNESS", "APPROVAL",
)

# §6.2 fields with no trusted M2 input source (no P&L history, no order-rate
# window, no account-snapshot timestamps, synchronous fake acks). These are
# audited as MOCK_ONLY-unenforced on every decision — and any LIVE-policy
# decision is REJECTED outright while they remain unenforced (R7).
MOCK_ONLY_UNENFORCED_FIELDS = (
    "max_daily_loss_pct",
    "max_peak_to_trough_drawdown_pct",
    "max_abnormal_orders_per_minute",
    "max_account_snapshot_age_seconds",
    "max_broker_order_ack_wait_seconds",
    "allow_margin",
)

RISK_DECISION_TTL_SECONDS = 60


@dataclass(frozen=True)
class ExposureState:
    """What the engine is told about current exposure (provided by the OMS /
    account state, never invented here). ``symbol_exposure_usd`` carries
    per-symbol exposure for concentration checks; absent symbols count 0."""

    gross_exposure_usd: Decimal
    net_exposure_usd: Decimal
    equity_usd: Decimal
    settled_cash_usd: Decimal
    symbol_exposure_usd: dict[str, Decimal] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.symbol_exposure_usd is None:
            object.__setattr__(self, "symbol_exposure_usd", {})


class RiskEngine:
    def __init__(
        self,
        policy: RiskPolicy,
        kill_switch: KillSwitch,
        audit: AuditLog,
        trusted_producer: TrustedProducer,
        now_fn: NowFn,
        snapshot_provider: Callable[[], MarketSnapshot | None],
        exposure_provider: Callable[[], ExposureState],
        approval_verifier: Callable[[TradeIntent], tuple[bool, str]] | None = None,
        approval_secrets: ApprovalSecrets | None = None,
    ) -> None:
        self._policy = policy
        self._ks = kill_switch
        self._audit = audit
        self._producer = trusted_producer
        self._now_fn = now_fn
        self._snapshot_provider = snapshot_provider
        self._exposure_provider = exposure_provider
        self._approval_verifier = approval_verifier  # LIVE: LiveRelease chain (mock in M2)
        self._approval_secrets = approval_secrets

    # ------------------------------------------------------------------ #

    def evaluate(
        self,
        intent: TradeIntent,
        producer: TrustedProducer,
        symbol: str | None = None,
        max_bar_age_seconds: int | None = None,
        side: str | None = None,
    ) -> RiskDecision:
        """``side`` ("buy"/"sell") is optional risk context: a SELL
        releases cash and market value, so the settled-funds precondition
        (a BUY-side affordability check) does not apply to it. Every
        other check — exposure caps, concentration, TTL, symbol pool,
        freshness, kill switch — is side-independent and unchanged.
        ``side=None`` (all M2-era callers) keeps today's behavior
        exactly; negative ``desired_change`` still reads as shorting and
        is refused under ``allow_short=False``."""
        reasons: list[str] = []
        verdict = VERDICT_APPROVE

        def fail(level: str, code: str) -> None:
            nonlocal verdict
            reasons.append(code)
            if level == "HALT":
                verdict = VERDICT_HALT
            elif verdict != VERDICT_HALT:
                verdict = VERDICT_REJECT

        # 1. audit availability — fail-closed (no decision without a record)
        try:
            audit_ok, _first_bad = self._audit.verify()
        except Exception:
            audit_ok = False
        if not audit_ok:
            fail("REJECT", "AUDIT_UNAVAILABLE")

        # 2. kill switch
        try:
            self._ks.require_tradable()
        except Exception:
            fail("HALT", "KILL_SWITCH_ENGAGED")

        # 3. producer identity (unforgeable object binding; self-reported
        #    intent fields are never trusted as identity)
        if not self._producer.matches_binding(producer):
            fail("REJECT", "PRODUCER_NOT_TRUSTED")
        elif producer.reviewed_build_hash != intent.source_hash:
            fail("REJECT", "BUILD_HASH_MISMATCH")

        # 4. account / environment binding
        if intent.account_id != self._policy.account_id:
            fail("REJECT", f"ACCOUNT_MISMATCH:{intent.account_id}")
        if intent.environment is not self._policy.environment:
            fail("REJECT", f"ENVIRONMENT_MISMATCH:{intent.environment}")

        # 5. symbol pool (symbol travels with the intent from the same
        #    trusted channel; None is not pool membership)
        if symbol is None or symbol.upper() not in self._policy.allowed_symbols:
            fail("REJECT", f"SYMBOL_NOT_ALLOWED:{symbol}")

        # 6. intent TTL + quantity sanity
        if intent.expires_at_utc <= self._now_fn():
            fail("REJECT", "INTENT_EXPIRED")
        if intent.desired_change == 0:
            fail("REJECT", "ZERO_QUANTITY")
        if intent.desired_change < 0 and not self._policy.allow_short:
            fail("REJECT", f"SHORT_NOT_ALLOWED:{intent.desired_change}")
        if not intent.desired_change.is_finite():
            fail("REJECT", "NON_FINFINITE_QUANTITY")

        # 7. notional & exposure — need a price; the engine takes the
        #    notional as |desired_change| * reference price via the snapshot
        #    provider's dataset context. In M2 synthetic mode the notional is
        #    the |desired_change| itself (quantity of dollars for the fixture).
        notional = abs(intent.desired_change)
        if notional > self._policy.max_single_order_notional_usd:
            fail("REJECT", f"ORDER_NOTIONAL_EXCEEDED:{notional}>{self._policy.max_single_order_notional_usd}")

        exposure = self._exposure_provider()
        equity = exposure.equity_usd
        if equity <= 0 or not equity.is_finite():
            fail("REJECT", "ACCOUNT_STATE_UNUSABLE")
            equity = Decimal(0)
        # V0.2 activation T1: a SELL releases market value — its notional
        # is SUBTRACTED from gross/net/symbol exposure (a sell can never
        # be refused as a risk INCREASE; every other guard still runs and
        # allow_short still forbids negative positions upstream). buys
        # (and side-less M2-era callers) keep the exact add semantics.
        risk_delta = -notional if side == "sell" else notional
        if exposure.gross_exposure_usd + risk_delta > (
            self._policy.max_gross_exposure_pct / Decimal(100) * equity
        ):
            fail("REJECT", "GROSS_EXPOSURE_EXCEEDED")
        if exposure.net_exposure_usd + risk_delta > (
            self._policy.max_net_exposure_pct / Decimal(100) * equity
        ):
            fail("REJECT", "NET_EXPOSURE_EXCEEDED")
        symbol_exposure = exposure.symbol_exposure_usd.get(symbol, Decimal(0))
        if symbol_exposure + risk_delta > (
            self._policy.max_single_symbol_pct / Decimal(100) * equity
        ):
            fail("REJECT", f"SINGLE_SYMBOL_CONCENTRATION:{symbol}")
        if self._policy.require_settled_funds and side != "sell" \
                and notional > exposure.settled_cash_usd:
            fail("REJECT", "INSUFFICIENT_SETTLED_FUNDS")

        # 8. freshness — snapshot must exist and be recent (PIT data gate).
        # R7: an EXPLICIT 0 must never be shadowed by the policy default
        # (`or` would do exactly that).
        snapshot = self._snapshot_provider()
        max_age = (
            max_bar_age_seconds
            if max_bar_age_seconds is not None
            else self._policy.max_market_bar_age_seconds
        )
        if snapshot is None:
            fail("REJECT", "NO_DATA_SNAPSHOT")
        else:
            age = (self._now_fn() - snapshot.asof_utc).total_seconds()
            if age > max_age:
                fail("REJECT", f"SNAPSHOT_STALE:{age:.0f}s>{max_age}s")
            if snapshot.knowledge_cutoff_utc > self._now_fn():
                fail("REJECT", "SNAPSHOT_FROM_THE_FUTURE")

        # 9. approval artifact (LIVE): a missing verifier is a HARD reject
        # (R2) — M2 must not offer any executable Live path. Mock-only
        # unenforced mandatory fields also hard-reject any LIVE decision.
        if self._policy.environment is Environment.LIVE:
            if self._approval_verifier is None:
                fail("REJECT", "LIVE_APPROVAL_VERIFIER_MISSING")
            if MOCK_ONLY_UNENFORCED_FIELDS:
                fail("REJECT",
                     f"LIVE_MOCK_ONLY_UNENFORCED:{','.join(MOCK_ONLY_UNENFORCED_FIELDS)}")
            if self._approval_verifier is not None:
                try:
                    ok, reason = self._approval_verifier(intent)
                except Exception as exc:
                    ok, reason = False, f"VERIFIER_FAULT:{type(exc).__name__}"
                if not ok:
                    fail("REJECT", f"APPROVAL_INVALID:{reason}")

        limits_snapshot: dict[str, str] = {
            "max_single_order_notional_usd": str(self._policy.max_single_order_notional_usd),
            "max_gross_exposure_pct": str(self._policy.max_gross_exposure_pct),
            "allowed_symbols": ",".join(self._policy.allowed_symbols),
            "check_order": ",".join(DECISION_CHECK_ORDER),
        }
        decision_at = self._now_fn()
        if verdict == VERDICT_APPROVE:
            # R1: bind the approval to the exact intent+symbol+side+quantity
            # with an HMAC seal (runtime-minted secret shared only with the
            # OMS assembly). Forged/substituted decisions cannot recompute it.
            if self._approval_secrets is None:
                fail("REJECT", "APPROVAL_SECRETS_MISSING")
            else:
                # explicit side (V0.2 continuous execution) wins; the
                # sign of desired_change remains the default derivation
                # for M2-era callers that pass no side
                bound_side = side if side in ("buy", "sell") else (
                    "buy" if intent.desired_change > 0 else "sell")
                expiry = decision_at + dt.timedelta(seconds=RISK_DECISION_TTL_SECONDS)
                binding = build_send_binding(
                    intent_payload=intent.model_dump(mode="json"),
                    symbol=symbol,
                    side=bound_side,
                    quantity=str(abs(intent.desired_change)),
                    policy_hash=self._policy.policy_hash,
                    decision_at=decision_at.isoformat(),
                    expires_at=expiry.isoformat(),
                )
                limits_snapshot.update(
                    {
                        "bound_symbol": symbol,
                        "bound_side": bound_side,
                        "bound_quantity": str(abs(intent.desired_change)),
                        "decision_expires_at": expiry.isoformat(),
                        "approval_seal": self._approval_secrets.seal(binding),
                    }
                )
        decision = RiskDecision(
            intent_id=intent.intent_id,
            policy_hash=self._policy.policy_hash,
            allow=(verdict == VERDICT_APPROVE),
            reason_codes=tuple(reasons) if reasons else ("POLICY_SATISFIED",),
            limits_snapshot=limits_snapshot,
            decision_at=decision_at,
        )
        self._audit.append(
            "RISK_DECISION",
            {
                "intent_id": intent.intent_id,
                "verdict": verdict,
                "allow": decision.allow,
                "reason_codes": list(decision.reason_codes),
                "policy_hash": self._policy.policy_hash,
            },
        )
        return decision

    def policy_digest(self) -> str:
        """Stable digest of the frozen policy (pinned into decisions)."""
        return sha256_hex(canonical_json_bytes(self._policy.model_dump(mode="json")))


__all__ = [
    "DECISION_CHECK_ORDER",
    "ExposureState",
    "RiskEngine",
    "VERDICT_APPROVE",
    "VERDICT_HALT",
    "VERDICT_REJECT",
]
