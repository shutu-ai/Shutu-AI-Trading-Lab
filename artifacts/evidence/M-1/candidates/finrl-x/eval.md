# FinRL-X (FinRL-Trading) — M-1 POC Evaluation

- Evaluated at commit: `4409abe925c904e570be78ebfb5e77ac3491dff8` (origin/master, clone at `third_party/FinRL-Trading`)
- Date: 2026-11-19. Evaluator venv: `third_party/.venv-finrl` (Python 3.13.15, pip 26.2.1)
- Proxy for all network traffic: `http://192.168.1.2:8080`
- Note: the clone was delivered shallow (`.git/shallow`); it was deepened/unshallowed via
  `git fetch --deepen=50` then `git fetch --unshallow` (proxy) to obtain real commit history.
  Logs: `logs/repolog_shallow.txt`, `logs/git_deepen.txt`, `logs/repolog.txt`, `logs/commit_cadence_by_month.txt`.

---

## [Repo state]

| Item | Status | Evidence |
|---|---|---|
| Pinned HEAD matches | **PASS** | `git rev-parse HEAD` = 4409abe925c904e570be78ebfb5e77ac3491dff8 (`logs/repolog_shallow.txt`) |
| Real commit cadence | **PASS** (verified) | 322 commits total, 2020-05 .. 2026-09 (`logs/commit_cadence_by_month.txt`). Bursts: 2020-08/09/10 (117 commits), 2022-10, 2025-10/11, 2026-03/04 (63). Head commit 2026-09-18. Many head-era commits are "Add files via upload" by maintainer accounts (no PR review), e.g. 3b81650, 0cd14b3, 12b0909 (`logs/repolog.txt`). |
| README claims (Alpaca/live) | **PASS** (recorded) | `README.md:61` "Execution — Live/paper trading: Alpaca multi-account integration with pre-trade risk checks"; `README.md:291-294` Python API example calling `AlpacaManager.execute_portfolio_rebalance`; `README.md:107` "DRL Allocator — PPO/SAC continuous weight generation". Reality check in [Code inspection] below. |
| Tests | **FAIL** | No test files anywhere: `find -name "test_*.py"`, `conftest.py` → none; only incidental `backtest`/`latest` substring matches (`logs/tree.txt`, 84 tracked files total). |
| CI config | **FAIL** | No `.github/` directory (`ls .github` → No such file or directory). No CI of any kind. |
| requirements.txt | **PASS** (recorded) | Modern floor-pins only (`>=`), no version locks: numpy>=1.24, pandas>=2.0, alpaca-py>=0.13, pydantic>=2.5, bt>=1.2, torch>=2.0, streamlit, openai, finnhub>=2.4.19, `pathlib>=1.0.1` (questionable — 2013-era PyPI `pathlib` package shadowing stdlib name; `requirements.txt:41`). |
| License | **PASS** | `LICENSE` = Apache License, Version 2.0 (11711 bytes); README badge and `LICENSE` head agree. |
| Hygiene findings | — (info) | Committed `__pycache__/*.cpython-311.pyc` files tracked in git (3 files); committed binary `data/finrl_trading.7z`; `src/trading/alpaca_manager.py` is not valid UTF-8 (ISO-8859/GBK mojibake comments at lines 440/460, `logs/bug_evidence.txt`); README references `examples/FinRL_Full_Workflow.ipynb` which does not exist (actual: `FinRL_Full_selection.ipynb`, `FinRL_universe_portfolio.ipynb`). |

---

## [Install]

### Attempt 1 — `pip install -r requirements.txt` as shipped: **FAIL (Python 3.13)**

- Environment: Python 3.13.15 venv `third_party/.venv-finrl`, pip 26.2.1, proxy 192.168.1.2:8080.
- Verbatim terminal error (full transcript `logs/install.txt`):

