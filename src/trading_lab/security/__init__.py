"""Security package: canonical serialization, Ed25519 signing (test keys in
M0), LiveRelease verifier, trusted Schema Gate, manual kill switch,
append-only audit log, and runtime isolation boundaries."""

from .approval import ApprovalSecrets, build_send_binding, seal_is_valid
from .audit import AuditLog, GENESIS_HASH
from .canonical import canonical_digest, canonical_json_bytes, sha256_hex
from .isolation import (
    IsolationViolation,
    ResearchSandboxPolicy,
    RuntimeContext,
    load_runtime_config,
    scan_for_live_artifacts,
)
from .kill_switch import KillSwitch, KillSwitchError
from .schema_gate import GateDecision, SchemaGate, SchemaGateAuditUnavailable, TrustedProducerContext
from .signing import (
    SIGNATURE_ALGORITHM,
    TestKeyPair,
    generate_test_keypair,
    sign_payload,
    verify_signature,
)
from .verifier import (
    ExpectedBinding,
    LiveReleaseVerifier,
    NonceLedger,
    RevocationCheck,
    RevocationLedger,
    TrustedKey,
    TrustedKeyStore,
    VerifierDecision,
)

__all__ = [
    "ApprovalSecrets",
    "build_send_binding",
    "seal_is_valid",
    "AuditLog",
    "GENESIS_HASH",
    "GateDecision",
    "ExpectedBinding",
    "IsolationViolation",
    "KillSwitch",
    "KillSwitchError",
    "LiveReleaseVerifier",
    "NonceLedger",
    "ResearchSandboxPolicy",
    "RevocationCheck",
    "RevocationLedger",
    "RuntimeContext",
    "SIGNATURE_ALGORITHM",
    "SchemaGate",
    "SchemaGateAuditUnavailable",
    "TrustedProducerContext",
    "TrustedKey",
    "TrustedKeyStore",
    "TestKeyPair",
    "VerifierDecision",
    "canonical_digest",
    "canonical_json_bytes",
    "generate_test_keypair",
    "load_runtime_config",
    "scan_for_live_artifacts",
    "sha256_hex",
    "sign_payload",
    "verify_signature",
]
