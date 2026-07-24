"""Orchestrates one hypothesis run: load data, split in/out-of-sample, backtest
each market, aggregate metrics, and judge against pre-registered criteria."""
from __future__ import annotations

import os
from typing import Dict

from . import data as data_mod
from . import splits
from .strategies.base import Strategy
from .backtester import run as run_bt, Trade
from .metrics import compute


def _run_window(cfg, datasets_dir, window_slicer) -> Dict:
    entry_tf = cfg["timeframes"]["entry"]
    spread = cfg.get("costs", {}).get("spread_pips", 1.0)
    commission_r = cfg.get("costs", {}).get("commission_r", 0.0)
    max_tpd = cfg["risk"].get("max_trades_per_day", 3)

    all_trades = []
    per_market = {}
    for sym in cfg["markets"]:
        try:
            df = data_mod.load_symbol(datasets_dir, sym, entry_tf)
        except FileNotFoundError:
            per_market[sym] = {"trades": 0}
            continue
        df = window_slicer(df, cfg)
        if len(df) < 300:
            per_market[sym] = {"trades": 0}
            continue
        strat = Strategy.create(cfg)
        trades = run_bt(sym, df, strat, spread_pips=spread,
                        commission_r=commission_r, max_trades_per_day=max_tpd)
        per_market[sym] = compute(trades)
        all_trades.extend(trades)
    return {"metrics": compute(all_trades), "per_market": per_market,
            "trades": all_trades}


def run_hypothesis(cfg: dict, datasets_dir: str) -> Dict:
    return {
        "in_sample": _run_window(cfg, datasets_dir, splits.in_sample),
        "out_sample": _run_window(cfg, datasets_dir, splits.out_sample),
    }


def run_full(cfg: dict, datasets_dir: str) -> Dict:
    """Backtest the entire available history with no split — the full realised
    trade set, used as the input to Monte Carlo resampling."""
    return _run_window(cfg, datasets_dir, lambda df, _cfg: df)
