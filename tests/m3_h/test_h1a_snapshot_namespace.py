"""H1A T4 (data side) — deterministic historical snapshot in the
``historical_research`` namespace, offline end-to-end.

Two symbols x multi-page scripted history -> unified data model rows ->
quality denominators -> purpose verdict -> snapshot manifest -> files
under an explicit namespace root. Proves:

- determinism (same inputs -> same manifest hash) and tamper
  sensitivity (one changed close -> different hash);
- ASSUMED pit evidence: verdict RESTRICT_SCOPE carrying
  ``PIT_ASSUMED_NOT_VERIFIED`` (license unconfirmed => BLOCKED_DATA,
  honestly); API_VERIFIED stays NONE;
- namespace isolation: writes ONLY under the given root; forward S8
  state and M3 synthetic ledgers are byte-untouched;
- the observed latency statistic and the calendar-deadline gate stay
  two different mechanisms.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (REPO_ROOT / "src", REPO_ROOT / "tests", REPO_ROOT):
    _sp = str(_p)
    if _sp not in sys.path:
        sys.path.insert(0, _sp)

from helpers_m3_h import H1A_RECEIVED_AT, nyse_2026_fixture_supply  # noqa: E402

UTC = dt.timezone.utc
CUTOFF = dt.datetime(2026, 12, 31, 23, 59, tzinfo=UTC)
GRACE_SECONDS = 3600


def _bar(session: str, close: str) -> dict:
    # Decimals directly — the exact shape the guarded client hands over
    # (JSON numbers parse_float=Decimal); floats never survive the guard.
    from decimal import Decimal

    return {
        "t": f"{session}T05:00:00Z",
        "o": Decimal("600"),
        "h": Decimal("602"),
        "l": Decimal("599"),
        "c": Decimal(close),
        "v": 1000,
    }


def _fetch_result(symbol: str, closes: list[str], start, end):
    from apps.market_gateway.historical_bars import HistoricalFetchResult

    sessions = ["2026-11-20", "2026-11-23", "2026-11-24", "2026-11-25"][: len(closes)]
    rows = []
    for s, c in zip(sessions, closes):
        row = _bar(s, c)
        row["session_date"] = s
        rows.append(row)
    return HistoricalFetchResult(
        symbol=symbol,
        start=start,
        end=end,
        rows=tuple(rows),
        pages=1,
        request_count=1,
        request_urls=(f"https://data.alpaca.markets/v2/stocks/{symbol}/bars",),
        page_tokens_seen=(),
        complete=True,
    )


def _requirements():
    from trading_lab.data.acceptance import PurposeRequirements
    from trading_lab.data.historical import derive_max_latency_seconds
    from trading_lab.data.historical_calendar import VersionedMarketCalendar

    calendar = VersionedMarketCalendar.from_supply(nyse_2026_fixture_supply())
    derived, _ = derive_max_latency_seconds(calendar, GRACE_SECONDS)
    return PurposeRequirements(
        purpose_id="historical_research_limited_etf",
        description="H1A offline template purpose (test-only until calendar freeze)",
        data_scope="us_equities_daily_limited_etf_history",
        requires_daily_bars=True,
        requires_minute_bars=False,
        requires_corporate_actions=False,
        requires_history_membership=False,
        requires_delisting=False,
        available_at_rule="daily_close_available_next_open",
        max_missing_rate=0.001,
        min_coverage_rate=0.999,
        max_latency_seconds=derived,
        required_license_scope="personal_research",
        on_fail="RESTRICT_SCOPE",
    )


def _vendor(*, license_confirmed: bool):
    from trading_lab.data.acceptance import VendorFacts

    return VendorFacts(
        license_scope="personal_research",
        license_confirmed=license_confirmed,
        history_membership_coverage="yes",
        delisting_coverage="yes",
        corporate_actions_coverage="yes",
        pit_availability="eod_only",
    )


def _build(closes_spy=None, closes_qqq=None):
    from trading_lab.data.historical import build_historical_snapshot
    from trading_lab.data.historical_calendar import VersionedMarketCalendar

    calendar = VersionedMarketCalendar.from_supply(nyse_2026_fixture_supply())
    results = [
        _fetch_result(
            "SPY",
            closes_spy or ["600.10", "601.20", "602.30", "603.40"],
            dt.date(2026, 11, 20),
            dt.date(2026, 11, 25),
        ),
        _fetch_result(
            "QQQ",
            closes_qqq or ["300.10", "301.20", "302.30", "303.40"],
            dt.date(2026, 11, 20),
            dt.date(2026, 11, 25),
        ),
    ]
    return build_historical_snapshot(
        fetch_results=results,
        calendar=calendar,
        received_at_utc=H1A_RECEIVED_AT,
        knowledge_cutoff_utc=CUTOFF,
        requirements=_requirements(),
        vendor=_vendor(license_confirmed=False),  # honest default: UNVERIFIED
        grace_seconds=GRACE_SECONDS,
    )


class TestEndToEndOffline:
    def test_two_symbols_deterministic_snapshot_license_blocked(self):
        build = _build()
        from trading_lab.data.snapshot import research_admissible

        assert build.manifest.verify()
        assert research_admissible(build.manifest).ok
        assert len(build.manifest.entries) == 2
        # honest verdict: license unconfirmed blocks, pit stays ASSUMED
        assert build.decision.verdict == "BLOCKED_DATA"
        assert build.decision.pit_level == "ASSUMED"
        assert any(r.startswith("LICENSE_UNCONFIRMED") for r in build.decision.reasons)
        assert len(build.records) == 8
        # observed latency stays the OTHER mechanism (a statistic)
        assert build.quality.latency.sample_count == 8
        # worst observed assumed span: Fri 11-20 close -> Mon 11-23 open
        assert build.quality.latency.max_seconds == pytest.approx(65.5 * 3600)

    def test_license_confirmed_assumed_capped_restrict_scope(self):
        from trading_lab.data.historical import evaluate_historical_research

        build = _build()
        decision = evaluate_historical_research(
            _requirements(), build.quality, _vendor(license_confirmed=True), build.manifest
        )
        assert decision.verdict == "RESTRICT_SCOPE"
        assert decision.base_verdict == "ACCEPT"
        assert decision.pit_level == "ASSUMED"
        assert "PIT_ASSUMED_NOT_VERIFIED" in decision.reasons

    def test_determinism_same_inputs_same_hash(self):
        a = _build()
        b = _build()
        assert a.manifest.dataset_hash == b.manifest.dataset_hash

    def test_one_close_change_changes_hash(self):
        a = _build()
        b = _build(closes_spy=["600.11", "601.20", "602.30", "603.40"])
        assert a.manifest.dataset_hash != b.manifest.dataset_hash

    def test_session_outside_calendar_coverage_refused_at_build(self):
        from trading_lab.data.historical import HistoricalDataError, build_historical_snapshot
        from trading_lab.data.historical_calendar import VersionedMarketCalendar

        calendar = VersionedMarketCalendar.from_supply(nyse_2026_fixture_supply())
        result = _fetch_result(
            "SPY", ["600.10"], dt.date(2026, 11, 25), dt.date(2026, 11, 25)
        )
        rows = [dict(row, session_date="2027-01-04") for row in result.rows]
        doctored = type(result)(
            symbol=result.symbol,
            start=result.start,
            end=result.end,
            rows=tuple(rows),
            pages=result.pages,
            request_count=result.request_count,
            request_urls=result.request_urls,
            page_tokens_seen=result.page_tokens_seen,
            complete=result.complete,
        )
        with pytest.raises(HistoricalDataError):
            build_historical_snapshot(
                fetch_results=[doctored],
                calendar=calendar,
                received_at_utc=H1A_RECEIVED_AT,
                knowledge_cutoff_utc=CUTOFF,
                requirements=_requirements(),
                vendor=_vendor(license_confirmed=True),
                grace_seconds=GRACE_SECONDS,
            )

    def test_deadline_boundary_zero_grace_passes_at_exact_next_open(self):
        """With grace 0 the assumed stamp sits exactly ON the deadline —
        the one-sided gate passes it (deadline is an upper bound)."""
        from trading_lab.data.historical import calendar_deadline_violations
        from trading_lab.data.historical import HistoricalBarRecord
        from trading_lab.data.historical_calendar import VersionedMarketCalendar

        calendar = VersionedMarketCalendar.from_supply(nyse_2026_fixture_supply())
        rec = HistoricalBarRecord.assumed_next_open_row(
            _bar("2026-11-25", "600.10"),
            symbol="SPY",
            session_date=dt.date(2026, 11, 25),
            session_close_utc=dt.datetime(2026, 11, 25, 21, 0, tzinfo=UTC),
            assumed_available_at_utc=dt.datetime(2026, 11, 27, 14, 30, tzinfo=UTC),
            received_at_utc=H1A_RECEIVED_AT,
        )
        assert calendar_deadline_violations([rec], calendar, 0) == ()


class TestSymbolSegmentValidation:
    """Review finding 1 (IMPORTANT): the partition directory comes from
    the fetch result's symbol segment — an unvalidated symbol could
    escape the namespace root. Both the build and the writer must
    refuse unsafe segments."""

    def test_unsafe_symbol_refused_at_build(self):
        from trading_lab.data.historical import HistoricalDataError, build_historical_snapshot
        from trading_lab.data.historical_calendar import VersionedMarketCalendar

        calendar = VersionedMarketCalendar.from_supply(nyse_2026_fixture_supply())
        result = _fetch_result("SPY", ["600.10"], dt.date(2026, 11, 25), dt.date(2026, 11, 25))
        evil = type(result)(**{**result.__dict__, "symbol": "..\\..\\escape"})
        with pytest.raises(HistoricalDataError) as exc:
            build_historical_snapshot(
                fetch_results=[evil],
                calendar=calendar,
                received_at_utc=H1A_RECEIVED_AT,
                knowledge_cutoff_utc=CUTOFF,
                requirements=_requirements(),
                vendor=_vendor(license_confirmed=True),
                grace_seconds=GRACE_SECONDS,
            )
        assert "SYMBOL_SEGMENT_UNSAFE" in str(exc.value)

    def test_writer_refuses_unsafe_entry_name_segment(self, tmp_path):
        import dataclasses

        from trading_lab.data.historical import HistoricalDataError, write_historical_namespace

        build = _build()
        tampered_entry = dataclasses.replace(
            build.entries[0], name="historical_research/../../escape/1Day/raw"
        )
        tampered_build = dataclasses.replace(build, entries=(tampered_entry,))
        with pytest.raises(HistoricalDataError):
            write_historical_namespace(tmp_path / "ns", tampered_build)


class TestNamespaceIsolation:
    def test_writes_only_under_namespace_root_and_forward_state_untouched(self, tmp_path):
        build = _build()
        from trading_lab.data.historical import write_historical_namespace

        # decoy forward/S8 + synthetic-M3 state next to the namespace root
        s8_journal = tmp_path / "state" / "s8-real-pilot" / "journal.jsonl"
        s8_journal.parent.mkdir(parents=True)
        s8_journal.write_bytes(b"S8-FORWARD-STATE-DECOY\n")
        m3_ledger = tmp_path / "artifacts" / "evidence" / "M3" / "ledger.jsonl"
        m3_ledger.parent.mkdir(parents=True)
        m3_ledger.write_bytes(b"M3-SYNTHETIC-LEDGER-DECOY\n")

        root = tmp_path / "artifacts" / "datasets" / "historical_research"
        written = write_historical_namespace(root, build)

        assert written and all(str(p).startswith(str(root)) for p in written.values())
        for _name, path in written.items():
            assert path.exists()
        for p in root.rglob("*"):
            assert "s8" not in p.name.lower()
        assert s8_journal.read_bytes() == b"S8-FORWARD-STATE-DECOY\n"
        assert m3_ledger.read_bytes() == b"M3-SYNTHETIC-LEDGER-DECOY\n"
        manifest_doc = json.loads((root / "snapshot-manifest.json").read_text(encoding="utf-8"))
        assert manifest_doc["pit_level"] == "ASSUMED"
        assert manifest_doc["research_admissible"] is True
        admission = json.loads((root / "admission.json").read_text(encoding="utf-8"))
        assert admission["verdict"] == "BLOCKED_DATA"  # license unconfirmed
        assert admission["api_verified_claim"] == "NONE"

    def test_namespace_bytes_deterministic(self, tmp_path):
        build = _build()
        from trading_lab.data.historical import write_historical_namespace

        root_a = tmp_path / "a" / "historical_research"
        root_b = tmp_path / "b" / "historical_research"
        write_historical_namespace(root_a, build)
        write_historical_namespace(root_b, build)
        for rel in ("snapshot-manifest.json", "admission.json"):
            assert (root_a / rel).read_bytes() == (root_b / rel).read_bytes()
