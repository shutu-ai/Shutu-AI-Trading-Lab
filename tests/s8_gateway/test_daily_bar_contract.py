"""Ranged daily-bars contract (production, contract remediation R1).

Proves the P0-1 fix: only the official ranged bars contract
(timeframe=1Day + bounded window + documented response shape) can
produce candidate daily events; minute-bar semantics are structurally
refused at three layers. Every payload below is a HAND-BUILT
documented-shape fixture — nothing touches the network, and nothing here
is a real API response.
"""

from __future__ import annotations

import copy
import datetime as dt
import sys
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from trading_lab.data.calendar import ET, MarketCalendar  # noqa: E402

from apps.market_gateway.alpaca_feed import (  # noqa: E402
    CollectorCodeIdentity,
)
from apps.market_gateway.http_client import TransportError  # noqa: E402
from apps.market_gateway.offline_fixtures import (  # noqa: E402
    ScriptedBarsClient,
    fixture_clock,
    load_fixture_table,
)

REPO = Path(__file__).resolve().parents[2]
FIXTURE_V2 = REPO / "apps" / "market_gateway" / "fixtures" / \
    "selftest_daily_bars_v2.json"


def _feed(ranged_prereg, cycles, *, cycle_index=0, fail_hosts=None):
    transport = ranged_prereg.transport_config
    client = ScriptedBarsClient(
        allowed_hosts=list(transport.get("allowed_hosts") or ()),
        allowed_paths=list(transport.get("allowed_paths") or ()),
        cycles=cycles, fail_hosts=fail_hosts)
    client.cycle_index = cycle_index
    clock = fixture_clock(cycles)
    clock.sync_with(client)
    from apps.market_gateway.alpaca_feed import AlpacaIexDailyBarFeed
    feed = AlpacaIexDailyBarFeed(
        client=client.client, prereg=ranged_prereg, now_fn=clock,
        code_identity=CollectorCodeIdentity(
            schema="forward-daemon-identity-v1", code_hash="cd" * 32),
        credential_reader=lambda name: "OFFLINE-RANGED-TEST")
    return feed, client, clock


@pytest.fixture()
def ranged_cycles():
    return load_fixture_table(FIXTURE_V2)["cycles"]


# ---------------------------------------------------------------------------
# the official daily-bar contract admits real-shaped responses
# ---------------------------------------------------------------------------

def test_ranged_single_page_yields_daily_event(ranged_prereg, ranged_cycles):
    feed, client, clock = _feed(ranged_prereg, ranged_cycles)
    result = feed.collect_once()
    assert result.status == "OK"
    spy = result.events[1]
    assert spy["event_id"] == "alpaca_iex:SPY:1d:2026-11-23"
    assert spy["interval"] == "1d"
    assert spy["close"] == Decimal("680.10")
    # EST: 16:00 ET close == 21:00 UTC; conservative PIT availability
    assert spy["ts_event"] == dt.datetime(2026, 11, 23, 21, 0,
                                          tzinfo=dt.timezone.utc)
    assert spy["ts_available"] == spy["received_at"] == clock()
    receipt = result.receipts[1]
    assert receipt["event_type"] == "RECEIPT"
    assert receipt["receipt_schema"] == "s8-receipts-v2"
    assert "timeframe=1Day" in receipt["request_query"]
    assert "feed=iex" in receipt["request_query"]
    assert "adjustment=raw" in receipt["request_query"]
    # bounded window: start = session midnight ET (05:00Z EST), end = receipt
    assert "start=2026-11-23T05%3A00%3A00Z" in receipt["request_query"]
    assert "disconnect_eligible" not in receipt  # receipts are not errors


def test_ranged_window_bounds_are_exact(ranged_prereg, ranged_cycles):
    """The bounded window is the requested session only: start = session
    midnight ET inclusive (the vendor's pre-open daily stamp), end = the
    real receipt instant — no wide historical sweep can masquerade as a
    forward observation."""
    feed, client, _clock = _feed(ranged_prereg, ranged_cycles)
    feed.collect_once()
    url = client.requests[0]
    assert "start=2026-11-23T05%3A00%3A00Z" in url   # 00:00 EST == 05:00Z
    assert "end=2026-11-23T21%3A06%3A00Z" in url     # 16:06 ET receipt
    assert "limit=10000" in url
    assert "sort=asc" in url


