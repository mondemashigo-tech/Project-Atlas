"""Entry filters driven by external data sources (Phase 4).

* **CarryFilter** — only allow a trade whose direction is aligned with the
  interest-rate differential of the pair (long the higher-yielding currency).
  Rationale: carry is a documented, persistent FX return source; trading with it
  puts a small structural tailwind behind each position. When rate data is
  missing for either leg, the filter abstains (allows) rather than guessing.

* **NewsFilter** — block entries inside a blackout window around high-impact
  scheduled events for either currency of the pair. Rationale: entries taken
  seconds before a central-bank release are gambling on a coin flip, not on the
  edge the hypothesis is meant to test.

Both are constructed only when the hypothesis enables them; otherwise the
strategy holds ``None`` and nothing is filtered.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from .datasources import IMPACT_RANK, rate_asof


def currencies_of(symbol: str):
    s = symbol.upper()
    return s[:3], s[3:6]


class CarryFilter:
    def __init__(self, rates, require_aligned: bool = True):
        self.rates = rates
        self.require_aligned = require_aligned

    def allows(self, symbol: str, direction: str, ts: pd.Timestamp) -> bool:
        if not self.require_aligned or not self.rates:
            return True
        base, quote = currencies_of(symbol)
        rb = rate_asof(self.rates, base, ts)
        rq = rate_asof(self.rates, quote, ts)
        if rb is None or rq is None:
            return True                      # no data -> abstain
        diff = rb - rq                       # +ve: base out-yields quote
        if diff == 0:
            return True
        return (direction == "BUY" and diff > 0) or (direction == "SELL" and diff < 0)


class NewsFilter:
    def __init__(self, calendar: pd.DataFrame, symbol: str,
                 before_min: int = 30, after_min: int = 30, min_impact: str = "high"):
        self.before = pd.Timedelta(minutes=before_min)
        self.after = pd.Timedelta(minutes=after_min)
        self._times = np.array([], dtype="datetime64[ns]")
        if calendar is not None and len(calendar):
            base, quote = currencies_of(symbol)
            floor = IMPACT_RANK.get(str(min_impact).lower(), 3)
            mask = calendar["currency"].isin({base, quote}) & (calendar["rank"] >= floor)
            times = calendar.loc[mask, "time"]
            if len(times):
                naive = times.dt.tz_convert("UTC").dt.tz_localize(None)
                self._times = np.sort(naive.to_numpy().astype("datetime64[ns]"))

    def blocks(self, ts: pd.Timestamp) -> bool:
        if self._times.size == 0:
            return False
        # An entry at ts is blocked if some event e satisfies
        #   e - before <= ts <= e + after   <=>   ts - after <= e <= ts + before
        t = np.datetime64(ts.tz_convert("UTC").tz_localize(None), "ns")
        lo = t - np.timedelta64(self.after)
        hi = t + np.timedelta64(self.before)
        i = np.searchsorted(self._times, lo, side="left")
        return bool(i < self._times.size and self._times[i] <= hi)


def build(cfg: dict, context: dict, symbol: str):
    """Return (carry_filter_or_None, news_filter_or_None) for a symbol."""
    context = context or {}
    carry = None
    if cfg.get("carry", {}).get("require_aligned"):
        carry = CarryFilter(context.get("rates"), require_aligned=True)
    news = None
    nf = cfg.get("news_filter", {})
    if nf.get("enabled"):
        news = NewsFilter(context.get("calendar"), symbol,
                          before_min=nf.get("block_minutes_before", 30),
                          after_min=nf.get("block_minutes_after", 30),
                          min_impact=nf.get("min_impact", "high"))
    return carry, news
