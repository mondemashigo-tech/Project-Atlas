"""Mean-reversion (z-score fade) template.

When price is stretched far from a moving average, fade it back toward the mean.
z = (close - SMA) / rolling std. A BUY triggers when z <= -entry_z (oversold);
a SELL when z >= +entry_z (overbought). Stop = atr_mult * ATR beyond entry;
target is either the mean (exit: mean) or a fixed R multiple (exit: rr).

This is a counter-trend edge — the opposite premise to trend_continuation — so
running both on the same data is a genuine test of which regime the market is in.
Every threshold is a config parameter.
"""
from __future__ import annotations

from typing import Optional
import pandas as pd

from ..indicators import atr
from .base import Strategy, Signal
from .common import session_weekday_mask


@Strategy.register("mean_reversion")
class MeanReversion(Strategy):
    name = "mean_reversion"

    def prepare(self, entry_df: pd.DataFrame, symbol: str = None,
                context: dict = None) -> None:
        c = self.config
        self.df = entry_df
        m = c["meanrev"]
        period = m.get("ma_period", 20)
        px = entry_df["close"]
        self.sma = px.rolling(period).mean()
        self.std = px.rolling(period).std()
        self.z = (px - self.sma) / self.std
        self.atr = atr(entry_df, c["risk"]["stop"].get("atr_period", 14))
        self.tradeable = session_weekday_mask(entry_df, c)

    def signal_at(self, i: int) -> Optional[Signal]:
        if i < 2 or not bool(self.tradeable.iloc[i]):
            return None
        z = self.z.iloc[i]
        a = self.atr.iloc[i]
        sma = self.sma.iloc[i]
        if pd.isna(z) or pd.isna(a) or a <= 0 or pd.isna(sma):
            return None

        c = self.config
        m = c["meanrev"]
        entry_z = m.get("entry_z", 2.0)
        exit_mode = m.get("exit", "mean")
        stop_mult = c["risk"]["stop"].get("atr_mult", 1.0)
        target_r = c["risk"].get("target_r", 1.5)
        cl = self.df["close"].iloc[i]

        if z <= -entry_z:                      # oversold -> fade up (BUY)
            stop = cl - stop_mult * a
            r = cl - stop
            if r <= 0:
                return None
            target = sma if exit_mode == "mean" else cl + target_r * r
            if target <= cl:
                return None
            return Signal("BUY", cl, stop, target, f"z {round(float(z),2)} fade up")
        if z >= entry_z:                       # overbought -> fade down (SELL)
            stop = cl + stop_mult * a
            r = stop - cl
            if r <= 0:
                return None
            target = sma if exit_mode == "mean" else cl - target_r * r
            if target >= cl:
                return None
            return Signal("SELL", cl, stop, target, f"z {round(float(z),2)} fade down")
        return None
