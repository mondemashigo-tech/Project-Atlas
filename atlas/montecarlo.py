"""Monte Carlo robustness on a *realised* trade sequence.

Two resampling schemes, each answering a different question:

* **bootstrap** — resample the R-multiples WITH replacement. How much did the
  result depend on the particular mix of trades we happened to get? Produces a
  distribution for total R, expectancy, profit factor and max drawdown, plus
  the probability the edge was actually negative.
* **shuffle** — PERMUTE the realised trades (no replacement). Same trades,
  random order. How much did the equity curve — especially the worst drawdown —
  depend on the lucky *ordering* of wins and losses?

Everything is in R units, so none of it depends on account size or lot sizing.
A strong in-sample backtest that still shows P(total < 0) around a coin flip is
not an edge; it is a story the sample told once."""
from __future__ import annotations

from typing import Sequence
import numpy as np

from .backtester import Trade


def _pnl_array(trades) -> np.ndarray:
    if len(trades) and isinstance(trades[0], Trade):
        return np.asarray([t.pnl_r for t in trades], dtype=float)
    return np.asarray(trades, dtype=float)


def _row_max_drawdown(samples: np.ndarray) -> np.ndarray:
    """Max drawdown per row of a (sims, n) matrix of R-multiples, off a 0 start."""
    equity = np.cumsum(samples, axis=1)
    peak = np.maximum.accumulate(equity, axis=1)
    peak = np.maximum(peak, 0.0)                 # peak can't be below the 0 start
    return (peak - equity).max(axis=1)


def _row_profit_factor(samples: np.ndarray) -> np.ndarray:
    gross_win = np.where(samples > 0, samples, 0.0).sum(axis=1)
    gross_loss = -np.where(samples < 0, samples, 0.0).sum(axis=1)
    pf = np.full(samples.shape[0], np.inf)
    nz = gross_loss > 0
    pf[nz] = gross_win[nz] / gross_loss[nz]
    pf[(~nz) & (gross_win == 0)] = 0.0
    return pf


def _bands(x: np.ndarray, ps=(5, 25, 50, 75, 95)) -> dict:
    x = x[np.isfinite(x)]
    if len(x) == 0:
        return {f"p{p}": None for p in ps}
    return {f"p{p}": round(float(np.percentile(x, p)), 3) for p in ps}


def bootstrap(pnl, n_sims: int = 5000, seed: int = 7) -> dict:
    r = _pnl_array(pnl)
    n = len(r)
    rng = np.random.default_rng(seed)
    samples = r[rng.integers(0, n, size=(n_sims, n))]   # (n_sims, n), with replacement
    totals = samples.sum(axis=1)
    expect = samples.mean(axis=1)
    pf = _row_profit_factor(samples)
    dd = _row_max_drawdown(samples)
    return {
        "n_trades": n,
        "n_sims": n_sims,
        "total_r": _bands(totals),
        "expectancy_r": _bands(expect),
        "profit_factor": _bands(pf),
        "max_drawdown_r": _bands(dd),
        "p_total_negative": round(float((totals < 0).mean()), 4),
        "p_expectancy_negative": round(float((expect < 0).mean()), 4),
    }


def shuffle_drawdown(pnl, n_sims: int = 5000, seed: int = 7) -> dict:
    r = _pnl_array(pnl)
    n = len(r)
    rng = np.random.default_rng(seed)
    order = rng.random((n_sims, n)).argsort(axis=1)      # random permutation per row
    samples = r[order]
    dd = _row_max_drawdown(samples)
    realised = float(_row_max_drawdown(r.reshape(1, -1))[0])
    return {
        "realised_max_drawdown_r": round(realised, 3),
        "max_drawdown_r": _bands(dd),
        "p_worse_than_realised": round(float((dd >= realised).mean()), 4),
    }


def analyze(trades, n_sims: int = 5000, seed: int = 7) -> dict:
    r = _pnl_array(trades)
    if len(r) == 0:
        return {"trades": 0}
    return {
        "trades": int(len(r)),
        "bootstrap": bootstrap(r, n_sims, seed),
        "shuffle": shuffle_drawdown(r, n_sims, seed),
    }


def render(mc: dict) -> str:
    if not mc or mc.get("trades", 0) == 0:
        return "MONTE CARLO\n  NO TRADES\n"
    b, s = mc["bootstrap"], mc["shuffle"]

    def band(d):
        return f"p5 {d['p5']}  p50 {d['p50']}  p95 {d['p95']}"

    lines = [
        f"MONTE CARLO  ({b['n_sims']} sims on {mc['trades']} trades)",
        "  bootstrap (resample trades WITH replacement):",
        f"    total R         {band(b['total_r'])}",
        f"    expectancy R    {band(b['expectancy_r'])}",
        f"    profit factor   {band(b['profit_factor'])}",
        f"    max drawdown R  {band(b['max_drawdown_r'])}",
        f"    P(total < 0)          {b['p_total_negative']}",
        f"    P(expectancy < 0)     {b['p_expectancy_negative']}",
        "  shuffle (same trades, random order):",
        f"    realised max DD       {s['realised_max_drawdown_r']}R",
        f"    max drawdown R        {band(s['max_drawdown_r'])}",
        f"    P(DD >= realised)     {s['p_worse_than_realised']}",
    ]
    return "\n".join(lines) + "\n"
