"""Milestone 2 tests: HistData importer, DataSnapshot provenance, regime breakdown."""
import os
import tempfile

import numpy as np
import pandas as pd

from atlas.research.fx import histdata, regime
from atlas.research.fx.data import load_symbol
from atlas.research.fx.backtester import run
from atlas.research.fx.strategies.base import Strategy
import atlas.research.fx.strategies  # noqa: registers templates
from atlas.snapshots import make_snapshot
from atlas.memory import MemoryStore


# ---- HistData importer -----------------------------------------------------

def test_histdata_import_est_to_utc():
    with tempfile.TemporaryDirectory() as d:
        raw = os.path.join(d, "DAT_ASCII_GBPUSD_M1_2023.csv")
        # 17:00:00 EST on 2023-01-02 == 22:00:00 UTC.
        with open(raw, "w") as f:
            f.write("20230102 170000;1.20000;1.20050;1.19990;1.20010;0\n")
            f.write("20230102 170100;1.20010;1.20080;1.20000;1.20070;0\n")
        out = histdata.import_histdata(raw, os.path.join(d, "datasets"), "GBPUSD")
        df = load_symbol(os.path.join(d, "datasets"), "GBPUSD", "M1")
        assert len(df) == 2
        assert str(df.index[0]) == "2023-01-02 22:00:00+00:00"   # EST->UTC (+5h)
        assert abs(df["close"].iloc[0] - 1.20010) < 1e-9


def test_histdata_import_then_resample_to_m5():
    with tempfile.TemporaryDirectory() as d:
        raw = os.path.join(d, "hd.csv")
        rows = []
        base = pd.Timestamp("2023-01-03 09:30")
        for i in range(60):                       # 60 M1 bars
            t = (base + pd.Timedelta(minutes=i)).strftime("%Y%m%d %H%M%S")
            rows.append(f"{t};1.20000;1.20050;1.19990;1.20010;0")
        with open(raw, "w") as f:
            f.write("\n".join(rows) + "\n")
        datasets = os.path.join(d, "datasets")
        histdata.import_histdata(raw, datasets, "GBPUSD")
        from atlas.research.fx.data import load_csv, resample
        m1 = load_csv(os.path.join(datasets, "GBPUSD_M1.csv"))
        r = resample(m1, "M5")
        r.reset_index().to_csv(os.path.join(datasets, "GBPUSD_M5.csv"), index=False)
        m5 = load_symbol(datasets, "GBPUSD", "M5")
        assert len(m5) == 12                       # 60 M1 -> 12 M5
        assert list(m5.columns) == ["open", "high", "low", "close"]


def test_histdata_dedup_and_sort():
    with tempfile.TemporaryDirectory() as d:
        raw = os.path.join(d, "a.csv")
        with open(raw, "w") as f:
            f.write("20230102 170100;1;1;1;1;0\n")   # out of order + dup below
            f.write("20230102 170000;1;1;1;1;0\n")
            f.write("20230102 170000;1;1;1;1;0\n")
        histdata.import_histdata(raw, os.path.join(d, "datasets"), "EURUSD")
        df = load_symbol(os.path.join(d, "datasets"), "EURUSD", "M1")
        assert len(df) == 2                       # dedup
        assert df.index.is_monotonic_increasing   # sorted


# ---- DataSnapshot ----------------------------------------------------------

def _synth_csv(datasets, symbol, n=2000, seed=1):
    os.makedirs(datasets, exist_ok=True)
    idx = pd.date_range("2025-01-02", periods=n, freq="5min", tz="UTC")
    rng = np.random.default_rng(seed)
    close = 1.30 + rng.normal(0, 0.0006, n).cumsum()
    pd.DataFrame({"time": idx.astype(str), "open": close, "high": close + 3e-4,
                  "low": close - 3e-4, "close": close}).to_csv(
        os.path.join(datasets, f"{symbol}_M5.csv"), index=False)


def test_snapshot_identity_and_dedup():
    with tempfile.TemporaryDirectory() as d:
        ds = os.path.join(d, "datasets")
        _synth_csv(ds, "GBPUSD")
        s1 = make_snapshot(ds, ["GBPUSD"], "M5", source="test")
        s2 = make_snapshot(ds, ["GBPUSD"], "M5", source="test")
        assert s1.content_hash == s2.content_hash and s1.row_count == 2000
        assert s1.symbols == ["GBPUSD"]
        store = MemoryStore(d)
        a = store.write_snapshot(s1)
        b = store.write_snapshot(s2)          # same hash -> same stored id
        assert a.id == b.id
        assert store.get_snapshot(a.id) is not None
        store.close()


# ---- regime ----------------------------------------------------------------

def test_regime_classify_labels():
    n = 3000
    idx = pd.date_range("2025-01-02", periods=n, freq="5min", tz="UTC")
    close = 1.30 + np.linspace(0, 0.05, n)        # persistent uptrend
    df = pd.DataFrame({"open": close, "high": close + 2e-4, "low": close - 2e-4,
                       "close": close}, index=idx)
    labels = regime.classify(df).dropna().unique()
    assert any(l.startswith("trend_up") for l in labels)


def test_regime_breakdown_buckets_trades():
    n = 8000
    idx = pd.date_range("2025-01-02", periods=n, freq="5min", tz="UTC")
    rng = np.random.default_rng(3)
    close = 1.30 + rng.normal(0.00012, 0.0007, n).cumsum()
    df = pd.DataFrame({"open": np.concatenate([[close[0]], close[:-1]]),
                       "high": close + np.abs(rng.normal(0, 3e-4, n)),
                       "low": close - np.abs(rng.normal(0, 3e-4, n)),
                       "close": close}, index=idx)
    cfg = {"template": "trend_continuation", "timeframes": {"bias": "H1", "entry": "M5"},
           "session": {"start": "00:00", "end": "23:59", "tz": "UTC"},
           "weekdays": [0, 1, 2, 3, 4], "trend": {"ema_fast": 50, "ema_slow": 200},
           "entry": {"pullback_ema": 20},
           "risk": {"stop": {"atr_mult": 1.0, "atr_period": 14, "swing_lookback": 20},
                    "target_r": 2.0, "max_trades_per_day": 5}}
    strat = Strategy.create(cfg)
    trades = run("GBPUSD", df, strat, max_trades_per_day=5)
    bd = regime.breakdown(trades, df)
    assert sum(m["trades"] for m in bd.values()) == len(trades)   # every trade bucketed
    assert "REGIME" in regime.render(bd)
