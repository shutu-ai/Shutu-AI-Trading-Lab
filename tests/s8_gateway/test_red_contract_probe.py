"""T0.2 RED contract probe — pins the CURRENT defective behavior of the
S8 v1 (legacy) contract so the defect is proven, not asserted.

These tests demonstrate the P0 findings against the code AS IT IS (before
remediation). They run against the preserved legacy preregistration
(configs/forward_observation_s8_real.yaml) and are converted into the
permanent pinned-legacy regression after GREEN (the legacy branch survives
as historical-defect evidence; the production path moves to the ranged
daily-bars contract). Every payload here is a HAND-BUILT documented-shape
fixture — nothing here touches the network or claims real API responses.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from apps.market_gateway.alpaca_feed import (  # noqa: E402
    CollectorCodeIdentity,
)
from apps.market_gateway.offline_fixtures import (  # noqa: E402
    ScriptedBarsClient,
    fixture_clock,
    load_fixture_table,
)
from apps.market_gateway.prereg_real import PreregistrationReal  # noqa: E402
from apps.market_gateway.quality import validate_raw_bar  # noqa: E402
from apps.market_gateway.feed_session import (  # noqa: E402
    window_facts_from_journal,
)

REPO = Path(__file__).resolve().parents[2]
LEGACY_PREREG_PATH = REPO / "configs" / "forward_observation_s8_real.yaml"
FIXTURE_PATH = REPO / "apps" / "market_gateway" / "fixtures" / "selftest_bars.json"


def _legacy_prereg() -> PreregistrationReal:
    return PreregistrationReal.load(LEGACY_PREREG_PATH)


def _make_legacy_feed(cycles, cycle_index=0):
    from apps.market_gateway.alpaca_feed import AlpacaIexDailyBarFeed
    transport = _legacy_prereg().transport_config
    client = ScriptedBarsClient(
        allowed_hosts=list(transport.get("allowed_hosts") or ()),
        allowed_paths=list(transport.get("allowed_paths") or ()),
        cycles=cycles)
    client.cycle_index = cycle_index
    clock = fixture_clock(cycles)
    clock.sync_with(client)
    feed = AlpacaIexDailyBarFeed(
        client=client.client, prereg=_legacy_prereg(), now_fn=clock,
        code_identity=CollectorCodeIdentity(
            schema="forward-daemon-identity-v1", code_hash="ab" * 32),
        credential_reader=lambda name: "OFFLINE-RED-PROBE")
    return feed, client, clock


# ---------------------------------------------------------------------------
# RED-1: the OFFICIAL bars/latest response shape is unparseable by the
# legacy quality gate — the collector could never admit a real response.
# ---------------------------------------------------------------------------

def test_red_official_latest_shape_is_rejected_by_legacy_gate():
    """Hand-built EXACT documented shape (official-api-contract.md §1,
    retrieval 2026-11-22): {"symbol": ..., "bar": {single object}}. The
    legacy gate answers SCHEMA reject — it expects a fabricated `bars`
    array no real endpoint returns."""
    official = {
        "symbol": "SPY",
        "bar": {"t": "2026-11-23T20:05:00Z", "o": 679.90, "h": 680.10,
                "l": 679.85, "c": 680.05, "v": 1280, "n": 14,
                "vw": 680.02},
    }
    import datetime as dt
    from trading_lab.data.calendar import MarketCalendar
    reject = validate_raw_bar(
        symbol="SPY", session_date=dt.date(2026, 11, 23), payload=official,
        calendar=MarketCalendar(holidays=set(), half_days=set()),
        raw_payload_digest="0" * 64)
    assert isinstance(reject, object) and not hasattr(reject, "close"), (
        "legacy gate parsed the official shape — probe assumption wrong")
    assert reject.reason == "SCHEMA"
    assert "bars" in reject.detail


def test_red_legacy_request_contract_asks_for_minute_bars():
    """The legacy feed requests /bars/latest with NO timeframe — per the
    official contract that endpoint IS the latest MINUTE bar; and the
    receipt hardcodes a query string that hides the real request."""
    cycles = load_fixture_table(FIXTURE_PATH)["cycles"]
    feed, client, _clock = _make_legacy_feed(cycles)
    feed.collect_once()
    assert client.requests, "no request captured"
    for url in client.requests:
        assert "/bars/latest" in url, url
        assert "timeframe" not in url, (
            "probe assumption wrong: legacy request carries a timeframe")


# ---------------------------------------------------------------------------
# RED-2: under the legacy contract, a MINUTE-stamped bar passes as a
# completed daily event — no daily/minute discrimination exists.
# ---------------------------------------------------------------------------

def test_red_minute_stamped_bar_becomes_daily_event_under_legacy():
    """A bar stamped INSIDE the session hours (16:05 ET — the shape of a
    real minute bar) flows through the legacy pipeline as a '1d' event
    with the session-close ts_event. This is the mislabel hazard of the
    fabricated contract."""
    cycles = load_fixture_table(FIXTURE_PATH)["cycles"]
    minute_stamped = copy.deepcopy(cycles)
    minute_stamped[0]["responses"]["SPY"]["bars"][0]["t"] = \
        "2026-11-23T21:05:00Z"          # 16:05 ET — intraday minute stamp
    feed, _client, _clock = _make_legacy_feed(minute_stamped)
    result = feed.collect_once()
    spy_events = [e for e in result.events if e["symbol"] == "SPY"]
    assert len(spy_events) == 1, (
        "probe assumption wrong: minute-stamped bar was not admitted")
    spy = spy_events[0]
    assert spy["interval"] == "1d"
    assert spy["close"] is not None
    # the event CLAIMS the completed session close while carrying a
    # minute bar's close — the exact conflation P0-1 forbids


# ---------------------------------------------------------------------------
# RED-3: window facts never provide the three PASS criterion fields.
# ---------------------------------------------------------------------------

def test_green_window_facts_now_provide_pass_criterion_fields(
        tmp_path, s8_identity):
    """GREEN (post-remediation): the same simulated window — feed-error
    episode + recovery + duplicate redelivery — now exposes
    disconnect_recoveries / duplicate_recoveries / audits_passed as
    chain-computed facts. (The RED counterpart — asserting their
    absence — is archived verbatim in red-tests.log, 4 passed against
    pre-fix code.) NOTE: this probe window is fixture-driven and flagged
    events_synthetic=True, so its PASS claim still refuses — the fields
    are necessary, and real arrivals stay the sufficient condition."""
    from apps.market_gateway.feed_session import (
        FORWARD_STATE_SUBDIR,
        run_collection_cycle,
    )
    from apps.market_gateway.offline_fixtures import build_selftest_feed
    fixture = load_fixture_table(FIXTURE_PATH)
    prereg = _legacy_prereg()
    feed, client, clock = build_selftest_feed(
        prereg=prereg, fixture=fixture, identity=s8_identity)
    state = tmp_path / "state"
    for index in range(6):
        run_collection_cycle(feed=feed, prereg=prereg, state_dir=state,
                             identity=s8_identity, session_index=index + 1)
        client.advance_cycle()
        clock.sync_with(client)
    client.set_cycle(5)
    clock.sync_with(client)
    run_collection_cycle(feed=feed, prereg=prereg, state_dir=state,
                         identity=s8_identity, session_index=7)
    facts = window_facts_from_journal(state, prereg, events_synthetic=True)
    assert facts["duplicate_recoveries"] >= 1
    assert facts["audits_passed"] is True
    assert facts["protocol_binding_ok"] is True
    assert facts["receipt_evidence_ok"] is True
    assert isinstance(facts["disconnect_recoveries"], int)
    # fixture facts stay synthetic: the E-Gate still refuses — fields are
    # necessary, never sufficient without real arrivals
    from apps.trading_daemon.eligibility import EligibilityRefused
    with pytest.raises(EligibilityRefused):
        from apps.market_gateway.feed_session import evaluate_window
        evaluate_window(prereg=prereg, harness={}, facts=facts,
                        claim="PASS")
