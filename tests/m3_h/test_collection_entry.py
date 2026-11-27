"""Restricted historical collection entry — dry-run acceptance over the
FAKE transport only (BUSINESS-MVP-V02 workflow A2).

NO NETWORK anywhere in this file: probe mode runs the real guarded
client over the in-repo deterministic fixture transport; live-mode tests
prove the refusal paths BEFORE any transport exists (authorization and
blocked-env fail closed, zero bytes, zero sockets).

Proves, per the task contract:

- probe collection of the full pinned window (SPY+QQQ together) writes
  the ``historical_research`` namespace (bars.jsonl + manifest) and
  nothing else;
- budget exceeded aborts MID-RUN with a partial-audit dump and NO
  manifest success marker (manifest existence == success);
- a non-200 stops immediately (no retry storm);
- manifest hashes are RECOMPUTED from the written files and match;
- every bars.jsonl row validates against the frozen ``MarketBar``
  contract;
- ``ts_available_utc`` follows the VersionedMarketCalendar next-open
  rule (v2 calendar: correctly skips 2025-01-09);
- duplicate/overlapping rows dedup deterministically (idempotent reruns,
  overlapping windows keep history, conflicting data refuses).
"""

from __future__ import annotations

import datetime as dt
import functools
import importlib.util
import json
import sys
from decimal import Decimal
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (REPO_ROOT / "src", REPO_ROOT / "tests", REPO_ROOT):
    _sp = str(_p)
    if _sp not in sys.path:
        sys.path.insert(0, _sp)

from apps.market_gateway import collection_session as cs  # noqa: E402
from apps.market_gateway.collection_session import (  # noqa: E402
    AUTHORIZATION_FACTS_INCOMPATIBLE,
    AUTHORIZATION_FACTS_MISSING,
    AUTHORIZATION_SCOPE_MISMATCH,
    AdmissionFacts,
    AuthorizationFactsRefused,
    AuthorizationRefused,
    AuthorizedScope,
    BlockedEnv,
    CollectionConfig,
    CollectionError,
    CollectionReport,
    LICENSE_STATUS_ATTESTED,
    LicenseFacts,
    MANIFEST_NAME,
    NAMESPACE_DIRNAME,
    PARTIAL_AUDIT_NAME,
    TRANSPORT_LIVE,
    TRANSPORT_PROBE,
    dedupe_bars_rows,
    parse_authorization_record,
    resolve_transport_authorization,
    run_collection,
)
from apps.market_gateway.historical_bars import (  # noqa: E402
    FEED,
    TIMEFRAME,
    HistoricalFetchResult,
)
from apps.market_gateway.probe_transport import (  # noqa: E402
    FAKE_TRANSPORT_LABEL,
    FakeAlpacaProbeTransport,
)
from trading_lab.contracts.events import MarketBar  # noqa: E402
from trading_lab.data.historical_calendar import VersionedMarketCalendar  # noqa: E402
from trading_lab.data.historical_calendar_supply import (  # noqa: E402
    FROZEN_SUPPLY_HASH_V2,
    NYSE_2017_2025_SUPPLY_V2,
    frozen_supply_hash,
)
from trading_lab.security.canonical import sha256_hex  # noqa: E402

UTC = dt.timezone.utc
FULL_START = dt.date(2017, 1, 1)
FULL_END = dt.date(2025, 12, 31)
JAN_WINDOW = (dt.date(2025, 1, 2), dt.date(2025, 1, 17))  # spans 2025-01-09 closure
DEC_WINDOW = (dt.date(2025, 12, 1), dt.date(2025, 12, 31))  # spans half-day + Christmas


def _calendar() -> VersionedMarketCalendar:
    return VersionedMarketCalendar.from_supply(NYSE_2017_2025_SUPPLY_V2)


def _config(
    tmp_path: Path,
    *,
    window: tuple[dt.date, dt.date] = JAN_WINDOW,
    transport: str = TRANSPORT_PROBE,
    budget: int = 30,
) -> CollectionConfig:
    return CollectionConfig(
        symbols=("SPY", "QQQ"),
        start=window[0],
        end=window[1],
        output_dir=tmp_path,
        transport=transport,
        request_budget=budget,
    )


def _manifest_path(tmp_path: Path) -> Path:
    return tmp_path / NAMESPACE_DIRNAME / MANIFEST_NAME


def _bars_path(tmp_path: Path, symbol: str) -> Path:
    return tmp_path / NAMESPACE_DIRNAME / symbol / "bars.jsonl"


