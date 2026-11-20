"""Root tests package marker: loading this conftest puts ``tests/`` on
sys.path so test modules can import the unique-named helper modules
(``helpers_security`` / ``helpers_no_lookahead`` / ``helpers_m2``) without
cross-directory ``conftest`` name collisions. Fixtures live in the
per-suite helper modules and directory conftests."""

from helpers_m2 import stack  # noqa: F401  (pytest fixture re-export)

