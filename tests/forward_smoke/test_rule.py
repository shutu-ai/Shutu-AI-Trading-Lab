"""B2ForwardRule: frozen MA(2,4) above-state decisions."""

from __future__ import annotations

from decimal import Decimal

from apps.trading_daemon.rule import B2ForwardRule


def test_warmup_until_long_n_closes():
    rule = B2ForwardRule(short_n=2, long_n=4)
    assert rule.decide([]) == "WARMUP"
    assert rule.decide([Decimal("100")]) == "WARMUP"
    assert rule.decide([Decimal("100")] * 3) == "WARMUP"


def test_above_state_matches_hand_computed_ma_2_4():
    rule = B2ForwardRule(short_n=2, long_n=4)
    # closes: 100,101,102,103 -> MA2=(102,103)=102.5 > MA4=(101.5) -> LONG
    assert rule.decide([Decimal("100"), Decimal("101"),
                        Decimal("102"), Decimal("103")]) == "LONG"
    # drop: 100,101,102,90 -> MA2=(102+90)/2=96 < MA4=(100.75) -> FLAT
    assert rule.decide([Decimal("100"), Decimal("101"),
                        Decimal("102"), Decimal("90")]) == "FLAT"


def test_decision_uses_only_supplied_window():
    """The rule decides ONLY on the closes handed to it (the engine is
    responsible for the PIT window); extra history cannot be sensed."""
    rule = B2ForwardRule(short_n=2, long_n=4)
    window = [Decimal("100"), Decimal("101"), Decimal("102"), Decimal("103")]
    assert rule.decide(window) == "LONG"
    assert rule.decide(window[-4:]) == "LONG"
    # same window, one different tail -> different state (no hidden state)
    assert rule.decide([Decimal("100"), Decimal("101"),
                        Decimal("102"), Decimal("99")]) == "FLAT"


def test_rule_is_stateless_and_deterministic():
    window = [Decimal("100"), Decimal("101"), Decimal("102"), Decimal("103")]
    a = B2ForwardRule(short_n=2, long_n=4)
    b = B2ForwardRule(short_n=2, long_n=4)
    assert a.decide(window) == b.decide(window) == "LONG"
    assert a.params_digest == b.params_digest
