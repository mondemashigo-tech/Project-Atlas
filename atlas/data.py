"""Data ingestion for Atlas.

The platform reads OHLC from CSV (portable, reproducible) rather than a live
terminal, so any backtest can be re-run by anyone with the dataset. An optional
MT5 exporter (run once on a machine with MetaTrader5) produces those CSVs.

CSV schema: columns time, open, high, low, close  (time = ISO8601 or epoch s),
one file per symbol+timeframe, named e.g. GBPUSD_M5.csv.
"""
from __future__ import annotations

import os
import pandas as pd

TF_PANDAS = {"M1": "1min", "M5": "5min", "M15": "15min", "M30": "30min",
             "H1": "1h", "H4": "4h", "D1": "1D"}


def load_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    if "time" not in df.columns:
        raise ValueError(f"{path}: expected a 'time' column")
    t = df["time"]
    if pd.api.types.is_numeric_dtype(t):
        df["time"] = pd.to_datetime(t, unit="s", utc=True)
    else:
        df["time"] = pd.to_datetime(t, utc=True)
    df = df.set_index("time").sort_index()
    for c in ("open", "high", "low", "close"):
        if c not in df.columns:
            raise ValueError(f"{path}: missing column '{c}'")
    return df[["open", "high", "low", "close"]].astype(float)


def load_symbol(datasets_dir: str, symbol: str, timeframe: str) -> pd.DataFrame:
    path = os.path.join(datasets_dir, f"{symbol.upper()}_{timeframe.upper()}.csv")
    return load_csv(path)


def resample(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """Resample a fine OHLC frame up to a higher timeframe."""
    rule = TF_PANDAS[timeframe.upper()]
    out = df.resample(rule, label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"})
    return out.dropna()


def export_from_mt5(symbol: str, timeframe: str, years: float, out_dir: str) -> str:
    """Run on a machine with MetaTrader5 to produce a dataset CSV. Returns path."""
    import datetime as dt
    import MetaTrader5 as mt5  # noqa: import guarded to keep the platform portable

    tf_map = {"M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15,
              "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4, "D1": mt5.TIMEFRAME_D1}
    if not mt5.initialize():
        raise RuntimeError(f"MT5 init failed: {mt5.last_error()}")
    end = dt.datetime.now()
    start = end - dt.timedelta(days=int(years * 365))
    rates = mt5.copy_rates_range(symbol, tf_map[timeframe.upper()], start, end)
    mt5.shutdown()
    if rates is None or len(rates) == 0:
        raise RuntimeError(f"No {symbol} {timeframe} history returned.")
    df = pd.DataFrame(rates)[["time", "open", "high", "low", "close"]]
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{symbol.upper()}_{timeframe.upper()}.csv")
    df.to_csv(path, index=False)
    return path
