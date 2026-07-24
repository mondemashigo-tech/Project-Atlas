"""Phase 4 external data sources: interest-rate differentials (carry) and an
economic calendar (news blackout). Both are optional and portable — plain CSVs
that live alongside the price datasets, loaded once per run and handed to the
strategy as ``context``. If a hypothesis references neither, nothing loads and
behaviour is identical to Phase 1-3.

CSV schemas (under the datasets dir):
  rates.csv     time, currency, rate      # policy / benchmark rate, step series
  calendar.csv  time, currency, impact    # impact in {low, medium, high}
"""
from __future__ import annotations

import os
from typing import Dict, Optional

import numpy as np
import pandas as pd

IMPACT_RANK = {"low": 1, "medium": 2, "high": 3}


def load_rates(datasets_dir: str) -> Optional[Dict[str, pd.DataFrame]]:
    path = os.path.join(datasets_dir, "rates.csv")
    if not os.path.exists(path):
        return None
    df = pd.read_csv(path)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df = df.sort_values("time")
    out = {}
    for cur, grp in df.groupby("currency"):
        out[str(cur).upper()] = grp[["time", "rate"]].reset_index(drop=True)
    return out


def rate_asof(rates: Dict[str, pd.DataFrame], currency: str,
              ts: pd.Timestamp) -> Optional[float]:
    """Most recent rate for `currency` at or before `ts` (no look-ahead)."""
    g = rates.get(currency.upper()) if rates else None
    if g is None or len(g) == 0:
        return None
    pos = g["time"].searchsorted(ts, side="right") - 1
    if pos < 0:
        return None
    return float(g["rate"].iloc[pos])


def load_calendar(datasets_dir: str) -> Optional[pd.DataFrame]:
    path = os.path.join(datasets_dir, "calendar.csv")
    if not os.path.exists(path):
        return None
    df = pd.read_csv(path)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df["currency"] = df["currency"].astype(str).str.upper()
    df["impact"] = df["impact"].astype(str).str.lower()
    df["rank"] = df["impact"].map(IMPACT_RANK).fillna(0).astype(int)
    return df.sort_values("time").reset_index(drop=True)


def build_context(cfg: dict, datasets_dir: str) -> dict:
    """Load only the sources a hypothesis actually asks for."""
    ctx = {"rates": None, "calendar": None}
    if cfg.get("carry", {}).get("require_aligned"):
        ctx["rates"] = load_rates(datasets_dir)
    if cfg.get("news_filter", {}).get("enabled"):
        ctx["calendar"] = load_calendar(datasets_dir)
    return ctx


def export_calendar_from_csv(*_args, **_kw):  # placeholder for a future fetcher
    raise NotImplementedError(
        "Provide calendar.csv (time, currency, impact) in the datasets dir. "
        "A live fetcher (e.g. from an economic-calendar API) can be added here.")
