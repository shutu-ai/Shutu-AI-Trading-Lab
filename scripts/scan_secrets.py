"""Secret leak scan over Git-tracked files (M0 task: 密钥泄漏扫描).

Exit codes: 0 = clean, 1 = findings, 2 = usage error.
Patterns: PEM private-key blocks, Alpaca-style key ids (PK/AK + 18-20
alphanumerics), AWS access keys, and literal assignments to
secret/api-key/password variables. Prose mentions of the *word* "secret"
do not match; a literal assigned value does.

Complements isolation.scan_for_live_artifacts (which guards Paper configs):
this scanner covers the whole tracked tree.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

_PATTERNS: list[tuple[str, re.Pattern[str], int]] = [
    # (name, pattern, group index of the captured value; 0 = whole match)
    ("pem_private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), 0),
    ("alpaca_key_id", re.compile(r"\b(?:PK|AK)[A-Za-z0-9]{18,20}\b"), 0),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b"), 0),
    (
        "literal_secret_assignment",
        re.compile(
            r"(?i)\b(api[_-]?secret|secret[_-]?key|private[_-]?key|password|passwd|token)\b"
            r"\s*[:=]\s*['\"]([^'\"]{8,})['\"]"
        ),
        2,
    ),
    (
        "env_key_pair_assignment",
        re.compile(r"(?i)\bAPCA_(API_)?(KEY_ID|SECRET_KEY)\b\s*=\s*['\"]([^'\"]{8,})['\"]"),
        3,
    ),
]

# Placeholder values that are not real credentials (e.g. dummy accounts in
# historical evaluation scripts). Matched case-insensitively against the
# captured value; anything else is reported.
_PLACEHOLDER_VALUE = re.compile(
    r"(?i)^(dummy.*|placeholder.*|changeme.*|change[_-]?me.*|your[_-].*|example.*|xxx+|<.*>)$"
)

# Files where discussion of patterns is the point (this scanner itself, and
# the security tests that plant decoys) are scanned too — the tests plant
# decoys only in tmp dirs, so tracked-tree scans must stay clean. No
# allowlist exists on purpose: any real finding must surface.


def tracked_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [Path(line) for line in out.splitlines() if line.strip()]


def scan(files: list[Path]) -> list[str]:
    findings: list[str] = []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for name, pattern, value_group in _PATTERNS:
            for i, line in enumerate(text.splitlines(), start=1):
                m = pattern.search(line)
                if not m:
                    continue
                captured = m.group(value_group) if value_group else m.group(0)
                if _PLACEHOLDER_VALUE.match(captured):
                    continue  # documented dummy value, not a credential
                findings.append(f"{f}:{i}:{name}")
    return findings


def main() -> int:
    files = tracked_files()
    findings = scan(files)
    for f in findings:
        print(f"SECRET_LEAK:{f}")
    print(f"scan_secrets: scanned {len(files)} tracked files, {len(findings)} findings")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
