"""Price feeds for the executor.

A feed answers one question: "give me the most recent N bars for this symbol,
as of now." The executor rebuilds the strategy on that window each step, so the
same strategy code drives backtest, replay and live — no divergence.

- ReplayFeed: walks a stored DataFrame with a cursor (history/testing).
- MT5Feed: pulls recent bars from a MetaTrader 5 terminal (the trading machine).
"""
from __future__ import annotations

from typing import Dict, Optional
import pandas as pd


class ReplayFeed:
    """Replays historical bars. `recent_bars` returns everything up to (and
    including) the cursor; `advance` moves it forward one bar (a new 'close')."""
    def __init__(self, bars_by_symbol: Dict[str, pd.DataFrame], start: int = 300):
        self._bars = {s: df for s, df in bars_by_symbol.items()}
        self._cursor = start
        self._len = min((len(df) for df in self._bars.values()), default=0)

    def recent_bars(self, symbol: str, count: int = 600) -> pd.DataFrame:
        df = self._bars.get(symbol)
        if df is None:
            return pd.DataFrame()
        end = min(self._cursor, len(df))
        return df.iloc[max(0, end - count):end]

    def now_price(self, symbol: str) -> Optional[float]:
        bars = self.recent_bars(symbol, 1)
        return float(bars["close"].iloc[-1]) if len(bars) else None

    def advance(self, n: int = 1) -> None:
        self._cursor += n

    def has_more(self) -> bool:
        return self._cursor < self._len


class MT5Feed:
    """Recent bars from a MetaTrader 5 terminal. Runs only on the trading
    machine; MetaTrader5 is imported lazily (tests inject a stub)."""
    _TF = None

    def __init__(self, timeframe: str = "M5", mt5=None):
        self._mt5 = mt5
        self._timeframe = timeframe

    def _lib(self):
        if self._mt5 is None:
            import MetaTrader5 as mt5   # noqa: only on the trading machine
            self._mt5 = mt5
        return self._mt5

    def _tf_const(self):
        mt5 = self._lib()
        return getattr(mt5, "TIMEFRAME_" + self._timeframe.upper(),
                       getattr(mt5, "TIMEFRAME_M5"))

    def recent_bars(self, symbol: str, count: int = 600) -> pd.DataFrame:
        mt5 = self._lib()
        mt5.symbol_select(symbol, True)
        rates = mt5.copy_rates_from_pos(symbol, self._tf_const(), 0, count)
        if rates is None or len(rates) == 0:
            return pd.DataFrame()
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        return df.set_index("time")[["open", "high", "low", "close"]]

    def now_price(self, symbol: str):
        t = self._lib().symbol_info_tick(symbol)
        return float(t.bid) if t else None
