"""Break of Structure + Retracement Entry (BOS_RETRACE).

A faithful, stateful implementation of the video-derived spec (Atlas Strategy
Handoff v0.1). This is NOT a plain breakout: it is a multi-phase state machine
that distinguishes a liquidity sweep from a genuine break, then waits for a
retracement to the broken level and a confirmation candle before entering.

Phases (bullish; bearish mirrors):
  1. Structure   — confirmed swing high (pivot with `swing_pivot` bars each side;
                   available only `swing_pivot` bars after it forms — no look-ahead).
  2. BOS         — a candle CLOSES above the level by >= `bos_atr` * ATR, with body
                   >= `body_frac` of its range and true range >= `displacement_atr`
                   * ATR (genuine displacement, not a wick/sweep).
  3. Retracement — within `expiry_bars`, price returns to within `retest_atr` * ATR
                   of the broken level WITHOUT a close back below it (invalidation).
  4. Confirmation— a candle closes above the prior candle's high at the retest.
  5. Entry       — next candle open (+ realistic costs, handled by the backtester).
     Stop  = lowest low of the retracement - `stop_buffer_atr` * ATR.
     Target= `target_r` R.
  One trade per structural break; the setup expires if no valid retest occurs.

Everything is precomputed vectorially in prepare(); signal_at(i) just reports a
precomputed entry, so it is robust to the backtester skipping bars during a trade.
Assumptions (everything the video did NOT specify) are config parameters with
labelled defaults — the strategy claims no edge; the ladder decides.
"""
from __future__ import annotations

from typing import Optional
import numpy as np
import pandas as pd

from ..indicators import atr as _atr
from .base import Strategy, Signal
from .common import session_weekday_mask


@Strategy.register("bos_retrace")
class BosRetrace(Strategy):
    name = "bos_retrace"

    def prepare(self, entry_df: pd.DataFrame, symbol: str = None,
                context: dict = None) -> None:
        c = self.config
        self.df = entry_df
        b = c.get("bos", {})
        s = int(b.get("swing_pivot", 3))
        atr_period = int(b.get("atr_period", 14))
        bos_atr = float(b.get("bos_atr", 0.10))
        body_frac = float(b.get("body_frac", 0.60))
        disp_atr = float(b.get("displacement_atr", 1.20))
        retest_atr = float(b.get("retest_atr", 0.20))
        expiry = int(b.get("expiry_bars", 12))
        stop_buf = float(b.get("stop_buffer_atr", 0.10))
        target_r = float(c.get("risk", {}).get("target_r", 2.0))

        h, l, o, cl = (entry_df["high"], entry_df["low"],
                       entry_df["open"], entry_df["close"])
        atr = _atr(entry_df, atr_period)
        # per-bar true range (for the displacement filter)
        prev_c = cl.shift(1)
        tr = pd.concat([h - l, (h - prev_c).abs(), (l - prev_c).abs()],
                       axis=1).max(axis=1)
        rng = (h - l).replace(0, np.nan)
        body = (cl - o).abs()

        # confirmed pivots: a centred rolling extreme, made available `s` bars later
        win = 2 * s + 1
        piv_hi = h == h.rolling(win, center=True).max()
        piv_lo = l == l.rolling(win, center=True).min()
        level_hi = h.where(piv_hi).shift(s).ffill()
        level_lo = l.where(piv_lo).shift(s).ffill()

        bull_bos = ((cl > level_hi + bos_atr * atr) & (cl > o) &
                    (body >= body_frac * rng) & (tr >= disp_atr * atr))
        bear_bos = ((cl < level_lo - bos_atr * atr) & (cl < o) &
                    (body >= body_frac * rng) & (tr >= disp_atr * atr))

        self.tradeable = session_weekday_mask(entry_df, c)

        # forward-scan each BOS for a valid retest + confirmation -> entry bar
        Hn, Ln, Cn = h.to_numpy(), l.to_numpy(), cl.to_numpy()
        A = atr.to_numpy(); LH = level_hi.to_numpy(); LL = level_lo.to_numpy()
        bull = bull_bos.fillna(False).to_numpy()
        bear = bear_bos.fillna(False).to_numpy()
        n = len(entry_df)
        entries = {}                      # entry_bar_index -> Signal

        for b0 in range(n):
            a = A[b0]
            if np.isnan(a) or a <= 0:
                continue
            if bull[b0]:
                level = LH[b0]; tol = retest_atr * a; lowest = Ln[b0]
                for j in range(b0 + 1, min(b0 + 1 + expiry, n)):
                    if Cn[j] < level:                      # invalidation
                        break
                    lowest = min(lowest, Ln[j])
                    if Ln[j] <= level + tol and Cn[j] > Hn[j - 1]:  # retest + confirm
                        stop = lowest - stop_buf * a
                        entry = Cn[j]; r = entry - stop
                        if r > 0 and j not in entries:
                            entries[j] = Signal("BUY", entry, stop,
                                                entry + target_r * r, "bull BOS+retrace")
                        break
            elif bear[b0]:
                level = LL[b0]; tol = retest_atr * a; highest = Hn[b0]
                for j in range(b0 + 1, min(b0 + 1 + expiry, n)):
                    if Cn[j] > level:                      # invalidation
                        break
                    highest = max(highest, Hn[j])
                    if Hn[j] >= level - tol and Cn[j] < Ln[j - 1]:
                        stop = highest + stop_buf * a
                        entry = Cn[j]; r = stop - entry
                        if r > 0 and j not in entries:
                            entries[j] = Signal("SELL", entry, stop,
                                                entry - target_r * r, "bear BOS+retrace")
                        break
        self._entries = entries

    def signal_at(self, i: int) -> Optional[Signal]:
        if not bool(self.tradeable.iloc[i]):
            return None
        return self._entries.get(i)
