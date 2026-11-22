"""Daemon plane rules (M3.5 S6): apps/trading_daemon must never import
broker machinery, network modules, or POC/artifact code. The checker
gains rejection AND legal-import cases so the rule cannot rot."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "src"))

import check_architecture as ca  # noqa: E402

DAEMON_PACKAGE_DIR = ca.DAEMON_PACKAGE_DIR


def _write(tmp_path, code) -> Path:
    p = tmp_path / "probe_module.py"
    p.write_text(code, encoding="utf-8")
    return p


@pytest.mark.parametrize("code", [
    "import trading_lab.brokers\n",
    "import trading_lab.brokers.port\n",
    "from trading_lab.brokers.port import BrokerPort\n",
    "import socket\n",
    "import ssl\n",
    "from urllib.request import urlopen\n",
    "import http.client\n",
    "import requests\n",
    "import websockets\n",
    "import alpaca\n",
    "from alpaca.common import RESTClient\n",
    "import poc_tools\n",
    "from artifacts.evidence import something\n",
    "import importlib\nimportlib.import_module('socket')\n",
])
def test_forbidden_daemon_imports_rejected(tmp_path, code):
    violations = ca.check_daemon_file(_write(tmp_path, code))
    assert violations, f"not flagged: {code!r}"


@pytest.mark.parametrize("code", [
    "from trading_lab.security.canonical import canonical_digest\n",
    "from trading_lab.security.audit import AuditLog\n",
    "from trading_lab.data.calendar import MarketCalendar\n",
    "from trading_lab.validation.cohorts import ForwardCohort\n",
    "from trading_lab.contracts import MarketBar\n",
    "import json\nimport datetime as dt\n",
    "import yaml\n",
    "from apps.trading_daemon.envelope import ForwardEvent\n",
    "import trading_lab.brokers_extra\n",   # prefix-similar: not brokers
])
def test_legal_daemon_imports_not_flagged(tmp_path, code):
    violations = ca.check_daemon_file(_write(tmp_path, code))
    assert violations == [], f"false positive: {code!r} -> {violations}"


def test_real_daemon_package_scans_clean():
    assert DAEMON_PACKAGE_DIR.exists(), "daemon package missing"
    violations = []
    for py in sorted(DAEMON_PACKAGE_DIR.rglob("*.py")):
        violations.extend(ca.check_daemon_file(py))
    assert violations == [], violations
