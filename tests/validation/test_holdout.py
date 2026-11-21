"""M3-R1-T5 — sealed holdout access-control state machine.

Covers: role-refusal matrix (research read/aggregate/difference/probe),
single legal unlock -> pollution, second unlock refused, champion
re-selection refused, verdict states PASS/FAILED/INCONCLUSIVE/INVALIDATED,
audit trail integrity. Honest boundary: application-level simulation,
NOT an OS sandbox (M4 owns hard isolation).
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

from trading_lab.validation.holdout import (  # noqa: E402
    HoldoutError,
    HoldoutRole,
    SealedHoldout,
    VERDICT_STATES,
)

U = dt.timezone.utc
NOW = dt.datetime(2029, 6, 1, tzinfo=U)


def make_holdout() -> SealedHoldout:
    return SealedHoldout(
        holdout_id="m9-final-2029",
        sealing_manifest_hash="a" * 32,
        created_at=dt.datetime(2026, 11, 21, tzinfo=U),
        max_unlocks=1,
    )


class TestResearchRefusalMatrix:
    def test_direct_read_refused_and_audited(self):
        h = make_holdout()
        with pytest.raises(HoldoutError, match="direct sample access"):
            h.read_samples("research-agent", HoldoutRole.RESEARCH, now=NOW)
        entries = h.read_audit("auditor", HoldoutRole.AUDITOR, now=NOW)
        assert any(e.action == "READ_SAMPLES" and not e.allowed
                   for e in entries)

    def test_aggregation_refused(self):
        h = make_holdout()
        with pytest.raises(HoldoutError, match="aggregation"):
            h.aggregate("research-agent", HoldoutRole.RESEARCH, now=NOW)

    def test_query_differencing_refused(self):
        h = make_holdout()
        with pytest.raises(HoldoutError, match="differencing"):
            h.query_difference("research-agent", HoldoutRole.RESEARCH,
                               probe="mean(close[2029-01..03])", now=NOW)

    def test_repeated_probing_refused(self):
        h = make_holdout()
        with pytest.raises(HoldoutError, match="50 repeated probes"):
            h.probe_repeatedly("research-agent", HoldoutRole.RESEARCH,
                               count=50, now=NOW)
        probes = [e for e in h.read_audit(
            "auditor", HoldoutRole.AUDITOR, now=NOW)
            if e.action == "PROBE"]
        assert len(probes) == 50  # every single probe audited

    def test_manifest_readable_only_by_auditor(self):
        h = make_holdout()
        with pytest.raises(HoldoutError, match="AUDITOR"):
            h.read_manifest("research-agent", HoldoutRole.RESEARCH, now=NOW)
        assert h.read_manifest(
            "auditor", HoldoutRole.AUDITOR, now=NOW) == "a" * 32


class TestSingleUnlock:
    def test_unlock_requires_governance(self):
        h = make_holdout()
        with pytest.raises(HoldoutError, match="GOVERNANCE"):
            h.unlock("research-agent", HoldoutRole.RESEARCH, now=NOW,
                     unlock_note="sneaky")
        with pytest.raises(HoldoutError, match="GOVERNANCE"):
            h.unlock("auditor", HoldoutRole.AUDITOR, now=NOW,
                     unlock_note="also sneaky")

    def test_first_unlock_emits_event_and_pollutes(self):
        h = make_holdout()
        event = h.unlock("gov", HoldoutRole.GOVERNANCE, now=NOW,
                         unlock_note="pre-registered M9 evaluation")
        assert event == "HOLDOUT_ACCESS_EVENT#1"
        assert h.polluted_for_future_selection is True
        assert h.status == "UNLOCKED"
        audit = h.read_audit("gov", HoldoutRole.GOVERNANCE, now=NOW)
        assert any(e.action == "HOLDOUT_ACCESS_EVENT" and e.allowed
                   for e in audit)

    def test_second_unlock_refused(self):
        h = make_holdout()
        h.unlock("gov", HoldoutRole.GOVERNANCE, now=NOW, unlock_note="m9")
        with pytest.raises(HoldoutError, match="second unlock refused"):
            h.unlock("gov", HoldoutRole.GOVERNANCE, now=NOW,
                     unlock_note="retry after FAILED")
        assert h.unlock_count == 1

    def test_unlock_then_verdict_consumes(self):
        h = make_holdout()
        h.unlock("gov", HoldoutRole.GOVERNANCE, now=NOW, unlock_note="m9")
        assert h.record_verdict("gov", HoldoutRole.GOVERNANCE,
                                "INCONCLUSIVE", now=NOW) == "INCONCLUSIVE"
        assert h.final_holdout_status == "INCONCLUSIVE"
        assert h.status == "CONSUMED"
        with pytest.raises(HoldoutError, match="second unlock"):
            h.unlock("gov", HoldoutRole.GOVERNANCE, now=NOW,
                     unlock_note="another try")

    @pytest.mark.parametrize("verdict", VERDICT_STATES)
    def test_all_verdict_states_supported(self, verdict):
        h = make_holdout()
        h.unlock("gov", HoldoutRole.GOVERNANCE, now=NOW, unlock_note="m9")
        assert h.record_verdict("gov", HoldoutRole.GOVERNANCE, verdict,
                                now=NOW) == verdict
        assert h.final_holdout_status == verdict

    def test_unknown_verdict_rejected(self):
        h = make_holdout()
        h.unlock("gov", HoldoutRole.GOVERNANCE, now=NOW, unlock_note="m9")
        with pytest.raises(HoldoutError, match="verdict must be"):
            h.record_verdict("gov", HoldoutRole.GOVERNANCE, "MOSTLY_PASS",
                             now=NOW)

    def test_verdict_requires_unlock_first(self):
        h = make_holdout()
        with pytest.raises(HoldoutError, match="pre-registered unlock"):
            h.record_verdict("gov", HoldoutRole.GOVERNANCE, "PASS", now=NOW)


class TestChampionSelection:
    def test_champion_selection_via_holdout_refused_pre_and_post(self):
        h = make_holdout()
        with pytest.raises(HoldoutError, match="unconditionally"):
            h.select_champion("gov", HoldoutRole.GOVERNANCE, now=NOW)
        h.unlock("gov", HoldoutRole.GOVERNANCE, now=NOW, unlock_note="m9")
        with pytest.raises(HoldoutError, match="unconditionally"):
            h.select_champion("gov", HoldoutRole.GOVERNANCE, now=NOW)

    def test_research_cannot_record_verdict(self):
        h = make_holdout()
        h.unlock("gov", HoldoutRole.GOVERNANCE, now=NOW, unlock_note="m9")
        with pytest.raises(HoldoutError, match="GOVERNANCE"):
            h.record_verdict("research-agent", HoldoutRole.RESEARCH,
                             "PASS", now=NOW)


class TestHonestBoundary:
    def test_simulation_not_os_sandbox_is_documented(self):
        """The module docstring must disclose that this is an
        application-level simulation, not OS-level isolation."""
        import trading_lab.validation.holdout as mod
        assert "NOT an OS-level sandbox" in mod.__doc__
        assert "M4" in mod.__doc__
