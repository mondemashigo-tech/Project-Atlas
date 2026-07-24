"""Vectorised indicators. Pure functions on a price DataFrame (OHLC)."""
from __future__ import annotations

import pandas as pd


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))


def swing_low(df: pd.DataFrame, lookback: int = 20) -> pd.Series:
    """Rolling lowest low over the prior `lookback` bars (excludes current)."""
    return df["low"].shift(1).rolling(lookback).min()


def swing_high(df: pd.DataFrame, lookback: int = 20) -> pd.Series:
    return df["high"].shift(1).rolling(lookback).max()
