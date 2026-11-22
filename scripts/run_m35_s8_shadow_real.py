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
  Integrity is fail-closed: when the persisted completion evidence
  (evaluation snapshot + its committed ``WINDOW_COMPLETED`` chain
  record) fails verification, ``status`` exits non-zero — exit codes are
  part of the machine contract and must never be interpreted as
  "eligible" (eligibility is a JSON field, an exit code is not).

Exit codes (stable, distinguishable; the T7 contract):

- ``0`` ``EXIT_OK`` — the requested command ran; integrity verified or
  a legal not-started / in-progress query. NOT an eligibility claim.
- ``1`` ``EXIT_FAILURE`` — generic failure (unknown completion state).
- ``3`` ``EXIT_BLOCKED_ENV`` — collect: no legal data access configured.
- ``4`` ``EXIT_AUTHORIZATION_REFUSED`` — collect: wrong/missing operator
  token.
- ``5`` ``EXIT_LEGACY_CONTRACT`` — collect: the pinned legacy contract.
- ``6`` ``EXIT_INTEGRITY_FAILURE`` — persisted completion evidence
  failed verification: snapshot digest/protocol mismatch, snapshot not
  bound to a committed completion record, non-idempotent duplicate or
  conflicting completions, or corrupted snapshot/journal/receipt chain.
- ``7`` ``EXIT_COMPLETION_INCOMPLETE`` — the completion procedure did
  not finish: receipt persistence failed (no snapshot written), the
  snapshot persistence failed after a committed receipt, or the chain
  carries a committed completion whose snapshot is missing. All three
  are recoverable by re-running ``collect --complete`` (idempotent);
  none may ever be reported as a completed window.

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
    read_completion_records,
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

PREREG_PATH_LEGACY = REPO_ROOT / "configs" / "forward_observation_s8_real.yaml"
PREREG_PATH = REPO_ROOT / "configs" / "forward_observation_s8_real_v2.yaml"
FIXTURE_PATH = REPO_ROOT / "apps" / "market_gateway" / "fixtures" / \
    "selftest_daily_bars_v2.json"
FIXTURE_PATH_LEGACY = REPO_ROOT / "apps" / "market_gateway" / "fixtures" / \
    "selftest_bars.json"
EVIDENCE_DIR = REPO_ROOT / "artifacts" / "evidence" / "M3.5" / \
    "s8-contract-r1"
DEFAULT_STATE_DIR = REPO_ROOT / "artifacts" / "state" / "s8-shadow-r2"

EXIT_OK = 0
EXIT_BLOCKED_ENV = 3
EXIT_AUTHORIZATION_REFUSED = 4
EXIT_LEGACY_CONTRACT = 5
EXIT_FAILURE = 1
EXIT_INTEGRITY_FAILURE = 6
EXIT_COMPLETION_INCOMPLETE = 7


def _print_json(payload: dict) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


def _identity():
    commit, tree = git_facts(REPO_ROOT)
    return build_s8_forward_identity(
        REPO_ROOT, git_commit=commit, git_tree=tree)


def cmd_check_config(config_path: Path) -> int:
    prereg = PreregistrationReal.load(config_path)
    identity = _identity()
    payload = {
        "protocol_id": prereg.forward_protocol_id,
        "protocol_hash": prereg.hash,
        "schema": str(prereg.payload.get("schema")),
        "contract_legacy": prereg.contract_legacy,
        "environment": prereg.environment,
        "mode": "REAL_SHADOW_READ_ONLY",
        "symbols": list(prereg.symbols),
        "feed": prereg.feed,
        "plan": prereg.plan,
        "dataset_admission": prereg.dataset_admission,
        "min_trading_days": prereg.min_trading_days,
        "read_only": True,
        "paper_write": "NOT_AUTHORIZED",
    }
    if not prereg.contract_legacy:
        contract = prereg.data_contract
        payload["data_contract"] = {
            "bars_endpoint": contract.get("bars_endpoint"),
            "timeframe": contract.get("timeframe"),
            "adjustment": contract.get("adjustment"),
            "window_bounds": contract.get("window_bounds"),
            "limit": prereg.bars_limit,
            "page_cap": prereg.page_cap,
        }
    payload["calendar"] = {
        "valid_from": prereg.calendar_valid_from.isoformat(),
        "valid_until": prereg.calendar_valid_until.isoformat(),
        "holidays": sorted(d.isoformat() for d in prereg.holidays),
        "half_days": sorted(d.isoformat() for d in prereg.half_days),
    }
    payload["identity_schema"] = identity.schema
    payload["identity_code_hash"] = identity.code_hash
    payload["identity_files"] = len(identity.files)
    _print_json(payload)
    return EXIT_OK


