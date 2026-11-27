"""H1A T4 (gateway side) — minimal restricted historical bars client.

Reuse-only: every byte flows through the existing ``GuardedGetClient``
(GET-only, https, host allowlist, path regex, redirect refusal,
Decimal JSON). The client adds the H1 business entry gate (SPY/QQQ
only, ``feed=iex``, ``timeframe=1Day``, ``adjustment=raw``, dates
inside the frozen license window, request budget) and the offline
pagination loop over ``next_page_token`` with loop detection and an
honest request audit.

Zero network, zero credentials: the scripted transport proves all of
this works with NO API keys present.
"""

from __future__ import annotations

import datetime as dt
import sys
import urllib.error
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (REPO_ROOT / "src", REPO_ROOT / "tests", REPO_ROOT):
    _sp = str(_p)
    if _sp not in sys.path:
        sys.path.insert(0, _sp)

from apps.market_gateway.http_client import GuardedGetClient  # noqa: E402

UTC = dt.timezone.utc
RECEIVED_AT = dt.datetime(2026, 11, 26, 12, 0, tzinfo=UTC)
WINDOW = (dt.date(2026, 11, 20), dt.date(2026, 12, 31))  # fixture licensed window


def _bar(session: str, close: str, base: int = 600) -> dict:
    # NOTE: prices are JSON NUMBERS (floats in the fixture) — the guarded
    # client parses them into exact Decimals, exactly like the vendor wire
    # format. Strings would be a schema violation, correctly refused.
    # H1B P0-Q2 fixture fix: geometry is self-consistent by construction
    # (the close is enclosed by the bar's own low/high).
    c = float(close)
    low = min(base, c) - 1
    high = max(base, c) + 1
    return {
        "t": f"{session}T05:00:00Z",
        "o": float(base),
        "h": high,
        "l": low,
        "c": c,
        "v": 1000,
    }


def _page(bars: list[dict], token: str | None, symbol: str) -> bytes:
    import json

    payload: dict = {"bars": bars, "symbol": symbol}
    if token is not None:
        payload["next_page_token"] = token
    return json.dumps(payload).encode("utf-8")


class ScriptedHistoryTransport:
    """Consumes scripted bodies in call order; records (url, headers) per
    request. Any unexpected extra request explodes the test."""

    def __init__(self, bodies: list[bytes]) -> None:
        self._bodies = list(bodies)
        self.requests: list[tuple[str, dict[str, str]]] = []

    def __call__(self, request, timeout=None):
        self.requests.append((request.full_url, dict(request.header_items())))
        if not self._bodies:
            raise AssertionError(f"unexpected extra request: {request.full_url}")
        body = self._bodies.pop(0)

        class _Resp:
            def __init__(self, data: bytes) -> None:
                self._data = data

            def read(self) -> bytes:
                return self._data

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return None

        return _Resp(body)


def _client(transport, *, max_requests: int = 30):
    from apps.market_gateway.historical_bars import (
        HISTORY_HOST,
        HISTORY_PATH_PATTERN,
        HistoricalBarsClient,
        HistoricalWindow,
    )

    guard = GuardedGetClient(
        allowed_hosts=[HISTORY_HOST],
        allowed_paths=[HISTORY_PATH_PATTERN],
        opener=transport,
    )
    return HistoricalBarsClient(
        client=guard,
        window=HistoricalWindow(start=WINDOW[0], end=WINDOW[1], label="h1a-fixture-window"),
        max_requests=max_requests,
    )


def _fetch(client, symbol: str = "SPY", start=WINDOW[0], end=dt.date(2026, 11, 25)):
    return client.fetch_daily_bars(
        symbol=symbol, start=start, end=end, received_at_utc=RECEIVED_AT
    )


# ---------------------------------------------------------------------------
# business-entry refusals — transport never touched
# ---------------------------------------------------------------------------

