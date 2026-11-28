"""FROZEN NYSE calendar supply for the H1 restricted-ETF research window
(2017-01-01 .. 2025-12-31) plus the required next trading day boundary
(Fri 2026-01-02; window extends to 2026-01-31).

Provenance (assembled 2026-11-27; every date below was verified against
an archived OFFICIAL NYSE holiday-calendar page or an ICE/NYSE press
release — snapshot URL + original URL + verbatim quotes are recorded in
``artifacts/evidence/M3-H/h1b/calendar/frozen-supply-record.json``):

- 2017/2018/2019: Wayback snapshot 2017-06-02 of
  https://www.nyse.com/markets/hours-calendars
- 2020/2021: snapshots 2020-05-30, 2021-03-04, 2021-06-30
- 2022/2023/2024: snapshots 2022-06-01, 2022-12-04, 2022-12-19
- 2025 (+2026 column): snapshot 2025-03-05; 2026 boundary re-confirmed
  by snapshot 2026-01-09 of https://www.nyse.com/trade/hours-calendars
  and the live page (fetched 2026-11-27)
- 2018-12-05 national day of mourning (President G.H.W. Bush): ICE/NYSE
  press release ir.theice.com/press/press-releases/all-categories/2018/
  12-01-2018-171457429 (announced 2018-12-01; not on pre-published
  calendars), corroborated by ISDA guidance note
- Special-case findings frozen with the supply: Juneteenth observed from
  2022 (NOT 2021); NO July early close in 2020/2021; Christmas Eve
  early closes only 2018/2019/2020/2024/2025 (none 2017/2021/2022/2023);
  New Year's observed 2017-01-02 and 2023-01-02, NOT observed for 2022
  (NYSE Rule 7.2); 2021 Christmas observed Friday 2021-12-24 (full
  closure); 2022 Christmas observed Monday 2022-12-26.

LICENSE CAVEAT (recorded, not hidden): the ICE/NYSE website terms of use
(https://www.ice.com/privacy-security-center/terms-of-use, fetched
2026-11-27) grant personal, non-commercial download/print use but
prohibit systematic collection/compilation into datasets and automated
extraction, with a revocable license and no explicit caching provision.
``LICENSE_UNVERIFIED`` — this supply may drive ENGINEERING verification
this round; real-research usability requires the operator's own license
review. This is separate from, and never substitutes, the Alpaca data
license attestation (H1 draft remains unsigned).

## v2 addendum (2026-11-27, BUSINESS-MVP-V02-REAL-HISTORY workflow A1)

Two hard errors were found in the v1 table above AFTER its freeze; v2
below folds them in as the corrected frozen supply. v1 is preserved
UNCHANGED above (constants, hash, docstring) as evidence — including
its wrong dates and its defective hash; the v1->v2 delta is exactly:

- 2025-01-09 (Thursday) ADDED — NYSE closed, National Day of Mourning
  for former President Jimmy Carter. Official source: ICE/NYSE press
  release https://ir.theice.com/press/news-details/2024/The-New-York-Stock-Exchange-Will-Close-Markets-on-January-9-to-Honor-the-Passing-of-Former-President-Jimmy-Carter-on-National-Day-of-Mourning/default.aspx
- 2026-01-19 (Monday) ADDED — NYSE closed, Martin Luther King Jr. Day.
  Official sources: NYSE holidays calendar
  https://www.nyse.com/trade/hours-calendars and the ICE/NYSE
  2024-2025-and-2026 holiday & early-closings calendar press release
  https://ir.theice.com/press/news-details/2023/NYSE-Group-Announces-2024-2025-and-2026-Holiday-and-Early-Closings-Calendar/default.aspx

No other holiday, half-day, or window field changes. The LICENSE
CAVEAT above carries over to v2 unchanged in spirit: personal-use
website terms are NOT a dataset license (``LICENSE_UNVERIFIED``);
real-research usability still requires the operator's own license
review, separate from the Alpaca data-license attestation.

## current-supply addendum (2026-11-27, BUSINESS-V03-OPERATIONAL-ACTIVATION T3-B)

The frozen supplies above END at 2026-01-31; a daily run at a later
asof date needs a CURRENT calendar covering warmup, the trading day
and the next execution session. That calendar is SUPPLIED DATA the
operator maintains from a licensed source — it is never inferred from
data gaps and never replaces the frozen v1/v2 records above.

``build_current_supply(...)`` constructs one from an explicit
holiday/half-day table; ``load_supply_from_config(path)`` reads the
operator-maintained YAML file (``configs/current_calendar.yaml``),
whose shape is EXACTLY (no other keys — unknown keys refuse):

    version: <non-empty string>
    valid_from: <YYYY-MM-DD>
    valid_until: <YYYY-MM-DD>        # strict: valid_from < valid_until
    holidays: [<YYYY-MM-DD>, ...]    # sorted ascending, unique, weekdays
    half_days: [<YYYY-MM-DD>, ...]   # sorted ascending, unique, weekdays
    license_note: <non-empty string> # LICENSE_UNVERIFIED placeholder allowed, must be stated
    source_refs: [<string>, ...]     # non-empty; first must be an http(s) URL

Fail-closed: unknown keys, missing fields, unsorted/duplicate date
lists, weekend entries, an inverted/equal window and an empty
version/license note are all refused at load. Any current supply whose
window overlaps the frozen v2 supply is additionally checked for
CONSISTENCY over the overlap (e.g. 2026-01-19 MLK must match v2's
fixed date): contradicting the frozen record on any session/half-day
classification is ``CALENDAR_SUPPLY_DRIFT`` and refuses. A current
supply carries whatever license the operator stated — a stated
``LICENSE_UNVERIFIED`` is recorded verbatim, never upgraded.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

import yaml

from ..security.canonical import canonical_json_bytes, sha256_hex
from .calendar import CalendarError, MarketCalendar, SessionInfo
from .historical_calendar import CalendarSupply

__all__ = [
    "NYSE_2017_2025_SUPPLY",
    "NYSE_2017_2025_SUPPLY_V2",
    "FROZEN_SUPPLY_HASH",
    "FROZEN_SUPPLY_HASH_V2",
    "frozen_supply_hash",
    "SUPPLY_SOURCE_REFS",
    "SUPPLY_SOURCE_REFS_V2",
    "CURRENT_CALENDAR_CONFIG_KEYS",
    "CalendarConfigError",
    "CalendarSupplyDriftError",
    "LICENSE_UNVERIFIED_NOTE",
    "build_current_supply",
    "load_supply_from_config",
]


def _d(iso: str) -> dt.date:
    return dt.date.fromisoformat(iso)


_HOLIDAYS = frozenset(
    _d(x)
    for x in (
        # 2017
        "2017-01-02", "2017-01-16", "2017-02-20", "2017-04-14", "2017-05-29",
        "2017-07-04", "2017-09-04", "2017-11-23", "2017-12-25",
        # 2018 (incl. 12-05 national day of mourning)
        "2018-01-01", "2018-01-15", "2018-02-19", "2018-03-30", "2018-05-28",
        "2018-07-04", "2018-09-03", "2018-11-22", "2018-12-05", "2018-12-25",
        # 2019
        "2019-01-01", "2019-01-21", "2019-02-18", "2019-04-19", "2019-05-27",
        "2019-07-04", "2019-09-02", "2019-11-28", "2019-12-25",
        # 2020
        "2020-01-01", "2020-01-20", "2020-02-17", "2020-04-10", "2020-05-25",
        "2020-07-03", "2020-09-07", "2020-11-26", "2020-12-25",
        # 2021
        "2021-01-01", "2021-01-18", "2021-02-15", "2021-04-02", "2021-05-31",
        "2021-07-05", "2021-09-06", "2021-11-25", "2021-12-24",
        # 2022
        "2022-01-17", "2022-02-21", "2022-04-15", "2022-05-30", "2022-06-20",
        "2022-07-04", "2022-09-05", "2022-11-24", "2022-12-26",
        # 2023
        "2023-01-02", "2023-01-16", "2023-02-20", "2023-04-07", "2023-05-29",
        "2023-06-19", "2023-07-04", "2023-09-04", "2023-11-23", "2023-12-25",
        # 2024
        "2024-01-01", "2024-01-15", "2024-02-19", "2024-03-29", "2024-05-27",
        "2024-06-19", "2024-07-04", "2024-09-02", "2024-11-28", "2024-12-25",
        # 2025
        "2025-01-01", "2025-01-20", "2025-02-17", "2025-04-18", "2025-05-26",
        "2025-06-19", "2025-07-04", "2025-09-01", "2025-11-27", "2025-12-25",
        # 2026 boundary
        "2026-01-01",
    )
)

_HALF_DAYS = frozenset(
    _d(x)
    for x in (
        "2017-07-03", "2017-11-24",
        "2018-07-03", "2018-11-23", "2018-12-24",
        "2019-07-03", "2019-11-29", "2019-12-24",
        "2020-11-27", "2020-12-24",
        "2021-11-26",
        "2022-11-25",
        "2023-07-03", "2023-11-24",
        "2024-07-03", "2024-11-29", "2024-12-24",
        "2025-07-03", "2025-11-28", "2025-12-24",
    )
)

NYSE_2017_2025_SUPPLY = CalendarSupply(
    version="nyse-2017-2026-01-frozen-v1",
    source=(
        "NYSE official holiday calendars (Wayback-archived nyse.com pages, "
        "2017-2025) + ICE/NYSE press release for the 2018-12-05 national day "
        "of mourning — LICENSE_UNVERIFIED (ICE website terms "
        "ambiguous-to-restrictive for systematic collection/caching; "
        "personal-research usability requires operator license review)"
    ),
    source_url="https://www.nyse.com/markets/hours-calendars (archived snapshots; see SUPPLY_SOURCE_REFS)",
    retrieved_utc=dt.datetime(2026, 11, 27, tzinfo=dt.timezone.utc),
    valid_from=dt.date(2017, 1, 1),
    valid_until=dt.date(2026, 1, 31),
    holidays=_HOLIDAYS,
    half_days=_HALF_DAYS,
)

#: per-year source provenance (snapshot URLs + retrieval date; verbatim
#: quotes live in artifacts/evidence/M3-H/h1b/calendar/)
SUPPLY_SOURCE_REFS = {
    "2017_2018_2019": "https://web.archive.org/web/20170602092600/https://www.nyse.com/markets/hours-calendars",
    "2020_2021": "https://web.archive.org/web/20200530191718/https://www.nyse.com/markets/hours-calendars",
    "2021_crosscheck": [
        "https://web.archive.org/web/20210304140048/https://www.nyse.com/markets/hours-calendars",
        "https://web.archive.org/web/20210630220654/https://www.nyse.com/markets/hours-calendars",
    ],
    "2022_2023_2024": [
        "https://web.archive.org/web/20220601133900/https://www.nyse.com/markets/hours-calendars",
        "https://web.archive.org/web/20221204100459/https://www.nyse.com/markets/hours-calendars",
        "https://web.archive.org/web/20221219222145/https://www.nyse.com/markets/hours-calendars",
    ],
    "2025_2026": [
        "https://web.archive.org/web/20250305025600/https://www.nyse.com/markets/hours-calendars",
        "https://web.archive.org/web/20260109170436/https://www.nyse.com/trade/hours-calendars",
        "https://www.nyse.com/trade/hours-calendars (live, fetched 2026-11-27)",
    ],
    "2018-12-05_mourning": "https://ir.theice.com/press/press-releases/all-categories/2018/12-01-2018-171457429",
    "2018-12-05_corroboration": "https://www.isda.org/a/rRFEE/George-H-W-Bush-national-day-of-mourning-on-December-5-2018-ISDA-guidance2.pdf",
    "terms_of_use": "https://www.ice.com/privacy-security-center/terms-of-use (LICENSE_UNVERIFIED)",
    "retrieved_utc": "2026-11-27T00:00:00+00:00",
}


def frozen_supply_hash(supply: CalendarSupply) -> str:
    """SHA-256 over the canonical form of the supply's frozen fields —
    any single-date change (or source/window/version change) changes the
    hash, so the frozen record is tamper-evident."""
    payload = {
        "version": supply.version,
        "valid_from": supply.valid_from.isoformat(),
        "valid_until": supply.valid_until.isoformat(),
        "holidays": sorted(d.isoformat() for d in supply.holidays),
        "half_days": sorted(d.isoformat() for d in supply.half_days),
    }
    return sha256_hex(canonical_json_bytes(payload))


#: computed at freeze time (2026-11-27); re-verified by
#: tests/m3_h/test_h1b_calendar_freeze.py. A changed value means the
#: supply dates or scope drifted — refuse and re-verify sources.
FROZEN_SUPPLY_HASH = "826bd96a08b18ada69f77010fa2006516f5088d69a8fb1ceec44033ec106e285"


# ---------------------------------------------------------------------------
# v2 — corrected frozen supply (BUSINESS-MVP-V02-REAL-HISTORY workflow A1,
# 2026-11-27). Everything above this line is the preserved v1 record; the
# only v1->v2 delta is the two added holidays documented in the docstring
# addendum. Hashed with the same frozen_supply_hash function (same canonical
# payload shape), so v1 and v2 hashes are directly comparable evidence.
# ---------------------------------------------------------------------------

#: the two v1 hard errors, now included as holidays
_V2_ADDED_HOLIDAYS = (_d("2025-01-09"), _d("2026-01-19"))

_HOLIDAYS_V2 = frozenset(_HOLIDAYS | set(_V2_ADDED_HOLIDAYS))

#: v2 provenance: v1's refs plus the two official correction sources
SUPPLY_SOURCE_REFS_V2 = {
    **SUPPLY_SOURCE_REFS,
    "2025-01-09_carter_mourning": (
        "https://ir.theice.com/press/news-details/2024/"
        "The-New-York-Stock-Exchange-Will-Close-Markets-on-January-9-to-Honor-"
        "the-Passing-of-Former-President-Jimmy-Carter-on-National-Day-of-"
        "Mourning/default.aspx"
    ),
    "2026-01-19_mlk": [
        "https://www.nyse.com/trade/hours-calendars",
        "https://ir.theice.com/press/news-details/2023/NYSE-Group-Announces-"
        "2024-2025-and-2026-Holiday-and-Early-Closings-Calendar/default.aspx",
    ],
    "v2_delta_record": (
        "v1 -> v2 adds exactly {2025-01-09, 2026-01-19} to holidays; "
        "half_days, window and sources otherwise unchanged; v1 preserved "
        "as evidence with its defective FROZEN_SUPPLY_HASH"
    ),
}

NYSE_2017_2025_SUPPLY_V2 = CalendarSupply(
    version="nyse-2017-2026-01-frozen-v2",
    source=(
        "NYSE official holiday calendars (Wayback-archived nyse.com pages, "
        "2017-2025) + ICE/NYSE press releases for the two closures v1 "
        "missed (2025-01-09 Carter national day of mourning; 2026-01-19 "
        "MLK Day) — LICENSE_UNVERIFIED (ICE website terms "
        "ambiguous-to-restrictive for systematic collection/caching; "
        "personal-research usability requires operator license review)"
    ),
    source_url="https://www.nyse.com/trade/hours-calendars (see SUPPLY_SOURCE_REFS_V2)",
    retrieved_utc=dt.datetime(2026, 11, 27, tzinfo=dt.timezone.utc),
    valid_from=dt.date(2017, 1, 1),
    valid_until=dt.date(2026, 1, 31),
    holidays=_HOLIDAYS_V2,
    half_days=_HALF_DAYS,
)

#: computed at v2 freeze time (2026-11-27); re-verified by
#: tests/m3_h/test_calendar_supply_v2.py. A changed value means the v2
#: dates or scope drifted — refuse and re-verify sources. v1's
#: FROZEN_SUPPLY_HASH above stays the pinned evidence of the defective
#: table and must never be "fixed".
FROZEN_SUPPLY_HASH_V2 = (
    "bd06be2f355cbe984a0cdfa58d5f071719cb9b52647ffc0c19d59e64138d8067"
)


# ---------------------------------------------------------------------------
# CURRENT-supply constructor (BUSINESS-V03-OPERATIONAL-ACTIVATION T3-B,
# 2026-11-27): operator-supplied current-year calendars (2026+). The frozen
# v1/v2 records above are preserved evidence; nothing below modifies them.
# ---------------------------------------------------------------------------

#: the license placeholder a current supply MUST state until the operator
#: has verified the calendar source's license for dataset use — a default
#: is allowed, but it is never silent: it is recorded verbatim in the
#: supply's source field.
LICENSE_UNVERIFIED_NOTE = "LICENSE_UNVERIFIED"

#: the exact YAML key set ``load_supply_from_config`` accepts (closed world)
CURRENT_CALENDAR_CONFIG_KEYS = frozenset(
    {
        "version",
        "valid_from",
        "valid_until",
        "holidays",
        "half_days",
        "license_note",
        "source_refs",
    }
)


class CalendarConfigError(ValueError):
    """The operator's current-calendar config file is missing, malformed
    or incomplete (fail-closed — no supply is ever half-built from it)."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


