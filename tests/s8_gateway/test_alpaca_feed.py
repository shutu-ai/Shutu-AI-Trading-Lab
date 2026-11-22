"""AlpacaIexDailyBarFeed — normalization, quality rejects, calendar and
poll-window discipline, receipt records, transport-error evidence."""

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
    FeedConfigError,
    credential_env_visible,
)
from apps.market_gateway.http_client import TransportError  # noqa: E402
from apps.market_gateway.offline_fixtures import (  # noqa: E402
    ScriptedBarsClient,
    fixture_clock,
    load_fixture_table,
)

REPO = Path(__file__).resolve().parents[2]
FIXTURE_PATH = REPO / "apps" / "market_gateway" / "fixtures" / "selftest_bars.json"


class _Resp:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None


def make_feed(real_prereg, cycles, *, fail_hosts=None, cycle_index=0):
    transport = real_prereg.transport_config
    client = ScriptedBarsClient(
        allowed_hosts=list(transport.get("allowed_hosts") or ()),
        allowed_paths=list(transport.get("allowed_paths") or ()),
        cycles=cycles, fail_hosts=fail_hosts)
    client.cycle_index = cycle_index
    clock = fixture_clock(cycles)
    clock.sync_with(client)
    feed = _feed_cls()(
        client=client.client, prereg=real_prereg, now_fn=clock,
        code_identity=CollectorCodeIdentity(
            schema="forward-daemon-identity-v1", code_hash="ab" * 32),
        credential_reader=lambda name: "OFFLINE-SELFTEST")
    return feed, client, clock


def _feed_cls():
    from apps.market_gateway.alpaca_feed import AlpacaIexDailyBarFeed
    return AlpacaIexDailyBarFeed


@pytest.fixture()
def fixture_table():
    return load_fixture_table(FIXTURE_PATH)["cycles"]


# ---------------------------------------------------------------------------
# normalization — deterministic, DST-correct, conservative PIT
# ---------------------------------------------------------------------------

def test_first_cycle_normalizes_two_symbols(real_prereg, fixture_table):
    feed, client, clock = make_feed(real_prereg, fixture_table)
    result = feed.collect_once()
    assert result.status == "OK"
    assert result.session_date == dt.date(2026, 11, 23)
    assert [e["symbol"] for e in result.events] == ["QQQ", "SPY"]  # sorted
    spy = result.events[1]
    assert spy["event_id"] == "alpaca_iex:SPY:1d:2026-11-23"
    assert spy["source"] == "alpaca_iex"
    assert spy["environment"] == "REAL_SHADOW_READ_ONLY"
    assert spy["close"] == Decimal("680.10")
    # EST (UTC-5): 16:00 ET close == 21:00 UTC
    assert spy["ts_event"] == dt.datetime(2026, 11, 23, 21, 0,
                                          tzinfo=dt.timezone.utc)
    # conservative PIT: availability claimed only at real receipt
    assert spy["ts_available"] == spy["received_at"] == clock()
    assert spy["ts_available"] >= spy["ts_event"]


def test_half_day_normalizes_to_13_et_close(real_prereg, fixture_table):
    feed, client, clock = make_feed(real_prereg, fixture_table, cycle_index=3)
    result = feed.collect_once()
    assert result.session_date == dt.date(2026, 11, 27)
    spy = result.events[1]
    # half day: 13:00 EST == 18:00 UTC
    assert spy["ts_event"] == dt.datetime(2026, 11, 27, 18, 0,
                                          tzinfo=dt.timezone.utc)


def test_event_id_and_dataset_hash_deterministic(real_prereg, fixture_table):
    feed_a, _, _ = make_feed(real_prereg, fixture_table)
    feed_b, _, _ = make_feed(real_prereg, fixture_table)
    a = feed_a.collect_once().events
    b = feed_b.collect_once().events
    assert [e["event_id"] for e in a] == [e["event_id"] for e in b]
    assert [e["dataset_hash"] for e in a] == [e["dataset_hash"] for e in b]
    assert len({e["dataset_hash"] for e in a}) == len(a)


