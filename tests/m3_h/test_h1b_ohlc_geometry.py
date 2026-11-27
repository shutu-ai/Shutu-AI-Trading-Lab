"""H1B P0-Q2 — OHLC crossed-bar geometry, hard-fail at both boundaries.

Mirrors the FROZEN S8 quality semantics (apps/market_gateway/quality.py,
``CROSSED_BAR``): ``high >= low`` AND ``low <= min(open, close)`` AND
``max(open, close) <= high``. H1A only checked ``low <= high`` — a bar
whose close (or open) escapes its own [low, high] passed both the
gateway validator and the data model, and the committed H1A QQQ fixture
(close ~300 against open=600/high=602) exercised exactly that hole.

The degenerate legal bar ``low == open == close == high`` must pass.
No silent price adjustment anywhere. SYNTHETIC_OFFLINE_ONLY.
"""

from __future__ import annotations

import datetime as dt
import sys
import urllib.error
from decimal import Decimal
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (REPO_ROOT / "src", REPO_ROOT / "tests", REPO_ROOT):
    _sp = str(_p)
    if _sp not in sys.path:
        sys.path.insert(0, _sp)

from helpers_m3_h import H1A_RECEIVED_AT  # noqa: E402

UTC = dt.timezone.utc
WINDOW = (dt.date(2026, 11, 20), dt.date(2026, 12, 31))


def _bar(session: str, o: str, h: str, low: str, c: str) -> dict:
    return {
        "t": f"{session}T05:00:00Z",
        "o": float(o),
        "h": float(h),
        "l": float(low),
        "c": float(c),
        "v": 1000,
    }


def _page(bars: list[dict], symbol: str) -> bytes:
    import json

    return json.dumps({"bars": bars, "symbol": symbol}).encode("utf-8")


class ScriptedTransport:
    def __init__(self, bodies: list[bytes]) -> None:
        self._bodies = list(bodies)
        self.requests: list[str] = []

    def __call__(self, request, timeout=None):
        self.requests.append(request.full_url)
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


def _client(transport):
    from apps.market_gateway.historical_bars import (
        HISTORY_HOST,
        HISTORY_PATH_PATTERN,
        HistoricalBarsClient,
        HistoricalWindow,
    )
    from apps.market_gateway.http_client import GuardedGetClient

    guard = GuardedGetClient(
        allowed_hosts=[HISTORY_HOST],
        allowed_paths=[HISTORY_PATH_PATTERN],
        opener=transport,
    )
    return HistoricalBarsClient(
        client=guard,
        window=HistoricalWindow(start=WINDOW[0], end=WINDOW[1], label="h1b-fixture-window"),
        max_requests=30,
    )


def _fetch(client, symbol: str = "SPY"):
    return client.fetch_daily_bars(
        symbol=symbol,
        start=dt.date(2026, 11, 20),
        end=dt.date(2026, 11, 20),
        received_at_utc=H1A_RECEIVED_AT,
    )


CROSSED_CASES = [
    ("high_below_low", _bar("2026-11-20", "600", "598", "599", "600")),  # h < l
    ("open_below_low", _bar("2026-11-20", "598", "602", "599", "600")),  # o < l
    ("open_above_high", _bar("2026-11-20", "603", "602", "599", "600")),  # o > h
    ("close_below_low", _bar("2026-11-20", "600", "602", "599", "598")),  # c < l
    ("close_above_high", _bar("2026-11-20", "600", "602", "599", "603")),  # c > h — the committed H1A QQQ defect shape
]


class TestGatewayCrossedBar:
    @pytest.mark.parametrize("case_name,bar", CROSSED_CASES, ids=[c[0] for c in CROSSED_CASES])
    def test_crossed_bar_refused_at_gateway(self, case_name, bar):
        from apps.market_gateway.historical_bars import HistoricalRequestRefused

        transport = ScriptedTransport([_page([bar], "SPY")])
        client = _client(transport)
        with pytest.raises(HistoricalRequestRefused) as exc:
            _fetch(client)
        assert "CROSSED_BAR" in str(exc.value)

    def test_degenerate_flat_bar_is_legal(self):
        flat = _bar("2026-11-20", "600", "600", "600", "600")
        transport = ScriptedTransport([_page([flat], "SPY")])
        client = _client(transport)
        result = _fetch(client)
        assert len(result.rows) == 1
        assert result.rows[0]["o"] == result.rows[0]["c"] == Decimal("600")


class TestRecordCrossedBar:
    def _record(self, o, h, low, c):
        from trading_lab.data.historical import HistoricalBarRecord

        return HistoricalBarRecord.assumed_next_open_row(
            {
                "t": "2026-11-20T05:00:00Z",
                "o": Decimal(o),
                "h": Decimal(h),
                "l": Decimal(low),
                "c": Decimal(c),
                "v": 1000,
            },
            symbol="SPY",
            session_date=dt.date(2026, 11, 20),
            session_close_utc=dt.datetime(2026, 11, 20, 21, 0, tzinfo=UTC),
            assumed_available_at_utc=dt.datetime(2026, 11, 23, 14, 30, tzinfo=UTC),
            received_at_utc=H1A_RECEIVED_AT,
        )

    @pytest.mark.parametrize(
        "o,h,low,c",
        [("598", "602", "599", "600"), ("603", "602", "599", "600"),
         ("600", "602", "599", "598"), ("600", "602", "599", "603"),
         ("600", "598", "599", "600")],
    )
    def test_crossed_bar_rejected_at_data_model(self, o, h, low, c):
        from trading_lab.data.historical import HistoricalDataError

        with pytest.raises(HistoricalDataError) as exc:
            self._record(o, h, low, c)
        assert "CROSSED_BAR" in str(exc.value)

    def test_degenerate_flat_bar_record_legal(self):
        rec = self._record("600", "600", "600", "600")
        assert rec.low == rec.high == Decimal("600")
