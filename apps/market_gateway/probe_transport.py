"""Deterministic FAKE Alpaca-shaped bar transport — the ``probe`` mode of
the restricted historical collection entry (BUSINESS-MVP-V02 workflow A2).

This module is an in-repo, offline, deterministic fixture that speaks the
SHAPE of the real Alpaca v2 daily-bar endpoint (URL, sorted query params,
``bars``/``symbol``/``next_page_token`` payload, page-token pagination)
so the whole guarded-client + collection pipeline can be accepted with
ZERO real network traffic. It plugs into :class:`GuardedGetClient`
through the existing ``opener`` seam — the guarded checks themselves are
NOT patched or bypassed (host/path allowlist, GET-only, Decimal JSON all
still run on every request).

Honesty labels, enforced by construction:

- the class name, the module, and every audit row produced from it carry
  ``FAKE_TRANSPORT`` (:data:`FAKE_TRANSPORT_LABEL`);
- fixture rows are SYNTHETIC deterministic prices — they are NOT market
  data and must never be presented as such downstream;
- no credential exists on this path and none is accepted;
- fault injection (``fail_first_with_status``) exists ONLY so tests can
  prove the non-200 abort path; the default probe never fails.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import urllib.error
import urllib.parse
from decimal import Decimal
from typing import Any

from trading_lab.data.historical_calendar import VersionedMarketCalendar

__all__ = [
    "FAKE_TRANSPORT_LABEL",
    "FakeAlpacaProbeTransport",
    "ProbeResponse",
]

#: the single label every probe-mode artifact must carry
FAKE_TRANSPORT_LABEL = "FAKE_TRANSPORT"

#: deterministic base price per authorized symbol (distinct levels so the
#: two symbols can never be confused in a merged audit)
_BASE_PRICES: dict[str, Decimal] = {
    "SPY": Decimal("600"),
    "QQQ": Decimal("300"),
}

_BARS_PATH_RE = re.compile(r"^/v2/stocks/(SPY|QQQ)/bars$")

_DEFAULT_PAGE_SIZE = 1000  # forces >= 2 pages for the multi-year window


def _encode_exact_json(payload: Any) -> bytes:
    """Exact-decimal JSON writer for fixture pages: ``Decimal`` emits as a
    bare JSON number (so the guarded client re-parses it into an exact
    ``Decimal``, exactly like the vendor wire format), everything else
    via :func:`json.dumps`. Deterministic, no float rounding anywhere."""

    def _enc(node: Any) -> str:
        if isinstance(node, bool) or node is None:
            return json.dumps(node)
        if isinstance(node, Decimal):
            return str(node)
        if isinstance(node, int):
            return str(node)
        if isinstance(node, str):
            return json.dumps(node)
        if isinstance(node, dict):
            body = ", ".join(
                f"{json.dumps(str(key))}: {_enc(value)}" for key, value in node.items()
            )
            return "{" + body + "}"
        if isinstance(node, (list, tuple)):
            return "[" + ", ".join(_enc(item) for item in node) + "]"
        raise TypeError(f"fixture encoder refuses {type(node).__name__}")

    return _enc(payload).encode("utf-8")


class ProbeResponse:
    """Minimal urllib-response shape the guarded client consumes
    (context manager + ``read``); body is exact UTF-8 JSON bytes."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "ProbeResponse":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None


class FakeAlpacaProbeTransport:
    """Callable urllib-opener shaped like the Alpaca bars endpoint.

    Deterministic: for a given requested window, page size and symbol,
    the served bytes are always identical (fixture prices derive from the
    session DATE alone, never from call order, so page splits cannot
    change data). Request URLs are recorded in call order for the audit.
    """

    def __init__(
        self,
        *,
        calendar: VersionedMarketCalendar,
        page_size: int = _DEFAULT_PAGE_SIZE,
        fail_first_with_status: int | None = None,
    ) -> None:
        if page_size < 1:
            raise ValueError(f"page_size must be >= 1, got {page_size}")
        if fail_first_with_status is not None and not (100 <= fail_first_with_status <= 599):
            raise ValueError(
                f"fail_first_with_status must be an HTTP code, got {fail_first_with_status}"
            )
        self._calendar = calendar
        self._page_size = int(page_size)
        self._fail_first_with_status = fail_first_with_status
        self.requests: list[str] = []  # full URLs, call order
        self.calls = 0

    def __call__(self, request: Any, timeout: float | None = None) -> ProbeResponse:
        del timeout  # fixture: no real timeout applies
        self.calls += 1
        url = str(request.full_url)
        self.requests.append(url)
        if self._fail_first_with_status is not None and self.calls == 1:
            # inject the non-200 abort path for tests — raised BEFORE any
            # body is produced, exactly like a real HTTP error surfaced
            # by urllib (the guarded client turns it into HTTP_STATUS).
            raise urllib.error.HTTPError(
                url, self._fail_first_with_status,
                "FAKE_TRANSPORT injected non-200 (test fault)", hdrs=None, fp=None,
            )
        parts = urllib.parse.urlsplit(url)
        symbol = self._symbol_of(parts.path)
        params = dict(urllib.parse.parse_qsl(parts.query, keep_blank_values=True))
        start = dt.date.fromisoformat(self._required(params, "start"))
        end = dt.date.fromisoformat(self._required(params, "end"))
        sessions = self._calendar.expected_sessions(start, end)
        client_limit = int(self._required(params, "limit"))
        # the fixture caps the page SERVER-side (a vendor may return fewer
        # bars than the requested limit) — this is what exercises the
        # client's page-token pagination on every multi-year window.
        size = min(client_limit, self._page_size)
        offset = int(params["page_token"]) if "page_token" in params else 0
        page = sessions[offset:offset + size]
        bars = [self._fixture_bar(symbol, session) for session in page]
        payload: dict[str, Any] = {"bars": bars, "symbol": symbol}
        next_offset = offset + len(page)
        if next_offset < len(sessions):
            payload["next_page_token"] = str(next_offset)
        return ProbeResponse(_encode_exact_json(payload))

    # -- fixture internals -----------------------------------------------------

    @staticmethod
    def _symbol_of(path: str) -> str:
        match = _BARS_PATH_RE.match(path)
        if match is None:
            raise ValueError(
                f"FAKE_TRANSPORT only shapes the authorized bars path, got {path!r}"
            )
        return match.group(1)

    @staticmethod
    def _required(params: dict[str, str], key: str) -> str:
        value = params.get(key)
        if value is None:
            raise ValueError(f"FAKE_TRANSPORT: request missing query param {key!r}")
        return value

    @staticmethod
    def _fixture_bar(symbol: str, session: dt.date) -> dict[str, Any]:
        """One synthetic bar: deterministic pure function of (symbol,
        session date), OHLC-contained by construction, exact decimals."""
        base = _BASE_PRICES[symbol]
        ordinal = session.toordinal()
        close = base + (Decimal(ordinal % 200) * Decimal("0.25"))
        open_ = close - Decimal("1.25")
        high = max(open_, close) + Decimal("0.75")
        low = min(open_, close) - Decimal("0.75")
        volume = 900_000 + (ordinal % 11) * 1_234
        return {
            "t": f"{session.isoformat()}T05:00:00Z",
            "o": open_,
            "h": high,
            "l": low,
            "c": close,
            "v": volume,
        }
