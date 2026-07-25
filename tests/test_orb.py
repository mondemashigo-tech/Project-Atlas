"""ORB (Opening Range Breakout) template test on constructed session data."""
import numpy as np
import pandas as pd

from atlas.research.fx.backtester import run
from atlas.research.fx.strategies.base import Strategy
import atlas.research.fx.strategies  # noqa: registers templates
from atlas.research.fx.config import load


def _session_days(days=6, up=True):
    """M5 bars, 09:30–16:00 UTC, each day: a tight opening candle then a steady
    trend that closes beyond the opening range."""
    frames = []
    start = pd.Timestamp("2024-01-01", tz="UTC")
    d = 0
    made = 0
    while made < days:
        day = start + pd.Timedelta(days=d)
        d += 1
        if day.weekday() >= 5:
            continue
        made += 1
        idx = pd.date_range(day + pd.Timedelta(hours=9, minutes=30),
                            day + pd.Timedelta(hours=15, minutes=55), freq="5min")
        n = len(idx)
        base = 100.0
        drift = np.linspace(0, 2.0 if up else -2.0, n)
        close = base + drift
        # opening candle tight range around base
        high = close + 0.05
        low = close - 0.05
        high[0] = base + 0.2
        low[0] = base - 0.2
        open_ = np.concatenate([[close[0]], close[:-1]])
        frames.append(pd.DataFrame({"open": open_, "high": high, "low": low,
                                    "close": close}, index=idx))
    return pd.concat(frames)


_CFG = {
    "template": "orb", "timeframes": {"entry": "M5"},
    "session": {"start": "09:30", "end": "16:00", "tz": "UTC"},
    "weekdays": [0, 1, 2, 3, 4],
    "orb": {"range_minutes": 5, "ema": 20},
    "risk": {"stop": {"type": "opposite_range", "atr_period": 14},
             "target_r": 2.0, "max_trades_per_day": 1},
}


def test_orb_long_breakouts_and_no_lookahead():
    strat = Strategy.create(_CFG)
    trades = run("SPY", _session_days(up=True), strat, spread_pips=0.0,
                 max_trades_per_day=1)
    assert len(trades) > 0
    for t in trades:
        assert t.direction == "BUY"                 # uptrend days -> long only
        assert t.stop < t.entry < t.target          # stop at range low, target above
        # entry must be AFTER the opening range (09:35+), never inside it
        assert pd.Timestamp(t.entry_time).minute != 30 or \
            pd.Timestamp(t.entry_time).hour != 9


def test_orb_one_trade_per_day():
    strat = Strategy.create(_CFG)
    trades = run("SPY", _session_days(days=5, up=True), strat, spread_pips=0.0,
                 max_trades_per_day=1)
    days = {pd.Timestamp(t.entry_time).date() for t in trades}
    assert len(days) == len(trades)                 # at most one entry per day


def test_orb_hypothesis_parses_and_builds():
    cfg = load("hypotheses/orb_us_equity.yaml")
    strat = Strategy.create(cfg)
    assert strat is not None and cfg["template"] == "orb"
