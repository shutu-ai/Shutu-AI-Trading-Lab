"""Import smoke test for FinRL-X (FinRL-Trading) trading stack on Python 3.13.
Run from repo root with the eval venv python:
  python <this file> <repo_root>
Prints one line per module: OK / FAIL(with exception text). Exits 0 always so the
transcript is the evidence.
"""
import sys, time, traceback

repo = sys.argv[1] if len(sys.argv) > 1 else "."
sys.path.insert(0, repo)
sys.path.insert(0, repo + "/src")

mods = [
    ("numpy", "numpy"),
    ("pandas", "pandas"),
    ("pydantic_settings", "pydantic_settings"),
    ("alpaca-py (installed, is it used?)", "alpaca"),
    ("pandas_market_calendars", "pandas_market_calendars"),
    ("bt", "bt"),
    ("yfinance", "yfinance"),
    ("src.config.settings", "src.config.settings"),
    ("src.data.data_fetcher", "src.data.data_fetcher"),
    ("src.backtest.backtest_engine", "src.backtest.backtest_engine"),
    ("src.trading.alpaca_manager", "src.trading.alpaca_manager"),
    ("src.trading.trade_executor", "src.trading.trade_executor"),
    ("src.trading.performance_analyzer", "src.trading.performance_analyzer"),
    ("src.strategies.adaptive_rotation", "src.strategies.adaptive_rotation"),
    ("src.strategies.run_adaptive_rotation_strategy", "src.strategies.run_adaptive_rotation_strategy"),
    ("src.main (CLI entry)", "src.main"),
]

print(f"python={sys.version}")
for label, name in mods:
    t0 = time.time()
    try:
        __import__(name)
        print(f"OK   {label}  ({time.time()-t0:.1f}s)")
    except Exception as e:
        print(f"FAIL {label}: {type(e).__name__}: {e}")
