"""Real-window collection session — receipts, engine feeding, and the
arrival-evidence binding.

Structure per poll cycle (:meth:`run_collection_cycle`):

1. the feed polls the preregistered symbols (guarded GET, quality
   validation);
2. every receipt / quality reject / transport error is appended to the
   **receipt chain** — an AuditLog hash chain with head record and an
   external anchor, reusing the same mechanism as the forward journal;
3. the produced envelope events go through the daemon's
   :func:`run_replay` (lock-before-observe, idempotency, exactly-once
   scoring, single-writer lease) — the real plane invents no second
   engine. Sessions stay OPEN across cycles: restarts resume from the
   chain, and the operator completes the window explicitly.

Arrival-evidence binding (:func:`window_facts_from_journal`): a
``WINDOW`` fact is real only when every ``EVENT_CONSUMED`` journal entry
has a receipt-chain entry with the same ``event_id`` and payload digest,
and both chains verify (head record + anchor). This is what separates
``SHADOW_REAL_OBSERVED`` from a selftest over recorded fixtures —
selftest facts are flagged ``events_synthetic=True`` and can never mint
``PENDING_FORWARD_WINDOW``/``PASS`` (the eligibility machine refuses).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from trading_lab.security.audit import AuditLog

from apps.trading_daemon.driver import run_replay, visible_credential_env_names
from apps.trading_daemon.journal import read_entries, verify_journal_file

from .alpaca_feed import CollectResult

__all__ = [
    "AuthorizationRefused",
    "OPERATOR_AUTHORIZATION_TOKEN",
    "PreflightResult",
    "RECEIPT_LOG_NAME",
    "FORWARD_STATE_SUBDIR",
    "append_receipts",
    "evaluate_window",
    "preflight",
    "run_collection_cycle",
    "window_facts_from_journal",
]

#: the operator passes this exact token on the collect CLI; it names the
#: signed approval (2026-11-22) that the record below archives verbatim.
OPERATOR_AUTHORIZATION_TOKEN = "S8_APPROVAL_20261122"

RECEIPT_LOG_NAME = "receipts.jsonl"
FORWARD_STATE_SUBDIR = "forward"


class AuthorizationRefused(RuntimeError):
    """The operator authorization token is missing or wrong — the
    collector refuses to run (exit path 4 in the runner)."""


@dataclass(frozen=True)
class PreflightResult:
    status: str                    # READY | BLOCKED_ENV
    credential_env_visible: list[str]
    reason: str


def preflight(
    *,
    operator_authorization: str | None,
    credential_env: dict[str, str] | None = None,
) -> PreflightResult:
    """The two independent operator gates before any real connection:

    1. the explicit authorization token naming the signed approval —
       anything else is a hard :class:`AuthorizationRefused`;
    2. market-data credentials actually visible in the environment
       (presence only — values are never read here). Missing credentials
       are the honest ``BLOCKED_ENV`` state, not an error to retry.
    """
    if operator_authorization != OPERATOR_AUTHORIZATION_TOKEN:
        raise AuthorizationRefused(
            "operator authorization token missing or unknown — the "
            "collector runs only under the signed S8 approval "
            "(S8_DATA_READ_ONLY=APPROVED_WITH_SCOPE, 2026-11-22)")
    if credential_env is None:
        visible = visible_credential_env_names()
    else:
        visible = sorted(name for name in credential_env
                         if credential_env.get(name) is not None)
    needed = {"APCA_API_KEY_ID", "APCA_API_SECRET_KEY"}
    if not needed.issubset(set(visible)):
        missing = sorted(needed - set(visible))
        return PreflightResult(
            status="BLOCKED_ENV",
            credential_env_visible=visible,
            reason=(
                "market-data credentials are not visible in the collector "
                f"environment (missing: {', '.join(missing)}) — no legal "
                "data access is configured; the collector must not attempt "
                "real connections (BLOCKED_ENV)"))
    return PreflightResult(
        status="READY",
        credential_env_visible=visible,
        reason="operator authorization present; market-data credentials "
               "visible (values never read at preflight)")


def receipt_log_path(state_dir: Path | str) -> Path:
    return Path(state_dir) / RECEIPT_LOG_NAME


def append_receipts(state_dir: Path | str, records: list[dict[str, Any]],
                    environment: str) -> int:
    """Append one AuditLog entry per receipt record (chain + head)."""
    if not records:
        return 0
    log = AuditLog(receipt_log_path(state_dir), environment_tag=environment)
    for record in records:
        log.append(str(record.get("event_type", "RECEIPT")), record)
    return len(records)


def run_collection_cycle(
    *,
    feed,                                   # AlpacaIexDailyBarFeed
    prereg,                                 # PreregistrationReal
    state_dir: Path | str,
    identity,
    session_index: int,
) -> dict[str, Any]:
    """One poll cycle: collect -> receipt chain -> engine (journal stays
    open for the next cycle / restart)."""
    state_dir = Path(state_dir)
    result: CollectResult = feed.collect_once()
    receipt_records = [
        *result.receipts,
        *result.quality_rejects,
        *result.transport_errors,
    ]
    receipt_count = append_receipts(
        state_dir, receipt_records, environment=prereg.environment)
    summary = run_replay(
        state_dir=state_dir / FORWARD_STATE_SUBDIR, prereg=prereg,
        events=result.events, session_index=session_index,
        complete=False, identity=identity)
    return {
        "collect_status": result.status,
        "session_date": (result.session_date.isoformat()
                         if result.session_date else None),
        "events_emitted": len(result.events),
        "receipts_appended": receipt_count,
        "quality_rejects": [r.get("reject_reason")
                            for r in result.quality_rejects],
        "transport_errors": [e.get("error_reason")
                             for e in result.transport_errors],
        "engine_counters": summary.counters,
        "score_sequence": summary.score_sequence,
        "credential_env_visible": summary.credential_env_visible,
    }


# ---------------------------------------------------------------------------
# window facts — computed from the chains, not from operator claims
# ---------------------------------------------------------------------------

def window_facts_from_journal(
    state_dir: Path | str,
    prereg,                                 # PreregistrationReal
    *,
    events_synthetic: bool,
) -> dict[str, Any]:
    """Arrival-evidence facts from the two chains (fail-closed defaults).

    ``events_synthetic`` must be passed honestly by the caller: True for
    the offline selftest fixtures, False only for the real collector. The
    cross-check below independently verifies that every consumed event
    carries a receipt — a synthetic selftest run has receipts too, which
    is exactly why the flag exists and why PASS/PENDING additionally
    require it False.
    """
    state_dir = Path(state_dir)
    journal_path = state_dir / FORWARD_STATE_SUBDIR / "journal.jsonl"
    facts: dict[str, Any] = {
        "events_synthetic": bool(events_synthetic),
        "receipt_evidence_ok": False,
        "trading_days_observed": 0,
        "days_full_coverage": 0,
        "days_partial": 0,
        "symbols_expected": len(prereg.symbols),
        "duplicate_events": 0,
        "feed_errors": 0,
        "quality_rejects": 0,
        "cycles_after_feed_error": 0,
        "unauthorized_broker_orders": 0,
        "duplicate_broker_orders": 0,
        "scored": {},
        "journal_verified": False,
        "receipts_verified": False,
    }
    if not journal_path.exists():
        return facts

    journal_ok, _msg = verify_journal_file(journal_path)
    facts["journal_verified"] = bool(journal_ok)

    receipt_path = receipt_log_path(state_dir)
    receipts_ok = False
    receipt_index: dict[str, dict[str, Any]] = {}
    receipt_order: list[tuple[str, str]] = []
    if receipt_path.exists():
        try:
            log = AuditLog(receipt_path, environment_tag=prereg.environment)
            receipts_ok, _bad = log.verify()
            for record in read_entries(receipt_path):
                payload = record.get("payload", {}) or {}
                event_type = payload.get("event_type", "")
                if event_type == "RECEIPT":
                    receipt_index[str(payload.get("event_id"))] = payload
                    receipt_order.append(("RECEIPT",
                                          str(payload.get("event_id"))))
                elif event_type == "FEED_ERROR":
                    receipt_order.append(("FEED_ERROR", ""))
                    facts["feed_errors"] += 1
                elif event_type == "QUALITY_REJECT":
                    receipt_order.append(("QUALITY_REJECT", ""))
                    facts["quality_rejects"] += 1
        except (ValueError, OSError, KeyError):
            receipts_ok = False
    facts["receipts_verified"] = bool(receipts_ok)

    # a successful RECEIPT after the first FEED_ERROR = disconnect recovery
    seen_error = False
    for kind, _eid in receipt_order:
        if kind == "FEED_ERROR":
            seen_error = True
        elif kind == "RECEIPT" and seen_error:
            facts["cycles_after_feed_error"] += 1

    entries = read_entries(journal_path)
    consumed: dict[str, dict[str, Any]] = {}
    duplicates = 0
    scored: dict[str, int] = {}
    coverage: dict[str, set[str]] = {}
    for entry in entries:
        etype = entry.get("event_type", "")
        payload = entry.get("payload", {}) or {}
        if etype == "EVENT_CONSUMED":
            consumed[str(payload.get("event_id"))] = payload
            symbol = str(payload.get("symbol", ""))
            ts = payload.get("ts_event", "")
            day = str(ts)[:10] if ts else ""
            if symbol and day:
                coverage.setdefault(symbol, set()).add(day)
        elif etype == "DUPLICATE":
            duplicates += 1
        elif etype == "SCORED":
            verdict = str(payload.get("verdict", ""))
            scored[verdict] = scored.get(verdict, 0) + 1
    facts["duplicate_events"] = duplicates
    facts["scored"] = scored

    # arrival-evidence binding: every consumed event must carry a receipt
    # with the SAME event_id and the SAME dataset content digest (the
    # journal's EVENT_CONSUMED entry records it alongside the logical
    # payload digest; the receipt records the collector-computed content
    # digest of the arriving payload)
    missing = [eid for eid in consumed if eid not in receipt_index]
    mismatched = [
        eid for eid, payload in consumed.items()
        if eid in receipt_index
        and str(receipt_index[eid].get("payload_digest"))
        != str(payload.get("dataset_hash"))
    ]
    facts["receipt_binding_missing"] = sorted(missing)
    facts["receipt_binding_mismatched"] = sorted(mismatched)
    facts["receipt_evidence_ok"] = bool(
        journal_ok and receipts_ok and not missing and not mismatched)

    expected_symbols = set(prereg.symbols)
    full_days: set[str] = set()
    all_days: set[str] = set()
    for _symbol, days in coverage.items():
        all_days |= days
    for day in all_days:
        delivered = {s for s, days in coverage.items() if day in days}
        if delivered == expected_symbols:
            full_days.add(day)
    facts["days_full_coverage"] = len(full_days)
    facts["days_partial"] = len(all_days) - len(full_days)
    # the honest day count toward the 5-day threshold: full-coverage days
    facts["trading_days_observed"] = len(full_days)
    return facts


def evaluate_window(
    *,
    prereg,                                 # PreregistrationReal
    harness: dict[str, bool],
    facts: dict[str, Any],
    claim: str | None = None,
) -> dict[str, Any]:
    """S5 eligibility over real-window facts (the machine lives in the
    daemon; the real plane adds no second evaluator)."""
    from apps.trading_daemon.eligibility import evaluate_eligibility
    return evaluate_eligibility(
        prereg_real_window_enabled=bool(
            prereg.payload["real_window"]["enabled"]),
        source_authorization=str(
            prereg.payload["source_authorization"]["real_market_data"]),
        harness=harness,
        real_window_facts=facts,
        claim=claim,
        min_trading_days=prereg.min_trading_days)


# ---------------------------------------------------------------------------
# offline selftest — the pipeline proof over recorded-shape fixtures
# ---------------------------------------------------------------------------

#: selftest harness facts: ``negatives_passed=None`` means attested by the
#: CI suite and the stage negative-tests log (never a fake local pass;
#: an explicit False would block — the eligibility machine treats only
#: ``False`` as a failure).
SELFTEST_HARNESS: dict[str, bool | None] = {
    "harness_complete": True,
    "negatives_passed": None,
    "replay_reproducible": True,
    "journal_verified": True,
    "no_broker_writes": True,
}


def run_offline_selftest(*, prereg, state_dir, identity,
                         fixture_path) -> dict[str, Any]:
    """Drive the WHOLE S8 pipeline offline: guarded client -> feed ->
    quality validation -> engine -> journal + receipt chains -> window
    facts -> eligibility. Fixture facts are flagged synthetic; the
    PASS/PENDING claims must refuse (proven here, per cycle).

    The selftest proves PLUMBING, never a forward window: its outcome is
    ``OFFLINE_HARNESS_PASS_WITH_SCOPE`` at best, and its events are never
    presented as real trading days."""
    from .offline_fixtures import build_selftest_feed, load_fixture_table

    state_dir = Path(state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    fixture = load_fixture_table(fixture_path)
    feed, client, clock = build_selftest_feed(
        prereg=prereg, fixture=fixture, identity=identity)
    cycle_results: list[dict[str, Any]] = []
    for index in range(len(fixture["cycles"])):
        cycle_results.append(run_collection_cycle(
            feed=feed, prereg=prereg, state_dir=state_dir,
            identity=identity, session_index=index + 1))
        client.advance_cycle()
        clock.sync_with(client)

    # full redelivery of the LAST cycle: every event re-arrives with the
    # same logical payload -> the idempotency layer must swallow all of
    # them and score NOTHING new
    client.set_cycle(len(fixture["cycles"]) - 1)
    clock.sync_with(client)
    duplicate_cycle = run_collection_cycle(
        feed=feed, prereg=prereg, state_dir=state_dir, identity=identity,
        session_index=len(fixture["cycles"]) + 1)

    facts = window_facts_from_journal(state_dir, prereg,
                                      events_synthetic=True)
    harness = dict(SELFTEST_HARNESS)
    eligibility = evaluate_window(prereg=prereg, harness=harness, facts=facts)
    refusals: dict[str, str] = {}
    for claim in ("PENDING_FORWARD_WINDOW", "PASS"):
        try:
            evaluate_window(prereg=prereg, harness=dict(harness),
                            facts=facts, claim=claim)
        except Exception as exc:  # EligibilityRefused — the REQUIRED outcome
            refusals[claim] = str(exc)
        else:
            refusals[claim] = "NOT REFUSED — SELFTEST INTEGRITY FAILURE"

    journal_ok, journal_msg = verify_journal_file(
        state_dir / FORWARD_STATE_SUBDIR / "journal.jsonl")
    return {
        "cycles": cycle_results,
        "duplicate_cycle": {
            "events_emitted": duplicate_cycle["events_emitted"],
            "engine_duplicates":
                duplicate_cycle["engine_counters"]["duplicates"],
            "new_scores":
                duplicate_cycle["engine_counters"]["scored"]["total"],
        },
        "facts": facts,
        "eligibility": eligibility,
        "claim_refusals": refusals,
        "journal_ok": bool(journal_ok),
        "journal_msg": journal_msg,
    }
