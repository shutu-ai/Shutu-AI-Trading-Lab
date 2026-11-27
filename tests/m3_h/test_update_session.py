"""Current-window incremental update entry + operator-supplied CURRENT
calendar supply — dry-run acceptance (T3-B of BUSINESS-V03-OPERATIONAL-
ACTIVATION-20261127-R1).

NO NETWORK anywhere in this file: probe mode runs the real guarded
client over the in-repo deterministic fixture transport; live-mode
tests prove every refusal path BEFORE any transport exists
(authorization record, scope match, blind env — zero bytes, zero
sockets, credential values never echoed).

Pins, per the task contract:

- ``build_current_supply`` / ``load_supply_from_config``: the
  operator-supplied CURRENT calendar (supplied data, never inferred
  from data gaps) validates fail-closed — weekend entries, duplicates,
  unsorted lists, unknown keys, missing fields, empty
  version/license/refs, inverted windows — and must AGREE with the
  frozen v2 supply over the window overlap (2026-01-19 MLK);
- probe end-to-end: small window, budget accounting (structural cap 6),
  ``FAKE_TRANSPORT_INCREMENTAL`` labels, ``historical_research``
  namespace layout, RECOMPUTED hashes, MarketBar-valid rows, next-open
  rule over the 2026 holidays (Juneteenth) and the Christmas Eve
  half-day;
- default window: end = yesterday ET, start = 10 sessions back; a
  stale supply refuses (CALENDAR_SUPPLY_STALE) before any write;
- live gate: CURRENT_DATA_AUTHORIZED=SIGNED + operator authorization
  record whose scope matches the invocation exactly — every missing or
  mismatched fact refuses with the reason recorded and nothing echoed;
- budget exceeded aborts cleanly (two-phase: partial audit, no
  manifest, no bars); the target must be clean — merging into an
  existing snapshot refuses (future work).
"""

from __future__ import annotations

import datetime as dt
import functools
import importlib.util
import json
import sys
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (REPO_ROOT / "src", REPO_ROOT / "tests", REPO_ROOT):
    _sp = str(_p)
    if _sp not in sys.path:
        sys.path.insert(0, _sp)

from apps.market_gateway import update_session as us  # noqa: E402
from apps.market_gateway.collection_session import (  # noqa: E402
    MANIFEST_NAME as COLLECTION_MANIFEST_NAME,
    NAMESPACE_DIRNAME,
    PROBE_RECEIVED_AT_UTC,
)
from apps.market_gateway.probe_transport import (  # noqa: E402
    FakeAlpacaProbeTransport,
)
from apps.market_gateway.update_session import (  # noqa: E402
    AUTH_ENV_VAR,
    DEFAULT_SESSIONS_LOOKBACK,
    UPDATE_BUDGET_CAP,
    UPDATE_MANIFEST_NAME,
    UPDATE_PARTIAL_AUDIT_NAME,
    TRANSPORT_LABEL_PROBE_INCREMENTAL,
    WINDOW_SOURCE_DEFAULT,
    WINDOW_SOURCE_EXPLICIT,
    AuthorizationRefused,
    BlockedEnv,
    UpdateConfig,
    UpdateError,
    UpdateReport,
    load_authorization_record,
    parse_authorization_record,
    resolve_default_window,
    resolve_update_authorization,
    run_update,
)
from trading_lab.contracts.events import MarketBar  # noqa: E402
from trading_lab.data.calendar import CalendarError, ET, MarketCalendar  # noqa: E402
from trading_lab.data.historical_calendar import (  # noqa: E402
    CalendarSupply,
    VersionedMarketCalendar,
)
from trading_lab.data.historical_calendar_supply import (  # noqa: E402
    CalendarConfigError,
    CalendarSupplyDriftError,
    build_current_supply,
    frozen_supply_hash,
    load_supply_from_config,
)
from trading_lab.security.canonical import sha256_hex  # noqa: E402

ET_TZ = ZoneInfo("America/New_York")
UTC = dt.timezone.utc
CONFIG_PATH = REPO_ROOT / "configs" / "current_calendar.yaml"
#: spans the 2026 Juneteenth closure (Fri 2026-06-19)
JUNE_WINDOW = (dt.date(2026, 6, 15), dt.date(2026, 6, 26))
#: spans the Christmas Eve half-day and the Christmas closure (ends 12-30:
#: the 12-31 final-session boundary is covered by its own refusal test)
DECEMBER_WINDOW = (dt.date(2026, 12, 21), dt.date(2026, 12, 30))
LIVE_ENV = {
    AUTH_ENV_VAR: "SIGNED",
    "APCA_API_KEY_ID": "KEY-VALUE-MUST-NOT-LEAK",
    "APCA_API_SECRET_KEY": "SECRET-VALUE-MUST-NOT-LEAK",
}


def _supply() -> CalendarSupply:
    return load_supply_from_config(CONFIG_PATH)


def _calendar() -> VersionedMarketCalendar:
    return VersionedMarketCalendar.from_supply(_supply())


def _config(
    tmp_path: Path,
    *,
    window: tuple[dt.date, dt.date] = JUNE_WINDOW,
    transport: str = "probe",
    budget: int = UPDATE_BUDGET_CAP,
    window_source: str = WINDOW_SOURCE_EXPLICIT,
    record: object = None,
    supply: CalendarSupply | None = None,
) -> UpdateConfig:
    return UpdateConfig(
        symbols=("SPY", "QQQ"),
        start=window[0],
        end=window[1],
        output_dir=tmp_path,
        calendar_supply=supply if supply is not None else _supply(),
        transport=transport,
        request_budget=budget,
        window_source=window_source,
        authorization_record=record,  # type: ignore[arg-type]
    )


def _manifest_path(tmp_path: Path) -> Path:
    return tmp_path / NAMESPACE_DIRNAME / UPDATE_MANIFEST_NAME


def _bars_path(tmp_path: Path, symbol: str) -> Path:
    return tmp_path / NAMESPACE_DIRNAME / symbol / "bars.jsonl"


