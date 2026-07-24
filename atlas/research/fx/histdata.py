"""HistData.com importer.

HistData "Generic ASCII" M1 files look like:

    20230102 170000;1.070000;1.070200;1.069900;1.070100;0
    <YYYYMMDD HHMMSS>;<open>;<high>;<low>;<close>;<volume>

Timestamps are US Eastern Standard Time with NO daylight saving (fixed UTC-5),
per HistData's format notes. We convert to true UTC on import so the rest of
Atlas is timezone-clean. Output is the platform's standard schema
(`time,open,high,low,close`), which `data.load_csv` already reads.

Input may be a list of .csv or .zip files (HistData ships monthly/yearly zips
each containing one DAT_ASCII_*.csv). Files are concatenated, de-duplicated on
timestamp, and sorted.
"""
from __future__ import annotations

import glob
import io
import os
import zipfile
from typing import List

import pandas as pd

HISTDATA_SRC_UTC_OFFSET = -5   # EST, no DST


def _read_one(path: str) -> pd.DataFrame:
    if path.lower().endswith(".zip"):
        with zipfile.ZipFile(path) as z:
            name = next(n for n in z.namelist() if n.lower().endswith(".csv"))
            raw = z.read(name)
        buf = io.BytesIO(raw)
    else:
        buf = path
    df = pd.read_csv(buf, sep=";", header=None,
                     names=["dt", "open", "high", "low", "close", "volume"])
    return df


def import_histdata(paths, out_dir: str, symbol: str,
                    src_utc_offset: int = HISTDATA_SRC_UTC_OFFSET) -> str:
    """Import one or more HistData ASCII M1 files into out_dir/SYMBOL_M1.csv (UTC).
    `paths` may be a single path, a glob, or a list. Returns the output path."""
    if isinstance(paths, str):
        paths = sorted(glob.glob(paths)) or [paths]
    frames = [_read_one(p) for p in paths]
    df = pd.concat(frames, ignore_index=True)

    dt = pd.to_datetime(df["dt"], format="%Y%m%d %H%M%S")
    # EST (fixed) -> UTC:  utc = est - offset  (offset is -5, so utc = est + 5h)
    df["time"] = (dt - pd.Timedelta(hours=src_utc_offset)).dt.tz_localize("UTC")
    df = (df[["time", "open", "high", "low", "close"]]
          .drop_duplicates("time").sort_values("time").reset_index(drop=True))
    df["time"] = df["time"].dt.strftime("%Y-%m-%d %H:%M:%S%z")

    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{symbol.upper()}_M1.csv")
    df.to_csv(path, index=False)
    return path
