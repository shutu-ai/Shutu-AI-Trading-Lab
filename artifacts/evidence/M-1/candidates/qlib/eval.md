# Qlib evaluation — Shutu AI Trading Lab M-1 POC

Evaluated: 2026-11-19. Evaluator: Claude Code agent (audit trail in `logs/`).
Clone: `third_party/qlib` @ SHA `54355232463878d2eebb91fe0ee5fa7fa1f5976c` (commit 2026-10-08, "fix(security): constrain config-driven code execution (#2340)"), not modified.
Venv: `third_party/.venv-qlib` (Python 3.13.15, pip 26.2.1). All downloads via proxy http://192.168.1.2:8080.

## [Install]

- **PASS** — `pip install -e third_party/qlib` from the pinned clone succeeded on Python 3.13.15, exit 0. Log: `logs/install.txt` (first `=== CMD ===` block).
  - `Successfully built pyqlib gym` / `Successfully installed ... pyqlib` — pyqlib built as an editable (cp313) wheel; `gym 0.26.2` built from source as a dependency.
  - No dependency-resolution failure occurred; **no pins were changed for the install itself**. All heavy deps resolved to cp313 wheels (numpy 2.5.5, pandas 2.3.3, pyarrow 23.0.1 at install time, lightgbm 4.7.0, mlflow 3.12.0, scikit-learn 1.9.1).
  - PyPI `pyqlib` fallback (task 1b) was NOT needed.
- **PASS (import)** — `import qlib; qlib.__version__ == '0.9.8'`; `qlib.init(provider_uri=<sample data>, region='cn')` OK. Log: `logs/install.txt` (last block). See [Windows/Py3.13 compat] for the cwd-shadowing gotcha hit during first import attempt.

## [Version]

- **PASS** — installed package reports **pyqlib 0.9.8** via `importlib.metadata.version('pyqlib')`. Log: `logs/install.txt`.
  - Note: `qlib.__version__` exists only when `import qlib` resolves to the real package (see cwd note below); top-level attribute is `qlib.__version__` set from `qlib/_version.py` (setuptools-scm). `pyqlib` PyPI name, 0.9.8 is qlib's latest dev-line version from the pinned clone.

## [License]

- **PASS** — `LICENSE` is standard MIT, "Copyright (c) Microsoft Corporation" (21 lines). Verified by reading the file; head shown in install session transcript and in commit metadata.
- **PASS (NOTICE)** — no `NOTICE` file exists in the clone (repo root listing: CHANGELOG.md, LICENSE, README.md, SECURITY.md, CODE_OF_CONDUCT.md, ...).

## [Data]

- **PASS** — qlib's public sample dataset downloaded through the proxy and saved under `data/`:
  - `data/qlib_data_cn_1d_latest.zip` — 240,739,135 bytes, HTTP 200, from `https://github.com/SunsetWolf/qlib_dataset/releases/download/v3/qlib_data_cn_1d_latest.zip` (the current full CN daily dataset; size matches the GitHub release asset exactly). Extracted to `data/qlib_data_cn_1d/`. Log: `logs/data.txt`.
  - First attempt `v3/qlib_data_simple_cn_1d_latest.zip` returned HTTP body `Not Found` (9 bytes) — the "simple" variant only exists in the v2 release (51,810,838 B); recorded in `logs/data.txt`, the 9-byte file was deleted.
  - `data/qlib_data_pit_1d_latest.zip` — 2,865 bytes, HTTP 200, v2 release; a 2-stock PIT demo (`sh600519.csv`, `sz000725.csv`, announcement-date/period/value rows), extracted to `data/qlib_data_pit_1d/`.

