"""Composed strategy — the template Atlas *invents* into.

Unlike the four hand-built templates, a composed strategy is assembled entirely
from config: a list of features (built-in or invented formula indicators) plus
entry rules expressed in the rule grammar. This is what lets the lab mix
things — "trend filter AND rsi oversold AND volatility expanding" — and test the
mixture with zero new Python.

Config shape (all under the usual hypothesis YAML):

    template: composed
    features:
      - {name: ema_fast, kind: ema, source: close, period: 20}
      - {name: rsi14,    kind: rsi, period: 14}
      - {name: atr14,    kind: atr, period: 14}
      - {name: stretch,  kind: formula,
         expr: {fn: div, args: [{fn: sub, args: ["close", "ema_fast"]}, "atr14"]}}
    entry_long:  {all: [{lhs: close, cmp: ">", rhs: ema_fast},
                        {lhs: rsi14, cmp: "<", rhs: 35}]}
    entry_short: {all: [{lhs: close, cmp: "<", rhs: ema_fast},
                        {lhs: rsi14, cmp: ">", rhs: 65}]}      # optional
    session: {start: "07:00", end: "16:00", tz: "Europe/London",
              data_utc_offset: 0}                              # optional
    weekdays: [0,1,2,3,4]                                      # optional
    risk:
      stop: {kind: atr, atr_period: 14, atr_mult: 1.5}         # or {kind: swing, lookback: 20}
      target_r: 2.0
      max_trades_per_day: 3

Look-ahead safety is inherited: features and rules only read the current-or-prior
bar, and the backtester still fills at the next bar's open.
"""
from __future__ import annotations

from typing import Optional
import pandas as pd

from ..features import build_features
from ..rules import evaluate
from ..indicators import atr as _atr, swing_low, swing_high
from .base import Strategy, Signal


@Strategy.register("composed")
class Composed(Strategy):
    name = "composed"

    def prepare(self, entry_df: pd.DataFrame, symbol: str = None,
                context: dict = None) -> None:
        c = self.config
        self.df = entry_df
        self.symbol = symbol

        # 1) features (built-in + invented). Later features may use earlier ones.
        self.feats = build_features(entry_df, c.get("features", []))

        # 2) entry masks from the rule grammar. entry_long is required; short is
        #    optional (a long-only strategy just omits it).
        if "entry_long" not in c and "entry_short" not in c:
            raise ValueError("composed strategy needs entry_long and/or entry_short")
        idx = entry_df.index
        self.long_mask = (evaluate(c["entry_long"], entry_df, self.feats)
                          if "entry_long" in c else pd.Series(False, index=idx))
        self.short_mask = (evaluate(c["entry_short"], entry_df, self.feats)
                           if "entry_short" in c else pd.Series(False, index=idx))

        # 3) risk plumbing
        risk = c.get("risk", {})
        stop = risk.get("stop", {})
        self.stop_kind = stop.get("kind", "atr")
        self.atr = _atr(entry_df, int(stop.get("atr_period", 14)))
        self.atr_mult = float(stop.get("atr_mult", 1.5))
        self.swing_lo = swing_low(entry_df, int(stop.get("lookback", 20)))
        self.swing_hi = swing_high(entry_df, int(stop.get("lookback", 20)))
        self.target_r = float(risk.get("target_r", 2.0))

        # 4) session / weekday mask (optional). Same broker-offset handling as the
        #    other templates: data_utc_offset shifts stamps back to true UTC first.
        self.tradeable = self._session_mask(entry_df, c)

    @staticmethod
    def _session_mask(entry_df: pd.DataFrame, c: dict) -> pd.Series:
        sess = c.get("session")
        idx = entry_df.index
        if not sess:
            base = pd.Series(True, index=idx)
            local = idx
        else:
            tz = sess.get("tz", "UTC")
            offset = sess.get("data_utc_offset", 0)
            local = (idx - pd.Timedelta(hours=offset)).tz_convert(tz) \
                if idx.tz is not None else idx - pd.Timedelta(hours=offset)
            start = pd.to_datetime(sess["start"]).time()
            end = pd.to_datetime(sess["end"]).time()
            base = pd.Series([start <= t.time() < end for t in local], index=idx)
        wd_source = local if hasattr(local, "weekday") else idx
        weekdays = c.get("weekdays")
        if weekdays is not None:
            wd = pd.Series(wd_source.weekday, index=idx)
            base = base & wd.isin(set(weekdays))
        return base

    def _stop_for(self, direction: str, i: int, cl: float) -> Optional[float]:
        a = self.atr.iloc[i]
        if self.stop_kind == "swing":
            swing = (self.swing_lo.iloc[i] if direction == "BUY"
                     else self.swing_hi.iloc[i])
            if pd.isna(swing):                       # fall back to ATR early on
                if pd.isna(a) or a <= 0:
                    return None
                return cl - self.atr_mult * a if direction == "BUY" \
                    else cl + self.atr_mult * a
            return float(swing)
        # default: ATR stop
        if pd.isna(a) or a <= 0:
            return None
        return cl - self.atr_mult * a if direction == "BUY" \
            else cl + self.atr_mult * a

    def signal_at(self, i: int) -> Optional[Signal]:
        if i < 1 or not bool(self.tradeable.iloc[i]):
            return None
        want_long = bool(self.long_mask.iloc[i])
        want_short = bool(self.short_mask.iloc[i])
        if want_long == want_short:                  # neither, or ambiguous both
            return None
        direction = "BUY" if want_long else "SELL"
        cl = float(self.df["close"].iloc[i])
        stop = self._stop_for(direction, i, cl)
        if stop is None:
            return None
        r = (cl - stop) if direction == "BUY" else (stop - cl)
        if r <= 0:
            return None
        target = cl + self.target_r * r if direction == "BUY" \
            else cl - self.target_r * r
        return Signal(direction, cl, stop, target, "composed")