class TestBusinessEntryRefusals:
    def test_symbol_outside_authorization_refused(self):
        boom = ScriptedHistoryTransport([])
        client = _client(boom)
        with pytest.raises(Exception) as exc:
            _fetch(client, symbol="AAPL")
        assert "SYMBOL_NOT_AUTHORIZED" in str(exc.value)
        assert boom.requests == []

    def test_dates_outside_license_window_refused(self):
        """The frozen license window is enforced at the business entry:
        2017 dates are refused even though the calendar fixture could
        never certify them either."""
        boom = ScriptedHistoryTransport([])
        client = _client(boom)
        with pytest.raises(Exception) as exc:
            _fetch(client, start=dt.date(2017, 1, 1), end=dt.date(2017, 12, 31))
        assert "OUTSIDE_LICENSE_WINDOW" in str(exc.value)
        assert boom.requests == []

    def test_inverted_date_range_refused(self):
        boom = ScriptedHistoryTransport([])
        client = _client(boom)
        with pytest.raises(Exception) as exc:
            _fetch(client, start=dt.date(2026, 11, 25), end=dt.date(2026, 11, 20))
        assert "BAD_DATE_RANGE" in str(exc.value)
        assert boom.requests == []


# ---------------------------------------------------------------------------
# pagination, contract, audit — offline with no credentials
# ---------------------------------------------------------------------------

