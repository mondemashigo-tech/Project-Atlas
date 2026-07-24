"""Grid-search optimiser with an honesty guard.

Searches the ``optimize:`` grid on IN-SAMPLE data, ranks configurations by an
in-sample objective, then reports each one's OUT-OF-SAMPLE result alongside it.
The point is to make overfitting *visible*: a row that tops the in-sample table
and then collapses out-of-sample was tuned to noise. The optimiser NEVER ranks
on out-of-sample — that column is the verdict, never the selection signal.
"""
from __future__ import annotations

from typing import Dict

from . import data as data_mod
from . import splits
from .paramgrid import expand
from .strategies.base import Strategy
from .backtester import run as run_bt
from .metrics import compute


def _bt(cfg: dict, datasets_dir: str, slicer) -> list:
    entry_tf = cfg["timeframes"]["entry"]
    spread = cfg.get("costs", {}).get("spread_pips", 1.0)
    commission_r = cfg.get("costs", {}).get("commission_r", 0.0)
    max_tpd = cfg["risk"].get("max_trades_per_day", 3)
    trades = []
    for sym in cfg["markets"]:
        try:
            df = data_mod.load_symbol(datasets_dir, sym, entry_tf)
        except FileNotFoundError:
            continue
        w = slicer(df, cfg)
        if len(w) < 300:
            continue
        strat = Strategy.create(cfg)
        trades.extend(run_bt(sym, w, strat, spread_pips=spread,
                             commission_r=commission_r, max_trades_per_day=max_tpd))
    return trades


def optimize(cfg: dict, datasets_dir: str, objective: str = "total_r",
             min_trades: int = 30) -> Dict:
    rows = []
    for overrides, variant in expand(cfg):
        is_m = compute(_bt(variant, datasets_dir, splits.in_sample))
        oos_m = compute(_bt(variant, datasets_dir, splits.out_sample))
        rows.append({"params": overrides, "is": is_m, "oos": oos_m})

    def rank_key(r):
        m = r["is"]
        if m.get("trades", 0) < min_trades:
            return float("-inf")
        return m.get(objective, float("-inf"))

    rows.sort(key=rank_key, reverse=True)
    best = rows[0] if rows else None
    gap = None
    if best and best["is"].get("trades") and best["oos"].get("trades"):
        gap = round(best["is"]["expectancy_r"] - best["oos"]["expectancy_r"], 4)
    return {"objective": objective, "min_trades": min_trades,
            "n_configs": len(rows), "rows": rows, "best": best, "overfit_gap": gap}


def render(opt: dict) -> str:
    lines = [f"OPTIMISER  ({opt['n_configs']} configs, ranked by IS {opt['objective']}, "
             f"min {opt['min_trades']} IS trades)"]
    width = max([46] + [len(str(r["params"])) for r in opt["rows"]])
    lines.append(f"  {'rank':>4}  {'params':{width}}  {'IS':>26}  {'OOS':>26}")
    for i, r in enumerate(opt["rows"], 1):
        im, om = r["is"], r["oos"]
        pstr = str(r["params"]) if r["params"] else "(base)"

        def cell(m):
            if not m.get("trades"):
                return "  -- no trades --"
            return f"T{m['trades']:>4} PF{m['profit_factor']:>5} exp{m['expectancy_r']:>7}"
        lines.append(f"  {i:>4}  {pstr:{width}}  {cell(im):>26}  {cell(om):>26}")
    if opt["overfit_gap"] is not None:
        flag = "  <-- large IS/OOS gap, suspect overfit" if opt["overfit_gap"] > 0.15 else ""
        lines.append(f"  best IS/OOS expectancy gap: {opt['overfit_gap']}R{flag}")
    lines.append("  NOTE: selection is on IN-SAMPLE only; OOS is reported, never optimised.")
    return "\n".join(lines) + "\n"
