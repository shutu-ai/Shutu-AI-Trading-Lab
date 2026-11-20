"""Manual Kill Switch — persisted halt of all new-risk activity for one
(environment, account) (M0 task: 手动 Kill Switch).

Fail-closed semantics:

- Setting the halt writes a durable JSON file; the halt therefore survives
  restarts (architecture §6.2: 事故状态必须持续存储，不得因重启自动清除).
- While halted, :meth:`KillSwitch.require_tradable` raises — the hook every
  risk-adding path must call before proceeding (M0 skeleton; the risk engine
  wires it in from M2).
- Clearing the halt requires a non-empty operator authorization reference
  (who authorized + reconciliation evidence pointer). There is no code path
  that clears a halt implicitly, on a timer, or on startup.
- Setting is idempotent and audited; every attempt is recorded.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path

from ..contracts import Environment, HaltState
from .audit import AuditLog


class KillSwitchError(RuntimeError):
    """Raised by require_tradable() while a halt is active."""


class KillSwitch:
    def __init__(
        self,
        environment: Environment,
        account_id: str,
        state_dir: str | os.PathLike[str],
        audit: AuditLog,
    ) -> None:
        self._environment = environment
        self._account_id = account_id
        self._dir = Path(state_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._halt_file = self._dir / f"halt.{environment.value}.{account_id}.json"
        self._audit = audit

    # -- state ---------------------------------------------------------------

    def is_halted(self) -> bool:
        return self._halt_file.exists()

    def halt_state(self) -> HaltState:
        return HaltState.HALT_NEW_RISK if self.is_halted() else HaltState.NORMAL

    def require_tradable(self) -> None:
        """Every risk-adding path must call this first; raises while halted."""
        if self.is_halted():
            reason = "halted (reason persisted in kill-switch state file)"
            self._audit.append(
                "RISK_ACTION_REFUSED_HALTED",
                {"environment": self._environment.value, "account_id": self._account_id},
            )
            raise KillSwitchError(f"{self._environment.value}/{self._account_id}: {reason}")

    # -- transitions ---------------------------------------------------------

    def set(self, reason: str, operator_id: str) -> None:
        """Activate the halt (idempotent). Requires a non-empty reason."""
        if not reason.strip():
            raise ValueError("kill switch set requires a non-empty reason")
        record = {
            "environment": self._environment.value,
            "account_id": self._account_id,
            "state": HaltState.HALT_NEW_RISK.value,
            "reason": reason,
            "operator_id": operator_id,
            "set_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        }
        # Write durable halt record ('x' -> refuse to clobber an existing file
        # without going through set() again; idempotent when identical state).
        if not self._halt_file.exists():
            self._halt_file.write_text(
                json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2),
                encoding="utf-8",
            )
        self._audit.append(
            "KILL_SWITCH_SET",
            {
                "environment": self._environment.value,
                "account_id": self._account_id,
                "reason": reason,
                "operator_id": operator_id,
            },
        )

    def clear(self, operator_id: str, authorization_ref: str) -> None:
        """Deactivate the halt. Explicit human authorization is mandatory and
        is recorded verbatim (who + reconciliation evidence pointer)."""
        if not self.is_halted():
            return  # idempotent; audit the no-op for the record
        if not authorization_ref.strip():
            self._audit.append(
                "KILL_SWITCH_CLEAR_REFUSED_NO_AUTHORIZATION",
                {
                    "environment": self._environment.value,
                    "account_id": self._account_id,
                    "operator_id": operator_id,
                },
            )
            raise ValueError(
                "clearing a kill switch requires a non-empty authorization_ref "
                "(operator approval + completed reconciliation evidence)"
            )
        self._halt_file.unlink()
        self._audit.append(
            "KILL_SWITCH_CLEARED",
            {
                "environment": self._environment.value,
                "account_id": self._account_id,
                "operator_id": operator_id,
                "authorization_ref": authorization_ref,
            },
        )

    @property
    def halt_file(self) -> Path:
        return self._halt_file


__all__ = ["KillSwitch", "KillSwitchError"]
