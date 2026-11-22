"""M3-R2 — official synthetic baseline run, batch ``m3-r2-batch-1``.

Successor of the r1 runner under the v2 protocol:

- **Full research code identity**: ``code_hash`` comes from
  ``validation.code_identity`` (runner + backtest + validation +
  contracts + security + top-level init — newline-normalized, sorted).
  The legacy r1 runner-only hash stays pinned as RUNNER_ONLY_LEGACY.
- **Sample gate enforced**: the official dataset is 120 fully synthetic
  sessions; ``official_sample_gate`` refuses (exit 2) any dataset below
  ``validation.min_bars=100`` before any engineering verdict exists.
  The 20-bar r1 run remains SYNTHETIC_SMOKE_ONLY legacy evidence.
- **Batch ledger**: a NEW file under ``artifacts/evidence/M3/r2/`` bound
  to batch ``m3-r2-batch-1``; its first entry (BATCH_INIT) registers the
  r1 legacy batch's hashes, consumed budget and ledger anchor. The r1
  ledger file is never touched. Budgets: fresh per-arm 3/3/3 for this
  batch; 4 MA-grid queries billed as queries.
- **Honest stamping**: every result carries sample_bars /
  sample_gate_verdict / trade_stats_status. Arms below
  ``min_trades_for_stats`` have trade statistics N_A — reported, not
  fabricated, and never read as "engineering invalid".

SYNTHETIC_ENGINEERING_ONLY: the output is engineering evidence for the
harness (conservation, PIT, determinism, budget accounting, sample-gate
mechanics). It is NOT alpha, NOT OOS, and must never be reported as
HIST_OOS_SUPPORTED. Real data stays BLOCKED_DATA.
"""

from __future__ import annotations

import datetime as dt
import dataclasses
import json
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

from trading_lab.backtest.arms import (  # noqa: E402
    SyntheticDataset,
    run_arm,
    select_ma_params,
)
from trading_lab.contracts import AdjustmentKind, MarketBar  # noqa: E402
from trading_lab.validation import EvaluationProtocol  # noqa: E402
from trading_lab.validation.code_identity import (  # noqa: E402
    build_code_identity,
)
from trading_lab.validation.cohorts import (  # noqa: E402
    CohortRole,
    CohortSpec,
    check_overlaps,
)
from trading_lab.validation.ledger import (  # noqa: E402
    ExperimentLedger,
    LedgerIntegrityError,
    LedgerLockedError,
    read_ledger_anchor,
    verify_ledger_file,
)
from trading_lab.validation.protocol import SampleGateVerdict  # noqa: E402

EVIDENCE_DIR = REPO_ROOT / "artifacts" / "evidence" / "M3" / "r2"
PROTOCOL_PATH = REPO_ROOT / "configs" / "evaluation_protocol.yaml"
RUNNER_REL = "scripts/run_m3_r2_baselines.py"
BATCH_ID = "m3-r2-batch-1"
DATASET_NAME = "m3-r2-official-v1"
N_SESSIONS = 120
TRAIN_VAL_END_FRACTION = 0.5  # first half = Train/Validation, rest = OOS


class OfficialRunRefused(RuntimeError):
    """The dataset fails a pre-registered official-run gate — no
    engineering verdict may be produced."""


def _plain(obj: Any) -> Any:
    """Deep-convert frozen protocol views (mappingproxy/tuple) to plain
    JSON-serializable structures."""
    if isinstance(obj, Mapping):
        return {str(k): _plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_plain(v) for v in obj]
    return obj


def synth_closes(n_sessions: int) -> list[Decimal]:
    """Deterministic synthetic closes: slow uptrend + a pure-Decimal
    triangle oscillation (period 12, amplitude 2.1). No randomness, no
    floats; reproducible by hand from the formula."""
    closes: list[Decimal] = []
    for i in range(n_sessions):
        c = i % 12
        triangle = c if c <= 6 else 12 - c          # 0..6, period 12
        osc = (Decimal(triangle) - Decimal(3)) * Decimal("0.7")
        closes.append(Decimal("100") + Decimal("0.18") * i + osc)
    return closes


def build_dataset(name: str = DATASET_NAME,
                  n_sessions: int = N_SESSIONS) -> SyntheticDataset:
    base = dt.datetime(2026, 2, 2, 21, 0, tzinfo=dt.timezone.utc)
    bars = [
        MarketBar.model_validate(dict(
            asset_id="SYN-ETF", ts_event_utc=base + dt.timedelta(days=i),
            ts_available_utc=base + dt.timedelta(days=i),
            interval="1d", open=c, high=c + Decimal("0.5"),
            low=c - Decimal("0.5"), close=c,
            volume=Decimal("5000000"), source="synthetic",
            adjustment=AdjustmentKind.RAW, quality="ok"))
        for i, c in enumerate(synth_closes(n_sessions))
    ]
    return SyntheticDataset(name=name, bars={"SYN-ETF": bars})