```
ERROR: Ignored the following versions that require a different python version: 0.55.2 Requires-Python <3.5; ... 1.26.0 Requires-Python >=3.9,<3.13; 1.26.1 Requires-Python >=3.9,<3.13; ...
ERROR: Could not find a version that satisfies the requirement finnhub>=2.4.19 (from versions: none)
ERROR: No matching distribution found for finnhub>=2.4.19
PIP_EXIT=1
```

- The blocker is `finnhub>=2.4.19` (`requirements.txt:44`): pip resolves **no distribution at all** for
  finnhub on Python 3.13 (`pip index versions finnhub` → `ERROR: No matching distribution found for finnhub`,
  recorded in `logs/install_finnhub_probe.txt`). finnhub is **not imported anywhere in `src/`**
  (`grep -rn finnhub --include="*.py" src/` → no matches), so it is a dead dependency that breaks
  the entire install on 3.13.
- Contrast with the brief's expectation: this repo does **not** pin old gym/stable-baselines3/tensorflow
  in requirements.txt. The old-RL stack appears instead as *undeclared* imports (see next section).

### Attempt 2 — documented deviation, recovery install: see `logs/install_recovery.txt`

- **DEVIATION RECORDED**: finnhub removed via a filtered copy at
  `logs/requirements-filtered-nofinnhub.txt` (diff vs shipped requirements = exactly the one line).
  Command: `pip install -r artifacts/evidence/M-1/candidates/finrl-x/logs/requirements-filtered-nofinnhub.txt`.
  No library code was modified; the clone is untouched.
- Result and version resolution: see `logs/install_recovery.txt` (PIP_EXIT recorded at end of file).

---

## [Runtime]

See `logs/runtime_import_smoke.txt`, `logs/runtime_backtest_smoke.txt`, `logs/runtime_rotation.txt`.
(Filled after execution; CLI-level findings summarized here.)

---

## [Code inspection: order semantics]

All citations are to the pinned commit. The execution stack is three files plus callers:
`src/trading/alpaca_manager.py` (941 lines), `src/trading/trade_executor.py` (529),
`src/strategies/execution_engine.py` (427, backtest-only), `src/web/app.py` (dashboard),
`deploy.sh` (paper-mode one-shot runner).

### (a) Alpaca integration

- **Uses raw `requests` against the REST v2 API, NOT the alpaca-py SDK.** `alpaca_manager.py:19`
  `import requests`; `_api_request()` (`alpaca_manager.py:729-772`) builds
  `f"{account.base_url}{path}"` with manual `APCA-API-KEY-ID/SECRET` headers. Despite
  `requirements.txt:21` declaring `alpaca-py>=0.13.0`, `grep -rn "import alpaca|from alpaca" src/`
  finds **zero imports** — the SDK is installed but unused (`logs/grepfindings.txt`).
- Paper vs live: `AlpacaAccount.base_url` defaults to `https://paper-api.alpaca.markets`
  (`alpaca_manager.py:39`); `is_paper` = `"paper" in base_url` (`:41-44`). Live trading is possible
  by switching base_url; `deploy.sh:426-431` refuses non-paper accounts **in deploy.sh only** —
  the library itself has no live-trading guard.
- Order placement: `place_order()` (`alpaca_manager.py:197-255`) POSTs `/v2/orders` with
  `{symbol, qty, side, type, time_in_force, extended_hours, [limit_price], [stop_price]}`.
  Order types supported in the dataclass: market/limit/stop/stop_limit (`:53`).
- **The rebalance path places market orders only**: sells built at `:521-526`
  (`order_type='market'`), buys at `:600-605` (`order_type='market'`). No bracket orders, no
  attached take-profit/stop-loss, nowhere in the codebase (`grep bracket` → no matches).
- Flow used by the flagship paper path (`deploy.sh:454-459`): compute target weights →
  `AlpacaManager.execute_portfolio_rebalance()` → cancel all open orders (`:422`) → Phase 1 sells
  (`:470-537`) → refresh positions (`:541-547`) → Phase 2 buys scaled to 98% of buying power
  (`:580-587`) → fire-and-forget. **The rebalance path never calls `wait_for_order_fill()`** —
  `place_orders_batch` sleeps 0.1 s between submissions (`:277`) and returns immediately.
  `wait_for_order_fill` (2 s polling loop, `:365-389`) is called only from the *other* path,
  `trade_executor._execute_orders` (`trade_executor.py:330-336`), which deploy.sh does not use.
