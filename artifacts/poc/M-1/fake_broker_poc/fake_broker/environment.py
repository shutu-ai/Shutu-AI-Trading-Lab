"""Environment namespace isolation helpers (mock level, M-1).

Production (M0/M2) will enforce: a Paper runtime process must not hold Live
credentials, endpoints, DB paths, or writable queues, and no boolean switch
may promote Paper to Live. Here we test the contract shape:
- broker/OMS instances are bound to exactly one (environment, account)
- cross-namespace writes raise
- a runtime config for PAPER is structurally scanned for LIVE artifacts
"""
from __future__ import annotations

from typing import Any


def scan_config_for_foreign_environment(config: dict[str, Any], env: str) -> list[str]:
    """Return keys in config that reference a foreign environment.
    For env=PAPER: any key/value mentioning live endpoints, LIVE env, or
    live-seeming secret fields is reported."""
    live_markers = ("live", "://api.alpaca.markets")  # '://api.' disambiguates the
    # live trading host from 'paper-api.alpaca.markets' (no substring false positive)
    hits: list[str] = []

    def walk(prefix: str, node: Any) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                walk(f"{prefix}.{k}" if prefix else str(k), v)
        elif isinstance(node, str):
            low = node.lower()
            key_low = prefix.lower()
            if any(m in low for m in live_markers) or any(m in key_low for m in live_markers):
                hits.append(prefix)

    walk("", config)
    return hits
