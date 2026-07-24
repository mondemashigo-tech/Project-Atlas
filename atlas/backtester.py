"""Event-driven backtester. Walks entry-timeframe bars, asks the strategy for a
signal, fills at the next bar's open, and resolves stop/target bar-by-bar with
modelled spread + commission. One position per symbol at a time; a per-day trade
cap is enforced. No look-ahead: signal_at(i) never sees bar i+1."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import List
import pandas as pd

from .strategies.base import Strategy


@dataclass
class Trade:
    symbol: str
    direction: str
    entry_time: str
    exit_time: str
    entry: float
    stop: float
    target: float
    exit: float
    exit_reason: str
    r_multiple: float
    pnl_r: float          # P/L in R units, AFTER costs
    reason: str


def _pip(symbol: str) -> float:
    return 0.01 if symbol.upper().endswith("JPY") else 0.0001


def run(symbol: str, entry_df: pd.DataFrame, strategy: Strategy,
        spread_pips: float = 1.0, commission_r: float = 0.0,
        max_trades_per_day: int = 3, context: dict = None) -> List[Trade]:
    strategy.prepare(entry_df, symbol=symbol, context=context)
    pip = _pip(symbol)
    spread = spread_pips * pip

    idx = entry_df.index
    o = entry_df["open"].to_numpy()
    h = entry_df["high"].to_numpy()
    lo = entry_df["low"].to_numpy()
    n = len(entry_df)

    trades: List[Trade] = []
    i = 0
    day_count = {}
    while i < n - 1:
        day = idx[i].date()
        if day_count.get(day, 0) >= max_trades_per_day:
            i += 1
            continue
        sig = strategy.signal_at(i)
        if sig is None:
            i += 1
            continue

        # Fill at next bar open, paying the spread on the crossed side.
        entry = o[i + 1] + (spread if sig.direction == "BUY" else -spread)
        r = abs(entry - sig.stop)
        if r <= 0:
            i += 1
            continue

        exit_price = exit_reason = None
        exit_j = None
        for j in range(i + 1, n):
            if sig.direction == "BUY":
                hit_sl = lo[j] <= sig.stop
                hit_tp = h[j] >= sig.target
            else:
                hit_sl = h[j] >= sig.stop
                hit_tp = lo[j] <= sig.target
            if hit_sl and hit_tp:      # ambiguous bar -> assume stop first (conservative)
                exit_price, exit_reason = sig.stop, "SL"
            elif hit_sl:
                exit_price, exit_reason = sig.stop, "SL"
            elif hit_tp:
                exit_price, exit_reason = sig.target, "TP"
            if exit_price is not None:
                exit_j = j
                break
        if exit_price is None:
            exit_price, exit_reason, exit_j = entry_df["close"].iloc[-1], "END", n - 1

        signed = 1 if sig.direction == "BUY" else -1
        pnl_price = signed * (exit_price - entry)
        pnl_r = pnl_price / r - commission_r      # net of commission (in R)
        trades.append(Trade(
            symbol, sig.direction, str(idx[i + 1]), str(idx[exit_j]),
            round(entry, 5), round(sig.stop, 5), round(sig.target, 5),
            round(exit_price, 5), exit_reason, round(pnl_price / r, 3),
            round(pnl_r, 3), sig.reason))
        day_count[day] = day_count.get(day, 0) + 1
        i = exit_j + 1     # flat until the trade closes, then resume
    return trades


def trades_to_frame(trades: List[Trade]) -> pd.DataFrame:
    return pd.DataFrame([asdict(t) for t in trades])
