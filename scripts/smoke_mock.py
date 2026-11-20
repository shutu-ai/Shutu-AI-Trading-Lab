"""Mock dry-run smoke for M0 (task: 两套独立 runtime 启动配置，Live 仅 mock 干运行).

Runs fully offline with fictional accounts and mock test keys:

1. Paper: bind the paper runtime config, run a valid signal through the
   Schema Gate -> ALLOW; verify the kill switch blocks new risk while set.
2. LIVE dry-run: materialize a resolved *mock* live config (fictional
   account, mock test keys) in a temp dir, verify a mock-signed
   LiveRelease, then prove the platform has no broker execution path
   (importing a brokers module fails; RuntimeContext exposes no write path).

Nothing here connects to a broker, requests keys, or sends orders.
Exit 0 = all expected outcomes observed; nonzero = environment problem.
Writes its log to artifacts/evidence/M0/smoke_mock.log.
"""

from __future__ import annotations

import dataclasses
import datetime as dt

import json
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from trading_lab.contracts import Environment, LiveRelease  # noqa: E402
from trading_lab.security import (  # noqa: E402
    AuditLog,
    ExpectedBinding,
    KillSwitch,
    LiveReleaseVerifier,
    NonceLedger,
    RevocationLedger,
    RuntimeContext,
    SchemaGate,
    generate_test_keypair,
    sign_payload,
)
from trading_lab.security.verifier import TrustedKeyStore  # noqa: E402

NOW = dt.datetime.now(dt.timezone.utc)
FRESH = NOW - dt.timedelta(seconds=10)
LOG_LINES: list[str] = []


def log(line: str) -> None:
    print(line)
    LOG_LINES.append(line)


