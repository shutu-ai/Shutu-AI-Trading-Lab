"""Restricted historical snapshot collection CLI (BUSINESS-MVP-V02
workflow A2) — the one command driving the historical_research namespace
entry. Offline by default: ``--transport probe`` (default) runs the
whole guarded pipeline against the in-repo deterministic FAKE transport
(zero real network). ``--transport live`` is the real Alpaca run and is
REFUSED unless the operator has pre-set ``H1_REAL_API_AUTHORIZED=SIGNED``
in the environment (a separate, explicit human act — this script never
sets it, never reads or prints credential values).

Usage::

    python scripts/collect_historical_snapshot.py \
        --symbol SPY --symbol QQQ \
        --output-dir <dir>            # probe (default): FAKE_TRANSPORT dry run

    python scripts/collect_historical_snapshot.py \
        --symbol SPY --symbol QQQ --transport live --output-dir <dir> \
        --authorization-record <operator-written.json>
        # ^ requires BOTH the operator-set env signature AND the signed
        # authorization record (the env var alone never substitutes);
        # the record's scope is validated against the frozen window

Exit codes: 0 collected, 1 unexpected failure, 2 config/usage refusal,
3 live blocked env (credentials not configured), 4 live authorization
refused, 5 mid-run collection abort (partial audit written, no manifest),
6 collection authorization-facts refused (live without facts / record
scope mismatch / invalid record / facts on a probe run).
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

from apps.market_gateway.collection_session import (  # noqa: E402
    AdmissionFacts,
    AuthorizationFactsRefused,
    AuthorizationRefused,
    BlockedEnv,
    CollectionConfig,
    CollectionError,
    CollectionReport,
    LicenseFacts,
    MANIFEST_NAME,
    NAMESPACE_DIRNAME,
    TRANSPORT_LIVE,
    TRANSPORT_PROBE,
    parse_authorization_record,
    run_collection,
)

EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_CONFIG_REFUSED = 2
EXIT_BLOCKED_ENV = 3
EXIT_AUTHORIZATION_REFUSED = 4
EXIT_COLLECTION_ABORTED = 5
EXIT_COLLECTION_REFUSED = 6


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="collect_historical_snapshot",
        description=(
            "Restricted historical daily-bar collection into the "
            "historical_research namespace (SPY+QQQ, frozen license "
            "window, request budget 30; probe mode is a FAKE_TRANSPORT "
            "dry run with zero real network)."
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
        "--start",
        default="2017-01-01",
        metavar="YYYY-MM-DD",
        help="window start, ET session-date semantics (default 2017-01-01)",
    )
    parser.add_argument(
        "--end",
        default="2025-12-31",
        metavar="YYYY-MM-DD",
        help="window end, ET session-date semantics (default 2025-12-31)",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        metavar="DIR",
        help="root for the historical_research namespace output",
    )
    parser.add_argument(
        "--transport",
        choices=(TRANSPORT_PROBE, TRANSPORT_LIVE),
        default=TRANSPORT_PROBE,
        help="probe = in-repo FAKE transport (default); live = real run, "
        "refused unless H1_REAL_API_AUTHORIZED=SIGNED",
    )
    parser.add_argument(
        "--authorization-record",
        default=None,
        metavar="PATH",
        help="operator-written JSON authorization record (authorization_ref, "
        "attested_by, attested_at, calendar_license_note, scope echo, "
        "restricted_research_permitted); REQUIRED for live runs — the env "
        "signature alone never substitutes for the signed record; refused "
        "on probe runs (probe artifacts never bind attestation)",
    )
    return parser


def _load_authorization_record(
    record_path: str,
) -> tuple[LicenseFacts, AdmissionFacts] | None:
    """Read + parse the operator-written authorization record; on any
    refusal print the COLLECTION_REFUSED payload and return None (the
    caller must then return EXIT_COLLECTION_REFUSED)."""
    try:
        payload = json.loads(Path(record_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        _print_json({
            "status": "COLLECTION_REFUSED",
            "reason": "AUTHORIZATION_RECORD_INVALID",
            "detail": f"cannot read authorization record {record_path}: {exc}",
        })
        return None
    try:
        parsed = parse_authorization_record(payload)
    except CollectionError as exc:
        _print_json({
            "status": "COLLECTION_REFUSED",
            "reason": exc.reason,
            "detail": str(exc),
        })
        return None
    return parsed.license, parsed.admission


def _print_json(payload: Mapping[str, object]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


def _summary(report: CollectionReport) -> Mapping[str, object]:
    assert report.manifest is not None  # COLLECTED implies manifest
    manifest = report.manifest
    return {
        "status": "COLLECTED",
        "manifest_path": str(report.manifest_path),
        "transport": manifest["transport"],
        "calendar_supply": manifest["calendar_supply"],
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


def main(argv: list[str] | None = None, *, environ: Mapping[str, str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    license_facts: LicenseFacts | None = None
    admission_facts: AdmissionFacts | None = None
    if args.authorization_record is not None:
        parsed = _load_authorization_record(args.authorization_record)
        if parsed is None:
            return EXIT_COLLECTION_REFUSED
        license_facts, admission_facts = parsed
    try:
        config = CollectionConfig(
            symbols=tuple(args.symbol),
            start=dt.date.fromisoformat(args.start),
            end=dt.date.fromisoformat(args.end),
            output_dir=Path(args.output_dir),
            transport=args.transport,
        )
    except (ValueError, CollectionError) as exc:
        _print_json({"status": "CONFIG_REFUSED", "reason": str(exc)})
        return EXIT_CONFIG_REFUSED
    try:
        report = run_collection(
            config,
            environ=environ,
            license_facts=license_facts,
            admission_facts=admission_facts,
        )
    except AuthorizationFactsRefused as exc:
        _print_json({
            "status": "COLLECTION_REFUSED",
            "reason": exc.reason,
            "detail": str(exc),
        })
        return EXIT_COLLECTION_REFUSED
    except AuthorizationRefused as exc:
        _print_json({"status": "AUTHORIZATION_REFUSED", "reason": str(exc)})
        return EXIT_AUTHORIZATION_REFUSED
    except BlockedEnv as exc:
        _print_json({"status": "BLOCKED_ENV", "reason": str(exc)})
        return EXIT_BLOCKED_ENV
    except CollectionError as exc:
        _print_json({"status": "CONFIG_REFUSED", "reason": str(exc)})
        return EXIT_CONFIG_REFUSED
    if report.ok:
        _print_json(_summary(report))
        return EXIT_OK
    assert report.partial_audit is not None  # ABORTED implies audit dump
    _print_json(
        {
            "status": "COLLECTION_ABORTED",
            "reason": report.partial_audit.get("reason"),
            "detail": report.partial_audit.get("detail"),
            "budget_spent": report.partial_audit["budget"]["spent"],
            "partial_audit_path": str(report.partial_audit_path),
            "manifest_written": False,
            "note": (
                f"no {NAMESPACE_DIRNAME}/{MANIFEST_NAME} was written; the "
                "manifest's existence is the success marker"
            ),
        }
    )
    return EXIT_COLLECTION_ABORTED


if __name__ == "__main__":
    sys.exit(main())
