"""Research code identity manifest (M3-R2-T1) — fixes audited P0 R2-P0-1:
the official ``code_hash`` used to be the byte hash of the runner script
ALONE, so algorithm changes in ``backtest``/``validation`` did not move
the experiment identity. This module is the single authority for the
research code identity.

Contract (fixed, minimal, explainable):

- **Scope**: the official runner script (exactly one, under ``scripts/``)
  plus every first-party source that executes on the research import/run
  path: ``src/trading_lab/backtest/**``, ``validation/**``, and their
  import-time semantic dependencies — ``contracts/**`` (bar/action
  validation semantics), the whole ``security`` package (its ``__init__``
  executes every security submodule when ``canonical`` is imported), and
  the top-level ``trading_lab/__init__.py``. Trading-plane code
  (``oms``/``risk``/``brokers``/``data``) is deliberately OUTSIDE: it must
  never influence research results (architecture rules forbid the import).
- **Normalization**: identity is a function of source CONTENT, not
  checkout artifacts — bytes are decoded as UTF-8, a leading BOM is
  stripped, and CRLF/CR line endings are normalized to LF. A GitHub
  Windows (CRLF) and a Linux (LF) checkout of the same commit therefore
  produce the SAME ``code_hash``.
- **Exclusions**: ``__pycache__`` and every non-``.py`` file are excluded;
  third-party dependencies are environment, not research code identity.
- **Manifest**: ``files`` is a path-sorted tuple of
  ``(posix_relpath, normalized_sha256)``; ``code_hash`` is the SHA-256 of
  the canonical JSON (security.canonical — no second canonicalization) of
  ``{"schema", "runner", "files"}``. ``git_commit``/``git_tree`` are
  recorded for independent re-verification but are NEVER hashed in: the
  identity is a function of the on-disk source that actually ran.
- **Fail closed**: any missing declared scope member (runner, package,
  top-level file) is a CodeIdentityError — a silently reduced identity is
  impossible.
- **Legacy boundary**: ``LEGACY_R1_RUNNER_ONLY_HASH`` pins the r1 scheme
  (runner bytes only). r1 ledger entries keep that value; it is marked
  ``RUNNER_ONLY_LEGACY`` in protocol v2's batch registry and is not
  extended, re-signed or rewritten.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

from trading_lab.security.canonical import canonical_json_bytes, sha256_hex

__all__ = [
    "IDENTITY_PACKAGES",
    "IDENTITY_SCHEMA",
    "IDENTITY_TOP_LEVEL_FILES",
    "LEGACY_R1_RUNNER_ONLY_HASH",
    "CodeIdentity",
    "CodeIdentityError",
    "build_code_identity",
]

IDENTITY_SCHEMA = "research-code-identity-v1"

#: first-party packages that execute on the official research run path
#: (backtest/validation are the algorithm; contracts/security are their
#: import-time semantic dependencies — see module docstring).
IDENTITY_PACKAGES: tuple[str, ...] = (
    "backtest", "contracts", "security", "validation")

#: top-level first-party files that execute on import
IDENTITY_TOP_LEVEL_FILES: tuple[str, ...] = (
    "src/trading_lab/__init__.py",
)

#: the r1 official ledger's code_hash — computed by the r1 runner as the
#: byte hash of ``scripts/run_m3_baselines.py`` alone (LF-normalized text
#: equals the raw bytes of that file as committed). Pinned so any change
#: to the r1 runner source that would break r1 reproduction fails loudly.
LEGACY_R1_RUNNER_ONLY_HASH = (
    "c0a9ede5bf4dea02e5a4141f3a494c29291039d678ed3aae2380619d510a8d0f")


class CodeIdentityError(ValueError):
    """The code identity manifest cannot be built — fail closed."""


def _normalized_source_digest(data: bytes) -> str:
    """SHA-256 of the newline-normalized UTF-8 source text (BOM stripped).

    Windows-CRLF and Linux-LF checkouts of the same content hash equal;
    any real content change still moves the digest."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CodeIdentityError(
            f"identity scope file is not valid UTF-8: {exc}") from None
    if text.startswith("﻿"):
        text = text[1:]
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return sha256_hex(normalized.encode("utf-8"))


@dataclasses.dataclass(frozen=True)
class CodeIdentity:
    """One immutable research code identity: the sorted source manifest
    plus the single ``code_hash`` that experiments, results, ledgers and
    recomputation records must all reference."""

    schema: str
    runner: str                                   # posix relpath, scripts/
    files: tuple[tuple[str, str], ...]            # ((relpath, sha256)…)
    code_hash: str                                # the experiment identity
    git_commit: str | None = None                 # recorded, NOT hashed
    git_tree: str | None = None                   # recorded, NOT hashed

    def file_digest(self, relpath: str) -> str | None:
        index = {p: h for p, h in self.files}
        return index.get(relpath)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "runner": self.runner,
            "files": [list(f) for f in self.files],
            "code_hash": self.code_hash,
            "git_commit": self.git_commit,
            "git_tree": self.git_tree,
        }


def build_code_identity(
        repo_root: Path | str, *, runner: str,
        git_commit: str | None = None,
        git_tree: str | None = None) -> CodeIdentity:
    """Build the identity of the research code tree rooted at ``repo_root``.

    ``runner`` must be one repo-relative ``scripts/*.py`` path — it is the
    single entry script whose bytes join the manifest together with the
    fixed package scope. Missing scope members fail closed; ``__pycache__``
    and non-``.py`` files are excluded; the result is deterministic.
    """
    root = Path(repo_root)
    runner_rel = Path(runner)
    if runner_rel.is_absolute() or ".." in runner_rel.parts \
            or runner_rel.parts[:1] != ("scripts",) \
            or runner_rel.suffix != ".py":
        raise CodeIdentityError(
            f"runner must be one repo-relative scripts/*.py path, got "
            f"{runner!r}")
    runner_path = root / runner_rel
    if not runner_path.is_file():
        raise CodeIdentityError(f"declared runner missing: {runner}")

    collected: dict[str, Path] = {runner_rel.as_posix(): runner_path}
    for top in IDENTITY_TOP_LEVEL_FILES:
        p = root / top
        if not p.is_file():
            raise CodeIdentityError(f"declared identity source missing: {top}")
        collected[top] = p
    for pkg in IDENTITY_PACKAGES:
        pkg_dir = root / "src" / "trading_lab" / pkg
        if not pkg_dir.is_dir():
            raise CodeIdentityError(
                f"declared identity package missing: "
                f"src/trading_lab/{pkg}")
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
    }
    code_hash = sha256_hex(canonical_json_bytes(payload))
    return CodeIdentity(
        schema=IDENTITY_SCHEMA, runner=runner_rel.as_posix(), files=files,
        code_hash=code_hash, git_commit=git_commit, git_tree=git_tree)
