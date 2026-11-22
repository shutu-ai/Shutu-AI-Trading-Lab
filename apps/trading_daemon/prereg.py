"""Forward observation preregistration loader (fail-closed).

The preregistration is the ONLY permission surface: the daemon refuses
any configuration that authorizes real market data, broker credentials,
vendor capability claims (U-1 bypass), a non-replay mode, or an enabled
real window. Loading is frozen (any mutation attempt raises); the
canonical digest is the ``protocol_hash`` of the forward protocol.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import yaml

from trading_lab.security.canonical import canonical_digest

__all__ = ["Preregistration", "PreregistrationRefused"]


class PreregistrationRefused(ValueError):
    """The configuration authorizes something outside the offline
    synthetic scope — the daemon refuses to run under it."""


_REQUIRED_MODE = "SYNTHETIC_REPLAY_ONLY"


class Preregistration:
    def __init__(self, payload: Mapping[str, Any]) -> None:
        self._validate_scope(payload)
        object.__setattr__(self, "_payload", _freeze(dict(payload)))
        object.__setattr__(self, "hash", canonical_digest(dict(payload)))

    # -- construction -----------------------------------------------------

    @classmethod
    def load(cls, path) -> "Preregistration":
        raw = Path(path).read_bytes()
        try:
            payload = yaml.safe_load(raw.decode("utf-8"))
        except yaml.YAMLError as exc:
            raise PreregistrationRefused(f"unparsable YAML: {exc}") from exc
        if not isinstance(payload, dict):
            raise PreregistrationRefused("preregistration must be a mapping")
        return cls(payload)

    @staticmethod
    def _validate_scope(p: Mapping[str, Any]) -> None:
        if p.get("mode") != _REQUIRED_MODE:
            raise PreregistrationRefused(
                f"mode must be {_REQUIRED_MODE}, got {p.get('mode')!r}")
        auth = p.get("source_authorization") or {}
        if auth.get("real_market_data") != "NONE":
            raise PreregistrationRefused(
                "real_market_data authorization must be NONE — no licensed "
                "real source may be admitted in the offline scope "
                "(BLOCKED_DATA stays)")
        if auth.get("broker_credentials") != "FORBIDDEN":
            raise PreregistrationRefused(
                "broker_credentials must be FORBIDDEN")
        if auth.get("vendor_capability_claims_accepted") is not False:
            raise PreregistrationRefused(
                "vendor capability claims are not evidence (M1 U-1 stays "
                "UNRESOLVED) — they cannot be accepted")
        real = p.get("real_window") or {}
        if real.get("enabled") is not False:
            raise PreregistrationRefused(
                "real_window.enabled must be false in this preregistration; "
                "real collection needs a separately authorized version (S8)")
        if not p.get("admitted_datasets"):
            raise PreregistrationRefused("no admitted dataset registered")

    # -- immutability ------------------------------------------------------

    def __setattr__(self, name, value) -> None:
        raise AttributeError(
            "preregistration is frozen; a change is a new version with a "
            "new hash (edit the YAML, never the object)")

    def __delattr__(self, name) -> None:
        raise AttributeError("preregistration is frozen")

    # -- views -------------------------------------------------------------

    def plain_payload(self) -> dict:
        """Fully plain (JSON/YAML-safe) deep copy of the payload."""
        def conv(o: Any) -> Any:
            if isinstance(o, Mapping):
                return {str(k): conv(v) for k, v in o.items()}
            if isinstance(o, (list, tuple)):
                return [conv(v) for v in o]
            return o
        return conv(self._payload)  # type: ignore[attr-defined]

    @property
    def payload(self) -> Mapping[str, Any]:
        return self._payload  # type: ignore[attr-defined]

    @property
    def forward_protocol_id(self) -> str:
        return str(self._payload["forward_protocol_id"])  # type: ignore

    @property
    def environment(self) -> str:
        return str(self._payload["environment_must_equal"])  # type: ignore

    @property
    def admitted_sources(self) -> tuple[str, ...]:
        return tuple(self._payload["source_authorization"]["admitted_sources"])  # type: ignore

    @property
    def admitted_dataset_hashes(self) -> tuple[str, ...]:
        return tuple(  # type: ignore
            str(d["dataset_hash"])
            for d in self._payload["admitted_datasets"])

    @property
    def admitted_symbols(self) -> tuple[str, ...]:
        return tuple(str(d["symbol"]) for d in self._payload["admitted_datasets"]  # type: ignore
                     if d.get("symbol"))

    @property
    def dataset_admission(self) -> str:
        """How ``dataset_hash`` admission is policed. ``pinned`` (this
        synthetic preregistration): every event must carry a
        preregistered fixture hash. ``receipt_content_hash`` (S8 real
        scope, only on the separately-authorized real preregistration
        class): the digest is computed by the collector from the arriving
        payload and cross-verified against the receipt chain."""
        return "pinned"

    @property
    def ttl(self) -> Mapping[str, int]:
        return self._payload["event_contract"]["ttl"]  # type: ignore

    @property
    def strategy(self) -> Mapping[str, Any]:
        return self._payload["strategy"]  # type: ignore

    @property
    def market_clock(self) -> Mapping[str, Any]:
        return self._payload["market_clock"]  # type: ignore

    @property
    def cohort_id_prefix(self) -> str:
        return str(self._payload["forward_protocol_id"])  # type: ignore


def _freeze(obj: Any) -> Any:
    if isinstance(obj, Mapping):
        return _FrozenMap({k: _freeze(v) for k, v in obj.items()})
    if isinstance(obj, (list, tuple)):
        return tuple(_freeze(v) for v in obj)
    return obj


class _FrozenMap(Mapping):
    def __init__(self, data: dict) -> None:
        object.__setattr__(self, "_data", data)

    def __getitem__(self, key):
        return self._data[key]  # type: ignore[attr-defined]

    def __iter__(self):
        return iter(self._data)  # type: ignore[attr-defined]

    def __len__(self) -> int:
        return len(self._data)  # type: ignore[attr-defined]

    def __repr__(self) -> str:
        return repr(self._data)  # type: ignore[attr-defined]
