"""Offline selftest harness for the S8 collector plane.

The scripted transport is the OFFLINE SELFTEST path only: it routes
requests through the SAME guarded client (host allowlist, path whitelist,
GET-only) and answers them from a committed fixture table of
bars-latest-response-shaped payloads. The REAL collector never touches
this module — it builds the client over urllib with operator-injected
credentials.

Honesty boundary: selftest events are FIXTURE events. They flow through
the real pipeline (feed -> quality -> engine -> journal -> receipt chain)
so the plumbing is provable offline, and they are flagged
``events_synthetic=True`` in the window facts — they can never mint
``PENDING_FORWARD_WINDOW`` or ``PASS`` (the eligibility machine refuses).
They are not real trading days and are never presented as one.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

from trading_lab.data.calendar import ET, MarketCalendar

from .alpaca_feed import AlpacaIexDailyBarFeed, CollectorCodeIdentity
from .http_client import GuardedGetClient, TransportError

__all__ = [
    "ScriptedBarsClient",
    "ScriptedExhausted",
    "fixture_clock",
    "load_fixture_table",
]

FIXTURE_SCHEMA = "s8-selftest-bars-latest-v1"


class ScriptedExhausted(RuntimeError):
    """The scripted transport was asked for a cycle/response it does not
    carry — a harness configuration defect, never silently answered."""


class _ScriptedResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_ScriptedResponse":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None


class ScriptedBarsClient:
    """Canned transport behind the REAL GuardedGetClient: every request
    still passes the guard; canned data is only the network answer."""

    def __init__(
        self,
        *,
        allowed_hosts: list[str] | tuple[str, ...],
        allowed_paths: list[str] | tuple[str, ...],
        cycles: list[dict[str, Any]],
        fail_hosts: set[str] | None = None,
    ) -> None:
        self._cycle_tables = cycles
        self.cycle_index = 0
        self.requests: list[str] = []          # audited request log (URLs)
        self._fail_hosts = {h.lower() for h in (fail_hosts or set())}
        self._client = GuardedGetClient(
            allowed_hosts=allowed_hosts,
            allowed_paths=allowed_paths,
            opener=self._open)

    @property
    def client(self) -> GuardedGetClient:
        return self._client

    def advance_cycle(self) -> None:
        self.cycle_index += 1

    def set_cycle(self, index: int) -> None:
        self.cycle_index = index

    # -- canned transport ------------------------------------------------------

    def _open(self, request: Any, timeout: float | None = None):
        url = request.full_url
        self.requests.append(url)
        import urllib.parse
        parsed = urllib.parse.urlparse(url)
        host = (parsed.hostname or "").lower()
        if host in self._fail_hosts:
            raise TransportError("TRANSPORT", "scripted disconnect (test)")
        if parsed.scheme != "https":
            raise ScriptedExhausted(f"non-https scripted request: {url}")
        parts = [p for p in parsed.path.split("/") if p]
        # /v2/stocks/{SYMBOL}/bars/latest
        if len(parts) != 5 or parts[3] != "bars" or parts[4] != "latest":
            raise ScriptedExhausted(
                f"scripted transport only carries bars/latest: {url}")
        symbol = parts[2]
        if self.cycle_index >= len(self._cycle_tables):
            raise ScriptedExhausted(
                f"cycle {self.cycle_index} beyond the fixture table "
                f"({len(self._cycle_tables)} cycles)")
        responses = self._cycle_tables[self.cycle_index].get(
            "responses", {})
        if symbol not in responses:
            raise ScriptedExhausted(
                f"no scripted response for {symbol} in cycle "
                f"{self.cycle_index}")
        return _ScriptedResponse(
            json.dumps(responses[symbol]).encode("utf-8"))


def load_fixture_table(path: Path | str) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schema") != FIXTURE_SCHEMA:
        raise ScriptedExhausted(
            f"fixture schema mismatch: {payload.get('schema')!r} != "
            f"{FIXTURE_SCHEMA!r}")
    return payload


def fixture_clock(cycle_tables: list[dict[str, Any]],
                  ) -> "CycleClock":
    """Deterministic collection clock: cycle i receives at
    {session_date} 16:06 ET (inside the preregistered poll window),
    DST-correct via the market calendar."""
    return CycleClock(cycle_tables)


class CycleClock:
    def __init__(self, cycle_tables: list[dict[str, Any]]) -> None:
        self._tables = cycle_tables
        self.cycle_index = 0

    def sync_with(self, client: ScriptedBarsClient) -> None:
        self.cycle_index = client.cycle_index

    def __call__(self) -> dt.datetime:
        table = self._tables[self.cycle_index]
        day = dt.date.fromisoformat(table["session_date"])
        return MarketCalendar.to_utc(
            dt.datetime.combine(day, dt.time(16, 6), tzinfo=ET))


def build_selftest_feed(
    *,
    prereg,                                   # PreregistrationReal
    fixture: dict[str, Any],
    identity,                                 # ForwardIdentity
) -> tuple[AlpacaIexDailyBarFeed, ScriptedBarsClient, CycleClock]:
    """Assemble the offline selftest feed over the guarded client."""
    transport = prereg.transport_config
    client = ScriptedBarsClient(
        allowed_hosts=list(transport.get("allowed_hosts") or ()),
        allowed_paths=list(transport.get("allowed_paths") or ()),
        cycles=fixture["cycles"])
    clock = fixture_clock(fixture["cycles"])
    clock.sync_with(client)
    feed = AlpacaIexDailyBarFeed(
        client=client.client,
        prereg=prereg,
        now_fn=clock,
        code_identity=CollectorCodeIdentity(
            schema=identity.schema, code_hash=identity.code_hash),
        credential_reader=lambda name: "SELFTEST-OFFLINE-NO-SECRETS")
    return feed, client, clock
