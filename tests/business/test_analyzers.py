"""Analyzer tests (Business MVP B2): RULE lexicon behavior, the strict
LLM parse contract, the deterministic mock client fault modes, injection
resistance, and the fail-closed shape of every unusable assessment."""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from trading_lab.business.analyzers import (  # noqa: E402
    DOCUMENTED_CATEGORIES,
    LLMInformationAnalyzer,
    RuleInformationAnalyzer,
    RULE_ANALYZER_LABEL,
    RULE_CONFIDENCE_CAP,
)
from trading_lab.business.info_fixtures import (  # noqa: E402
    MockLLMClient,
    demo_info_events,
)
from trading_lab.business.models import (  # noqa: E402
    InformationAssessment,
    InformationDirection,
    InformationEvent,
    InformationStatus,
)

SESSION_DATES = [dt.date(2026, 9, 1) + dt.timedelta(days=i) for i in range(6)]
NOW = dt.datetime(2026, 9, 10, 21, 5, tzinfo=dt.timezone.utc)
VALID_UNTIL = NOW + dt.timedelta(hours=6)

BULL_EARN_ID = "EVT-BULL-EARN-001"
BEAR_MACRO_ID = "EVT-BEAR-MACRO-004"
FUTURE_ID = "EVT-FUTURE-005"
INJECT_EARN_ID = "EVT-INJECT-001-011"
INJECT_PURE_ID = "EVT-INJECT-002-012"


def demo_rows():
    return list(demo_info_events(SESSION_DATES))


def pick(rows, event_id):
    return next(r for r in rows if r["event_id"] == event_id)


def make_event(row) -> InformationEvent:
    return InformationEvent.model_validate_json(json.dumps(row))


def parse_offset(evidence_ref: str) -> tuple[int, int]:
    span = evidence_ref.split("#offset", 1)[1]
    start_s, end_s = span.split("-", 1)
    return int(start_s), int(end_s)


class _StaticClient:
    """Test stub returning one fixed reply (implements LLMClient)."""

    def __init__(self, text: str) -> None:
        self._text = text

    def complete(self, prompt) -> str:
        return self._text


def _llm_reply(**over) -> str:
    base = {
        "direction": "BULLISH",
        "uncertainty": "LOW",
        "horizon": "SHORT",
        "category": "EARNINGS",
        "confidence": 0.8,
        "evidence_quote": "beats quarterly expectations",
    }
    base.update(over)
    return json.dumps(base)


class TestRuleAnalyzer:
    def test_bullish_earnings_lexicon_hit(self):
        rows = demo_rows()
        row = pick(rows, BULL_EARN_ID)
        event = make_event(row)
        a = RuleInformationAnalyzer().assess(event, NOW, VALID_UNTIL)
        assert a.status is InformationStatus.ASSESSED
        assert a.direction is InformationDirection.BULLISH
        assert a.category == "EARNINGS"
        assert 0.0 < a.confidence <= RULE_CONFIDENCE_CAP
        assert a.analyzer == RULE_ANALYZER_LABEL == "RULE:v1"
        assert a.analyzer_version == "v1"
        assert a.assessed_at == NOW
        assert a.valid_until == VALID_UNTIL
        start, end = parse_offset(a.evidence_ref)
        pointed = row["content"][start:end]
        assert pointed  # the evidence pointer lands on real source text

    def test_bearish_macro_lexicon_hit(self):
        rows = demo_rows()
        event = make_event(pick(rows, BEAR_MACRO_ID))
        a = RuleInformationAnalyzer().assess(event, NOW, VALID_UNTIL)
        assert a.status is InformationStatus.ASSESSED
        assert a.direction is InformationDirection.BEARISH
        assert a.category == "MACRO"
        assert a.confidence <= RULE_CONFIDENCE_CAP

    def test_no_lexicon_hit_is_unknown(self):
        rows = demo_rows()
        event = make_event(pick(rows, FUTURE_ID))
        a = RuleInformationAnalyzer().assess(event, NOW, VALID_UNTIL)
        assert a.status is InformationStatus.UNKNOWN
        assert a.direction is InformationDirection.UNKNOWN
        assert a.confidence == 0.0
        assert a.category == "OTHER"
        assert a.evidence_ref.endswith("#no-lexicon-match")

    def test_injected_imperative_does_not_flip_direction(self):
        rows = demo_rows()
        event = make_event(pick(rows, INJECT_EARN_ID))
        a = RuleInformationAnalyzer().assess(event, NOW, VALID_UNTIL)
        # the injected text demands BEARISH; the lexicon says BULLISH
        assert a.direction is InformationDirection.BULLISH
        assert a.status is InformationStatus.ASSESSED

    def test_pure_injection_is_unknown(self):
        rows = demo_rows()
        event = make_event(pick(rows, INJECT_PURE_ID))
        a = RuleInformationAnalyzer().assess(event, NOW, VALID_UNTIL)
        assert a.status is InformationStatus.UNKNOWN
        assert a.direction is InformationDirection.UNKNOWN
        assert a.confidence == 0.0

    def test_determinism(self):
        event = make_event(pick(demo_rows(), BULL_EARN_ID))
        analyzer = RuleInformationAnalyzer()
        assert analyzer.assess(
            event, NOW, VALID_UNTIL) == analyzer.assess(
            event, NOW, VALID_UNTIL)