def _rows(tmp_path: Path, symbol: str) -> list[dict]:
    return [
        json.loads(line)
        for line in _bars_path(tmp_path, symbol).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


# ---------------------------------------------------------------------------
# end-to-end probe collection, full pinned window
# ---------------------------------------------------------------------------


class TestProbeEndToEnd:
    def test_full_window_two_symbols_collected(self, tmp_path) -> None:
        report = run_collection(_config(tmp_path, window=(FULL_START, FULL_END)))
        assert report.ok
        assert report.manifest is not None and report.manifest_path.exists()
        assert len(report.bars_paths) == 2
        spy = _rows(tmp_path, "SPY")
        qqq = _rows(tmp_path, "QQQ")
        # v2 calendar: 2262 sessions in the window (v1's defective 2264 - 2)
        assert len(spy) == 2262 and len(qqq) == 2262

    def test_manifest_honesty_fields(self, tmp_path) -> None:
        report = run_collection(_config(tmp_path, window=(FULL_START, FULL_END)))
        manifest = report.manifest
        assert manifest is not None
        assert manifest["status"] == "COLLECTED"
        assert manifest["transport"] == {
            "mode": "probe",
            "label": "FAKE_TRANSPORT",
            "real_network_used": False,
        }
        assert manifest["calendar_supply"]["version"] == "nyse-2017-2026-01-frozen-v2"
        assert manifest["calendar_supply"]["hash"] == FROZEN_SUPPLY_HASH_V2
        assert (
            manifest["calendar_supply"]["hash"]
            == frozen_supply_hash(NYSE_2017_2025_SUPPLY_V2)
        )
        assert manifest["license"]["status"] == "LICENSE_UNVERIFIED"
        assert manifest["pit"]["level"] == "ASSUMED"
        assert manifest["pit"]["api_verified_claim"] == "NONE"
        assert manifest["admission"]["status"] == "NOT_RESEARCH_ADMITTED"

    def test_budget_accounting_and_request_audit(self, tmp_path) -> None:
        report = run_collection(_config(tmp_path, window=(FULL_START, FULL_END)))
        manifest = report.manifest
        assert manifest is not None
        assert manifest["budget"] == {"cap": 30, "spent": 6, "remaining": 24}
        for symbol in ("SPY", "QQQ"):
            doc = manifest["symbols"][symbol]
            assert doc["pages"] == 3  # fixture page size forces pagination
            assert doc["request_count_cumulative"] == 3 if symbol == "SPY" else 6
            assert doc["complete"] is True
            assert doc["page_tokens_seen"] == ["1000", "2000"]
            assert len(doc["request_urls"]) == 3
            assert all("data.alpaca.markets/v2/stocks/" in url for url in doc["request_urls"])
            assert all("feed=iex" in url and "timeframe=1Day" in url for url in doc["request_urls"])
            assert doc["expected_sessions"] == doc["row_count"] == 2262
            assert doc["missing_sessions"] == [] and doc["missing_rate"] == 0.0

    def test_namespace_isolation_decoy_untouched(self, tmp_path) -> None:
        decoy = tmp_path / "other" / "decoy.txt"
        decoy.parent.mkdir(parents=True)
        decoy.write_bytes(b"DECOY")
        run_collection(_config(tmp_path))
        written = {
            p for p in tmp_path.rglob("*") if p.is_file() and p != decoy
        }
        assert written  # something was actually written
        assert all(
            str(p).startswith(str(tmp_path / NAMESPACE_DIRNAME)) for p in written
        )
        assert decoy.read_bytes() == b"DECOY"
        assert not any("s8" in p.name.lower() for p in written)


# ---------------------------------------------------------------------------
# manifest integrity: recomputed hashes, determinism, contract validation
# ---------------------------------------------------------------------------


class TestManifestIntegrity:
    def test_hashes_recomputed_from_disk_match(self, tmp_path) -> None:
        run_collection(_config(tmp_path))
        manifest = json.loads(_manifest_path(tmp_path).read_text(encoding="utf-8"))
        for symbol in ("SPY", "QQQ"):
            doc = manifest["symbols"][symbol]
            data = _bars_path(tmp_path, symbol).read_bytes()
            assert doc["bars_sha256"] == sha256_hex(data)  # recomputed, matches
            assert doc["bars_bytes"] == len(data)
            assert doc["row_count"] == len(data.decode("utf-8").splitlines())

    def test_probe_artifacts_byte_deterministic(self, tmp_path) -> None:
        run_collection(_config(tmp_path))
        first_manifest = _manifest_path(tmp_path).read_bytes()
        first_bars = _bars_path(tmp_path, "SPY").read_bytes()
        other = tmp_path / "rerun"
        run_collection(_config(other))
        assert _manifest_path(other).read_bytes() == first_manifest
        assert _bars_path(other, "SPY").read_bytes() == first_bars

    def test_every_row_passes_marketbar_contract(self, tmp_path) -> None:
        run_collection(_config(tmp_path, window=DEC_WINDOW))
        for symbol in ("SPY", "QQQ"):
            for line in _bars_path(tmp_path, symbol).read_text(encoding="utf-8").splitlines():
                bar = MarketBar.model_validate_json(line)
                assert bar.asset_id == symbol
                assert bar.adjustment == "RAW"
                assert bar.interval == "1Day"
                assert isinstance(bar.close, Decimal) and bar.close > 0
                assert bar.volume >= 0
                assert bar.source == FAKE_TRANSPORT_LABEL  # honest label

    def test_manifest_records_probe_received_at_as_fixture_fact(self, tmp_path) -> None:
        report = run_collection(_config(tmp_path))
        assert report.manifest is not None
        assert report.manifest["received_at_utc"] == "2026-11-27T00:00:00+00:00"
        assert report.manifest["received_at_is_probe_fixture_fact"] is True


# ---------------------------------------------------------------------------
# budget abort mid-run: partial audit dump, NO manifest success marker
# ---------------------------------------------------------------------------


class TestBudgetAbortMidRun:
    def test_budget_exceeded_aborts_with_partial_audit_and_no_manifest(
        self, tmp_path
    ) -> None:
        # one page per symbol in the JAN window; budget 1 lets SPY finish
        # and refuses QQQ's request before it is sent
        report = run_collection(_config(tmp_path, budget=1))
        assert not report.ok and report.status == "ABORTED"
        assert report.manifest is None and report.manifest_path is None
        assert not _manifest_path(tmp_path).exists()  # NO success marker
        assert not _bars_path(tmp_path, "SPY").exists()  # two-phase: nothing written
        assert not _bars_path(tmp_path, "QQQ").exists()
        audit_path = tmp_path / NAMESPACE_DIRNAME / PARTIAL_AUDIT_NAME
        assert report.partial_audit_path == audit_path and audit_path.exists()
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        assert audit["status"] == "ABORTED"
        assert audit["reason"] == "REQUEST_BUDGET_EXCEEDED"
        assert "NOT sent" in audit["detail"]
        assert audit["budget"] == {"cap": 30, "spent": 1, "remaining": 29}
        assert audit["symbols"]["SPY"]["status"] == "FETCHED"
        assert audit["symbols"]["QQQ"]["status"] == "REFUSED"
        assert audit["license"]["status"] == "LICENSE_UNVERIFIED"
        assert audit["admission"]["status"] == "NOT_RESEARCH_ADMITTED"

    def test_lowered_budget_is_allowed_raising_is_not(self, tmp_path) -> None:
        with pytest.raises(CollectionError) as exc:
            _config(tmp_path, budget=31)
        assert "BAD_BUDGET" in str(exc.value)


# ---------------------------------------------------------------------------
# non-200 abort: stop immediately, no retry storm
# ---------------------------------------------------------------------------


class TestNon200Abort:
    def test_non_200_stops_immediately(self, tmp_path) -> None:
        opener = FakeAlpacaProbeTransport(
            calendar=_calendar(), fail_first_with_status=403
        )
        report = run_collection(_config(tmp_path), probe_opener=opener)
        assert not report.ok and report.manifest is None
        assert opener.calls == 1, "a non-200 must stop immediately (no retry storm)"
        assert len(opener.requests) == 1
        audit = report.partial_audit
        assert audit is not None
        assert audit["reason"] == "HTTP_STATUS"
        assert "403" in audit["detail"]
        assert audit["request_urls_seen"] == opener.requests
        assert not _manifest_path(tmp_path).exists()
        assert (tmp_path / NAMESPACE_DIRNAME / PARTIAL_AUDIT_NAME).exists()


# ---------------------------------------------------------------------------
# the calendar next-open rule in the written data
# ---------------------------------------------------------------------------


class TestNextOpenRuleInWrittenData:
    def test_window_excludes_v2_holidays_and_skips_carter_mourning(
        self, tmp_path
    ) -> None:
        run_collection(_config(tmp_path, window=JAN_WINDOW))
        spy = _rows(tmp_path, "SPY")
        events = {row["ts_event_utc"] for row in spy}
        # 2025-01-09 (Carter national day of mourning) has NO bar — the
        # v2 supply says closed and the fixture serves v2 sessions
        assert "2025-01-09T21:00:00+00:00" not in events
        # Wed 2025-01-08 close -> available at Fri 2025-01-10 open (v2 rule;
        # the defective v1 table would have stamped the closed Thursday)
        jan8 = [r for r in spy if r["ts_event_utc"] == "2025-01-08T21:00:00+00:00"]
        assert len(jan8) == 1
        assert jan8[0]["ts_available_utc"] == "2025-01-10T14:30:00+00:00"
        # Friday close -> Monday open (65.5h weekend span is legal)
        jan10 = [r for r in spy if r["ts_event_utc"] == "2025-01-10T21:00:00+00:00"]
        assert jan10[0]["ts_available_utc"] == "2025-01-13T14:30:00+00:00"

    def test_availability_strictly_after_event_for_every_row(self, tmp_path) -> None:
        run_collection(_config(tmp_path, window=(FULL_START, FULL_END)))
        for symbol in ("SPY", "QQQ"):
            for row in _rows(tmp_path, symbol):
                ts_event = dt.datetime.fromisoformat(row["ts_event_utc"])
                ts_avail = dt.datetime.fromisoformat(row["ts_available_utc"])
                assert ts_event.tzinfo is not None and ts_avail.tzinfo is not None
                assert ts_avail > ts_event

    def test_half_day_close_and_availability(self, tmp_path) -> None:
        run_collection(_config(tmp_path, window=DEC_WINDOW))
        spy = _rows(tmp_path, "SPY")
        half = [r for r in spy if r["ts_event_utc"].startswith("2025-12-24T")]
        assert len(half) == 1
        # 13:00 ET early close (EST) -> available at the next session open
        assert half[0]["ts_event_utc"] == "2025-12-24T18:00:00+00:00"
        assert half[0]["ts_available_utc"] == "2025-12-26T14:30:00+00:00"
        # Christmas has no bar
        assert not any(r["ts_event_utc"].startswith("2025-12-25T") for r in spy)


# ---------------------------------------------------------------------------
# dedup: deterministic over duplicate/overlapping rows
# ---------------------------------------------------------------------------


def _row(asset_id: str, close: str) -> dict:
    return {
        "asset_id": asset_id,
        "ts_event_utc": "2025-01-06T21:00:00+00:00",
        "ts_available_utc": "2025-01-07T14:30:00+00:00",
        "interval": "1Day",
        "open": "600.00",
        "high": "601.00",
        "low": "599.00",
        "close": close,
        "volume": "1000",
        "source": FAKE_TRANSPORT_LABEL,
        "adjustment": "RAW",
        "quality": "PIT_ASSUMED_NEXT_OPEN",
    }


class TestDedupDeterministic:
    def test_identical_duplicates_collapse_conflicts_refuse(self) -> None:
        row = _row("SPY", "600.10")
        merged = dedupe_bars_rows([row, dict(row)], context="unit")
        assert len(merged) == 1  # byte-identical duplicates collapse
        with pytest.raises(Exception) as exc:
            dedupe_bars_rows([row, _row("SPY", "999.99")], context="unit")
        assert "conflicting duplicate" in str(exc.value)

    def test_overlapping_page_boundaries_dedup_deterministically(self) -> None:
        a = [_row("SPY", "600.10"), dict(_row("SPY", "600.10"), ts_event_utc="2025-01-07T21:00:00+00:00")]
        b = [dict(_row("SPY", "600.10"), ts_event_utc="2025-01-07T21:00:00+00:00"), dict(_row("SPY", "600.10"), ts_event_utc="2025-01-08T21:00:00+00:00")]
        merged = dedupe_bars_rows([*a, *b], context="overlap")  # overlapping union
        assert [r["ts_event_utc"] for r in merged] == [
            "2025-01-06T21:00:00+00:00",
            "2025-01-07T21:00:00+00:00",
            "2025-01-08T21:00:00+00:00",
        ]
        again = dedupe_bars_rows([*b, *a], context="overlap")  # order-independent
        assert again == merged

    def test_rerun_into_same_dir_is_idempotent(self, tmp_path) -> None:
        run_collection(_config(tmp_path))
        first = _bars_path(tmp_path, "SPY").read_bytes()
        manifest_first = _manifest_path(tmp_path).read_bytes()
        report = run_collection(_config(tmp_path))  # rerun, merge dedup
        assert report.ok
        assert _bars_path(tmp_path, "SPY").read_bytes() == first
        assert _manifest_path(tmp_path).read_bytes() == manifest_first

    def test_narrower_rerun_keeps_full_history(self, tmp_path) -> None:
        run_collection(_config(tmp_path, window=(FULL_START, FULL_END)))
        full_rows = _rows(tmp_path, "SPY")
        assert full_rows[0]["ts_event_utc"].startswith("2017-01-03")
        rerun = run_collection(_config(tmp_path, window=DEC_WINDOW))
        assert rerun.ok
        kept = _rows(tmp_path, "SPY")
        assert kept == full_rows  # 2017 rows survive the overlapping rerun


# ---------------------------------------------------------------------------
# live transport: fail-closed refusals, blind env mechanism
# ---------------------------------------------------------------------------


class TestLiveRefusal:
    def test_live_without_signature_refused_value_never_echoed(self) -> None:
        with pytest.raises(AuthorizationRefused) as exc:
            resolve_transport_authorization(TRANSPORT_LIVE, environ={})
        assert "H1_REAL_API_AUTHORIZED" in str(exc.value)
        with pytest.raises(AuthorizationRefused) as exc:
            resolve_transport_authorization(
                TRANSPORT_LIVE, environ={cs.AUTH_ENV_VAR: "OPERATOR_SECRET_TOKEN"}
            )
        assert "OPERATOR_SECRET_TOKEN" not in str(exc.value)

    def test_signed_but_credentials_missing_is_blocked_env(self) -> None:
        with pytest.raises(BlockedEnv) as exc:
            resolve_transport_authorization(
                TRANSPORT_LIVE, environ={cs.AUTH_ENV_VAR: "SIGNED"}
            )
        assert "APCA_API_KEY_ID" in str(exc.value)

    def test_signed_with_credential_names_only(self) -> None:
        auth = resolve_transport_authorization(
            TRANSPORT_LIVE,
            environ={
                cs.AUTH_ENV_VAR: "SIGNED",
                "APCA_API_KEY_ID": "KEY-VALUE-MUST-NOT-LEAK",
                "APCA_API_SECRET_KEY": "SECRET-VALUE-MUST-NOT-LEAK",
            },
        )
        assert auth.transport == TRANSPORT_LIVE and auth.label == "LIVE"
        assert auth.credential_env_visible == ("APCA_API_KEY_ID", "APCA_API_SECRET_KEY")
        repr_auth = repr(auth) + str(auth)
        assert "KEY-VALUE-MUST-NOT-LEAK" not in repr_auth
        assert "SECRET-VALUE-MUST-NOT-LEAK" not in repr_auth

    def test_probe_never_needs_authorization(self) -> None:
        auth = resolve_transport_authorization(TRANSPORT_PROBE, environ={})
        assert auth.label == FAKE_TRANSPORT_LABEL

    def test_cli_live_refused_writes_nothing(self, tmp_path, capsys) -> None:
        cli = _cli()
        code = cli.main(
            ["--symbol", "SPY", "--symbol", "QQQ", "--output-dir", str(tmp_path),
             "--transport", "live"],
            environ={},
        )
        assert code == cli.EXIT_AUTHORIZATION_REFUSED == 4
        assert not (tmp_path / NAMESPACE_DIRNAME).exists()
        assert "AUTHORIZATION_REFUSED" in capsys.readouterr().out

    def test_cli_probe_happy_path(self, tmp_path, capsys) -> None:
        cli = _cli()
        code = cli.main(
            ["--symbol", "SPY", "--symbol", "QQQ", "--output-dir", str(tmp_path)],
            environ={},
        )
        assert code == cli.EXIT_OK == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["status"] == "COLLECTED"
        assert payload["transport"]["label"] == "FAKE_TRANSPORT"
        assert _manifest_path(tmp_path).exists()

    def test_cli_single_symbol_refused(self, tmp_path, capsys) -> None:
        cli = _cli()
        code = cli.main(
            ["--symbol", "SPY", "--output-dir", str(tmp_path)], environ={}
        )
        assert code == cli.EXIT_CONFIG_REFUSED == 2
        assert "UNIVERSE_MISMATCH" in capsys.readouterr().out
        assert not (tmp_path / NAMESPACE_DIRNAME).exists()

    def test_cli_window_outside_license_refused(self, tmp_path, capsys) -> None:
        cli = _cli()
        code = cli.main(
            ["--symbol", "SPY", "--symbol", "QQQ", "--start", "2016-01-01",
             "--end", "2025-12-31", "--output-dir", str(tmp_path)],
            environ={},
        )
        assert code == 2
        assert "OUTSIDE_LICENSE_WINDOW" in capsys.readouterr().out

    def test_cli_abort_maps_to_exit_5(self, tmp_path, capsys, monkeypatch) -> None:
        cli = _cli()
        audit_path = tmp_path / NAMESPACE_DIRNAME / PARTIAL_AUDIT_NAME
        stub = CollectionReport(
            status="ABORTED",
            manifest=None,
            partial_audit={
                "reason": "REQUEST_BUDGET_EXCEEDED", "detail": "stopped",
                "budget": {"spent": 2},
            },
            manifest_path=None,
            partial_audit_path=audit_path,
            bars_paths=(),
        )
        monkeypatch.setattr(cli, "run_collection", lambda *a, **k: stub)
        code = cli.main(
            ["--symbol", "SPY", "--symbol", "QQQ", "--output-dir", str(tmp_path)],
            environ={},
        )
        assert code == cli.EXIT_COLLECTION_ABORTED == 5
        payload = json.loads(capsys.readouterr().out)
        assert payload["manifest_written"] is False

    def test_calendar_supply_drift_fails_closed(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(cs, "FROZEN_SUPPLY_HASH_V2", "drifted-hash")
        with pytest.raises(CollectionError) as exc:
            run_collection(_config(tmp_path))
        assert "CALENDAR_SUPPLY_DRIFT" in str(exc.value)
        assert not (tmp_path / NAMESPACE_DIRNAME).exists()


# ---------------------------------------------------------------------------
# authorization-facts binding (V0.3 T1): live runs bind operator facts
# ---------------------------------------------------------------------------

#: the EXACT legacy unsigned docs — probe artifacts must stay byte-stable
_LEGACY_LICENSE_DOC = {
    "status": "LICENSE_UNVERIFIED",
    "calendar_supply_license": (
        "LICENSE_UNVERIFIED (carried unchanged from calendar supply v2: "
        "ICE/NYSE website personal-use terms are not a dataset license)"
    ),
    "market_data_license": (
        "Alpaca historical-data personal-research attestation (H1 §7 "
        "draft) remains unsigned"
    ),
}
_LEGACY_ADMISSION_DOC = {
    "status": "NOT_RESEARCH_ADMITTED",
    "until": (
        "the account owner signs the revised H1 §7 and confirms the "
        "calendar/data licenses; until then these files must not enter "
        "formal research"
    ),
    "corporate_actions": "NONE_COLLECTED",
    "raw_only_disclosure": (
        "raw prices without corporate actions: no total-return, "
        "long-horizon comparability, or unbiased-alpha claims are "
        "permitted from this data"
    ),
    "s8_forward_ledger": "EXCLUDED",
}

#: blind live env (NAMES visible to the gate; values never asserted)
_LIVE_ENV = {
    cs.AUTH_ENV_VAR: "SIGNED",
    "APCA_API_KEY_ID": "KEY-VALUE-MUST-NOT-LEAK",
    "APCA_API_SECRET_KEY": "SECRET-VALUE-MUST-NOT-LEAK",
}


def _authorized_scope() -> AuthorizedScope:
    return AuthorizedScope(
        start=FULL_START,
        end=FULL_END,
        symbols=("SPY", "QQQ"),
        feed=FEED,
        timeframe=TIMEFRAME,
    )


def _license_facts(scope: AuthorizedScope | None = None) -> LicenseFacts:
    return LicenseFacts(
        authorization_ref="H1-S7-TEST-0001",
        attested_by="account-owner-test-fixture",
        attested_at="2026-11-27T00:00:00+00:00",
        scope=scope or _authorized_scope(),
        calendar_license_note=(
            "calendar supply v2 personal-use terms re-checked by the "
            "operator on 2026-11-27"
        ),
    )


def _admission_facts(
    scope: AuthorizedScope | None = None, *, permitted: bool = False
) -> AdmissionFacts:
    return AdmissionFacts(
        authorization_ref="H1-S7-TEST-0001",
        attested_by="account-owner-test-fixture",
        attested_at="2026-11-27T00:00:00+00:00",
        scope=scope or _authorized_scope(),
        restricted_research_permitted=permitted,
    )


class TestAuthorizationFactsBinding:
    """V0.3 T1: a live run binds the operator's signed authorization
    FACTS into the new snapshot mechanically — the ``SIGNED`` env var is
    a necessary run switch but never a substitute for the signed record,
    so live without supplied facts refuses (AUTHORIZATION_FACTS_MISSING)
    instead of emitting unverifiable labels. Probe runs stay byte-stable
    and never emit verified labels nor bind facts (their artifacts are
    FAKE_TRANSPORT validation data)."""

    def test_probe_docs_byte_stable(self, tmp_path) -> None:
        report = run_collection(_config(tmp_path))
        manifest = report.manifest
        assert manifest is not None
        assert manifest["license"] == _LEGACY_LICENSE_DOC
        assert manifest["admission"] == _LEGACY_ADMISSION_DOC
        assert "restricted_research_permitted" not in manifest

    def test_probe_never_binds_facts(self, tmp_path) -> None:
        with pytest.raises(AuthorizationFactsRefused) as exc:
            run_collection(
                _config(tmp_path),
                license_facts=_license_facts(),
                admission_facts=_admission_facts(),
            )
        assert exc.value.reason == AUTHORIZATION_FACTS_INCOMPATIBLE
        assert not (tmp_path / NAMESPACE_DIRNAME).exists()

    def test_live_signed_without_facts_refused(self, tmp_path) -> None:
        with pytest.raises(AuthorizationFactsRefused) as exc:
            run_collection(
                _config(tmp_path, transport=TRANSPORT_LIVE), environ=_LIVE_ENV
            )
        assert exc.value.reason == AUTHORIZATION_FACTS_MISSING
        assert cs.AUTH_ENV_VAR in exc.value.detail
        assert not (tmp_path / NAMESPACE_DIRNAME).exists()

    def test_env_gate_precedence_unchanged(self, tmp_path) -> None:
        # no env signature at all: the original LIVE_AUTHORIZATION_REFUSED
        # still fires BEFORE the facts gate
        with pytest.raises(AuthorizationRefused):
            run_collection(_config(tmp_path, transport=TRANSPORT_LIVE), environ={})

    def test_live_facts_scope_mismatch_refused(self, tmp_path) -> None:
        narrow = AuthorizedScope(
            start=dt.date(2018, 1, 1),
            end=FULL_END,
            symbols=("SPY", "QQQ"),
            feed=FEED,
            timeframe=TIMEFRAME,
        )
        with pytest.raises(AuthorizationFactsRefused) as exc:
            run_collection(
                _config(tmp_path, transport=TRANSPORT_LIVE),
                environ=_LIVE_ENV,
                license_facts=_license_facts(narrow),
            )
        assert exc.value.reason == AUTHORIZATION_SCOPE_MISMATCH
        assert "2018-01-01" in exc.value.detail
        assert not (tmp_path / NAMESPACE_DIRNAME).exists()

    def test_live_wrong_feed_scope_refused(self, tmp_path) -> None:
        sip = AuthorizedScope(
            start=FULL_START, end=FULL_END,
            symbols=("SPY", "QQQ"), feed="sip", timeframe=TIMEFRAME)
        with pytest.raises(AuthorizationFactsRefused) as exc:
            run_collection(
                _config(tmp_path, transport=TRANSPORT_LIVE),
                environ=_LIVE_ENV,
                license_facts=_license_facts(sip),
            )
        assert exc.value.reason == AUTHORIZATION_SCOPE_MISMATCH

    def _fake_live_client(self, monkeypatch, opener=None) -> None:
        """Keep the REAL guarded client (host/path/budget gates); stand
        the offline FAKE fixture behind it — no network. This pins the
        live path's manifest BINDING behavior, not the transport."""
        real_guarded = cs.GuardedGetClient

        def guarded_with_fixture(**kwargs):
            kwargs["opener"] = opener or FakeAlpacaProbeTransport(calendar=_calendar())
            return real_guarded(**kwargs)

        monkeypatch.setattr(cs, "GuardedGetClient", guarded_with_fixture)

    def test_live_with_facts_binds_attestation(self, tmp_path, monkeypatch) -> None:
        self._fake_live_client(monkeypatch)
        report = run_collection(
            _config(tmp_path, transport=TRANSPORT_LIVE),
            environ=_LIVE_ENV,
            license_facts=_license_facts(),
            admission_facts=_admission_facts(),
        )
        assert report.ok
        manifest = report.manifest
        assert manifest is not None
        license_doc = manifest["license"]
        assert license_doc["status"] == LICENSE_STATUS_ATTESTED
        assert license_doc["authorization_ref"] == "H1-S7-TEST-0001"
        assert license_doc["attested_by"] == "account-owner-test-fixture"
        assert license_doc["attested_at"] == "2026-11-27T00:00:00+00:00"
        assert license_doc["authorization_scope"] == {
            "start": "2017-01-01",
            "end": "2025-12-31",
            "symbols": ["SPY", "QQQ"],
            "feed": "iex",
            "timeframe": "1Day",
        }
        assert "operator" in license_doc["calendar_supply_license"].lower()
        admission_doc = manifest["admission"]
        # an attestation NEVER upgrades admission: PIT is still ASSUMED
        assert admission_doc["status"] == "NOT_RESEARCH_ADMITTED"
        assert admission_doc["license_status"] == LICENSE_STATUS_ATTESTED
        assert admission_doc["authorization_ref"] == "H1-S7-TEST-0001"
        assert admission_doc["attested_by"] == "account-owner-test-fixture"
        assert admission_doc["restricted_research_permitted"] is False
        assert manifest["restricted_research_permitted"] is False
        # rows still carry the honest live source label
        for row in _rows(tmp_path, "SPY"):
            assert row["source"] == "alpaca_iex"

    def test_live_facts_restricted_permitted_recorded(
        self, tmp_path, monkeypatch
    ) -> None:
        self._fake_live_client(monkeypatch)
        report = run_collection(
            _config(tmp_path, transport=TRANSPORT_LIVE),
            environ=_LIVE_ENV,
            license_facts=_license_facts(),
            admission_facts=_admission_facts(permitted=True),
        )
        assert report.ok and report.manifest is not None
        assert report.manifest["restricted_research_permitted"] is True
        assert report.manifest["admission"]["restricted_research_permitted"] is True
        assert report.manifest["admission"]["status"] == "NOT_RESEARCH_ADMITTED"

    def test_live_abort_dump_carries_bound_facts(
        self, tmp_path, monkeypatch
    ) -> None:
        self._fake_live_client(
            monkeypatch,
            opener=FakeAlpacaProbeTransport(
                calendar=_calendar(), fail_first_with_status=403
            ),
        )
        report = run_collection(
            _config(tmp_path, transport=TRANSPORT_LIVE),
            environ=_LIVE_ENV,
            license_facts=_license_facts(),
            admission_facts=_admission_facts(),
        )
        assert not report.ok and report.manifest is None
        audit = report.partial_audit
        assert audit is not None
        assert audit["license"]["status"] == LICENSE_STATUS_ATTESTED
        assert audit["admission"]["authorization_ref"] == "H1-S7-TEST-0001"
        assert audit["restricted_research_permitted"] is False

    # -- operator record file (CLI surface) ------------------------------

    def _record_file(self, tmp_path: Path, **overrides) -> Path:
        record: dict = {
            "authorization_ref": "H1-S7-TEST-0001",
            "attested_by": "account-owner-test-fixture",
            "attested_at": "2026-11-27T00:00:00+00:00",
            "calendar_license_note": "calendar terms re-checked 2026-11-27",
            "scope": {
                "start": "2017-01-01",
                "end": "2025-12-31",
                "symbols": ["SPY", "QQQ"],
                "feed": "iex",
                "timeframe": "1Day",
            },
            "restricted_research_permitted": False,
        }
        record.update(overrides)
        path = tmp_path / "authorization_record.json"
        path.write_text(json.dumps(record), encoding="utf-8")
        return path

    def test_cli_live_without_record_refused(self, tmp_path, capsys) -> None:
        cli = _cli()
        code = cli.main(
            ["--symbol", "SPY", "--symbol", "QQQ", "--output-dir", str(tmp_path),
             "--transport", "live"],
            environ=_LIVE_ENV,
        )
        assert code == cli.EXIT_COLLECTION_REFUSED == 6
        payload = json.loads(capsys.readouterr().out)
        assert payload["status"] == "COLLECTION_REFUSED"
        assert payload["reason"] == AUTHORIZATION_FACTS_MISSING
        assert not (tmp_path / NAMESPACE_DIRNAME).exists()

    def test_cli_probe_with_record_refused(self, tmp_path, capsys) -> None:
        cli = _cli()
        record = self._record_file(tmp_path)
        code = cli.main(
            ["--symbol", "SPY", "--symbol", "QQQ", "--output-dir", str(tmp_path),
             "--authorization-record", str(record)],
            environ={},
        )
        assert code == cli.EXIT_COLLECTION_REFUSED == 6
        payload = json.loads(capsys.readouterr().out)
        assert payload["reason"] == AUTHORIZATION_FACTS_INCOMPATIBLE
        assert not (tmp_path / NAMESPACE_DIRNAME).exists()

    def test_cli_mismatched_scope_record_refused(self, tmp_path, capsys) -> None:
        cli = _cli()
        record = self._record_file(
            tmp_path,
            scope={
                "start": "2018-01-01", "end": "2025-12-31",
                "symbols": ["SPY", "QQQ"], "feed": "iex", "timeframe": "1Day",
            },
        )
        code = cli.main(
            ["--symbol", "SPY", "--symbol", "QQQ", "--output-dir", str(tmp_path),
             "--transport", "live", "--authorization-record", str(record)],
            environ=_LIVE_ENV,
        )
        assert code == cli.EXIT_COLLECTION_REFUSED == 6
        payload = json.loads(capsys.readouterr().out)
        assert payload["status"] == "COLLECTION_REFUSED"
        assert payload["reason"] == AUTHORIZATION_SCOPE_MISMATCH
        assert not (tmp_path / NAMESPACE_DIRNAME).exists()

    def test_cli_invalid_record_refused(self, tmp_path, capsys) -> None:
        cli = _cli()
        record = tmp_path / "authorization_record.json"
        record.write_text(
            json.dumps({"authorization_ref": "only-one-field"}), encoding="utf-8"
        )
        code = cli.main(
            ["--symbol", "SPY", "--symbol", "QQQ", "--output-dir", str(tmp_path),
             "--transport", "live", "--authorization-record", str(record)],
            environ=_LIVE_ENV,
        )
        assert code == cli.EXIT_COLLECTION_REFUSED == 6
        payload = json.loads(capsys.readouterr().out)
        assert payload["reason"] == "AUTHORIZATION_RECORD_INVALID"

    def test_cli_record_file_missing_refused(self, tmp_path, capsys) -> None:
        cli = _cli()
        code = cli.main(
            ["--symbol", "SPY", "--symbol", "QQQ", "--output-dir", str(tmp_path),
             "--authorization-record", str(tmp_path / "absent.json")],
            environ={},
        )
        assert code == cli.EXIT_COLLECTION_REFUSED == 6
        payload = json.loads(capsys.readouterr().out)
        assert payload["reason"] == "AUTHORIZATION_RECORD_INVALID"

    def test_cli_live_with_record_binds_attestation(
        self, tmp_path, capsys, monkeypatch
    ) -> None:
        self._fake_live_client(monkeypatch)
        cli = _cli()
        record = self._record_file(tmp_path)
        code = cli.main(
            ["--symbol", "SPY", "--symbol", "QQQ", "--output-dir", str(tmp_path),
             "--transport", "live", "--authorization-record", str(record)],
            environ=_LIVE_ENV,
        )
        assert code == cli.EXIT_OK == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["status"] == "COLLECTED"
        assert payload["license"] == LICENSE_STATUS_ATTESTED
        manifest = json.loads(_manifest_path(tmp_path).read_text(encoding="utf-8"))
        assert manifest["license"]["authorization_ref"] == "H1-S7-TEST-0001"
        assert manifest["admission"]["status"] == "NOT_RESEARCH_ADMITTED"

    def test_parse_authorization_record_shapes_scope(self) -> None:
        record = parse_authorization_record({
            "authorization_ref": "R-1",
            "attested_by": "owner",
            "attested_at": "2026-11-27",
            "calendar_license_note": "note",
            "scope": {
                "start": "2017-01-01", "end": "2025-12-31",
                "symbols": ["QQQ", "SPY"], "feed": "iex", "timeframe": "1Day",
            },
        })
        # symbol order canonicalized: manifests stay byte-deterministic
        assert record.license.scope.symbols == ("SPY", "QQQ")
        assert record.admission.restricted_research_permitted is False

    def test_parse_authorization_record_unknown_key_refused(self) -> None:
        with pytest.raises(CollectionError) as exc:
            parse_authorization_record({
                "authorization_ref": "R-1", "attested_by": "owner",
                "attested_at": "2026-11-27", "calendar_license_note": "note",
                "signature": "trust-me",   # unknown key — refused
                "scope": {
                    "start": "2017-01-01", "end": "2025-12-31",
                    "symbols": ["SPY", "QQQ"], "feed": "iex",
                    "timeframe": "1Day",
                },
            })
        assert exc.value.reason == "AUTHORIZATION_RECORD_INVALID"


# ---------------------------------------------------------------------------
# probe transport units
# ---------------------------------------------------------------------------


class TestProbeTransport:
    def test_bytes_deterministic_across_instances(self) -> None:
        bodies = []
        for _ in range(2):
            transport = FakeAlpacaProbeTransport(calendar=_calendar(), page_size=3)
            bodies.append(transport(self._request("2025-01-02", "2025-01-10")).read())
        assert bodies[0] == bodies[1]

    def test_pagination_tokens_chain(self) -> None:
        transport = FakeAlpacaProbeTransport(calendar=_calendar(), page_size=2)
        page1 = json.loads(
            transport(self._request("2025-01-02", "2025-01-10")).read().decode("utf-8")
        )
        assert page1["symbol"] == "SPY" and len(page1["bars"]) == 2
        assert page1["next_page_token"] == "2"
        page2 = json.loads(
            transport(
                self._request("2025-01-02", "2025-01-10", page_token="2")
            ).read().decode("utf-8")
        )
        assert len(page2["bars"]) == 2
        # continuation pages never repeat page 1's sessions
        assert page2["bars"][0]["t"] > page1["bars"][-1]["t"]

    def test_unauthorized_path_refused_by_fixture(self) -> None:
        transport = FakeAlpacaProbeTransport(calendar=_calendar())
        with pytest.raises(ValueError):
            transport(self._request("2025-01-02", "2025-01-10", path="/v2/stocks/AAPL/bars"))

    def test_fault_injection_raises_http_error(self) -> None:
        import urllib.error

        transport = FakeAlpacaProbeTransport(
            calendar=_calendar(), fail_first_with_status=503
        )
        with pytest.raises(urllib.error.HTTPError) as exc:
            transport(self._request("2025-01-02", "2025-01-10"))
        assert exc.value.code == 503

    def test_exact_decimal_json_round_trip(self) -> None:
        from apps.market_gateway.probe_transport import _encode_exact_json

        text = _encode_exact_json({"o": Decimal("600.25")}).decode("utf-8")
        assert text == '{"o": 600.25}'  # bare number, never a quoted string
        parsed = json.loads(text, parse_float=Decimal)
        assert parsed["o"] == Decimal("600.25") and isinstance(parsed["o"], Decimal)

    @staticmethod
    def _request(start: str, end: str, *, page_token: str | None = None, path: str = "/v2/stocks/SPY/bars"):
        import urllib.parse
        import urllib.request

        params = {
            "adjustment": "raw",
            "end": end,
            "feed": "iex",
            "limit": "10000",
            "start": start,
            "timeframe": "1Day",
        }
        if page_token is not None:
            params["page_token"] = page_token
        url = f"https://data.alpaca.markets{path}?" + urllib.parse.urlencode(sorted(params.items()))
        return urllib.request.Request(url, method="GET")


# ---------------------------------------------------------------------------
# misc fail-closed config
# ---------------------------------------------------------------------------


class TestConfigRefusals:
    def test_duplicate_symbols_still_require_both(self, tmp_path) -> None:
        with pytest.raises(CollectionError) as exc:
            CollectionConfig(
                symbols=("SPY", "SPY"), start=JAN_WINDOW[0], end=JAN_WINDOW[1],
                output_dir=tmp_path,
            )
        assert "UNIVERSE_MISMATCH" in str(exc.value)

    def test_unknown_symbol_refused(self, tmp_path) -> None:
        with pytest.raises(CollectionError):
            CollectionConfig(
                symbols=("SPY", "AAPL"), start=JAN_WINDOW[0], end=JAN_WINDOW[1],
                output_dir=tmp_path,
            )


@functools.lru_cache(maxsize=1)
def _cli():
    spec = importlib.util.spec_from_file_location(
        "collect_historical_snapshot_cli",
        REPO_ROOT / "scripts" / "collect_historical_snapshot.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-q"]))