def official_sample_gate(protocol: EvaluationProtocol,
                         dataset: SyntheticDataset) -> SampleGateVerdict:
    """Enforce the pre-registered sample gate BEFORE any verdict:
    below ``validation.min_bars`` an official engineering run is
    refused outright (the data may only ever back smoke evidence)."""
    sessions = len({b.ts_event_utc for series in dataset.bars.values()
                    for b in series})
    gate = protocol.sample_gate(sessions)
    if not gate.satisfied:
        raise OfficialRunRefused(
            f"OFFICIAL RUN REFUSED: dataset has {gate.n_bars} sessions < "
            f"validation.min_bars={gate.min_bars} "
            f"({gate.verdict}); it may only serve SYNTHETIC_SMOKE_ONLY "
            "evidence — no engineering verdict may be issued")
    return gate


def _git_facts() -> tuple[str | None, str | None]:
    """Record commit + tree for independent re-verification (never part
    of code_hash). Missing git is recorded as None, not invented."""
    commit = tree = None
    for args, out in ((("rev-parse", "HEAD"), "commit"),
                      (("rev-parse", "HEAD^{tree}"), "tree")):
        try:
            proc = subprocess.run(
                ["git", *args], cwd=str(REPO_ROOT), capture_output=True,
                text=True, timeout=30)
            if proc.returncode == 0 and proc.stdout.strip():
                value = proc.stdout.strip()
                if out == "commit":
                    commit = value
                else:
                    tree = value
        except (OSError, subprocess.TimeoutExpired):
            pass
    return commit, tree


