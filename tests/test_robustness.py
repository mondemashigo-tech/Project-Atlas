"""Phase 2 robustness tests: Monte Carlo resampling and walk-forward analysis.
All on synthetic data — no MT5, no real dataset."""
import os
import tempfile

import numpy as np
import pandas as pd

from atlas import montecarlo as mc
from atlas import walkforward as wf
from atlas.strategies import trend_continuation  # noqa: registers template


# ---- Monte Carlo -----------------------------------------------------------

def test_mc_positive_edge_low_ruin_prob():
    # A clearly positive edge (mostly +2R wins, some -1R losses) should almost
    # never bootstrap to a negative total.
    rng = np.random.default_rng(0)
    pnl = np.where(rng.random(400) < 0.5, 2.0, -1.0)  # +0.5R expectancy
    out = mc.analyze(pnl, n_sims=2000, seed=1)
    assert out["trades"] == 400
    assert out["bootstrap"]["p_total_negative"] < 0.02
    assert out["bootstrap"]["expectancy_r"]["p5"] > 0     # even the 5th pct is +ve


def test_mc_no_edge_is_a_coin_flip():
    # An exactly balanced realised sample (equal +1R and -1R) has zero
    # expectancy; bootstrap totals are symmetric about 0, so P(total < 0) must
    # sit near a coin flip rather than being masked as a win.
    pnl = [1.0, -1.0] * 200  # 400 trades, total exactly 0
    out = mc.analyze(pnl, n_sims=4000, seed=3)
    assert 0.35 < out["bootstrap"]["p_total_negative"] < 0.55


def test_mc_deterministic_with_seed():
    pnl = [1.0, -1.0, 2.0, -1.0, 0.5, -1.0, 1.5]
    a = mc.analyze(pnl, n_sims=500, seed=42)
    b = mc.analyze(pnl, n_sims=500, seed=42)
    assert a == b
    assert "MONTE CARLO" in mc.render(a)


def test_mc_empty():
    assert mc.analyze([]) == {"trades": 0}
    assert "NO TRADES" in mc.render({"trades": 0})


# ---- Walk-forward ----------------------------------------------------------

def _write_synth(datasets_dir, symbol="GBPUSD", n=20000, seed=1):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2022-01-03 00:00", periods=n, freq="5min", tz="UTC")
    steps = rng.normal(0.00004, 0.0008, n).cumsum()
    close = 1.30 + steps
    high = close + np.abs(rng.normal(0, 0.0004, n))
    low = close - np.abs(rng.normal(0, 0.0004, n))
    open_ = np.concatenate([[close[0]], close[:-1]])
    # ISO timestamps: resolution-agnostic across pandas versions (3.0 defaults
    # DatetimeIndex to microseconds, so epoch-integer math would misconvert).
    df = pd.DataFrame({"time": idx.astype(str),
                       "open": open_, "high": high, "low": low, "close": close})
    os.makedirs(datasets_dir, exist_ok=True)
    df.to_csv(os.path.join(datasets_dir, f"{symbol}_M5.csv"), index=False)


CFG = {
    "name": "wf_test",
    "template": "trend_continuation",
    "markets": ["GBPUSD"],
    "timeframes": {"bias": "H1", "entry": "M5"},
    "session": {"start": "00:00", "end": "23:59", "tz": "UTC"},
    "weekdays": [0, 1, 2, 3, 4],
    "trend": {"ema_fast": 50, "ema_slow": 200},
    "entry": {"pullback_ema": 20},
    "risk": {"stop": {"atr_mult": 1.0, "atr_period": 14, "swing_lookback": 20},
             "target_r": 2.0, "max_trades_per_day": 3},
    "costs": {"spread_pips": 1.0, "commission_r": 0.03},
    "criteria": {"success": {}, "failure": {}},
    "data": {"in_sample": ["2022-01-01", "2022-12-31"],
             "out_sample": ["2023-01-01", "2023-12-31"]},
}


def test_walk_forward_runs_and_structures():
    with tempfile.TemporaryDirectory() as d:
        _write_synth(d)
        out = wf.walk_forward(CFG, d, folds=3, min_is_trades=5)
        assert len(out["folds"]) == 3
        # OOS windows must be strictly forward of their IS windows.
        for f in out["folds"]:
            assert f["oos_range"][0] >= f["is_range"][1]
        assert "aggregate_oos" in out
        assert "consistency" in out
        assert "WALK-FORWARD" in wf.render(out)


def test_walk_forward_grid_selects_a_variant():
    cfg = dict(CFG, optimize={"risk.target_r": [1.5, 2.0, 3.0]})
    with tempfile.TemporaryDirectory() as d:
        _write_synth(d)
        out = wf.walk_forward(cfg, d, folds=2, min_is_trades=5)
        assert out["optimized"] is True
        # Every fold must have recorded a chosen target_r from the grid.
        for f in out["folds"]:
            assert f["chosen"].get("risk.target_r") in (1.5, 2.0, 3.0)
