"""M3.5 forward daemon code identity (``forward-daemon-identity-v1``).

Same discipline as the M3 ``research-code-identity-v1`` scheme (LF-
normalized source digests, sorted manifest, canonical JSON, git facts
recorded but NOT hashed) over the DAEMON's own scope:

- ``apps/trading_daemon/**/*.py`` (the application layer)
- ``scripts/run_m35_shadow_replay.py`` (the official runner)
- ``configs/forward_observation.yaml`` (the frozen preregistration)
- ``src/trading_lab/__init__.py`` plus the library packages the daemon
  imports at runtime: contracts, security, validation, data

``backtest`` is deliberately NOT in scope: the daemon core never imports
it (the fixture/runner layer and the decision-equivalence test do).

The M3 identity scope is untouched by construction — nothing here writes
into ``src/trading_lab``, and a stability test recomputes the M3-R2
hash at CI time to prove it. The parent linkage to the M3-R2 identity is
part of the hashed payload, so an M3.5 identity can never be confused
with, or silently detached from, its research-plane parent.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

from trading_lab.security.canonical import canonical_json_bytes, sha256_hex

IDENTITY_SCHEMA = "forward-daemon-identity-v1"

DAEMON_PACKAGE_DIR = "apps/trading_daemon"
DEFAULT_RUNNER = "scripts/run_m35_shadow_replay.py"
CONFIG_FILE = "configs/forward_observation.yaml"

#: top-level first-party file that executes on import
_TOP_LEVEL_FILES = ("src/trading_lab/__init__.py",)

#: library packages the daemon core imports at runtime
_LIB_PACKAGES = ("contracts", "security", "validation", "data")

#: the recorded M3-R2 research identity (artifacts/evidence/M3/r2)
PARENT_IDENTITY = {
    "schema": "research-code-identity-v1",
    "code_hash":
        "af7ff10c425c0f153b2e7c1d1a86c6185267438610a81fa39a268a0f8d15f611",
    "runner": "scripts/run_m3_r2_baselines.py",
    "git_commit": "4ae119fe17ab7118075adb2899def69eafe2cd78",
    "recorded_in": "artifacts/evidence/M3/r2/code-identity-manifest.json",
}

__all__ = [
    "IDENTITY_SCHEMA",
    "ForwardIdentity",
    "build_forward_identity",
]


class IdentityError(ValueError):
    """The identity manifest cannot be built — fail closed."""


def _normalized_source_digest(data: bytes) -> str:
    """SHA-256 over the newline-normalized UTF-8 text (BOM stripped) —
    Windows-CRLF and Linux-LF checkouts of the same content hash equal."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise IdentityError(f"identity scope file is not UTF-8: {exc}") from None
    if text.startswith("﻿"):
        text = text[1:]
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return sha256_hex(normalized.encode("utf-8"))


@dataclasses.dataclass(frozen=True)
class ForwardIdentity:
    schema: str
    runner: str
    files: tuple[tuple[str, str], ...]
    code_hash: str
    parent: dict[str, Any]
    git_commit: str | None = None
    git_tree: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "runner": self.runner,
            "files": [list(f) for f in self.files],
            "code_hash": self.code_hash,
            "parent": dict(self.parent),
            "git_commit": self.git_commit,
            "git_tree": self.git_tree,
        }


def build_forward_identity(repo_root: Path | str, *,
                           runner: str = DEFAULT_RUNNER,
                           git_commit: str | None = None,
                           git_tree: str | None = None) -> ForwardIdentity:
    root = Path(repo_root)
    runner_rel = Path(runner)
    if runner_rel.is_absolute() or ".." in runner_rel.parts or \
            runner_rel.parts[:1] != ("scripts",):
        raise IdentityError(
            f"runner must be a repo-relative scripts/*.py path, got {runner!r}")
    collected: dict[str, Path] = {}

    daemon_dir = root / DAEMON_PACKAGE_DIR
    if not daemon_dir.is_dir():
        raise IdentityError(f"daemon package missing: {DAEMON_PACKAGE_DIR}")
    for py in sorted(daemon_dir.rglob("*.py")):
        if "__pycache__" in py.parts:
            continue
        collected[py.relative_to(root).as_posix()] = py

    for required in (runner_rel, Path(CONFIG_FILE),
                     *(Path(t) for t in _TOP_LEVEL_FILES)):
        p = root / required
        if not p.is_file():
            raise IdentityError(f"declared identity source missing: {required}")
        collected[required.as_posix()] = p

    for pkg in _LIB_PACKAGES:
        pkg_dir = root / "src" / "trading_lab" / pkg
        if not pkg_dir.is_dir():
            raise IdentityError(
                f"declared identity package missing: src/trading_lab/{pkg}")
        for py in sorted(pkg_dir.rglob("*.py")):
            if "__pycache__" in py.parts:
                continue
            collected[py.relative_to(root).as_posix()] = py

    files = tuple(sorted(
        (rel, _normalized_source_digest(p.read_bytes()))
        for rel, p in collected.items()))
    payload = {
        "schema": IDENTITY_SCHEMA,
        "runner": runner_rel.as_posix(),
        "files": [list(item) for item in files],
        "parent": dict(PARENT_IDENTITY),
    }
    code_hash = sha256_hex(canonical_json_bytes(payload))
    return ForwardIdentity(
        schema=IDENTITY_SCHEMA, runner=runner_rel.as_posix(), files=files,
        code_hash=code_hash, parent=dict(PARENT_IDENTITY),
        git_commit=git_commit, git_tree=git_tree)


def git_facts(repo_root: Path | str) -> tuple[str | None, str | None]:
    """Record commit + tree for independent re-verification (never part
    of code_hash). Missing git is recorded as None, not invented."""
    import subprocess
    root = Path(repo_root)
    commit = tree = None
    for args, target in ((("rev-parse", "HEAD"), "commit"),
                         (("rev-parse", "HEAD^{tree}"), "tree")):
        try:
            proc = subprocess.run(
                ["git", *args], cwd=str(root), capture_output=True,
                text=True, timeout=30)
            if proc.returncode == 0 and proc.stdout.strip():
                if target == "commit":
                    commit = proc.stdout.strip()
                else:
                    tree = proc.stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            pass
    return commit, tree
