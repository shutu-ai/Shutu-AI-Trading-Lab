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


@dataclass(frozen=True)
class GateDecision:
    allow: bool
    action: str  # "ALLOW_SIGNAL" / "NO_TRADE"
    reason_codes: tuple[str, ...]
    strategy_id: str  # best-effort echo for audit; "" when unknown


class SchemaGate:
    def __init__(
        self,
        reviewed_builds: dict[str, set[str]],
        allowed_symbols: set[str],
        audit: AuditLog,
        now_fn: NowFn,
    ) -> None:
        """``reviewed_builds``: strategy_id -> set of reviewed_build_hash values
        from the environment's release whitelist. Not "whitelist + no
        prompt-based bans": membership is the only acceptance path."""
        self._builds = reviewed_builds
        self._symbols = frozenset(allowed_symbols)
        self._audit = audit
        self._now_fn = now_fn

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

    def evaluate_portfolio(self, raw: bytes | str) -> GateDecision:
        portfolio, reject = self._parse(raw, TargetPortfolio)
        if reject is not None:
            return self._reject(reject)
        reasons: list[str] = []

        off_pool = sorted({a.symbol for a in portfolio.allocation} - self._symbols)
        if off_pool:
            reasons.append(f"SYMBOLS_OUTSIDE_ALLOWED_POOL:{','.join(off_pool)}")

        return self._decide("", reasons, "ALLOW_PORTFOLIO")

    # -- internals -----------------------------------------------------------

    def _parse(self, raw: bytes | str, model: type) -> tuple[Any, GateDecision | None]:
        """Strict parse+validate. Returns (model, None) or (None, reject)."""
        try:
            text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
            data = json.loads(text)  # distinguishes invalid JSON from bad shape
        except (UnicodeDecodeError, json.JSONDecodeError):
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
        self._audit.append(
            decision.action,
            {
                "strategy_id": decision.strategy_id,
                "reason_codes": list(decision.reason_codes),
            },
        )
        return decision


__all__ = ["GateDecision", "SchemaGate", "SUPPORTED_SCHEMA_VERSIONS"]
