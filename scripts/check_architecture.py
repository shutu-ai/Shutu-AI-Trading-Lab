"""Architecture boundary check (M1 task §5; hardened per
M1-REVIEW-REMEDIATION-001 R4; extended in M3-R1-T6 to the research
planes): the data plane must never import the trading/research planes or
POC code, and the M3 research packages (backtest/validation) must never
import oms/risk/brokers/data — they consume admitted facts ONLY through
``trading_lab.contracts`` plus ``trading_lab.security`` canonicalization.

Machine-executable, stdlib-only AST check over
``src/trading_lab/{data,risk,oms,backtest,validation}/`` and (M3.5 S6)
the Shadow application layer ``apps/trading_daemon/`` (no broker
machinery, no trading planes, no network modules, no POC/artifacts).

Coverage and honest boundaries:

- absolute imports (``import trading_lab.oms``, ``from trading_lab.oms import X``)
- parent-package member imports (``from trading_lab import oms``)
- relative imports resolved against the file's package
  (``from .. import oms``, ``from ..oms import X``)
- dynamic imports with a CONSTANT module argument
  (``__import__('trading_lab.oms')``, ``importlib.import_module(...)``)
- any module path containing ``artifacts`` or ``poc`` fragments
- package-boundary matching: ``trading_lab.oms`` forbids the module and its
  subpaths, but NOT prefix-similar names like ``trading_lab.oms_tools``

Known real boundary (recorded, not hidden): this is a STATIC check of
literal import statements and constant dynamic imports. It cannot catch
computed dynamic imports (``importlib.import_module(variable)``),
``exec``/``eval``, or C-extension tricks — those belong to the process
isolation work in later stages, not to this script.

Exit codes: 0 = clean, 1 = violations.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TARGET_PACKAGE = "src/trading_lab/data"
TARGET_PACKAGE_NAME = "trading_lab.data"

FORBIDDEN_ROOTS = (
    "trading_lab.oms",
    "trading_lab.brokers",
    "trading_lab.risk",
    "trading_lab.strategies",
    "trading_lab.research",
    "trading_lab.evolution",
    "trading_lab.portfolio",
    "trading_lab.monitoring",
    "trading_lab.backtest",
    "trading_lab.validation",
)
FORBIDDEN_FRAGMENTS = ("artifacts", "poc")

# M3.5 daemon plane rules (task M3.5-SHADOW-FORWARD-ENGINEERING-001 S6):
# apps/trading_daemon is the offline Shadow application layer. It must
# never touch broker machinery, the trading planes, ANY network module,
# or POC/artifact code — the daemon's whole safety argument is that its
# import path contains no broker write and no network egress.
DAEMON_PACKAGE_NAME = "apps.trading_daemon"
DAEMON_PACKAGE_DIR = REPO / "apps" / "trading_daemon"
DAEMON_FORBIDDEN_ROOTS = (
    # broker machinery and the trading planes (no write path, no fence
    # borrowing, no risk engine re-entry from the app layer)
    "trading_lab.brokers",
    "trading_lab.oms",
    "trading_lab.risk",
    # network egress (stdlib + third-party names)
    "socket",
    "ssl",
    "urllib",
    "http",
    "ftplib",
    "smtplib",
    "telnetlib",
    "xmlrpc",
    "requests",
    "websockets",
    "aiohttp",
    "alpaca",
)

# M2 plane rules (task §8): each package additionally forbids importing its
# sibling planes directly — decisions/broker access flow one way only.
#   data       -> no risk/oms/brokers + no research packages (M1 rule,
#                 extended in M3-R1: research must never feed the data plane)
#   risk       -> no oms/brokers/data + no research (risk decides BEFORE
#                 the OMS; broker access is oms's job)
#   oms        -> no risk/data + no research (OMS consumes RiskDecision as
#                 data; brokers is the sanctioned direction)
#   backtest   -> no oms/risk/brokers/data (M3-R1: research plane consumes
#                 ONLY contracts + security.canonical — one OMS/broker
#                 authority, admitted data via contracts, never live)
#   validation -> same as backtest
_RESEARCH_FUTURE = (
    "trading_lab.strategies",
    "trading_lab.research",
    "trading_lab.evolution",
    "trading_lab.portfolio",
    "trading_lab.monitoring",
    "trading_lab.backtest",
    "trading_lab.validation",
)
PLANE_RULES: dict[str, tuple[str, ...]] = {
    "trading_lab.data": (
        "trading_lab.risk",
        "trading_lab.oms",
        "trading_lab.brokers",
    ) + _RESEARCH_FUTURE,
    "trading_lab.risk": (
        "trading_lab.oms",
        "trading_lab.brokers",
        "trading_lab.data",
    ) + _RESEARCH_FUTURE,
    "trading_lab.oms": (
        "trading_lab.risk",
        "trading_lab.data",
    ) + _RESEARCH_FUTURE,
    # brokers is the ONE sanctioned trading-plane dependency of oms
    "trading_lab.backtest": (
        "trading_lab.oms",
        "trading_lab.risk",
        "trading_lab.brokers",
        "trading_lab.data",
        "trading_lab.strategies",
        "trading_lab.research",
        "trading_lab.evolution",
        "trading_lab.portfolio",
        "trading_lab.monitoring",
    ),
    "trading_lab.validation": (
        "trading_lab.oms",
        "trading_lab.risk",
        "trading_lab.brokers",
        "trading_lab.data",
        "trading_lab.strategies",
        "trading_lab.research",
        "trading_lab.evolution",
        "trading_lab.portfolio",
        "trading_lab.monitoring",
    ),
}


def module_forbidden(module: str | None, extra_roots: tuple[str, ...] = ()) -> bool:
    """Package-boundary match: a forbidden root matches the exact module and
    its subpaths only — never prefix-similar names (``oms_tools`` is not
    ``oms``). When the caller provides a plane rule set (extra_roots), that
    set REPLACES the generic roots — the plane rules are each package's
    complete cross-package policy, not an additive overlay."""
    if not module:
        return False
    roots = extra_roots if extra_roots else FORBIDDEN_ROOTS
    if module in roots:
        return True
    if any(module.startswith(root + ".") for root in roots):
        return True
    lowered = module.lower()
    return any(f in lowered for f in FORBIDDEN_FRAGMENTS)


def _resolve_relative(level: int, module: str | None, package: str) -> tuple[str, bool]:
    """Resolve a relative import against ``package`` (PEP 328 semantics).

    Returns (absolute_module, escapes_package). A level that climbs above
    the top-level package is unresolvable — treated fail-closed by the
    caller (a data-plane file has no business importing outside its
    package tree)."""
    parts = package.split(".")
    if level > len(parts):
        return (module or ""), True
    base_parts = parts[: len(parts) - (level - 1)] if level > 1 else parts
    base = ".".join(base_parts)
    if module:
        return (f"{base}.{module}" if base else module), False
    return base, False


def _candidate_modules(node: ast.ImportFrom, package: str) -> list[str] | None:
    """Full candidate names for an ImportFrom: the resolved module itself
    plus ``module.alias`` for every imported member — ``from trading_lab
    import oms`` must resolve the member name too (R4). Returns None when
    the import escapes the package (unresolvable -> fail-closed)."""
    module = node.module or ""
    if node.level:
        module, escapes = _resolve_relative(node.level, module, package)
        if escapes:
            return None
    candidates = [module] if module else []
    for alias in node.names:
        full = f"{module}.{alias.name}" if module else alias.name
        candidates.append(full)
    return candidates


def _intra_package(candidate: str, package: str) -> bool:
    """A package importing its own submodules is always legal — plane rules
    only govern CROSS-package dependencies."""
    return candidate == package or candidate.startswith(package + ".")


def check_file(path: Path, package: str = TARGET_PACKAGE_NAME,
               extra_roots: tuple[str, ...] | None = None) -> list[str]:
    violations: list[str] = []
    roots = extra_roots if extra_roots is not None \
        else PLANE_RULES.get(package, ())
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _intra_package(alias.name, package):
                    continue
                if module_forbidden(alias.name, roots):
                    violations.append(f"{path}:line {node.lineno}: import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            candidates = _candidate_modules(node, package)
            if candidates is None:
                violations.append(
                    f"{path}:line {node.lineno}: relative import escapes the package "
                    f"(fail-closed): from {'.' * node.level}{node.module or ''} import "
                    f"{', '.join(a.name for a in node.names)}"
                )
                continue
            for candidate in candidates:
                if _intra_package(candidate, package):
                    continue
                if module_forbidden(candidate, roots):
                    violations.append(
                        f"{path}:line {node.lineno}: from {node.module or '.' * node.level} "
                        f"import {', '.join(a.name for a in node.names)} ({candidate})"
                    )
                    break
        elif isinstance(node, ast.Call):
            func = node.func
            is_dynamic = (
                (isinstance(func, ast.Name) and func.id in {"__import__", "import_module"})
                or (isinstance(func, ast.Attribute) and func.attr == "import_module")
            )
            if is_dynamic and node.args and isinstance(node.args[0], ast.Constant):
                target = str(node.args[0].value)
                if not _intra_package(target, package) and module_forbidden(target, roots):
                    violations.append(
                        f"{path}:line {node.lineno}: dynamic import of {node.args[0].value!r}"
                    )
    return violations


def check_daemon_file(path: Path) -> list[str]:
    """The daemon plane rule set (see DAEMON_FORBIDDEN_ROOTS). Package
    boundary semantics match the src planes; intra-package imports are
    always legal; dynamic imports with constant targets are checked."""
    return check_file(path, package=DAEMON_PACKAGE_NAME,
                      extra_roots=DAEMON_FORBIDDEN_ROOTS)


def main() -> int:
    violations: list[str] = []
    scanned = 0
    packages = [TARGET_PACKAGE_NAME] + [p for p in PLANE_RULES if p != TARGET_PACKAGE_NAME]
    for package in packages:
        pkg_dir = REPO / "src" / package.replace(".", "/")
        if not pkg_dir.exists():
            continue
        files = list(pkg_dir.rglob("*.py"))
        scanned += len(files)
        for py in sorted(files):
            violations.extend(check_file(py, package=package))
    if DAEMON_PACKAGE_DIR.exists():
        daemon_files = list(DAEMON_PACKAGE_DIR.rglob("*.py"))
        scanned += len(daemon_files)
        for py in sorted(daemon_files):
            violations.extend(check_daemon_file(py))
    for v in violations:
        print(f"ARCH_VIOLATION:{v}")
    print(f"check_architecture: scanned {len(packages)} packages ({scanned} files), {len(violations)} violations")
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
