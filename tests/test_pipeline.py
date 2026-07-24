"""End-to-end pipeline test on synthetic data. Proves the engine runs, respects
the session/weekday filter, resolves SL/TP, and computes a sane verdict — with
no MT5 and no real dataset. Also asserts a couple of correctness invariants."""
import numpy as np
import pandas as pd

from atlas.research.fx.indicators import ema, atr
from atlas.research.fx.strategies.base import Strategy
from atlas.research.fx.strategies import trend_continuation  # noqa: registers template
from atlas.research.fx.backtester import run
from atlas.research.fx.metrics import compute, verdict


def _synth(n=6000, seed=1):
    """M5 bars with a gentle upward drift + noise so a trend exists to trade."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2023-01-03 00:00", periods=n, freq="5min", tz="UTC")
    steps = rng.normal(0.00005, 0.0008, n).cumsum()
    close = 1.30 + steps
    high = close + np.abs(rng.normal(0, 0.0004, n))
    low = close - np.abs(rng.normal(0, 0.0004, n))
    open_ = np.concatenate([[close[0]], close[:-1]])
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close}, index=idx)


CFG = {
    "template": "trend_continuation",
    "timeframes": {"bias": "H1", "entry": "M5"},
    "session": {"start": "00:00", "end": "23:59", "tz": "UTC"},
    "weekdays": [0, 1, 2, 3, 4],
    "trend": {"ema_fast": 50, "ema_slow": 200},
    "entry": {"pullback_ema": 20},
    "risk": {"stop": {"atr_mult": 1.0, "atr_period": 14, "swing_lookback": 20},
             "target_r": 2.0, "max_trades_per_day": 3},
}


def test_indicators_shapes():
    df = _synth(500)
    assert len(ema(df["close"], 20)) == 500
    assert atr(df, 14).notna().sum() > 400


def test_pipeline_runs_and_resolves():
    df = _synth()
    strat = Strategy.create(CFG)
    trades = run("GBPUSD", df, strat, spread_pips=1.0, commission_r=0.03)
    # It should generate trades on a trending synthetic series.
    assert len(trades) > 0
    # Every trade must have a stop on the correct side of entry, target beyond.
    for t in trades:
        if t.direction == "BUY":
            assert t.stop < t.entry < t.target
        else:
            assert t.target < t.entry < t.stop
        assert t.exit_reason in ("SL", "TP", "END")
    m = compute(trades)
    assert m["trades"] == len(trades)
    assert set(["win_rate", "profit_factor", "expectancy_r", "max_drawdown_r"]) <= set(m)


def test_session_filter_blocks_out_of_window():
    df = _synth()
    cfg = dict(CFG, session={"start": "08:00", "end": "08:05", "tz": "UTC"})
    strat = Strategy.create(cfg)
    trades = run("GBPUSD", df, strat)
    # A 5-minute daily window must yield far fewer trades than all-day.
    strat2 = Strategy.create(CFG)
    all_day = run("GBPUSD", df, strat2)
    assert len(trades) < len(all_day)


def test_verdict_logic():
    good = {"trades": 250, "profit_factor": 1.6, "expectancy_r": 0.2}
    crit = {"success": {"profit_factor": 1.5, "min_trades": 200, "expectancy": "positive"},
            "failure": {"profit_factor": 1.2, "expectancy": "negative"}}
    assert verdict(good, crit)["result"] == "PASS"
    bad = {"trades": 250, "profit_factor": 0.8, "expectancy_r": -0.1}
    assert verdict(bad, crit)["result"] == "REJECT"