def _rows(tmp_path: Path, symbol: str) -> list[dict]:
    return [
        json.loads(line)
        for line in _bars_path(tmp_path, symbol).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _auth_record(
    tmp_path: Path,
    *,
    symbols: list[str] | None = None,
    start: dt.date | None = None,
    end: dt.date | None = None,
    budget: int = UPDATE_BUDGET_CAP,
    ref: str = "AUTH-CUR-2026-001",
    by: str = "operator",
    at: str = "2026-11-27T09:00:00+00:00",
    raw: dict | None = None,
) -> Path:
    doc = raw if raw is not None else {
        "authorization_ref": ref,
        "attested_by": by,
        "attested_at": at,
        "scope": {
            "symbols": symbols if symbols is not None else ["SPY", "QQQ"],
            "start": (start if start is not None else JUNE_WINDOW[0]).isoformat(),
            "end": (end if end is not None else JUNE_WINDOW[1]).isoformat(),
            "budget": budget,
        },
    }
    path = tmp_path / "auth_record.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# build_current_supply: construction + fail-closed validation
# ---------------------------------------------------------------------------


class TestBuildCurrentSupply:
    def test_happy_path_fields(self) -> None:
        supply = build_current_supply(
            (dt.date(2026, 7, 3),),
            (dt.date(2026, 12, 24),),
            dt.date(2026, 7, 1),
            dt.date(2026, 12, 31),
            version="test-current-v1",
            license_note="LICENSE_UNVERIFIED",
            source_refs=("https://example.invalid/calendar",),
            retrieved_utc=dt.datetime(2026, 11, 27, tzinfo=UTC),
        )
        assert supply.version == "test-current-v1"
        assert supply.holidays == frozenset({dt.date(2026, 7, 3)})
        assert supply.half_days == frozenset({dt.date(2026, 12, 24)})
        assert supply.source_url == "https://example.invalid/calendar"
        assert supply.retrieved_utc.tzinfo is not None
        assert "LICENSE_UNVERIFIED" in supply.source  # stated, never silent

    def test_license_note_default_is_stated_not_silent(self) -> None:
        supply = build_current_supply(
            (), (), dt.date(2027, 1, 1), dt.date(2027, 12, 31),
            version="t", source_refs=("https://example.invalid/x",),
            retrieved_utc=dt.datetime(2026, 11, 27, tzinfo=UTC),
        )
        assert "LICENSE_UNVERIFIED" in supply.source

    def test_hash_is_deterministic_and_date_sensitive(self) -> None:
        def _build() -> CalendarSupply:
            return build_current_supply(
                (dt.date(2026, 7, 3),), (), dt.date(2026, 7, 1), dt.date(2026, 7, 31),
                version="t", source_refs=("https://example.invalid/x",),
                retrieved_utc=dt.datetime(2026, 11, 27, tzinfo=UTC),
            )

        assert frozen_supply_hash(_build()) == frozen_supply_hash(_build())
        moved = build_current_supply(
            (dt.date(2026, 7, 2),), (), dt.date(2026, 7, 1), dt.date(2026, 7, 31),
            version="t", source_refs=("https://example.invalid/x",),
            retrieved_utc=dt.datetime(2026, 11, 27, tzinfo=UTC),
        )
        assert frozen_supply_hash(moved) != frozen_supply_hash(_build())

    @pytest.mark.parametrize(
        "mutation",
        [
            {"version": ""},
            {"version": "   "},
            {"license_note": ""},
            {"license_note": "  "},
            {"source_refs": ()},
            {"source_refs": ("not-a-url",)},
            {"source_refs": ("https://ok.invalid/x", "   ")},
        ],
    )
    def test_empty_version_license_and_bad_refs_refused(self, mutation) -> None:
        kwargs = {
            "version": "v",
            "source_refs": ("https://example.invalid/x",),
            "retrieved_utc": dt.datetime(2026, 11, 27, tzinfo=UTC),
        }
        kwargs.update(mutation)
        with pytest.raises(CalendarError):
            build_current_supply(
                (), (), dt.date(2027, 1, 1), dt.date(2027, 12, 31), **kwargs
            )

    def test_window_must_be_strictly_positive(self) -> None:
        for valid_from, valid_until in (
            (dt.date(2027, 1, 1), dt.date(2027, 1, 1)),  # equal refuses
            (dt.date(2027, 2, 1), dt.date(2027, 1, 1)),  # inverted refuses
        ):
            with pytest.raises(CalendarError) as exc:
                build_current_supply(
                    (), (), valid_from, valid_until,
                    version="v", source_refs=("https://example.invalid/x",),
                    retrieved_utc=dt.datetime(2026, 11, 27, tzinfo=UTC),
                )
            assert "sane" in str(exc.value)

    def test_weekend_holiday_refused(self) -> None:
        with pytest.raises(CalendarError) as exc:
            build_current_supply(
                (dt.date(2027, 1, 2),), (), dt.date(2027, 1, 1), dt.date(2027, 12, 31),
                version="v", source_refs=("https://example.invalid/x",),
            )
        assert "weekend" in str(exc.value)

    def test_weekend_half_day_refused(self) -> None:
        with pytest.raises(CalendarError) as exc:
            build_current_supply(
                (), (dt.date(2027, 1, 2),), dt.date(2027, 1, 1), dt.date(2027, 12, 31),
                version="v", source_refs=("https://example.invalid/x",),
            )
        assert "weekend" in str(exc.value)

    def test_duplicate_entries_refused(self) -> None:
        with pytest.raises(CalendarError) as exc:
            build_current_supply(
                (dt.date(2027, 1, 4), dt.date(2027, 1, 4)), (),
                dt.date(2027, 1, 1), dt.date(2027, 12, 31),
                version="v", source_refs=("https://example.invalid/x",),
            )
        assert "duplicate" in str(exc.value)

    def test_holiday_half_day_overlap_refused(self) -> None:
        with pytest.raises(CalendarError) as exc:
            build_current_supply(
                (dt.date(2027, 1, 4),), (dt.date(2027, 1, 4),),
                dt.date(2027, 1, 1), dt.date(2027, 12, 31),
                version="v", source_refs=("https://example.invalid/x",),
            )
        assert "both holiday and half-day" in str(exc.value)

    def test_entry_outside_window_refused(self) -> None:
        with pytest.raises(CalendarError) as exc:
            build_current_supply(
                (dt.date(2026, 7, 3),), (), dt.date(2026, 8, 1), dt.date(2026, 12, 31),
                version="v", source_refs=("https://example.invalid/x",),
            )
        assert "outside supply window" in str(exc.value)

    def test_naive_retrieved_utc_refused(self) -> None:
        with pytest.raises(CalendarError) as exc:
            build_current_supply(
                (), (), dt.date(2027, 1, 1), dt.date(2027, 12, 31),
                version="v", source_refs=("https://example.invalid/x",),
                retrieved_utc=dt.datetime(2026, 11, 27),
            )
        assert "timezone-aware" in str(exc.value)

    def test_default_retrieved_utc_is_aware_wall_clock(self) -> None:
        supply = build_current_supply(
            (), (), dt.date(2027, 1, 1), dt.date(2027, 12, 31),
            version="v", source_refs=("https://example.invalid/x",),
        )
        assert supply.retrieved_utc.tzinfo is not None

    # -- drift vs the frozen v2 supply ------------------------------------

    def test_extra_holiday_contradicting_v2_is_drift(self) -> None:
        # Fri 2026-01-02 IS a session per the frozen v2 supply
        with pytest.raises(CalendarSupplyDriftError) as exc:
            build_current_supply(
                (dt.date(2026, 1, 2),), (), dt.date(2026, 1, 1), dt.date(2026, 12, 31),
                version="bad-v", source_refs=("https://example.invalid/x",),
            )
        assert exc.value.reason == "CALENDAR_SUPPLY_DRIFT"
        assert "2026-01-02" in exc.value.detail

    def test_missing_mlk_2026_is_drift(self) -> None:
        from trading_lab.data.historical_calendar_supply import (
            NYSE_2017_2025_SUPPLY_V2,
        )

        without_mlk = {
            day for day in NYSE_2017_2025_SUPPLY_V2.holidays if day.year == 2026
        } - {dt.date(2026, 1, 19)}
        with pytest.raises(CalendarSupplyDriftError) as exc:
            build_current_supply(
                sorted(without_mlk), (), dt.date(2026, 1, 1), dt.date(2026, 12, 31),
                version="bad-v", source_refs=("https://example.invalid/x",),
            )
        assert exc.value.reason == "CALENDAR_SUPPLY_DRIFT"
        assert "2026-01-19" in exc.value.detail

    def test_disjoint_window_skips_drift_check(self) -> None:
        # 2027 does not overlap the frozen v2 window: no drift possible
        supply = build_current_supply(
            (dt.date(2027, 1, 1),), (), dt.date(2027, 1, 1), dt.date(2027, 12, 31),
            version="future-v", source_refs=("https://example.invalid/x",),
        )
        assert dt.date(2027, 1, 1) in supply.holidays


# ---------------------------------------------------------------------------
# load_supply_from_config: the shipped file + fail-closed config parsing
# ---------------------------------------------------------------------------


class TestLoadSupplyFromConfig:
    def test_shipped_file_loads_with_the_documented_shape(self) -> None:
        supply = _supply()
        assert supply.version == "nyse-2026-current-operator-v1"
        assert supply.valid_from == dt.date(2026, 1, 1)
        assert supply.valid_until == dt.date(2026, 12, 31)
        assert supply.holidays == frozenset(
            {
                dt.date(2026, 1, 1), dt.date(2026, 1, 19), dt.date(2026, 2, 16),
                dt.date(2026, 4, 3), dt.date(2026, 5, 25), dt.date(2026, 6, 19),
                dt.date(2026, 7, 3), dt.date(2026, 9, 7), dt.date(2026, 11, 26),
                dt.date(2026, 12, 25),
            }
        )
        assert supply.half_days == frozenset({dt.date(2026, 12, 24)})
        assert "LICENSE_UNVERIFIED" in supply.source  # stated placeholder
        assert supply.source_url.startswith("https://")

    def test_mlk_2026_matches_frozen_v2_fixed_date(self) -> None:
        from trading_lab.data.historical_calendar_supply import (
            NYSE_2017_2025_SUPPLY_V2,
        )

        assert dt.date(2026, 1, 19) in NYSE_2017_2025_SUPPLY_V2.holidays
        assert dt.date(2026, 1, 19) in _supply().holidays

    def test_overlap_window_agrees_with_frozen_v2_day_by_day(self) -> None:
        supply = _supply()
        baseline = MarketCalendar(
            holidays=set(_v2().holidays), half_days=set(_v2().half_days)
        )
        current = MarketCalendar(holidays=set(supply.holidays), half_days=set(supply.half_days))
        day = max(supply.valid_from, _v2().valid_from)
        last = min(supply.valid_until, _v2().valid_until)
        checked = 0
        while day <= last:
            a, b = baseline.session(day), current.session(day)
            assert (a.is_trading_day, a.is_half_day) == (b.is_trading_day, b.is_half_day)
            checked += 1
            day += dt.timedelta(days=1)
        assert checked == 31  # the whole shared January 2026

    def test_calendar_answers_2026_sessions_and_half_day(self) -> None:
        calendar = _calendar()
        # January 2026: 22 weekdays minus New Year (01-01) and MLK (01-19)
        sessions = calendar.expected_sessions(dt.date(2026, 1, 1), dt.date(2026, 1, 31))
        assert len(sessions) == 20
        assert dt.date(2026, 1, 1) not in sessions
        assert dt.date(2026, 1, 19) not in sessions
        half = calendar.session(dt.date(2026, 12, 24))
        assert half.is_trading_day and half.is_half_day
        assert half.close_utc() == dt.datetime(2026, 12, 24, 18, 0, tzinfo=UTC)  # 13:00 EST
        assert not calendar.is_trading_day(dt.date(2026, 7, 3))  # July 4 observed

    def _write(self, tmp_path: Path, doc: dict) -> Path:
        path = tmp_path / "case.yaml"
        text = (
            "version: t\n"
            "valid_from: '2027-01-01'\n"
            "valid_until: '2027-12-31'\n"
        )
        if "holidays" in doc:
            if doc["holidays"]:
                text += "holidays:"
                text += "".join(f"\n  - '{item}'" for item in doc["holidays"]) + "\n"
            else:
                text += "holidays: []\n"
        if "half_days" in doc:
            if doc["half_days"]:
                text += "half_days:"
                text += "".join(f"\n  - '{item}'" for item in doc["half_days"]) + "\n"
            else:
                text += "half_days: []\n"
        if "license_note" in doc:
            text += f"license_note: '{doc['license_note']}'\n"
        if "source_refs" in doc:
            if doc["source_refs"]:
                text += "source_refs:"
                text += "".join(f"\n  - '{item}'" for item in doc["source_refs"]) + "\n"
            else:
                text += "source_refs: []\n"
        path.write_text(text, encoding="utf-8")
        return path

    def test_unknown_key_refused(self, tmp_path) -> None:
        path = self._write(tmp_path, {"holidays": [], "half_days": [], "license_note": "x", "source_refs": ["https://a.invalid/x"]})
        path.write_text(
            path.read_text(encoding="utf-8") + "unexpected_key: 1\n", encoding="utf-8"
        )
        with pytest.raises(CalendarConfigError) as exc:
            load_supply_from_config(path)
        assert exc.value.reason == "CONFIG_UNKNOWN_KEYS"

    def test_missing_field_refused(self, tmp_path) -> None:
        path = tmp_path / "missing.yaml"
        path.write_text(
            "version: t\nvalid_from: '2027-01-01'\nvalid_until: '2027-12-31'\n"
            "holidays: []\nhalf_days: []\nsource_refs:\n  - 'https://a.invalid/x'\n",
            encoding="utf-8",
        )  # license_note missing
        with pytest.raises(CalendarConfigError) as exc:
            load_supply_from_config(path)
        assert exc.value.reason == "CONFIG_MISSING_FIELDS"
        assert "license_note" in exc.value.detail

    def test_unsorted_holidays_refused(self, tmp_path) -> None:
        path = self._write(tmp_path, {"holidays": ["2027-02-02", "2027-01-18"], "half_days": [], "license_note": "x", "source_refs": ["https://a.invalid/x"]})
        with pytest.raises(CalendarConfigError) as exc:
            load_supply_from_config(path)
        assert exc.value.reason == "CONFIG_UNSORTED_LIST"

    def test_duplicate_holidays_refused(self, tmp_path) -> None:
        path = self._write(tmp_path, {"holidays": ["2027-01-18", "2027-01-18"], "half_days": [], "license_note": "x", "source_refs": ["https://a.invalid/x"]})
        with pytest.raises(CalendarConfigError) as exc:
            load_supply_from_config(path)
        assert exc.value.reason == "CONFIG_DUPLICATE_DATE"

    def test_bad_date_string_refused(self, tmp_path) -> None:
        path = self._write(tmp_path, {"holidays": ["not-a-date"], "half_days": [], "license_note": "x", "source_refs": ["https://a.invalid/x"]})
        with pytest.raises(CalendarConfigError) as exc:
            load_supply_from_config(path)
        assert exc.value.reason == "CONFIG_BAD_DATE"

    def test_empty_license_note_refused(self, tmp_path) -> None:
        path = self._write(tmp_path, {"holidays": [], "half_days": [], "license_note": "  ", "source_refs": ["https://a.invalid/x"]})
        with pytest.raises(CalendarConfigError) as exc:
            load_supply_from_config(path)
        assert exc.value.reason == "CONFIG_BAD_LICENSE_NOTE"

    def test_empty_source_refs_refused(self, tmp_path) -> None:
        path = self._write(tmp_path, {"holidays": [], "half_days": [], "license_note": "x", "source_refs": []})
        with pytest.raises(CalendarConfigError) as exc:
            load_supply_from_config(path)
        assert exc.value.reason == "CONFIG_BAD_SOURCE_REFS"

    def test_non_mapping_top_level_refused(self, tmp_path) -> None:
        path = tmp_path / "list.yaml"
        path.write_text("- just\n- a\n- list\n", encoding="utf-8")
        with pytest.raises(CalendarConfigError) as exc:
            load_supply_from_config(path)
        assert exc.value.reason == "CONFIG_SHAPE"

    def test_unparsable_yaml_refused(self, tmp_path) -> None:
        path = tmp_path / "broken.yaml"
        path.write_text("version: [unclosed\n", encoding="utf-8")
        with pytest.raises(CalendarConfigError) as exc:
            load_supply_from_config(path)
        assert exc.value.reason == "CONFIG_PARSE"

    def test_missing_file_refused(self, tmp_path) -> None:
        with pytest.raises(CalendarConfigError) as exc:
            load_supply_from_config(tmp_path / "nope.yaml")
        assert exc.value.reason == "CONFIG_NOT_READABLE"

    def test_yaml_drift_refused_through_load(self, tmp_path) -> None:
        # a 2026 file that contradicts v2 (MLK moved to 01-20) refuses
        path = self._write(tmp_path, {"holidays": ["2026-01-01", "2026-01-20", "2026-02-16", "2026-04-03", "2026-05-25", "2026-06-19", "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25"], "half_days": ["2026-12-24"], "license_note": "x", "source_refs": ["https://a.invalid/x"]})
        path.write_text(
            path.read_text(encoding="utf-8")
            .replace("version: t", "version: drifted")
            .replace("2027-01-01", "2026-01-01")
            .replace("2027-12-31", "2026-12-31"),
            encoding="utf-8",
        )
        with pytest.raises(CalendarSupplyDriftError):
            load_supply_from_config(path)


def _v2() -> CalendarSupply:
    from trading_lab.data.historical_calendar_supply import NYSE_2017_2025_SUPPLY_V2

    return NYSE_2017_2025_SUPPLY_V2


# ---------------------------------------------------------------------------
# probe end-to-end: small window, budget, manifest, hashes, contract rows
# ---------------------------------------------------------------------------


class TestProbeEndToEnd:
    def test_small_window_two_symbols_collected(self, tmp_path) -> None:
        report = run_update(_config(tmp_path))
        assert report.ok and report.status == "COLLECTED"
        assert report.manifest is not None and report.manifest_path.exists()
        assert len(report.bars_paths) == 2
        for symbol in ("SPY", "QQQ"):
            # 10 weekdays minus the Juneteenth Friday closure
            assert len(_rows(tmp_path, symbol)) == 9

    def test_manifest_honesty_fields(self, tmp_path) -> None:
        report = run_update(_config(tmp_path))
        manifest = report.manifest
        assert manifest is not None
        assert manifest["schema"] == "update_manifest_v1"
        assert manifest["entry"] == "incremental_update"
        assert manifest["status"] == "COLLECTED"
        assert manifest["transport"] == {
            "mode": "probe",
            "label": TRANSPORT_LABEL_PROBE_INCREMENTAL,
            "real_network_used": False,
        }
        supply = _supply()
        assert manifest["calendar_supply"]["version"] == supply.version
        assert manifest["calendar_supply"]["hash"] == frozen_supply_hash(supply)
        assert manifest["license"]["status"] == "LICENSE_UNVERIFIED"
        assert manifest["pit"]["level"] == "ASSUMED"
        assert manifest["pit"]["api_verified_claim"] == "NONE"
        assert manifest["admission"]["status"] == "NOT_RESEARCH_ADMITTED"
        assert manifest["window"]["source"] == WINDOW_SOURCE_EXPLICIT

    def test_budget_accounting_and_request_audit(self, tmp_path) -> None:
        report = run_update(_config(tmp_path))
        manifest = report.manifest
        assert manifest is not None
        assert manifest["budget"]["structural_cap"] == UPDATE_BUDGET_CAP == 6
        assert manifest["budget"] == {
            "cap": 6,
            "structural_cap": 6,
            "authorization_budget": None,
            "spent": 2,
            "remaining": 4,
        }
        for symbol, spent in (("SPY", 1), ("QQQ", 2)):  # cumulative across symbols
            doc = manifest["symbols"][symbol]
            assert doc["pages"] == 1 and doc["complete"] is True
            assert doc["request_count_cumulative"] == spent
            assert len(doc["request_urls"]) == 1
            assert all("data.alpaca.markets/v2/stocks/" in url for url in doc["request_urls"])
            assert all("feed=iex" in url and "timeframe=1Day" in url for url in doc["request_urls"])
            assert doc["expected_sessions"] == doc["row_count"] == 9
            assert doc["missing_sessions"] == [] and doc["missing_rate"] == 0.0

    def test_hashes_recomputed_from_disk_match(self, tmp_path) -> None:
        run_update(_config(tmp_path))
        manifest = json.loads(_manifest_path(tmp_path).read_text(encoding="utf-8"))
        for symbol in ("SPY", "QQQ"):
            doc = manifest["symbols"][symbol]
            data = _bars_path(tmp_path, symbol).read_bytes()
            assert doc["bars_sha256"] == sha256_hex(data)
            assert doc["bars_bytes"] == len(data)
            assert doc["row_count"] == len(data.decode("utf-8").splitlines())

    def test_every_row_passes_marketbar_contract(self, tmp_path) -> None:
        run_update(_config(tmp_path, window=DECEMBER_WINDOW))
        for symbol in ("SPY", "QQQ"):
            for line in _bars_path(tmp_path, symbol).read_text(encoding="utf-8").splitlines():
                bar = MarketBar.model_validate_json(line)
                assert bar.asset_id == symbol
                assert bar.adjustment == "RAW"
                assert bar.interval == "1Day"
                assert bar.source == TRANSPORT_LABEL_PROBE_INCREMENTAL
                assert isinstance(bar.close, Decimal) and bar.close > 0

    def test_namespace_isolation_decoy_untouched(self, tmp_path) -> None:
        decoy = tmp_path / "other" / "decoy.txt"
        decoy.parent.mkdir(parents=True)
        decoy.write_bytes(b"DECOY")
        run_update(_config(tmp_path))
        written = {p for p in tmp_path.rglob("*") if p.is_file() and p != decoy}
        assert written
        assert all(str(p).startswith(str(tmp_path / NAMESPACE_DIRNAME)) for p in written)
        assert decoy.read_bytes() == b"DECOY"

    def test_probe_artifacts_byte_deterministic(self, tmp_path) -> None:
        run_update(_config(tmp_path))
        first_manifest = _manifest_path(tmp_path).read_bytes()
        first_bars = _bars_path(tmp_path, "SPY").read_bytes()
        other = tmp_path / "rerun"
        run_update(_config(other))
        assert _manifest_path(other).read_bytes() == first_manifest
        assert _bars_path(other, "SPY").read_bytes() == first_bars

    def test_received_at_is_the_probe_fixture_fact(self, tmp_path) -> None:
        report = run_update(_config(tmp_path))
        assert report.manifest is not None
        assert report.manifest["received_at_utc"] == PROBE_RECEIVED_AT_UTC.isoformat()
        assert report.manifest["received_at_is_probe_fixture_fact"] is True

    def test_juneteenth_closed_and_next_open_rule(self, tmp_path) -> None:
        run_update(_config(tmp_path))
        spy = _rows(tmp_path, "SPY")
        events = {row["ts_event_utc"] for row in spy}
        assert "2026-06-19T20:00:00+00:00" not in events  # Juneteenth: no bar
        jun18 = [r for r in spy if r["ts_event_utc"] == "2026-06-18T20:00:00+00:00"]
        assert len(jun18) == 1
        # Thu close -> Monday open (16:00 EDT close, 09:30 EDT open)
        assert jun18[0]["ts_available_utc"] == "2026-06-22T13:30:00+00:00"

    def test_christmas_eve_half_day_and_closure(self, tmp_path) -> None:
        report = run_update(_config(tmp_path, window=DECEMBER_WINDOW))
        assert report.ok
        spy = _rows(tmp_path, "SPY")
        half = [r for r in spy if r["ts_event_utc"].startswith("2026-12-24T")]
        assert len(half) == 1
        assert half[0]["ts_event_utc"] == "2026-12-24T18:00:00+00:00"  # 13:00 EST
        assert half[0]["ts_available_utc"] == "2026-12-28T14:30:00+00:00"  # Mon open
        assert not any(r["ts_event_utc"].startswith("2026-12-25T") for r in spy)

    def test_zero_session_window_refused_before_any_request(self, tmp_path) -> None:
        # Fri 2026-12-25 (holiday) + Sat 12-26: no sessions at all
        with pytest.raises(UpdateError) as exc:
            run_update(
                _config(tmp_path, window=(dt.date(2026, 12, 25), dt.date(2026, 12, 26)))
            )
        assert exc.value.reason == "WINDOW_HAS_NO_SESSIONS"
        assert not (tmp_path / NAMESPACE_DIRNAME).exists()

    def test_supply_boundary_refused_before_any_request(self, tmp_path) -> None:
        # window through the supply's last session: the final row's
        # next-open cannot be certified inside the supply
        with pytest.raises(UpdateError) as exc:
            run_update(
                _config(tmp_path, window=(dt.date(2026, 12, 24), dt.date(2026, 12, 31)))
            )
        assert exc.value.reason == "CALENDAR_SUPPLY_BOUNDARY"
        assert not (tmp_path / NAMESPACE_DIRNAME).exists()


# ---------------------------------------------------------------------------
# default window: yesterday ET minus 10 sessions, stale-supply refusal
# ---------------------------------------------------------------------------


class TestDefaultWindow:
    def test_default_window_is_yesterday_et_minus_ten_sessions(self) -> None:
        friday_night = dt.datetime(2026, 6, 26, 20, 0, tzinfo=ET_TZ)
        start, end = resolve_default_window(_calendar(), now_et=friday_night)
        assert end == dt.date(2026, 6, 25)  # yesterday ET
        sessions = _calendar().expected_sessions(start, end)
        assert len(sessions) == DEFAULT_SESSIONS_LOOKBACK == 10
        assert sessions[-1] == end and start == dt.date(2026, 6, 11)

    def test_naive_now_refused(self) -> None:
        with pytest.raises(UpdateError) as exc:
            resolve_default_window(_calendar(), now_et=dt.datetime(2026, 6, 26, 20, 0))
        assert exc.value.reason == "BAD_CLOCK"

    def test_stale_supply_refused(self) -> None:
        later = dt.datetime(2027, 1, 6, 8, 0, tzinfo=ET_TZ)
        with pytest.raises(UpdateError) as exc:
            resolve_default_window(_calendar(), now_et=later)
        assert exc.value.reason == "CALENDAR_SUPPLY_STALE"

    def test_short_coverage_refused(self) -> None:
        tiny = build_current_supply(
            (), (), dt.date(2026, 1, 20), dt.date(2026, 1, 23),
            version="tiny-v", source_refs=("https://example.invalid/x",),
            retrieved_utc=dt.datetime(2026, 11, 27, tzinfo=UTC),
        )
        calendar = VersionedMarketCalendar.from_supply(tiny)
        with pytest.raises(UpdateError) as exc:
            resolve_default_window(
                calendar, now_et=dt.datetime(2026, 1, 24, 8, 0, tzinfo=ET_TZ)
            )
        assert exc.value.reason == "INSUFFICIENT_SESSION_HISTORY"

    def test_run_with_default_window_records_its_source(self, tmp_path) -> None:
        config = _config(
            tmp_path,
            window=resolve_default_window(
                _calendar(), now_et=dt.datetime(2026, 6, 26, 20, 0, tzinfo=ET_TZ)
            ),
            window_source=WINDOW_SOURCE_DEFAULT,
        )
        report = run_update(config)
        assert report.ok
        assert report.manifest is not None
        assert report.manifest["window"]["source"] == WINDOW_SOURCE_DEFAULT
        assert report.manifest["window"]["start"] == "2026-06-11"
        assert report.manifest["window"]["end"] == "2026-06-25"


# ---------------------------------------------------------------------------
# budget: structural cap + mid-run abort (two-phase commit)
# ---------------------------------------------------------------------------


class TestBudget:
    def test_raising_budget_beyond_structural_cap_refused(self, tmp_path) -> None:
        with pytest.raises(UpdateError) as exc:
            _config(tmp_path, budget=UPDATE_BUDGET_CAP + 1)
        assert exc.value.reason == "BAD_BUDGET"

    def test_zero_or_negative_budget_refused(self, tmp_path) -> None:
        for bad in (0, -1):
            with pytest.raises(UpdateError) as exc:
                _config(tmp_path, budget=bad)
            assert exc.value.reason == "BAD_BUDGET"

    def test_budget_exceeded_aborts_cleanly(self, tmp_path) -> None:
        # budget 1 lets SPY finish its single page and refuses QQQ's
        # request before it is sent
        report = run_update(_config(tmp_path, budget=1))
        assert not report.ok and report.status == "ABORTED"
        assert report.manifest is None and report.manifest_path is None
        assert not _manifest_path(tmp_path).exists()  # NO success marker
        assert not _bars_path(tmp_path, "SPY").exists()  # two-phase: nothing written
        assert not _bars_path(tmp_path, "QQQ").exists()
        audit_path = tmp_path / NAMESPACE_DIRNAME / UPDATE_PARTIAL_AUDIT_NAME
        assert report.partial_audit_path == audit_path and audit_path.exists()
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        assert audit["schema"] == "update_audit_partial_v1"
        assert audit["entry"] == "incremental_update"
        assert audit["status"] == "ABORTED"
        assert audit["reason"] == "REQUEST_BUDGET_EXCEEDED"
        assert "NOT sent" in audit["detail"]
        assert audit["budget"]["cap"] == 1 and audit["budget"]["spent"] == 1
        assert audit["budget"]["structural_cap"] == 6
        assert audit["symbols"]["SPY"]["status"] == "FETCHED"
        assert audit["symbols"]["QQQ"]["status"] == "REFUSED"
        assert audit["license"]["status"] == "LICENSE_UNVERIFIED"
        assert audit["admission"]["status"] == "NOT_RESEARCH_ADMITTED"

    def test_non_200_stops_immediately(self, tmp_path) -> None:
        opener = FakeAlpacaProbeTransport(calendar=_calendar(), fail_first_with_status=403)
        report = run_update(_config(tmp_path), probe_opener=opener)
        assert not report.ok and report.manifest is None
        assert opener.calls == 1, "a non-200 must stop immediately (no retry storm)"
        audit = report.partial_audit
        assert audit is not None
        assert audit["reason"] == "HTTP_STATUS"
        assert audit["request_urls_seen"] == opener.requests
        assert not _manifest_path(tmp_path).exists()
        assert (tmp_path / NAMESPACE_DIRNAME / UPDATE_PARTIAL_AUDIT_NAME).exists()


# ---------------------------------------------------------------------------
# clean-target rule: never merge into an existing snapshot directory
# ---------------------------------------------------------------------------


class TestCleanTarget:
    def test_rerun_into_same_dir_refuses_and_leaves_artifacts_intact(
        self, tmp_path
    ) -> None:
        first = run_update(_config(tmp_path))
        assert first.ok
        manifest_before = _manifest_path(tmp_path).read_bytes()
        bars_before = _bars_path(tmp_path, "SPY").read_bytes()
        with pytest.raises(UpdateError) as exc:
            run_update(_config(tmp_path))
        assert exc.value.reason == "UPDATE_TARGET_NOT_CLEAN"
        assert "future work" in exc.value.detail
        assert _manifest_path(tmp_path).read_bytes() == manifest_before
        assert _bars_path(tmp_path, "SPY").read_bytes() == bars_before

    def test_existing_collector_snapshot_refuses(self, tmp_path) -> None:
        (tmp_path / NAMESPACE_DIRNAME).mkdir(parents=True)
        (tmp_path / NAMESPACE_DIRNAME / COLLECTION_MANIFEST_NAME).write_text("{}", encoding="utf-8")
        with pytest.raises(UpdateError) as exc:
            run_update(_config(tmp_path))
        assert exc.value.reason == "UPDATE_TARGET_NOT_CLEAN"
        assert COLLECTION_MANIFEST_NAME in exc.value.detail

    def test_existing_bars_file_only_refuses(self, tmp_path) -> None:
        (tmp_path / NAMESPACE_DIRNAME / "SPY").mkdir(parents=True)
        (tmp_path / NAMESPACE_DIRNAME / "SPY" / "bars.jsonl").write_text("", encoding="utf-8")
        with pytest.raises(UpdateError) as exc:
            run_update(_config(tmp_path))
        assert exc.value.reason == "UPDATE_TARGET_NOT_CLEAN"


# ---------------------------------------------------------------------------
# config refusals
# ---------------------------------------------------------------------------


class TestConfigRefusals:
    def test_universe_pins_match_the_collector(self, tmp_path) -> None:
        for bad in (("SPY",), ("SPY", "SPY"), ("SPY", "AAPL")):
            with pytest.raises(UpdateError) as exc:
                UpdateConfig(
                    symbols=bad,
                    start=JUNE_WINDOW[0],
                    end=JUNE_WINDOW[1],
                    output_dir=tmp_path,
                    calendar_supply=_supply(),
                )
            assert exc.value.reason == "UNIVERSE_MISMATCH"

    def test_window_outside_supply_coverage_refused(self, tmp_path) -> None:
        with pytest.raises(UpdateError) as exc:
            _config(tmp_path, window=(dt.date(2027, 2, 2), dt.date(2027, 2, 6)))
        assert exc.value.reason == "OUTSIDE_CALENDAR_COVERAGE"

    def test_non_supply_calendar_refused(self, tmp_path) -> None:
        with pytest.raises(UpdateError) as exc:
            UpdateConfig(
                symbols=("SPY", "QQQ"),
                start=JUNE_WINDOW[0],
                end=JUNE_WINDOW[1],
                output_dir=tmp_path,
                calendar_supply="configs/current_calendar.yaml",  # type: ignore[arg-type]
            )
        assert exc.value.reason == "BAD_CALENDAR_SUPPLY"

    def test_bad_window_source_refused(self, tmp_path) -> None:
        with pytest.raises(UpdateError) as exc:
            _config(tmp_path, window_source="guessed")
        assert exc.value.reason == "BAD_WINDOW_SOURCE"

    def test_inverted_window_refused(self, tmp_path) -> None:
        with pytest.raises(UpdateError) as exc:
            _config(tmp_path, window=(JUNE_WINDOW[1], JUNE_WINDOW[0]))
        assert exc.value.reason == "BAD_WINDOW"


# ---------------------------------------------------------------------------
# live transport: fail-closed refusals, blind env, scope matching
# ---------------------------------------------------------------------------


class TestLiveGate:
    def test_live_without_signature_refused_value_never_echoed(self) -> None:
        with pytest.raises(AuthorizationRefused) as exc:
            resolve_update_authorization(
                "live",
                symbols=("SPY", "QQQ"),
                start=JUNE_WINDOW[0],
                end=JUNE_WINDOW[1],
                budget=6,
                environ={},
                authorization_record=None,
            )
        assert exc.value.reason == "LIVE_AUTHORIZATION_REFUSED"
        assert AUTH_ENV_VAR in str(exc.value)
        with pytest.raises(AuthorizationRefused) as exc:
            resolve_update_authorization(
                "live",
                symbols=("SPY", "QQQ"),
                start=JUNE_WINDOW[0],
                end=JUNE_WINDOW[1],
                budget=6,
                environ={AUTH_ENV_VAR: "OPERATOR_SECRET_TOKEN"},
                authorization_record=None,
            )
        assert "OPERATOR_SECRET_TOKEN" not in str(exc.value)

    def test_signed_without_record_refused(self) -> None:
        with pytest.raises(AuthorizationRefused) as exc:
            resolve_update_authorization(
                "live",
                symbols=("SPY", "QQQ"),
                start=JUNE_WINDOW[0],
                end=JUNE_WINDOW[1],
                budget=6,
                environ={AUTH_ENV_VAR: "SIGNED"},
                authorization_record=None,
            )
        assert exc.value.reason == "LIVE_AUTHORIZATION_RECORD_REQUIRED"
        assert "does NOT extend" in str(exc.value)

    def test_scope_mismatch_names_the_field(self) -> None:
        record = parse_authorization_record(
            {
                "authorization_ref": "R",
                "attested_by": "operator",
                "attested_at": "2026-11-27T09:00:00+00:00",
                "scope": {
                    "symbols": ["SPY", "QQQ"],
                    "start": "2026-06-15",
                    "end": "2026-06-26",
                    "budget": 6,
                },
            },
            source="unit",
        )
        for field, kwargs in (
            ("start", {"start": dt.date(2026, 6, 2)}),
            ("end", {"end": dt.date(2026, 6, 27)}),
            ("symbols", {"symbols": ("QQQ", "SPY", "AAPL")}),
            ("budget", {"budget": 7}),  # requested above the record's 6
        ):
            request = {
                "symbols": ("SPY", "QQQ"),
                "start": JUNE_WINDOW[0],
                "end": JUNE_WINDOW[1],
                "budget": 6,
            }
            request.update(kwargs)
            with pytest.raises(AuthorizationRefused) as exc:
                resolve_update_authorization(
                    "live",
                    environ={AUTH_ENV_VAR: "SIGNED"},
                    authorization_record=record,
                    **request,
                )
            assert exc.value.reason == "AUTHORIZATION_SCOPE_MISMATCH"
            assert field in str(exc.value)

    def test_record_budget_above_structural_cap_invalid(self) -> None:
        with pytest.raises(AuthorizationRefused) as exc:
            parse_authorization_record(
                {
                    "authorization_ref": "R",
                    "attested_by": "operator",
                    "attested_at": "2026-11-27T09:00:00+00:00",
                    "scope": {
                        "symbols": ["SPY", "QQQ"],
                        "start": "2026-06-15",
                        "end": "2026-06-26",
                        "budget": UPDATE_BUDGET_CAP + 1,
                    },
                },
                source="unit",
            )
        assert "structural" in str(exc.value)

    @pytest.mark.parametrize(
        "mutation",
        [
            {"authorization_ref": ""},
            {"attested_by": ""},
            {"attested_at": "not-a-timestamp"},
            {"attested_at": "2026-11-27T09:00:00"},  # naive
            {"scope": {"symbols": [], "start": "2026-06-15", "end": "2026-06-26", "budget": 6}},
            {"scope": {"symbols": ["SPY", "QQQ"], "start": "2026-06-26", "end": "2026-06-15", "budget": 6}},
            {"scope": {"symbols": ["SPY", "QQQ"], "start": "2026-06-15", "end": "2026-06-26", "budget": "6"}},
            {"extra_key": 1},
        ],
    )
    def test_malformed_records_refused(self, mutation) -> None:
        doc = {
            "authorization_ref": "R",
            "attested_by": "operator",
            "attested_at": "2026-11-27T09:00:00+00:00",
            "scope": {
                "symbols": ["SPY", "QQQ"],
                "start": "2026-06-15",
                "end": "2026-06-26",
                "budget": 6,
            },
        }
        if "scope" in mutation:
            doc["scope"] = mutation["scope"]
        else:
            doc.update(mutation)
        with pytest.raises(AuthorizationRefused) as exc:
            parse_authorization_record(doc, source="unit")
        assert exc.value.reason == "AUTHORIZATION_RECORD_INVALID"

    def test_full_gate_passes_without_credential_values_leaking(self, tmp_path) -> None:
        record_path = _auth_record(tmp_path)
        record = load_authorization_record(record_path)
        auth = resolve_update_authorization(
            "live",
            symbols=("SPY", "QQQ"),
            start=JUNE_WINDOW[0],
            end=JUNE_WINDOW[1],
            budget=6,
            environ=LIVE_ENV,
            authorization_record=record,
        )
        assert auth.transport == "live" and auth.label == "LIVE"
        assert auth.authorization_ref == "AUTH-CUR-2026-001"
        assert auth.credential_env_visible == ("APCA_API_KEY_ID", "APCA_API_SECRET_KEY")
        leak = repr(auth) + str(auth)
        assert "KEY-VALUE-MUST-NOT-LEAK" not in leak
        assert "SECRET-VALUE-MUST-NOT-LEAK" not in leak

    def test_signed_and_recorded_but_credentials_missing_blocked(self, tmp_path) -> None:
        record = parse_authorization_record(
            json.loads(_auth_record(tmp_path).read_text(encoding="utf-8")),
            source="unit",
        )
        with pytest.raises(BlockedEnv) as exc:
            resolve_update_authorization(
                "live",
                symbols=("SPY", "QQQ"),
                start=JUNE_WINDOW[0],
                end=JUNE_WINDOW[1],
                budget=6,
                environ={AUTH_ENV_VAR: "SIGNED"},
                authorization_record=record,
            )
        assert exc.value.reason == "LIVE_BLOCKED_ENV"
        assert "APCA_API_KEY_ID" in str(exc.value)

    def test_probe_needs_no_authorization(self) -> None:
        auth = resolve_update_authorization(
            "probe",
            symbols=("SPY", "QQQ"),
            start=JUNE_WINDOW[0],
            end=JUNE_WINDOW[1],
            budget=6,
            environ={},
            authorization_record=None,
        )
        assert auth.label == TRANSPORT_LABEL_PROBE_INCREMENTAL

    def test_record_file_problems_never_downgrade_to_probe(self, tmp_path) -> None:
        missing = tmp_path / "nope.json"
        with pytest.raises(AuthorizationRefused) as exc:
            load_authorization_record(missing)
        assert exc.value.reason == "AUTHORIZATION_RECORD_UNREADABLE"
        broken = tmp_path / "broken.json"
        broken.write_text("{not json", encoding="utf-8")
        with pytest.raises(AuthorizationRefused) as exc:
            load_authorization_record(broken)
        assert exc.value.reason == "AUTHORIZATION_RECORD_INVALID"

    def test_live_scope_mismatch_via_run_writes_nothing(self, tmp_path) -> None:
        record_path = _auth_record(tmp_path, end=dt.date(2026, 6, 27))  # != window
        config = UpdateConfig(
            symbols=("SPY", "QQQ"),
            start=JUNE_WINDOW[0],
            end=JUNE_WINDOW[1],
            output_dir=tmp_path / "out",
            calendar_supply=_supply(),
            transport="live",
            authorization_record=load_authorization_record(record_path),
        )
        with pytest.raises(AuthorizationRefused) as exc:
            run_update(config, environ={AUTH_ENV_VAR: "SIGNED"})
        assert exc.value.reason == "AUTHORIZATION_SCOPE_MISMATCH"
        assert not (tmp_path / "out" / NAMESPACE_DIRNAME).exists()


# ---------------------------------------------------------------------------
# CLI surface
# ---------------------------------------------------------------------------


class TestCli:
    def test_probe_happy_path(self, tmp_path, capsys) -> None:
        cli = _cli()
        code = cli.main(
            ["--symbol", "SPY", "--symbol", "QQQ", "--output-dir", str(tmp_path)],
            environ={},
        )
        assert code == cli.EXIT_OK == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["status"] == "COLLECTED"
        assert payload["transport"]["label"] == TRANSPORT_LABEL_PROBE_INCREMENTAL
        assert payload["window"]["source"] == WINDOW_SOURCE_DEFAULT  # default window
        assert _manifest_path(tmp_path).exists()

    def test_cli_default_window_matches_yesterday_et_rule(self, tmp_path, capsys) -> None:
        cli = _cli()
        now_et = dt.datetime(2026, 6, 26, 20, 0, tzinfo=ET_TZ)
        code = cli.main(
            ["--symbol", "SPY", "--symbol", "QQQ", "--output-dir", str(tmp_path)],
            environ={},
            now_et=now_et,
        )
        assert code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["window"]["start"] == "2026-06-11"
        assert payload["window"]["end"] == "2026-06-25"

    def test_explicit_window_via_cli(self, tmp_path, capsys) -> None:
        cli = _cli()
        code = cli.main(
            [
                "--symbol", "SPY", "--symbol", "QQQ",
                "--output-dir", str(tmp_path),
                "--start", "2026-06-15", "--end", "2026-06-26",
            ],
            environ={},
        )
        assert code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["window"]["source"] == WINDOW_SOURCE_EXPLICIT
        assert payload["symbols"]["SPY"]["row_count"] == 9

    def test_single_symbol_refused(self, tmp_path, capsys) -> None:
        cli = _cli()
        code = cli.main(
            ["--symbol", "SPY", "--output-dir", str(tmp_path)], environ={}
        )
        assert code == cli.EXIT_CONFIG_REFUSED == 2
        assert "UNIVERSE_MISMATCH" in capsys.readouterr().out
        assert not (tmp_path / NAMESPACE_DIRNAME).exists()

    def test_start_without_end_refused(self, tmp_path, capsys) -> None:
        cli = _cli()
        code = cli.main(
            [
                "--symbol", "SPY", "--symbol", "QQQ",
                "--output-dir", str(tmp_path),
                "--start", "2026-06-15",
            ],
            environ={},
        )
        assert code == 2
        assert "BAD_WINDOW" in capsys.readouterr().out

    def test_bad_date_format_refused(self, tmp_path, capsys) -> None:
        cli = _cli()
        code = cli.main(
            [
                "--symbol", "SPY", "--symbol", "QQQ",
                "--output-dir", str(tmp_path),
                "--start", "06/15/2026", "--end", "2026-06-26",
            ],
            environ={},
        )
        assert code == 2
        assert "CONFIG_REFUSED" in capsys.readouterr().out

    def test_window_outside_coverage_refused(self, tmp_path, capsys) -> None:
        cli = _cli()
        code = cli.main(
            [
                "--symbol", "SPY", "--symbol", "QQQ",
                "--output-dir", str(tmp_path),
                "--start", "2027-02-02", "--end", "2027-02-06",
            ],
            environ={},
        )
        assert code == 2
        assert "OUTSIDE_CALENDAR_COVERAGE" in capsys.readouterr().out
        assert not (tmp_path / NAMESPACE_DIRNAME).exists()

    def test_budget_above_cap_refused(self, tmp_path, capsys) -> None:
        cli = _cli()
        code = cli.main(
            [
                "--symbol", "SPY", "--symbol", "QQQ",
                "--output-dir", str(tmp_path),
                "--budget", str(UPDATE_BUDGET_CAP + 1),
            ],
            environ={},
        )
        assert code == 2
        assert "BAD_BUDGET" in capsys.readouterr().out

    def test_missing_calendar_config_refused(self, tmp_path, capsys) -> None:
        cli = _cli()
        code = cli.main(
            [
                "--symbol", "SPY", "--symbol", "QQQ",
                "--output-dir", str(tmp_path),
                "--calendar-config", str(tmp_path / "nope.yaml"),
            ],
            environ={},
        )
        assert code == 2
        assert "CALENDAR_CONFIG" in capsys.readouterr().out

    def test_drifted_calendar_config_refused(self, tmp_path, capsys) -> None:
        drifted = tmp_path / "drifted.yaml"
        drifted.write_text(
            (CONFIG_PATH.read_text(encoding="utf-8"))
            .replace('"2026-01-19"', '"2026-01-20"'),
            encoding="utf-8",
        )
        cli = _cli()
        code = cli.main(
            [
                "--symbol", "SPY", "--symbol", "QQQ",
                "--output-dir", str(tmp_path / "out"),
                "--calendar-config", str(drifted),
            ],
            environ={},
        )
        assert code == 2
        assert "CALENDAR_SUPPLY_DRIFT" in capsys.readouterr().out
        assert not (tmp_path / "out" / NAMESPACE_DIRNAME).exists()

    def test_live_refused_without_anything_writes_nothing(self, tmp_path, capsys) -> None:
        cli = _cli()
        code = cli.main(
            [
                "--symbol", "SPY", "--symbol", "QQQ",
                "--output-dir", str(tmp_path),
                "--transport", "live",
            ],
            environ={},
        )
        assert code == cli.EXIT_AUTHORIZATION_REFUSED == 4
        assert "LIVE_AUTHORIZATION_REFUSED" in capsys.readouterr().out
        assert not (tmp_path / NAMESPACE_DIRNAME).exists()

    def test_live_signed_without_record_refused(self, tmp_path, capsys) -> None:
        cli = _cli()
        code = cli.main(
            [
                "--symbol", "SPY", "--symbol", "QQQ",
                "--output-dir", str(tmp_path),
                "--transport", "live",
            ],
            environ={AUTH_ENV_VAR: "SIGNED"},
        )
        assert code == 4
        assert "LIVE_AUTHORIZATION_RECORD_REQUIRED" in capsys.readouterr().out

    def test_live_record_scope_mismatch_refused(self, tmp_path, capsys) -> None:
        record_path = _auth_record(tmp_path, budget=3)  # requested 6 > record 3
        cli = _cli()
        code = cli.main(
            [
                "--symbol", "SPY", "--symbol", "QQQ",
                "--output-dir", str(tmp_path / "out"),
                "--transport", "live",
                "--authorization-record", str(record_path),
            ],
            environ={AUTH_ENV_VAR: "SIGNED"},
        )
        assert code == 4
        assert "AUTHORIZATION_SCOPE_MISMATCH" in capsys.readouterr().out
        assert not (tmp_path / "out" / NAMESPACE_DIRNAME).exists()

    def test_live_blocked_env_maps_to_exit_3(self, tmp_path, capsys) -> None:
        record_path = _auth_record(tmp_path)
        cli = _cli()
        code = cli.main(
            [
                "--symbol", "SPY", "--symbol", "QQQ",
                "--output-dir", str(tmp_path / "out"),
                "--start", "2026-06-15", "--end", "2026-06-26",
                "--transport", "live",
                "--authorization-record", str(record_path),
            ],
            environ={AUTH_ENV_VAR: "SIGNED"},  # no APCA-* names
        )
        assert code == cli.EXIT_BLOCKED_ENV == 3
        assert "BLOCKED_ENV" in capsys.readouterr().out

    def test_abort_maps_to_exit_5(self, tmp_path, capsys, monkeypatch) -> None:
        cli = _cli()
        audit_path = tmp_path / NAMESPACE_DIRNAME / UPDATE_PARTIAL_AUDIT_NAME
        stub = UpdateReport(
            status="ABORTED",
            manifest=None,
            partial_audit={
                "reason": "REQUEST_BUDGET_EXCEEDED",
                "detail": "stopped",
                "budget": {"spent": 2},
            },
            manifest_path=None,
            partial_audit_path=audit_path,
            bars_paths=(),
        )
        monkeypatch.setattr(cli, "run_update", lambda *a, **k: stub)
        code = cli.main(
            ["--symbol", "SPY", "--symbol", "QQQ", "--output-dir", str(tmp_path)],
            environ={},
        )
        assert code == cli.EXIT_UPDATE_ABORTED == 5
        payload = json.loads(capsys.readouterr().out)
        assert payload["manifest_written"] is False


@functools.lru_cache(maxsize=1)
def _cli():
    spec = importlib.util.spec_from_file_location(
        "update_market_data_cli",
        REPO_ROOT / "scripts" / "update_market_data.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-q"]))
