"""Architecture boundary check (M1 task §5): the data plane must never
import the trading/research planes or POC code.

Machine-executable, stdlib-only AST check. Rules over ``src/trading_lab/data/``:

- forbidden import roots: trading_lab.oms / trading_lab.brokers /
  trading_lab.risk / trading_lab.strategies / trading_lab.research /
  trading_lab.evolution / trading_lab.portfolio / trading_lab.monitoring
- any import whose module path contains ``artifacts`` or ``poc``
- dynamic imports (__import__/importlib.import_module) with a constant
  argument naming a forbidden root

Exit codes: 0 = clean, 1 = violations.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TARGET_PACKAGE = "src/trading_lab/data"

FORBIDDEN_ROOTS = (
    "trading_lab.oms",
    "trading_lab.brokers",
    "trading_lab.risk",
    "trading_lab.strategies",
    "trading_lab.research",
    "trading_lab.evolution",
    "trading_lab.portfolio",
    "trading_lab.monitoring",
)
FORBIDDEN_FRAGMENTS = ("artifacts", "poc")


def module_forbidden(module: str | None) -> bool:
    if not module:
        return False
    if module.startswith(FORBIDDEN_ROOTS):
        return True
    lowered = module.lower()
    return any(f in lowered for f in FORBIDDEN_FRAGMENTS)


def check_file(path: Path) -> list[str]:
    violations: list[str] = []
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if module_forbidden(alias.name):
                    violations.append(f"{path}:line {node.lineno}: import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:  # relative import — resolve within trading_lab
                module = f"trading_lab.{module}" if module else ""
            if module_forbidden(module):
                violations.append(f"{path}:line {node.lineno}: from {module} import ...")
        elif isinstance(node, ast.Call):
            func = node.func
            is_dynamic = (
                (isinstance(func, ast.Name) and func.id in {"__import__", "import_module"})
                or (
                    isinstance(func, ast.Attribute)
                    and func.attr == "import_module"
                )
            )
            if is_dynamic and node.args and isinstance(node.args[0], ast.Constant):
                if module_forbidden(str(node.args[0].value)):
                    violations.append(
                        f"{path}:line {node.lineno}: dynamic import of {node.args[0].value!r}"
                    )
    return violations


def main() -> int:
    pkg_dir = REPO / TARGET_PACKAGE
    violations: list[str] = []
    for py in sorted(pkg_dir.rglob("*.py")):
        violations.extend(check_file(py))
    for v in violations:
        print(f"ARCH_VIOLATION:{v}")
    print(
        f"check_architecture: scanned {TARGET_PACKAGE} "
        f"({len(list(pkg_dir.rglob('*.py')))} files), {len(violations)} violations"
    )
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
