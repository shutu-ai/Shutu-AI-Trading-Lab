"""Current-window incremental market-data update CLI (T3-B of
BUSINESS-V03-OPERATIONAL-ACTIVATION-20261127-R1) — the one command driving
the incremental-update entry (see
``apps/market_gateway/update_session.py``). Offline by default:
``--transport probe`` (default) runs the whole guarded pipeline against
the in-repo deterministic FAKE transport (zero real network) and labels
everything ``FAKE_TRANSPORT_INCREMENTAL``. ``--transport live`` is the
real current-window run and is REFUSED unless BOTH the operator has
pre-set ``CURRENT_DATA_AUTHORIZED=SIGNED`` in the environment AND an
operator-written ``--authorization-record`` JSON whose scope matches the
invocation exactly. The H1 2017-2025 authorization does NOT extend to
current-window dates; the update budget is structurally capped at 6.

Usage::

    python scripts/update_market_data.py --output-dir <dir>
        # probe (default): FAKE_TRANSPORT_INCREMENTAL dry run, default
        # window = yesterday ET minus 10 sessions per the current supply

    python scripts/update_market_data.py --output-dir <dir> \
        --start 2026-06-01 --end 2026-06-12 \
        --calendar-config configs/current_calendar.yaml

    python scripts/update_market_data.py --output-dir <dir> \
        --transport live --authorization-record <record.json>
        # ^ requires the operator-set env signature AND the record;
        #   refuses otherwise (scope mismatch also refuses)

Exit codes: 0 updated, 1 unexpected failure, 2 config refusal (bad
args, calendar config problems, stale/short calendar supply, dirty
target, window outside coverage), 3 live blocked env (credentials not
configured), 4 live authorization refused (env signature, record
missing/invalid/scope mismatch), 5 mid-run update abort (partial audit
written, no manifest).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from apps.market_gateway.update_session import (  # noqa: E402
    AuthorizationRefused,
    BlockedEnv,
    DEFAULT_SESSIONS_LOOKBACK,
    UPDATE_BUDGET_CAP,
    UPDATE_DEFAULT_BUDGET,
    UPDATE_MANIFEST_NAME,
    WINDOW_SOURCE_DEFAULT,
    WINDOW_SOURCE_EXPLICIT,
    UpdateConfig,
    UpdateError,
    UpdateReport,
    load_authorization_record,
    resolve_default_window,
    run_update,
)
from trading_lab.data.calendar import CalendarError  # noqa: E402
from trading_lab.data.historical_calendar import VersionedMarketCalendar  # noqa: E402
from trading_lab.data.historical_calendar_supply import (  # noqa: E402
    CalendarConfigError,
    CalendarSupplyDriftError,
    load_supply_from_config,
)

EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_CONFIG_REFUSED = 2
EXIT_BLOCKED_ENV = 3
EXIT_AUTHORIZATION_REFUSED = 4
EXIT_UPDATE_ABORTED = 5

DEFAULT_CALENDAR_CONFIG = REPO_ROOT / "configs" / "current_calendar.yaml"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="update_market_data",
        description=(
            "Incremental current-window daily-bar update into the "
            "historical_research namespace (SPY+QQQ, operator-supplied "
            "current calendar, request budget structurally capped at "
            f"{UPDATE_BUDGET_CAP}; probe mode is a "
            "FAKE_TRANSPORT_INCREMENTAL dry run with zero real network). "
            "Current-window dates are a SEPARATE authorization from the "
            "H1 2017-2025 window."
        ),
    )
    parser.add_argument(
        "--symbol",
        action="append",
        required=True,
        metavar="SYMBOL",
        help="authorized symbol; pass twice — SPY and QQQ (both together)",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        metavar="DIR",
        help="root for the historical_research namespace output (must be "
        "clean — an existing manifest or bars file refuses the run)",
    )
    parser.add_argument(
        "--calendar-config",
        default=str(DEFAULT_CALENDAR_CONFIG),
        metavar="PATH",
        help="operator-maintained current-calendar YAML "
        "(default: configs/current_calendar.yaml)",
    )
    parser.add_argument(
        "--start",
        default=None,
        metavar="YYYY-MM-DD",
        help="window start, ET session-date semantics (default: "
        f"{DEFAULT_SESSIONS_LOOKBACK} sessions before --end per the "
        "current supply)",
    )
    parser.add_argument(
        "--end",
        default=None,
        metavar="YYYY-MM-DD",
        help="window end, ET session-date semantics (default: yesterday ET)",
    )
    parser.add_argument(
        "--budget",
        type=int,
        default=UPDATE_DEFAULT_BUDGET,
        metavar="N",
        help=f"request budget, 1..{UPDATE_BUDGET_CAP} "
        f"(default {UPDATE_DEFAULT_BUDGET}; the cap is structural)",
    )
    parser.add_argument(
        "--transport",
        choices=("probe", "live"),
        default="probe",
        help="probe = in-repo FAKE transport (default); live = real "
        "current-window run, refused unless CURRENT_DATA_AUTHORIZED=SIGNED "
        "AND a matching --authorization-record is supplied",
    )
    parser.add_argument(
        "--authorization-record",
        default=None,
        metavar="PATH",
        help="operator-written authorization-record JSON (required for "
        "--transport live; scope must match this invocation exactly)",
    )
    return parser


def _print_json(payload: Mapping[str, object]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


def _summary(report: UpdateReport) -> Mapping[str, object]:
    assert report.manifest is not None  # COLLECTED implies manifest
    manifest = report.manifest
    return {
        "status": "COLLECTED",
        "entry": manifest["entry"],
        "manifest_path": str(report.manifest_path),
        "transport": manifest["transport"],
        "calendar_supply": manifest["calendar_supply"],
        "window": manifest["window"],
        "budget": manifest["budget"],
        "bars_paths": [str(p) for p in report.bars_paths],
        "symbols": {
            symbol: {
                "row_count": doc["row_count"],
                "expected_sessions": doc["expected_sessions"],
                "missing_sessions": len(doc["missing_sessions"]),
            }
            for symbol, doc in manifest["symbols"].items()
        },
        "admission": manifest["admission"]["status"],
        "license": manifest["license"]["status"],
        "pit_level": manifest["pit"]["level"],
    }


def main(argv: list[str] | None = None, *, environ: Mapping[str, str] | None = None,
         now_et: dt.datetime | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        supply = load_supply_from_config(args.calendar_config)
    except (OSError, CalendarConfigError, CalendarSupplyDriftError, CalendarError) as exc:
        _print_json({"status": "CONFIG_REFUSED", "reason": f"CALENDAR_CONFIG: {exc}"})
        return EXIT_CONFIG_REFUSED
    try:
        calendar = VersionedMarketCalendar.from_supply(supply)
    except CalendarError as exc:
        _print_json({"status": "CONFIG_REFUSED", "reason": f"CALENDAR_CONFIG: {exc}"})
        return EXIT_CONFIG_REFUSED

    window_source = WINDOW_SOURCE_EXPLICIT
    if (args.start is None) != (args.end is None):
        _print_json(
            {
                "status": "CONFIG_REFUSED",
                "reason": "BAD_WINDOW: provide both --start and --end, or "
                "neither (default: yesterday ET minus "
                f"{DEFAULT_SESSIONS_LOOKBACK} sessions per the current supply)",
            }
        )
        return EXIT_CONFIG_REFUSED
    if args.start is not None:
        try:
            start = dt.date.fromisoformat(args.start)
            end = dt.date.fromisoformat(args.end)
        except ValueError as exc:
            _print_json({"status": "CONFIG_REFUSED", "reason": f"BAD_WINDOW: {exc}"})
            return EXIT_CONFIG_REFUSED
    else:
        try:
            start, end = resolve_default_window(calendar, now_et=now_et)
        except UpdateError as exc:
            _print_json({"status": "CONFIG_REFUSED", "reason": str(exc)})
            return EXIT_CONFIG_REFUSED
        window_source = WINDOW_SOURCE_DEFAULT

    authorization_record = None
    if args.authorization_record is not None:
        try:
            authorization_record = load_authorization_record(args.authorization_record)
        except AuthorizationRefused as exc:
            _print_json({"status": "AUTHORIZATION_REFUSED", "reason": str(exc)})
            return EXIT_AUTHORIZATION_REFUSED

    try:
        config = UpdateConfig(
            symbols=tuple(args.symbol),
            start=start,
            end=end,
            output_dir=Path(args.output_dir),
            calendar_supply=supply,
            transport=args.transport,
            request_budget=args.budget,
            window_source=window_source,
            authorization_record=authorization_record,
        )
    except (ValueError, UpdateError) as exc:
        _print_json({"status": "CONFIG_REFUSED", "reason": str(exc)})
        return EXIT_CONFIG_REFUSED

    try:
        report = run_update(config, environ=environ)
    except AuthorizationRefused as exc:
        _print_json({"status": "AUTHORIZATION_REFUSED", "reason": str(exc)})
        return EXIT_AUTHORIZATION_REFUSED
    except BlockedEnv as exc:
        _print_json({"status": "BLOCKED_ENV", "reason": str(exc)})
        return EXIT_BLOCKED_ENV
    except UpdateError as exc:
        _print_json({"status": "CONFIG_REFUSED", "reason": str(exc)})
        return EXIT_CONFIG_REFUSED
    if report.ok:
        _print_json(_summary(report))
        return EXIT_OK
    assert report.partial_audit is not None  # ABORTED implies audit dump
    _print_json(
        {
            "status": "UPDATE_ABORTED",
            "reason": report.partial_audit.get("reason"),
            "detail": report.partial_audit.get("detail"),
            "budget_spent": report.partial_audit["budget"]["spent"],
            "partial_audit_path": str(report.partial_audit_path),
            "manifest_written": False,
            "note": (
                f"no historical_research/{UPDATE_MANIFEST_NAME} was written; "
                "the manifest's existence is the success marker"
            ),
        }
    )
    return EXIT_UPDATE_ABORTED


if __name__ == "__main__":
    sys.exit(main())
