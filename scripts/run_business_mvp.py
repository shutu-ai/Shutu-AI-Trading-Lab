#!/usr/bin/env python3
"""Business MVP — one-command offline replay and the V0.3 daily cycle.

    python scripts/run_business_mvp.py --mode replay --fixture demo \
        --output-dir <run-dir>
    python scripts/run_business_mvp.py --mode historical-replay \
        --snapshot-dir <dir> --output-dir <run-dir>
    python scripts/run_business_mvp.py --mode daily --asof <ISO-8601> \
        --snapshot-dir <dir> [--info-file <f>] --state-dir <dir> \
        --output-dir <dir>

Every mode is offline: no network, no keys, no real broker, no paid LLM.
  SYNTHETIC_OFFLINE_ONLY / EXPLORATORY · AI_PROVIDER=MOCK/RULE ·
  EXECUTION_BACKEND=FAKE_BROKER / MOCK_ONLY
A business demo PASS is a product-integration result — never strategy
effectiveness, never formal stage acceptance. The daily mode records
CALENDAR_COVERAGE_BLOCKED (never fabricates sessions) when the asof lies
outside the snapshot's session supply, and PENDING decisions are never
filled before the market clock reaches the next session open.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from trading_lab.business.config import BusinessConfig, load_config  # noqa: E402
from trading_lab.business.daily import (  # noqa: E402
    DAILY_WORKFLOW_VERSION,
    DailyWorkflow,
    DailyWorkflowHalt,
)
from trading_lab.business.replay import REPLAY_VERSION, run_replay  # noqa: E402

DEFAULT_CONFIG = REPO / "configs/business_mvp_demo.yaml"
DEFAULT_PROTOCOL = REPO / "configs/business_mvp_protocol.yaml"

MODES = ("replay", "historical-replay", "daily")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="run_business_mvp",
        description="Business MVP offline replay (SYNTHETIC_OFFLINE_ONLY / "
                    "exploratory historical snapshot) and daily cycle")
    parser.add_argument("--mode", default="replay", choices=list(MODES),
                        help="'replay' = synthetic demo fixture; "
                             "'historical-replay' = collected snapshot dir; "
                             "'daily' = one V0.3 daily decision cycle")
    parser.add_argument("--fixture", default="demo",
                        help="only the built-in 'demo' fixture exists")
    parser.add_argument("--output-dir", required=True,
                        help="run output directory (created if missing)")
    parser.add_argument("--snapshot-dir", default=None,
                        help="historical_research namespace root "
                             "(required for historical-replay and daily)")
    parser.add_argument("--asof", default=None,
                        help="daily decision instant, ISO-8601 with UTC "
                             "offset (required for --mode daily)")
    parser.add_argument("--state-dir", default=None,
                        help="persistent daily account state directory "
                             "(required for --mode daily)")
    parser.add_argument("--info-file", default=None,
                        help="local timestamped information events file "
                             "(JSONL/JSON/CSV; optional)")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG),
                        help="pinned business config YAML")
    parser.add_argument("--protocol", default=str(DEFAULT_PROTOCOL),
                        help="demo evaluation protocol YAML")
    return parser.parse_args(argv)


def _fail(message: str) -> int:
    print(f"REFUSED: {message}", file=sys.stderr)
    return 2


def _parse_asof(raw: str) -> dt.datetime | None:
    """ISO-8601 with an explicit UTC offset; naive/unparsable refuse."""
    text = raw.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(dt.timezone.utc)


def _cycle_to_report_shape(record: dict[str, object]) -> dict[str, object]:
    """Map a DailyWorkflow cycle record onto the daily_report CYCLE_KEYS
    contract (field names differ slightly between the two modules)."""
    return {
        "asof_utc": record.get("asof_utc"),
        "regime": record.get("regime"),
        "chosen": record.get("chosen_strategy_id") or record.get("chosen"),
        "target": record.get("target"),
        "action": record.get("action"),
        "risk_reasons": record.get("risk_reasons")
        or record.get("reasons") or (),
        "cash": record.get("cash"),
        "positions": record.get("positions"),
        "equity": record.get("equity"),
        "rationale": record.get("rationale"),
    }


def _write_daily_outputs(output_dir: Path, workflow: DailyWorkflow,
                         record: dict[str, object], replayed: bool,
                         asof: dt.datetime, command: str) -> Path:
    """summary.json + full cycle JSONL + self-contained daily HTML."""
    output_dir.mkdir(parents=True, exist_ok=True)
    data_block = record.get("data") or {}
    summary = {
        "mode": "daily",
        "workflow_version": DAILY_WORKFLOW_VERSION,
        "asof_utc": asof.isoformat(),
        "cycle_id": record.get("cycle_id"),
        "action": record.get("action"),
        "idempotent_replay": replayed,
        "pending_open": workflow.pending_count,
        "data_admission": data_block,
        "honesty_labels": {
            "EXECUTION_BACKEND": "FAKE_BROKER",
            "BROKER_BEHAVIOR": "MOCK_ONLY",
            "AI_PROVIDER": "MOCK/RULE",
            "data": "OFFLINE_LOCAL_SNAPSHOT_ONLY",
            "performance": "MOCK_ACCOUNT_ONLY — never backtest equity, "
                           "never strategy effectiveness",
        },
        "record": record,
    }
    summary_path = output_dir / "summary.json"
    summary_path.write_text(
        json.dumps(summary, sort_keys=True, ensure_ascii=False, default=str),
        encoding="utf-8")
    (output_dir / "cycles.jsonl").write_text(
        "\n".join(json.dumps(r, sort_keys=True, ensure_ascii=False,
                             default=str) for r in workflow.records) + "\n",
        encoding="utf-8")
    # self-contained daily HTML report (T3-A operational activation)
    from trading_lab.business.daily_report import render_daily_report

    run_meta = {
        "run_id": record.get("cycle_id"),
        "data_source": "OFFLINE",
        "admission_level": (data_block.get("admission", {})
                            .get("status", "NOT_RESEARCH_ADMITTED")
                            if isinstance(data_block, dict) else "—"),
        "license_level": "LICENSE_UNVERIFIED",
        "info_status": record.get("info_status", "NO_INFORMATION"),
        "data_cutoff_utc": record.get("data_cutoff_utc") or asof.isoformat(),
        "missing_data": record.get("missing_data", ""),
        "command": command,
        "mock_book": {
            "cash": record.get("cash"),
            "positions": record.get("positions"),
            "equity": record.get("equity"),
            "action": record.get("action"),
            "note": "MOCK_ACCOUNT_ONLY (FAKE_BROKER / MOCK_ONLY)",
        },
        "backtest_book": {
            "note": "no backtest book in daily mode (read-only analysis "
                    "+ mock account only)",
        },
    }
    cycles = [_cycle_to_report_shape(r) for r in workflow.records]
    (output_dir / "report.html").write_text(
        render_daily_report(cycles, run_meta=run_meta), encoding="utf-8")
    return summary_path


def _run_daily(args: argparse.Namespace, config: BusinessConfig) -> int:
    if not args.asof:
        return _fail("--mode daily requires --asof <ISO-8601>.")
    if not args.snapshot_dir:
        return _fail("--mode daily requires --snapshot-dir.")
    if not args.state_dir:
        return _fail("--mode daily requires --state-dir "
                     "(persistent account state).")
    asof = _parse_asof(args.asof)
    if asof is None:
        return _fail(f"--asof {args.asof!r} is not a timezone-aware "
                     "ISO-8601 instant (naive/unparsable refused).")
    workflow = DailyWorkflow.open(
        config=config, snapshot_dir=Path(args.snapshot_dir),
        state_dir=Path(args.state_dir),
        info_file=Path(args.info_file) if args.info_file else None)
    try:
        result = workflow.run_daily_cycle(asof=asof)
    except DailyWorkflowHalt as exc:
        print(f"HALT: {exc}", file=sys.stderr)
        print("  operator decision required: inspect the state dir, "
              "resolve, then restart (HALT is latched in the state file).",
              file=sys.stderr)
        return 4
    output_dir = Path(args.output_dir)
    command = (f"python scripts/run_business_mvp.py --mode daily "
               f"--asof {args.asof} --snapshot-dir {args.snapshot_dir} "
               f"--state-dir {args.state_dir} --output-dir {output_dir}")
    summary_path = _write_daily_outputs(
        output_dir, workflow, result.record, result.replayed, asof, command)
    record = result.record
    print(f"[{DAILY_WORKFLOW_VERSION}] daily cycle complete "
          f"({'replayed' if result.replayed else 'applied'})")
    print(f"  cycle_id : {record.get('cycle_id')}")
    print(f"  action   : {record.get('action')} "
          f"(decision={record.get('decision_status')})")
    print(f"  session  : {record.get('session_date')} "
          f"info={record.get('info_status')}")
    print(f"  summary  : {summary_path}")
    print(f"  cycles   : {output_dir / 'cycles.jsonl'}")
    print("  labels   : SYNTHETIC_OFFLINE_ONLY / EXPLORATORY · "
          "AI_PROVIDER=MOCK/RULE · EXECUTION_BACKEND=FAKE_BROKER/MOCK_ONLY")
    print("  honesty  : BUSINESS_DEMO_ONLY — mock account PnL is not "
          "strategy effectiveness; real provider and real forward days "
          "remain UNVERIFIED")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.mode not in MODES:
        return _fail(f"mode {args.mode!r} is not authorized "
                     f"(only {', '.join(MODES)}); other modes fail closed.")
    if args.mode == "historical-replay" and not args.snapshot_dir:
        return _fail("--mode historical-replay requires --snapshot-dir.")
    if args.mode == "replay" and args.fixture != "demo":
        return _fail(f"fixture {args.fixture!r} does not exist (only 'demo').")

    config = load_config(Path(args.config))
    if config.mode != "replay":
        return _fail("config mode is not 'replay'.")

    if args.mode == "daily":
        return _run_daily(args, config)

    output_dir = Path(args.output_dir)
    artifacts = run_replay(
        config=config,
        protocol_path=Path(args.protocol),
        output_dir=output_dir,
        command=f"python scripts/run_business_mvp.py --mode {args.mode} "
                + (f"--fixture {args.fixture} " if args.mode == "replay"
                   else f"--snapshot-dir {args.snapshot_dir} ")
                + f"--output-dir {output_dir}",
        snapshot_dir=Path(args.snapshot_dir)
        if args.mode == "historical-replay" else None,
        info_file=Path(args.info_file) if args.info_file else None,
    )
    print(f"[{REPLAY_VERSION}] run complete ({args.mode})")
    print(f"  run_id      : {artifacts.run_id}")
    print(f"  run_digest  : {artifacts.run_digest}")
    print(f"  summary     : {artifacts.summary_path}")
    print(f"  report      : {artifacts.output_dir / 'report.html'}")
    print("  labels      : SYNTHETIC_OFFLINE_ONLY / EXPLORATORY · "
          "AI_PROVIDER=MOCK/RULE · EXECUTION_BACKEND=FAKE_BROKER/MOCK_ONLY")
    print("  honesty     : BUSINESS_DEMO_ONLY — not strategy effectiveness, "
          "not formal stage acceptance, real broker NOT verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