- The positions refresh after sells (`:541`) is racy: market sell orders are typically not yet
  filled, so Phase-2 buying power/weights are computed from stale state (mitigated only by the
  buying-power scale-down).

### (b) Order state tracking / idempotency / recovery — **ABSENT**

Keyword sweep over the whole repo (`logs/grepfindings.txt`):

| Capability | Finding |
|---|---|
| `client_order_id` | **0 occurrences** repo-wide (.py/.sh/.ipynb). Order payload (`alpaca_manager.py:226-238`) contains no idempotency key → a retried/timeout-duplicated POST creates a duplicate order; crash between POST and response loses the order id. |
| Reconciliation | **0 occurrences** of `reconcil*`. No code reads open orders/positions at startup to resume state. `get_orders()` is called only by `performance_analyzer.py:33` (reporting). |
| Retry | **None.** `_api_request` raises `RuntimeError` on any `RequestException` (`:771-772`); callers convert to a `"failed"` placeholder response (`:282-291`) or log-and-continue. No backoff, no resubmit. |
| Partial fills | **Not handled.** `OrderResponse.filled_quantity` is populated (`:249`, `:354`) but no logic acts on partial fills; `wait_for_order_fill` treats only `{filled, canceled, rejected, expired}` as terminal (`:379`) and returns the last snapshot; a partial-then-canceled order is not topped up or re-planned. |
| Crash recovery / resubmission journal | **None.** `_log_execution`/`_log_rebalance` write JSON logs **after** execution (`trade_executor.py:406-447`); nothing reads them back; no WAL, no outbox, no pending-order queue. `grep recover/resume/restart/orphan` in trading code → no hits. |
| Idempotent state machine | None. State lives in Alpaca only; the app is stateless between runs. |

### Defects found while reading (verbatim in `logs/bug_evidence.txt`)

1. **Undefined-variable bug in the sell leg**: `alpaca_manager.py:493-497` —
   `except Exception:` (no `as e`) then `print(f"... {e}")` → `NameError` at runtime if
   `_get_latest_price` throws, aborting the rebalance mid-way (after cancel-all-orders).
2. **Silent `$100 price fallback** in three places: `alpaca_manager.py:506-507`, `:574-575`,
   `trade_executor.py:404` (`return 100.0`) — share quantities get computed from a fabricated
   price instead of failing the order.
3. **Wrong host for quote endpoint**: `trade_executor.py:399` GETs
   `/v2/stocks/{ticker}/quotes` against the **trading** base_url (`paper-api.alpaca.markets`);
   market data lives on `data.alpaca.markets` (the rebalance path does this correctly at
   `alpaca_manager.py:784`). So the `execute_strategy` path always falls into the $100 fallback.
4. **Config default mismatch**: `settings.py:35` defaults `APCA_BASE_URL` to
   `https://paper-api.alpaca.markets/v2` (with `/v2`), while `AlpacaManager` appends `/v2/...`
   to base_url → with the unset-env default, URLs would become `.../v2/v2/account`. Works only
   if the user sets APCA_BASE_URL explicitly (as `.env.example:27` shows).
5. **Broken CLI entry points**: `src/main.py:18` imports `utils.logging_utils` — module does not
   exist (`src/utils/` contains only `__init__.py`), so **every** `src/main.py` command dies at
   import; `src/main.py:82` imports `trading.trade_executor.main` which does not exist either
   (verified: no `def main` in trade_executor.py). `setup.py` console_scripts therefore point at
   dead code.