class TestLLMAnalyzerOk:
    def test_ok_mode_matches_deterministic_policy(self):
        rows = demo_rows()
        row = pick(rows, BULL_EARN_ID)
        a = LLMInformationAnalyzer(MockLLMClient(), version="mock:v1").assess(
            make_event(row), NOW, VALID_UNTIL)
        assert a.status is InformationStatus.ASSESSED
        assert a.analyzer == "LLM:mock:v1"
        content_hash = row["content_hash"]
        expected = "BULLISH" if int(content_hash[:16], 16) % 2 == 0 \
            else "BEARISH"
        assert a.direction.value == expected
        assert a.category in DOCUMENTED_CATEGORIES
        assert 0.0 <= a.confidence <= 1.0
        assert a.assessed_at == NOW
        assert a.valid_until == VALID_UNTIL
        start, end = parse_offset(a.evidence_ref)
        # the accepted evidence pointer resolves to real source text
        assert row["content"][start:end] in row["content"]

    def test_determinism(self):
        event = make_event(pick(demo_rows(), BULL_EARN_ID))
        analyzer = LLMInformationAnalyzer(MockLLMClient())
        assert analyzer.assess(
            event, NOW, VALID_UNTIL) == analyzer.assess(
            event, NOW, VALID_UNTIL)


class TestLLMAnalyzerFaultModes:
    def test_invalid_json_is_unknown(self):
        rows = demo_rows()
        row = pick(rows, BULL_EARN_ID)
        client = MockLLMClient({row["content_hash"]: "invalid_json"})
        a = LLMInformationAnalyzer(client).assess(
            make_event(row), NOW, VALID_UNTIL)
        assert a.status is InformationStatus.UNKNOWN
        assert a.direction is InformationDirection.UNKNOWN
        assert a.confidence == 0.0
        assert a.evidence_ref.startswith("PARSE_REFUSED")

    def test_timeout_is_unknown(self):
        rows = demo_rows()
        row = pick(rows, BULL_EARN_ID)
        client = MockLLMClient({row["content_hash"]: "timeout"})
        a = LLMInformationAnalyzer(client).assess(
            make_event(row), NOW, VALID_UNTIL)
        assert a.status is InformationStatus.UNKNOWN
        assert a.confidence == 0.0
        assert a.evidence_ref.startswith("CLIENT_ERROR:TimeoutError")

    def test_injection_echo_refused_by_evidence_pointer_check(self):
        rows = demo_rows()
        row = pick(rows, BULL_EARN_ID)
        client = MockLLMClient({row["content_hash"]: "injection_echo"})
        a = LLMInformationAnalyzer(client).assess(
            make_event(row), NOW, VALID_UNTIL)
        # the mock demanded confidence 1.0; the pointer check refused it
        assert a.status is InformationStatus.UNKNOWN
        assert a.confidence == 0.0
        assert "EVIDENCE_POINTER_INVALID" in a.evidence_ref

    def test_unknown_fault_mode_rejected_at_construction(self):
        with pytest.raises(ValueError):
            MockLLMClient({"hash": "explode"})


