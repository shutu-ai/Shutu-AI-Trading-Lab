# NautilusTrader evaluation — M-1 POC candidate

Evaluated 2026-11-19, Windows 11 Pro, Git Bash + PowerShell, proxy 192.168.1.2:8080.
Clone: `third_party/nautilus_trader` @ `8a4ac22fc08990a96c6e5750c76a3fa744f4d141` (shallow — history beyond 1 commit unavailable locally; release cadence taken from RELEASES.md in-tree).
Installed: PyPI `nautilus_trader` stable 1.231.0, then `--pre` 2.0.0rc9, into `third_party/.venv-nautilus` (Python 3.13.15).

Note on versions: the pinned clone is v2.0.0-in-development (Rust-native core, `python/pyproject.toml` version 2.0.0, RELEASES.md "2.0.0 Released on TBD"). PyPI latest stable is 1.231.0 (also Rust-native per its package summary); latest pre-release 2.0.0rc9 matches the clone's API. Both were installed and the documented example was run on 2.0.0rc9 (matches clone docs, which say `--pre` is required while 2.x ships as rc).

---

## [Install]

- PASS — `py -3.13 -m venv third_party/.venv-nautilus` created (Python 3.13.15).
- PASS — `pip install nautilus_trader` exit 0 → **nautilus_trader 1.231.0**. Log: logs/install.txt (`Successfully installed click-8.5.1 colorama-0.4.6 fsspec-2026.2.0 msgspec-0.22.0 nautilus_trader-1.231.0 numpy-2.5.5 pandas-3.1.1 portion-2.6.3 pyarrow-26.0.1 python-dateutil-4.0.0 pytz-2026.6 sortedcontainers-2.4.0 tqdm-4.70.1 tzdata-2026.6`).
- PASS — `pip install --pre --upgrade nautilus_trader` exit 0 → **2.0.0rc9**. Log: logs/install_pre.txt.
- PASS — `pip list`: 14 packages (stable install). Log: logs/piplist.txt.
- Heavy deps: numpy 2.5.5, pandas 3.1.1, pyarrow 26.0.1 (the heavy ones); click/fsspec/msgspec small. **The engine binary is a prebuilt compiled wheel** — no Cython, no compiler, no pyo3 runtime dependency at install time (pyo3/maturin are build-time binding tech, only relevant if building from source: `python/pyproject.toml` build-system = `maturin==1.16.0`, module `nautilus_trader._libnautilus`). 2.0.0rc9 declares **zero required runtime deps** (`Requires-Dist` only the optional `visualization` extra: pandas/plotly/kaleido/simplejson) — verified via importlib.metadata on the installed rc9.

## [Version / Py3.13 support]

- PASS — 1.231.0 metadata `Requires-Python: >=3.12,<3.15`, classifiers list 3.12/3.13/3.14 → 3.13 officially supported.
- PASS — 2.0.0rc9 metadata `Requires-Python: >=3.13, <3.16` → 3.13 officially supported.
- PASS — clone `python/pyproject.toml`: `requires-python = ">=3.13,<3.16"`, classifiers 3.13/3.14/3.15.
- PASS — both wheels install and run on Windows 11 x86_64 + Python 3.13.15 (backtest run below). README platform table: Windows x86_64 — Rust 1.100.0, Python 3.13-3.15.

## [License]

- PASS (verified by reading files) — clone `LICENSE` is the GNU Lesser General Public License v3 (header read). Clone `python/pyproject.toml`: `license = "LGPL-3.0-only"`. Installed 1.231.0 metadata License: `LGPL-3.0-or-later`. (Minor discrepancy between clone and installed metadata; both LGPL-3.0 family.)

## [Minimal backtest run]

