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
"""

from __future__ import annotations

import datetime as dt

from ..security.canonical import canonical_json_bytes, sha256_hex
from .historical_calendar import CalendarSupply

__all__ = ["NYSE_2017_2025_SUPPLY", "FROZEN_SUPPLY_HASH", "frozen_supply_hash", "SUPPLY_SOURCE_REFS"]


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
