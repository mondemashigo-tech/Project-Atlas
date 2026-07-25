"""Portfolio-level analysis.

Given several strategies' realised trades (Trade objects with `entry_time` and
`pnl_r`), align them to daily R-returns and measure: pairwise correlation (do they
fail together?), the combined equity/drawdown (is the book smoother than its
parts?), and per-strategy contribution. A small edge with low correlation can beat
a bigger but redundant one (Volume 2 §5.8).
"""
from __future__ import annotations

from typing import Dict, List

import numpy as np
import pandas as pd

from ..agents.base import Agent, AgentContext
from ..schemas import DecisionRecord


def daily_returns(trades: List) -> pd.Series:
    """Sum trade P/L (R) by entry date -> a daily return series."""
    if not trades:
        return pd.Series(dtype=float)
    rows = [(pd.Timestamp(t.entry_time).normalize(), t.pnl_r) for t in trades]
    s = pd.DataFrame(rows, columns=["day", "r"]).groupby("day")["r"].sum()
    s.index = s.index.tz_localize(None) if s.index.tz is not None else s.index
    return s


def _max_dd(equity: np.ndarray) -> float:
    peak = np.maximum.accumulate(np.concatenate([[0.0], equity]))[1:]
    return float(np.max(peak - equity)) if len(equity) else 0.0


def analyze(strat_trades: Dict[str, List]) -> dict:
    series = {k: daily_returns(v) for k, v in strat_trades.items()}
    series = {k: s for k, s in series.items() if len(s)}
    if not series:
        return {"strategies": 0}
    frame = pd.DataFrame(series).fillna(0.0).sort_index()
    corr = frame.corr().round(3) if frame.shape[1] > 1 else pd.DataFrame()
    combined = frame.sum(axis=1)
    combined_eq = combined.cumsum().to_numpy()
    per = {}
    for k in frame.columns:
        eq = frame[k].cumsum().to_numpy()
        per[k] = {"total_r": round(float(frame[k].sum()), 2),
                  "max_drawdown_r": round(_max_dd(eq), 2)}
    # average absolute off-diagonal correlation (0 = perfectly diversified)
    avg_corr = None
    if not corr.empty:
        m = corr.to_numpy()
        off = m[~np.eye(m.shape[0], dtype=bool)]
        avg_corr = round(float(np.mean(np.abs(off))), 3)
    return {
        "strategies": frame.shape[1],
        "combined_total_r": round(float(combined.sum()), 2),
        "combined_max_drawdown_r": round(_max_dd(combined_eq), 2),
        "avg_abs_correlation": avg_corr,
        "correlation": corr.to_dict() if not corr.empty else {},
        "per_strategy": per,
    }


def render(a: dict) -> str:
    if a.get("strategies", 0) == 0:
        return "PORTFOLIO\n  no strategies\n"
    lines = [f"PORTFOLIO ({a['strategies']} strategies)",
             f"  combined total {a['combined_total_r']}R | "
             f"combined maxDD {a['combined_max_drawdown_r']}R | "
             f"avg |corr| {a['avg_abs_correlation']}"]
    for k, m in a["per_strategy"].items():
        lines.append(f"  {k:20} total {m['total_r']}R  maxDD {m['max_drawdown_r']}R")
    return "\n".join(lines) + "\n"


class PortfolioBuilder(Agent):
    """Layer-6 gate. For a lone strategy it trivially diversifies; with peers it
    flags high correlation (fails together)."""
    name = "PortfolioBuilder"
    nature = "code"

    def __init__(self, peers: Dict[str, List] = None, max_corr: float = 0.8,
                 narrator=None):
        super().__init__(narrator)
        self.peers = peers or {}
        self.max_corr = max_corr

    def run(self, ctx: AgentContext) -> DecisionRecord:
        this_trades = ctx.extras.get("trades", [])
        if not self.peers:
            return self._record(ctx, "portfolio_validity", "pass",
                                "first strategy — trivially diversifying",
                                confidence="medium", next_action="deployment (human gate)")
        book = dict(self.peers)
        book[ctx.hypothesis.id] = this_trades
        a = analyze(book)
        ac = a.get("avg_abs_correlation")
        if ac is not None and ac > self.max_corr:
            return self._record(ctx, "portfolio_validity", "veto",
                                f"avg |corr| {ac} > {self.max_corr} — redundant/fails together",
                                confidence="high", next_action="prefer a less correlated edge")
        return self._record(ctx, "portfolio_validity", "pass",
                            f"avg |corr| {ac}; combined maxDD {a['combined_max_drawdown_r']}R",
                            confidence="medium", next_action="deployment (human gate)")
