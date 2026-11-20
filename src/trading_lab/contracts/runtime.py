"""Runtime configuration contracts — the two independent Paper/Live runtime
launch configurations (M0 task: 两套独立 runtime 启动配置，Live 仅 mock 干运行).

Invariants enforced here:

- The environment is part of the config and part of validation: a PAPER
  config must reference paper-only endpoints; a LIVE config must declare an
  external secret store and a trusted-keys path (out-of-band deployed).
- Inline broker credentials are structurally impossible: the credential
  fields only accept ``env:NAME`` / ``secret_store:NAME`` references. Any
  literal key material fails validation.
- LIVE configs must carry ``dry_run: true`` until a signed LiveRelease is
  verified by the verifier (M0 has no real release; M0 live mode is mock
  dry-run only).
"""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .enums import Environment

NonEmptyStr = Annotated[str, Field(min_length=1)]

_CREDENTIAL_REF = re.compile(r"^(env:[A-Za-z_][A-Za-z0-9_]*|secret_store:[A-Za-z0-9_.\-/]+)$")
_LIVE_HOST_MARKERS = ("api.alpaca.markets",)


class _RuntimeBase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class BrokerSettings(_RuntimeBase):
    adapter: Literal["fake", "gateway_single_writer"]
    endpoint: NonEmptyStr
    key_id_ref: NonEmptyStr
    secret_ref: NonEmptyStr

    @field_validator("key_id_ref", "secret_ref")
    @classmethod
    def _refs_only(cls, v: str) -> str:
        if not _CREDENTIAL_REF.match(v):
            raise ValueError(
                "credential fields must be references ('env:NAME' or "
                "'secret_store:NAME'); literal key material is forbidden"
            )
        return v


class ReleaseVerificationSettings(_RuntimeBase):
    trusted_keys_path: NonEmptyStr
    nonce_ledger_path: NonEmptyStr
    revocation_ledger_path: NonEmptyStr
    revocation_freshness_path: NonEmptyStr
    max_revocation_staleness_seconds: Annotated[int, Field(ge=1)]
    expected_approval_identity: NonEmptyStr


class RuntimeConfig(_RuntimeBase):
    environment: Environment
    account_id: NonEmptyStr
    dry_run: bool
    broker: BrokerSettings
    journal_dir: NonEmptyStr
    audit_log_path: NonEmptyStr
    kill_switch_dir: NonEmptyStr
    release_verification: ReleaseVerificationSettings | None = None

    @model_validator(mode="after")
    def _environment_purity(self) -> "RuntimeConfig":
        # Unresolved template placeholders must never reach a runtime.
        for label, value in (
            ("account_id", self.account_id),
            (
                "expected_approval_identity",
                self.release_verification.expected_approval_identity
                if self.release_verification
                else "",
            ),
        ):
            if "{{" in value:
                raise ValueError(f"unresolved placeholder in {label}: template must be resolved before load")
        # Paper runtime must never point at the live trading host.
        if self.environment is Environment.PAPER:
            live_host = any(m in self.broker.endpoint for m in _LIVE_HOST_MARKERS)
            if live_host and "paper" not in self.broker.endpoint:
                raise ValueError("PAPER config endpoint must not reference the live trading host")
            if self.broker.adapter == "gateway_single_writer":
                raise ValueError(
                    "PAPER config must use the 'fake' adapter in M0 "
                    "(single-writer gateway is a LIVE design contract, frozen not implemented)"
                )
        # LIVE: dry-run only in M0, credentials only via external secret store.
        if self.environment is Environment.LIVE:
            if not self.dry_run:
                raise ValueError(
                    "LIVE config must set dry_run=true; non-dry-run Live requires a "
                    "verified LiveRelease and is out of M0 scope"
                )
            if not self.broker.key_id_ref.startswith("secret_store:") or not (
                self.broker.secret_ref.startswith("secret_store:")
            ):
                raise ValueError(
                    "LIVE credentials must come from an external secret store "
                    "('secret_store:...'), never from environment variables"
                )
            if self.release_verification is None:
                raise ValueError(
                    "LIVE config requires release_verification settings "
                    "(trusted keys, nonce/revocation ledgers, freshness bound)"
                )
        return self


__all__ = ["BrokerSettings", "ReleaseVerificationSettings", "RuntimeConfig"]
