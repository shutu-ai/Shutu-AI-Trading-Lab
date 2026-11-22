"""Decision-equivalence drift guard: the forward daemon's B2 rule and
the historical backtest arm's B2 rule must make the SAME decisions on
the same closes (task S0.4/S1: reuse the frozen B2 definition; the
forward re-implementation may not drift from the backtest semantics).

The backtest decides at session closes and fills at the NEXT open
(delayed execution is a backtest simulation concern); the equivalence
here is at the DECISION level: every above-state flip of the forward
rule at close T must coincide with the backtest arm's buy/sell decision
at that same close.
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

from apps.trading_daemon.fixture import (  # noqa: E402
    SYMBOL, build_fixture_bars)
from apps.trading_daemon.rule import B2ForwardRule, FLAT, LONG  # noqa: E402
from trading_lab.backtest.arms import (  # noqa: E402
    SyntheticDataset, _run_ma_cross)
from trading_lab.backtest.engine import BacktestEngine  # noqa: E402
from trading_lab.validation import EvaluationProtocol  # noqa: E402


def test_forward_rule_decisions_match_backtest_b2_arm():
    bars = build_fixture_bars()
    dataset = SyntheticDataset(name="m35-equivalence-probe",
                               bars={SYMBOL: bars})
    protocol = EvaluationProtocol.load(
        REPO_ROOT / "configs" / "evaluation_protocol.yaml")

    eng = BacktestEngine(
        bars=dataset.bars, actions=list(dataset.actions),
        initial_cash=Decimal("100000"), protocol=protocol, seed=42,
        dataset_hash=dataset.dataset_hash,
        code_hash="equivalence-probe-not-an-official-run")
    _run_ma_cross(eng, dataset, 2, 4)

    bar_index = {b.ts_event_utc: i for i, b in enumerate(bars)}
    closes = [b.close for b in bars]

    backtest_flips: list[tuple[int, str]] = []
    for e in eng.events:
        if e.kind != "DECISION":
            continue
        side = e.detail.split("=", 1)[1]
        backtest_flips.append(
            (bar_index[e.ts], LONG if side == "buy" else FLAT))

    rule = B2ForwardRule(short_n=2, long_n=4)
    forward_flips: list[tuple[int, str]] = []
    previous: str | None = None
    for i in range(len(closes)):
        state = rule.decide(closes[:i + 1])
        if state == "WARMUP":
            continue
        if state != previous:
            forward_flips.append((i, state))
            previous = state

    assert backtest_flips, "backtest arm made no decisions"
    assert backtest_flips == forward_flips, (
        f"drift between forward rule and backtest B2 arm: "
        f"backtest={backtest_flips} forward={forward_flips}")


def test_forward_rule_flip_count_is_sane_for_fixture():
    """The fixture's oscillation produces multiple crosses; guard against
    a degenerate all-LONG or all-FLAT agreement that would hide drift."""
    bars = build_fixture_bars()
    closes = [b.close for b in bars]
    rule = B2ForwardRule(short_n=2, long_n=4)
    states = [rule.decide(closes[:i + 1]) for i in range(len(closes))]
    changes = sum(1 for a, b in zip(states, states[1:])
                  if a != b and a != "WARMUP" and b != "WARMUP")
    assert changes >= 4, f"fixture degenerated: {changes} flips"
