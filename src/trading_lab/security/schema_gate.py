"""Trusted Schema Gate — the unique data channel from strategy subprocesses
into the trading plane (architecture §2.6).

Only *data* crosses this boundary: raw JSON bytes. Python objects, pickles,
callables and command strings are structurally impossible here — the input
must parse as strict JSON and validate against :class:`StrategySignal` or
:class:`TargetPortfolio` with ``extra="forbid"``.

Gate checks (any failure -> NO_TRADE + audit event, never an exception):

- strict JSON parse; top-level shape; unknown fields rejected
- supported schema_version
- strategy_id / reviewed_build_hash must be in the reviewed-build whitelist
- snapshot_id present and non-empty
- signal TTL: expires_at_utc must be in the future (expired -> NO_TRADE)
- target_exposure / weights: finite, within [0, 1], no negatives
  (no leverage via negative weights), portfolio weights + cash sum to 1
- symbols must be in the allowed asset pool
- rationale_hash must be a hex hash, not free text

Rejections are decision events, not errors: an invalid signal must never
crash the trading plane into an undefined state.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from typing import Any, Callable

from ..contracts import StrategySignal, TargetPortfolio
from .audit import AuditLog

NowFn = Callable[[], dt.datetime]

SUPPORTED_SCHEMA_VERSIONS = frozenset({"1"})


class SchemaGateAuditUnavailable(RuntimeError):
    """Raised when the audit sink cannot record a gate decision.

    Fail-closed by design: no decision — least of all an ALLOW_* — may be
    returned to a caller without its audit record. This is an explicit stop
    error, not a swallowed one."""


@dataclass(frozen=True)
class TrustedProducerContext:
    """Runtime-owned trust facts for portfolio admission (R3). Every field
    comes from configuration independent of the evaluated JSON — a payload
    can never influence its own producer's trustworthiness.

    ``reviewed_portfolio_producers`` binds each allowed producer identity to
    its reviewed build hash (config-side); the producer identity itself is
    established by the calling channel (in M2, the process boundary), never
    by the payload.
    """

    runtime_account_id: str
    allowed_risk_budget_ids: frozenset[str]
    reviewed_portfolio_producers: dict[str, str]
    max_portfolio_age_seconds: int


@dataclass(frozen=True)
class GateDecision:
    allow: bool
    action: str  # "ALLOW_SIGNAL" / "ALLOW_PORTFOLIO" / "NO_TRADE"
    reason_codes: tuple[str, ...]
    strategy_id: str  # best-effort echo for audit; "" when unknown


class SchemaGate:
    def __init__(
        self,
        reviewed_builds: dict[str, set[str]],
        allowed_symbols: set[str],
        audit: AuditLog,
        now_fn: NowFn,
        portfolio_context: TrustedProducerContext | None = None,
    ) -> None:
        """``reviewed_builds``: strategy_id -> set of reviewed_build_hash values
        from the environment's release whitelist. Not "whitelist + no
        prompt-based bans": membership is the only acceptance path.

        ``portfolio_context``: required trust facts for
        :meth:`evaluate_portfolio`. Without it every portfolio is rejected
        (PORTFOLIO_NO_TRUSTED_CONTEXT) — structural validity alone never
        admits a portfolio (R3).
        """
        self._builds = reviewed_builds
        self._symbols = frozenset(allowed_symbols)
        self._audit = audit
        self._now_fn = now_fn
        self._portfolio_ctx = portfolio_context

    # -- public entrypoints --------------------------------------------------

    def evaluate_signal(self, raw: bytes | str) -> GateDecision:
        signal, reject = self._parse(raw, StrategySignal)
        if reject is not None:
            return self._reject(reject)
        reasons: list[str] = []

        if signal.schema_version not in SUPPORTED_SCHEMA_VERSIONS:
            reasons.append(f"UNSUPPORTED_SCHEMA_VERSION:{signal.schema_version}")
        if signal.strategy_id not in self._builds or (
            signal.reviewed_build_hash not in self._builds.get(signal.strategy_id, set())
        ):
            reasons.append(
                f"BUILD_NOT_REVIEWED:strategy={signal.strategy_id},"
                f"hash={signal.reviewed_build_hash}"
            )
        if not signal.snapshot_id.strip():
            reasons.append("MISSING_SNAPSHOT_ID")
        if self._now_fn() >= signal.expires_at_utc:
            reasons.append("SIGNAL_EXPIRED")
        if signal.target_exposure < 0 or signal.target_exposure > 1:
            reasons.append("TARGET_EXPOSURE_OUT_OF_RANGE")

        return self._decide(signal.strategy_id, reasons, "ALLOW_SIGNAL")

    def evaluate_portfolio(self, raw: bytes | str, producer_id: str) -> GateDecision:
        """Data-admission check for a target portfolio.

        ``producer_id`` identifies the calling producer via the trusted
        channel; it must be a key of the configured reviewed-producer set.
        ALLOW_PORTFOLIO means *data admission only* — it is not a trade
        authorization; independent risk and OMS decisions remain downstream
        (M2)."""
        ctx = self._portfolio_ctx
        if ctx is None:
            return self._decide("", ("PORTFOLIO_NO_TRUSTED_CONTEXT",), "ALLOW_PORTFOLIO")
        if not producer_id or producer_id not in ctx.reviewed_portfolio_producers:
            return self._decide("", ("PORTFOLIO_PRODUCER_NOT_REVIEWED",), "ALLOW_PORTFOLIO")

        portfolio, reject = self._parse(raw, TargetPortfolio)
        if reject is not None:
            return self._reject(reject)
        reasons: list[str] = []

        # Account binding: the JSON's self-reported account_id is compared
        # against the runtime's trusted binding, never trusted by itself.
        if portfolio.account_id != ctx.runtime_account_id:
            reasons.append(
                f"PORTFOLIO_ACCOUNT_MISMATCH:json={portfolio.account_id},"
                f"runtime={ctx.runtime_account_id}"
            )
        if portfolio.risk_budget_id not in ctx.allowed_risk_budget_ids:
            reasons.append(f"PORTFOLIO_RISK_BUDGET_UNKNOWN:{portfolio.risk_budget_id}")

        age = (self._now_fn() - portfolio.timestamp).total_seconds()
        if age > ctx.max_portfolio_age_seconds:
            reasons.append(f"PORTFOLIO_STALE:age_seconds={age:.0f}")
        if age < -60:  # clock-skew tolerance for future stamps
            reasons.append(f"PORTFOLIO_TIMESTAMP_FUTURE:age_seconds={age:.0f}")

        off_pool = sorted({a.symbol for a in portfolio.allocation} - self._symbols)
        if off_pool:
            reasons.append(f"SYMBOLS_OUTSIDE_ALLOWED_POOL:{','.join(off_pool)}")

        return self._decide("", reasons, "ALLOW_PORTFOLIO")

    # -- internals -----------------------------------------------------------

    def _parse(self, raw: bytes | str, model: type) -> tuple[Any, GateDecision | None]:
        """Strict parse+validate with an explicit type boundary (R4): any
        input that is not bytes/str, is not valid UTF-8, is not JSON, or does
        not match the schema yields a NO_TRADE decision — never an
        exception."""
        if not isinstance(raw, (bytes, str)):
            return None, GateDecision(
                allow=False,
                action="NO_TRADE",
                reason_codes=("INPUT_TYPE_INVALID",),
                strategy_id="",
            )
        try:
            text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
            data = json.loads(text)  # distinguishes invalid JSON from bad shape
        except (UnicodeDecodeError, ValueError, TypeError):
            return None, GateDecision(
                allow=False,
                action="NO_TRADE",
                reason_codes=("NOT_VALID_JSON",),
                strategy_id="",
            )
        try:
            parsed = model.model_validate_json(text)  # JSON-mode strict validation
        except Exception as exc:
            return None, GateDecision(
                allow=False,
                action="NO_TRADE",
                reason_codes=(f"SCHEMA_VALIDATION_FAILED:{type(exc).__name__}",),
                strategy_id=str(data.get("strategy_id", "")) if isinstance(data, dict) else "",
            )
        return parsed, None

    def _reject(self, decision: GateDecision) -> GateDecision:
        return self._decide(decision.strategy_id, list(decision.reason_codes), decision.action)

    def _decide(self, strategy_id: str, reasons: list[str], allow_action: str) -> GateDecision:
        allow = not reasons
        decision = GateDecision(
            allow=allow,
            action=allow_action if allow else "NO_TRADE",
            reason_codes=tuple(reasons),
            strategy_id=strategy_id,
        )
        # Audit BEFORE returning: an ALLOW_* decision must never reach a
        # caller unrecorded, and any audit fault is an explicit stop error
        # (fail-closed) rather than a silently allowed pass-through (R4.3).
        try:
            self._audit.append(
                decision.action,
                {
                    "strategy_id": decision.strategy_id,
                    "reason_codes": list(decision.reason_codes),
                },
            )
        except Exception as exc:
            raise SchemaGateAuditUnavailable(
                f"audit sink unavailable; gate decision {decision.action} not delivered "
                f"(fail-closed): {exc!r}"
            ) from exc
        return decision


__all__ = ["GateDecision", "SchemaGate", "SUPPORTED_SCHEMA_VERSIONS"]
