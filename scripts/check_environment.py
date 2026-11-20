"""Environment check for the M0 engineering baseline.

Reports the interpreter version against the approved baseline
(Python 3.13, M-1 ran 3.13.15 — user-approved deviation recorded in
docs/reviews/M-1-independent-review.md R5) and the key library versions.
Never sets or reads broker credentials; the absence of Alpaca env vars is
reported as expected state, not an error (M0 needs no broker access).

Exit codes: 0 = baseline satisfied, 1 = wrong Python version.
"""

from __future__ import annotations

import os
import sys

BASELINE_MAJOR_MINOR = (3, 13)


def main() -> int:
    version = sys.version_info
    print(f"python: {version.major}.{version.minor}.{version.micro}")
    print(f"platform: {sys.platform}")
    ok = (version.major, version.minor) == BASELINE_MAJOR_MINOR
    print(f"baseline (3.13): {'OK' if ok else 'MISMATCH'}")

    import pydantic

    print(f"pydantic: {pydantic.__version__}")
    try:
        import cryptography

        print(f"cryptography: {cryptography.__version__}")
    except ImportError:
        print("cryptography: MISSING (required for Ed25519 signing tests)")

    alpaca_vars = [k for k in os.environ if k.startswith("APCA_")]
    if alpaca_vars:
        print(f"alpaca env vars PRESENT (names only): {sorted(alpaca_vars)}")
    else:
        print("alpaca env vars: absent (expected for M0 — no broker access)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