def test_ranged_pagination_chains_page_token(ranged_prereg, ranged_cycles):
    """The documented page_token loop: an empty first page with a token,
    then the bar page — merged into exactly one daily event."""
    chained = copy.deepcopy(ranged_cycles)
    bar = chained[0]["pages"]["SPY"][0]["bars"][0]
    chained[0]["pages"]["SPY"] = [
        {"bars": [], "next_page_token": "QUFQTHxN", "symbol": "SPY"},
        {"bars": [bar], "next_page_token": None, "symbol": "SPY"},
    ]
    feed, _client, _clock = _feed(ranged_prereg, chained)
    result = feed.collect_once()
    spy_events = [e for e in result.events if e["symbol"] == "SPY"]
    assert len(spy_events) == 1
    assert spy_events[0]["close"] == Decimal("680.10")


def test_ranged_page_cap_is_fail_closed(ranged_prereg, ranged_cycles):
    """Every page claims another token: the preregistered cap stops the
    sweep — refusal, zero events (never an unbounded historical pull)."""
    endless = copy.deepcopy(ranged_cycles)
    endless[0]["pages"]["SPY"] = [
        {"bars": [], "next_page_token": f"tok{i}", "symbol": "SPY"}
        for i in range(10)
    ]
    feed, _client, _clock = _feed(ranged_prereg, endless)
    result = feed.collect_once()
    spy_errors = [e for e in result.transport_errors if e["symbol"] == "SPY"]
    assert len(spy_errors) == 1
    assert spy_errors[0]["event_type"] == "FEED_ERROR"
    assert spy_errors[0]["error_reason"] == "CONTRACT_SHAPE"
    assert spy_errors[0]["disconnect_eligible"] is False
    spy_events = [e for e in result.events if e["symbol"] == "SPY"]
    assert spy_events == []


# ---------------------------------------------------------------------------
# minute-bar semantics are structurally refused (P0-1 fix)
# ---------------------------------------------------------------------------

def test_intraday_minute_stamp_is_never_a_daily_bar(
        ranged_prereg, ranged_cycles):
    """Defense-in-depth: even a ranged response carrying an intraday
    (minute) stamp can never become the daily event — NOT_A_DAILY_BAR,
    receipted, zero events, zero day credit."""
    minute = copy.deepcopy(ranged_cycles)
    minute[0]["pages"]["SPY"][0]["bars"][0]["t"] = "2026-11-23T21:05:00Z"
    feed, _client, _clock = _feed(ranged_prereg, minute)
    result = feed.collect_once()
    reasons = [r["reject_reason"] for r in result.quality_rejects]
    assert reasons == ["NOT_A_DAILY_BAR"]
    assert [e for e in result.events if e["symbol"] == "SPY"] == []
    # the unrelated symbol still collects normally
    assert [e for e in result.events if e["symbol"] == "QQQ"]


def test_official_latest_shape_on_ranged_path_is_refused(
        ranged_prereg, ranged_cycles):
    """The REAL bars/latest shape ({symbol, bar}) sent where the ranged
    contract lives: the feed refuses it at the transport-contract layer
    (CONTRACT_SHAPE), receipted, zero events — a minute-bar response can
    never enter the daily pipeline."""
    latest_shape = copy.deepcopy(ranged_cycles)
    bar = latest_shape[0]["pages"]["SPY"][0]["bars"][0]
    latest_shape[0]["pages"]["SPY"] = [
        {"symbol": "SPY", "bar": bar}]
    feed, _client, _clock = _feed(ranged_prereg, latest_shape)
    result = feed.collect_once()
    spy_errors = [e for e in result.transport_errors if e["symbol"] == "SPY"]
    assert spy_errors[0]["error_reason"] == "CONTRACT_SHAPE"
    assert [e for e in result.events if e["symbol"] == "SPY"] == []


def test_missing_symbol_echo_refused(ranged_prereg, ranged_cycles):
    """The ranged schema REQUIRES the symbol echo (documented required
    field) — an echo-less page is a contract breach, refused."""
    no_echo = copy.deepcopy(ranged_cycles)
    del no_echo[0]["pages"]["SPY"][0]["symbol"]
    feed, _client, _clock = _feed(ranged_prereg, no_echo)
    result = feed.collect_once()
    spy_errors = [e for e in result.transport_errors if e["symbol"] == "SPY"]
    assert spy_errors[0]["error_reason"] == "CONTRACT_SHAPE"
    assert [e for e in result.events if e["symbol"] == "SPY"] == []


def test_empty_bars_is_a_receipted_gap_not_an_event(
        ranged_prereg, ranged_cycles):
    """Zero bars in the bounded window = the documented 'no data' answer:
    MISSING_BAR receipt, zero events, zero day credit."""
    empty = copy.deepcopy(ranged_cycles)
    empty[0]["pages"]["SPY"][0]["bars"] = []
    feed, _client, _clock = _feed(ranged_prereg, empty)
    result = feed.collect_once()
    assert [r["reject_reason"] for r in result.quality_rejects] == \
        ["MISSING_BAR"]
    spy_events = [e for e in result.events if e["symbol"] == "SPY"]
    assert spy_events == []
    qqq_events = [e for e in result.events if e["symbol"] == "QQQ"]
    assert len(qqq_events) == 1


