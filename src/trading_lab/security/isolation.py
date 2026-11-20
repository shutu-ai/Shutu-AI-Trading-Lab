"""Runtime isolation boundaries (architecture §2.1/§2.5/§6.3).

M0 enforces the deployment-isolation skeleton:

- :class:`RuntimeContext` is the *only* way a process obtains its trading
  identity. It is built from a validated :class:`RuntimeConfig` file, frozen
  for the lifetime of the process, and exposes no way to switch environment
  at runtime ("不得在一个进程里通过 paper=false 切换环境").
- :func:`load_runtime_config` rejects configs that leak credentials inline
  (contract layer), point Paper at the live host, or boot LIVE non-dry-run.
- :class:`ResearchSandboxPolicy` is the research plane's guard: research
  contexts structurally have no broker write path; attempting a trading-plane
  action from a research context raises and is audited.
- :func:`scan_for_live_artifacts` is the Paper-purity scanner used by
  ``scripts/verify_live_blocked.py`` and the CI gate: a Paper runtime must
  contain no Live keys/endpoints/account ids.
"""

from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from ..contracts import Environment, RuntimeConfig
from .audit import AuditLog


class IsolationViolation(RuntimeError):
    """Raised when a cross-domain access or purity violation is detected."""


def load_runtime_config(path: str | Path) -> RuntimeConfig:
    """Load and validate a runtime config file (YAML). Validation errors
    (inline credentials, live host in paper config, LIVE non-dry-run, etc.)
    raise before any runtime exists."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return RuntimeConfig.model_validate(raw)


@dataclass(frozen=True)
class RuntimeContext:
    """Immutable per-process trading identity. Create only via
    :meth:`bind`; the frozen dataclass makes environment switching
    structurally impossible."""

    config: RuntimeConfig
    config_path: str
    audit: AuditLog

    @classmethod
    def bind(cls, config_path: str | Path, audit: AuditLog) -> "RuntimeContext":
        config = load_runtime_config(config_path)
        ctx = cls(config=config, config_path=str(config_path), audit=audit)
        audit.append(
            "RUNTIME_BOUND",
            {
                "environment": config.environment.value,
                "account_id": config.account_id,
                "config_path": ctx.config_path,
            },
        )
        return ctx

    @property
    def environment(self) -> Environment:
        return self.config.environment

    @property
    def account_id(self) -> str:
        return self.config.account_id

    def broker_write_path_exists(self) -> bool:
        """M0 truth: no broker execution module exists anywhere in the
        platform, so there is no broker write path at all. This method is
        the explicit seam where M2's single-writer egress will land
        (design contract (d); frozen, not implemented)."""
        return False


# --------------------------------------------------------------------------
# Research sandbox guard
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ResearchSandboxPolicy:
    """Research plane policy: structurally no broker write capability, no
    trading-plane credentials, no sealed-holdout access. The policy object is
    the only sanctioned description of a research context."""

    sandbox_id: str
    network_egress: str = "DENIED"  # default no network egress
    broker_write: bool = dataclasses.field(default=False, init=False)
    can_read_sealed_holdout: bool = dataclasses.field(default=False, init=False)

    def assert_no_broker_write(self, attempted_action: str, audit: AuditLog) -> None:
        """Any trading-plane write attempted from the research plane raises
        and is audited — rejection is recorded, never silent."""
        audit.append(
            "CROSS_DOMAIN_ACCESS_REFUSED",
            {"sandbox_id": self.sandbox_id, "attempted_action": attempted_action},
        )
        raise IsolationViolation(
            f"research sandbox '{self.sandbox_id}' has no broker write path "
            f"(attempted: {attempted_action})"
        )


# --------------------------------------------------------------------------
# Paper purity scanner
# --------------------------------------------------------------------------

# Markers that must never appear in a Paper runtime's configs or state.
# Built by concatenation so this scanner file is not itself a match when the
# tracked tree is scanned (there is no allowlist).
_LIVE_URL = re.compile(r"https?://[^\s\"']*api\.alpaca\.markets[^\s\"']*", re.IGNORECASE)
_PAPER_URL = re.compile(r"https?://[^\s\"']*paper-api\.alpaca\.markets[^\s\"']*", re.IGNORECASE)
_SECRET_ASSIGN = re.compile(
    r"(?i)\b(api[_-]?secret|secret[_-]?key|private[_-]?key)\b\s*[:=]\s*['\"][^'\"]{8,}['\"]"
)
_PEM_PRIVATE = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
_ALPACA_KEY_ID = re.compile(r"\b(?:PK|AK)[A-Za-z0-9]{18,20}\b")
_ENV_LIVE_MARKERS = (
    "LIVE" + "_ACCOUNT",
    "ALPACA" + "_LIVE",
    "live" + "_oms",
    "live" + " journal",
)


def scan_for_live_artifacts(paths: list[str | Path]) -> list[str]:
    """Scan text files for Live markers. Returns a list of
    ``"<path>:<line>:<marker>"`` violations; empty list means clean."""
    violations: list[str] = []
    for root in paths:
        root = Path(root)
        if not root.exists():
            continue
        files = [root] if root.is_file() else sorted(p for p in root.rglob("*") if p.is_file())
        for f in files:
            try:
                text = f.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue  # binary or unreadable: not a text marker carrier
            for i, line in enumerate(text.splitlines(), start=1):
                # A paper endpoint URL is fine; a live host URL is not.
                if _PAPER_URL.search(line):
                    continue
                if _LIVE_URL.search(line):
                    violations.append(f"{f}:{i}:live_endpoint")
                for marker in _ENV_LIVE_MARKERS:
                    if marker in line:
                        violations.append(f"{f}:{i}:live_marker:{marker}")
                if _SECRET_ASSIGN.search(line):
                    violations.append(f"{f}:{i}:literal_secret_assignment")
                if _PEM_PRIVATE.search(line):
                    violations.append(f"{f}:{i}:private_key_block")
                if _ALPACA_KEY_ID.search(line):
                    violations.append(f"{f}:{i}:alpaca_key_id_literal")
    return violations


__all__ = [
    "IsolationViolation",
    "ResearchSandboxPolicy",
    "RuntimeContext",
    "load_runtime_config",
    "scan_for_live_artifacts",
]
