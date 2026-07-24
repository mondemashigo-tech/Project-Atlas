"""Anchored walk-forward analysis.

The timeline is cut into K+1 equal calendar segments. Fold *t* optimises the
strategy on segments [0..t] (an expanding IN-SAMPLE window) and then tests the
chosen parameters on segment t+1 — never-seen OUT-OF-SAMPLE data — for
t = 0..K-1. Every fold's out-of-sample trades are concatenated into one honest
walk-forward equity curve.

If the hypothesis declares an ``optimize:`` grid (mapping dotted config paths to
lists of candidate values), each fold re-selects the parameter set with the best
in-sample objective. With no grid, fixed parameters are simply rolled forward —
a consistency-through-time check, which is itself informative: a real edge keeps
working on data it was never tuned on.

Two headline numbers:
* **walk-forward efficiency** = mean OOS expectancy / mean IS expectancy. Near
  1.0 means out-of-sample performance held up; well below 1.0 (or negative) is
  the fingerprint of curve-fitting.
* **consistency** = fraction of folds whose out-of-sample total R was positive.
"""
from __future__ import annotations

from typing import Dict, List

import numpy as np
import pandas as pd

from . import data as data_mod
from . import datasources
from .paramgrid import expand as _grid
from .strategies.base import Strategy
from .backtester import run as run_bt
from .metrics import compute


def _time_edges(tmin: pd.Timestamp, tmax: pd.Timestamp, n_seg: int) -> List[pd.Timestamp]:
    """n_seg equal-duration segments -> n_seg+1 boundary timestamps. Uses
    Timedelta arithmetic so it is agnostic to the index's datetime resolution
    (pandas 2.x yields datetime64[s] from epoch-second CSVs, not [ns])."""
    span = tmax - tmin
    return [tmin + span * (i / n_seg) for i in range(n_seg + 1)]


def _bt_window(cfg_variant: dict, frames: Dict[str, pd.DataFrame],
               lo: pd.Timestamp, hi: pd.Timestamp, context: dict = None) -> list:
    spread = cfg_variant.get("costs", {}).get("spread_pips", 1.0)
    commission_r = cfg_variant.get("costs", {}).get("commission_r", 0.0)
    max_tpd = cfg_variant["risk"].get("max_trades_per_day", 3)
    trades = []
    for sym, df in frames.items():
        w = df[(df.index >= lo) & (df.index < hi)]
        if len(w) < 300:
            continue
        strat = Strategy.create(cfg_variant)
        trades.extend(run_bt(sym, w, strat, spread_pips=spread,
                             commission_r=commission_r, max_trades_per_day=max_tpd,
                             context=context))
    return trades


def walk_forward(cfg: dict, datasets_dir: str, folds: int = 5,
                 min_is_trades: int = 20) -> dict:
    entry_tf = cfg["timeframes"]["entry"]
    frames = {}
    for sym in cfg["markets"]:
        try:
            df = data_mod.load_symbol(datasets_dir, sym, entry_tf)
        except FileNotFoundError:
            continue
        if len(df):
            frames[sym] = df
    if not frames:
        return {"folds": [], "error": "no data for any market"}

    tmin = min(df.index.min() for df in frames.values())
    tmax = max(df.index.max() for df in frames.values())
    edges = _time_edges(tmin, tmax, folds + 1)
    grid = _grid(cfg)
    context = datasources.build_context(cfg, datasets_dir)

    fold_records, oos_all = [], []
    for t in range(folds):
        is_lo, is_hi = edges[0], edges[t + 1]
        oos_lo, oos_hi = edges[t + 1], edges[t + 2]

        # Optimise on in-sample: best total R, disqualifying too-thin variants.
        best = None
        for overrides, variant in grid:
            m = compute(_bt_window(variant, frames, is_lo, is_hi, context))
            enough = m.get("trades", 0) >= min_is_trades
            obj = m.get("total_r", 0.0) - (0.0 if enough else 1e6)
            if best is None or obj > best[0]:
                best = (obj, overrides, variant, m)
        _, overrides, variant, is_m = best

        oos_tr = _bt_window(variant, frames, oos_lo, oos_hi, context)
        oos_m = compute(oos_tr)
        oos_all.extend(oos_tr)
        fold_records.append({
            "fold": t + 1,
            "is_range": [str(is_lo.date()), str(is_hi.date())],
            "oos_range": [str(oos_lo.date()), str(oos_hi.date())],
            "chosen": overrides,
            "is": is_m,
            "oos": oos_m,
        })

    agg = compute(oos_all)
    is_exps = [f["is"]["expectancy_r"] for f in fold_records if f["is"].get("trades")]
    oos_exps = [f["oos"]["expectancy_r"] for f in fold_records if f["oos"].get("trades")]
    mean_is = float(np.mean(is_exps)) if is_exps else 0.0
    mean_oos = float(np.mean(oos_exps)) if oos_exps else 0.0
    wfe = round(mean_oos / mean_is, 3) if mean_is > 0 else None
    consistency = round(float(np.mean(
        [1.0 if f["oos"].get("total_r", 0.0) > 0 else 0.0 for f in fold_records])), 3)

    return {
        "folds": fold_records,
        "aggregate_oos": agg,
        "walk_forward_efficiency": wfe,
        "consistency": consistency,
        "optimized": bool(cfg.get("optimize")),
    }


def render(wf: dict) -> str:
    if wf.get("error"):
        return f"WALK-FORWARD\n  ERROR: {wf['error']}\n"
    lines = [f"WALK-FORWARD  ({len(wf['folds'])} folds, "
             f"{'optimized grid' if wf['optimized'] else 'fixed params'})"]
    for f in wf["folds"]:
        im, om = f["is"], f["oos"]
        istr = (f"IS T:{im.get('trades',0):>4} PF:{im.get('profit_factor','-')} "
                f"exp:{im.get('expectancy_r','-')}R")
        ostr = (f"OOS T:{om.get('trades',0):>4} PF:{om.get('profit_factor','-')} "
                f"exp:{om.get('expectancy_r','-')}R tot:{om.get('total_r','-')}R")
        chosen = f"  {f['chosen']}" if f["chosen"] else ""
        lines.append(f"  fold {f['fold']}  {f['oos_range'][0]}->{f['oos_range'][1]}  "
                     f"{istr} | {ostr}{chosen}")
    agg = wf["aggregate_oos"]
    if agg.get("trades", 0):
        lines.append(f"  ---- concatenated OOS: T:{agg['trades']} WR:{agg['win_rate']}% "
                     f"PF:{agg['profit_factor']} exp:{agg['expectancy_r']}R "
                     f"tot:{agg['total_r']}R maxDD:{agg['max_drawdown_r']}R")
    lines.append(f"  walk-forward efficiency: {wf['walk_forward_efficiency']} "
                 f"(mean OOS exp / mean IS exp; ~1.0 good, <<1 = overfit)")
    lines.append(f"  consistency: {wf['consistency']} (fraction of folds OOS-positive)")
    return "\n".join(lines) + "\n"
