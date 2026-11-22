"""S8 forward-daemon identity scope: deterministic, parent-linked to the
M3-R2 identity, covering the gateway plane + real preregistration +
selftest fixture + S8 runner, and distinct from the synthetic identity.
The M3-R2 hash itself remains untouched (recomputed at head)."""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

M3_R2_CODE_HASH = \
    "af7ff10c425c0f153b2e7c1d1a86c6185267438610a81fa39a268a0f8d15f611"

COMPUTE_TEMPLATE = textwrap.dedent("""
    import json, sys
    root = r"{root}"
    sys.path.insert(0, root)
    sys.path.insert(0, root + "\\src")
    from apps.trading_daemon.identity import build_s8_forward_identity
    ident = build_s8_forward_identity(root)
    print(json.dumps(ident.to_dict()))
""")


def _s8_identity():
    from apps.trading_daemon.identity import build_s8_forward_identity
    return build_s8_forward_identity(REPO_ROOT)


def test_s8_identity_is_deterministic_across_processes():
    payloads = []
    for _ in range(2):
        proc = subprocess.run(
            [sys.executable, "-c",
             COMPUTE_TEMPLATE.format(root=str(REPO_ROOT))],
            capture_output=True, text=True, timeout=180)
        assert proc.returncode == 0, proc.stderr
        payloads.append(json.loads(proc.stdout.strip().splitlines()[-1]))
    assert payloads[0]["code_hash"] == payloads[1]["code_hash"]


def test_s8_identity_scope_covers_gateway_config_fixture_runner():
    ident = _s8_identity()
    paths = {rel for rel, _ in ident.files}
    assert "scripts/run_m35_s8_shadow_real.py" in paths
    # the ranged production preregistration AND the pinned legacy pair
    assert "configs/forward_observation_s8_real_v2.yaml" in paths
    assert "configs/forward_observation_s8_real.yaml" in paths
    assert "apps/market_gateway/fixtures/selftest_daily_bars_v2.json" in paths
    assert "apps/market_gateway/fixtures/selftest_bars.json" in paths
    assert any(p.startswith("apps/market_gateway/") for p in paths)
    # ...and still covers the daemon core it reuses
    assert any(p.startswith("apps/trading_daemon/") for p in paths)
    assert any(p.startswith("src/trading_lab/data/") for p in paths)
    # out of scope stays out
    assert not any(p.startswith("tests/") for p in paths)
    assert not any(p.startswith("artifacts/") for p in paths)


def test_s8_identity_differs_from_synthetic_identity():
    from apps.trading_daemon.identity import build_forward_identity
    synthetic = build_forward_identity(REPO_ROOT)
    s8 = _s8_identity()
    assert s8.code_hash != synthetic.code_hash
    assert s8.runner == "scripts/run_m35_s8_shadow_real.py"
    assert synthetic.runner == "scripts/run_m35_shadow_replay.py"
    # both link the SAME frozen parent
    assert s8.parent["code_hash"] == synthetic.parent["code_hash"] == \
        M3_R2_CODE_HASH


def test_m3_r2_identity_still_recomputes_unchanged():
    """The U-1 fix touches src/trading_lab/data — NOT in the M3-R2
    identity scope (backtest/contracts/security/validation only), so the
    recorded M3-R2 hash still recomputes exactly at this head."""
    from trading_lab.validation.code_identity import build_code_identity
    ident = build_code_identity(
        REPO_ROOT, runner="scripts/run_m3_r2_baselines.py")
    recorded = json.loads(
        (REPO_ROOT / "artifacts" / "evidence" / "M3" / "r2" /
         "code-identity-manifest.json").read_text(encoding="utf-8"))
    assert ident.code_hash == recorded["code_hash"] == M3_R2_CODE_HASH
