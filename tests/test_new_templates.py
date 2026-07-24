"""Tests for the Phase-5 strategy templates: mean_reversion and breakout.
Each is exercised on synthetic data matched to its premise. Synthetic only."""
import numpy as np
import pandas as pd

from atlas.research.fx.backtester import run
from atlas.research.fx.config import load
from atlas.research.fx.strategies.base import Strategy
import atlas.research.fx.strategies  # noqa: registers all templates


def _mean_reverting(n=8000, seed=1):
    """AR(1) around a fixed level -> price repeatedly stretches then reverts."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2025-04-01", periods=n, freq="5min", tz="UTC")
    x = np.zeros(n)
    for t in range(1, n):
        x[t] = 0.92 * x[t - 1] + rng.normal(0, 0.0006)
    close = 1.30 + x
    high = close + np.abs(rng.normal(0, 0.0002, n))
    low = close - np.abs(rng.normal(0, 0.0002, n))
    open_ = np.concatenate([[close[0]], close[:-1]])
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close}, index=idx)


def _trending(n=8000, seed=2):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2025-04-01", periods=n, freq="5min", tz="UTC")
    close = 1.30 + rng.normal(0.00015, 0.0006, n).cumsum()
    high = close + np.abs(rng.normal(0, 0.0003, n))
    low = close - np.abs(rng.normal(0, 0.0003, n))
    open_ = np.concatenate([[close[0]], close[:-1]])
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close}, index=idx)


_RISK = {"stop": {"atr_mult": 1.5, "atr_period": 14}, "target_r": 1.5,
         "max_trades_per_day": 5}


def test_mean_reversion_trades_and_valid_signals():
    cfg = {"template": "mean_reversion", "timeframes": {"entry": "M5"},
           "weekdays": [0, 1, 2, 3, 4], "meanrev": {"ma_period": 20, "entry_z": 2.0,
           "exit": "mean"}, "risk": _RISK}
    strat = Strategy.create(cfg)
    trades = run("GBPUSD", _mean_reverting(), strat, max_trades_per_day=5)
    assert len(trades) > 0
    for t in trades:
        if t.direction == "BUY":
            assert t.stop < t.entry < t.target
        else:
            assert t.target < t.entry < t.stop


def test_breakout_trades_and_valid_signals():
    cfg = {"template": "breakout", "timeframes": {"entry": "M5"},
           "weekdays": [0, 1, 2, 3, 4], "breakout": {"channel": 20}, "risk": _RISK}
    strat = Strategy.create(cfg)
    trades = run("GBPUSD", _trending(), strat, max_trades_per_day=5)
    assert len(trades) > 0
    for t in trades:
        if t.direction == "BUY":
            assert t.stop < t.entry < t.target
        else:
            assert t.target < t.entry < t.stop


def test_new_hypotheses_parse_and_build():
    for path in ("hypotheses/meanrev_zscore.yaml", "hypotheses/donchian_breakout.yaml"):
        cfg = load(path)
        strat = Strategy.create(cfg)
        assert strat is not None
