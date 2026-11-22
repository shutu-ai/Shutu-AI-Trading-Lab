"""S8 gateway plane rules (approval S8_DATA_READ_ONLY=APPROVED_WITH_SCOPE,
2026-11-22): apps/market_gateway is the ONLY network-enabled plane, and
even there the network is confined to the guarded read-only client.
Broker machinery, the trading planes, raw stdlib network primitives and
third-party SDKs stay banned; urllib is the single permitted root."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "src"))

import check_architecture as ca  # noqa: E402

GATEWAY_PACKAGE_DIR = ca.GATEWAY_PACKAGE_DIR


def _write(tmp_path: Path, code: str) -> Path:
    p = tmp_path / "probe_module.py"
    p.write_text(code, encoding="utf-8")
    return p


@pytest.mark.parametrize("code", [
    "import trading_lab.brokers\n",
    "from trading_lab.brokers.port import BrokerPort\n",
    "import trading_lab.oms\n",
    "from trading_lab.risk.engine import RiskEngine\n",
    "import socket\n",
    "import ssl\n",
    "import http.client\n",
    "import ftplib\n",
    "import telnetlib\n",
    "import xmlrpc.client\n",
    "import requests\n",
    "import websockets\n",
    "import aiohttp\n",
    "import httpx\n",
    "import alpaca\n",
    "from alpaca.common import RESTClient\n",
    "import importlib\nimportlib.import_module('socket')\n",
    "from artifacts.evidence import something\n",
    "import poc_tools\n",
])
def test_forbidden_gateway_imports_rejected(tmp_path, code):
    violations = ca.check_gateway_file(_write(tmp_path, code))
    assert violations, f"not flagged: {code!r}"


@pytest.mark.parametrize("code", [
    "import urllib.request\n",
    "import urllib.parse\n",
    "from urllib.error import HTTPError\n",
    "from trading_lab.data.calendar import MarketCalendar, ET\n",
    "from trading_lab.security.audit import AuditLog\n",
    "from trading_lab.security.canonical import canonical_digest\n",
    "from apps.trading_daemon.driver import run_replay\n",
    "from apps.trading_daemon.engine import ShadowForwardEngine\n",
    "import json\nimport re\n",
    "from decimal import Decimal\n",
    "import trading_lab.brokers_extra\n",  # prefix-similar: not brokers
])
def test_legal_gateway_imports_not_flagged(tmp_path, code):
    violations = ca.check_gateway_file(_write(tmp_path, code))
    assert violations == [], f"false positive: {code!r} -> {violations}"


def test_real_gateway_package_scans_clean():
    assert GATEWAY_PACKAGE_DIR.exists(), "gateway package missing"
    violations: list[str] = []
    for py in sorted(GATEWAY_PACKAGE_DIR.rglob("*.py")):
        violations.extend(ca.check_gateway_file(py))
    assert violations == [], violations


def test_daemon_plane_stays_network_free_after_s8():
    """The S8 work must not weaken the offline daemon's no-network rule:
    apps/trading_daemon still refuses every network root."""
    daemon_dir = ca.DAEMON_PACKAGE_DIR
    violations: list[str] = []
    for py in sorted(daemon_dir.rglob("*.py")):
        violations.extend(ca.check_daemon_file(py))
    assert violations == [], violations
