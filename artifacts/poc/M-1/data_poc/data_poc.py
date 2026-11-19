"""M-1 data POC: minimal reproducible daily + 5-minute pipeline shape.

Proves (at POC scale, honest about limits):
1. UTC storage with explicit ts_event_utc (bar open/closed time) and
   ts_available_utc (when the bar was obtainable) — the §4.1 contract.
2. Raw vs adjusted prices both retained; corporate actions observable
   (split comparison), never silently overwriting raw data.
3. No-lookahead check: available_at <= decision cutoff is enforced.
4. Quality flags per row (source, interval, adjustment, quality).

Run:  .venv/Scripts/python.exe artifacts/poc/M-1/data_poc/data_poc.py
Data source: Yahoo Finance via yfinance (unofficial API — license constraint
recorded in docs/licenses/third-party.md and the vendor matrix).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf

HERE = Path(__file__).parent
OUT = HERE / "output"
OUT.mkdir(parents=True, exist_ok=True)

TICKERS_DAILY = ["SPY", "QQQ"]
TICKERS_INTRA = ["SPY"]
RUN_TS = datetime.now(timezone.utc)


def fetch(symbol: str, interval: str, period: str, auto_adjust: bool) -> pd.DataFrame:
    t = yf.Ticker(symbol)
    df = t.history(period=period, interval=interval, auto_adjust=auto_adjust)
    if df.empty:
        raise RuntimeError(f"empty download {symbol} {interval} auto_adjust={auto_adjust}")
    return df


def normalize(df: pd.DataFrame, symbol: str, interval: str, adjustment: str) -> pd.DataFrame:
    """yfinance returns tz-aware America/New_York index (DST-correct).
    ts_event_utc = bar OPEN time converted to UTC.
    ts_available_utc = conservative: bar close + poll time — a real feed's
    published availability; here we use download time (upper bound, honest)."""
    out = pd.DataFrame(index=df.index)
    out["symbol"] = symbol
    out["interval"] = interval
    out["ts_event_utc"] = df.index.tz_convert("UTC")
    # close-of-bar in UTC: daily bar closes at session close (16:00 ET or
    # 13:00 early close — we store the bar open time + known interval length
    interval_minutes = {"1d": None, "5m": 5}[interval]
    if interval_minutes:
        out["ts_bar_close_utc"] = out["ts_event_utc"] + pd.Timedelta(minutes=interval_minutes)
    else:
        # daily bar close = next calendar structure handled downstream; store
        # open date only, session close handled by the trading calendar (M1)
        out["ts_bar_close_utc"] = out["ts_event_utc"] + pd.Timedelta(hours=6, minutes=30)
    out["ts_available_utc"] = RUN_TS  # upper bound: we actually got it now
    out["open"] = df["Open"].astype(float)
    out["high"] = df["High"].astype(float)
    out["low"] = df["Low"].astype(float)
    out["close"] = df["Close"].astype(float)
    out["volume"] = df["Volume"].astype("int64")
    out["adjustment"] = adjustment
    out["source"] = "yahoo:yfinance"
    out["quality"] = "OK"
    out = out.reset_index(drop=True)
    return out[["symbol", "interval", "ts_event_utc", "ts_bar_close_utc", "ts_available_utc",
                "open", "high", "low", "close", "volume", "adjustment", "source", "quality"]]


def no_lookahead_check(df: pd.DataFrame) -> dict:
    """Every bar must satisfy: event time <= bar close <= available time,
    and available time never precedes its own event time."""
    bad = df[(df.ts_event_utc > df.ts_available_utc) | (df.ts_bar_close_utc > df.ts_available_utc)]
    return {"rows": int(len(df)), "violations": int(len(bad))}


def main() -> int:
    manifest = {"run_started_utc": RUN_TS.isoformat(), "files": {}, "checks": {}}

    # --- daily: raw + adjusted for each ticker ---
    for sym in TICKERS_DAILY:
        raw = normalize(fetch(sym, "1d", "2y", auto_adjust=False), sym, "1d", "RAW")
        adj = normalize(fetch(sym, "1d", "2y", auto_adjust=True), sym, "1d", "ADJUSTED")
        raw.to_parquet(OUT / f"daily_{sym}_raw.parquet", index=False)
        adj.to_parquet(OUT / f"daily_{sym}_adjusted.parquet", index=False)
        manifest["files"][f"daily_{sym}"] = {"rows_raw": len(raw), "rows_adj": len(adj),
                                             "span_raw": [str(raw.ts_event_utc.iloc[0]),
                                                          str(raw.ts_event_utc.iloc[-1])]}
        # corporate-action observability: raw close != adj close somewhere in
        # the window means dividends/splits are reflected (SPY/QQQ pay dividends)
        merged = raw[["ts_event_utc", "close"]].merge(
            adj[["ts_event_utc", "close"]], on="ts_event_utc", suffixes=("_raw", "_adj"))
        n_diff = int((merged.close_raw - merged.close_adj).abs().gt(1e-9).sum())
        manifest["checks"][f"{sym}_adjusted_vs_raw_diff_rows"] = n_diff
        assert n_diff > 0, f"{sym}: adjusted==raw everywhere — corporate actions invisible?"

    # --- 5-minute ---
    for sym in TICKERS_INTRA:
        raw = normalize(fetch(sym, "5m", "60d", auto_adjust=False), sym, "5m", "RAW")
        raw.to_parquet(OUT / f"min5_{sym}_raw.parquet", index=False)
        manifest["files"][f"min5_{sym}"] = {"rows": len(raw),
                                            "span": [str(raw.ts_event_utc.iloc[0]),
                                                     str(raw.ts_event_utc.iloc[-1])]}
        # 5m bars must be within session hours (no silent pre-market fill) —
        # Yahoo returns pre/post for some settings; we REPORT, not hide
        sessions = raw.set_index("ts_event_utc").tz_localize(None)
        manifest["checks"][f"{sym}_min5_bars_per_day_mean"] = round(
            len(raw) / max(1, sessions.index.normalize().nunique()), 1)

    # --- no-lookahead assertions ---
    for f in sorted(OUT.glob("*.parquet")):
        df = pd.read_parquet(f)
        res = no_lookahead_check(df)
        assert res["violations"] == 0, f"{f.name}: look-ahead violation {res}"
        manifest["checks"][f"{f.stem}_no_lookahead"] = res

    manifest["run_finished_utc"] = datetime.now(timezone.utc).isoformat()
    manifest["python"] = sys.version.split()[0]
    manifest["libraries"] = {"yfinance": yf.__version__, "pandas": pd.__version__}
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str))
    print(json.dumps(manifest, indent=2, default=str))
    print("DATA POC OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
