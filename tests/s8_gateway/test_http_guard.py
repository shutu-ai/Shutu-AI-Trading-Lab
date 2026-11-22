"""GuardedGetClient — the read-only network guard (S8 read-only proof).

Negative tests prove the guard rejects BEFORE any network I/O: the fake
transport explodes if touched for any request that should have been
refused. Positive tests prove exact-Decimal parsing, status/transport
error mapping and redirect refusal."""

from __future__ import annotations

import sys
import urllib.error
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from apps.market_gateway.http_client import (  # noqa: E402
    TRADING_API_HOSTS,
    GuardedGetClient,
    TransportError,
    market_data_headers,
)

ALLOWED_HOSTS = ["data.alpaca.markets"]
ALLOWED_PATHS = ["^/v2/stocks/[A-Z]{1,5}/bars/latest$"]


class ExplodingTransport:
    """If this is reached for a GUARD-refused request, the guard failed."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, request, timeout=None):
        self.calls.append(request.full_url)
        raise AssertionError(
            f"transport touched for a request that must be refused: "
            f"{request.full_url}")


class CannedTransport:
    def __init__(self, body: bytes, status_url: str | None = None) -> None:
        self.body = body
        self.calls: list[str] = []

    def __call__(self, request, timeout=None):
        self.calls.append(request.full_url)
        return _CannedResponse(self.body)


class _CannedResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None


def _guard(transport) -> GuardedGetClient:
    return GuardedGetClient(
        allowed_hosts=ALLOWED_HOSTS, allowed_paths=ALLOWED_PATHS,
        opener=transport)


# ---------------------------------------------------------------------------
# guard rejections — transport must NEVER be touched
# ---------------------------------------------------------------------------

def test_rejects_host_outside_allowlist():
    boom = ExplodingTransport()
    client = _guard(boom)
    with pytest.raises(TransportError) as exc:
        client.get_json(host="example.com", path="/v2/stocks/SPY/bars/latest")
    assert exc.value.reason == "HOST_NOT_ALLOWED"
    assert boom.calls == [], "network touched for refused host"


@pytest.mark.parametrize("host", sorted(TRADING_API_HOSTS))
def test_construction_refuses_trading_allowlist(host):
    with pytest.raises(TransportError) as exc:
        GuardedGetClient(
            allowed_hosts=[host],  # broken config — refused at build
            allowed_paths=ALLOWED_PATHS, opener=ExplodingTransport())
    assert exc.value.reason == "TRADING_HOST_FORBIDDEN"


@pytest.mark.parametrize("host", sorted(TRADING_API_HOSTS))
def test_request_time_guard_refuses_trading_hosts(host):
    """Even against a client whose allowlist somehow contains a trading
    host (built via the object bypass), every request re-checks and
    refuses — and the transport is never touched."""
    client = GuardedGetClient.__new__(GuardedGetClient)
    GuardedGetClient.__init__(
        client, allowed_hosts=["data.alpaca.markets"],
        allowed_paths=ALLOWED_PATHS, opener=ExplodingTransport())
    client._hosts = frozenset({host})   # simulate broken configuration
    boom = ExplodingTransport()
    client._open = boom
    with pytest.raises(TransportError) as exc:
        client.get_json(host=host, path="/v2/orders")
    assert exc.value.reason == "TRADING_HOST_FORBIDDEN"
    assert boom.calls == []


def test_client_construction_refuses_trading_allowlist():
    with pytest.raises(TransportError):
        GuardedGetClient(
            allowed_hosts=["paper-api.alpaca.markets"],
            allowed_paths=ALLOWED_PATHS, opener=ExplodingTransport())


@pytest.mark.parametrize("path", [
    "/v2/orders",
    "/v2/positions/SPY",
    "/v2/account",
    "/v2/stocks/SPY/quotes/latest",      # pattern allows bars/latest only
    "/v2/stocks/spy/bars/latest",        # lowercase symbol: not preregistered
    "v2/stocks/SPY/bars/latest",         # missing leading slash
    "/v2/stocks/SPY/bars/latest/extra",
])
def test_rejects_paths_outside_whitelist(path):
    boom = ExplodingTransport()
    client = _guard(boom)
    with pytest.raises(TransportError) as exc:
        client.get_json(host="data.alpaca.markets", path=path)
    assert exc.value.reason == "PATH_NOT_ALLOWED"
    assert boom.calls == []


def test_rejects_non_apca_headers():
    boom = ExplodingTransport()
    client = _guard(boom)
    with pytest.raises(TransportError) as exc:
        client.get_json(
            host="data.alpaca.markets",
            path="/v2/stocks/SPY/bars/latest",
            headers={"X-Custom": "1"})
    assert exc.value.reason == "HEADER_NOT_ALLOWED"
    assert boom.calls == []


def test_method_guard_is_frozen():
    assert GuardedGetClient.METHOD == "GET"


def test_get_only_surface_no_body_support():
    """The client exposes no API that could carry a body: only get_json
    exists as a request method."""
    public = [n for n in vars(GuardedGetClient)
              if not n.startswith("_") and n != "METHOD"]
    assert "get_json" in public
    assert not any(m in public for m in ("post", "put", "delete", "patch",
                                         "request", "send"))


# ---------------------------------------------------------------------------
# allowed requests — exact decimals, error mapping, redirects
# ---------------------------------------------------------------------------

def test_allowed_request_parses_exact_decimals():
    body = (b'{"bars": [{"t": "2026-11-23T05:00:00Z", "o": 679.40, '
            b'"h": 680.55, "l": 678.90, "c": 680.10, "v": 41230000}]}')
    canned = CannedTransport(body)
    client = _guard(canned)
    payload = client.get_json(
        host="data.alpaca.markets", path="/v2/stocks/SPY/bars/latest",
        params={"feed": "iex"})
    assert payload["bars"][0]["c"] == Decimal("680.10")
    assert str(payload["bars"][0]["c"]) == "680.10"   # exact text preserved
    assert isinstance(payload["bars"][0]["v"], int)
    assert len(canned.calls) == 1
    assert canned.calls[0] == ("https://data.alpaca.markets"
                               "/v2/stocks/SPY/bars/latest?feed=iex")


def test_http_error_maps_to_transport_error_with_status():
    class StatusTransport(CannedTransport):
        def __call__(self, request, timeout=None):
            raise urllib.error.HTTPError(
                request.full_url, 403, "forbidden", hdrs=None, fp=None)

    client = _guard(StatusTransport(None))
    with pytest.raises(TransportError) as exc:
        client.get_json(host="data.alpaca.markets",
                        path="/v2/stocks/SPY/bars/latest")
    assert exc.value.reason == "HTTP_STATUS"
    assert exc.value.status == 403


def test_redirect_status_is_refused_not_followed():
    class RedirectTransport(CannedTransport):
        def __call__(self, request, timeout=None):
            self.calls.append(request.full_url)
            raise urllib.error.HTTPError(
                "https://other.example.com/v2/stocks/SPY/bars/latest",
                302, "found", hdrs=None, fp=None)

    t = RedirectTransport(None)
    client = _guard(t)
    with pytest.raises(TransportError) as exc:
        client.get_json(host="data.alpaca.markets",
                        path="/v2/stocks/SPY/bars/latest")
    assert exc.value.status == 302
    assert "never followed" in exc.value.detail
    assert len(t.calls) == 1, "a second request was made (redirect followed)"


def test_transport_failure_maps_to_transport_error():
    class DownTransport(CannedTransport):
        def __call__(self, request, timeout=None):
            raise urllib.error.URLError("connection refused")

    client = _guard(DownTransport(None))
    with pytest.raises(TransportError) as exc:
        client.get_json(host="data.alpaca.markets",
                        path="/v2/stocks/SPY/bars/latest")
    assert exc.value.reason == "TRANSPORT"


def test_unparseable_body_refused():
    client = _guard(CannedTransport(b"<html>not json</html>"))
    with pytest.raises(TransportError) as exc:
        client.get_json(host="data.alpaca.markets",
                        path="/v2/stocks/SPY/bars/latest")
    assert exc.value.reason == "UNPARSEABLE"


def test_non_finite_json_literal_is_refused():
    """json routes NaN/Infinity through parse_constant, not parse_float —
    the client must refuse the body outright (no floats ever exist at
    this layer)."""
    client = _guard(CannedTransport(
        b'{"bars": [{"t": "2026-11-23T05:00:00Z", "o": NaN, "h": 1, '
        b'"l": 1, "c": 1, "v": 1}]}'))
    with pytest.raises(TransportError) as exc:
        client.get_json(host="data.alpaca.markets",
                        path="/v2/stocks/SPY/bars/latest")
    assert exc.value.reason == "UNPARSEABLE"


def test_credential_headers_never_appear_in_errors():
    headers = market_data_headers("SECRET-ID", "SECRET-KEY")
    assert headers["APCA-API-KEY-ID"] == "SECRET-ID"
    boom = ExplodingTransport()
    client = _guard(boom)
    with pytest.raises(TransportError) as exc:
        client.get_json(host="evil.example.com",
                        path="/v2/stocks/SPY/bars/latest",
                        headers=headers)
    assert "SECRET-ID" not in exc.value.detail
    assert "SECRET-KEY" not in str(exc.value)
