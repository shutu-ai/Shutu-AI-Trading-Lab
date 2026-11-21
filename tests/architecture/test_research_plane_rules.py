"""M3-R1-T6 — research-plane architecture rules: negative tests proving
the extended checker actually blocks forbidden imports for
trading_lab.backtest / trading_lab.validation, plus the honest
static-analysis limitation probes and a minimal runtime capability
negative test (no network in the research path).
"""

from __future__ import annotations

import datetime as dt
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "src"))

import check_architecture as ca  # noqa: E402

RESEARCH_PACKAGES = ("trading_lab.backtest", "trading_lab.validation")

# every forbidden form, per research package (mirrors the data-plane
# matrix and the sanctioned direction: contracts + security only)
_FORBIDDEN_FORMS = [
    "import trading_lab.oms\n",
    "from trading_lab.oms import OmsEngine\n",
    "from trading_lab.risk import RiskEngine\n",
    "from trading_lab.brokers import FakeBroker\n",
    "from trading_lab.data import snapshot\n",
    "from trading_lab import risk\n",
    "from trading_lab.oms.inner import Thing\n",
    "from .. import risk\n",
    "from ..oms import X\n",
    "from ... import data\n",
    "from artifacts.poc.runner import run\n",
    "__import__('trading_lab.oms')\n",
    "import importlib\nimportlib.import_module('trading_lab.brokers.http')\n",
]


class TestResearchPlaneForbiddenImports:
    @pytest.mark.parametrize("package", RESEARCH_PACKAGES)
    @pytest.mark.parametrize("code", _FORBIDDEN_FORMS)
    def test_forbidden_forms_detected(self, tmp_path, package, code):
        rel = Path(package.split(".")[-1]) / "module.py"
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(code, encoding="utf-8")
        violations = ca.check_file(f, package=package)
        assert violations, f"checker missed forbidden import: {code!r}"

    @pytest.mark.parametrize("package", RESEARCH_PACKAGES)
    def test_artifacts_fragment_forbidden(self, tmp_path, package):
        f = tmp_path / package.split(".")[-1] / "m.py"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("from ..artifacts.x import y\n", encoding="utf-8")
        assert ca.check_file(f, package=package)

    @pytest.mark.parametrize("package", RESEARCH_PACKAGES)
    def test_prefix_similar_names_not_flagged(self, tmp_path, package):
        """trading_lab.oms_tools is NOT trading_lab.oms — package-boundary
        matching must not false-positive on shared prefixes."""
        f = tmp_path / package.split(".")[-1] / "m.py"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(
            "import trading_lab.oms_tools\n"
            "from trading_lab.validation_utils import check\n",  # noqa: F401
            encoding="utf-8")
        assert ca.check_file(f, package=package) == []

    @pytest.mark.parametrize("package", RESEARCH_PACKAGES)
    def test_sanctioned_contracts_and_security_allowed(self, tmp_path,
                                                       package):
        """The ONLY cross-package dependencies research may use:
        contracts (admitted facts) and security (canonical/audit)."""
        f = tmp_path / package.split(".")[-1] / "m.py"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(
            "from trading_lab.contracts import MarketBar\n"
            "from trading_lab.security.canonical import canonical_digest\n"
            "from trading_lab.security import KillSwitch\n",
            encoding="utf-8")
        assert ca.check_file(f, package=package) == []

    @pytest.mark.parametrize("package", RESEARCH_PACKAGES)
    def test_intra_package_imports_allowed(self, tmp_path, package):
        leaf = package.split(".")[-1]
        f = tmp_path / leaf / "m.py"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(
            "from trading_lab.%s.engine import BacktestEngine\n"
            "from . import peers\n" % leaf,
            encoding="utf-8")
        assert ca.check_file(f, package=package) == []


class TestDataPlaneMustNotImportResearch:
    def test_data_importing_research_blocked(self, tmp_path):
        for target in ("trading_lab.backtest", "trading_lab.validation"):
            f = tmp_path / "data" / "m.py"
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(f"import {target}\n", encoding="utf-8")
            assert ca.check_file(f, package="trading_lab.data"), target

    def test_risk_and_oms_importing_research_blocked(self, tmp_path):
        for pkg in ("trading_lab.risk", "trading_lab.oms"):
            f = tmp_path / pkg.split(".")[-1] / "m.py"
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("import trading_lab.backtest\n", encoding="utf-8")
            assert ca.check_file(f, package=pkg), pkg


class TestHonestStaticLimitations:
    def test_computed_dynamic_import_not_caught_is_documented(self, tmp_path):
        """KNOWN LIMITATION (recorded in the checker docstring too): a
        computed dynamic import cannot be resolved statically. This test
        PINS the limitation honestly — the checker does NOT flag it, and
        runtime coverage belongs to the isolation work in M4."""
        f = tmp_path / "validation" / "m.py"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(
            "import importlib\n"
            "def load(name):\n"
            "    return importlib.import_module(name)\n",
            encoding="utf-8")
        assert ca.check_file(f, package="trading_lab.validation") == []


class TestRuntimeCapabilityNegative:
    def test_research_path_needs_no_network(self):
        """Minimal runtime probe: with socket construction disabled, the
        research path still loads a protocol, runs a backtest and writes a
        ledger — proving no network capability is exercised in this path.

        Honest boundary: this covers the stdlib socket surface for THIS
        code path only; it is not a sandbox and cannot constrain arbitrary
        dynamic code (M4 owns process isolation)."""
        import socket

        import yaml

        from trading_lab.backtest.engine import BacktestEngine
        from trading_lab.contracts import AdjustmentKind, MarketBar
        from trading_lab.validation import EvaluationProtocol
        from trading_lab.validation.ledger import ExperimentLedger

        class _NoNetwork(socket.socket):
            def __init__(self, *a, **k):
                raise AssertionError("network socket constructed in the "
                                     "offline research path")

        protocol = EvaluationProtocol.load(
            REPO_ROOT / "configs" / "evaluation_protocol.yaml")
        ts = dt.datetime(2026, 1, 5, 21, tzinfo=dt.timezone.utc)
        bars = [MarketBar.model_validate(dict(
            asset_id="SPY", ts_event_utc=ts, ts_available_utc=ts,
            interval="1d", open=Decimal("100"), high=Decimal("101"),
            low=Decimal("99"), close=Decimal("100"),
            volume=Decimal("1000000"), source="synthetic",
            adjustment=AdjustmentKind.RAW, quality="ok"))]
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(socket, "socket", _NoNetwork)
            eng = BacktestEngine(bars={"SPY": bars},
                                 initial_cash=Decimal("1000"),
                                 protocol=protocol, seed=42,
                                 dataset_hash="d" * 32, code_hash="c" * 32)
            eng.run_to_end()
            led = ExperimentLedger(
                Path(tempfile.mkdtemp()) / "l.jsonl",
                limits={"max_total_trials": 3, "max_search_queries": 3,
                        "max_failures_before_halt": 3, "max_hypotheses": 3},
                protocol_hash=protocol.protocol_hash, code_hash="c" * 32)
            led.register_trial("B0_cash", seed=42, dataset_hash="d" * 32)
            led.close()
            _ = yaml.safe_load("a: 1")  # config load also network-free
