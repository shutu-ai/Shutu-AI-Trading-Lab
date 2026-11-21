"""M3-R1-T7 — official synthetic baseline experiment runner.

Runs the frozen-protocol B0/B1/B2 arms on a deterministic synthetic
dataset (seeds and cost multipliers from the protocol), registering every
trial, failure, retry and query in the hash-chained experiment ledger at
``artifacts/evidence/M3/r1/experiment-ledger.jsonl``.

SYNTHETIC_ENGINEERING_ONLY: the output is engineering evidence for the
harness (conservation, PIT, determinism, budget accounting). It is NOT
alpha, NOT OOS, and must never be reported as HIST_OOS_SUPPORTED.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

from trading_lab.backtest.arms import (  # noqa: E402
    SyntheticDataset,
    run_arm,
    select_ma_params,
)
from trading_lab.contracts import AdjustmentKind, MarketBar  # noqa: E402
from trading_lab.security.canonical import sha256_hex  # noqa: E402
from trading_lab.validation import EvaluationProtocol  # noqa: E402
from trading_lab.validation.cohorts import (  # noqa: E402
    CohortRole,
    CohortSpec,
    check_overlaps,
)
from trading_lab.validation.ledger import BudgetExceeded, ExperimentLedger  # noqa: E402

EVIDENCE_DIR = REPO_ROOT / "artifacts" / "evidence" / "M3" / "r1"
PROTOCOL_PATH = REPO_ROOT / "configs" / "evaluation_protocol.yaml"

# Deterministic synthetic price path (hand-written, reproducible by eye):
# 20 sessions around 100 with a mild trend leg — no randomness at all.
PRICES = [
    "100.0", "100.6", "99.8", "101.2", "100.9", "102.1", "101.6", "102.8",
    "103.4", "102.6", "103.9", "104.7", "104.1", "105.2", "106.0", "105.4",
    "106.3", "107.1", "106.5", "107.4",
]
TRAIN_VAL_END_FRACTION = 0.5  # first half = Train/Validation, rest = OOS


def build_dataset() -> SyntheticDataset:
    base = dt.datetime(2026, 1, 5, 21, 0, tzinfo=dt.timezone.utc)
    bars = [
        MarketBar.model_validate(dict(
            asset_id="SYN-ETF", ts_event_utc=base + dt.timedelta(days=i),
            ts_available_utc=base + dt.timedelta(days=i),
            interval="1d", open=Decimal(p), high=Decimal(p) * Decimal("1.01"),
            low=Decimal(p) * Decimal("0.99"), close=Decimal(p),
            volume=Decimal("5000000"), source="synthetic",
            adjustment=AdjustmentKind.RAW, quality="ok"))
        for i, p in enumerate(PRICES)
    ]
    return SyntheticDataset(name="m3-r1-official-v1", bars={"SYN-ETF": bars})


def main() -> int:
    protocol = EvaluationProtocol.load(PROTOCOL_PATH)
    dataset = build_dataset()
    code_hash = sha256_hex(
        (REPO_ROOT / "scripts" / "run_m3_baselines.py").read_bytes())
    print(f"protocol_hash={protocol.protocol_hash}")
    print(f"dataset_hash={dataset.dataset_hash}")
    print(f"code_hash={code_hash}")

    ledger = ExperimentLedger(
        EVIDENCE_DIR / "experiment-ledger.jsonl",
        limits={
            "max_total_trials": protocol.budget_limits()["max_total_trials"],
            "max_search_queries": protocol.budget_limits()[
                "max_search_queries"],
            "max_failures_before_halt": protocol.budget_limits()[
                "max_failures_before_halt"],
            "max_hypotheses": protocol.budget_limits()["max_hypotheses"],
            "per_arm_trials": dict(
                protocol.equal_trial_budget()["per_arm_trials"]),
        },
        protocol_hash=protocol.protocol_hash, code_hash=code_hash)

    results = []
    # B2 parameter selection: Train/Validation slice only, grid billed
    n = len(PRICES)
    split_idx = int(n * TRAIN_VAL_END_FRACTION)
    train_val_end = dataset.bars["SYN-ETF"][split_idx - 1].ts_event_utc
    params, sel_trials = select_ma_params(
        dataset, protocol, train_val_end=train_val_end,
        code_hash=code_hash, seed=protocol.seeds[0])
    for idx in range(sel_trials):
        ledger.register_query(note=f"MA grid selection trial "
                                   f"{idx + 1}/{sel_trials}")
    print(f"B2 params selected on Train/Validation (<= {train_val_end}): "
          f"{params} ({sel_trials} grid trials billed as queries)")

    failures = 0
    official_seed = protocol.seeds[0]  # per protocol budget note
    for arm in ("B0_cash", "B1_buy_hold", "B2_single_rule"):
        for mult in protocol.cost_multipliers:
            kw = {"ma_params": params} if arm == "B2_single_rule" else {}
            try:
                r = run_arm(arm, dataset, protocol, seed=official_seed,
                            code_hash=code_hash, cost_multiplier=mult,
                            **kw)
            except Exception as exc:  # noqa: BLE001 — billed as failure
                failures += 1
                ledger.register_failure(arm, seed=official_seed,
                                        dataset_hash=dataset.dataset_hash,
                                        error=repr(exc))
                print(f"FAILED {arm} seed={official_seed} mult={mult}: "
                      f"{exc!r}")
                continue
            entry = ledger.register_trial(
                arm, seed=official_seed, dataset_hash=dataset.dataset_hash,
                note=json.dumps(r.as_dict(), sort_keys=True))
            results.append((arm, official_seed, mult, r, entry["digest"]))
            print(f"OK {arm} seed={official_seed} mult={mult} "
                  f"net={r.net_return} dd={r.max_drawdown} "
                  f"fees={r.fees_total} ledger={entry['digest'][:12]}")

    summary = {
        "protocol_hash": protocol.protocol_hash,
        "dataset_hash": dataset.dataset_hash,
        "code_hash": code_hash,
        "data_scope": protocol.data_scope,
        "max_claimable_evidence": protocol.max_claimable_evidence,
        "evidence_class": "SYNTHETIC_ENGINEERING_ONLY",
        "runs": len(results),
        "failures": failures,
        "b2_params_frozen": list(params),
        "selection": "Train/Validation-only; grid billed; frozen for OOS",
        "claim": ("engineering evidence only — NOT alpha, NOT "
                  "HIST_OOS_SUPPORTED, NOT deployable"),
    }
    (EVIDENCE_DIR / "experiment-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    counters = dict(ledger.counters())
    ok, msg = ledger.verify_chain()
    ledger.close()
    print(f"ledger counters: {counters}")
    print(f"ledger chain: {ok} ({msg})")
    return 0 if (ok and failures == 0) else 1


if __name__ == "__main__":
    sys.exit(main())
