"""Forward daemon identity (forward-daemon-identity-v1): deterministic,
scoped, parent-linked to the M3-R2 identity — and the M3 identity itself
is proven unchanged by recomputation (task S0.4)."""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

M3_R2_CODE_HASH = \
    "af7ff10c425c0f153b2e7c1d1a86c6185267438610a81fa39a268a0f8d15f611"

REPO_ROOT = Path(__file__).resolve().parents[2]

COMPUTE_TEMPLATE = textwrap.dedent("""
    import json, sys
    root = r"{root}"
    sys.path.insert(0, root)
    sys.path.insert(0, root + "\\src")
    from apps.trading_daemon.identity import build_forward_identity
    ident = build_forward_identity(repo_root=root)
    print(json.dumps(ident.to_dict()))
""")


def test_identity_is_deterministic_across_processes():
    procs = [
        subprocess.run([sys.executable, "-c",
                        COMPUTE_TEMPLATE.format(root=str(REPO_ROOT))],
                       capture_output=True, text=True, timeout=120)
        for _ in range(2)
    ]
    payloads = []
    for p in procs:
        assert p.returncode == 0, p.stderr
        payloads.append(json.loads(p.stdout.strip().splitlines()[-1]))
    assert payloads[0]["code_hash"] == payloads[1]["code_hash"]
    assert payloads[0]["code_hash"] != M3_R2_CODE_HASH


def test_identity_scope_covers_daemon_runner_config_and_lib_deps():
    ident = build_identity()
    paths = {rel for rel, _ in ident.files}
    assert "scripts/run_m35_shadow_replay.py" in paths
    assert "configs/forward_observation.yaml" in paths
    assert "src/trading_lab/__init__.py" in paths
    assert "apps/trading_daemon/engine.py" in paths
    assert any(p.startswith("apps/trading_daemon/") for p in paths)
    assert any(p.startswith("src/trading_lab/security/") for p in paths)
    assert any(p.startswith("src/trading_lab/validation/") for p in paths)
    assert any(p.startswith("src/trading_lab/data/") for p in paths)
    assert any(p.startswith("src/trading_lab/contracts/") for p in paths)
    # out of scope: tests, docs, artifacts, third_party, backtest is NOT a
    # daemon-runtime dependency
    assert not any(p.startswith("tests/") for p in paths)
    assert not any(p.startswith("docs/") for p in paths)
    assert not any(p.startswith("artifacts/") for p in paths)
    assert not any(p.startswith("src/trading_lab/backtest/") for p in paths)


def test_identity_parent_links_to_m3_r2():
    ident = build_identity()
    parent = ident.to_dict()["parent"]
    assert parent["code_hash"] == M3_R2_CODE_HASH
    assert parent["schema"] == "research-code-identity-v1"
    assert parent["runner"] == "scripts/run_m3_r2_baselines.py"


def test_identity_changes_when_a_scope_file_changes(tmp_path):
    ident_a = build_mini_identity(tmp_path)
    target = tmp_path / "apps" / "trading_daemon" / "engine.py"
    target.write_text(target.read_text(encoding="utf-8") + "\n# drift\n",
                      encoding="utf-8")
    ident_b = build_mini_identity(tmp_path)
    assert ident_a.code_hash != ident_b.code_hash


def test_m3_r2_identity_recomputes_unchanged_at_current_head():
    """THE non-negotiable guarantee: adding the daemon did not move a
    single byte inside the M3 research-code identity scope, so the
    recorded M3-R2 code_hash still recomputes exactly."""
    from trading_lab.validation.code_identity import build_code_identity
    ident = build_code_identity(REPO_ROOT, runner="scripts/run_m3_r2_baselines.py")
    recorded = json.loads(
        (REPO_ROOT / "artifacts" / "evidence" / "M3" / "r2" /
         "code-identity-manifest.json").read_text(encoding="utf-8"))
    assert ident.code_hash == recorded["code_hash"] == M3_R2_CODE_HASH


# -- helpers ---------------------------------------------------------------


def build_identity():
    from apps.trading_daemon.identity import build_forward_identity
    return build_forward_identity(repo_root=REPO_ROOT)


def build_mini_identity(root: Path):
    """A minimal tree with every declared scope member present."""
    from apps.trading_daemon.identity import build_forward_identity
    members = [
        "apps/trading_daemon/__init__.py",
        "apps/trading_daemon/engine.py",
        "scripts/run_m35_shadow_replay.py",
        "configs/forward_observation.yaml",
        "src/trading_lab/__init__.py",
    ]
    for pkg in ("contracts", "security", "validation", "data"):
        members.append(f"src/trading_lab/{pkg}/__init__.py")
    for rel in members:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if not p.exists():
            p.write_text(f"# mini tree member: {rel}\n", encoding="utf-8")
    return build_forward_identity(repo_root=root)
