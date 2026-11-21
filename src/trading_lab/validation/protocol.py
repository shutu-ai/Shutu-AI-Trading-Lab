"""Evaluation protocol registry (M3-R1-T2) — load, validate, freeze, hash.

The YAML file ``configs/evaluation_protocol.yaml`` is the single
authoritative evaluation protocol. This module is its ONLY sanctioned
loader:

- **fail-closed**: a missing file, unparsable YAML, or any missing
  controlled top-level section is a ProtocolError — never a default.
- **hash freeze**: ``protocol_hash`` is the canonical digest (reusing
  ``trading_lab.security.canonical`` — no second canonicalization) of the
  whole parsed payload. Any controlled-field change yields a different
  hash, i.e. a new protocol version; thresholds cannot be silently edited.
- **runtime immutability**: the loaded object refuses attribute writes and
  exposes deeply frozen views (mapping proxies / tuples); a threshold
  change means a new file, which means a new hash.
- **honest gates**: gates marked ``NOT_SETTABLE`` (no defensible numeric
  basis in the synthetic scope) must drive dependent experiment verdicts
  to ``INCONCLUSIVE`` — the loader exposes them as first-class facts.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

import yaml

from trading_lab.security.canonical import canonical_digest

__all__ = [
    "ArmSpec",
    "EvaluationProtocol",
    "ProtocolError",
]

#: every controlled top-level section; all are REQUIRED (fail closed).
CONTROLLED_SECTIONS: tuple[str, ...] = (
    "schema_version",
    "protocol_id",
    "protocol_version",
    "canonical_rule",
    "data_scope",
    "max_claimable_evidence",
    "seeds",
    "decimal_tolerance",
    "cost_model",
    "cost_multipliers",
    "execution",
    "pit_rule",
    "gates",
    "validation",
    "arms",
    "budget",
    "multiplicity",
    "holdout",
)


class ProtocolError(ValueError):
    """Protocol cannot be loaded/validated — fail closed."""


@dataclasses.dataclass(frozen=True)
class ArmSpec:
    arm_id: str
    enabled: bool
    definition: str
    budget_trials: int | None


def _freeze(obj: Any) -> Any:
    """Deep-freeze a parsed YAML structure into immutable views."""
    if isinstance(obj, dict):
        return MappingProxyType({k: _freeze(v) for k, v in obj.items()})
    if isinstance(obj, list):
        return tuple(_freeze(v) for v in obj)
    return obj


class EvaluationProtocol:
    """Frozen view over one protocol payload, bound to its hash."""

    # ------------------------------------------------------------------
    # construction
    # ------------------------------------------------------------------

    def __init__(self, payload: Mapping[str, Any]) -> None:
        object.__setattr__(self, "_frozen_payload", _freeze(dict(payload)))
        object.__setattr__(
            self, "protocol_hash", canonical_digest(dict(payload)))

    @classmethod
    def load(cls, path: Path | str) -> "EvaluationProtocol":
        path = Path(path)
        raw = path.read_bytes() if path.exists() else None
        if raw is None:
            raise ProtocolError(f"cannot read protocol file: {path}")
        try:
            payload = yaml.safe_load(raw.decode("utf-8"))
        except yaml.YAMLError as exc:
            raise ProtocolError(f"unparsable protocol YAML: {exc}") from exc
        if not isinstance(payload, dict):
            raise ProtocolError("protocol payload must be a mapping")
        missing = [s for s in CONTROLLED_SECTIONS if s not in payload]
        if missing:
            raise ProtocolError(
                f"protocol missing controlled section(s): "
                f"{', '.join(sorted(missing))}")
        return cls(payload)

    # ------------------------------------------------------------------
    # immutability
    # ------------------------------------------------------------------

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError(
            "protocol is frozen; a threshold change is a new protocol "
            "version with a new hash (edit the YAML, never the object)")

    def __delattr__(self, name: str) -> None:
        raise AttributeError("protocol is frozen")

    # ------------------------------------------------------------------
    # identity
    # ------------------------------------------------------------------

    @property
    def protocol_id(self) -> str:
        return self._frozen_payload["protocol_id"]

    @property
    def protocol_version(self) -> int:
        return int(self._frozen_payload["protocol_version"])

    @property
    def data_scope(self) -> str:
        return self._frozen_payload["data_scope"]

    @property
    def max_claimable_evidence(self) -> str:
        return self._frozen_payload["max_claimable_evidence"]

    @property
    def decimal_tolerance(self) -> str:
        return self._frozen_payload["decimal_tolerance"]

    @property
    def seeds(self) -> tuple[int, ...]:
        return self._frozen_payload["seeds"]

    @property
    def cost_model(self) -> Mapping[str, Any]:
        return self._frozen_payload["cost_model"]

    @property
    def cost_multipliers(self) -> tuple[int, ...]:
        return self._frozen_payload["cost_multipliers"]

    @property
    def execution(self) -> Mapping[str, Any]:
        return self._frozen_payload["execution"]

    @property
    def pit_rule(self) -> str:
        return self._frozen_payload["pit_rule"]

    @property
    def budget(self) -> Mapping[str, Any]:
        return self._frozen_payload["budget"]

    @property
    def validation_thresholds(self) -> Mapping[str, Any]:
        return self._frozen_payload["validation"]

    # ------------------------------------------------------------------
    # arms
    # ------------------------------------------------------------------

    def _arm_specs(self) -> tuple[ArmSpec, ...]:
        arms = self._frozen_payload["arms"]
        specs = []
        for arm_id in sorted(arms):
            a = arms[arm_id]
            body = a.get("definition") if a.get("definition") is not None \
                else a.get("description")
            specs.append(ArmSpec(
                arm_id=arm_id,
                enabled=bool(a["enabled"]),
                definition=str(body or ""),
                budget_trials=a.get("budget_trials"),
            ))
        return tuple(specs)

    def enabled_arms(self) -> tuple[ArmSpec, ...]:
        return tuple(a for a in self._arm_specs() if a.enabled)

    def registered_disabled_arms(self) -> tuple[ArmSpec, ...]:
        return tuple(a for a in self._arm_specs() if not a.enabled)

    # ------------------------------------------------------------------
    # budgets (structures, not booleans)
    # ------------------------------------------------------------------

    def equal_trial_budget(self) -> Mapping[str, Any]:
        return self._frozen_payload["budget"]["equal_trial_budget"]

    def equal_economic_budget(self) -> Mapping[str, Any]:
        return self._frozen_payload["budget"]["equal_economic_budget"]

    def budget_limits(self) -> dict[str, Any]:
        b = self._frozen_payload["budget"]
        return {
            "max_total_trials": b["max_total_trials"],
            "max_search_queries": b["max_search_queries"],
            "max_failures_before_halt": b["max_failures_before_halt"],
            "max_hypotheses": b["max_hypotheses"],
            "max_holdout_unlocks": b["max_holdout_unlocks"],
            "max_llm_usd": b["max_llm_usd"],
            "max_compute_hours": b["max_compute_hours"],
            "failure_retry_billing": b["failure_retry_billing"],
        }

    # ------------------------------------------------------------------
    # gates
    # ------------------------------------------------------------------

    def gate_status(self, name: str) -> str:
        try:
            return self._frozen_payload["gates"][name]["status"]
        except KeyError:
            raise ProtocolError(f"unknown gate: {name}") from None

    def verdict_for_incomplete_gate(self, name: str) -> str:
        """The verdict an experiment must report when it would depend on
        this gate and the gate is not SET (default INCONCLUSIVE)."""
        try:
            gate = self._frozen_payload["gates"][name]
        except KeyError:
            raise ProtocolError(f"unknown gate: {name}") from None
        if gate.get("status") == "SET":
            return "PASS_ELIGIBLE"
        return str(gate.get("verdict", "INCONCLUSIVE"))

    def numeric_gates(self) -> dict[str, tuple[float | int | None, bool]]:
        """Declared numeric thresholds -> (value, settable).

        Sources: numeric entries of the ``validation`` section (engineering
        acceptance thresholds, all binding in the synthetic scope) plus any
        ``gates`` entry that carries a numeric ``threshold``. Gates marked
        NOT_SETTABLE must carry ``threshold: null`` — an unset gate never
        pretends to have a bound.
        """
        out: dict[str, tuple[float | int | None, bool]] = {}
        for name, value in self._frozen_payload["validation"].items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                out[name] = (value, True)
        for name, gate in self._frozen_payload["gates"].items():
            if "threshold" in gate:
                settable = gate.get("status") == "SET"
                out[name] = (gate.get("threshold"), settable)
        return out

    # ------------------------------------------------------------------
    # holdout registration
    # ------------------------------------------------------------------

    def holdout_registration(self) -> Mapping[str, Any]:
        return self._frozen_payload["holdout"]

    # ------------------------------------------------------------------
    # canonical payload access (for evidence records)
    # ------------------------------------------------------------------

    def evidence_record(self) -> dict[str, Any]:
        """Hash + identity facts to embed in experiment ledger entries."""
        return {
            "protocol_id": self.protocol_id,
            "protocol_version": self.protocol_version,
            "protocol_hash": self.protocol_hash,
            "data_scope": self.data_scope,
            "max_claimable_evidence": self.max_claimable_evidence,
        }
