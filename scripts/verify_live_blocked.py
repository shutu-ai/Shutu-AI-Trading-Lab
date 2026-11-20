"""Verify the Paper runtime contains no Live artifacts (M0 E-Gate:
"Paper 运行时不存在 Live 密钥/DB/OMS/endpoint").

Scans configs/paper/ (committed) and artifacts/state/paper/ (local runtime
state, if present) using isolation.scan_for_live_artifacts, then additionally
loads the paper runtime config through the contract layer — a config that
points Paper at the live host fails validation and this gate.

Exit codes: 0 = paper purity holds, 1 = violation found, 2 = config invalid.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading_lab.contracts import Environment  # noqa: E402
from trading_lab.security import load_runtime_config, scan_for_live_artifacts  # noqa: E402

PAPER_CONFIGS = Path("configs/paper")
PAPER_STATE = Path("artifacts/state/paper")


def main() -> int:
    violations = scan_for_live_artifacts([PAPER_CONFIGS, PAPER_STATE])
    for v in violations:
        print(f"LIVE_ARTIFACT_IN_PAPER:{v}")
    if violations:
        print(f"verify_live_blocked: {len(violations)} violation(s) — FAIL")
        return 1

    # Contract-layer double check on every paper config file.
    for cfg in sorted(PAPER_CONFIGS.glob("*.yaml")):
        try:
            rc = load_runtime_config(cfg)
        except Exception as exc:
            print(f"INVALID_PAPER_CONFIG:{cfg}:{exc}")
            return 2
        if rc.environment is not Environment.PAPER:
            print(f"INVALID_PAPER_CONFIG:{cfg}:environment is {rc.environment}")
            return 2
        print(f"paper config ok: {cfg} ({rc.environment.value}/{rc.account_id})")

    print("verify_live_blocked: paper runtime contains no live artifacts — PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
