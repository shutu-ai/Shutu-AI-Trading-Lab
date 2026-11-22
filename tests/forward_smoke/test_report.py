"""S4 monitoring/evidence model: the status report carries every
mandated field, with explicit denominators and no zero-sample 100%
claims."""

from __future__ import annotations

from apps.trading_daemon.driver import run_replay
from apps.trading_daemon.fixture import build_fixture_events
from apps.trading_daemon.report import build_status_report, render_markdown

MANDATED_FIELDS = (
    "mode", "source_authorization_status", "source_evidence_level",
    "cohort_id", "event_id", "strategy_hash", "code_hash",
    "protocol_hash", "dataset_hash", "prediction_lock_digest",
    "event_ts", "available_at", "received_at", "decision_at", "score_at",
    "replay_count", "duplicate_count", "gap_count", "clock_skew",
    "recovery_status", "account_environment", "no_broker_writes",
)


def _run(tmp_path, prereg, events, session_index=1):
    return run_replay(state_dir=tmp_path / "state", prereg=prereg,
                      events=events, session_index=session_index)


def test_full_report_contains_mandated_fields(tmp_path, prereg, fixture_events):
    summary = _run(tmp_path, prereg, fixture_events)
    report = build_status_report(summary, prereg=prereg,
                                 harness={"harness_complete": True})
    for field in MANDATED_FIELDS:
        assert field in report, f"missing mandated field {field}"
    assert report["mode"] == "SYNTHETIC_REPLAY"
    assert report["source_evidence_level"] == "SYNTHETIC_REPLAY"
    assert report["account_environment"] == "SYNTHETIC_REPLAY"
    assert report["no_broker_writes"] is True
    assert report["score_at"] is not None
    assert report["prediction_lock_digest"]


def test_denominators_explicit_no_zero_sample_percent_claims(
        tmp_path, prereg, fixture_events):
    summary = _run(tmp_path, prereg, fixture_events)
    report = build_status_report(summary, prereg=prereg,
                                 harness={"harness_complete": True})
    for stat in ("duplicate_count", "gap_count", "expired_count",
                 "rejected_count"):
        assert stat in report
    counters = report["counters"]
    # every counter block carries its denominator
    assert counters["events_delivered"] == len(fixture_events)
    assert counters["scored"]["total"] == \
        counters["scored"]["hit"] + counters["scored"]["miss"] + \
        counters["scored"]["no_claim"]
    # no percentage with zero denominator anywhere in the counters
    def _scan(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if isinstance(v, (int, float)) and str(k).endswith("_pct"):
                    denom = obj.get(str(k).replace("_pct", "_denominator"))
                    assert denom and denom > 0, \
                        f"percentage {k} without a positive denominator"
                _scan(v)
    _scan(counters)


def test_markdown_rendering_includes_states(tmp_path, prereg, fixture_events):
    summary = _run(tmp_path, prereg, fixture_events)
    report = build_status_report(summary, prereg=prereg,
                                 harness={"harness_complete": True})
    md = render_markdown(report)
    assert "OFFLINE_HARNESS_PASS_WITH_SCOPE" in md
    assert "SYNTHETIC_REPLAY" in md
    assert "INCONCLUSIVE" in md
    assert "PAPER_NOT_RUN" in md