- PASS — example: `docs/getting_started/backtest_low_level.py` (the documented low-level `BacktestEngine` walkthrough: EMA-cross strategy + TWAP exec algorithm on simulated Binance Spot, ETHUSDT trade ticks aggregated into 250-TICK-INTERNAL bars). Verbatim copy: `backtest_low_level_copy.py`. Runnable variant: `backtest_run.py` — ONLY delta is wrapping the three report calls in `print()` (docs example targets Jupyter where the last expression is displayed); imports/strategy/config are verbatim.
- PASS — offline data: set `TEST_DATA_ROOT_PATH` to the clone root; `TestDataProvider` then reads the clone's shipped `test_data/binance/ethusdt-trades.csv` (`python/nautilus_trader/testkit/providers.py:75-77,111-124`), no network.
- PASS — run exit 0 on 2.0.0rc9 + Python 3.13.15. Log: logs/backtest.txt. Results: 30 parent orders (`O-20200814-102234-001-000-1` … `-30`), each sliced by the TWAP exec algorithm into `-E1/-E2/-E3` child orders; 75 fills; 15 positions; account report shows USDT/ETH balance evolution 1,000,000 USDT start.
- Wall time: `engine.run()` **0.144 s** for the full tick replay (~4.5 h of market data); whole script incl. interpreter+imports ≈ 4 s (log timestamps 09:59:19 → 09:59:23 UTC).

## [Order semantics verification]

All citations read directly from clone source (Rust crates are the real implementation in this 2.x architecture; the Python package is a pyo3 binding layer). Transcript with verbatim code: logs/greps.txt.

(a) **client_order_id generation & idempotency — PASS (code-verified)**
- Format `O-YYYYMMDD-HHMMSS-{trader_tag}-{strategy_tag}-{count}`, monotonic per-strategy counter, optional UUID4 mode: `crates/common/src/generators/client_order_id.rs:37-64` (format writer), `:191-209` (`generate()`); generator wired per-strategy via `OrderFactory` (`crates/common/src/factories/order.rs:43-77,115-120`). Matches the IDs observed in our run (`O-20200814-102234-001-000-1`).
- Exec-algorithm child ids spawned as `{primary}-E{n}`: `crates/trading/src/algorithm/core.rs:221` (observed `-E1..-E3` in run).
- Duplicate-submit guard: `crates/execution/src/engine/mod.rs:2321` `validate_submission` checks `cache.order(&client_order_id)`; already-dispatched ⇒ `SubmissionValidationResult::Dispatched` ⇒ "Skipping duplicate submit command for {client_order_id} already dispatched to an execution client" (`engine/mod.rs:2209-2214`).
- Duplicate-fill guard: `order.is_duplicate_fill` by `trade_id` (`crates/model/src/orders/mod.rs:413`) enforced in exec engine (`crates/execution/src/engine/mod.rs:4039-4047`, `OrderError::DuplicateFill`), plus position-level dedup (`engine/mod.rs:3553-3559`).
- Caveat: cross-restart idempotency holds only if the cache is persisted (see b) — the guard reads the cache, which defaults to in-memory.

(b) **order event journal persistence — PASS (code-verified), with an important nuance**
- Two backends implement `CacheDatabaseAdapter`: **Redis** (`crates/infrastructure/src/redis/cache.rs` — `update_order` :2202, order event log :1112, indexes :1326) and **PostgreSQL** (`crates/infrastructure/src/sql/cache.rs` — `update_order` :1682, `PostgresCacheConfig` :74-94, sqlx PgPool :58). **No SQLite backend exists in the 2.x Rust core** (grep `sqlite` over `crates/infrastructure/` = 0 hits). Whether the 1.x Python line offered SQLite: UNVERIFIED locally.
- New embedded append-only **event_store** ("authoritative log of state-affecting messages… stable restarts via tail-replay, deterministic incident replay, end-to-end audit"): `crates/event_store/src/lib.rs:16-23`.
- **Nuance — not default-on:** with no database configured, the cache uses in-memory `CacheMap` whose `update_order` is a no-op (`crates/trading/src/cache_database.rs:382-384`), and `event_store: Option<EventStoreConfig>` defaults to `None` (`crates/live/src/node/config.rs:825-827`; test `live_node_config_default_has_no_event_store` asserts none, :2397-2400). Crash-safe journaling must be explicitly configured (Redis/Postgres cache db and/or `LiveNodeBuilder::with_event_store`).

