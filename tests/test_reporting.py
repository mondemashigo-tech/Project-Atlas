"""Phase 3 tests: optimiser, research journal, SVG charts, HTML dashboard.
Synthetic data only."""
import os
import tempfile

import numpy as np
import pandas as pd

from atlas import charts, dashboard, journal, optimizer, runner
from atlas.strategies import trend_continuation  # noqa: registers template


def _write_synth(datasets_dir, symbol="GBPUSD", n=30000, seed=1):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2022-01-03 00:00", periods=n, freq="5min", tz="UTC")
    close = 1.30 + rng.normal(0.00004, 0.0008, n).cumsum()
    high = close + np.abs(rng.normal(0, 0.0004, n))
    low = close - np.abs(rng.normal(0, 0.0004, n))
    open_ = np.concatenate([[close[0]], close[:-1]])
    os.makedirs(datasets_dir, exist_ok=True)
    pd.DataFrame({"time": idx.astype(str), "open": open_, "high": high,
                  "low": low, "close": close}).to_csv(
        os.path.join(datasets_dir, f"{symbol}_M5.csv"), index=False)


CFG = {
    "name": "report_test", "version": "1.0", "template": "trend_continuation",
    "markets": ["GBPUSD"], "timeframes": {"bias": "H1", "entry": "M5"},
    "session": {"start": "00:00", "end": "23:59", "tz": "UTC"},
    "weekdays": [0, 1, 2, 3, 4],
    "trend": {"ema_fast": 50, "ema_slow": 200}, "entry": {"pullback_ema": 20},
    "risk": {"stop": {"atr_mult": 1.0, "atr_period": 14, "swing_lookback": 20},
             "target_r": 2.0, "max_trades_per_day": 3},
    "costs": {"spread_pips": 1.0, "commission_r": 0.03},
    "criteria": {"success": {"profit_factor": 1.3, "min_trades": 30, "expectancy": "positive"},
                 "failure": {"profit_factor": 1.0, "expectancy": "negative"}},
    "data": {"in_sample": ["2022-01-01", "2022-06-30"],
             "out_sample": ["2022-07-01", "2022-12-31"]},
}


# ---- charts ----------------------------------------------------------------

def test_charts_emit_svg():
    svg = charts.equity_curve_svg([1.0, -1.0, 2.0, -1.0, 1.5])
    assert svg.startswith("<svg") and "polyline" in svg
    assert charts.equity_curve_svg([]).startswith("<svg")  # empty is safe
    h = charts.histogram_svg([0.1, 0.2, 0.2, 0.5, -0.3], marker=0.2, label="exp")
    assert "<svg" in h and "rect" in h


# ---- journal ---------------------------------------------------------------

def test_journal_append_load_and_fingerprint():
    with tempfile.TemporaryDirectory() as d:
        _write_synth(os.path.join(d, "datasets"))
        results = runner.run_hypothesis(CFG, os.path.join(d, "datasets"))
        path = os.path.join(d, "journal.jsonl")
        journal.append(CFG, results, {"result": "PASS"}, path=path)
        journal.append(CFG, results, {"result": "PASS"}, path=path)
        recs = journal.load(path)
        assert len(recs) == 2
        assert recs[0]["name"] == "report_test"
        assert "report_test" in journal.render(recs)
        # Fingerprint must change when the hypothesis changes.
        fp1 = journal.fingerprint(CFG)
        changed = dict(CFG, risk=dict(CFG["risk"], target_r=3.0))
        assert journal.fingerprint(changed) != fp1


def test_journal_empty_load():
    assert journal.load("/nonexistent/path.jsonl") == []


# ---- optimiser -------------------------------------------------------------

def test_optimizer_ranks_on_in_sample_reports_oos():
    cfg = dict(CFG, optimize={"risk.target_r": [1.0, 2.0, 3.0]})
    with tempfile.TemporaryDirectory() as d:
        _write_synth(os.path.join(d, "datasets"))
        opt = optimizer.optimize(cfg, os.path.join(d, "datasets"),
                                 objective="total_r", min_trades=5)
        assert opt["n_configs"] == 3
        # rows must be sorted by in-sample objective, descending
        is_totals = [r["is"].get("total_r", float("-inf")) for r in opt["rows"]
                     if r["is"].get("trades", 0) >= 5]
        assert is_totals == sorted(is_totals, reverse=True)
        assert opt["best"] is not None
        assert "OPTIMISER" in optimizer.render(opt)


# ---- dashboard -------------------------------------------------------------

def test_dashboard_renders_full_html():
    with tempfile.TemporaryDirectory() as d:
        _write_synth(os.path.join(d, "datasets"))
        results = runner.run_hypothesis(CFG, os.path.join(d, "datasets"))
        html = dashboard.render(CFG, results, mc=None, wf=None, journal_records=[])
        assert html.startswith("<!doctype html>")
        for token in ("ATLAS", "Overview", "Walk-forward", "Monte Carlo",
                      "Trades", "Journal", "showTab"):
            assert token in html
