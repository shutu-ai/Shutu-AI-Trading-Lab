"""Business-MVP plane architecture rules (task
BUSINESS-MVP-V01-VERTICAL-SLICE-20261127-R1): negative tests proving the
checker enforces the business plane's offline/MOCK_ONLY guarantee (no
network modules, no app-layer imports, no artifacts/poc) and the one-way
flow (no restricted plane may import trading_lab.business).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "src"))

import check_architecture as ca  # noqa: E402

BUSINESS_PACKAGE = "trading_lab.business"

# business must stay fully offline and out of the app layers
_FORBIDDEN_IN_BUSINESS = [
    "import socket\n",
    "import ssl\n",
    "import urllib.request\n",
    "import http.client\n",
    "import requests\n",
    "import alpaca\n",
    "from apps.trading_daemon import engine\n",
    "from apps.market_gateway.historical_bars import fetch\n",
    "from artifacts.poc.runner import run\n",
    "__import__('socket')\n",
    "import importlib\nimportlib.import_module('urllib.parse')\n",
]

# no restricted plane may import the business layer back
_RESTRICTED_PACKAGES = (
    "trading_lab.data",
    "trading_lab.risk",
    "trading_lab.oms",
    "trading_lab.backtest",
    "trading_lab.validation",
)
_BUSINESS_IMPORT_FORMS = [
    "from trading_lab.business import replay\n",
    "import trading_lab.business.features\n",
]


class TestBusinessPlaneForbiddenImports:
    @pytest.mark.parametrize("code", _FORBIDDEN_IN_BUSINESS)
    def test_business_offline_and_app_layer_bans(self, tmp_path, code):
        f = tmp_path / "business" / "module.py"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(code, encoding="utf-8")
        violations = ca.check_file(f, package=BUSINESS_PACKAGE)
        assert violations, f"checker missed forbidden import: {code!r}"

    @pytest.mark.parametrize("code", [
        "from trading_lab.contracts import events\n",
        "from trading_lab.backtest.engine import BacktestEngine\n",
        "from trading_lab.risk import RiskEngine\n",
        "from trading_lab.oms import OmsEngine\n",
        "from trading_lab.brokers import FakeBroker\n",
        "from trading_lab.data import snapshot\n",
        "from trading_lab.security import canonical\n",
    ])
    def test_business_may_import_planes(self, tmp_path, code):
        """The sanctioned direction: business consumes every plane."""
        f = tmp_path / "business" / "module.py"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(code, encoding="utf-8")
        violations = ca.check_file(f, package=BUSINESS_PACKAGE)
        assert not violations, f"sanctioned import flagged: {code!r} -> {violations}"

    @pytest.mark.parametrize("package", _RESTRICTED_PACKAGES)
    @pytest.mark.parametrize("code", _BUSINESS_IMPORT_FORMS)
    def test_no_plane_imports_business(self, tmp_path, package, code):
        f = tmp_path / package.split(".")[-1] / "module.py"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(code, encoding="utf-8")
        violations = ca.check_file(f, package=package)
        assert violations, f"checker missed business import in {package}: {code!r}"

    def test_intra_package_imports_legal(self, tmp_path):
        f = tmp_path / "business" / "replay.py"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(
            "from trading_lab.business.features import FeatureEngine\n"
            "from . import types\n",
            encoding="utf-8",
        )
        violations = ca.check_file(f, package=BUSINESS_PACKAGE)
        assert not violations, f"intra-package import flagged: {violations}"

    def test_business_package_registered_for_walking(self):
        assert BUSINESS_PACKAGE in ca.PLANE_RULES
        pkg_dir = ca.REPO / "src" / "trading_lab" / "business"
        assert pkg_dir.exists(), "business package missing from src tree"