(c) **reconciliation on restart — PASS (code-verified)**
- Dedicated pure-function module: `crates/execution/src/reconciliation/mod.rs:19-43` — "bringing the engine's local order, fill, and position state into line with what the venue reports. Called at startup (mass status) and continuously at runtime", with documented invariants incl. deterministic synthetic trade_id/venue_order_id "so restart replays dedupe".
- Startup enabled by default: `crates/live/src/node/config.rs:434-436` — `#[builder(default = true)] pub reconciliation: bool`; plus knobs: startup delay 10s, lookback mins, instrument/client-order-id filters (:437-452). Engine-level config surface in `crates/live/src/execution/config.rs:30-60` (inflight checks+retries, submission recovery policy, open-order checks, missing-order generation).
- Behavior spec tests exist: `crates/live/tests/spec/main.rs:158-184` (startup_reconciliation feature). Operator docs: `docs/concepts/execution/reconciliation.md` (file exists).

(d) **order state machine — PASS (code-verified)**
- `OrderStatus` enum, 15 states: `crates/model/src/enums.rs:1478-1520` (Initialized→Denied/Emulated/Released/Submitted/Accepted/Rejected/Canceled/Expired/Triggered/PendingUpdate/PendingCancel/PartiallyFilled/Filled/Voided) with `is_open` / `is_closed` / `is_inflight` / `is_cancellable` helpers (:1523-1560+).
- Transitions enforced by event application: `Order::apply` → `Result<(), OrderError>` (`crates/model/src/orders/mod.rs:389-390`); concrete impl rejects invalid events (`AlreadyInitialized`, `DuplicateFill`, `InvalidOrderEvent`, replayed-expiry guard): `crates/model/src/orders/mod.rs:817-860`.

(e) **Alpaca adapter — FAIL at all versions evaluated (code-verified absence)**
- `grep -ril alpaca` over the entire clone (all file types, excl .git): **0 matches**. `python/nautilus_trader/adapters/` lists 21 venues (architect_ax, betfair, binance, blockchain, bybit, coinapi, coinbase, databento, deribit, derive, dydx, finfeed, hyperliquid, interactive_brokers, kalshi, kraken, lighter, okx, polymarket, sandbox, tardis) — no alpaca. `docs/integrations/` lists the same 21, no alpaca.
- Installed PyPI stable 1.231.0 wheel: `site-packages/nautilus_trader/adapters/` — no alpaca (18 dirs, incl. bitmex which 2.x dropped); installed 2.0.0rc9: 0 files containing the string "alpaca".
- Whether Alpaca support moved to a separate out-of-tree package: UNVERIFIED (needs network research; no credentials/keys were touched — adapter-construction-level test was impossible since there is no adapter module to construct).

## [Complexity assessment]

Scale (logs/complexity.txt, `git ls-files` in clone):
- 320,236 LOC Rust (226,272 excluding `crates/adapters/` and generated code) + 163,701 LOC Python/.pyi bindings = ~490k LOC total across 5,724 tracked files. Our minimal in-house OMS target is ~2-5k LOC Python — adopting NautilusTrader means owning/understanding a codebase ~100x that size (as a dependency, not maintained, but debugged when live money misbehaves).
- Structure: 28 Rust crates (core, common, model, data, execution, risk, portfolio, live, backtest, persistence, event_store, infrastructure, network, 21 adapter crates…). For live trading a team must internalize ~15-20 core concepts: Kernel/Node, MessageBus, Cache, DataEngine, RiskEngine, ExecutionEngine, Portfolio, OrderFactory, Strategy, Venue/Instrument/OmsType, exec algorithms, reconciliation, cache database, event store, persistence catalog. `docs/concepts/` alone holds 113 guides — deep but heavy learning surface.
- Windows + Py3.13: verified working (install + backtest PASS above); 2.x requires exactly >=3.13,<3.16 (3.13 is fine; 3.12 dropped — fine for us).
- Release cadence: RELEASES.md shows 12+ releases between Jun and Nov 2026 (~2-4/month; rc9 10 Nov, rc8 28 Oct, rc7 15 Oct, rc6 4 Oct, rc5 15 Sep). Clone HEAD sits mid-2.0.0 transition (2.0.0 "TBD") with an explicit Breaking Changes section per release — high API-churn risk right now; pin to a version and expect migration work.
- LGPL-3.0 implications: pip-installing and calling the unmodified library (dynamic linking in LGPL terms) carries no obligation to open our own strategy/lab code. If we patch their source, we must release the modified source under LGPL-3.0 (and keep notices). Compatible with a proprietary lab POC as long as we do not fork the engine source; bugfixes should go upstream as PRs instead of local forks.