class CalendarSupplyDriftError(ValueError):
    """A current supply contradicts the frozen v2 supply inside the
    overlap of the two windows — two supplies that disagree about the
    same date are drift, not options (fail-closed)."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


def _require_unique_weekday_entries(
    days: Iterable[dt.date], name: str
) -> tuple[dt.date, ...]:
    """Uniqueness + weekday guards for one operator-supplied date list.
    (Sorting is enforced on the YAML list in ``load_supply_from_config``;
    programmatic callers may pass any order — the supply stores a set.)"""
    normalized: list[dt.date] = []
    seen: set[dt.date] = set()
    for day in days:
        if isinstance(day, dt.datetime) or not isinstance(day, dt.date):
            raise CalendarError(
                f"current supply {name} entry {day!r} is not a calendar date"
            )
        if day in seen:
            raise CalendarError(
                f"current supply duplicate {name} entry {day.isoformat()}"
            )
        seen.add(day)
        if day.weekday() >= 5:
            raise CalendarError(
                f"current supply {name} {day.isoformat()} falls on a weekend "
                "(redundant entry — weekends are non-trading by construction)"
            )
        normalized.append(day)
    return tuple(normalized)


def build_current_supply(
    holidays: Iterable[dt.date],
    half_days: Iterable[dt.date],
    valid_from: dt.date,
    valid_until: dt.date,
    *,
    version: str,
    license_note: str = LICENSE_UNVERIFIED_NOTE,
    source_refs: Sequence[str],
    retrieved_utc: dt.datetime | None = None,
) -> CalendarSupply:
    """Construct an OPERATOR-SUPPLIED CURRENT calendar supply (2026+)
    from an explicit holiday/half-day table the operator maintains from a
    licensed source. The v1/v2 frozen constants above are untouched.

    Validation (fail-closed, before any object is returned): non-empty
    ``version``; a stated, non-empty ``license_note`` (the default is the
    stated ``LICENSE_UNVERIFIED`` placeholder — recorded verbatim, never
    upgraded); at least one non-empty ``source_refs`` entry whose FIRST
    entry is an http(s) URL (it becomes the supply's ``source_url``); a
    sane window (``valid_from < valid_until``, strict); unique weekday
    entries only (weekends are non-trading by construction — a weekend
    "holiday" would silently mean nothing and is refused, not ignored);
    the existing :class:`MarketCalendar` table guards (holiday/half-day
    overlap) applied eagerly; and the window-containment guards of
    :class:`CalendarSupply` itself.

    Drift guard: when the new supply's window overlaps the FROZEN v2
    supply, both supplies must classify every date in the overlap
    identically (trading / half-day / closed). Disagreement raises
    :class:`CalendarSupplyDriftError` — most commonly an operator table
    that dropped or moved a date the frozen record already certified
    (e.g. 2026-01-19 MLK).

    ``retrieved_utc`` defaults to the wall-clock build moment (the honest
    "when did the operator assemble this" fact); tests may pin it.
    """
    if not isinstance(version, str) or not version.strip():
        raise CalendarError("current supply requires a non-empty version")
    if not isinstance(license_note, str) or not license_note.strip():
        raise CalendarError(
            "current supply requires a non-empty license_note — the stated "
            f"{LICENSE_UNVERIFIED_NOTE} placeholder is allowed, an empty "
            "license status is not (it must be stated, never silent)"
        )
    if not isinstance(source_refs, (list, tuple)) or not source_refs:
        raise CalendarError("current supply requires at least one source ref")
    refs = tuple(ref.strip() if isinstance(ref, str) else "" for ref in source_refs)
    if any(not ref for ref in refs):
        raise CalendarError(
            "current supply source_refs entries must be non-empty strings"
        )
    if not (refs[0].startswith("http://") or refs[0].startswith("https://")):
        raise CalendarError(
            "current supply source_refs[0] must be an http(s) URL — it "
            "becomes the supply's source_url"
        )
    if (
        isinstance(valid_from, dt.datetime)
        or isinstance(valid_until, dt.datetime)
        or not isinstance(valid_from, dt.date)
        or not isinstance(valid_until, dt.date)
    ):
        raise CalendarError("current supply window bounds must be calendar dates")
    if valid_from >= valid_until:
        raise CalendarError(
            f"current supply coverage window is not sane: valid_from "
            f"{valid_from.isoformat()} must be strictly before valid_until "
            f"{valid_until.isoformat()}"
        )
    if retrieved_utc is None:
        retrieved_utc = dt.datetime.now(dt.timezone.utc)
    if not isinstance(retrieved_utc, dt.datetime) or retrieved_utc.tzinfo is None:
        raise CalendarError("current supply retrieved_utc must be timezone-aware")

    holiday_days = _require_unique_weekday_entries(holidays, "holiday")
    half_day_entries = _require_unique_weekday_entries(half_days, "half_day")
    # reuse the existing table guards (weekend holidays, holiday/half-day
    # overlap) by building the classifier eagerly — construction refuses,
    # it never warns
    MarketCalendar(holidays=set(holiday_days), half_days=set(half_day_entries))
    source = (
        f"operator-maintained CURRENT calendar ({license_note}); verify against "
        "the licensed calendar source before operational use — sessions are "
        "supplied data, never inferred from data gaps"
    )
    supply = CalendarSupply(
        version=version,
        source=source,
        source_url=refs[0],
        retrieved_utc=retrieved_utc,
        valid_from=valid_from,
        valid_until=valid_until,
        holidays=frozenset(holiday_days),
        half_days=frozenset(half_day_entries),
    )
    _assert_no_drift_vs_frozen_v2(supply)
    return supply


def _assert_no_drift_vs_frozen_v2(supply: CalendarSupply) -> None:
    """Every date inside the overlap with the frozen v2 supply must be
    classified identically by both supplies. Weekends classify the same
    way by construction, so this really pins the supplied tables."""
    overlap_start = max(supply.valid_from, NYSE_2017_2025_SUPPLY_V2.valid_from)
    overlap_end = min(supply.valid_until, NYSE_2017_2025_SUPPLY_V2.valid_until)
    if overlap_start > overlap_end:
        return
    baseline = MarketCalendar(
        holidays=set(NYSE_2017_2025_SUPPLY_V2.holidays),
        half_days=set(NYSE_2017_2025_SUPPLY_V2.half_days),
    )
    current = MarketCalendar(holidays=set(supply.holidays), half_days=set(supply.half_days))

    def _kind(info: SessionInfo) -> str:
        return (
            "half-day session"
            if info.is_half_day
            else ("session" if info.is_trading_day else "closed")
        )

    mismatches: list[str] = []
    day = overlap_start
    while day <= overlap_end:
        base_kind = _kind(baseline.session(day))
        current_kind = _kind(current.session(day))
        if base_kind != current_kind:
            mismatches.append(
                f"{day.isoformat()} frozen-v2 says {base_kind} but the "
                f"current supply says {current_kind}"
            )
        day += dt.timedelta(days=1)
    if mismatches:
        raise CalendarSupplyDriftError(
            "CALENDAR_SUPPLY_DRIFT",
            "the current supply contradicts the frozen v2 supply on "
            f"{len(mismatches)} date(s) inside the overlap "
            f"[{overlap_start.isoformat()}, {overlap_end.isoformat()}]: "
            f"{'; '.join(mismatches)} — refuse and re-verify sources",
        )


def load_supply_from_config(path: Path | str) -> CalendarSupply:
    """Load an operator-maintained CURRENT calendar supply from a YAML
    file (``configs/current_calendar.yaml`` shape; documented in the
    module docstring).

    Fail-closed: missing file, unparsable YAML, a non-mapping top level,
    unknown keys, missing fields, malformed dates, unsorted/duplicate
    date lists, an empty license note or source refs — every one refuses
    with a :class:`CalendarConfigError`; drift against the frozen v2
    supply refuses with :class:`CalendarSupplyDriftError`. No supply is
    ever half-built from a bad file.
    """
    config_path = Path(path)
    try:
        text = config_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CalendarConfigError(
            "CONFIG_NOT_READABLE", f"{config_path}: {exc}"
        ) from exc
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise CalendarConfigError(
            "CONFIG_PARSE", f"{config_path} is not valid YAML: {exc}"
        ) from exc
    if not isinstance(raw, dict):
        raise CalendarConfigError(
            "CONFIG_SHAPE", f"{config_path}: top level must be a mapping"
        )
    unknown = sorted(str(key) for key in set(raw) - CURRENT_CALENDAR_CONFIG_KEYS)
    if unknown:
        raise CalendarConfigError(
            "CONFIG_UNKNOWN_KEYS",
            f"{config_path}: unknown keys {unknown} — known keys are "
            f"{sorted(CURRENT_CALENDAR_CONFIG_KEYS)}",
        )
    missing = sorted(CURRENT_CALENDAR_CONFIG_KEYS - set(raw))
    if missing:
        raise CalendarConfigError(
            "CONFIG_MISSING_FIELDS", f"{config_path}: missing fields {missing}"
        )
    version = raw["version"]
    if not isinstance(version, str) or not version.strip():
        raise CalendarConfigError(
            "CONFIG_BAD_VERSION",
            f"{config_path}: version must be a non-empty string",
        )
    valid_from = _config_date(config_path, raw["valid_from"], "valid_from")
    valid_until = _config_date(config_path, raw["valid_until"], "valid_until")
    holidays = _config_day_list(config_path, raw["holidays"], "holidays")
    half_days = _config_day_list(config_path, raw["half_days"], "half_days")
    license_note = raw["license_note"]
    if not isinstance(license_note, str) or not license_note.strip():
        raise CalendarConfigError(
            "CONFIG_BAD_LICENSE_NOTE",
            f"{config_path}: license_note must be a non-empty string — the "
            f"stated {LICENSE_UNVERIFIED_NOTE} placeholder is allowed, an "
            "empty license status is not",
        )
    refs = raw["source_refs"]
    if not isinstance(refs, list) or not refs:
        raise CalendarConfigError(
            "CONFIG_BAD_SOURCE_REFS",
            f"{config_path}: source_refs must be a non-empty list of strings",
        )
    if not all(isinstance(ref, str) and ref.strip() for ref in refs):
        raise CalendarConfigError(
            "CONFIG_BAD_SOURCE_REFS",
            f"{config_path}: source_refs entries must be non-empty strings",
        )
    return build_current_supply(
        holidays,
        half_days,
        valid_from,
        valid_until,
        version=version,
        license_note=license_note,
        source_refs=refs,
    )


def _config_date(config_path: Path, value: Any, field: str) -> dt.date:
    """One YAML date: an ISO ``YYYY-MM-DD`` string, or the date object
    PyYAML's resolver produces for an unquoted date. A datetime (time
    components present) is refused — coverage bounds are dates."""
    if isinstance(value, dt.datetime):
        raise CalendarConfigError(
            "CONFIG_BAD_DATE",
            f"{config_path}: {field} must be a calendar date, not a datetime",
        )
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        try:
            return dt.date.fromisoformat(value.strip())
        except ValueError as exc:
            raise CalendarConfigError(
                "CONFIG_BAD_DATE",
                f"{config_path}: {field} {value!r} is not YYYY-MM-DD",
            ) from exc
    raise CalendarConfigError(
        "CONFIG_BAD_DATE",
        f"{config_path}: {field} must be a YYYY-MM-DD string, got {type(value).__name__}",
    )


def _config_day_list(config_path: Path, value: Any, field: str) -> tuple[dt.date, ...]:
    """One YAML date list: strictly ascending (sorted AND unique — equal
    neighbours are duplicates, descending neighbours are unsorted)."""
    if not isinstance(value, list):
        raise CalendarConfigError(
            "CONFIG_BAD_LIST",
            f"{config_path}: {field} must be a list of YYYY-MM-DD strings",
        )
    days = tuple(
        _config_date(config_path, item, f"{field}[{index}]")
        for index, item in enumerate(value)
    )
    for previous, following in zip(days, days[1:]):
        if following == previous:
            raise CalendarConfigError(
                "CONFIG_DUPLICATE_DATE",
                f"{config_path}: {field} has duplicate entry "
                f"{previous.isoformat()} (lists must be sorted and unique)",
            )
        if following < previous:
            raise CalendarConfigError(
                "CONFIG_UNSORTED_LIST",
                f"{config_path}: {field} is not sorted ascending "
                f"({previous.isoformat()} appears before {following.isoformat()})",
            )
    return days
