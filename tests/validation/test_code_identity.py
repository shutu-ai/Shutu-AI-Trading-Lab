"""M3-R2-T1 — research code identity manifest (P0 R2-P0-1 fix).

RED-first evidence: written and run BEFORE
``trading_lab.validation.code_identity`` existed (ImportError = RED); the
module was then implemented to turn these GREEN with zero weakening.

Contract under test:
- ``code_hash`` binds EVERY first-party source that executes on the
  research run path: the official runner script, ``backtest``,
  ``validation``, their import-time semantic dependencies (``contracts``,
  the whole ``security`` package, top-level package init) — never just the
  runner.
- Any byte change in participating source (engine/arms/validation/
  contracts/security/runner) must change ``code_hash`` — else result
  versions cannot be attributed.
- Deterministic across calls, processes and OS line-ending conventions
  (UTF-8, BOM-stripped, newline-normalized, sorted POSIX relpaths).
- ``__pycache__``/non-.py files excluded; missing declared scope fails
  closed; git metadata recorded but NEVER hashed into ``code_hash``.
- The legacy r1 runner-only hash is pinned as a documented insufficient
  scheme, and the new manifest must differ from it.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

from trading_lab.security.canonical import sha256_hex  # noqa: E402
from trading_lab.validation.code_identity import (  # noqa: E402
    LEGACY_R1_RUNNER_ONLY_HASH,
    CodeIdentityError,
    build_code_identity,
)

R2_RUNNER = "scripts/run_m3_r2_baselines.py"
R1_RUNNER = "scripts/run_m3_baselines.py"


def make_fake_repo(tmp_path: Path) -> Path:
    """Isolated copy of the research source tree + runner scripts (never
    the real tree — RED/GREEN probes must not touch live history)."""
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    shutil.copytree(
        REPO_ROOT / "src" / "trading_lab", root / "src" / "trading_lab",
        ignore=shutil.ignore_patterns("__pycache__"), dirs_exist_ok=True)
    (root / "scripts").mkdir()
    for name in (R1_RUNNER, R2_RUNNER):
        src = REPO_ROOT / name
        if src.is_file():
            shutil.copy2(src, root / name)
    return root


def flip_byte(root: Path, relpath: str, marker: str, replacement: str) -> None:
    p = root / relpath
    text = p.read_text(encoding="utf-8")
    assert marker in text, f"probe marker missing in {relpath}"
    p.write_text(text.replace(marker, replacement), encoding="utf-8")


# ---------------------------------------------------------------------------
# scope: every participating source is bound
# ---------------------------------------------------------------------------


class TestScopeBinding:
    @pytest.mark.parametrize("relpath,marker,replacement", [
        ("src/trading_lab/backtest/engine.py",
         "offline execution simulator", "offline execution simulator X"),
        ("src/trading_lab/backtest/arms.py",
         "transparent synthetic baselines", "transparent synthetic baselines X"),
        ("src/trading_lab/validation/ledger.py",
         "append-only, hash-chained", "append-only, hash-chained X"),
        ("src/trading_lab/validation/protocol.py",
         "Evaluation protocol registry", "Evaluation protocol registry X"),
        ("src/trading_lab/validation/code_identity.py",
         "Research code identity manifest", "Research code identity manifest X"),
        ("src/trading_lab/contracts/__init__.py",
         "event contracts", "event contracts X"),
        ("src/trading_lab/security/canonical.py",
         "Canonical JSON serialization", "Canonical JSON serialization X"),
        (R1_RUNNER, "official synthetic baseline experiment runner",
         "official synthetic baseline experiment runner X"),
    ])
    def test_participating_source_byte_change_changes_code_hash(
            self, tmp_path, relpath, marker, replacement):
        """R2-P0-1 core requirement: changing code that really affects the
        backtest MUST change code_hash even when the runner is untouched."""
        root = make_fake_repo(tmp_path)
        before = build_code_identity(root, runner=R1_RUNNER).code_hash
        flip_byte(root, relpath, marker, replacement)
        after = build_code_identity(root, runner=R1_RUNNER).code_hash
        assert before != after, (
            f"code_hash did not move after a byte change in {relpath}")

    def test_real_repo_identity_covers_expected_scope_and_nothing_else(self):
        """On the real tree: the manifest contains the runner, all four
        packages and the top init — and NO trading-plane modules (oms/
        risk/brokers/data) or anything outside the declared scope."""
        identity = build_code_identity(REPO_ROOT, runner=R2_RUNNER)
        rels = [p for p, _ in identity.files]
        for must in (
                R2_RUNNER, "src/trading_lab/__init__.py",
                "src/trading_lab/backtest/engine.py",
                "src/trading_lab/backtest/arms.py",
                "src/trading_lab/validation/ledger.py",
                "src/trading_lab/validation/protocol.py",
                "src/trading_lab/validation/code_identity.py",
                "src/trading_lab/contracts/__init__.py",
                "src/trading_lab/security/canonical.py"):
            assert must in rels, f"scope hole: {must} not in manifest"
        assert len(identity.files) >= 20
        for rel in rels:
            in_pkg = rel.startswith("src/trading_lab/") and \
                rel.split("/")[2] in ("backtest", "contracts", "security",
                                      "validation")
            assert in_pkg or rel in (R2_RUNNER, "src/trading_lab/__init__.py"), \
                f"identity scope leak: {rel}"
            for plane in ("oms", "risk", "brokers", "data"):
                assert f"trading_lab/{plane}/" not in rel, \
                    f"trading-plane code must not be in research identity: {rel}"

    def test_manifest_digest_is_canonical_json_of_sorted_file_list(self):
        """code_hash = sha256 over canonical JSON {schema, runner, files}
        — no second canonicalization, git fields excluded."""
        import json as _json

        from trading_lab.security.canonical import canonical_json_bytes
        identity = build_code_identity(
            REPO_ROOT, runner=R2_RUNNER, git_commit="a" * 40,
            git_tree="b" * 40)
        payload = {
            "schema": identity.schema,
            "runner": identity.runner,
            "files": [list(f) for f in identity.files],
        }
        assert identity.code_hash == sha256_hex(canonical_json_bytes(payload))
        assert identity.git_commit == "a" * 40  # recorded
        assert identity.git_tree == "b" * 40


# ---------------------------------------------------------------------------
# determinism: cross-call, cross-process, cross-OS line endings
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_same_tree_same_hash_across_calls(self, tmp_path):
        root = make_fake_repo(tmp_path)
        h1 = build_code_identity(root, runner=R2_RUNNER).code_hash
        h2 = build_code_identity(root, runner=R2_RUNNER).code_hash
        assert h1 == h2

    def test_same_hash_in_fresh_processes(self, tmp_path):
        """No in-memory caching: two isolated interpreters agree, and with
        an in-process computation (-I isolation, explicit sys.path)."""
        root = make_fake_repo(tmp_path)
        expected = build_code_identity(root, runner=R2_RUNNER).code_hash
        src_dir = str(root / "src")
        repo = str(root)
        code = (
            "import sys;"
            f"sys.path.insert(0, r'{src_dir}');"
            "from trading_lab.validation.code_identity import"
            " build_code_identity;"
            "print(build_code_identity("
            f"r'{repo}', runner=r'{R2_RUNNER}').code_hash)"
        )
        outs = []
        for _ in range(2):
            proc = subprocess.run(
                [sys.executable, "-I", "-c", code],
                capture_output=True, text=True, timeout=120)
            assert proc.returncode == 0, proc.stderr
            outs.append(proc.stdout.strip())
        assert outs[0] == outs[1] == expected

    def test_windows_crlf_and_linux_lf_checkouts_hash_identically(self, tmp_path):
        """GitHub Windows runners check out CRLF, Linux LF; the identity
        must be a function of source CONTENT, not checkout line endings."""
        root = make_fake_repo(tmp_path)
        h_lf = build_code_identity(root, runner=R2_RUNNER).code_hash
        target = root / "src" / "trading_lab" / "validation" / "ledger.py"
        data = target.read_bytes()
        assert b"\r\n" not in data  # repo stores LF
        target.write_bytes(data.replace(b"\n", b"\r\n"))
        h_crlf = build_code_identity(root, runner=R2_RUNNER).code_hash
        assert h_lf == h_crlf

    def test_bom_and_utf8_content_equivalence(self, tmp_path):
        root = make_fake_repo(tmp_path)
        h_before = build_code_identity(root, runner=R2_RUNNER).code_hash
        target = root / "src" / "trading_lab" / "backtest" / "engine.py"
        target.write_bytes(b"\xef\xbb\xbf" + target.read_bytes())
        h_bom = build_code_identity(root, runner=R2_RUNNER).code_hash
        assert h_before == h_bom  # BOM is a checkout artifact, not content

    def test_pycache_and_non_py_files_excluded(self, tmp_path):
        root = make_fake_repo(tmp_path)
        h_before = build_code_identity(root, runner=R2_RUNNER).code_hash
        cache = root / "src" / "trading_lab" / "backtest" / "__pycache__"
        cache.mkdir()
        (cache / "engine.cpython-313.pyc").write_bytes(b"\x00\x01junk")
        (root / "src" / "trading_lab" / "validation" / "notes.txt").write_text(
            "scratch", encoding="utf-8")
        h_after = build_code_identity(root, runner=R2_RUNNER).code_hash
        assert h_before == h_after


# ---------------------------------------------------------------------------
# fail-closed scope + legacy boundary
# ---------------------------------------------------------------------------


class TestFailClosedAndLegacy:
    def test_missing_declared_package_fails_closed(self, tmp_path):
        root = make_fake_repo(tmp_path)
        shutil.rmtree(root / "src" / "trading_lab" / "validation")
        with pytest.raises(CodeIdentityError, match="missing"):
            build_code_identity(root, runner=R2_RUNNER)

    def test_missing_runner_fails_closed(self, tmp_path):
        root = make_fake_repo(tmp_path)
        (root / R2_RUNNER).unlink()  # simulate a lost runner
        with pytest.raises(CodeIdentityError, match="runner missing"):
            build_code_identity(root, runner=R2_RUNNER)

    def test_runner_must_live_under_scripts(self, tmp_path):
        root = make_fake_repo(tmp_path)
        with pytest.raises(CodeIdentityError, match="scripts"):
            build_code_identity(root, runner="src/trading_lab/__init__.py")

    def test_legacy_r1_runner_only_hash_is_pinned_and_insufficient(
            self, tmp_path):
        """Documents the audited P0 gap, mechanically: the legacy scheme
        hashes ONLY the runner file, so an engine byte change leaves it
        unchanged. The pinned value equals the hash recorded by every r1
        official ledger entry (over normalized source text)."""
        from trading_lab.validation.code_identity import (
            _normalized_source_digest,
        )
        root = make_fake_repo(tmp_path)
        legacy_before = sha256_hex(
            (root / R1_RUNNER).read_bytes())
        flip_byte(root, "src/trading_lab/backtest/engine.py",
                  "offline execution simulator",
                  "offline execution simulator X")
        legacy_after = sha256_hex((root / R1_RUNNER).read_bytes())
        assert legacy_before == legacy_after  # the gap, demonstrated
        new_after = build_code_identity(root, runner=R1_RUNNER).code_hash
        assert new_after != legacy_after  # required new behavior
        # pinned: r1 official ledger's code_hash is exactly the legacy
        # runner-only digest of the (unchanged) r1 runner source
        assert _normalized_source_digest(
            (REPO_ROOT / R1_RUNNER).read_bytes()) == LEGACY_R1_RUNNER_ONLY_HASH
        # and the new manifest identity differs from the legacy scheme
        assert build_code_identity(
            REPO_ROOT, runner=R2_RUNNER).code_hash != LEGACY_R1_RUNNER_ONLY_HASH