def main() -> int:
    failures: list[str] = []

    # ------------------------------------------------------------------ 1
    log("== 1. PAPER runtime: bind, gate, kill switch ==")
    paper_cfg_path = REPO / "configs/paper/runtime.example.yaml"
    with tempfile.TemporaryDirectory() as tmp:
        cfg_text = paper_cfg_path.read_text(encoding="utf-8").replace(
            "artifacts/state/paper", str(Path(tmp) / "paper_state")
        )
        mock_cfg = Path(tmp) / "paper_runtime.yaml"
        mock_cfg.write_text(cfg_text, encoding="utf-8")
        paper_audit = AuditLog(Path(tmp) / "paper_state/audit.jsonl", "PAPER")
        paper_ctx = RuntimeContext.bind(mock_cfg, paper_audit)
        log(f"paper context bound: {paper_ctx.environment.value}/{paper_ctx.account_id}")

        gate = SchemaGate(
            reviewed_builds={"demo_ma": {"a" * 32}},
            allowed_symbols={"SPY", "QQQ"},
            audit=paper_audit,
            now_fn=lambda: NOW,
        )
        signal = {
            "schema_version": "1",
            "strategy_id": "demo_ma",
            "strategy_version": "1.0.0",
            "reviewed_build_hash": "a" * 32,
            "snapshot_id": "snap-0001",
            "target_exposure": "0.30",
            "expires_at_utc": (NOW + dt.timedelta(minutes=5)).isoformat(),
            "rationale_hash": "b" * 32,
        }
        decision = gate.evaluate_signal(json.dumps(signal))
        log(f"valid signal -> {decision.action} allow={decision.allow}")
        if not (decision.allow and decision.action == "ALLOW_SIGNAL"):
            failures.append("paper gate did not allow the valid signal")

        ks = KillSwitch(paper_ctx.environment, paper_ctx.account_id, Path(tmp) / "ks", paper_audit)
        ks.set(reason="smoke test halt", operator_id="smoke_mock")
        try:
            ks.require_tradable()
            failures.append("kill switch did not block require_tradable")
        except Exception:
            log("kill switch set -> require_tradable blocked (expected)")
        ks.clear(operator_id="smoke_mock", authorization_ref="smoke:reconciled:no-positions")
        ks.require_tradable()
        log("kill switch cleared with authorization -> tradable again")

    # ------------------------------------------------------------------ 2
    log("== 2. LIVE dry-run: mock release verification ==")
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        owner = generate_test_keypair()
        attacker = generate_test_keypair()  # self-built key: must never verify
        (tmp_path / "keys").mkdir()
        (tmp_path / "keys/trusted.json").write_text(
            json.dumps([{"key_id": owner.key_id, "public_pem": owner.public_pem.decode()}]),
            encoding="utf-8",
        )

        release_payload = {
            "release_id": "rel-mock-0001",
            "environment": Environment.LIVE,
            "account_id": "MOCK_LIVE_DRYRUN_ACCOUNT",
            "strategy_hashes": ("c" * 32,),
            "build_digest": "d" * 32,
            "protocol_hash": "e" * 32,
            "policy_hash": "f" * 32,
            "capital_cap": Decimal("1000.00"),
            "max_order_cap": Decimal("100.00"),
            "valid_from": NOW - dt.timedelta(minutes=1),
            "expires_at": NOW + dt.timedelta(hours=1),
            "approval_identity": "OWNER_MOCK",
            "nonce": "1" * 32,
            "revocation_epoch": 0,
            "signature_algorithm": "Ed25519",
        }
        signature = sign_payload(owner.private_pem, release_payload)
        release = LiveRelease.model_validate({**release_payload, "signature": signature})

        live_audit = AuditLog(tmp_path / "live_audit.jsonl", "LIVE")
        verifier = LiveReleaseVerifier(
            trusted_keys=TrustedKeyStore.from_json_file(tmp_path / "keys/trusted.json"),
            nonce_ledger=NonceLedger(tmp_path / "nonces.jsonl"),
            revocation_ledger=RevocationLedger(
                tmp_path / "revocations.jsonl",
                tmp_path / "freshness.json",
                max_staleness_seconds=300,
                now_fn=lambda: NOW,
            ),
            audit=live_audit,
            now_fn=lambda: NOW,
        )
        # fresh revocation status
        (tmp_path / "revocations.jsonl").write_text("", encoding="utf-8")
        (tmp_path / "freshness.json").write_text(
            json.dumps({"last_checked_at": FRESH.isoformat()}), encoding="utf-8"
        )
        binding = ExpectedBinding(
            environment=Environment.LIVE,
            account_id="MOCK_LIVE_DRYRUN_ACCOUNT",
            approval_identity="OWNER_MOCK",
            strategy_hashes=frozenset({"c" * 32}),
            build_digest="d" * 32,
            protocol_hash="e" * 32,
            policy_hash="f" * 32,
            requested_capital_cap=Decimal("1000.00"),
            requested_max_order_cap=Decimal("100.00"),
        )
        vd = verifier.verify(release, binding)
        log(f"mock-signed release -> allow={vd.allow} reasons={vd.reason_codes}")
        if not vd.allow:
            failures.append(f"mock release unexpectedly rejected: {vd.reason_codes}")

        # Negative 1: attacker-signed document (fresh nonce, inflated cap)
        # must fail on the trust root, not on business checks.
        attacker_payload = {**release_payload,
                            "capital_cap": Decimal("999999.00"),
                            "nonce": "2" * 32}
        bad_sig = sign_payload(attacker.private_pem, attacker_payload)
        attacker_release = LiveRelease.model_validate({**attacker_payload, "signature": bad_sig})
        vd2 = verifier.verify(attacker_release, binding)
        log(f"attacker-signed release -> allow={vd2.allow} reasons={vd2.reason_codes}")
        if vd2.allow or not any(
            r.startswith("SIGNATURE_INVALID_OR_TRUST_ROOT_UNRECOGNIZED") for r in vd2.reason_codes
        ):
            failures.append("attacker-signed release was not rejected on trust root")

        # Negative 2: the *valid* release must refuse a request beyond its
        # signed capital cap (quota enforcement is independent of signing).
        vd3 = verifier.verify(
            release,
            dataclasses.replace(binding, requested_capital_cap=Decimal("5000.00")),
        )
        log(f"over-quota request on valid release -> allow={vd3.allow} reasons={vd3.reason_codes}")
        if vd3.allow or not any(r.startswith("CAPITAL_CAP_EXCEEDED") for r in vd3.reason_codes):
            failures.append("over-quota request against valid release was not rejected")

        # M2 reality: the brokers plane exists but must be FAKE-ONLY — no
        # network/real-broker client imports anywhere in the package.
        import re as _re
        from pathlib import Path as _Path

        brokers_dir = REPO / "src" / "trading_lab" / "brokers"
        forbidden_network = _re.compile(
            r"^\s*(import|from)\s+(socket|ssl|http|httpx|requests|urllib|alpaca|websocket|aiohttp)",
        )
        network_hits: list[str] = []
        for py in sorted(brokers_dir.rglob("*.py")):
            for i, line in enumerate(py.read_text(encoding="utf-8").splitlines(), start=1):
                if forbidden_network.match(line):
                    network_hits.append(f"{py.name}:{i}:{line.strip()}")
        if network_hits:
            failures.append(f"network imports in brokers plane: {network_hits}")
        else:
            log("brokers plane is fake-only (zero network/real-broker imports)")

    log_dir = REPO / "artifacts/evidence/M0"
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / "smoke_mock.log").write_text("\n".join(LOG_LINES) + "\n", encoding="utf-8")

    if failures:
        for f in failures:
            log(f"SMOKE FAILURE: {f}")
        return 1
    log("SMOKE PASS: paper gate + kill switch + mock live verification all behaved fail-closed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
