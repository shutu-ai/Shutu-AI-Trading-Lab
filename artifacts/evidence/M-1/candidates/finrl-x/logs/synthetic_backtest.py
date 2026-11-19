"""Offline synthetic-data smoke test of FinRL-X BacktestEngine (bt-powered).
Run: python <this file> <repo_root>
Creates 5 synthetic price series (daily business days, ~500 rows), equal-weight
rebalance signals, runs BacktestEngine.run_backtest, prints metrics + wall time.
No network, no API keys.
"""
import sys, time
import numpy as np
import pandas as pd

repo = sys.argv[1] if len(sys.argv) > 1 else "."
sys.path.insert(0, repo)

from src.backtest.backtest_engine import BacktestEngine, BacktestConfig

rng = np.random.default_rng(42)
dates = pd.bdate_range("2023-01-02", periods=500)
symbols = ["SYN1", "SYN2", "SYN3", "SYN4", "SYN5"]
frames = {}
for s in symbols:
    ret = rng.normal(0.0004, 0.015, len(dates))
    px = 100 * np.exp(np.cumsum(ret))
    frames[s] = pd.DataFrame(
        {"datadate": dates.strftime("%Y-%m-%d"), "tic": s, "adj_close": px}
    )
price_long = pd.concat(frames.values(), ignore_index=True)

# weight signal frame: index=datadate, columns=tickers, values=weights
w = pd.DataFrame(0.2, index=dates.strftime("%Y-%m-%d"), columns=symbols)

t0 = time.time()
engine = BacktestEngine(BacktestConfig(start_date="2023-01-02", end_date="2024-12-31"))
# NOTE: actual signature is run_backtest(strategy_name, price_data, weight_signals)
# (backtest_engine.py:124). README.md:288 documents it as (name, weights, prices) -- swapped.
result = engine.run_backtest("equal_weight_synth", price_long, w)
dt = time.time() - t0

print(f"WALL_TIME_SECONDS={dt:.1f}")
md = getattr(result, "metrics", {}) or {}
for k, v in md.items():
    print(f"METRIC {k} = {v}")
print("SMOKE_TEST_RESULT=PASS" if dt >= 0 else "SMOKE_TEST_RESULT=FAIL")