def test_dataset_hash_reflects_payload_change(real_prereg, fixture_table):
    varied = copy.deepcopy(fixture_table)
    varied[0]["responses"]["SPY"]["bars"][0]["c"] = 680.20   # valid bar
    a = make_feed(real_prereg, fixture_table)[0].collect_once().events
    b = make_feed(real_prereg, varied)[0].collect_once().events
    spy_a = next(e for e in a if e["symbol"] == "SPY")
    spy_b = next(e for e in b if e["symbol"] == "SPY")
    assert spy_a["dataset_hash"] != spy_b["dataset_hash"]
    assert spy_a["event_id"] == spy_b["event_id"]  # same id + new payload
    # ...is exactly the revision-conflict shape the engine refuses


def test_receipts_carry_required_fields(real_prereg, fixture_table):
    feed, _, _ = make_feed(real_prereg, fixture_table)
    result = feed.collect_once()
    for receipt in result.receipts:
        for field in ("provider", "feed", "symbol", "event_id",
                      "received_at", "protocol_hash", "payload_digest",
                      "collector_code_hash", "environment"):
            assert field in receipt, f"receipt missing {field}"
        assert receipt["feed"] == "iex"
        # no credential material ever
        assert "OFFLINE-SELFTEST" not in str(receipt)
        assert "APCA" not in str(receipt)
        # receipt lag = received_at - session close
        lag = receipt["receipt_lag_seconds"]
        assert 0 < lag <= 6 * 60


# ---------------------------------------------------------------------------
# calendar / poll-window discipline
# ---------------------------------------------------------------------------

def test_market_closed_on_declared_holiday(real_prereg, fixture_table):
    thanksgiving = [dict(session_date="2026-11-26",
                         responses=fixture_table[0]["responses"])]
    feed, _, _ = make_feed(real_prereg, thanksgiving)
    result = feed.collect_once()
    assert result.status == "MARKET_CLOSED"
    assert result.events == []


def test_outside_calendar_coverage_refuses_to_run(real_prereg, fixture_table):
    """The preregistered calendar authority is bounded: collection outside
    it refuses (a new preregistration version is required) — never invent
    holidays."""
    before = [dict(session_date="2026-11-16",
                   responses=fixture_table[0]["responses"])]
    feed, _, _ = make_feed(real_prereg, before)
    with pytest.raises(FeedConfigError):
        feed.collect_once()


def test_outside_poll_window_is_honest_noop(real_prereg, fixture_table):
    from apps.market_gateway.alpaca_feed import AlpacaIexDailyBarFeed
    from apps.market_gateway.offline_fixtures import ScriptedBarsClient
    transport = real_prereg.transport_config
    client = ScriptedBarsClient(
        allowed_hosts=list(transport.get("allowed_hosts") or ()),
        allowed_paths=list(transport.get("allowed_paths") or ()),
        cycles=fixture_table)
    mid_morning = MarketCalendar.to_utc(
        dt.datetime.combine(dt.date(2026, 11, 23), dt.time(11, 0),
                            tzinfo=ET))
    feed = AlpacaIexDailyBarFeed(
        client=client.client, prereg=real_prereg, now_fn=lambda: mid_morning,
        credential_reader=lambda name: "OFFLINE-SELFTEST")
    result = feed.collect_once()
    assert result.status == "OUTSIDE_POLL_WINDOW"
    assert result.events == []
    assert client.requests == [], "network touched outside the poll window"


def test_client_hosts_must_not_exceed_prereg_allowlist(real_prereg):
    from apps.market_gateway.alpaca_feed import AlpacaIexDailyBarFeed
    from apps.market_gateway.http_client import GuardedGetClient
    rogue = GuardedGetClient(
        allowed_hosts=["data.alpaca.markets", "example.com"],
        allowed_paths=["^/v2/stocks/[A-Z]{1,5}/bars/latest$"],
        opener=lambda req, timeout=None: None)
    with pytest.raises(FeedConfigError):
        AlpacaIexDailyBarFeed(
            client=rogue, prereg=real_prereg,
            now_fn=lambda: MarketCalendar.to_utc(dt.datetime.combine(
                dt.date(2026, 11, 23), dt.time(16, 6), tzinfo=ET)),
            credential_reader=lambda name: "X")