class TestPaginationAndContract:
    def test_two_symbols_multi_page_no_silent_loss(self):
        transport = ScriptedHistoryTransport(
            [
                _page([_bar("2026-11-20", "600.10"), _bar("2026-11-23", "601.20")], "tok-p2", "SPY"),
                _page([_bar("2026-11-24", "602.30"), _bar("2026-11-25", "603.40")], None, "SPY"),
                _page(
                    [
                        _bar("2026-11-20", "300.10"),
                        _bar("2026-11-23", "301.20"),
                        _bar("2026-11-24", "302.30"),
                        _bar("2026-11-25", "303.40"),
                    ],
                    None,
                    "QQQ",
                ),
            ]
        )
        client = _client(transport)
        spy = _fetch(client, "SPY")
        qqq = _fetch(client, "QQQ")
        assert spy.complete and qqq.complete
        assert spy.pages == 2 and qqq.pages == 1
        assert len(spy.rows) == 4 and len(qqq.rows) == 4  # no silent loss
        # request_count is the execution-window cumulative budget counter
        assert spy.request_count == 2 and qqq.request_count == 3
        assert client.request_count == 3
        # exact params, sorted, fixed contract
        assert "feed=iex" in spy.request_urls[0]
        assert "timeframe=1Day" in spy.request_urls[0]
        assert "adjustment=raw" in spy.request_urls[0]
        assert "page_token=tok-p2" in spy.request_urls[1]
        # no credentials were ever needed or sent
        for _url, headers in transport.requests:
            flat = str(headers).lower()
            assert "apca-api-key-id" not in flat and "apca-api-secret-key" not in flat

    def test_symbol_echo_required_and_exact(self):
        import json

        transport = ScriptedHistoryTransport(
            [json.dumps({"bars": [_bar("2026-11-20", "600")]}).encode("utf-8")]
        )
        client = _client(transport)
        with pytest.raises(Exception) as exc:
            _fetch(client, "SPY")
        assert "SCHEMA" in str(exc.value) or "SYMBOL_MISMATCH" in str(exc.value)

    def test_empty_page_refused(self):
        import json

        transport = ScriptedHistoryTransport(
            [json.dumps({"bars": [], "symbol": "SPY"}).encode("utf-8")]
        )
        client = _client(transport)
        with pytest.raises(Exception) as exc:
            _fetch(client, "SPY")
        assert "EMPTY_PAGE" in str(exc.value)

    def test_page_token_loop_detected(self):
        transport = ScriptedHistoryTransport(
            [
                _page([_bar("2026-11-20", "600")], "tok-loop", "SPY"),
                _page([_bar("2026-11-23", "601")], "tok-loop", "SPY"),
            ]
        )
        client = _client(transport)
        with pytest.raises(Exception) as exc:
            _fetch(client, "SPY")
        assert "PAGE_TOKEN_LOOP" in str(exc.value)
        assert client.request_count == 2  # stopped before burning budget

    def test_out_of_range_bar_refused(self):
        transport = ScriptedHistoryTransport(
            [_page([_bar("2026-12-01", "600")], None, "SPY")]
        )
        client = _client(transport)
        with pytest.raises(Exception) as exc:
            _fetch(client, "SPY")  # window end 2026-11-25
        assert "OUT_OF_RANGE_BAR" in str(exc.value)

    def test_duplicate_or_out_of_order_refused(self):
        transport = ScriptedHistoryTransport(
            [
                _page(
                    [_bar("2026-11-23", "601"), _bar("2026-11-23", "601")],
                    None,
                    "SPY",
                )
            ]
        )
        client = _client(transport)
        with pytest.raises(Exception) as exc:
            _fetch(client, "SPY")
        assert "DUPLICATE_OR_OUT_OF_ORDER" in str(exc.value)

    def test_request_budget_hard_capped(self):
        # distinct ascending sessions per page so the duplicate gate never
        # fires before the budget gate does
        sessions = ["2026-11-20", "2026-11-23", "2026-11-24", "2026-11-25", "2026-11-25"]
        pages = [_page([_bar(sessions[i], str(600 + i))], f"tok-{i + 1}", "SPY") for i in range(5)]
        transport = ScriptedHistoryTransport(pages)
        client = _client(transport, max_requests=3)
        with pytest.raises(Exception) as exc:
            _fetch(client, "SPY")
        assert "REQUEST_BUDGET_EXCEEDED" in str(exc.value)
        assert client.request_count <= 3

    def test_non_200_propagates_as_transport_error(self):
        class Forbidden(ScriptedHistoryTransport):
            def __call__(self, request, timeout=None):
                self.requests.append((request.full_url, {}))
                raise urllib.error.HTTPError(
                    request.full_url, 403, "forbidden", hdrs=None, fp=None
                )

        client = _client(Forbidden([]))
        from apps.market_gateway.http_client import TransportError

        with pytest.raises(TransportError) as exc:
            _fetch(client, "SPY")
        assert exc.value.status == 403

    def test_failed_wire_requests_count_toward_budget(self):
        """Review finding 2: a failed transport attempt consumes the
        authorized budget exactly like a success — an operator retry
        loop cannot push unlimited failed wire requests past the cap."""
        class FlakyOnce(ScriptedHistoryTransport):
            def __init__(self, bodies):
                super().__init__(bodies)
                self.wire_attempts = 0

            def __call__(self, request, timeout=None):
                self.wire_attempts += 1
                if self.wire_attempts == 1:
                    raise urllib.error.URLError("transient 5xx")
                return super().__call__(request, timeout)

        from apps.market_gateway.http_client import TransportError

        transport = FlakyOnce([_page([_bar("2026-11-20", "600.10")], None, "SPY")])
        client = _client(transport, max_requests=2)
        with pytest.raises(TransportError):
            _fetch(client, "SPY")  # first attempt fails on the wire
        assert client.request_count == 1, "failed wire attempt must consume budget"
        result = _fetch(client, "SPY")  # retry succeeds (2nd scripted page... body)
        assert result.complete and client.request_count == 2
        with pytest.raises(Exception) as exc:
            _fetch(client, "SPY")  # third fetch: budget exhausted
        assert "REQUEST_BUDGET_EXCEEDED" in str(exc.value)

    def test_guard_path_still_enforced_for_history_client(self):
        """If the configured path regex ever drifts away from the bars
        pattern, the guard refuses before the transport (defense in
        depth survives configuration)."""
        from apps.market_gateway.historical_bars import (
            HISTORY_HOST,
            HistoricalBarsClient,
            HistoricalWindow,
        )
        from apps.market_gateway.http_client import GuardedGetClient, TransportError

        boom = ScriptedHistoryTransport([])
        guard = GuardedGetClient(
            allowed_hosts=[HISTORY_HOST],
            allowed_paths=[r"^/v2/stocks/[A-Z]{1,5}/quotes$"],  # drifted config
            opener=boom,
        )
        client = HistoricalBarsClient(
            client=guard,
            window=HistoricalWindow(start=WINDOW[0], end=WINDOW[1]),
            max_requests=30,
        )
        with pytest.raises(TransportError) as exc:
            _fetch(client, "SPY")
        assert exc.value.reason == "PATH_NOT_ALLOWED"
        assert boom.requests == []
