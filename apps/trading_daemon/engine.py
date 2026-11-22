"""The Shadow forward engine — one durable state machine.

Invariants (task S1/S2, v2.1 §4.5):

1. PREDICTION_LOCKED is appended to the hash-chained journal BEFORE the
   observation event is consumed. There is no code path that reads an
   observation without a stored lock for its slot.
2. Scoring happens exactly once per slot: the SCORED chain entry IS the
   persistent scored record; rebuilds refuse double scores, and an
   observed-but-unscored slot is completed exactly once on recovery with
   ``recovered=true``.
3. Anomalies (duplicates with differing payloads, out-of-order/late
   events, future stamps, TTL breaches, illegal clocks, unadmitted
   sources, environment mismatches, malformed envelopes) are rejected or
   conservatively held — audited, never silently repaired.
4. Every decision uses only closes whose ``ts_available <= decision_at``
   (the PIT gate); ``decision_at`` derives from event times, never from
   the wall clock. Wall-clock stamps appear only as audit metadata of
   the processing itself.
5. No broker write exists anywhere in this module; shadow intents are
   internal records only.
"""

from __future__ import annotations

import copy
import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from trading_lab.security.canonical import canonical_digest
from trading_lab.validation.cohorts import ForwardCohort

from .clock import ClockError, ReplayClock
from .envelope import EnvelopeError, ForwardEvent, payload_digest
from .journal import ForwardJournal
from .rule import B2ForwardRule, LONG

__all__ = ["Outcome", "ShadowForwardEngine"]


@dataclass(frozen=True)
class Outcome:
    kind: str                     # LOCKED | OBSERVED_SCORED | DUPLICATE |
                                  # REJECTED | HELD | SUSPENDED
    reason: str
    details: dict[str, Any] = field(default_factory=dict)


