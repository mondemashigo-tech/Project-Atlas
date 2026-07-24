"""Donchian channel breakout template.

Momentum, not pullback: enter when price closes beyond the highest high / lowest
low of the previous N bars (the channel), betting the move continues. Stop =
atr_mult * ATR beyond entry; target = target_r * R. Optional session/weekday
window and optional bias-trend alignment (only break in the higher-timeframe
trend direction).

Breakout is the third distinct premise alongside trend-continuation (pullback)
and mean-reversion (fade) — together they probe whether the market is trending,
ranging, or expanding.
"""
from __future__ import annotations

from typing import Optional
import pandas as pd

from ..indicators import atr, ema
from ..data import resample
from .base import Strategy, Signal
from .common import session_weekday_mask


@Strategy.register("breakout")
class Breakout(Strategy):
    name = "breakout"

    def prepare(self, entry_df: pd.DataFrame, symbol: str = None,
                context: dict = None) -> None:
        c = self.config
        self.df = entry_df
        ch = c["breakout"].get("channel", 20)
        # Prior-bar channel: shift(1) so bar i breaks the range formed BEFORE it.
        self.hi = entry_df["high"].rolling(ch).max().shift(1)
        self.lo = entry_df["low"].rolling(ch).min().shift(1)
        self.atr = atr(entry_df, c["risk"]["stop"].get("atr_period", 14))
        self.tradeable = session_weekday_mask(entry_df, c)

        # Optional higher-timeframe trend alignment.
        self.trend = None
        if c.get("trend") and c.get("timeframes", {}).get("bias"):
            bias = resample(entry_df, c["timeframes"]["bias"])
            bc = bias["close"]
            ef = ema(bc, c["trend"]["ema_fast"])
            es = ema(bc, c["trend"]["ema_slow"])
            t = pd.Series("NONE", index=bias.index)
            t[(bc > es) & (ef > es)] = "BULL"
            t[(bc < es) & (ef < es)] = "BEAR"
            self.trend = t.shift(1).reindex(entry_df.index, method="ffill").fillna("NONE")

    def signal_at(self, i: int) -> Optional[Signal]:
        if i < 2 or not bool(self.tradeable.iloc[i]):
            return None
        hi, lo, a = self.hi.iloc[i], self.lo.iloc[i], self.atr.iloc[i]
        if pd.isna(hi) or pd.isna(lo) or pd.isna(a) or a <= 0:
            return None
        c = self.config
        stop_mult = c["risk"]["stop"].get("atr_mult", 1.0)
        target_r = c["risk"].get("target_r", 1.5)
        cl = self.df["close"].iloc[i]
        trend = self.trend.iloc[i] if self.trend is not None else None

        if cl > hi and (trend is None or trend == "BULL"):
            stop = cl - stop_mult * a
            r = cl - stop
            if r <= 0:
                return None
            return Signal("BUY", cl, stop, cl + target_r * r, "channel break up")
        if cl < lo and (trend is None or trend == "BEAR"):
            stop = cl + stop_mult * a
            r = stop - cl
            if r <= 0:
                return None
            return Signal("SELL", cl, stop, cl - target_r * r, "channel break down")
        return None
