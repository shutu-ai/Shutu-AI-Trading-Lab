"""The offline replay driver — session lifecycle around the engine.

One ``run_replay`` call = one audit session on the journal: acquire the
session lease (stale takeover is audited INSIDE the journal), open and
verify the journal, complete any pending recovery scores, feed events,
complete the session and anchor the journal. Credential visibility is
audited; nothing is ever read from it.
"""

from __future__ import annotations

import dataclasses
import os
from pathlib import Path
from typing import Any, Sequence

from .engine import ShadowForwardEngine
from .identity import build_forward_identity
from .journal import ForwardJournal
from .rule import B2ForwardRule
from .session import SessionLock

JOURNAL_NAME = "journal.jsonl"
LOCK_NAME = "session.lock"

#: broker-credential variable names audited for visibility (never read).
CREDENTIAL_ENV_NAMES = (
    "APCA_API_KEY_ID", "APCA_API_SECRET_KEY",
    "ALPACA_API_KEY_ID", "ALPACA_API_SECRET_KEY",
)

__all__ = ["ReplaySummary", "run_replay", "CREDENTIAL_ENV_NAMES"]


@dataclasses.dataclass(frozen=True)
class ReplaySummary:
    session_index: int
    cohort_id: str
    counters: dict[str, Any]
    score_sequence: list[str]
    logical_digest: str
    suspended: bool
    recovery_status: str
    resume_scores_completed: int
    no_broker_writes: bool
    credential_env_visible: list[str]
    stale_takeovers: list[dict]
    cohort: dict[str, Any]
    last_status: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


def visible_credential_env_names() -> list[str]:
    """Names of broker-credential variables VISIBLE in the environment
    (presence only — membership check; values are never read)."""
    return sorted(
        name for name in CREDENTIAL_ENV_NAMES if name in os.environ)


def run_replay(*, state_dir: Path | str, prereg, events: Sequence[dict],
               session_index: int, lease_seconds: int = 300,
               identity=None, repo_root: Path | None = None,
               complete: bool = True, with_lock: bool = True) -> ReplaySummary:
    """One audit session on the journal.

    ``complete=False`` leaves the session OPEN (no SESSION_COMPLETED, no
    anchor) — exactly the durable state a mid-stream crash leaves.
    ``with_lock=False`` is for crash-test workers that already hold the
    lease themselves and die without releasing it.
    """
    state = Path(state_dir)
    state.mkdir(parents=True, exist_ok=True)

    # single writer, lease-protected; a stale takeover is captured here
    # and journaled once the (verified) journal is open
    takeover_facts: list[dict] = []
    lock = SessionLock(state / LOCK_NAME, lease_seconds=lease_seconds)
    if with_lock:
        lock.acquire(on_takeover=takeover_facts.append)
    try:
        journal = ForwardJournal.open(state / JOURNAL_NAME, prereg=prereg)
        identity = identity or build_forward_identity(
            repo_root=repo_root or Path(__file__).resolve().parents[2])
        rule = B2ForwardRule(
            short_n=int(prereg.strategy["short_n"]),
            long_n=int(prereg.strategy["long_n"]))
        engine = ShadowForwardEngine(
            journal=journal, prereg=prereg, rule=rule,
            code_identity=identity,
            cohort_id=f"{prereg.forward_protocol_id}-s{session_index}")
        engine.start_session(
            session_index=session_index,
            credential_env_visible=visible_credential_env_names(),
            recovery_notes=takeover_facts)
        recovered = engine.resume_pending_scores()

        for payload in events:
            engine.process_event(dict(payload))
        if complete:
            summary = engine.complete_session()
            anchor = journal.write_anchor(session_id=f"{engine.cohort_id}")
        else:
            summary = {"cohort_id": engine.cohort_id,
                       "counters": engine.counters_snapshot(),
                       "code_hash": identity.code_hash,
                       "protocol_hash": prereg.hash,
                       "no_broker_writes": True}
            anchor = {"tail_digest": ""}

        counters = engine.counters_snapshot()
        # verdict sequence from the journal (not from memory): the audit
        # chain is the authority for replay equivalence
        from .journal import read_entries
        entries = read_entries(journal.path)
        score_sequence = [
            e["payload"]["verdict"] for e in entries
            if e["event_type"] == "SCORED"]
        logical_digest_payload = {
            "cohort_id": engine.cohort_id,
            "score_sequence": score_sequence,
            "counters": counters,
            "code_hash": identity.code_hash,
            "protocol_hash": prereg.hash,
            # deliberately EXCLUDES the anchor tail digest and every
            # wall-clock stamp: those are per-journal processing facts;
            # the logical digest must be equal for equivalent replays
        }
        from trading_lab.security.canonical import canonical_digest
        return ReplaySummary(
            session_index=session_index,
            cohort_id=engine.cohort_id,
            counters=counters,
            score_sequence=score_sequence,
            logical_digest=canonical_digest(logical_digest_payload),
            suspended=engine.suspended,
            recovery_status=engine.recovery_status,
            resume_scores_completed=recovered,
            no_broker_writes=True,
            credential_env_visible=visible_credential_env_names(),
            stale_takeovers=takeover_facts,
            cohort={                "role": "FORWARD",
                "cohort_id": engine.cohort_id,
                "prediction_locked_at": _first_lock_time(journal),
                "last_observation_at": _last_observation_time(journal),
                "independent_disclosure":
                    "SYNTHETIC_REPLAY fixture cohort; no overlap with any "
                    "real forward window exists (none was collected); "
                    "disclosure degrades nothing but is recorded",
            },
            last_status=engine.status(),
        )
    finally:
        lock.release()


def _first_lock_time(journal: ForwardJournal) -> str:
    from .journal import read_entries
    for e in read_entries(journal.path):
        if e["event_type"] == "PREDICTION_LOCKED":
            return str(e["payload"]["decision_at"])
    return ""


def _last_observation_time(journal: ForwardJournal) -> str:
    from .journal import read_entries
    last = ""
    for e in read_entries(journal.path):
        if e["event_type"] == "OBSERVATION_RECEIVED":
            last = str(e["payload"]["ts_available"])
    return last
