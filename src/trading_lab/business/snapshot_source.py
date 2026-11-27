"""V0.2 historical snapshot reader (B1 data-source half).

Reads a collection produced by ``scripts/collect_historical_snapshot.py``
(BUSINESS-MVP-V02 workflow A2) in the ``historical_research`` namespace,
fully offline, fail-closed:

    <snapshot_dir>/collection_manifest.json
    <snapshot_dir>/<SYMBOL>/bars.jsonl      (one MarketBar JSON per line)

``snapshot_dir`` is the namespace root itself (the directory that holds
the manifest; the collector writes it as ``<output-dir>/historical_research``).

The layout constants below are pinned to the producer
``apps/market_gateway/collection_session.py``. The business plane may not
import the gateway (scripts/check_architecture.py), so the shapes are
re-declared here and any drift fails closed: unknown schema, transport
mode, license status, PIT level or admission status are hard errors —
never best-effort guesses about a changed producer.

Manifest fields honored (all produced by the collector):

- ``schema`` == "collection_manifest_v1"; ``status`` == "COLLECTED";
  ``namespace`` == "historical_research";
- ``window``: ``{"start", "end"}`` ET session dates (inclusive);
- ``transport``: ``{"mode": "probe"|"live", "label", "real_network_used"}``
  — probe rows are FAKE-transport validation data, never real history;
- ``calendar_supply``: ``version`` (required), ``hash`` / ``hash_frozen``
  (recorded, trusted — re-deriving ``ts_available_utc`` from the calendar
  is the A2 writer's duty and is NOT re-done here);
- ``license.status``: "LICENSE_VERIFIED" | "LICENSE_UNVERIFIED";
- ``pit``: ``level`` "VERIFIED" | "ASSUMED" | "UNKNOWN" (+ ``rule``);
- ``admission.status``: "RESEARCH_ADMITTED" | "NOT_RESEARCH_ADMITTED"
  (the until-gate marker; the collector always emits the restricted one);
- ``symbols``: ``{SYMBOL: {"row_count": int, "bars_sha256": <sha256 of the
  raw bars.jsonl file bytes>, ...}}``.

Severity split: the collection itself being unusable (missing/unparsable/
shape-invalid manifest) is a HARD ERROR (:class:`SnapshotSourceError`) and
produces no bundle. Content-level failures refuse ONE symbol with a
recorded reason and keep independently valid symbols: file-bytes hash
mismatch, row-count mismatch, row outside the window, non-monotonic
``ts_event``, bar ``source`` inconsistent with the manifest transport
mode (SOURCE_LABEL_MISMATCH), missing/empty bars file, store-plane
admission refusal (e.g. a quality label outside the store vocabulary).

Research admission is explicit and orthogonal to loading:
``research_admitted`` is True only when the admission marker is released
AND the license is verified AND the PIT level is VERIFIED. Every snapshot
this collector can emit today (LICENSE_UNVERIFIED / ASSUMED /
NOT_RESEARCH_ADMITTED) loads as ``research_admitted=False`` with
``scenario_tags`` = "HISTORICAL_EXPLORATORY" — exploratory-only, never
silently treated as admitted.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Any

from trading_lab.business.series import (
    SeriesStore,
    SeriesStoreError,
    load_bars_jsonl,
)
from trading_lab.contracts import MarketBar
from trading_lab.data.calendar import ET
from trading_lab.security.canonical import canonical_digest

__all__ = [
    "ADMISSION_RELEASED",
    "ADMISSION_STATUSES",
    "ADMISSION_RESTRICTED",
    "COLLECTED_STATUS",
    "LICENSE_STATUSES",
    "LICENSE_UNVERIFIED",
    "LICENSE_VERIFIED",
    "MANIFEST_SCHEMA",
    "NAMESPACE_MARKER",
    "PIT_ASSUMED_NOT_VERIFIED",
    "PIT_LEVELS",
    "PIT_LEVEL_ASSUMED",
    "PIT_LEVEL_UNKNOWN",
    "PIT_LEVEL_VERIFIED",
    "SCENARIO_TAG_ADMITTED",
    "SCENARIO_TAG_EXPLORATORY",
    "SNAPSHOT_MANIFEST_NAME",
    "SOURCE_LIVE",
    "SOURCE_PROBE",
    "TRANSPORT_MODES",
    "TRANSPORT_MODE_LIVE",
    "TRANSPORT_MODE_PROBE",
    "SnapshotBundle",
    "SnapshotSourceError",
    "SymbolRefusal",
    "load_historical_snapshot",
]

# -- layout constants, pinned to apps/market_gateway/collection_session.py ----
# (import-banned by the architecture check; drift fails closed below)

MANIFEST_SCHEMA = "collection_manifest_v1"
COLLECTED_STATUS = "COLLECTED"
NAMESPACE_MARKER = "historical_research"
SNAPSHOT_MANIFEST_NAME = "collection_manifest.json"

TRANSPORT_MODE_PROBE = "probe"
TRANSPORT_MODE_LIVE = "live"
TRANSPORT_MODES = frozenset({TRANSPORT_MODE_PROBE, TRANSPORT_MODE_LIVE})
SOURCE_PROBE = "FAKE_TRANSPORT"
SOURCE_LIVE = "alpaca_iex"
#: the only bar ``source`` label each transport mode may emit
_EXPECTED_SOURCE = {
    TRANSPORT_MODE_PROBE: SOURCE_PROBE,
    TRANSPORT_MODE_LIVE: SOURCE_LIVE,
}

LICENSE_VERIFIED = "LICENSE_VERIFIED"
LICENSE_UNVERIFIED = "LICENSE_UNVERIFIED"
LICENSE_STATUSES = frozenset({LICENSE_VERIFIED, LICENSE_UNVERIFIED})

#: PIT evidence vocabulary (mirrors trading_lab.data.historical.PIT_LEVELS)
PIT_LEVEL_VERIFIED = "VERIFIED"
PIT_LEVEL_ASSUMED = "ASSUMED"
PIT_LEVEL_UNKNOWN = "UNKNOWN"
PIT_LEVELS = frozenset({
    PIT_LEVEL_VERIFIED, PIT_LEVEL_ASSUMED, PIT_LEVEL_UNKNOWN,
})
#: the claim marker any ASSUMED-only result carries (data.historical)
PIT_ASSUMED_NOT_VERIFIED = "PIT_ASSUMED_NOT_VERIFIED"

ADMISSION_RELEASED = "RESEARCH_ADMITTED"
ADMISSION_RESTRICTED = "NOT_RESEARCH_ADMITTED"
ADMISSION_STATUSES = frozenset({ADMISSION_RELEASED, ADMISSION_RESTRICTED})

SCENARIO_TAG_ADMITTED = "HISTORICAL"
SCENARIO_TAG_EXPLORATORY = "HISTORICAL_EXPLORATORY"

_SYMBOL_RE = re.compile(r"^[A-Z]{1,5}$")   # namespace-root escape guard
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")

#: canonical projection of a bar row for the dataset digest (same fields
#: as the store plane's admission record)
_ROW_FIELDS: tuple[str, ...] = (
    "asset_id", "ts_event_utc", "ts_available_utc", "interval",
    "open", "high", "low", "close", "volume", "source",
    "adjustment", "quality",
)


class SnapshotSourceError(ValueError):
    """The collection itself is unusable (manifest missing/invalid) —
    fail closed; no bundle is produced."""


@dataclass(frozen=True)
class SymbolRefusal:
    """One refused symbol with its machine-readable reason."""

    symbol: str
    reason: str
    detail: str


class _SymbolRejection(Exception):
    """Internal control flow: a per-symbol refusal (not a hard error)."""

    def __init__(self, refusal: SymbolRefusal) -> None:
        super().__init__(refusal.detail)
        self.refusal = refusal


@dataclass(frozen=True)
class _SymbolEntry:
    """Manifest-parsed per-symbol partition spec (shape-validated)."""

    symbol: str
    row_count: int
    bars_sha256: str


@dataclass(frozen=True)
class _ManifestView:
    """Shape-validated manifest (see module docstring for the layout)."""

    window: tuple[dt.date, dt.date]
    transport_mode: str
    transport_label: str
    real_network_used: bool
    expected_source: str
    calendar_version: str
    calendar_hash: str | None
    calendar_hash_frozen: str | None
    license_status: str
    pit_level: str | None
    pit_rule: str | None
    admission_status: str
    entries: dict[str, _SymbolEntry]


@dataclass(frozen=True)
class SnapshotBundle:
    """A validated local historical snapshot, ready for the existing
    pipeline. ``stores`` holds ONE independent ``SeriesStore`` per loaded
    symbol (never concatenated); ``bars`` mirrors the loaded rows for
    reporting/valuation and keeps working for exploratory bundles whose
    quality labels the store plane refuses. A refused symbol is absent
    from both and recorded in ``refusals``/``blockers``;
    ``scenario_tags`` covers every manifest-declared symbol (the tag
    describes the dataset, not only the loadable part)."""

    stores: Mapping[str, SeriesStore]
    bars: Mapping[str, tuple[MarketBar, ...]]
    session_dates: tuple[dt.date, ...]
    manifest_summary: Mapping[str, object]
    research_admitted: bool
    blockers: tuple[str, ...]
    dataset_hash: str
    scenario_tags: Mapping[str, str]
    refusals: tuple[SymbolRefusal, ...] = ()

    def next_open_price(self, symbol: str, session_date: dt.date) -> Decimal | None:
        """Open of the symbol's first bar STRICTLY AFTER ``session_date``
        (next-open fill valuation, same semantics as the demo fixture).
        None when no later bar exists or the symbol was refused/unknown."""
        for bar in self.bars.get(symbol, ()):
            if bar.ts_event_utc.date() > session_date:
                return bar.open
        return None


# ---------------------------------------------------------------------------
# manifest reading + shape validation (hard errors)
# ---------------------------------------------------------------------------


def _read_manifest(snapshot_dir: Path) -> dict[str, Any]:
    if not snapshot_dir.is_dir():
        raise SnapshotSourceError(f"snapshot dir missing: {snapshot_dir}")
    path = snapshot_dir / SNAPSHOT_MANIFEST_NAME
    if not path.is_file():
        raise SnapshotSourceError(f"missing snapshot manifest: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SnapshotSourceError(
            f"unparsable snapshot manifest {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SnapshotSourceError("snapshot manifest must be a JSON mapping")
    return payload


def _require_str(manifest: Mapping[str, Any], key: str) -> str:
    if key not in manifest:
        raise SnapshotSourceError(
            f"snapshot manifest missing required key {key!r}")
    value = manifest[key]
    if not isinstance(value, str) or not value.strip():
        raise SnapshotSourceError(
            f"snapshot manifest key {key!r} must be a non-empty string")
    return value


def _expect(manifest: Mapping[str, Any], key: str, allowed: frozenset[str]) -> str:
    value = _require_str(manifest, key)
    if value not in allowed:
        raise SnapshotSourceError(
            f"snapshot manifest {key} {value!r} outside {sorted(allowed)} "
            "(producer drift — fail closed)")
    return value


def _parse_window(manifest: Mapping[str, Any]) -> tuple[dt.date, dt.date]:
    window = manifest.get("window")
    if not isinstance(window, dict) or "start" not in window or "end" not in window:
        raise SnapshotSourceError(
            "snapshot manifest window must be a mapping with start/end")
    try:
        start = dt.date.fromisoformat(str(window["start"]))
        end = dt.date.fromisoformat(str(window["end"]))
    except ValueError as exc:
        raise SnapshotSourceError(
            f"snapshot manifest window dates invalid: {exc}") from exc
    if end < start:
        raise SnapshotSourceError("snapshot manifest window end precedes start")
    return start, end


def _parse_transport(manifest: Mapping[str, Any]) -> tuple[str, str, bool, str]:
    transport = manifest.get("transport")
    if not isinstance(transport, dict):
        raise SnapshotSourceError(
            "snapshot manifest transport must be a mapping")
    mode = transport.get("mode")
    if mode not in TRANSPORT_MODES:
        raise SnapshotSourceError(
            f"snapshot manifest transport mode {mode!r} outside "
            f"{sorted(TRANSPORT_MODES)} (producer drift — fail closed)")
    label = transport.get("label")
    if not isinstance(label, str) or not label.strip():
        raise SnapshotSourceError(
            "snapshot manifest transport label must be a non-empty string")
    real_network = transport.get("real_network_used")
    if not isinstance(real_network, bool):
        raise SnapshotSourceError(
            "snapshot manifest transport real_network_used must be boolean")
    return mode, label, real_network, _EXPECTED_SOURCE[mode]


def _parse_calendar_supply(
    manifest: Mapping[str, Any],
) -> tuple[str, str | None, str | None]:
    calendar = manifest.get("calendar_supply")
    if not isinstance(calendar, dict):
        raise SnapshotSourceError(
            "snapshot manifest calendar_supply must be a mapping")
    version = calendar.get("version")
    if not isinstance(version, str) or not version.strip():
        raise SnapshotSourceError(
            "snapshot manifest calendar_supply must record a non-empty version")
    for key in ("hash", "hash_frozen"):
        value = calendar.get(key)
        if value is not None and (
                not isinstance(value, str) or not _HEX64_RE.fullmatch(value)):
            raise SnapshotSourceError(
                f"snapshot manifest calendar_supply {key} must be a sha256 "
                "hex digest")
    return version, calendar.get("hash"), calendar.get("hash_frozen")


def _parse_license(manifest: Mapping[str, Any]) -> str:
    license_doc = manifest.get("license")
    if not isinstance(license_doc, dict):
        raise SnapshotSourceError("snapshot manifest license must be a mapping")
    status = license_doc.get("status")
    if status not in LICENSE_STATUSES:
        raise SnapshotSourceError(
            f"snapshot manifest license status {status!r} outside "
            f"{sorted(LICENSE_STATUSES)} (producer drift — fail closed)")
    return str(status)


def _parse_pit(manifest: Mapping[str, Any]) -> tuple[str | None, str | None]:
    """``(None, None)`` means the pit doc is ABSENT — a gate blocker, not
    a shape error (its absence must be able to block admission)."""
    pit = manifest.get("pit")
    if pit is None:
        return None, None
    if not isinstance(pit, dict):
        raise SnapshotSourceError("snapshot manifest pit must be a mapping")
    level = pit.get("level")
    if level not in PIT_LEVELS:
        raise SnapshotSourceError(
            f"snapshot manifest pit level {level!r} outside "
            f"{sorted(PIT_LEVELS)} (producer drift — fail closed)")
    rule = pit.get("rule")
    return str(level), (str(rule) if isinstance(rule, str) else None)


def _parse_admission(manifest: Mapping[str, Any]) -> str:
    admission = manifest.get("admission")
    if not isinstance(admission, dict):
        raise SnapshotSourceError("snapshot manifest admission must be a mapping")
    status = admission.get("status")
    if status not in ADMISSION_STATUSES:
        raise SnapshotSourceError(
            f"snapshot manifest admission status {status!r} outside "
            f"{sorted(ADMISSION_STATUSES)} (must be explicit; producer "
            "drift — fail closed)")
    return str(status)


def _parse_symbols(manifest: Mapping[str, Any]) -> dict[str, _SymbolEntry]:
    raw = manifest.get("symbols")
    if not isinstance(raw, dict) or not raw:
        raise SnapshotSourceError(
            "snapshot manifest symbols must be a non-empty mapping")
    entries: dict[str, _SymbolEntry] = {}
    for key, spec in raw.items():
        symbol = str(key)
        if not _SYMBOL_RE.fullmatch(symbol):
            raise SnapshotSourceError(
                f"snapshot manifest symbol segment unsafe: {symbol!r} "
                "(partition names are namespace-root escape guards)")
        if not isinstance(spec, dict):
            raise SnapshotSourceError(
                f"snapshot manifest entry for {symbol} must be a mapping")
        row_count = spec.get("row_count")
        if isinstance(row_count, bool) or not isinstance(row_count, int) \
                or row_count < 0:
            raise SnapshotSourceError(
                f"snapshot manifest row_count for {symbol} must be an int >= 0")
        bars_sha256 = spec.get("bars_sha256")
        if not isinstance(bars_sha256, str) or not _HEX64_RE.fullmatch(bars_sha256):
            raise SnapshotSourceError(
                f"snapshot manifest bars_sha256 for {symbol} must be a "
                "sha256 hex digest")
        entries[symbol] = _SymbolEntry(symbol, row_count, bars_sha256)
    return entries


def _parse_manifest(manifest: Mapping[str, Any]) -> _ManifestView:
    _expect(manifest, "schema", frozenset({MANIFEST_SCHEMA}))
    _expect(manifest, "status", frozenset({COLLECTED_STATUS}))
    _expect(manifest, "namespace", frozenset({NAMESPACE_MARKER}))
    window = _parse_window(manifest)
    mode, label, real_network, expected_source = _parse_transport(manifest)
    version, cal_hash, cal_hash_frozen = _parse_calendar_supply(manifest)
    license_status = _parse_license(manifest)
    pit_level, pit_rule = _parse_pit(manifest)
    admission_status = _parse_admission(manifest)
    entries = _parse_symbols(manifest)
    return _ManifestView(
        window=window,
        transport_mode=mode,
        transport_label=label,
        real_network_used=real_network,
        expected_source=expected_source,
        calendar_version=version,
        calendar_hash=cal_hash,
        calendar_hash_frozen=cal_hash_frozen,
        license_status=license_status,
        pit_level=pit_level,
        pit_rule=pit_rule,
        admission_status=admission_status,
        entries=entries,
    )


# ---------------------------------------------------------------------------
# per-symbol loading (refusals, never hard errors)
# ---------------------------------------------------------------------------


def _refuse(symbol: str, reason: str, detail: str) -> _SymbolRejection:
    return _SymbolRejection(SymbolRefusal(symbol, reason, detail))


def _load_symbol_bars(
    snapshot_dir: Path,
    entry: _SymbolEntry,
    view: _ManifestView,
) -> tuple[MarketBar, ...]:
    """Load + validate one symbol's partition. Raises ``_SymbolRejection``
    (recorded refusal) — any other exception is a programming error."""
    symbol = entry.symbol
    bars_path = snapshot_dir / symbol / "bars.jsonl"
    try:
        raw_bytes = bars_path.read_bytes()
    except OSError as exc:
        raise _refuse(symbol, "MISSING_BARS_FILE",
                      f"cannot read {bars_path}: {exc}") from exc
    digest = hashlib.sha256(raw_bytes).hexdigest()
    if digest != entry.bars_sha256:
        raise _refuse(symbol, "HASH_MISMATCH",
                      f"file sha256 {digest} != manifest bars_sha256 "
                      f"{entry.bars_sha256}")
    try:
        bars = load_bars_jsonl(bars_path)
    except SeriesStoreError as exc:
        raise _refuse(symbol, "PARSE_INVALID", str(exc)) from exc
    if entry.row_count == 0:
        raise _refuse(symbol, "EMPTY_PARTITION",
                      "manifest records row_count 0 (no bars collected)")
    if len(bars) != entry.row_count:
        raise _refuse(symbol, "ROW_COUNT_MISMATCH",
                      f"{len(bars)} parsed rows != manifest row_count "
                      f"{entry.row_count}")
    start, end = view.window
    prev_event: dt.datetime | None = None
    for bar in bars:
        if bar.source != view.expected_source:
            raise _refuse(symbol, "SOURCE_LABEL_MISMATCH",
                          f"bar source {bar.source!r} != manifest transport "
                          f"mode {view.transport_mode!r} (expected "
                          f"{view.expected_source!r})")
        if bar.ts_available_utc < bar.ts_event_utc:   # contract re-check
            raise _refuse(symbol, "AVAILABILITY_BEFORE_EVENT",
                          f"ts_available_utc {bar.ts_available_utc} < "
                          f"ts_event_utc {bar.ts_event_utc}")
        session = bar.ts_event_utc.astimezone(ET).date()   # ET session date
        if session < start or session > end:
            raise _refuse(symbol, "OUTSIDE_WINDOW",
                          f"session {session.isoformat()} outside manifest "
                          f"window [{start.isoformat()}, {end.isoformat()}]")
        if prev_event is not None and bar.ts_event_utc <= prev_event:
            raise _refuse(symbol, "NON_MONOTONIC_TS_EVENT",
                          f"ts_event_utc not strictly increasing at "
                          f"{bar.ts_event_utc}")
        prev_event = bar.ts_event_utc
    return bars


# ---------------------------------------------------------------------------
# public entry point
# ---------------------------------------------------------------------------


def _gate_blockers(view: _ManifestView) -> list[str]:
    """Admission gates: explicit release + verified license + VERIFIED
    PIT. Every collector-produced snapshot fails at least one of these —
    that is the honest state, recorded as blockers, never upgraded."""
    blockers: list[str] = []
    if view.admission_status != ADMISSION_RELEASED:
        blockers.append("ADMISSION_NOT_RELEASED")
    if view.license_status != LICENSE_VERIFIED:
        blockers.append("LICENSE_NOT_VERIFIED")
    if view.pit_level is None:
        blockers.append("PIT_BASIS_MISSING")
    elif view.pit_level == PIT_LEVEL_UNKNOWN:
        blockers.append("PIT_LEVEL_UNKNOWN")
    elif view.pit_level == PIT_LEVEL_ASSUMED:
        blockers.append(PIT_ASSUMED_NOT_VERIFIED)
    return blockers


def load_historical_snapshot(snapshot_dir: Path) -> SnapshotBundle:
    """Load a V0.2 collection into a validated, admission-explicit bundle.

    Hard-fails on a missing/unusable manifest; refuses individual symbols
    on content-level failures while keeping independently valid symbols;
    never upgrades a restricted/unlicensed snapshot to admitted."""
    root = Path(snapshot_dir)
    view = _parse_manifest(_read_manifest(root))

    blockers: list[str] = _gate_blockers(view)
    research_admitted = not blockers

    # fail-closed honesty: directories on disk that the manifest does not
    # list are never loaded, only recorded
    for child in sorted(root.iterdir()):
        if child.is_dir() and child.name not in view.entries:
            blockers.append(f"UNLISTED_SYMBOL_DIR:{child.name}")

    stores: dict[str, SeriesStore] = {}
    bars_by: dict[str, tuple[MarketBar, ...]] = {}
    refusals: list[SymbolRefusal] = []
    for symbol in sorted(view.entries):
        try:
            bars = _load_symbol_bars(root, view.entries[symbol], view)
            # ONE store per symbol — never concatenated across symbols
            store = SeriesStore({symbol: bars})
        except _SymbolRejection as exc:
            refusals.append(exc.refusal)
            blockers.append(f"{exc.refusal.reason}:{symbol}")
            continue
        except SeriesStoreError as exc:
            refusal = SymbolRefusal(symbol, "STORE_ADMISSION_REFUSED", str(exc))
            refusals.append(refusal)
            blockers.append(f"{refusal.reason}:{symbol}")
            continue
        bars_by[symbol] = bars
        stores[symbol] = store

    rows = sorted(
        ({field: getattr(bar, field) for field in _ROW_FIELDS}
         for series in bars_by.values() for bar in series),
        key=lambda row: (row["asset_id"], row["ts_event_utc"]),
    )
    dataset_hash = canonical_digest({"rows": rows})
    session_dates = tuple(sorted({
        bar.ts_event_utc.date() for series in bars_by.values() for bar in series}))
    tag = SCENARIO_TAG_EXPLORATORY if not research_admitted \
        else SCENARIO_TAG_ADMITTED
    summary: dict[str, object] = {
        "schema": MANIFEST_SCHEMA,
        "status": COLLECTED_STATUS,
        "namespace": NAMESPACE_MARKER,
        "window": {
            "start": view.window[0].isoformat(),
            "end": view.window[1].isoformat(),
        },
        "transport": {
            "mode": view.transport_mode,
            "label": view.transport_label,
            "real_network_used": view.real_network_used,
            "expected_source": view.expected_source,
        },
        "calendar_supply": {
            "version": view.calendar_version,
            "hash": view.calendar_hash,
            "hash_frozen": view.calendar_hash_frozen,
        },
        "license_status": view.license_status,
        "pit_level": view.pit_level,
        "pit_rule": view.pit_rule,
        "admission_status": view.admission_status,
        "symbols_declared": sorted(view.entries),
        "symbols_loaded": sorted(bars_by),
        "symbols_refused": sorted(r.symbol for r in refusals),
        "refusals": [
            {"symbol": r.symbol, "reason": r.reason, "detail": r.detail}
            for r in refusals
        ],
        "research_admitted": research_admitted,
        "dataset_hash": dataset_hash,
    }
    return SnapshotBundle(
        stores=MappingProxyType(stores),
        bars=MappingProxyType(bars_by),
        session_dates=session_dates,
        manifest_summary=MappingProxyType(summary),
        research_admitted=research_admitted,
        blockers=tuple(sorted(dict.fromkeys(blockers))),
        dataset_hash=dataset_hash,
        scenario_tags=MappingProxyType(
            {symbol: tag for symbol in view.entries}),
        refusals=tuple(refusals),
    )
