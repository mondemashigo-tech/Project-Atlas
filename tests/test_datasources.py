"""Phase 4 tests: carry (rate differential) + economic-calendar news filter.
Loaders, both filters in isolation, and an integration check that a filter
actually changes the trade set. Synthetic data only."""
import os
import tempfile

import numpy as np
import pandas as pd

from atlas.research.fx import datasources as ds
from atlas.research.fx import runner
from atlas.research.fx.filters import CarryFilter, NewsFilter, build
from atlas.research.fx.strategies import trend_continuation  # noqa: registers template


def _write_prices(datasets_dir, symbol="GBPUSD", n=30000, seed=1):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2022-01-03 00:00", periods=n, freq="5min", tz="UTC")
    close = 1.30 + rng.normal(0.00005, 0.0008, n).cumsum()
    high = close + np.abs(rng.normal(0, 0.0004, n))
    low = close - np.abs(rng.normal(0, 0.0004, n))
    open_ = np.concatenate([[close[0]], close[:-1]])
    os.makedirs(datasets_dir, exist_ok=True)
    pd.DataFrame({"time": idx.astype(str), "open": open_, "high": high,
                  "low": low, "close": close}).to_csv(
        os.path.join(datasets_dir, f"{symbol}_M5.csv"), index=False)
    return idx


# ---- loaders + rate_asof ---------------------------------------------------

def test_rates_load_and_asof_no_lookahead():
    with tempfile.TemporaryDirectory() as d:
        pd.DataFrame({"time": ["2022-01-01", "2022-06-01"],
                      "currency": ["USD", "USD"], "rate": [0.25, 2.0]}).to_csv(
            os.path.join(d, "rates.csv"), index=False)
        rates = ds.load_rates(d)
        assert ds.rate_asof(rates, "USD", pd.Timestamp("2022-03-01", tz="UTC")) == 0.25
        assert ds.rate_asof(rates, "USD", pd.Timestamp("2022-07-01", tz="UTC")) == 2.0
        # Before the first observation -> None (no look-ahead / no guessing).
        assert ds.rate_asof(rates, "USD", pd.Timestamp("2021-01-01", tz="UTC")) is None


def test_calendar_load_and_rank():
    with tempfile.TemporaryDirectory() as d:
        pd.DataFrame({"time": ["2022-01-04 09:00", "2022-01-04 12:00"],
                      "currency": ["usd", "gbp"], "impact": ["High", "low"]}).to_csv(
            os.path.join(d, "calendar.csv"), index=False)
        cal = ds.load_calendar(d)
        assert list(cal["rank"]) == [3, 1]
        assert cal["currency"].tolist() == ["USD", "GBP"]


# ---- carry filter ----------------------------------------------------------

def test_carry_filter_alignment():
    rates = {"GBP": pd.DataFrame({"time": pd.to_datetime(["2022-01-01"], utc=True), "rate": [1.0]}),
             "USD": pd.DataFrame({"time": pd.to_datetime(["2022-01-01"], utc=True), "rate": [0.25]})}
    f = CarryFilter(rates, require_aligned=True)
    ts = pd.Timestamp("2022-02-01", tz="UTC")
    assert f.allows("GBPUSD", "BUY", ts) is True     # base out-yields quote
    assert f.allows("GBPUSD", "SELL", ts) is False
    # Missing data -> abstain (allow), never guess.
    assert CarryFilter({}, True).allows("GBPUSD", "SELL", ts) is True


# ---- news filter -----------------------------------------------------------

def test_news_filter_blackout_window():
    cal = pd.DataFrame({"time": pd.to_datetime(["2022-01-04 09:00"], utc=True),
                        "currency": ["USD"], "impact": ["high"], "rank": [3]})
    f = NewsFilter(cal, "GBPUSD", before_min=30, after_min=30, min_impact="high")
    assert f.blocks(pd.Timestamp("2022-01-04 09:15", tz="UTC")) is True   # inside
    assert f.blocks(pd.Timestamp("2022-01-04 08:45", tz="UTC")) is True   # 15m before
    assert f.blocks(pd.Timestamp("2022-01-04 08:00", tz="UTC")) is False  # >30m before
    assert f.blocks(pd.Timestamp("2022-01-04 10:00", tz="UTC")) is False  # >30m after
    # A low-impact-only calendar should never block a high-impact filter.
    low = pd.DataFrame({"time": pd.to_datetime(["2022-01-04 09:00"], utc=True),
                        "currency": ["USD"], "impact": ["low"], "rank": [1]})
    assert NewsFilter(low, "GBPUSD", min_impact="high").blocks(
        pd.Timestamp("2022-01-04 09:00", tz="UTC")) is False


def test_build_returns_none_when_disabled():
    carry, news = build({}, {}, "GBPUSD")
    assert carry is None and news is None
    carry, news = build({"carry": {"require_aligned": True},
                         "news_filter": {"enabled": True}}, {"rates": None, "calendar": None},
                        "GBPUSD")
    assert carry is not None and news is not None


# ---- integration: a filter must actually change the trade set ---------------

_CFG = {
    "name": "ds_test", "template": "trend_continuation", "markets": ["GBPUSD"],
    "timeframes": {"bias": "H1", "entry": "M5"},
    "session": {"start": "00:00", "end": "23:59", "tz": "UTC"},
    "weekdays": [0, 1, 2, 3, 4],
    "trend": {"ema_fast": 50, "ema_slow": 200}, "entry": {"pullback_ema": 20},
    "risk": {"stop": {"atr_mult": 1.0, "atr_period": 14, "swing_lookback": 20},
             "target_r": 2.0, "max_trades_per_day": 3},
    "costs": {"spread_pips": 1.0, "commission_r": 0.03},
    "criteria": {"success": {}, "failure": {}},
    "data": {"in_sample": ["2022-01-01", "2022-12-31"],
             "out_sample": ["2022-01-01", "2022-12-31"]},
}


def test_news_filter_reduces_trades_end_to_end():
    with tempfile.TemporaryDirectory() as d:
        datasets = os.path.join(d, "datasets")
        idx = _write_prices(datasets)
        base = runner.run_full(dict(_CFG), datasets)["metrics"]["trades"]
        # A dense high-impact USD calendar (every day, 08:00) blacking out a big
        # slice of each session must reduce the number of trades.
        days = pd.date_range("2022-01-03", "2023-01-01", freq="D", tz="UTC")
        pd.DataFrame({"time": [f"{day.date()} 08:00" for day in days],
                      "currency": "USD", "impact": "high"}).to_csv(
            os.path.join(datasets, "calendar.csv"), index=False)
        cfg = dict(_CFG, news_filter={"enabled": True, "block_minutes_before": 240,
                                      "block_minutes_after": 240, "min_impact": "high"})
        filtered = runner.run_full(cfg, datasets)["metrics"]["trades"]
        assert base > 0
        assert filtered < base