def cmd_selftest(state_dir: Path, evidence_dir: Path | None,
                 config_path: Path, fixture_path: Path) -> int:
    from apps.market_gateway.feed_session import run_offline_selftest
    prereg = PreregistrationReal.load(config_path)
    identity = _identity()
    result = run_offline_selftest(
        prereg=prereg, state_dir=state_dir, identity=identity,
        fixture_path=fixture_path)

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
            load_fixture_table(fixture_path)["cycles"]):
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


def cmd_collect(state_dir: Path, once: bool, complete: bool,
                config_path: Path) -> int:
    prereg = PreregistrationReal.load(config_path)
    if prereg.contract_legacy:
        _print_json({
            "collect": "LEGACY_CONTRACT_INVALID",
            "reason": (
                "the selected preregistration is the pinned "
                "LEGACY_INVALID_VENDOR_CONTRACT (schema v2): it encodes "
                "the fabricated latest-bar shape and minute-as-daily "
                "semantics; real collection is structurally refused. "
                "Run under configs/forward_observation_s8_real_v2.yaml"),
            "protocol_id": prereg.forward_protocol_id,
        })
        return EXIT_LEGACY_CONTRACT
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
        summary = _complete_window(state_dir, prereg, identity,
                                   evidence_dir=EVIDENCE_DIR)
        _print_json({"window_completion": summary})
        # P0-A fail closed: a failed/refused completion is a non-zero,
        # distinguishable exit — never a silent EXIT_OK
        return _completion_exit_code(summary)
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


SNAPSHOT_NAME = "forward-window-evaluation.json"

#: completion state -> cmd_collect exit code (T7 contract; unknown
#: states fall back to EXIT_FAILURE — never silently OK)
_COMPLETION_EXIT_CODES = {
    "COMPLETE_VERIFIED": EXIT_OK,
    "RECEIPT_WRITE_FAILED": EXIT_COMPLETION_INCOMPLETE,
    "SNAPSHOT_WRITE_FAILED": EXIT_COMPLETION_INCOMPLETE,
    "EVIDENCE_COPY_WRITE_FAILED": EXIT_COMPLETION_INCOMPLETE,
    "REFUSED_ALREADY_COMPLETED": EXIT_INTEGRITY_FAILURE,
    "REFUSED_CHAIN_CORRUPT": EXIT_INTEGRITY_FAILURE,
}


def _completion_exit_code(payload: dict) -> int:
    return _COMPLETION_EXIT_CODES.get(
        str(payload.get("completion")), EXIT_FAILURE)


def _atomic_write_text(path: Path, text: str) -> None:
    """Crash-safe persistence: write a sibling temp file, flush + fsync,
    then ``os.replace`` onto the target — atomic on POSIX; on Windows
    ``os.replace`` uses ``MOVEFILE_REPLACE_EXISTING`` and is atomic for
    existing file targets on NTFS. Newlines are forced to LF on both
    platforms. A crash mid-write leaves only an orphaned ``.tmp`` file:
    the target is either absent or complete, never partial (a partial
    snapshot cannot masquerade as committed evidence)."""
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def _window_harness(facts: dict) -> dict:
    return {
        "harness_complete": True,
        "negatives_passed": None,
        "replay_reproducible": True,
        "journal_verified": facts["journal_verified"],
        "no_broker_writes": True,
    }


