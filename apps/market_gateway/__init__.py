"""S8 read-only real-market-data Shadow plane (approval
``S8_DATA_READ_ONLY=APPROVED_WITH_SCOPE``, user-signed 2026-11-22, record:
``artifacts/evidence/M3.5/s8/authorization-check.md``).

Scope of this package — the ONLY network-enabled application plane:

- a guarded GET-only HTTP client (market-data host allowlist, path
  whitelist, no redirects, no body, Decimal-preserving JSON);
- the Alpaca Basic/IEX daily-bar feed adapter (read-only normalization
  of real arrivals into daemon envelope events);
- data-quality validation of the raw vendor payloads;
- the separately-authorized real preregistration loader (v2 — a NEW
  version; the synthetic preregistration
  ``configs/forward_observation.yaml`` stays byte-frozen);
- the real-window session runner (receipt chain + forward journal
  cross-verification).

Hard limits that outlive this stage unless separately re-authorized:

- read-only: no order/position/account endpoints, no trading-API hosts,
  no write verbs — enforced statically (``scripts/check_architecture.py``
  gateway rules) AND at runtime (client guard, negative-tested);
- ``PAPER_WRITE=NOT_AUTHORIZED``: there is no broker adapter here at all;
- at most 3 admitted US equity/ETF symbols (preregistration-enforced);
- ``BLOCKED_DATA`` (full-market historical research) and ``M1 U-1``
  semantics are untouched; ``S=INCONCLUSIVE`` throughout.
"""

from .prereg_real import PreregistrationReal, PreregistrationRealRefused

__all__ = ["PreregistrationReal", "PreregistrationRealRefused"]
