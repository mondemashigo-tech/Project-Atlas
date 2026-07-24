"""Market-regime classification and per-regime performance breakdown.

A strategy that only works in one regime (e.g. strong trend, high volatility) is
fragile (Volume 3 §12 regime testing). This module labels each bar by trend
direction and volatility, then buckets a strategy's realised trades by the regime
at entry so we can see *where* an edge lives — or whether it's a one-regime
artifact.
"""
from __future__ import annotations

from typing import Dict, List

import pandas as pd

from .indicators import ema, atr
from .metrics import compute


def classify(df: pd.DataFrame, ema_fast: int = 50, ema_slow: int = 200,
             atr_period: int = 14, vol_window: int = 500) -> pd.Series:
    """Return a per-bar regime label like 'trend_up/high', 'range/low'.
    Uses only past/current data (EMAs + ATR), so it is look-ahead safe when read
    at the same bar the strategy acted on."""
    close = df["close"]
    ef, es = ema(close, ema_fast), ema(close, ema_slow)
    a = atr(df, atr_period)
    vol_med = a.rolling(vol_window, min_periods=max(20, atr_period)).median()

    trend = pd.Series("range", index=df.index)
    trend[(ef > es) & (close > es)] = "trend_up"
    trend[(ef < es) & (close < es)] = "trend_down"
    vol = pd.Series("low", index=df.index)
    vol[a > vol_med] = "high"
    return trend.str.cat(vol, sep="/")


def breakdown(trades: List, df: pd.DataFrame) -> Dict[str, dict]:
    """Bucket a symbol's trades by the regime at entry and compute metrics per
    bucket. `trades` are backtester Trade objects (entry_time is an ISO string)."""
    if not trades:
        return {}
    reg = classify(df)
    buckets: Dict[str, list] = {}
    for t in trades:
        ts = pd.Timestamp(t.entry_time)
        # regime at or before entry (no look-ahead)
        pos = reg.index.searchsorted(ts, side="right") - 1
        label = reg.iloc[pos] if pos >= 0 else "unknown"
        buckets.setdefault(label, []).append(t)
    return {label: compute(ts) for label, ts in sorted(buckets.items())}


def render(bd: Dict[str, dict]) -> str:
    if not bd:
        return "REGIME BREAKDOWN\n  no trades\n"
    lines = ["REGIME BREAKDOWN (by regime at entry)"]
    for label, m in bd.items():
        if m.get("trades"):
            lines.append(f"  {label:16} T:{m['trades']:>4} WR:{m['win_rate']:>5}% "
                         f"PF:{m['profit_factor']} exp:{m['expectancy_r']}R "
                         f"tot:{m['total_r']}R")
    return "\n".join(lines) + "\n"
