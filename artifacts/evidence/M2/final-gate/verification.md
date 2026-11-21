# M2 final gate verification â€” 2026-11-21T16:28:49+02:00 â€” HEAD 1988cab264e6f76ee280eb245e3ce16378be9ba2
## environment
python: 3.13.15
CHECK_ENV_EXIT=0
## pytest full
...........................................................              [100%]
347 passed in 153.15s (0:02:33)
PYTEST_EXIT=0
## check_architecture
check_architecture: scanned 3 packages (18 files), 0 violations
ARCH_EXIT=0
## scan_secrets
scan_secrets: scanned 318 tracked files, 0 findings
SCAN_EXIT=0
## verify_live_blocked
verify_live_blocked: paper runtime contains no live artifacts ¡ª PASS
VLB_EXIT=0
## smoke_mock
SMOKE PASS: paper gate + kill switch + mock live verification all behaved fail-closed
SMOKE_EXIT=0
## git diff --check
DIFF_CHECK_EXIT=0
## fault matrix
...........                                                              [100%]
MATRIX_EXIT=0
## suite counts
== tests/contract tests/security ==
140 passed
== tests/no_lookahead ==
71 passed
== tests/risk ==
19 passed
== tests/oms ==
14 passed
== tests/architecture ==
26 passed
== tests/fault_injection ==
29 passed
== tests/m2_remediation ==
48 passed
