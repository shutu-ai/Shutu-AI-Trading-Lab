"""Official M3.5-S8 read-only real-shadow runner (S8 plane).

Subcommands:

- ``check-config``: load + validate the frozen v2 real preregistration,
  build the S8 code identity, print the frozen facts (offline, no auth).
- ``selftest``: drive the WHOLE S8 pipeline offline over the committed
  fixture table (guarded client -> feed -> quality -> engine -> journal +
  receipt chains -> window facts -> eligibility). Fixture facts are
  synthetic: PENDING/PASS claims must refuse. Writes evidence.
- ``collect``: REAL collection. Requires BOTH operator gates — the
  authorization token naming the signed approval AND market-data
  credentials visible in the environment. Missing credentials are the
  honest ``BLOCKED_ENV`` outcome (exit 3), a wrong/missing token is
  ``AUTHORIZATION_REFUSED`` (exit 4). One cycle per invocation
  (``--once``); the operator schedules cycles across the real window and
  completes it explicitly (``--complete``).
- ``status``: window facts + eligibility from the chains (no claim).

STRICT READ-ONLY: no broker adapter exists in this plane; the guarded
client cannot reach a trading-API host or send a non-GET request even if
misconfigured. Credentials are read only by the collector process to
build request headers and are never logged, receipted, or committed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from apps.market_gateway.feed_session import (  # noqa: E402
    AuthorizationRefused,
    FORWARD_STATE_SUBDIR,
    OPERATOR_AUTHORIZATION_TOKEN,
    evaluate_window,
    preflight,
    run_collection_cycle,
    window_facts_from_journal,
)
from apps.market_gateway.offline_fixtures import (  # noqa: E402
    build_selftest_feed,
    load_fixture_table,
)
from apps.market_gateway.prereg_real import (  # noqa: E402
    PreregistrationReal,
)
from apps.trading_daemon.identity import (  # noqa: E402
    build_s8_forward_identity,
    git_facts,
)
from apps.trading_daemon.journal import verify_journal_file  # noqa: E402

PREREG_PATH = REPO_ROOT / "configs" / "forward_observation_s8_real.yaml"
FIXTURE_PATH = REPO_ROOT / "apps" / "market_gateway" / "fixtures" / \
    "selftest_bars.json"
EVIDENCE_DIR = REPO_ROOT / "artifacts" / "evidence" / "M3.5" / "s8"
DEFAULT_STATE_DIR = REPO_ROOT / "artifacts" / "state" / "s8-shadow"

EXIT_OK = 0
EXIT_BLOCKED_ENV = 3
EXIT_AUTHORIZATION_REFUSED = 4
EXIT_FAILURE = 1


def _print_json(payload: dict) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


def _identity():
    commit, tree = git_facts(REPO_ROOT)
    return build_s8_forward_identity(
        REPO_ROOT, git_commit=commit, git_tree=tree)


def cmd_check_config() -> int:
    prereg = PreregistrationReal.load(PREREG_PATH)
    identity = _identity()
    _print_json({
        "protocol_id": prereg.forward_protocol_id,
        "protocol_hash": prereg.hash,
        "environment": prereg.environment,
        "mode": "REAL_SHADOW_READ_ONLY",
        "symbols": list(prereg.symbols),
        "feed": prereg.feed,
        "plan": prereg.plan,
        "dataset_admission": prereg.dataset_admission,
        "min_trading_days": prereg.min_trading_days,
        "calendar": {
            "valid_from": prereg.calendar_valid_from.isoformat(),
            "valid_until": prereg.calendar_valid_until.isoformat(),
            "holidays": sorted(d.isoformat() for d in prereg.holidays),
            "half_days": sorted(d.isoformat() for d in prereg.half_days),
        },
        "identity_schema": identity.schema,
        "identity_code_hash": identity.code_hash,
        "identity_files": len(identity.files),
        "read_only": True,
        "paper_write": "NOT_AUTHORIZED",
    })
    return EXIT_OK


def cmd_selftest(state_dir: Path, evidence_dir: Path | None) -> int:
    from apps.market_gateway.feed_session import run_offline_selftest
    prereg = PreregistrationReal.load(PREREG_PATH)
    identity = _identity()
    result = run_offline_selftest(
        prereg=prereg, state_dir=state_dir, identity=identity,
        fixture_path=FIXTURE_PATH)

    dup = result["duplicate_cycle"]
    facts = result["facts"]
    problems: list[str] = []
    if not result["journal_ok"]:
        problems.append(f"journal failed verification: "
                        f"{result['journal_msg']}")
    if dup["new_scores"] != 0:
        problems.append(
            f"redelivery scored {dup['new_scores']} NEW events — "
            "idempotency failure")
    if dup["engine_duplicates"] < dup["events_emitted"]:
        problems.append(
            "redelivery was not fully idempotent: "
            f"{dup['engine_duplicates']}/{dup['events_emitted']}")
    if not facts["receipt_evidence_ok"]:
        problems.append("receipt chain cross-check failed")
    for claim, refusal in result["claim_refusals"].items():
        if "INTEGRITY FAILURE" in refusal:
            problems.append(
                f"synthetic facts did NOT refuse claim {claim}")
    if facts["trading_days_observed"] != len(
            load_fixture_table(FIXTURE_PATH)["cycles"]):
        problems.append(
            "full-coverage day count drifted from the fixture table")

    payload = {
        "selftest": "S8-READ-ONLY-PIPELINE-OFFLINE",
        "events_synthetic": True,
        "protocol_id": prereg.forward_protocol_id,
        "protocol_hash": prereg.hash,
        "identity_code_hash": identity.code_hash,
        "cycles": result["cycles"],
        "duplicate_cycle": dup,
        "facts": facts,
        "eligibility": result["eligibility"],
        "claim_refusals": result["claim_refusals"],
        "journal_ok": result["journal_ok"],
        "journal_msg": result["journal_msg"],
        "problems": problems,
        "outcome": ("OFFLINE_HARNESS_PASS_WITH_SCOPE" if not problems
                    else "SELFTEST_FAILED"),
        "honesty": "fixture events are never real trading days; they can "
                   "never mint PENDING_FORWARD_WINDOW or PASS",
    }
    _print_json(payload)
    if evidence_dir is not None:
        evidence_dir.mkdir(parents=True, exist_ok=True)
        (evidence_dir / "selftest-result.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8")
        print(f"wrote {evidence_dir / 'selftest-result.json'}")
    return EXIT_FAILURE if problems else EXIT_OK


def cmd_collect(state_dir: Path, once: bool, complete: bool) -> int:
    prereg = PreregistrationReal.load(PREREG_PATH)
    identity = _identity()
    try:
        gate = preflight(operator_authorization=os.environ.get(
            "S8_OPERATOR_AUTHORIZATION"))
    except AuthorizationRefused as exc:
        _print_json({"collect": "AUTHORIZATION_REFUSED", "reason": str(exc)})
        return EXIT_AUTHORIZATION_REFUSED
    if gate.status != "READY":
        _print_json({
            "collect": "BLOCKED_ENV",
            "reason": gate.reason,
            "credential_env_visible": gate.credential_env_visible,
            "note": "no legal data access configured — the collector must "
                    "not attempt real connections (S8 approval condition 3)",
        })
        return EXIT_BLOCKED_ENV

    # credentials exist for the collector process only at header-build
    # time; they are never printed, receipted, or committed
    from apps.market_gateway.alpaca_feed import (
        AlpacaIexDailyBarFeed,
        CollectorCodeIdentity,
    )
    from apps.market_gateway.http_client import GuardedGetClient
    transport = prereg.transport_config
    client = GuardedGetClient(
        allowed_hosts=list(transport.get("allowed_hosts") or ()),
        allowed_paths=list(transport.get("allowed_paths") or ()),
        timeout_seconds=float(
            prereg.payload["collection"].get("poll_timeout_seconds", 20)),
    )
    feed = AlpacaIexDailyBarFeed(
        client=client, prereg=prereg, now_fn=_real_now,
        code_identity=CollectorCodeIdentity(
            schema=identity.schema, code_hash=identity.code_hash))

    session_index = _completed_sessions(state_dir) + 1
    result = run_collection_cycle(
        feed=feed, prereg=prereg, state_dir=state_dir, identity=identity,
        session_index=session_index)
    _print_json({"collect": "CYCLE_DONE", **result})

    if complete:
        summary = _complete_window(state_dir, prereg, identity)
        _print_json({"window_completion": summary})
    return EXIT_OK


def _real_now():
    import datetime as dt
    return dt.datetime.now(dt.timezone.utc)


def _completed_sessions(state_dir: Path) -> int:
    journal = state_dir / FORWARD_STATE_SUBDIR / "journal.jsonl"
    if not journal.exists():
        return 0
    from apps.trading_daemon.journal import read_entries
    return sum(
        1 for e in read_entries(journal)
        if e.get("event_type") == "SESSION_COMPLETED")


def _complete_window(state_dir: Path, prereg, identity):
    """Operator-requested window completion: finish the open session,
    anchor the journal + receipt chain, compute final facts + eligibility."""
    from apps.trading_daemon.driver import run_replay
    summary = run_replay(
        state_dir=state_dir / FORWARD_STATE_SUBDIR, prereg=prereg,
        events=[], session_index=_completed_sessions(state_dir) + 1,
        complete=True, identity=identity)
    facts = window_facts_from_journal(state_dir, prereg,
                                      events_synthetic=False)
    harness = {
        "harness_complete": True,
        "negatives_passed": None,
        "replay_reproducible": True,
        "journal_verified": facts["journal_verified"],
        "no_broker_writes": True,
    }
    claim = None
    if facts["trading_days_observed"] >= prereg.min_trading_days:
        claim = "PASS"  # attempted; the machine refuses unless every
        # preregistered requirement holds (recoveries, audits, 0 orders)
    try:
        eligibility = evaluate_window(prereg=prereg, harness=harness,
                                      facts=facts, claim=claim)
        claim_error = None
    except Exception as exc:
        eligibility = evaluate_window(prereg=prereg, harness=harness,
                                      facts=facts, claim=None)
        claim_error = f"{type(exc).__name__}: {exc}"
    payload = {
        "session_completed": summary,
        "facts": facts,
        "eligibility": eligibility,
        "claim_attempt": claim,
        "claim_error": claim_error,
    }
    evidence = EVIDENCE_DIR / "real-forward-window-status.json"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8")
    return payload


def cmd_status(state_dir: Path) -> int:
    prereg = PreregistrationReal.load(PREREG_PATH)
    facts = window_facts_from_journal(state_dir, prereg,
                                      events_synthetic=False)
    harness = {
        "harness_complete": True,
        "negatives_passed": None,
        "replay_reproducible": True,
        "journal_verified": facts["journal_verified"],
        "no_broker_writes": True,
    }
    eligibility = evaluate_window(prereg=prereg, harness=harness, facts=facts)
    _print_json({"facts": facts, "eligibility": eligibility})
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="run_m35_s8_shadow_real",
        description="M3.5-S8 read-only real-shadow runner "
                    "(REAL_SHADOW_READ_ONLY; no broker write path exists)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check-config", help="validate the frozen v2 prereg")
    p_self = sub.add_parser(
        "selftest", help="offline pipeline proof over the committed fixture")
    p_self.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIR)
    p_self.add_argument("--evidence-dir", type=Path, default=EVIDENCE_DIR)
    p_self.add_argument(
        "--no-evidence", action="store_true",
        help="do not write the selftest evidence file (tests)")
    p_col = sub.add_parser(
        "collect", help="one REAL collection cycle (operator-gated)")
    p_col.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIR)
    p_col.add_argument("--once", action="store_true",
                       help="exactly one poll cycle (default)")
    p_col.add_argument("--complete", action="store_true",
                       help="also complete + anchor the window")
    p_sta = sub.add_parser(
        "status", help="window facts + eligibility from the chains")
    p_sta.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIR)
    args = parser.parse_args(argv)

    if args.command == "check-config":
        return cmd_check_config()
    if args.command == "selftest":
        evidence_dir = None if args.no_evidence else args.evidence_dir
        return cmd_selftest(args.state_dir, evidence_dir)
    if args.command == "collect":
        return cmd_collect(args.state_dir, once=args.once,
                           complete=args.complete)
    if args.command == "status":
        return cmd_status(args.state_dir)
    return EXIT_FAILURE


if __name__ == "__main__":
    sys.exit(main())