- Dataset facts (verified from extracted files):
  - Calendar (`calendars/day.txt`): 1999-11-10 → **2022-12-30**, 5,491 trading days.
  - Instruments (`instruments/`): `all.txt` 4,368 instruments (includes 3 index series SH000300/SH000903 etc. + stocks); `csi300.txt` 820 rows; `csi100.txt` 246; `csi500.txt` 2,017. `features/` holds 4,368 symbol dirs.
  - Fields per stock: `open, high, low, close, volume, factor, change` (.day.bin) — OHLCV + adjustment factor + pct change only. **No fundamentals in the sample dataset** (PIT demo is separate, 2 stocks).
  - `instruments/csi300.txt` encodes **historical index membership windows** (e.g. `SH600000  2005-01-01  2020-09-25`) — qlib's market=csi300 uses point-in-time membership, not today's constituents.
  - **Survivorship caveat (verified from data):** 88 instruments in `all.txt` end before the calendar end; **87 of them stop at exactly 2020-09-25** and 1 at 2022-06-09. The mass cutoff at one date indicates a data-collection snapshot boundary, not organic delisting dates. So delisted-ish names are present, but true delisting history is not represented; Yahoo Finance-sourced sample data (qlib's own warning: "the quality of the data might not be perfect").

## [Runtime]

- **FAIL → PASS after a dependency downgrade within qlib's own metadata.** Log: `logs/runtime.txt`.
  1. First `qrun config/workflow_config_lightgbm_Alpha158.yaml` (mlflow 3.12.0, the latest satisfying qlib's `mlflow<3.13` pin) **died at startup**, before any data loading:
     `MlflowException: Run 'aac39cbe3678478ab7c1600edaf9dd69' not found`
     from `qlib/workflow/recorder.py:349` `mlflow.start_run(self.id, ...)` → mlflow file store. qlib passes a fresh recorder UUID as the mlflow run id; mlflow 3.x no longer accepts that (file-store backend also prints a deprecation FutureWarning).
  2. **Pin change recorded:** installed `mlflow<3` → **mlflow 2.22.5** (still inside qlib's own declared constraint `mlflow<3.13`; pyproject comment says mlflow 3.13 disables qlib's filesystem tracking backend). Side effects recorded in `logs/install.txt`: pyarrow 23.0.1 → 19.0.1 (mlflow 2.22 constraint), packaging downgraded to 24.2 (pip reports `vcs-versioning 2.6.0 requires packaging>=26.2 ... incompatible` — build-time-only package, no runtime impact on qlib; log: `logs/install.txt`).
  3. Retry with mlflow 2.22.5: **PASS — full end-to-end run, exit 0.** Log: `logs/runtime.txt` (after `=== RETRY ===`), metrics extract in `metrics_output.txt`, config in `config/workflow_config_lightgbm_Alpha158.yaml` (only `provider_uri` changed to the evidence data dir).

  Final run facts (all verbatim from `logs/runtime.txt`):
  - **Wall time:** START 12:13:00 → END 12:23:27 = **10m27s** total. Breakdown: Alpha158 data init **350.6s**, LightGBM training ~45s (early stop, best iteration 18), TopkDropout backtest 871 trading days in **39s** (~22 it/s).
  - **Signal metrics** (SigAnaRecord): `IC 0.0468`, `ICIR 0.3816`, `Rank IC 0.0490`, `Rank ICIR 0.4067`.
  - **Portfolio metrics** (PortAnaRecord, csi300 2017-01-01→2020-08-01, benchmark SH000300, 100M CNY, costs 0.05%/0.15%):
    - benchmark: annualized_return 0.1136, information_ratio 0.5987, max_drawdown -0.3705
    - excess return w/o cost: annualized_return 0.1260, information_ratio 1.4286, max_drawdown -0.0723
    - excess return with cost: annualized_return 0.0807, information_ratio 0.9145, max_drawdown -0.0861
  - These match the magnitude of qlib's published LightGBM Alpha158 reference numbers (their README lists excess return w/o cost ≈ 0.12, IC ≈ 0.05) — sane, not suspicious.
  - Warnings during run (benign, documented in log): gym deprecation shim, `$close field data contains nan` (sample-data quality), index SH000300 has no factor file → adjusted-price orders for benchmark, "trade unit 100 not supported in adjusted_price mode", future-calendar warning in backtest infra.

## [Dependencies]

- **PASS** — `pip list`: **195 packages** (see `logs/piplist.txt`; count line at bottom).
- Heavy deps (versions actually installed, final state after mlflow<3): numpy 2.5.5, pandas 2.3.3, pyarrow 19.0.1 (downgraded from 23.0.1 by mlflow<3), lightgbm 4.7.0, mlflow 2.22.5, scikit-learn 1.9.1, matplotlib 3.11.2, cvxpy (with clarabel/osqp/qdldl/scs/highspy solvers), scipy. **torch NOT installed** (rl extras only; not needed for this POC). jupyter + notebook are pulled in by default (fat dependency footprint).
- Final package count after mlflow downgrade: **196** (`logs/piplist.txt`, final block; 195 before).
- qlib version string: **0.9.8** (`logs/install.txt`).

## [Windows/Py3.13 compat]

- **PASS** — end-to-end on Windows 11 + Python 3.13.15: venv creation, editable install with native build steps (pyqlib Cython machinery + gym sdist wheel build), import, qlib.init against the bin-format sample data, qrun workflow (see Runtime).
- **Gotcha (documented, not a blocker):** running `python -c "import qlib"` with **cwd inside `third_party/`** makes the clone root dir `third_party/qlib` shadow the installed package as an implicit namespace package (`qlib.__file__ == None`, no attributes) — two initial `AttributeError: module 'qlib' has no attribute 'init'` errors in `logs/install.txt` are this, and were resolved by running from another cwd. Any runner script must not execute from inside `third_party/`.
- Known incompat found: mlflow 3.x breaks qlib's recorder (see Runtime); requires `mlflow<3`.

## [Assessment]

Verdict: **viable for the research sandbox; the workflow engine runs on Windows + Py3.13 after pinning mlflow<3. Main real-world risks are data, not code.**

What works (verified): clean editable install on Py3.13; native bin-format data loading over 4.3k instruments; Alpha158 feature pipeline; LightGBM training; IC/backtest reporting via qrun (see runtime log).

1. **PIT / survivorship is partial by design.** qlib has a real PIT database format (docs/advanced/PIT.rst: statement publication date + period + `_next` chaining; `qlib_data_pit` zip) and csi300 membership is point-in-time in the sample data — both genuinely good. But the shipped sample dataset has **no fundamentals**, and the price panel itself shows a snapshot artifact (87 instruments all end 2020-09-25) rather than true delisting history, so backtests on this data overstate liquidity/fitness for anything touching delisted names. PIT data for CN must be crawled/dumped yourself (scripts/data_collector/pit) — that cost is not in this evaluation.
2. **Data staleness.** The current public dataset ends 2022-12-30 (asset published 2024-05). For anything live you must run qlib's Yahoo collector yourself, or pipe your own data into qlib's bin format — the dump/collector scripts are CN-Yahoo-centric and were not evaluated here.
3. **mlflow recorder fragility.** qlib's experiment tracker breaks on mlflow 3.x (observed) — it is version-coupled to mlflow's fluent API semantics. If you need experiment tracking, treat mlflow as a pinned component (`mlflow<3`, currently 2.22.5). File-store backend is deprecated upstream, so this coupling will need maintenance attention.
4. **Windows quirks.** Works, but (a) never run scripts with cwd inside the package/clone tree (namespace shadowing), (b) qlib warns about multiprocessing-on-Windows in nested loops for backtest, (c) sample config's `num_threads: 20` assumes a big box.
5. **Maintenance risk.** Pinned clone is active upstream (2026-10 commit touching security). Heavy default deps (jupyter, mlflow, cvxpy) inflate install surface; gym 0.26.2 (deprecated pkg, built from source) is only needed for RL extras yet is a hard dep of the base package.
6. **Python 3.13:** fully worked in this evaluation, including source builds. Upstream classifiers only claim through 3.12, so 3.13 is not officially blessed — treat CI for Py3.13 as your own responsibility.