class ShadowForwardEngine:
    def __init__(self, *, journal: ForwardJournal, prereg,
                 rule: B2ForwardRule, code_identity,
                 cohort_id: str | None = None,
                 clock: ReplayClock | None = None) -> None:
        self.journal = journal
        self.prereg = prereg
        self.rule = rule
        self.identity = code_identity
        self.cohort_id = cohort_id or \
            f"{prereg.forward_protocol_id}-session"
        self.clock = clock or self._clock_from_prereg()

        state = journal.state
        self._slots = state.slots
        self._events = state.events
        self.consumed_closes: list[tuple[dt.datetime, Decimal]] = \
            list(state.consumed_closes)
        self._source_frontier: dict[str, dt.datetime] = \
            dict(state.source_frontier)
        self.counters: dict[str, Any] = {
            "events_delivered": 0, "consumed": 0, "locked": 0,
            "observed": 0,
            "scored": {"total": 0, "hit": 0, "miss": 0,
                       "no_claim": 0, "flat_close": 0},
            "expired": 0, "rejected": 0, "held": 0, "duplicates": 0,
        }
        self._slot_waited: dict[str, int] = {}
        self.suspended = False
        self.frontier_ts: dt.datetime | None = (
            max(state.source_frontier.values())
            if state.source_frontier else None)
        self.recovery_status = "RESUMED_FROM_JOURNAL" \
            if state.counters.get("PREDICTION_LOCKED", 0) else "CLEAN_START"
        self._status: dict[str, Any] = {
            "code_hash": self.identity.code_hash,
            "protocol_hash": self.prereg.hash,
            "strategy_hash": self.strategy_hash,
            "replay_count": max(0, state.sessions - 1),
        }

    # -- lifecycle ------------------------------------------------------------

    @staticmethod
    def _clock_from_prereg() -> ReplayClock:
        """Engine-level default; the driver builds the clock from the
        preregistered synthetic table before construction."""
        return ReplayClock()

    def start_session(self, session_index: int,
                      credential_env_visible: list[str] | None = None,
                      recovery_notes: list[dict] | None = None) -> None:
        for note in recovery_notes or []:
            self.journal.append("RECOVERY", note)
        self.journal.append("SESSION_STARTED", {
            "session_index": session_index,
            "cohort_id": self.cohort_id,
            "code_hash": self.identity.code_hash,
            "protocol_hash": self.prereg.hash,
            "environment": self.prereg.environment,
            "recovery_status": self.recovery_status,
            "credential_env_visible": credential_env_visible or [],
        })

    def suspend(self, reason: str) -> None:
        """Conservative halt: no new predictions, no scoring until an
        operator reviews the journal. The reason is audited."""
        self.suspended = True
        self.journal.append("SUSPENDED", {"reason": reason})

    def resume_pending_scores(self) -> int:
        """Complete observed-but-unscored slots exactly once (crash point:
        OBSERVATION_RECEIVED persisted, SCORED lost)."""
        completed = 0
        for slot_id, slot in sorted(self._slots.items()):
            if slot["stage"] != "OBSERVED":
                continue
            self._score_slot(slot_id, slot, recovered=True)
            completed += 1
        return completed

    def complete_session(self) -> dict[str, Any]:
        """Expire any open slot (audited), close the session, anchor the
        journal."""
        open_slot = None
        for slot in self._slots.values():
            if slot["stage"] == "LOCKED":
                open_slot = slot
                break
        if open_slot is not None:
            slot_id = open_slot["prediction"]["slot_id"]
            self.journal.append("EXPIRED", {
                "slot_id": slot_id, "reason": "SESSION_END",
                "note": "observation never arrived before session end",
            })
            open_slot["stage"] = "EXPIRED"
            self.counters["expired"] += 1
        summary = {
            "cohort_id": self.cohort_id,
            "counters": self.counters_snapshot(),
            "code_hash": self.identity.code_hash,
            "protocol_hash": self.prereg.hash,
            "no_broker_writes": True,
        }
        self.journal.append("SESSION_COMPLETED", summary)
        return summary

    # -- event processing -------------------------------------------------------

    def process_event(self, payload: dict[str, Any]) -> Outcome:
        self.counters["events_delivered"] += 1
        if self.suspended:
            self.journal.append("SUSPENDED_REFUSED", {
                "event_id": str(payload.get("event_id", ""))})
            return Outcome("SUSPENDED", "SUSPENDED_AFTER_CONFLICT")

        # 1) envelope (fail closed)
        try:
            ev = ForwardEvent.model_validate(dict(payload))
        except EnvelopeError as exc:
            return self._reject(exc.reason, exc.detail,
                                event_id=str(payload.get("event_id", "")))
        if ev.environment is not None and \
                ev.environment != self.prereg.environment:
            return self._reject(
                "ENV_MISMATCH",
                f"event claims environment {ev.environment!r}, session is "
                f"{self.prereg.environment!r}", ev=ev)

        # 2) duplicate / conflict (logical payload; first receipt stands)
        digest = payload_digest(ev)
        known = self._events.get(ev.event_id)
        if known is not None:
            if known["digest"] == digest:
                self.counters["duplicates"] += 1
                self.journal.append("DUPLICATE", {
                    "event_id": ev.event_id,
                    "payload_digest": digest,
                    "stage": known["stage"],
                })
                return Outcome("DUPLICATE", "IDEMPOTENT_REDELIVERY",
                               {"event_id": ev.event_id})
            return self._reject(
                "CONFLICT_PAYLOAD_DIFFERS",
                f"event_id {ev.event_id} was already consumed with a "
                "different logical payload", ev=ev, conflict=True)

        # 3) admission — the preregistration is the only permission surface
        if ev.source not in self.prereg.admitted_sources:
            return self._reject(
                "SOURCE_NOT_ADMITTED",
                f"source {ev.source!r} is not preregistered; vendor "
                "capability claims are not evidence (M1 U-1 stays)", ev=ev)
        if ev.dataset_hash not in self.prereg.admitted_dataset_hashes:
            return self._reject(
                "DATASET_NOT_ADMITTED",
                f"dataset_hash {ev.dataset_hash} is not the preregistered "
                "fixture", ev=ev)
        if self.prereg.admitted_symbols and \
                ev.symbol not in self.prereg.admitted_symbols:
            return self._reject(
                "SYMBOL_NOT_ADMITTED",
                f"symbol {ev.symbol!r} is not the preregistered fixture "
                "symbol", ev=ev)

        # 4) future stamp beyond the scheduling horizon (checked before
        #    the market clock: an out-of-horizon stamp is held regardless
        #    of which session it would land in)
        horizon = int(self.prereg.ttl.get("max_synthetic_seconds", 604800))
        if self.frontier_ts is not None and \
                ev.ts_event > self.frontier_ts + \
                dt.timedelta(seconds=horizon):
            return self._hold(
                "FUTURE_STAMP",
                "ts_event beyond the preregistered horizon", ev=ev)

        # 5) market clock (declared synthetic table, DST-correct)
        try:
            self.clock.check_event_time(ev.ts_event)
        except ClockError as exc:
            return self._reject("MARKET_CLOCK", str(exc), ev=ev)

        # 6) per-source ordering (out-of-order / late backfill)
        source_frontier = self._source_frontier.get(ev.source)
        if source_frontier is not None and ev.ts_event < source_frontier:
            late = (source_frontier - ev.ts_event) > dt.timedelta(days=1)
            self._account_waited()
            return self._hold(
                "OUT_OF_ORDER",
                f"ts_event {ev.ts_event.isoformat()} precedes this "
                f"source's frontier {source_frontier.isoformat()}",
                ev=ev, details={"late_backfill": late})

        # 7) observation phase — ONLY a stored lock makes this legal
        slot_entry = self._open_slot()
        slot_id: str | None = None
        if slot_entry is not None:
            prediction = slot_entry["prediction"]
            slot_ts_event = dt.datetime.fromisoformat(prediction["ts_event"])
            if prediction["symbol"] == ev.symbol and \
                    ev.ts_event > slot_ts_event:
                slot_id = prediction["slot_id"]
            else:
                self._account_waited()
        if slot_id is not None:
            obs_payload = {
                "slot_id": slot_id,
                "event_id": ev.event_id,
                "payload_digest": digest,
                "close": str(ev.close),
                "ts_event": ev.ts_event.isoformat(),
                "ts_available": ev.ts_available.isoformat(),
                "received_at": ev.received_at.isoformat(),
            }
            self.journal.append("OBSERVATION_RECEIVED", obs_payload)
            slot_entry["stage"] = "OBSERVED"
            slot_entry["observation"] = obs_payload
            self._score_slot(slot_id, slot_entry, recovered=False)
            self.counters["observed"] += 1

        # 8) prediction phase — lock BEFORE any later observation exists
        decision_at = ev.ts_available          # PIT decision instant
        closes = [c for ta, c in self.consumed_closes
                  if ta <= decision_at]        # the PIT gate
        decision = self.rule.decide(closes)
        observed_flag = slot_id is not None
        if decision != "WARMUP":
            self._lock_prediction(ev, digest, decision, decision_at)

        # 9) consume the event as a PIT rule input (durable consumption
        #    record — the chain is the source of truth across restarts)
        self.journal.append("EVENT_CONSUMED", {
            "event_id": ev.event_id, "source": ev.source,
            "payload_digest": digest, "symbol": ev.symbol,
            "ts_event": ev.ts_event.isoformat(),
            "ts_available": ev.ts_available.isoformat(),
            "close": str(ev.close),
        })
        self._events[ev.event_id] = {"digest": digest,
                                     "stage": "OBSERVED_SCORED"
                                     if observed_flag else "LOCKED"}
        self.consumed_closes.append((ev.ts_available, ev.close))
        self.frontier_ts = ev.ts_event if self.frontier_ts is None else \
            max(self.frontier_ts, ev.ts_event)
        prev = self._source_frontier.get(ev.source)
        self._source_frontier[ev.source] = (
            ev.ts_event if prev is None else max(prev, ev.ts_event))
        self.counters["consumed"] += 1
        self._remember_status(ev, slot_id)
        kind = "OBSERVED_SCORED" if observed_flag else "LOCKED"
        return Outcome(kind, "OK", {"event_id": ev.event_id})

    # -- internals -------------------------------------------------------------

    def _open_slot(self) -> dict[str, Any] | None:
        for slot in self._slots.values():
            if slot["stage"] == "LOCKED":
                return slot
        return None

    def _account_waited(self) -> None:
        """A well-formed admitted arrival that could not serve as the
        open slot's observation. Beyond the preregistered TTL the slot
        expires (audited; counted in denominators)."""
        slot_entry = self._open_slot()
        if slot_entry is None:
            return
        slot_id = slot_entry["prediction"]["slot_id"]
        waited = self._slot_waited.get(slot_id, 0) + 1
        self._slot_waited[slot_id] = waited
        if waited > int(self.prereg.ttl.get("max_events_wait", 3)):
            self.journal.append("EXPIRED", {
                "slot_id": slot_id, "reason": "TTL_EVENTS",
                "events_waited": waited,
            })
            slot_entry["stage"] = "EXPIRED"
            self.counters["expired"] += 1

    def _lock_prediction(self, ev: ForwardEvent, digest: str,
                         exposure: str, decision_at: dt.datetime) -> None:
        slot_id = f"slot-{ev.event_id}"
        prediction_locked_at = dt.datetime.now(dt.timezone.utc)
        lock_payload = {
            "slot_id": slot_id,
            "event_id": ev.event_id,
            "cohort_id": self.cohort_id,
            "exposure": exposure,
            "reference_close": str(ev.close),
            "reference_close_digest": digest,
            "rule_params_digest": self.rule.params_digest,
            "strategy_hash": self.strategy_hash,
            "code_hash": self.identity.code_hash,
            "protocol_hash": self.prereg.hash,
            "dataset_hash": ev.dataset_hash,
            "symbol": ev.symbol,
            "source": ev.source,
            "ts_event": ev.ts_event.isoformat(),
            "decision_at": decision_at.isoformat(),
            "prediction_locked_at": prediction_locked_at.isoformat(),
            "prediction_lock_digest": "",
        }
        lock_payload["prediction_lock_digest"] = canonical_digest(
            lock_payload)
        self.journal.append("PREDICTION_LOCKED", lock_payload)
        self._slots[slot_id] = {"stage": "LOCKED",
                                "prediction": lock_payload, "seq": None}
        self.counters["locked"] += 1

    def _score_slot(self, slot_id: str, slot: dict[str, Any],
                    *, recovered: bool) -> None:
        prediction = slot["prediction"]
        observation = slot["observation"]
        reference = Decimal(prediction["reference_close"])
        realized = Decimal(observation["close"])
        exposure = prediction["exposure"]
        if exposure == LONG:
            if realized > reference:
                verdict = "hit"
            elif realized < reference:
                verdict = "miss"
            else:
                verdict = "flat_close"
        else:
            verdict = "no_claim"
        # forward-cohort discipline, mechanically enforced (validation
        # package, reused): locked-before-available and one-shot scoring.
        # Times here are SYNTHETIC-REPLAY decision-clock facts, clearly
        # labeled — the wall-clock processing facts live in the audit
        # records' own ts fields.
        fc = ForwardCohort(
            cohort_id=f"{prediction['cohort_id']}:{slot_id}",
            prediction_locked_at=dt.datetime.fromisoformat(
                prediction["decision_at"]),
            observation_available_at=dt.datetime.fromisoformat(
                observation["ts_available"]))
        fc.score(now=dt.datetime.fromisoformat(
            observation["ts_available"]))
        score_payload = {
            "slot_id": slot_id,
            "prediction_lock_digest": prediction["prediction_lock_digest"],
            "exposure": exposure,
            "reference_close": prediction["reference_close"],
            "observed_close": str(realized),
            "verdict": verdict,
            "recovered": recovered,
            "score_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "forward_cohort": {
                "cohort_id": fc.cohort_id,
                "prediction_locked_at": fc.prediction_locked_at.isoformat(),
                "observation_available_at":
                    fc.observation_available_at.isoformat(),
                "score": "SCORED",
                "basis": "SYNTHETIC_REPLAY_DETERMINISTIC_CLOCK",
            },
        }
        self.journal.append("SCORED", score_payload)
        slot["stage"] = "SCORED"
        slot["score"] = score_payload
        self.counters["scored"]["total"] += 1
        self.counters["scored"][verdict] += 1
        self._status["score_at"] = score_payload["score_at"]

    def _reject(self, reason: str, detail: str,
                ev: ForwardEvent | None = None, event_id: str = "",
                conflict: bool = False) -> Outcome:
        payload: dict[str, Any] = {"reason": reason, "detail": detail}
        if ev is not None:
            payload["event_id"] = ev.event_id
        elif event_id:
            payload["event_id"] = event_id
        self.journal.append("REJECTED", payload)
        self.counters["rejected"] += 1
        if conflict:
            self.suspend(
                f"conflicting payload for event {payload.get('event_id')}")
        return Outcome("REJECTED", reason, {"detail": detail})

    def _hold(self, reason: str, detail: str, ev: ForwardEvent,
              details: dict[str, Any] | None = None) -> Outcome:
        self.journal.append("HELD", {
            "event_id": ev.event_id, "reason": reason, "detail": detail,
            **(details or {}),
        })
        self.counters["held"] += 1
        return Outcome("HELD", reason,
                       {"detail": detail, **(details or {})})

    def _remember_status(self, ev: ForwardEvent, slot_id: str | None) -> None:
        self._status = getattr(self, "_status", {})
        self._status.update({
            "event_id": ev.event_id,
            "event_ts": ev.ts_event.isoformat(),
            "available_at": ev.ts_available.isoformat(),
            "received_at": ev.received_at.isoformat(),
            "decision_at": ev.ts_available.isoformat(),
            "dataset_hash": ev.dataset_hash,
            "clock_skew_seconds": max(
                float(self._status.get("clock_skew_seconds", 0.0)),
                abs((ev.received_at - ev.ts_available).total_seconds())),
            "slot_id": slot_id,
        })
        if slot_id:
            self._status["prediction_lock_digest"] = \
                self._slots[slot_id]["prediction"]["prediction_lock_digest"]

    # -- reporting surfaces -------------------------------------------------------

    @property
    def strategy_hash(self) -> str:
        strategy = self.prereg.strategy
        return canonical_digest({
            "arm": strategy["arm"],
            "rule": strategy["rule"],
            "short_n": int(strategy["short_n"]),
            "long_n": int(strategy["long_n"]),
        })

    def counters_snapshot(self) -> dict[str, Any]:
        return copy.deepcopy(self.counters)

    def status(self) -> dict[str, Any]:
        return dict(getattr(self, "_status", {}))
