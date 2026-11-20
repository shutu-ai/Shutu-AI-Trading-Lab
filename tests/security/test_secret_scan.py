"""Secret scanner tests: the scanner catches planted leaks (in tmp dirs) and
the tracked tree itself stays clean.

Planted literals are built by concatenation at runtime so this tracked test
file never contains a matching literal itself — the scanner has no
allowlist, so decoys must not be scannable in source.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "src"))

import scan_secrets  # noqa: E402

# Runtime-built decoys (never as one literal in this source file).
PEM_BLOCK = "-----BEGIN " + "PRIVATE KEY-----\nAAAA\n-----END PRIVATE KEY-----"
ALPACA_KEY = "PK" + "DEMO1234567890ABCDEF"          # PK + 18 alphanumerics
AWS_KEY = "AKIA" + "IOSFODNN7EXAMPLE"                # AKIA + 16 chars
SECRET_ASSIGN = "API_" + "SECRET = 's3cr3tvalue12345'"
APCA_ASSIGN = "APCA_API_" + "SECRET_KEY='notarealsecret123'"


class TestPatterns:
    def test_pem_private_key_detected(self, tmp_path):
        f = tmp_path / "key.pem"
        f.write_text(PEM_BLOCK + "\n")
        findings = scan_secrets.scan([f])
        assert any("pem_private_key" in x for x in findings)

    def test_alpaca_style_key_id_detected(self, tmp_path):
        f = tmp_path / "cfg.yaml"
        f.write_text(f"key_id: {ALPACA_KEY}\n")
        findings = scan_secrets.scan([f])
        assert any("alpaca_key_id" in x for x in findings)

    def test_aws_key_detected(self, tmp_path):
        f = tmp_path / "creds.txt"
        f.write_text(f"aws_key = {AWS_KEY}\n")
        findings = scan_secrets.scan([f])
        assert any("aws_access_key" in x for x in findings)

    def test_literal_secret_assignment_detected(self, tmp_path):
        f = tmp_path / "settings.py"
        f.write_text(SECRET_ASSIGN + "\n")
        findings = scan_secrets.scan([f])
        assert any("literal_secret_assignment" in x for x in findings)

    def test_apca_env_assignment_detected(self, tmp_path):
        f = tmp_path / "env.bash"
        f.write_text(APCA_ASSIGN + "\n")
        findings = scan_secrets.scan([f])
        assert any("env_key_pair_assignment" in x for x in findings)

    def test_prose_mentions_do_not_match(self, tmp_path):
        f = tmp_path / "docs.md"
        f.write_text(
            "# Secret handling\n\n"
            "The secret is provided by the owner. Never store a token in Git.\n"
            "Credentials come from a secret store.\n"
        )
        assert scan_secrets.scan([f]) == []

    def test_reference_refs_do_not_match(self, tmp_path):
        f = tmp_path / "config.yaml"
        f.write_text(
            "key_id_ref: env:ALPACA_PAPER_KEY_ID\nsecret_ref: secret_store:trading/live/x\n"
        )
        assert scan_secrets.scan([f]) == []

    def test_paper_endpoint_not_flagged(self, tmp_path):
        f = tmp_path / "runtime.yaml"
        f.write_text("endpoint: https://paper-api.alpaca.markets\n")
        assert scan_secrets.scan([f]) == []


class TestTrackedTree:
    def test_repo_has_no_secrets(self):
        files = scan_secrets.tracked_files()
        findings = scan_secrets.scan(files)
        assert findings == [], f"secret leak in tracked tree: {findings}"
