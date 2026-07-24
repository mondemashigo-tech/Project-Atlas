"""In-sample / out-of-sample date splitting. The frozen rule of the platform:
optimise on in-sample, judge on out-of-sample, never the reverse."""
from __future__ import annotations

import pandas as pd


def slice_dates(df: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    lo = pd.Timestamp(start, tz="UTC")
    hi = pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1)
    return df[(df.index >= lo) & (df.index < hi)]


def in_sample(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    a, b = config["data"]["in_sample"]
    return slice_dates(df, a, b)


def out_sample(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    a, b = config["data"]["out_sample"]
    return slice_dates(df, a, b)