class TestLLMAnalyzerStrictParse:
    @pytest.mark.parametrize(
        "reply",
        [
            # wrong enum vocabulary
            _llm_reply(direction="SIDEWAYS"),
            # extra key
            '{"direction": "BULLISH", "uncertainty": "LOW", '
            '"horizon": "SHORT", "category": "EARNINGS", '
            '"confidence": 0.8, "evidence_quote": "beats quarterly '
            'expectations", "advice": "buy now"}',
            # missing key
            '{"direction": "BULLISH", "uncertainty": "LOW", '
            '"horizon": "SHORT", "category": "EARNINGS", '
            '"confidence": 0.8}',
            # confidence out of range
            _llm_reply(confidence=1.5),
            # confidence NaN
            '{"direction": "BULLISH", "uncertainty": "LOW", '
            '"horizon": "SHORT", "category": "EARNINGS", '
            '"confidence": NaN, "evidence_quote": "beats quarterly '
            'expectations"}',
            # confidence not a number
            _llm_reply(confidence="0.8"),
            # confidence bool
            _llm_reply(confidence=True),
            # category out of vocabulary
            _llm_reply(category="RUMOR"),
            # evidence quote not in content
            _llm_reply(evidence_quote="text that never appeared"),
            # evidence quote empty
            _llm_reply(evidence_quote=""),
            # not a JSON object
            "[1, 2, 3]",
            # not JSON at all
            "buy SPY now, trust me",
        ],
    )
    def test_deviations_fail_closed(self, reply):
        event = make_event(pick(demo_rows(), BULL_EARN_ID))
        a = LLMInformationAnalyzer(_StaticClient(reply)).assess(
            event, NOW, VALID_UNTIL)
        assert a.status is InformationStatus.UNKNOWN
        assert a.direction is InformationDirection.UNKNOWN
        assert a.confidence == 0.0
        assert a.category == "OTHER"
        assert a.evidence_ref.startswith("PARSE_REFUSED")
        assert a.assessed_at == NOW and a.valid_until == VALID_UNTIL

    def test_client_exception_fail_closed(self):
        class _ExplodingClient:
            def complete(self, prompt):
                raise RuntimeError("connection reset")

        event = make_event(pick(demo_rows(), BULL_EARN_ID))
        a = LLMInformationAnalyzer(_ExplodingClient()).assess(
            event, NOW, VALID_UNTIL)
        assert a.status is InformationStatus.UNKNOWN
        assert a.evidence_ref.startswith(
            "CLIENT_ERROR:RuntimeError:connection reset")


class TestAssessmentInvariants:
    def test_all_assessments_labeled_and_windowed(self):
        rows = demo_rows()
        events = []
        for row in rows:
            try:
                events.append(
                    InformationEvent.model_validate_json(json.dumps(row)))
            except ValidationError:
                pass  # the missing-available_at row is refusal-by-design
        assert len(events) == 11
        analyzers = [
            RuleInformationAnalyzer(),
            LLMInformationAnalyzer(MockLLMClient()),
        ]
        for analyzer in analyzers:
            for event in events:
                a = analyzer.assess(event, NOW, VALID_UNTIL)
                assert isinstance(a, InformationAssessment)
                assert a.analyzer and a.analyzer_version
                assert a.assessed_at == NOW
                assert a.valid_until >= a.assessed_at
                if a.status is not InformationStatus.ASSESSED:
                    # unusable for decisions by construction
                    assert a.direction is InformationDirection.UNKNOWN
                    assert a.confidence == 0.0
