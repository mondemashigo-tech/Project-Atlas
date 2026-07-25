"""Milestone 4 tests: Risk Manager hard gate + portfolio analysis, and the
orchestrator ladder extended through risk + portfolio + candidate registration."""
import os
import tempfile
from dataclasses import dataclass

import numpy as np
import pandas as pd

from atlas.schemas import Hypothesis, ExperimentRecord, new_id, ATLAS_ENGINE_VERSION
from atlas.agents.base import AgentContext
from atlas.risk import RiskManager, RiskPolicy
from atlas.portfolio import analyze, daily_returns
from atlas.kernel import Orchestrator
from atlas.registry import Registry


@dataclass
class _T:
    entry_time: str
    pnl_r: float
    symbol: str = "X"
    direction: str = "BUY"


def _ctx(metrics, risk_rules):
    h = Hypothesis(id=new_id("HYP"), version="1.0", domain="fx", title="t",
                   markets=["GBPUSD"], timeframes={"entry": "M5"},
                   spec={"template": "x"}, success_criteria={}, failure_criteria={},
                   data_split={"in_sample": ["2025-01-01", "2025-06-30"],
                               "out_sample": ["2025-07-01", "2025-12-31"]},
                   risk_rules=risk_rules).freeze()
    e = ExperimentRecord(id=new_id("EXP"), hypothesis_id=h.id, hypothesis_version="1.0",
                         engine_version=ATLAS_ENGINE_VERSION, data_snapshot_id="DS",
                         window="out_sample", metrics=metrics, verdict="PASS")
    return AgentContext(task_id=h.id, hypothesis=h, experiment=e, verdict={"result": "PASS"})


# ---- risk ------------------------------------------------------------------

def test_risk_vetoes_excessive_drawdown():
    ctx = _ctx({"trades": 300, "max_drawdown_r": 60.0}, {"max_trades_per_day": 3})
    d = RiskManager(RiskPolicy(max_drawdown_r=40.0)).run(ctx)
    assert d.decision == "veto" and "drawdown" in d.evidence


def test_risk_passes_within_limits():
    ctx = _ctx({"trades": 300, "max_drawdown_r": 12.0}, {"max_trades_per_day": 3,
               "risk_pct": 1.0})
    d = RiskManager(RiskPolicy()).run(ctx)
    assert d.decision == "pass"


def test_risk_vetoes_thin_sample():
    ctx = _ctx({"trades": 20, "max_drawdown_r": 5.0}, {"max_trades_per_day": 2})
    d = RiskManager(RiskPolicy(min_trades=100)).run(ctx)
    assert d.decision == "veto"


# ---- portfolio -------------------------------------------------------------

def test_daily_returns_and_analyze():
    a_trades = [_T("2025-01-02 10:00", 1.0), _T("2025-01-02 12:00", -1.0),
                _T("2025-01-03 10:00", 2.0)]
    b_trades = [_T("2025-01-02 09:00", -0.5), _T("2025-01-03 09:00", 1.5)]
    dr = daily_returns(a_trades)
    assert abs(dr.loc[pd.Timestamp("2025-01-02")] - 0.0) < 1e-9    # +1 -1
    a = analyze({"A": a_trades, "B": b_trades})
    assert a["strategies"] == 2
    assert "combined_total_r" in a and a["avg_abs_correlation"] is not None


def test_analyze_empty():
    assert analyze({})["strategies"] == 0


# ---- orchestrator through risk + portfolio ---------------------------------

def _dataset(root):
    ds = os.path.join(root, "datasets"); os.makedirs(ds)
    n = 12000
    idx = pd.date_range("2025-01-02", periods=n, freq="5min", tz="UTC")
    rng = np.random.default_rng(1)
    close = 1.30 + rng.normal(0.00012, 0.0007, n).cumsum()
    pd.DataFrame({"time": idx.astype(str),
                  "open": np.concatenate([[close[0]], close[:-1]]),
                  "high": close + np.abs(rng.normal(0, 3e-4, n)),
                  "low": close - np.abs(rng.normal(0, 3e-4, n)),
                  "close": close}).to_csv(os.path.join(ds, "GBPUSD_M5.csv"), index=False)


def _hyp_file(root):
    p = os.path.join(root, "h.yaml")
    with open(p, "w") as f:
        f.write("""name: rp_test
version: "1.0"
template: trend_continuation
markets: [GBPUSD]
timeframes: {bias: H1, entry: M5}
session: {start: "00:00", end: "23:59", tz: UTC}
weekdays: [0,1,2,3,4]
trend: {ema_fast: 50, ema_slow: 200}
entry: {pullback_ema: 20}
risk: {stop: {atr_mult: 1.0, atr_period: 14, swing_lookback: 20}, target_r: 2.0, max_trades_per_day: 3, risk_pct: 1.0}
costs: {spread_pips: 1.0, commission_r: 0.03}
criteria: {success: {profit_factor: 1.3, min_trades: 10, expectancy: positive}, failure: {profit_factor: 1.0, expectancy: negative}}
data: {in_sample: ["2025-01-01","2025-06-30"], out_sample: ["2025-01-02","2025-12-31"]}
""")
    return p


def test_orchestrator_reaches_portfolio_and_registers_candidate():
    with tempfile.TemporaryDirectory() as root:
        _dataset(root)
        # generous drawdown limit so a trending synth passes risk
        res = Orchestrator(root).run(_hyp_file(root), window="out_sample",
                                     risk_policy=RiskPolicy(max_drawdown_r=200.0, min_trades=10))
        phases = [d.phase for d in res["decisions"]]
        assert "risk_validity" in phases and "portfolio_validity" in phases
        assert res["reached_layer"] == "portfolio_validity"
        assert res["advanced"] is True and res["candidate_id"]
        # a NON-capital candidate now exists in the registry; nothing executable yet
        reg = Registry(root)
        assert reg.get(res["candidate_id"]).status == "candidate"
        assert reg.export_json() == []       # candidate is not executable
        reg.close()
