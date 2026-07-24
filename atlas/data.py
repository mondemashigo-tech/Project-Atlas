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


_TF_MINUTES = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240, "D1": 1440}


def mt5_diagnostics(symbols) -> dict:
    """Report which account/terminal is connected, the real symbol names that
    match what was asked for, and how many M5 bars are actually available. Use
    this when export returns no history — it tells us whether the problem is a
    wrong symbol name or history that hasn't downloaded yet."""
    import MetaTrader5 as mt5  # noqa

    if not mt5.initialize():
        return {"ok": False, "error": f"MT5 init failed: {mt5.last_error()}"}
    try:
        ai = mt5.account_info()
        out = {"ok": True,
               "account": ({"login": ai.login, "server": ai.server,
                            "company": ai.company, "currency": ai.currency}
                           if ai else None),
               "symbols_total": mt5.symbols_total(),
               "requested": {}}
        allsyms = mt5.symbols_get() or []
        for s in symbols:
            key = s.upper()[:6]
            matches = sorted({x.name for x in allsyms if key in x.name.upper()})
            sel = mt5.symbol_select(s, True)
            bars = 0
            first = last = None
            if sel:
                r = mt5.copy_rates_from_pos(s, mt5.TIMEFRAME_M5, 0, 500000)
                if r is not None and len(r):
                    bars = len(r)
                    import datetime as dt
                    first = str(dt.datetime.utcfromtimestamp(int(r[0]["time"])))
                    last = str(dt.datetime.utcfromtimestamp(int(r[-1]["time"])))
            out["requested"][s] = {"exact_selected": bool(sel), "m5_bars": bars,
                                   "first": first, "last": last,
                                   "name_matches": matches[:25]}
        return out
    finally:
        mt5.shutdown()


def export_from_mt5(symbol: str, timeframe: str, years: float, out_dir: str) -> str:
    """Run on a machine with MetaTrader5 to produce a dataset CSV. Returns path.

    Mirrors the live bot's access pattern: select the symbol into Market Watch
    first (MT5 returns no history for an unselected symbol), then pull recent
    bars with copy_rates_from_pos, which is more reliable than a date range.

    NOTE on time: MT5 timestamps are the *broker server* clock stored as epoch
    seconds. If the server is not UTC, session filters are offset by the broker's
    UTC offset — calibrate `session` accordingly (see README).
    """
    import MetaTrader5 as mt5  # noqa: import guarded to keep the platform portable

    tf_map = {"M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15,
              "M30": mt5.TIMEFRAME_M30, "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4,
              "D1": mt5.TIMEFRAME_D1}
    tf = timeframe.upper()
    if tf not in tf_map:
        raise ValueError(f"Unknown timeframe {timeframe!r}. Known: {list(tf_map)}")
    if not mt5.initialize():
        raise RuntimeError(f"MT5 init failed: {mt5.last_error()}")
    import datetime as dt
    import time
    try:
        if not mt5.symbol_select(symbol, True):
            raise RuntimeError(
                f"Could not select '{symbol}' in Market Watch (last_error="
                f"{mt5.last_error()}). Check the exact symbol name in your terminal.")
        bars = int(years * 365 * 24 * 60 / _TF_MINUTES[tf]) + 100
        end = dt.datetime.now()
        start = end - dt.timedelta(days=int(years * 365) + 2)
        # A fresh terminal may need a few seconds to pull history from the server;
        # the first call kicks off the download and can return empty. Retry.
        rates = None
        for attempt in range(15):
            rates = mt5.copy_rates_range(symbol, tf_map[tf], start, end)
            if rates is not None and len(rates):
                break
            rates = mt5.copy_rates_from_pos(symbol, tf_map[tf], 0, bars)
            if rates is not None and len(rates):
                break
            time.sleep(2)
    finally:
        mt5.shutdown()
    if rates is None or len(rates) == 0:
        raise RuntimeError(f"No {symbol} {tf} history returned (broker may not "
                           f"serve this depth; try fewer years).")
    df = pd.DataFrame(rates)[["time", "open", "high", "low", "close"]]
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{symbol.upper()}_{tf}.csv")
    df.to_csv(path, index=False)
    return path