# ---------------------------------------------------------------------------
# quality rejects — fail-closed per payload
# ---------------------------------------------------------------------------

def _mutated_bar(cycles, symbol, **fields):
    varied = copy.deepcopy(cycles)
    bar = varied[0]["responses"][symbol]["bars"][0]
    bar.update(fields)
    return varied


@pytest.mark.parametrize("mutation,reason", [
    ({"c": 0}, "NON_FINITE_PRICE"),
    ({"c": -680.1}, "NON_FINITE_PRICE"),
    ({"l": 681.0, "h": 680.0}, "CROSSED_BAR"),
    ({"c": 999.0, "h": 681.0, "l": 678.9, "o": 679.4}, "CROSSED_BAR"),
    ({"v": -1}, "NEGATIVE_VOLUME"),
    ({"o": "679.40"}, "SCHEMA"),
    ({"t": "2026-11-23"}, "SCHEMA"),
])
def test_bad_payload_becomes_quality_reject_not_event(
        real_prereg, fixture_table, mutation, reason):
    varied = _mutated_bar(fixture_table, "SPY", **mutation)
    feed, _, _ = make_feed(real_prereg, varied)
    result = feed.collect_once()
    reasons = [r["reject_reason"] for r in result.quality_rejects]
    assert reason in reasons
    spy_events = [e for e in result.events if e["symbol"] == "SPY"]
    assert spy_events == [], "a rejected payload produced an event"
    qqq_events = [e for e in result.events if e["symbol"] == "QQQ"]
    assert len(qqq_events) == 1, "unrelated symbol must still collect"


def test_stale_previous_session_bar_rejected(real_prereg, fixture_table):
    """A previous session's bar arriving in a new session is a gap —
    disclosed, never silently consumed as today's bar."""
    stale = copy.deepcopy(fixture_table)
    stale[1]["responses"]["SPY"]["bars"][0]["t"] = "2026-11-23T05:00:00Z"
    feed, _, _ = make_feed(real_prereg, stale, cycle_index=1)
    result = feed.collect_once()
    assert [r["reject_reason"] for r in result.quality_rejects] == \
        ["STALE_BAR"]


def test_future_session_bar_rejected(real_prereg, fixture_table):
    """A bar stamped for a LATER session can never be consumed as today's
    (retroactive-future guard)."""
    future = copy.deepcopy(fixture_table)
    future[0]["responses"]["SPY"]["bars"][0]["t"] = "2026-11-24T05:00:00Z"
    feed, _, _ = make_feed(real_prereg, future)
    result = feed.collect_once()
    assert [r["reject_reason"] for r in result.quality_rejects] == \
        ["UNEXPECTED_BAR_DATE"]


def test_symbol_echo_mismatch_rejected(real_prereg, fixture_table):
    wrong = copy.deepcopy(fixture_table)
    wrong[0]["responses"]["SPY"] = {"symbol": "QQQ",
                                    "bars": wrong[0]["responses"]["SPY"]["bars"]}
    feed, _, _ = make_feed(real_prereg, wrong)
    result = feed.collect_once()
    assert "SYMBOL_MISMATCH" in [r["reject_reason"]
                                 for r in result.quality_rejects]


# ---------------------------------------------------------------------------
# transport errors — evidence, not silence
# ---------------------------------------------------------------------------

def test_transport_disconnect_records_feed_error_and_continues(
        real_prereg, fixture_table):
    feed, _, _ = make_feed(real_prereg, fixture_table, fail_hosts={
        list(real_prereg.transport_config["allowed_hosts"])[0]})
    result = feed.collect_once()
    assert result.status == "OK"          # the cycle ran; both symbols errored
    assert len(result.transport_errors) == 2
    assert result.events == []
    for error in result.transport_errors:
        assert error["event_type"] == "FEED_ERROR"
        assert error["error_reason"] == "TRANSPORT"


def test_credential_env_visibility_is_names_only():
    env = {"APCA_API_KEY_ID": "id-value", "APCA_API_SECRET_KEY": "sekret"}
    visible = credential_env_visible(env)
    assert visible == ["APCA_API_KEY_ID", "APCA_API_SECRET_KEY"]
    assert "sekret" not in str(visible)
    assert credential_env_visible({}) == []