def main() -> int:
    protocol = EvaluationProtocol.load(PROTOCOL_PATH)
    batches = protocol.experiment_batches
    legacy = batches["m3-r1-batch-1"]

    dataset = build_dataset()
    gate = official_sample_gate(protocol, dataset)  # raises below min_bars
    print(f"sample_gate={gate.verdict} sessions={gate.n_bars} "
          f"min_bars={gate.min_bars} role={gate.role}")

    commit, tree = _git_facts()
    identity = build_code_identity(
        REPO_ROOT, runner=RUNNER_REL, git_commit=commit, git_tree=tree)
    code_hash = identity.code_hash
    print(f"protocol={protocol.protocol_id}/v{protocol.protocol_version} "
          f"protocol_hash={protocol.protocol_hash}")
    print(f"dataset_hash={dataset.dataset_hash}")
    print(f"code_hash={code_hash} (research-code-identity manifest: "
          f"{len(identity.files)} files)")

    ledger_path = EVIDENCE_DIR / "experiment-ledger.jsonl"
    if ledger_path.exists():
        print(f"REFUSED: {ledger_path} already exists — batch "
              f"{BATCH_ID} has been registered; a new experiment batch "
              "needs a new protocol version and a new ledger file")
        return 2

    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    (EVIDENCE_DIR / "code-identity-manifest.json").write_text(
        json.dumps(identity.to_dict(), indent=2, sort_keys=True),
        encoding="utf-8")

    limits = protocol.budget_limits()
    limits["per_arm_trials"] = dict(
        protocol.equal_trial_budget()["per_arm_trials"])
    ledger = ExperimentLedger(
        ledger_path, limits=limits, protocol_hash=protocol.protocol_hash,
        code_hash=code_hash, batch_id=BATCH_ID)
    try:
        # batch registration: lineage to the legacy r1 batch is explicit
        r1_anchor = read_ledger_anchor(
            REPO_ROOT / str(legacy["ledger"]))
        ledger.register_batch_init(
            BATCH_ID,
            dataset_name=DATASET_NAME,
            dataset_hash=dataset.dataset_hash,
            sample_gate=dict(
                verdict=gate.verdict, n_bars=gate.n_bars,
                min_bars=gate.min_bars, role=gate.role),
            code_identity=dict(
                schema=identity.schema, code_hash=code_hash,
                files=len(identity.files), runner=identity.runner,
                git_commit=identity.git_commit, git_tree=identity.git_tree),
            legacy_batch=dict(
                batch_id="m3-r1-batch-1",
                status=str(legacy["status"]),
                sample_gate=str(legacy["sample_gate"]),
                dataset_bars=int(legacy["dataset_bars"]),
                protocol_hash=str(legacy["protocol_hash"]),
                code_hash=str(legacy["code_hash"]),
                code_hash_scope=str(legacy["code_hash_scope"]),
                ledger=str(legacy["ledger"]),
                consumed=_plain(legacy["consumed_budget"]),
                anchor=dict(
                    entry_count=r1_anchor.entry_count,
                    head_digest=r1_anchor.head_digest,
                    tail_digest=r1_anchor.tail_digest,
                    created_ts=r1_anchor.created_ts)),
            evidence_class=protocol.data_scope)

        results: list[dict[str, Any]] = []
        # B2 parameter selection: Train/Validation slice only, grid billed
        n = gate.n_bars
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
        official_seed = protocol.seeds[0]
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
                    arm, seed=official_seed,
                    dataset_hash=dataset.dataset_hash,
                    note=json.dumps(r.as_dict(), sort_keys=True))
                results.append(dict(
                    arm=arm, seed=official_seed, cost_multiplier=mult,
                    net_return=str(r.net_return),
                    max_drawdown=str(r.max_drawdown),
                    tail_loss=str(r.tail_loss), fills=r.fills,
                    fees_total=str(r.fees_total),
                    sample_bars=r.sample_bars,
                    sample_gate_verdict=r.sample_gate_verdict,
                    trade_stats_status=r.trade_stats_status,
                    ledger_digest=entry["digest"]))
                print(f"OK {arm} seed={official_seed} mult={mult} "
                      f"net={r.net_return} dd={r.max_drawdown} "
                      f"fills={r.fills} gate={r.sample_gate_verdict} "
                      f"stats={r.trade_stats_status} "
                      f"ledger={entry['digest'][:12]}")

        # cohort hygiene disclosure for the official split (PIT-clean);
        # end bounds are exclusive per CohortSpec
        bars_ts = dataset.bars["SYN-ETF"]
        cohort_report = check_overlaps([
            CohortSpec(
                role=CohortRole.TRAIN,
                start=bars_ts[0].ts_event_utc,
                end=bars_ts[split_idx].ts_event_utc,
                symbols=frozenset({"SYN-ETF"})),
            CohortSpec(
                role=CohortRole.HIST_OOS,
                start=bars_ts[split_idx].ts_event_utc,
                end=bars_ts[-1].ts_event_utc + dt.timedelta(days=1),
                symbols=frozenset({"SYN-ETF"})),
        ])

        summary = {
            "batch_id": BATCH_ID,
            "protocol": dict(
                protocol_id=protocol.protocol_id,
                protocol_version=protocol.protocol_version,
                protocol_hash=protocol.protocol_hash,
                data_scope=protocol.data_scope,
                max_claimable_evidence=protocol.max_claimable_evidence),
            "code_identity": dict(
                code_hash=code_hash,
                manifest_files=len(identity.files),
                runner=identity.runner,
                schema=identity.schema,
                git_commit=identity.git_commit,
                git_tree=identity.git_tree,
                legacy_r1_code_hash=str(legacy["code_hash"]),
                legacy_scope=str(legacy["code_hash_scope"])),
            "dataset": dict(
                name=DATASET_NAME, dataset_hash=dataset.dataset_hash,
                sessions=gate.n_bars, source="synthetic"),
            "sample_gate": dict(
                verdict=gate.verdict, n_bars=gate.n_bars,
                min_bars=gate.min_bars,
                enforcement="OfficialRunRefused below min_bars"),
            "evidence_class": "SYNTHETIC_ENGINEERING_ONLY",
            "runs": len(results),
            "failures": failures,
            "b2_params_frozen": list(params),
            "selection": "Train/Validation-only; grid billed; frozen for OOS",
            "trade_stats_note": (
                "Arms below validation.min_trades_for_stats=10 fill "
                "events report trade_stats_status="
                "N_A_INSUFFICIENT_TRADES: statistics not computable — "
                "engineering gates (conservation/PIT/determinism) are "
                "independent of this and reported separately"),
            "cohort_overlap_independent": cohort_report.independent,
            "results": results,
            "claim": ("engineering evidence only — NOT alpha, NOT "
                      "HIST_OOS_SUPPORTED, NOT deployable; synthetic "
                      "upward drift means positive net_return is a data "
                      "shape artifact, not a market judgment"),
        }
        (EVIDENCE_DIR / "experiment-summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")

        counters = dict(ledger.counters())
        ok_chain, msg_chain = ledger.verify_chain()
        anchor = ledger.export_anchor()
    finally:
        ledger.close()

    (EVIDENCE_DIR / "ledger-anchor.json").write_text(
        json.dumps({
            "note": ("external anchor for m3-r2-batch-1 — store/keep this "
                     "committed record OUTSIDE the ledger file; it is what "
                     "makes tail truncation / whole-file replacement "
                     "detectable on the next open. Trust equals this "
                     "file's own storage (documented boundary)."),
            **dataclasses.asdict(anchor)},
            indent=2, sort_keys=True), encoding="utf-8")
    ok_file, msg_file = verify_ledger_file(ledger_path)
    print(f"ledger counters: {counters}")
    print(f"ledger chain: {ok_chain} ({msg_chain})")
    print(f"ledger file re-verify: {ok_file} ({msg_file})")
    print(f"ledger anchor: head={anchor.head_digest[:12]}… "
          f"tail={str(anchor.tail_digest)[:12]}… "
          f"entries={anchor.entry_count} → ledger-anchor.json")
    return 0 if (ok_chain and ok_file and failures == 0
                 and gate.satisfied) else 1


if __name__ == "__main__":
    sys.exit(main())