Operational risk for a small team (3-5 bullets):
1. Alpaca adapter absent in every artifact we can install today → we would have to write and maintain our own Alpaca `LiveExecClient`/`LiveDataClient` adapter (compare: existing adapter crates are 10k-30k LOC each) — exactly the work M-1 option C was meant to avoid.
2. Crash-safe journaling is opt-in (Redis or Postgres cache DB, or event_store) — operational dependency we must deploy and monitor; the default in-memory cache loses order state on restart, and cross-restart submit-idempotency depends on that persistence being configured.
3. Rust-core debugging: live order-flow bugs may require reading Rust (320k LOC) and understanding the msgbus/event flow; Python-only team assumption does not hold.
4. 2.0.0 is at rc with monthly breaking changes; long-term support for the 1.x line unclear from local evidence (UNVERIFIED).
5. Positives: reconciliation-on-startup default-on, strict event/state machine, deterministic backtest==live architecture claim (backtest determinism verified by our run; live-parity UNVERIFIED without a venue), excellent docs and spec tests.

## [Assessment]

- PASS items: install (both lines), Py3.13 support (both lines), LGPL-3.0 license verified, offline minimal backtest on 2.0.0rc9 (0.144 s engine time), client_order_id scheme + submit/fill dedup, order event persistence backends (Redis/Postgres/event_store), startup reconciliation (default-on), OrderStatus state machine.
- FAIL item: Alpaca adapter — absent from the pinned clone, from PyPI stable 1.231.0, and from 2.0.0rc9. This defeats the primary reason M-1 option C listed NautilusTrader (Alpaca integration out of the box).
- UNVERIFIED: live venue behavior end-to-end (no credentials by policy), whether Alpaca moved to a separate package, SQLite cache backend on the 1.x Python line, exact git history/release timeline (shallow clone; RELEASES.md used instead).
- BUILD-vs-ADOPT read (feeds ADR-001): as a *backtest/strategy engine*, NautilusTrader is strong and cheap to adopt (pure wheel, no build, deterministic). As the *live trading base for an Alpaca small-capital system*, it currently costs more than a minimal in-house OMS: we would build an Alpaca adapter against a moving 2.0 rc API and operate a persistence backend, to inherit rigor (state machine, reconciliation, idempotent ids) that our design doc already specifies for the in-house OMS at ~2-5k LOC. Recommend: do not adopt for M-1 live trading; revisit if (a) Alpaca support reappears (out-of-tree package or upstream), or (b) M-2+ moves to venues NautilusTrader already supports (Binance/Bybit/IB et al.), where adoption economics flip.
- Constraint compatibility: design doc's "no two engines may hold write access to the same account" is satisfiable (NautilusTrader would be sole writer), and its default-on reconciliation + `client_order_id` dedup assume exclusive write access — consistent with our constraint.

## Evidence index

- logs/install.txt — stable 1.231.0 install transcript (exit 0)
- logs/install_pre.txt — 2.0.0rc9 pre-release upgrade transcript (exit 0)
- logs/piplist.txt — venv package list (14 packages at stable install)
- logs/backtest.txt — verbatim backtest run output (exit 0, wall times)
- logs/greps.txt — verbatim code citations for order semantics (a)-(e) + defaults
- logs/complexity.txt — LOC/crate/adapter/docs/release-cadence metrics
- backtest_low_level_copy.py — verbatim copy of docs/getting_started/backtest_low_level.py
- backtest_run.py — runnable variant (print-wrapped reports; otherwise verbatim)