6. **README's "DRL Allocator (PPO/SAC)" is not importable as shipped**: `rl_model.py:25` and
   `fundamental_portfolio_drl.py:20-24` import the **old `finrl` package** (`finrl.agents...`),
   plus `pypfopt` (`fundamental_portfolio_drl.py:7`) — none of which are declared in
   requirements.txt (no finrl / stable-baselines3 / gymnasium / pypfopt entries; verified
   `logs/bug_evidence.txt`). These modules fail with ModuleNotFoundError under the shipped deps.

### (c) Event-driven vs periodic-rebalance

- **Periodic-rebalance only.** There is no event loop, no websocket/stream, no scheduling in the
  repo (`logs/grepfindings.txt`: only trading-calendar "schedule" false positives and a log-writer
  thread in `strategylogger.py`). Execution is: external cron (user-managed) → run
  `deploy.sh --mode paper` or `trade_executor` → one-shot `execute_portfolio_rebalance` → exit.
- "Daily monitoring" (Fast Risk-Off, stop-loss) exists **only inside the backtest simulator**
  (`run_adaptive_rotation_strategy.py:134-165`); the live path has no intraday monitoring at all.
- `src/strategies/execution_engine.py` (`ExecutionManager`) is a weight-matrix generator for
  backtests (D/W/M rebalance frequency, cooldowns, constraints) — simulation only, not an OMS.
- Dashboard (`web/app.py:415-475`) adds a manual market/limit order form and a "sample strategy"
  button — same fire-and-forget `place_order`, no fill confirmation loop.

---

## [Code inspection: OMS capabilities]

Verdict table for ADR-001 (each row cites code):

| OMS capability | Present? | Evidence |
|---|---|---|
| Weight→order translation | Partial (market orders, sell-then-buy, buying-power scaling) | `alpaca_manager.py:470-616` |
| Pre-trade risk checks | Present but **bypassed on the flagship path**: `ExecutionConfig.max_order_value/max_portfolio_turnover` enforced only in `TradeExecutor._apply_risk_checks` (`trade_executor.py:280-316`); deploy.sh paper mode calls `AlpacaManager.execute_portfolio_rebalance` directly (`deploy.sh:454`), skipping them | `deploy.sh:416-459` |
| Fill tracking | Read-only snapshots; polling helper exists but unused in rebalance path | `alpaca_manager.py:365-389`, `:249` |
| Idempotency (client_order_id) | **ABSENT** | `logs/grepfindings.txt` (0 hits) |
| Crash recovery / order reconciliation | **ABSENT** | no reconcile/recovery code; JSON logs are write-only |
| Partial-fill handling | **ABSENT** | fields populated, never acted on |
| Duplicate-order protection | **ABSENT** (cancel_all + recompute each run is the only mitigation; relies on next run) | `alpaca_manager.py:418-424` |
| Event-driven execution / market-data stream | **ABSENT** (periodic one-shot scripts only) | `logs/grepfindings.txt` |
| Order journal with replay | **ABSENT** (post-hoc JSON logs only) | `trade_executor.py:406-447` |
| Paper-vs-live guard | Partial: only in deploy.sh, not in library | `deploy.sh:426-431` |

---

## [Assessment]

(Filled after install/runtime evidence; summary below.)

- Maintenance state: see [Repo state]. Active in 2026 but bursty, much of it direct uploads;
  zero tests, zero CI.
- Dependency health on 3.13: install fails as shipped (finnhub unresolvable); core data/execution
  deps are modern floor-pins and do resolve once finnhub is removed (see `logs/install_recovery.txt`).
- Alpaca execution maturity vs a thin official SDK: it is a ~940-line hand-rolled REST wrapper
  (requests) duplicating what `alpaca-py` provides, minus retries, minus idempotency, minus types,
  with a live/paper guard only at the script level and at least one wrong-endpoint bug and one
  NameError bug on plausible failure paths.
- OMS/event-driven acceptance gate: **does not plausibly pass** — no client_order_id, no
  reconciliation, no partial-fill handling, no crash recovery, no event loop (details in
  [Code inspection: OMS capabilities]).
- License: Apache-2.0 — no obstacle.
