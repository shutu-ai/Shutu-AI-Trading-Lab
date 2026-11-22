"""Minimal SHADOW forward daemon (M3.5, SYNTHETIC_REPLAY only).

Application layer ABOVE ``src/trading_lab``: it composes the existing
library mechanisms (security.canonical, security.audit.AuditLog,
validation.cohorts semantics, data.calendar, contracts) into a forward
event state machine that locks predictions BEFORE consuming observations,
is exactly-once across restarts, and has no broker/network path at all.

Scope discipline (task M3.5-SHADOW-FORWARD-ENGINEERING-001):
- ``--mode synthetic-replay`` is the only permitted mode; real data
  endpoints and broker credentials are refused by construction.
- This package is NOT part of the M3 ``research-code-identity-v1`` scope;
  it carries its own ``forward-daemon-identity-v1`` with an explicit
  parent link to the M3-R2 identity (``af7ff10c…``).
"""

from __future__ import annotations

__version__ = "0.1.0.m35"

FORWARD_IDENTITY_SCHEMA = "forward-daemon-identity-v1"
