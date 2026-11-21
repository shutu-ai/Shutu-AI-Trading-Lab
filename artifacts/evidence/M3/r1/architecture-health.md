=== M3-R1 T6/T7 architecture health — 2026-11-21T18:46:30Z ===

## Checker run (5 packages, real tree)
check_architecture: scanned 5 packages (26 files), 0 violations
EXIT=0

## Package scan coverage
- trading_lab.data / risk / oms (M1/M2 rules intact, extended to block research-plane imports)
- trading_lab.backtest / validation (NEW M3-R1 rules: only contracts + security allowed cross-package)

## Runtime capability probe
.                                                                        [100%]

## Remaining honest limitations
1. Static check cannot see computed dynamic imports / exec-eval (pinned by negative test; M4 process isolation).
2. Runtime socket probe covers the exercised code path only (not a sandbox).
3. Holdout vault is application-level simulation — OS-level sealing belongs to M4.
4. No new third-party dependencies introduced in M3-R1 (stdlib + existing pydantic/PyYAML/pytest).
