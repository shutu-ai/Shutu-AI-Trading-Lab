# alpaca-py — M-1 POC Evaluation

- Evaluated: 2026-11-19 (by main session; offline contract evaluation only — no network, no keys)
- Installed: **alpaca-py 0.45.0** from PyPI into main venv (Python 3.13.15); clone pinned at `third_party/alpaca-py` SHA `f8fd9555ec182ccc0f8f6b5b819779fe7b2fb6d3` (Apache-2.0, last commit 2026-11-16)
- Note: this file was added during M-1-REVIEW-REMEDIATION-001 to give alpaca-py the same eval.md structure as the other candidates; no new testing was performed — facts below come from the M-1 run recorded in `logs/offline_contract.txt`.

## [Install]

- **PASS** — `pip install alpaca-py` on Python 3.13.15, import OK. Version `0.45.0` via `importlib.metadata`. Log: `logs/offline_contract.txt` (env versions also in `../../env/main_venv_pip_freeze.txt`).

## [Version]

- **PASS** — 0.45.0 (PyPI), matching recent development state of pinned clone (HEAD 2026-11-16).

## [License]

- **PASS** — Apache-2.0 (LICENSE in clone; recorded in `docs/licenses/third-party.md`).

## [Runtime (offline contract)]

- **PASS** — all checks below ran offline with DUMMY keys; no network call was made:
  - Endpoint constants separate: `BaseURL.TRADING_PAPER = https://paper-api.alpaca.markets`, `TRADING_LIVE = https://api.alpaca.markets` (source read: `.venv/Lib/site-packages/alpaca/common/enums.py:23-24`).
  - `TradingClient(dummy, dummy, paper=True/False)` constructs offline; `_base_url` switches by the `paper` flag (constant inspection only; live-mode client never called).
  - Fractional `qty` ("0.5") and `notional` ("50.00") market orders both serialize; mutual exclusion enforced (`Both qty and notional can not be set` ValidationError).
  - OCO/bracket + `extended_hours` expressiveness present (model keys verified).
  - `GetOrdersRequest(status=OPEN)` query model verified (reconciliation query shape).
  - `client_order_id` accepted on order requests (idempotency key supported at SDK level).

## [Negative findings]

1. **FAIL (SDK validation gap)** — `MarketOrderRequest(qty="-1", ...)` is **ACCEPTED** by the pydantic model. Negative-quantity validation must live in our intent/risk layers (POC `OrderIntent.validate()` rejects it; test `test_negative_qty_rejected_at_intent_validation`).
2. **BLOCKED_ENV (Paper behavior)** — no Alpaca credentials exist in this environment; real order semantics (idempotency window, post-timeout query behavior, fill reporting) remain **BROKER_BEHAVIOR_UNVERIFIED** (global flag recorded in `docs/reviews/M-1-independent-review.md` §4).

## [Dependencies]

- **PASS** — pure-Python SDK; pulls pydantic v2 + httpx/rest stack; full list in `../../env/main_venv_pip_freeze.txt`.

## [Windows/Py3.13 compat]

- **PASS** — installed and ran on Windows 11 + Python 3.13.15 with no issues.

## [Assessment]

ADOPTED as the sole BrokerAdapter base (ADR-001 option B). SDK scope is correct (protocol semantics); validation is insufficient (negative qty) → our OMS must fully validate intents before persistence/send. Paper/Live endpoints are separate constants — the paper-only runtime guarantee must still be enforced by our own configuration/namespace checks (POC `test_05_env_isolation.py`).
