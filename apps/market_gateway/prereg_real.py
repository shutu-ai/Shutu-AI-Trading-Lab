"""Real forward preregistration loader (v2, S8 read-only scope).

A SECOND, separately-authorized preregistration version — the synthetic
one (``configs/forward_observation.yaml``, ``SYNTHETIC_REPLAY_ONLY``) is
byte-frozen and is never edited or upgraded in place. This loader accepts
ONLY the read-only real-market-data scope the user signed on 2026-11-22
(record: ``artifacts/evidence/M3.5/s8/authorization-check.md``):

- Alpaca free Basic plan, IEX feed, at most 3 US equity/ETF symbols;
- GET-only market-data transport against ``data.alpaca.markets`` — the
  trading-API hosts (``api.alpaca.markets``, ``paper-api.alpaca.markets``)
  are structurally forbidden;
- ``broker_credentials: FORBIDDEN`` (no trading API use of any kind —
  ``PAPER_WRITE=NOT_AUTHORIZED`` holds);
- vendor capability claims still not evidence (M1 U-1 stays closed);
- ``real_window.enabled: true`` — this version is the ONLY one allowed to
  enable it, and the 5-real-trading-day threshold is preregistered.

Any other configuration raises :class:`PreregistrationRealRefused`.
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import Any, Mapping

import yaml

from apps.trading_daemon.prereg import Preregistration

__all__ = ["PreregistrationReal", "PreregistrationRealRefused"]


class PreregistrationRealRefused(ValueError):
    """The real preregistration authorizes anything outside the signed
    read-only scope — the collector refuses to run under it."""


_REQUIRED_MODE = "REAL_SHADOW_READ_ONLY"

#: schema v2 = the pinned LEGACY contract (LEGACY_INVALID_VENDOR_CONTRACT:
#: fabricated latest-bar shape, minute-bar semantics consumed as daily).
#: Loadable for pinned evidence reproduction only — real collection
#: refuses it.
_LEGACY_SCHEMA = "forward-observation-preregistration-v2"
#: schema v3 = the production ranged-daily-bars contract (official
#: /v2/stocks/{symbol}/bars?timeframe=1Day, official-api-contract.md §2).
_RANGED_SCHEMA = "forward-observation-preregistration-v3"

_MAX_SYMBOLS = 3
_SYMBOL_RE = re.compile(r"^[A-Z]{1,5}$")
_DATA_HOSTS = frozenset({"data.alpaca.markets"})
_TRADING_HOSTS = frozenset({"api.alpaca.markets", "paper-api.alpaca.markets"})
_PATH_PREFIX = "/v2/stocks/"
_HHMM_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_RANGED_PROBE_PATH = "/v2/stocks/SPY/bars"


def _parse_date(value: str, field: str) -> dt.date:
    try:
        return dt.date.fromisoformat(str(value))
    except ValueError as exc:
        raise PreregistrationRealRefused(
            f"{field} must be an ISO date, got {value!r}") from exc


def _parse_hhmm(value: str, field: str) -> dt.time:
    if not isinstance(value, str) or not _HHMM_RE.match(value):
        raise PreregistrationRealRefused(
            f"{field} must be HH:MM, got {value!r}")
    parts = value.split(":")
    return dt.time(int(parts[0]), int(parts[1]))


class PreregistrationReal(Preregistration):
    """Frozen v2 preregistration — the real Shadow read-only protocol."""

    # -- scope validation (fail closed, on construction) ---------------------

    def _validate_scope(self, p: Mapping[str, Any]) -> None:
        schema_value = p.get("schema")
        if schema_value == _LEGACY_SCHEMA:
            object.__setattr__(self, "_contract_legacy", True)
        elif schema_value == _RANGED_SCHEMA:
            object.__setattr__(self, "_contract_legacy", False)
        else:
            raise PreregistrationRealRefused(
                "schema must be "
                f"{_LEGACY_SCHEMA} (pinned legacy evidence) or "
                f"{_RANGED_SCHEMA} (production ranged daily bars), got "
                f"{schema_value!r}")
        if p.get("mode") != _REQUIRED_MODE:
            raise PreregistrationRealRefused(
                f"mode must be {_REQUIRED_MODE}, got {p.get('mode')!r}")

        auth = p.get("source_authorization") or {}
        rmd = auth.get("real_market_data")
        if rmd != "ALPACA_IEX_BASIC_READ_ONLY":
            raise PreregistrationRealRefused(
                "real_market_data must be exactly "
                f"ALPACA_IEX_BASIC_READ_ONLY, got {rmd!r}")
        if auth.get("provider") != "alpaca":
            raise PreregistrationRealRefused("provider must be 'alpaca'")
        if auth.get("feed") != "iex":
            raise PreregistrationRealRefused(
                "feed must be 'iex' — the free Basic feed; SIP/paid feeds "
                "are not authorized")
        if auth.get("plan") != "basic_free":
            raise PreregistrationRealRefused(
                "plan must be 'basic_free' ($0) — paid upgrades are never "
                "authorized from this stage")
        if auth.get("broker_credentials") != "FORBIDDEN":
            raise PreregistrationRealRefused(
                "broker_credentials must be FORBIDDEN — no trading API use "
                "of any kind (PAPER_WRITE=NOT_AUTHORIZED)")
        if auth.get("vendor_capability_claims_accepted") is not False:
            raise PreregistrationRealRefused(
                "vendor capability claims are not evidence (M1 U-1 stays "
                "closed)")
        if tuple(auth.get("admitted_sources") or ()) != ("alpaca_iex",):
            raise PreregistrationRealRefused(
                "admitted_sources must be exactly ['alpaca_iex']")

        att = auth.get("license_attestation") or {}
        if att.get("operator_confirmed") is not True:
            raise PreregistrationRealRefused(
                "license_attestation.operator_confirmed must be true — the "
                "operator (account owner) confirms license/feed/credential "
                "setup personally; the collector never substitutes for it")
        if not str(att.get("approval_record") or "").strip():
            raise PreregistrationRealRefused(
                "license_attestation.approval_record must name the signed "
                "approval record path")

        self._validate_datasets(p.get("admitted_datasets"))
        self._validate_real_window(p.get("real_window") or {})
        self._validate_clock(p.get("market_clock") or {})
        self._validate_collection(p.get("collection") or {})
        if p.get("event_contract", {}).get("timestamps_tz_aware") is not True:
            raise PreregistrationRealRefused(
                "event_contract.timestamps_tz_aware must be true")
        if p.get("environment_must_equal") != _REQUIRED_MODE:
            raise PreregistrationRealRefused(
                "environment_must_equal must be " f"{_REQUIRED_MODE}")
        if not getattr(self, "_contract_legacy", True):
            # ranged contract (schema v3): hard constraints on the daily
            # bars data contract — the only legal production source
            self._validate_data_contract(p.get("data_contract") or {},
                                         p.get("collection") or {})

    @staticmethod
    def _validate_datasets(datasets: Any) -> None:
        if not isinstance(datasets, list) or not datasets:
            raise PreregistrationRealRefused(
                "admitted_datasets must be a non-empty list")
        if len(datasets) != 1:
            raise PreregistrationRealRefused(
                "exactly one admitted dataset entry is allowed in this scope")
        d = datasets[0]
        if d.get("source") != "alpaca_iex":
            raise PreregistrationRealRefused(
                "admitted dataset source must be 'alpaca_iex'")
        symbols = d.get("symbols")
        if not isinstance(symbols, list) or not symbols:
            raise PreregistrationRealRefused(
                "admitted dataset must declare a non-empty symbols list")
        if len(symbols) > _MAX_SYMBOLS:
            raise PreregistrationRealRefused(
                f"at most {_MAX_SYMBOLS} symbols are authorized initially "
                f"(got {len(symbols)})")
        for s in symbols:
            if not isinstance(s, str) or not _SYMBOL_RE.match(s):
                raise PreregistrationRealRefused(
                    f"symbol {s!r} is not a plain uppercase US ticker")
        if len(set(symbols)) != len(symbols):
            raise PreregistrationRealRefused("duplicate symbols in dataset")
        if d.get("interval") != "1d":
            raise PreregistrationRealRefused(
                "interval must be '1d' — daily completed bars only")
        if d.get("dataset_admission") != "receipt_content_hash":
            raise PreregistrationRealRefused(
                "dataset_admission must be 'receipt_content_hash' — "
                "live-arriving data has no preregisterable fixture hash")
        if "dataset_hash" in d:
            raise PreregistrationRealRefused(
                "dataset_hash must NOT be pinned in the real preregistration "
                "(it is computed from the arriving payload at receipt)")

    @staticmethod
    def _validate_real_window(real: Mapping[str, Any]) -> None:
        if real.get("enabled") is not True:
            raise PreregistrationRealRefused(
                "real_window.enabled must be true in the REAL version "
                "(the synthetic version is the one that pins it false)")
        days = real.get("min_trading_days")
        if not isinstance(days, int) or days < 5:
            raise PreregistrationRealRefused(
                "min_trading_days must be an int >= 5 — the signed approval "
                "requires at least 5 real observable US trading days")
        if real.get("paper_orders") != "PAPER_NOT_RUN":
            raise PreregistrationRealRefused(
                "paper_orders must stay PAPER_NOT_RUN — no Paper write "
                "authorization exists")
        if real.get("day_counting_rule") != "full_coverage":
            raise PreregistrationRealRefused(
                "day_counting_rule must be 'full_coverage' — a day counts "
                "only when every admitted symbol delivered")

    @staticmethod
    def _validate_clock(clock: Mapping[str, Any]) -> None:
        if clock.get("calendar_source") != "OPERATOR_DECLARED_TABLE":
            raise PreregistrationRealRefused(
                "calendar_source must be OPERATOR_DECLARED_TABLE — real "
                "holidays are declared, never inferred from a fixture")
        valid_from = _parse_date(clock.get("calendar_valid_from", ""),
                                 "calendar_valid_from")
        valid_until = _parse_date(clock.get("calendar_valid_until", ""),
                                  "calendar_valid_until")
        if valid_until < valid_from:
            raise PreregistrationRealRefused(
                "calendar_valid_until precedes calendar_valid_from")
        holidays = [_parse_date(d, "holiday")
                    for d in (clock.get("holidays") or [])]
        half_days = [_parse_date(d, "half_day")
                     for d in (clock.get("half_days") or [])]
        for label, dates in (("holiday", holidays), ("half_day", half_days)):
            for d in dates:
                if d.weekday() >= 5:
                    raise PreregistrationRealRefused(
                        f"{label} {d} falls on a weekend")
                if not (valid_from <= d <= valid_until):
                    raise PreregistrationRealRefused(
                        f"{label} {d} lies outside the declared calendar "
                        "coverage window")
        overlap = set(holidays) & set(half_days)
        if overlap:
            raise PreregistrationRealRefused(
                f"dates marked both holiday and half-day: {sorted(overlap)}")
        window = clock.get("session_window_et")
        if not (isinstance(window, list) and len(window) == 2):
            raise PreregistrationRealRefused(
                "session_window_et must be [open, close]")
        if _parse_hhmm(window[0], "session open") != dt.time(9, 30) or \
                _parse_hhmm(window[1], "session close") != dt.time(16, 0):
            raise PreregistrationRealRefused(
                "session_window_et must be ['09:30', '16:00'] (the half-day "
                "13:00 close comes from the half_days table, not the window)")
        if clock.get("daily_bar_normalization") != "SESSION_CLOSE_ET":
            raise PreregistrationRealRefused(
                "daily_bar_normalization must be SESSION_CLOSE_ET")

    @staticmethod
    def _validate_data_contract(contract: Mapping[str, Any],
                                collection: Mapping[str, Any]) -> None:
        """Schema v3 hard constraints — the daily bars contract is the
        official ranged endpoint (official-api-contract.md §2). The
        legacy latest-bar contract can never re-enter production through
        a v3 preregistration."""
        if contract.get("bars_endpoint") != "ranged_daily_bars":
            raise PreregistrationRealRefused(
                "data_contract.bars_endpoint must be 'ranged_daily_bars' "
                "(GET /v2/stocks/{symbol}/bars?timeframe=1Day) — the "
                "latest-bar endpoint is minute-bar semantics and is "
                "pinned as legacy evidence only")
        if contract.get("timeframe") != "1Day":
            raise PreregistrationRealRefused(
                "data_contract.timeframe must be '1Day'")
        if contract.get("adjustment") != "raw":
            raise PreregistrationRealRefused(
                "data_contract.adjustment must be 'raw'")
        if contract.get("window_bounds") != "session_midnight_et_to_received_at":
            raise PreregistrationRealRefused(
                "data_contract.window_bounds must be "
                "'session_midnight_et_to_received_at' — an explicit "
                "bounded window for the requested session; no wide "
                "historical sweeps")
        limit = contract.get("limit")
        if not isinstance(limit, int) or not 1 <= limit <= 10000:
            raise PreregistrationRealRefused(
                "data_contract.limit must be an int in [1, 10000]")
        page_cap = contract.get("page_cap")
        if not isinstance(page_cap, int) or not 1 <= page_cap <= 20:
            raise PreregistrationRealRefused(
                "data_contract.page_cap must be an int in [1, 20]")
        if contract.get("completion_note") is None:
            raise PreregistrationRealRefused(
                "data_contract.completion_note must record the honest "
                "completion margin (vendor finality is not guaranteed)")
        transport = collection.get("transport") or {}
        patterns = [str(p_) for p_ in (transport.get("allowed_paths") or [])]
        if not any(re.match(pat, _RANGED_PROBE_PATH) for pat in patterns):
            raise PreregistrationRealRefused(
                "transport.allowed_paths must admit the ranged bars "
                f"endpoint {_RANGED_PROBE_PATH} under the ranged contract")

    @staticmethod
    def _validate_collection(collection: Mapping[str, Any]) -> None:
        transport = collection.get("transport") or {}
        hosts = [str(h).lower() for h in (transport.get("allowed_hosts") or [])]
        if not hosts:
            raise PreregistrationRealRefused(
                "transport.allowed_hosts must be non-empty")
        if not set(hosts) <= _DATA_HOSTS:
            raise PreregistrationRealRefused(
                f"allowed_hosts must be a subset of {sorted(_DATA_HOSTS)}")
        if set(hosts) & _TRADING_HOSTS:
            raise PreregistrationRealRefused(
                "trading-API hosts can never be allowed here")
        methods = transport.get("methods")
        if methods != ["GET"]:
            raise PreregistrationRealRefused(
                "transport.methods must be exactly ['GET']")
        if transport.get("redirects") != "forbidden":
            raise PreregistrationRealRefused(
                "transport.redirects must be 'forbidden'")
        paths = transport.get("allowed_paths") or []
        if not paths:
            raise PreregistrationRealRefused(
                "transport.allowed_paths must be non-empty")
        for pat in paths:
            # patterns are regexes anchored with ^...$: strip the leading
            # anchor before the market-data prefix check, then prove the
            # pattern compiles (an invalid pattern must refuse at load)
            bare = str(pat).lstrip("^")
            if not bare.startswith(_PATH_PREFIX):
                raise PreregistrationRealRefused(
                    f"allowed path pattern {pat!r} is outside the "
                    f"market-data prefix {_PATH_PREFIX}")
            try:
                re.compile(str(pat))
            except re.error as exc:
                raise PreregistrationRealRefused(
                    f"allowed path pattern {pat!r} does not compile: {exc}"
                ) from exc
        poll = collection.get("poll_window_et")
        if not (isinstance(poll, list) and len(poll) == 2):
            raise PreregistrationRealRefused(
                "collection.poll_window_et must be [start, end]")
        start = _parse_hhmm(poll[0], "poll window start")
        end = _parse_hhmm(poll[1], "poll window end")
        if not (dt.time(0, 0) < start < end):
            raise PreregistrationRealRefused(
                "poll window must be a non-empty ordered HH:MM range")
        interval = collection.get("poll_interval_seconds")
        if not isinstance(interval, int) or interval <= 0:
            raise PreregistrationRealRefused(
                "poll_interval_seconds must be a positive int")

    # -- v2 views -------------------------------------------------------------

    @property
    def contract_legacy(self) -> bool:
        """True for the pinned LEGACY_INVALID_VENDOR_CONTRACT schema
        (fabricated latest-bar shape) — loadable for evidence
        reproduction, refused for real collection."""
        return bool(getattr(self, "_contract_legacy", True))

    @property
    def data_contract(self) -> Mapping[str, Any]:
        """The ranged daily-bars contract (empty mapping under the legacy
        schema — the legacy contract has no legal data contract)."""
        if self.contract_legacy:
            return {}
        return self._payload["data_contract"]  # type: ignore[index]

    @property
    def page_cap(self) -> int:
        if self.contract_legacy:
            return 1
        return int(self._payload["data_contract"]["page_cap"])  # type: ignore[index]

    @property
    def bars_limit(self) -> int:
        if self.contract_legacy:
            return 1
        return int(self._payload["data_contract"]["limit"])  # type: ignore[index]

    @property
    def dataset_admission(self) -> str:
        """Real scope: the dataset digest is computed from the arriving
        payload at receipt; the receipt chain (cross-verified against the
        forward journal) is its traceability — no pinned hash exists."""
        return "receipt_content_hash"

    @property
    def admitted_dataset_hashes(self) -> tuple[str, ...]:
        """Meaningless in the receipt-content scope; the engine never
        consults it here. Returns empty (not an error) so a stray call is
        visible instead of crashing state reconstruction."""
        return ()

    @property
    def symbols(self) -> tuple[str, ...]:
        d = self._payload["admitted_datasets"][0]  # type: ignore[index]
        return tuple(str(s) for s in d["symbols"])

    @property
    def admitted_symbols(self) -> tuple[str, ...]:
        """The engine's per-symbol admission gate consumes this property;
        the v2 dataset declares a ``symbols`` LIST, so the base single-
        ``symbol`` view would silently return an empty tuple and disable
        the gate. The override keeps the gate live over the preregistered
        symbols."""
        return self.symbols

    @property
    def source_name(self) -> str:
        return "alpaca_iex"

    @property
    def feed(self) -> str:
        return "iex"

    @property
    def provider(self) -> str:
        return str(self._payload["source_authorization"]["provider"])

    @property
    def plan(self) -> str:
        return str(self._payload["source_authorization"]["plan"])

    @property
    def min_trading_days(self) -> int:
        return int(self._payload["real_window"]["min_trading_days"])

    @property
    def calendar_valid_from(self) -> dt.date:
        return _parse_date(
            self._payload["market_clock"]["calendar_valid_from"],  # type: ignore[index]
            "calendar_valid_from")

    @property
    def calendar_valid_until(self) -> dt.date:
        return _parse_date(
            self._payload["market_clock"]["calendar_valid_until"],  # type: ignore[index]
            "calendar_valid_until")

    @property
    def holidays(self) -> frozenset[dt.date]:
        return frozenset(_parse_date(d, "holiday")
                         for d in self._payload["market_clock"]["holidays"])  # type: ignore[index]

    @property
    def half_days(self) -> frozenset[dt.date]:
        return frozenset(_parse_date(d, "half_day")
                         for d in self._payload["market_clock"]["half_days"])  # type: ignore[index]

    @property
    def poll_window_et(self) -> tuple[dt.time, dt.time]:
        poll = self._payload["collection"]["poll_window_et"]  # type: ignore[index]
        return (_parse_hhmm(poll[0], "poll start"),
                _parse_hhmm(poll[1], "poll end"))

    @property
    def poll_interval_seconds(self) -> int:
        return int(self._payload["collection"]["poll_interval_seconds"])  # type: ignore[index]

    @property
    def transport_config(self) -> Mapping[str, Any]:
        return self._payload["collection"]["transport"]  # type: ignore[index]

    # -- loading ---------------------------------------------------------------

    @classmethod
    def load(cls, path: str | Path) -> "PreregistrationReal":
        raw = Path(path).read_bytes()
        try:
            payload = yaml.safe_load(raw.decode("utf-8"))
        except yaml.YAMLError as exc:
            raise PreregistrationRealRefused(
                f"unparsable YAML: {exc}") from exc
        if not isinstance(payload, dict):
            raise PreregistrationRealRefused(
                "preregistration must be a mapping")
        return cls(payload)
