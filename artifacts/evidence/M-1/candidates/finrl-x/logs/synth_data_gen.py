"""Generate synthetic {SYMBOL}_daily.csv files for the adaptive_rotation runner.
Run: python <this file> <out_dir> [symbol file]
Format required by src/strategies/adaptive_rotation/data_preprocessor.py:
columns date,open,high,low,close,volume.
Deterministic (seed 42). ~2200 business days from 2017-01-03.
"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd

out_dir = Path(sys.argv[1])
symbols_file = sys.argv[2] if len(sys.argv) > 2 else None

if symbols_file:
    symbols = [s.strip() for s in Path(symbols_file).read_text().splitlines() if s.strip()]
else:
    symbols = ["AAPL", "MSFT", "QQQ", "SPY", "^GSPC", "^VIX"]

out_dir.mkdir(parents=True, exist_ok=True)
rng = np.random.default_rng(42)
dates = pd.bdate_range("2017-01-03", periods=2200)

for s in symbols:
    sym = s.replace("^", "^")  # keep as-is; file name uses raw symbol
    ret = rng.normal(0.0003, 0.012, len(dates))
    close = 100 * np.exp(np.cumsum(ret))
    open_ = close * (1 + rng.normal(0, 0.002, len(dates)))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.003, len(dates))))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.003, len(dates))))
    vol = rng.integers(1_000_000, 5_000_000, len(dates)).astype(float)
    df = pd.DataFrame(
        {
            "date": dates.strftime("%Y-%m-%d"),
            "open": open_.round(4),
            "high": high.round(4),
            "low": low.round(4),
            "close": close.round(4),
            "volume": vol,
        }
    )
    df.to_csv(out_dir / f"{sym}_daily.csv", index=False)
    print(f"wrote {out_dir / (sym + '_daily.csv')} rows={len(df)}")
print(f"TOTAL_SYMBOLS={len(symbols)}")