def _evaluate_with_claim(prereg, facts: dict) -> tuple[dict, str | None]:
    """The honest attempt order: claim PASS only when the preregistered
    day threshold is met; the machine still refuses unless every other
    requirement holds. Falls back to the no-claim evaluation, keeping the
    refusal as claim_error."""
    claim = None
    if facts["trading_days_observed"] >= prereg.min_trading_days:
        claim = "PASS"  # attempted; the machine refuses unless every
        # preregistered requirement holds (recoveries, audits, 0 orders)
    try:
        eligibility = evaluate_window(prereg=prereg,
                                      harness=_window_harness(facts),
                                      facts=facts, claim=claim)
        claim_error = None
    except Exception as exc:
        eligibility = evaluate_window(prereg=prereg,
                                      harness=_window_harness(facts),
                                      facts=facts, claim=None)
        claim_error = f"{type(exc).__name__}: {exc}"
    return eligibility, claim_error


def _complete_window(state_dir: Path, prereg, identity,
                     evidence_dir: Path | None = None):
    """Operator-requested window completion — a terminal, idempotent,
    crash-recoverable state machine over the receipt chain (T7):

    1. read the committed ``WINDOW_COMPLETED`` records fail-closed FIRST;
       a corrupted receipt chain refuses every completion decision
       (``REFUSED_CHAIN_CORRUPT``) before anything is mutated;
    2. fresh completion (no committed record): close the session,
       compute the final facts, commit the completion receipt, and only
       then persist the chain-bound evaluation snapshot (atomic
       temp-file + replace; LF on both platforms). A failed receipt
       persistence writes NO snapshot and NO evidence copy — an
       unpersisted completion can never leave success-form evidence
       behind (P0-A fix). A failed snapshot persistence after a
       committed receipt is reported and left recoverable;
    3. re-completion with unchanged facts (e.g. after a crash between
       receipt commit and snapshot write) repairs the snapshot WITHOUT
       appending a second receipt — completion is idempotent;
    4. re-completion after the facts drifted (new chain events, or a
       different protocol) is REFUSED: the committed completion stands,
       nothing is overwritten, nothing is mutated.

    ``evidence_dir`` is passed ONLY by the real ``collect --complete``
    operator path — simulated/test invocations never write into the
    committed evidence set (a simulated evaluation must never sit beside
    real-window evidence)."""
    from apps.trading_daemon.driver import run_replay
    from trading_lab.security.canonical import canonical_digest

    state_dir = Path(state_dir)
    chain_ok, existing = read_completion_records(
        state_dir, prereg.environment)
    if not chain_ok:
        return {
            "completion": "REFUSED_CHAIN_CORRUPT",
            "reason": "the receipt chain failed verification; the "
                      "completion decision is refused before any "
                      "mutation (fail closed)",
        }

    if existing:
        # terminal branch: the window was already completed. Re-completion
        # may only repair the snapshot — never re-close, never re-commit.
        if len(existing) > 1:
            return {
                "completion": "REFUSED_ALREADY_COMPLETED",
                "reason": f"{len(existing)} WINDOW_COMPLETED records are "
                          "already committed; a non-idempotent duplicate "
                          "completion cannot be resolved by this command",
                "committed_completions": len(existing),
            }
        facts = window_facts_from_journal(state_dir, prereg,
                                          events_synthetic=False)
        facts_digest = canonical_digest(facts)
        record = existing[0]
        if str(record.get("facts_digest")) != facts_digest or \
                str(record.get("protocol_hash")) != str(prereg.hash):
            return {
                "completion": "REFUSED_ALREADY_COMPLETED",
                "reason": "the window is already completed with a "
                          "committed completion record; the current "
                          "chain facts differ (new events or a different "
                          "protocol) — re-opening a completed window is "
                          "refused (fail closed)",
                "facts_digest": facts_digest,
                "committed_digest": str(record.get("facts_digest")),
            }
        # identical facts -> identical recomputed eligibility/claim fields
        # (same code path as the fresh branch) -> byte-identical snapshot
        eligibility, claim_error = _evaluate_with_claim(prereg, facts)
        claim = "PASS" if facts["trading_days_observed"] >= \
            prereg.min_trading_days else None
        try:
            _atomic_write_text(state_dir / SNAPSHOT_NAME, json.dumps({
                "schema": "s8-forward-window-evaluation-v1",
                "facts_digest": facts_digest,
                "facts": facts,
                "eligibility": eligibility,
                "claim_attempt": claim,
                "claim_error": claim_error,
                "protocol_hash": prereg.hash,
            }, indent=2, sort_keys=True, default=str) + "\n")
        except OSError as exc:
            return {
                "completion": "SNAPSHOT_WRITE_FAILED",
                "reason": f"receipt committed; snapshot repair failed: "
                          f"{exc} — re-run completion to repair "
                          "(idempotent)",
            }
        payload = {
            "completion": "COMPLETE_VERIFIED",
            "window_completed_receipt": True,   # committed previously
            "repaired_snapshot": True,
            "facts": facts,
            "facts_digest": facts_digest,
        }
    else:
        summary = run_replay(
            state_dir=state_dir / FORWARD_STATE_SUBDIR, prereg=prereg,
            events=[], session_index=_completed_sessions(state_dir) + 1,
            complete=True, identity=identity)
        facts = window_facts_from_journal(state_dir, prereg,
                                          events_synthetic=False)
        eligibility, claim_error = _evaluate_with_claim(prereg, facts)
        claim = "PASS" if facts["trading_days_observed"] >= \
            prereg.min_trading_days else None
        facts_digest = canonical_digest(facts)
        payload = {
            "session_completed": summary,
            "facts": facts,
            "facts_digest": facts_digest,
            "eligibility": eligibility,
            "claim_attempt": claim,
            "claim_error": claim_error,
        }
        # T2: the E-Gate verdict gets a PERSISTENT, chain-bound fact
        # source — a WINDOW_COMPLETED record (facts digest) is appended
        # to the receipt chain and the evaluation snapshot is written
        # beside the state; any later status recomputes the facts,
        # compares digests AND verifies the chain binding.
        try:
            from apps.market_gateway.feed_session import append_receipts
            append_receipts(state_dir, [{
                "event_type": "WINDOW_COMPLETED",
                "facts_digest": facts_digest,
                "eligibility": eligibility["eligibility"],
                "forward_window_status":
                    eligibility["forward_window_status"],
                "trading_days_observed": facts["trading_days_observed"],
                "protocol_hash": prereg.hash,
                "environment": prereg.environment,
                "received_at": _real_now().isoformat(),
                "receipt_schema": "s8-receipts-v2",
            }], environment=prereg.environment)
            payload["window_completed_receipt"] = True
        except Exception as exc:                 # audit sink must not be
            payload["window_completed_receipt"] = f"FAILED: {exc}"  # silent
            payload["completion"] = "RECEIPT_WRITE_FAILED"
            payload["reason"] = (
                "the completion receipt did not persist; NO evaluation "
                "snapshot was written and the window is NOT complete — "
                "an unpersisted completion can never leave success-form "
                "evidence behind (P0-A, fail closed)")
            return payload
        try:
            _atomic_write_text(state_dir / SNAPSHOT_NAME, json.dumps({
                "schema": "s8-forward-window-evaluation-v1",
                "facts_digest": facts_digest,
                "facts": facts,
                "eligibility": eligibility,
                "claim_attempt": claim,
                "claim_error": claim_error,
                "protocol_hash": prereg.hash,
            }, indent=2, sort_keys=True, default=str) + "\n")
        except OSError as exc:
            payload["completion"] = "SNAPSHOT_WRITE_FAILED"
            payload["reason"] = (
                "the completion receipt IS committed but the evaluation "
                "snapshot failed to persist; re-run completion to repair "
                "(idempotent, no duplicate receipt)")
            return payload
        payload["completion"] = "COMPLETE_VERIFIED"
    if evidence_dir is not None:
        evidence = evidence_dir / "real-forward-window-status.json"
        try:
            evidence.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write_text(evidence, json.dumps(
                payload, indent=2, sort_keys=True, default=str) + "\n")
        except OSError as exc:
            payload["completion"] = "EVIDENCE_COPY_WRITE_FAILED"
            payload["reason"] = (
                "the completion IS committed (receipt + snapshot); the "
                "operator evidence copy failed to persist: "
                f"{exc}")
            return payload
        payload["evidence_copy"] = str(evidence)
    return payload


