"""Trend-continuation pullback template (the London hypothesis, generalised).

Config-driven. In the higher-timeframe (bias) trend direction, enter on a
pullback to the entry-TF fast EMA with a confirmation candle, during a session
window on allowed weekdays. Stop = max(swing, N*ATR); target = R multiple.
Every threshold is a config parameter — nothing is hardcoded.
"""
from __future__ import annotations

from typing import Optional
import pandas as pd

from ..indicators import ema, atr, swing_low, swing_high
from .base import Strategy, Signal


@Strategy.register("trend_continuation")
class TrendContinuation(Strategy):
    name = "trend_continuation"

    def prepare(self, entry_df: pd.DataFrame) -> None:
        c = self.config
        self.df = entry_df
        px = entry_df["close"]

        # Entry-TF pullback reference + confirmation inputs.
        self.ema_pull = ema(px, c["entry"]["pullback_ema"])
        self.atr = atr(entry_df, c["risk"]["stop"].get("atr_period", 14))
        self.swing_lo = swing_low(entry_df, c["risk"]["stop"].get("swing_lookback", 20))
        self.swing_hi = swing_high(entry_df, c["risk"]["stop"].get("swing_lookback", 20))

        # Bias trend, computed on the bias timeframe then aligned back to entry
        # bars via as-of merge (each entry bar sees the last CLOSED bias bar).
        from ..data import resample
        bias = resample(entry_df, c["timeframes"]["bias"])
        bias_close = bias["close"]
        ef = ema(bias_close, c["trend"]["ema_fast"])
        es = ema(bias_close, c["trend"]["ema_slow"])
        bull = (bias_close > es) & (ef > es)
        bear = (bias_close < es) & (ef < es)
        trend = pd.Series("NONE", index=bias.index)
        trend[bull] = "BULL"
        trend[bear] = "BEAR"
        # shift(1): an entry bar may only use bias bars that have fully closed.
        self.trend = trend.shift(1).reindex(entry_df.index, method="ffill").fillna("NONE")

        # Session / weekday mask on the entry index (index is UTC).
        tz = c["session"].get("tz", "UTC")
        local = entry_df.index.tz_convert(tz)
        start = pd.to_datetime(c["session"]["start"]).time()
        end = pd.to_datetime(c["session"]["end"]).time()
        in_sess = pd.Series([start <= t.time() < end for t in local], index=entry_df.index)
        wd = pd.Series(local.weekday, index=entry_df.index)
        allowed = set(c.get("weekdays", [0, 1, 2, 3, 4]))
        self.tradeable = in_sess & wd.isin(allowed)

    def signal_at(self, i: int) -> Optional[Signal]:
        if i < 2 or not bool(self.tradeable.iloc[i]):
            return None
        trend = self.trend.iloc[i]
        if trend == "NONE":
            return None
        row = self.df.iloc[i]
        o, h, l, cl = row["open"], row["high"], row["low"], row["close"]
        ep = self.ema_pull.iloc[i]
        a = self.atr.iloc[i]
        if pd.isna(ep) or pd.isna(a) or a <= 0:
            return None

        c = self.config
        stop_mult = c["risk"]["stop"].get("atr_mult", 1.0)
        target_r = c["risk"]["target_r"]

        touched_ema = l <= ep <= h  # price pulled back to / through the fast EMA
        if trend == "BULL" and touched_ema and cl > o:
            swing = self.swing_lo.iloc[i]
            stop = min(swing if not pd.isna(swing) else cl - stop_mult * a,
                       cl - stop_mult * a)
            r = cl - stop
            if r <= 0:
                return None
            return Signal("BUY", cl, stop, cl + target_r * r, "bull pullback+confirm")
        if trend == "BEAR" and touched_ema and cl < o:
            swing = self.swing_hi.iloc[i]
            stop = max(swing if not pd.isna(swing) else cl + stop_mult * a,
                       cl + stop_mult * a)
            r = stop - cl
            if r <= 0:
                return None
            return Signal("SELL", cl, stop, cl - target_r * r, "bear pullback+confirm")
        return None
