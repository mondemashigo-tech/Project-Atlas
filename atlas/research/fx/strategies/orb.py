"""Opening Range Breakout (ORB) template.

The opening range is the first `range_minutes` of the session. After that window
closes, the first bar to CLOSE beyond the range high/low — in agreement with an
EMA filter — triggers a trade. Wick-only breaks (that don't close outside) are
ignored by construction (we test the close, not the high/low).

Rules (all config-driven):
- opening range = high/low of the first `range_minutes` of `session`.
- LONG when a bar closes ABOVE the range high AND above the `ema`.
- SHORT when a bar closes BELOW the range low AND below the `ema`.
- stop = opposite side of the range (`stop.type: opposite_range`) or ATR
  (`stop.type: atr`, `atr_mult`); target = `target_r` × risk.
- one entry per session-day is the convention — set `risk.max_trades_per_day: 1`.

No look-ahead: the range is only used AFTER its window has fully closed.
"""
from __future__ import annotations

from typing import Optional
import pandas as pd

from ..indicators import ema, atr
from .base import Strategy, Signal
from .common import session_weekday_mask


@Strategy.register("orb")
class OpeningRangeBreakout(Strategy):
    name = "orb"

    def prepare(self, entry_df: pd.DataFrame, symbol: str = None,
                context: dict = None) -> None:
        c = self.config
        o = c["orb"]
        self.df = entry_df
        self.ema = ema(entry_df["close"], o.get("ema", 20))
        self.atr = atr(entry_df, c["risk"]["stop"].get("atr_period", 14))
        self.tradeable = session_weekday_mask(entry_df, c)

        sess = c["session"]
        tz = sess.get("tz", "UTC")
        off = sess.get("data_utc_offset", 0)
        local = (entry_df.index - pd.Timedelta(hours=off)).tz_convert(tz)
        start_t = pd.to_datetime(sess["start"]).time()
        start_secs = start_t.hour * 3600 + start_t.minute * 60
        range_secs = o.get("range_minutes", 5) * 60

        secs = pd.Series([t.hour * 3600 + t.minute * 60 + t.second for t in local],
                         index=entry_df.index)
        day = pd.Series([d.date() for d in local], index=entry_df.index)
        in_or = (secs >= start_secs) & (secs < start_secs + range_secs)
        # Opening-range high/low per session-day (NaN outside OR bars -> ignored).
        self.or_hi = entry_df["high"].where(in_or).groupby(day).transform("max")
        self.or_lo = entry_df["low"].where(in_or).groupby(day).transform("min")
        self.in_or = in_or
        self.after_or = secs >= (start_secs + range_secs)

    def signal_at(self, i: int) -> Optional[Signal]:
        if i < 1 or not bool(self.tradeable.iloc[i]) or bool(self.in_or.iloc[i]) \
                or not bool(self.after_or.iloc[i]):
            return None
        orh, orl = self.or_hi.iloc[i], self.or_lo.iloc[i]
        e, a = self.ema.iloc[i], self.atr.iloc[i]
        if pd.isna(orh) or pd.isna(orl) or pd.isna(e) or pd.isna(a) or a <= 0:
            return None
        row = self.df.iloc[i]
        cl = row["close"]

        c = self.config
        st = c["risk"]["stop"]
        stop_type = st.get("type", "opposite_range")
        atr_mult = st.get("atr_mult", 1.0)
        target_r = c["risk"].get("target_r", 2.0)

        if cl > orh and cl > e:                       # close breaks range high, above EMA
            stop = orl if stop_type == "opposite_range" else cl - atr_mult * a
            r = cl - stop
            if r <= 0:
                return None
            return Signal("BUY", cl, stop, cl + target_r * r, "ORB long breakout")
        if cl < orl and cl < e:                       # close breaks range low, below EMA
            stop = orh if stop_type == "opposite_range" else cl + atr_mult * a
            r = stop - cl
            if r <= 0:
                return None
            return Signal("SELL", cl, stop, cl - target_r * r, "ORB short breakout")
        return None
