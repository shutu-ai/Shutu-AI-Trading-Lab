"""R4 — architecture checker self-tests: the checker must PROVE it blocks
forbidden imports (fixture files with planted violations), not merely report
a clean repository. Also pins the legal data -> contracts/security.canonical
dependency direction and package-boundary semantics (oms_tools != oms).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "src"))

import check_architecture as ca  # noqa: E402


def write(tmp_path: Path, rel: Path, text: str) -> Path:
    f = tmp_path / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text, encoding="utf-8")
    return f


# Simulate the package layout: file at <tmp>/data/module.py with package
# "trading_lab.data" — the checker resolves relative imports against it.
PKG_ROOT = "trading_lab.data"


class TestForbiddenImportsCaught:
    @pytest.mark.parametrize(
        "code",
        [
            "import trading_lab.oms\n",
            "from trading_lab.oms import OrderBook\n",
            "from trading_lab import oms\n",
            "from trading_lab.brokers import BrokerAdapter\n",
            "from trading_lab.risk import RiskEngine\n",
            "from trading_lab.oms.inner import Thing\n",
            "from .. import oms\n",
            "from ..oms import X\n",
            "from ... import brokers\n",
            "from artifacts.poc.data_poc import run\n",
            "__import__('trading_lab.oms')\n",
            "import importlib\nimportlib.import_module('trading_lab.brokers.http')\n",
        ],
    )
    def test_forbidden_forms_detected(self, tmp_path, code):
        f = write(tmp_path, Path("data") / "module.py", code)
        violations = ca.check_file(f, package=PKG_ROOT)
        assert violations, f"checker missed forbidden import: {code!r}"

    def test_artifact_poc_relative_fragment(self, tmp_path):
        f = write(tmp_path, Path("data") / "module.py", "from ..poc import run\n")
        # relative .. from trading_lab.data -> trading_lab; trading_lab.poc is
        # not a real module but contains the fragment 'poc' -> forbidden.
        violations = ca.check_file(f, package=PKG_ROOT)
        assert violations


class TestLegalImportsNotFlagged:
    @pytest.mark.parametrize(
        "code",
        [
            "from trading_lab.security.canonical import sha256_hex\n",
            "from trading_lab.contracts import MarketBar\n",
            "from trading_lab.security import AuditLog\n",
            "import datetime as dt\nfrom decimal import Decimal\n",
            "from trading_lab.oms_tools import unrelated_helper\n",  # prefix-similar, NOT a subpath
            "import trading_lab.oms_tools\n",
        ],
    )
    def test_legal_or_prefix_similar_not_flagged(self, tmp_path, code):
        f = write(tmp_path, Path("data") / "module.py", code)
        assert ca.check_file(f, package=PKG_ROOT) == [], f"false positive on: {code!r}"

    def test_rules_are_file_level_scoping_is_mains_job(self, tmp_path):
        """check_file evaluates rules for the file it is given (a forbidden
        import is forbidden regardless of package); which directories get
        scanned is main()'s decision."""
        f = write(tmp_path, Path("security") / "module.py", "import trading_lab.oms\n")
        assert ca.check_file(f, package="trading_lab.security") != []
        assert ca.main() == 0  # and the real repo data package stays clean


class TestModuleBoundary:
    def test_forbidden_matching_is_package_boundary_exact(self):
        assert ca.module_forbidden("trading_lab.oms")
        assert ca.module_forbidden("trading_lab.oms.journal")
        assert not ca.module_forbidden("trading_lab.oms_tools")
        assert not ca.module_forbidden("trading_lab.om"
                                       "sх")  # non-ascii lookalike stays unmatched
        assert ca.module_forbidden("artifacts.poc.data_poc")

    def test_repo_scan_still_clean(self):
        assert ca.main() == 0
