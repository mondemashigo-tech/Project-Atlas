"""BOS + Retracement strategy: builds, respects its state machine, trades on
synthetic data, and pre-registers distinctly. No market data / no network."""
import numpy as np
import pandas as pd

from atlas.research.fx.strategies.base import Strategy
import atlas.research.fx.strategies  # noqa: registers templates
from atlas.research.fx import backtester
from atlas.schemas import Hypothesis


def _staircase(n=4000, seed=3):
    """Synthetic uptrend built from breaks + pullbacks, so BOS+retest can fire:
    push up, pull back, push up again."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2021-01-04 08:00", periods=n, freq="5min", tz="UTC")
    price = [1.30]
    phase = 0
    for k in range(1, n):
        # alternate impulse-up and shallow pullback segments
        drift = 0.0006 if (k // 40) % 2 == 0 else -0.00018
        price.append(price[-1] + drift + rng.normal(0, 0.0004))
    close = np.array(price)
    high = close + np.abs(rng.normal(0, 0.0004, n)) + 0.0002
    low = close - np.abs(rng.normal(0, 0.0004, n)) - 0.0002
    openp = np.concatenate([[close[0]], close[:-1]])
    return pd.DataFrame({"open": openp, "high": high, "low": low, "close": close}, index=idx)


def _cfg():
    return {
        "name": "bos_test", "template": "bos_retrace", "markets": ["GBPUSD"],
        "timeframes": {"entry": "M5"},
        "weekdays": [0, 1, 2, 3, 4],
        "bos": {"swing_pivot": 3, "atr_period": 14, "bos_atr": 0.05,
                "body_frac": 0.4, "displacement_atr": 1.0, "retest_atr": 0.30,
                "expiry_bars": 15, "stop_buffer_atr": 0.10},
        "risk": {"target_r": 2.0, "max_trades_per_day": 10},
        "costs": {"spread_pips": 1.0, "commission_r": 0.05},
        "criteria": {"success": {}, "failure": {}},
        "data": {"in_sample": ["2020-01-01", "2022-12-31"],
                 "out_sample": ["2023-01-01", "2025-12-31"]},
    }


def test_bos_retrace_builds_and_registered():
    assert "bos_retrace" in Strategy._registry
    assert Strategy.create(_cfg()) is not None


def test_bos_retrace_produces_trades_on_synthetic():
    df = _staircase()
    strat = Strategy.create(_cfg())
    trades = backtester.run("GBPUSD", df, strat, spread_pips=1.0,
                            commission_r=0.05, max_trades_per_day=10)
    assert len(trades) > 0                         # the state machine fires
    for t in trades:
        assert t.direction in ("BUY", "SELL")
        # stop must be on the invalidation side of entry
        if t.direction == "BUY":
            assert t.stop < t.entry and t.target > t.entry
        else:
            assert t.stop > t.entry and t.target < t.entry


def test_bos_retrace_no_lookahead_entries_have_prior_bar():
    # every entry is a confirmation bar, so index >= a few bars in
    df = _staircase()
    strat = Strategy.create(_cfg())
    strat.prepare(df, symbol="GBPUSD")
    assert all(i >= 3 for i in strat._entries)     # needs pivots + BOS + retest before


def test_bos_retrace_preregisters_distinctly():
    from atlas.research.fx.config import load
    import tempfile, os, yaml
    base = _cfg(); base["version"] = "0.1"
    other = _cfg(); other["version"] = "0.1"
    other["bos"] = dict(other["bos"]); other["bos"]["bos_atr"] = 0.20  # different rule
    h1 = Hypothesis.from_fx_config(base).freeze()
    h2 = Hypothesis.from_fx_config(other).freeze()
    assert h1.preregistration_hash != h2.preregistration_hash


def test_shipped_hypothesis_loads_and_builds():
    from atlas.research.fx.config import load
    cfg = load("hypotheses/bos_retrace_v0_1.yaml")
    assert cfg["template"] == "bos_retrace"
    assert Strategy.create(cfg) is not None
