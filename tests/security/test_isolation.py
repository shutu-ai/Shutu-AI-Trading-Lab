"""Runtime isolation tests: two independent configs, no in-process
environment switch, research plane has no broker write path, paper runtime
must be free of live artifacts."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from trading_lab.contracts import Environment
from trading_lab.security import (
    AuditLog,
    IsolationViolation,
    ResearchSandboxPolicy,
    RuntimeContext,
    load_runtime_config,
    scan_for_live_artifacts,
)

REPO = REPO_ROOT
PAPER_CONFIG = REPO / "configs/paper/runtime.example.yaml"
LIVE_TEMPLATE = REPO / "configs/live/runtime.template.yaml"


def paper_config(tmp_path: Path, replacements: dict[str, str] | None = None) -> Path:
    text = PAPER_CONFIG.read_text(encoding="utf-8")
    text = text.replace("artifacts/state/paper", str(tmp_path / "paper_state"))
    for old, new in (replacements or {}).items():
        text = text.replace(old, new)
    path = tmp_path / "paper_runtime.yaml"
    path.write_text(text, encoding="utf-8")
    return path


class TestRuntimeBinding:
    def test_paper_context_binds_and_freezes(self, tmp_path):
        audit = AuditLog(tmp_path / "audit.jsonl", "PAPER")
        ctx = RuntimeContext.bind(paper_config(tmp_path), audit)
        assert ctx.environment is Environment.PAPER
        assert ctx.account_id == "PAPER_TEST_ACCOUNT"

    def test_environment_cannot_be_switched_in_process(self, tmp_path):
        """§6.3: 不得在一个进程里通过 paper=false 切换环境."""
        audit = AuditLog(tmp_path / "audit.jsonl", "PAPER")
        ctx = RuntimeContext.bind(paper_config(tmp_path), audit)
        for target_attr, value in (
            ("config.environment", Environment.LIVE),
            ("environment", Environment.LIVE),
        ):
            with pytest.raises(Exception):
                if "." in target_attr:
                    setattr(ctx.config, "environment", value)
                else:
                    setattr(ctx, "environment", value)
        assert ctx.environment is Environment.PAPER

    def test_paper_config_with_live_host_rejected(self, tmp_path):
        bad = paper_config(
            tmp_path,
            {"https://paper-api.alpaca.markets": "https://api.alpaca.markets"},
        )
        with pytest.raises(Exception):
            load_runtime_config(bad)

    # -- R2 (M0-REVIEW-REMEDIATION-001): endpoint origin whitelist ----------
    # Policy: exact scheme https + exact hostname, bare origin only (no
    # path/query/fragment/userinfo/port). Hostname comparison is exact, never
    # substring containment.

    DISGUISED_LIVE_URLS = [
        "https://api.alpaca.markets/paper",          # live host + "paper" path
        "https://api.alpaca.markets/v2?paper=test",  # live host + "paper" query
        "https://paper-api.alpaca.markets.evil.com",  # suffix confusion
        "https://evil.com/paper-api.alpaca.markets",  # path confusion
        "http://paper-api.alpaca.markets",            # wrong scheme
        "ftp://paper-api.alpaca.markets",             # wrong scheme
        "https://user:pw@paper-api.alpaca.markets",   # userinfo
        "https://paper-api.alpaca.markets:8443",      # explicit port
        "https://paper-api.alpaca.markets/v2",        # non-empty path
        "https://paper-api.alpaca.markets/",          # trailing slash path
        "https://paper-api.alpaca.markets?x=1",       # query
        "not-a-url",                                  # unparseable
        "",                                           # empty
        "https://",                                   # no host
    ]

    def test_disguised_or_invalid_paper_endpoints_rejected(self, tmp_path):
        """M0-REVIEW-REMEDIATION-001 R2: the old 'paper in URL' containment
        check accepted live hosts carrying a 'paper' path/query (bypass)."""
        for url in self.DISGUISED_LIVE_URLS:
            bad = paper_config(
                tmp_path,
                {"https://paper-api.alpaca.markets": url},
            )
            with pytest.raises(Exception, match=r"endpoint|scheme|host|port|userinfo"):
                load_runtime_config(bad)

    def test_paper_hostname_case_insensitive_exact_match(self, tmp_path):
        ok = paper_config(
            tmp_path,
            {"https://paper-api.alpaca.markets": "https://PAPER-API.ALPACA.MARKETS"},
        )
        cfg = load_runtime_config(ok)
        assert cfg.environment is Environment.PAPER

    def test_live_template_host_is_exact_live_origin(self):
        """LIVE whitelist accepts exactly api.alpaca.markets (resolved
        template loads with dry_run=true); a paper host in a LIVE config is
        not the trusted live origin."""
        resolved = (
            LIVE_TEMPLATE.read_text(encoding="utf-8")
            .replace("{{LIVE_ACCOUNT_ID}}", "MOCK_LIVE_DRYRUN_ACCOUNT")
            .replace("{{OWNER_IDENTITY}}", "OWNER_MOCK")
            .replace("https://api.alpaca.markets", "https://paper-api.alpaca.markets")
        )
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "live.yaml"
            path.write_text(resolved, encoding="utf-8")
            with pytest.raises(Exception):
                load_runtime_config(path)

    def test_inline_credentials_rejected(self, tmp_path):
        bad = paper_config(
            tmp_path,
            {"env:ALPACA_PAPER_KEY_ID": "AK" + "FOOBARBAZ0011223344"},
        )
        with pytest.raises(Exception):
            load_runtime_config(bad)

    def test_template_placeholders_rejected(self, tmp_path):
        raw = PAPER_CONFIG.read_text(encoding="utf-8").replace(
            "PAPER_TEST_ACCOUNT", "{{LIVE_ACCOUNT_ID}}"
        )
        path = tmp_path / "tpl.yaml"
        path.write_text(raw, encoding="utf-8")
        with pytest.raises(Exception):
            load_runtime_config(path)

    def test_committed_paper_config_is_valid(self):
        cfg = load_runtime_config(PAPER_CONFIG)
        assert cfg.environment is Environment.PAPER

    def test_committed_live_template_requires_resolution(self):
        """The live template carries placeholders -> must not load until the
        deploy step resolves them (fail-closed template)."""
        with tempfile.TemporaryDirectory() as td:
            raw_path = Path(td) / "raw.yaml"
            raw_path.write_text(LIVE_TEMPLATE.read_text(encoding="utf-8"), encoding="utf-8")
            with pytest.raises(Exception):
                load_runtime_config(raw_path)

            resolved = (
                LIVE_TEMPLATE.read_text(encoding="utf-8")
                .replace("{{LIVE_ACCOUNT_ID}}", "MOCK_LIVE_DRYRUN_ACCOUNT")
                .replace("{{OWNER_IDENTITY}}", "OWNER_MOCK")
                .replace("artifacts/state/live", str(Path(td) / "live_state"))
                .replace("configs/live/trusted_public_keys.json", str(Path(td) / "keys.json"))
            )
            ok_path = Path(td) / "resolved.yaml"
            ok_path.write_text(resolved, encoding="utf-8")
            cfg = load_runtime_config(ok_path)
            assert cfg.environment is Environment.LIVE
            assert cfg.dry_run is True
            assert cfg.broker.key_id_ref.startswith("secret_store:")

    def test_live_non_dry_run_rejected(self, tmp_path):
        resolved = (
            LIVE_TEMPLATE.read_text(encoding="utf-8")
            .replace("{{LIVE_ACCOUNT_ID}}", "X")
            .replace("{{OWNER_IDENTITY}}", "Y")
            .replace("dry_run: true", "dry_run: false")
        )
        path = tmp_path / "live.yaml"
        path.write_text(resolved, encoding="utf-8")
        with pytest.raises(Exception):
            load_runtime_config(path)

    def test_live_env_credentials_rejected(self, tmp_path):
        """LIVE 凭据必须走外部 secret store，不允许环境变量引用。"""
        resolved = (
            LIVE_TEMPLATE.read_text(encoding="utf-8")
            .replace("{{LIVE_ACCOUNT_ID}}", "X")
            .replace("{{OWNER_IDENTITY}}", "Y")
            .replace("secret_store:trading/live/alpaca_key_id", "env:ALPACA_LIVE_KEY_ID")
            .replace("artifacts/state/live", str(tmp_path / "live_state"))
            .replace("configs/live/trusted_public_keys.json", str(tmp_path / "keys.json"))
        )
        path = tmp_path / "live.yaml"
        path.write_text(resolved, encoding="utf-8")
        with pytest.raises(Exception):
            load_runtime_config(path)


class TestResearchSandbox:
    def test_no_broker_write_path(self, tmp_path):
        audit = AuditLog(tmp_path / "audit.jsonl", "RESEARCH")
        policy = ResearchSandboxPolicy(sandbox_id="rs-1")
        assert policy.broker_write is False
        with pytest.raises(IsolationViolation):
            policy.assert_no_broker_write("submit_order", audit)
        types = [
            json.loads(l)["event_type"]
            for l in (tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines()
            if l.strip()
        ]
        assert types == ["CROSS_DOMAIN_ACCESS_REFUSED"]

    def test_context_exposes_no_write_path_in_m0(self, tmp_path):
        audit = AuditLog(tmp_path / "audit.jsonl", "PAPER")
        ctx = RuntimeContext.bind(paper_config(tmp_path), audit)
        assert ctx.broker_write_path_exists() is False


class TestPaperPurity:
    def test_committed_paper_tree_is_clean(self):
        assert scan_for_live_artifacts([REPO / "configs/paper"]) == []

    def test_planted_live_key_detected(self, tmp_path):
        evil = tmp_path / "leaked.yaml"
        # concatenation: this tracked test file must not itself contain a
        # scannable key literal (the scanner has no allowlist)
        evil.write_text(
            "paper_broker:\n  key_id: " + "PK" + "DEMO1234567890ABCDEF" + "\n",
            encoding="utf-8",
        )
        violations = scan_for_live_artifacts([evil])
        assert any("alpaca_key_id_literal" in v for v in violations)

    def test_planted_live_endpoint_detected(self, tmp_path):
        evil = tmp_path / "endpoint.yaml"
        evil.write_text("broker:\n  endpoint: https://api.alpaca.markets\n", encoding="utf-8")
        violations = scan_for_live_artifacts([evil])
        assert any("live_endpoint" in v for v in violations)

    def test_paper_endpoint_not_flagged(self, tmp_path):
        ok = tmp_path / "paper.yaml"
        ok.write_text("broker:\n  endpoint: https://paper-api.alpaca.markets\n", encoding="utf-8")
        assert scan_for_live_artifacts([ok]) == []

    def test_committed_code_and_paper_configs_clean(self):
        # configs/live is excluded by design: the live template legitimately
        # names the live endpoint; paper purity is about Paper trees + code.
        violations = scan_for_live_artifacts(
            [REPO / "configs/paper", REPO / "scripts", REPO / "src"]
        )
        assert violations == []