def _verify_completion_evidence(state_dir: Path, prereg,
                                facts: dict, facts_digest: str, *,
                                chain_ok: bool,
                                records: list[dict]) -> tuple[str, list[str],
                                                              dict]:
    """Shared fail-closed verification of the persisted completion
    evidence (used by ``status`` and reusable by any checker): the
    snapshot must match the freshly recomputed facts digest AND the
    preregistered protocol AND be bound to a committed
    ``WINDOW_COMPLETED`` chain record — digest equality alone is never
    completion. Returns ``(completion_state, problems,
    snapshot_verification)``; any problem means the evidence must not be
    trusted (P0-B: callers fail closed with EXIT_INTEGRITY_FAILURE)."""
    problems: list[str] = []
    journal_path = state_dir / FORWARD_STATE_SUBDIR / "journal.jsonl"
    started = journal_path.exists()
    if started and not facts["journal_verified"]:
        problems.append("JOURNAL_CORRUPT")
    if not chain_ok:
        problems.append("RECEIPT_CHAIN_CORRUPT")
    if len(records) > 1:
        digests = {str(r.get("facts_digest")) for r in records}
        problems.append("CONFLICTING_COMPLETIONS" if len(digests) > 1
                        else "DUPLICATE_COMPLETION")

    snapshot_verification: dict = {"present": False}
    snapshot: dict | None = None
    snapshot_path = state_dir / SNAPSHOT_NAME
    if snapshot_path.exists():
        try:
            loaded = json.loads(
                snapshot_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                snapshot = loaded
            else:
                problems.append("SNAPSHOT_MALFORMED")
        except (OSError, ValueError):
            problems.append("SNAPSHOT_MALFORMED")
    committed = records[0] if len(records) == 1 else None
    if snapshot is not None:
        digest_match = str(snapshot.get("facts_digest")) == facts_digest
        protocol_match = \
            str(snapshot.get("protocol_hash")) == str(prereg.hash)
        if not digest_match:
            problems.append("DIGEST_MISMATCH")
        if not protocol_match:
            problems.append("PROTOCOL_MISMATCH")

        def _bound(record: dict) -> bool:
            eligibility = snapshot.get("eligibility") or {}
            return (
                str(record.get("facts_digest"))
                == str(snapshot.get("facts_digest"))
                and str(record.get("protocol_hash"))
                == str(snapshot.get("protocol_hash"))
                and str(record.get("protocol_hash")) == str(prereg.hash)
                and str(record.get("eligibility"))
                == str(eligibility.get("eligibility"))
                and str(record.get("forward_window_status"))
                == str(eligibility.get("forward_window_status")))

        bound = any(_bound(r) for r in records)
        if not bound:
            problems.append("UNBOUND_SNAPSHOT")
        snapshot_verification = {
            "present": True,
            "digest_match": digest_match,
            "protocol_hash_match": protocol_match,
            "chain_binding": bound,
            "snapshot_protocol_hash": snapshot.get("protocol_hash"),
            "snapshot_eligibility":
                (snapshot.get("eligibility") or {}).get("eligibility"),
        }
    if problems:
        return "INTEGRITY_FAILURE", problems, snapshot_verification
    if snapshot is None and committed is not None:
        # a committed completion whose snapshot is missing/partial:
        # recoverable by re-running completion — never a completed window
        return "CHAIN_COMMITTED_SNAPSHOT_MISSING", [], snapshot_verification
    if snapshot is not None:
        return "COMPLETE_VERIFIED", [], snapshot_verification
    return ("NOT_STARTED" if not started else "NOT_COMPLETED",
            [], snapshot_verification)


def cmd_status(state_dir: Path, config_path: Path) -> int:
    prereg = PreregistrationReal.load(config_path)
    state_dir = Path(state_dir)
    facts: dict
    try:
        facts = window_facts_from_journal(state_dir, prereg,
                                          events_synthetic=False)
    except (ValueError, OSError, KeyError) as exc:
        # an unreadable journal is integrity failure, never a crash with
        # a misleading exit code
        _print_json({
            "facts": None,
            "eligibility": None,
            "evaluation_snapshot": {"present": False},
            "completion_state": "INTEGRITY_FAILURE",
            "completion_problems": ["JOURNAL_UNREADABLE"],
            "reason": f"{type(exc).__name__}: {exc}",
        })
        return EXIT_INTEGRITY_FAILURE
    chain_ok, records = read_completion_records(
        state_dir, prereg.environment)
    from trading_lab.security.canonical import canonical_digest
    facts_digest = canonical_digest(facts)
    completion_state, problems, snapshot_verification = \
        _verify_completion_evidence(state_dir, prereg, facts, facts_digest,
                                    chain_ok=chain_ok, records=records)
    harness = {
        "harness_complete": True,
        "negatives_passed": None,
        "replay_reproducible": True,
        "journal_verified": facts["journal_verified"],
        "no_broker_writes": True,
    }
    eligibility = evaluate_window(prereg=prereg, harness=harness, facts=facts)
    _print_json({"facts": facts, "eligibility": eligibility,
                 "evaluation_snapshot": snapshot_verification,
                 "completion_state": completion_state,
                 "completion_problems": problems,
                 "facts_digest": facts_digest})
    if problems:
        # P0-B fail closed: integrity failure is a NON-ZERO, stable,
        # distinguishable exit — a zero exit never means "integrity ok"
        # by accident, and EXIT_OK never means eligibility PASS (that is
        # a JSON field, not an exit code)
        return EXIT_INTEGRITY_FAILURE
    if completion_state == "CHAIN_COMMITTED_SNAPSHOT_MISSING":
        return EXIT_COMPLETION_INCOMPLETE
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="run_m35_s8_shadow_real",
        description="M3.5-S8 read-only real-shadow runner "
                    "(REAL_SHADOW_READ_ONLY; ranged daily-bars contract; "
                    "no broker write path exists)")
    sub = parser.add_subparsers(dest="command", required=True)
    p_chk = sub.add_parser(
        "check-config", help="validate a preregistration and print facts")
    p_chk.add_argument(
        "--config", type=Path, default=PREREG_PATH,
        help="preregistration YAML (default: the ranged v2 protocol; "
             "the legacy v2-schema file is pinned evidence only)")
    p_self = sub.add_parser(
        "selftest", help="offline pipeline proof over the committed fixture")
    p_self.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIR)
    p_self.add_argument("--evidence-dir", type=Path, default=EVIDENCE_DIR)
    p_self.add_argument("--config", type=Path, default=PREREG_PATH)
    p_self.add_argument("--fixture", type=Path, default=FIXTURE_PATH)
    p_self.add_argument(
        "--no-evidence", action="store_true",
        help="do not write the selftest evidence file (tests)")
    p_col = sub.add_parser(
        "collect", help="one REAL collection cycle (operator-gated)")
    p_col.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIR)
    p_col.add_argument("--config", type=Path, default=PREREG_PATH)
    p_col.add_argument("--once", action="store_true",
                       help="exactly one poll cycle (default)")
    p_col.add_argument("--complete", action="store_true",
                       help="also complete + anchor the window and "
                            "persist the evaluation snapshot")
    p_sta = sub.add_parser(
        "status", help="window facts + eligibility from the chains")
    p_sta.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIR)
    p_sta.add_argument("--config", type=Path, default=PREREG_PATH)
    args = parser.parse_args(argv)

    if args.command == "check-config":
        return cmd_check_config(args.config)
    if args.command == "selftest":
        evidence_dir = None if args.no_evidence else args.evidence_dir
        return cmd_selftest(args.state_dir, evidence_dir,
                            args.config, args.fixture)
    if args.command == "collect":
        return cmd_collect(args.state_dir, once=args.once,
                           complete=args.complete, config_path=args.config)
    if args.command == "status":
        return cmd_status(args.state_dir, args.config)
    return EXIT_FAILURE


if __name__ == "__main__":
    sys.exit(main())