def test_two_bars_in_one_daily_window_is_schema_rejected(
        ranged_prereg, ranged_cycles):
    doubled = copy.deepcopy(ranged_cycles)
    bars = doubled[0]["pages"]["SPY"][0]["bars"]
    doubled[0]["pages"]["SPY"][0]["bars"] = [bars[0], dict(bars[0])]
    feed, _client, _clock = _feed(ranged_prereg, doubled)
    result = feed.collect_once()
    assert [r["reject_reason"] for r in result.quality_rejects] == \
        ["SCHEMA"]
    assert [e for e in result.events if e["symbol"] == "SPY"] == []
    assert [e for e in result.events if e["symbol"] == "QQQ"]


# ---------------------------------------------------------------------------
# error classification — what counts as disconnect evidence
# ---------------------------------------------------------------------------

def test_rate_limit_is_disconnect_eligible(ranged_prereg, ranged_cycles):
    class RateLimited(ScriptedBarsClient):
        def _open(self, request, timeout=None):
            self.requests.append(request.full_url)
            raise TransportError("HTTP_STATUS",
                                 "429 for data.alpaca.markets (rate)",
                                 status=429)

    transport = ranged_prereg.transport_config
    client = RateLimited(
        allowed_hosts=list(transport.get("allowed_hosts") or ()),
        allowed_paths=list(transport.get("allowed_paths") or ()),
        cycles=ranged_cycles)
    client.cycle_index = 0
    clock = fixture_clock(ranged_cycles)
    clock.sync_with(client)
    from apps.market_gateway.alpaca_feed import AlpacaIexDailyBarFeed
    feed = AlpacaIexDailyBarFeed(
        client=client.client, prereg=ranged_prereg, now_fn=clock,
        credential_reader=lambda name: "OFFLINE-RANGED-TEST")
    result = feed.collect_once()
    assert len(result.transport_errors) == 2
    assert all(e["disconnect_eligible"] is True
               for e in result.transport_errors)


def test_forbidden_is_not_disconnect_evidence(ranged_prereg, ranged_cycles):
    """403 is an operator-side credential/subscription fault — receipted,
    but it can NEVER back a disconnect-recovery claim (task T2)."""
    class Forbidden(ScriptedBarsClient):
        def _open(self, request, timeout=None):
            self.requests.append(request.full_url)
            raise TransportError("HTTP_STATUS", "403 forbidden",
                                 status=403)

    transport = ranged_prereg.transport_config
    client = Forbidden(
        allowed_hosts=list(transport.get("allowed_hosts") or ()),
        allowed_paths=list(transport.get("allowed_paths") or ()),
        cycles=ranged_cycles)
    client.cycle_index = 0
    clock = fixture_clock(ranged_cycles)
    clock.sync_with(client)
    from apps.market_gateway.alpaca_feed import AlpacaIexDailyBarFeed
    feed = AlpacaIexDailyBarFeed(
        client=client.client, prereg=ranged_prereg, now_fn=clock,
        credential_reader=lambda name: "OFFLINE-RANGED-TEST")
    result = feed.collect_once()
    assert len(result.transport_errors) == 2
    assert all(e["disconnect_eligible"] is False
               for e in result.transport_errors)


# ---------------------------------------------------------------------------
# normalization invariants carry over (DST, half day, determinism)
# ---------------------------------------------------------------------------

def test_half_day_normalizes_to_13_et_close_ranged(
        ranged_prereg, ranged_cycles):
    feed, _client, _clock = _feed(ranged_prereg, ranged_cycles, cycle_index=3)
    result = feed.collect_once()
    spy = result.events[1]
    assert result.session_date == dt.date(2026, 11, 27)
    assert spy["ts_event"] == dt.datetime(2026, 11, 27, 18, 0,
                                          tzinfo=dt.timezone.utc)


def test_ranged_event_ids_and_digests_deterministic(
        ranged_prereg, ranged_cycles):
    a = _feed(ranged_prereg, ranged_cycles)[0].collect_once()
    b = _feed(ranged_prereg, ranged_cycles)[0].collect_once()
    assert [e["event_id"] for e in a.events] == \
        [e["event_id"] for e in b.events]
    assert [e["dataset_hash"] for e in a.events] == \
        [e["dataset_hash"] for e in b.events]
