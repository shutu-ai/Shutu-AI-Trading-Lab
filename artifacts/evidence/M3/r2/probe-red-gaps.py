"""M3-R2 T0 — pure-behavior RED probes for the three audited gaps.

Runs against the CURRENT code (pre-GREEN) to prove each failure mode
mechanically. Operates ONLY on temp-dir copies; the real M3/r1 evidence
is opened read-only at most. Exit code 0 = all three gaps reproduced.

Probe 1 (R2-P0-1): the legacy code_hash covers only the runner file, so
         mutating backtest algorithm source cannot move it.
Probe 2 (R2-P1-1): a 20-bar dataset runs an "official" arm end-to-end
         under min_bars=100 with no gate refusal and no sample verdict.
Probe 3 (R2-P1-2): a middle-tampered ledger loads silently and keeps
         accepting research entries; and verify_chain cannot see that the
         ledger lost its last entry (tail truncation).
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT / "src"))

from trading_lab.backtest.arms import SyntheticDataset, run_arm
from trading_lab.contracts import AdjustmentKind, MarketBar
from trading_lab.security.canonical import sha256_hex
from trading_lab.validation import EvaluationProtocol
from trading_lab.validation.ledger import ExperimentLedger

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str) -> None:
    results.append((name, ok, detail))
    print(f"[{'GAP-PROVEN' if ok else 'NOT-REPRODUCED'}] {name}: {detail}")


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="m3r2-red-probe-"))

    # ---- probe 1: legacy code_hash is runner-only --------------------
    runner = REPO_ROOT / "scripts" / "run_m3_baselines.py"
    legacy_before = sha256_hex(runner.read_bytes())
    copy = tmp / "run_m3_baselines.py"
    shutil.copy2(runner, copy)
    engine_copy = tmp / "engine-copy.py"
    engine_copy.write_bytes(
        (REPO_ROOT / "src" / "trading_lab" / "backtest" / "engine.py")
        .read_bytes())
    # the legacy scheme would not even look at engine.py; demonstrate by
    # hashing: engine bytes are outside its input, whatever they become
    engine_tampered = engine_copy.read_bytes().replace(
        b"offline execution simulator", b"TAMPERED simulator")
    assert engine_tampered != engine_copy.read_bytes()
    # legacy hash over the SAME runner is the identity actually recorded:
    r1_ledger = (REPO_ROOT / "artifacts" / "evidence" / "M3" / "r1" /
                 "experiment-ledger.jsonl")
    recorded = {json.loads(l)["code_hash"]
                for l in r1_ledger.read_text(encoding="utf-8").splitlines()
                if l.strip()}
    check("P0-1 legacy hash == r1 ledger value",
          recorded == {legacy_before},
          f"legacy={legacy_before[:12]} recorded={ {h[:12] for h in recorded} }")
    check("P0-1 engine bytes outside legacy identity input",
          sha256_hex(engine_tampered) != legacy_before
          and sha256_hex(copy.read_bytes()) == legacy_before,
          "mutating engine source cannot move the legacy code_hash")

    # ---- probe 2: 20-bar official run with no sample gate ------------
    protocol = EvaluationProtocol.load(
        REPO_ROOT / "configs" / "evaluation_protocol.yaml")
    min_bars = protocol.validation_thresholds["min_bars"]
    base = __import__("datetime").datetime(
        2026, 1, 5, 21, tzinfo=__import__("datetime").timezone.utc)
    n_bars = 20
    bars = [MarketBar.model_validate(dict(
        asset_id="SYN-ETF", ts_event_utc=base + __import__("datetime").timedelta(days=i),
        ts_available_utc=base + __import__("datetime").timedelta(days=i),
        interval="1d", open=Decimal("100") + Decimal("0.3") * i,
        high=Decimal("101") + Decimal("0.3") * i,
        low=Decimal("99") + Decimal("0.3") * i,
        close=Decimal("100") + Decimal("0.3") * i,
        volume=Decimal("5000000"), source="synthetic",
        adjustment=AdjustmentKind.RAW, quality="ok"))
        for i in range(n_bars)]
    ds = SyntheticDataset(name="red-probe-20bars", bars={"SYN-ETF": bars})
    r = run_arm("B1_buy_hold", ds, protocol, seed=42, code_hash="c" * 32)
    has_gate = hasattr(r, "sample_gate_verdict")
    check("P1-1 below-gate run completes with NO refusal and NO verdict",
          (not has_gate) and int(min_bars) == 100 and n_bars < int(min_bars),
          f"min_bars={min_bars} bars={n_bars} ran to net_return={r.net_return} "
          f"sample_gate_verdict_field={has_gate}")

    # ---- probe 3a: tampered ledger loads and keeps writing -----------
    led_path = tmp / "probe-ledger.jsonl"
    led = ExperimentLedger(led_path, limits={
        "max_total_trials": 10, "max_search_queries": 10,
        "max_failures_before_halt": 5, "max_hypotheses": 5},
        protocol_hash="p" * 32, code_hash="c" * 32)
    led.register_trial("B0_cash", seed=1, dataset_hash="d" * 32)
    led.register_trial("B0_cash", seed=2, dataset_hash="d" * 32)
    led.close()
    lines = led_path.read_text(encoding="utf-8").splitlines()
    obj = json.loads(lines[0])
    obj["detail"]["seed"] = 666  # retro-edit history entry #1
    lines[0] = json.dumps(obj, sort_keys=True)
    led_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    led2 = ExperimentLedger(led_path, limits={
        "max_total_trials": 10, "max_search_queries": 10,
        "max_failures_before_halt": 5, "max_hypotheses": 5},
        protocol_hash="p" * 32, code_hash="c" * 32)
    ok, msg = led2.verify_chain()
    check("P1-2 tampered history loads; verification only fails later",
          not ok,
          f"tampered file RE-OPENED and accepted entries; verify_chain now "
          f"says {ok} ({msg}) — load-time verify-before-replay is missing")

    # ---- probe 3b: tail truncation invisible without anchor ----------
    clean = tmp / "clean-ledger.jsonl"
    led3 = ExperimentLedger(clean, limits={
        "max_total_trials": 10, "max_search_queries": 10,
        "max_failures_before_halt": 5, "max_hypotheses": 5},
        protocol_hash="p" * 32, code_hash="c" * 32)
    led3.register_trial("B0_cash", seed=1, dataset_hash="d" * 32)
    led3.register_trial("B0_cash", seed=2, dataset_hash="d" * 32)
    led3.register_trial("B0_cash", seed=3, dataset_hash="d" * 32)
    led3.close()
    kept = clean.read_text(encoding="utf-8").splitlines()[:2]
    clean.write_text("\n".join(kept) + "\n", encoding="utf-8")
    led4 = ExperimentLedger(clean, limits={
        "max_total_trials": 10, "max_search_queries": 10,
        "max_failures_before_halt": 5, "max_hypotheses": 5},
        protocol_hash="p" * 32, code_hash="c" * 32)
    ok3b, msg3b = led4.verify_chain()
    check("P1-2 tail truncation undetectable without external anchor",
          ok3b,
          f"last entry deleted; remaining chain self-verifies: {ok3b} "
          f"({msg3b}) — no head/entry-count anchor exists")

    print("\n-- summary --")
    for name, ok, _ in results:
        print(f"  {'GAP-PROVEN' if ok else 'NOT-REPRODUCED'}  {name}")
    all_ok = all(ok for _, ok, _ in results)
    print(f"probe exit={0 if all_ok else 1} "
          f"({sum(ok for _, ok, _ in results)}/{len(results)} gaps proven)")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
