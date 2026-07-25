"""Milestone 8 tests: governed research loop + decay monitoring, with the
autonomy ceiling and no-autonomous-deployment guardrails."""
import os
import tempfile
from dataclasses import dataclass

import numpy as np
import pandas as pd
import pytest

from atlas.lab import ResearchLoop, MAX_AUTONOMY, decay_check, monitor
from atlas.risk import RiskPolicy
from atlas.registry import Registry


@dataclass
class _T:
    pnl_r: float


def _dataset(root, drift=0.00012, seed=1):
    ds = os.path.join(root, "datasets"); os.makedirs(ds, exist_ok=True)
    n = 12000
    idx = pd.date_range("2025-01-02", periods=n, freq="5min", tz="UTC")
    rng = np.random.default_rng(seed)
    close = 1.30 + rng.normal(drift, 0.0007, n).cumsum()
    pd.DataFrame({"time": idx.astype(str),
                  "open": np.concatenate([[close[0]], close[:-1]]),
                  "high": close + np.abs(rng.normal(0, 3e-4, n)),
                  "low": close - np.abs(rng.normal(0, 3e-4, n)),
                  "close": close}).to_csv(os.path.join(ds, "GBPUSD_M5.csv"), index=False)


def _base(root):
    p = os.path.join(root, "base.yaml")
    with open(p, "w") as f:
        f.write("""name: loop_base
version: "1.0"
template: trend_continuation
markets: [GBPUSD]
timeframes: {bias: H1, entry: M5}
session: {start: "00:00", end: "23:59", tz: UTC}
weekdays: [0,1,2,3,4]
trend: {ema_fast: 50, ema_slow: 200}
entry: {pullback_ema: 20}
risk: {stop: {atr_mult: 1.0, atr_period: 14, swing_lookback: 20}, target_r: 2.0, max_trades_per_day: 5, risk_pct: 1.0}
costs: {spread_pips: 1.0, commission_r: 0.03}
criteria: {success: {profit_factor: 1.3, min_trades: 10, expectancy: positive}, failure: {profit_factor: 1.0, expectancy: negative}}
data: {in_sample: ["2025-01-01","2025-06-30"], out_sample: ["2025-01-02","2025-12-31"]}
""")
    return p


# ---- guardrails ------------------------------------------------------------

def test_autonomy_ceiling_enforced():
    with pytest.raises(ValueError):
        ResearchLoop(autonomy_level=MAX_AUTONOMY + 1)


def test_level2_proposes_only_no_testing():
    with tempfile.TemporaryDirectory() as root:
        _dataset(root)
        loop = ResearchLoop(root=root, autonomy_level=2, max_per_cycle=2)
        r = loop.run_cycle(_base(root), grid={"risk.target_r": [1.5, 2.5]})
        assert r["tested"] == [] and "proposals" in r
        # nothing was registered
        reg = Registry(root)
        assert reg.list() == []
        reg.close()


# ---- L3 loop ---------------------------------------------------------------

def test_level3_tests_and_never_promotes_to_capital():
    with tempfile.TemporaryDirectory() as root:
        _dataset(root, drift=0.00025)      # trending -> some variants may pass
        loop = ResearchLoop(root=root, autonomy_level=3, max_per_cycle=2,
                            risk_policy=RiskPolicy(max_drawdown_r=300.0, min_trades=10))
        r = loop.run_cycle(_base(root), grid={"risk.target_r": [1.5, 2.5]})
        assert len(r["tested"]) >= 1
        assert os.path.exists(r["report_path"])
        # Any candidates are NON-capital; the bot's executable export stays empty.
        reg = Registry(root)
        assert reg.export_json() == []
        for rec in reg.list():
            assert rec.status == "candidate"       # never auto-promoted
        reg.close()


# ---- decay -----------------------------------------------------------------

def test_decay_flags_drift():
    good = decay_check(0.3, [_T(0.28), _T(0.31), _T(0.29)])
    assert good["drifted"] is False
    bad = decay_check(0.3, [_T(-0.1), _T(0.0), _T(-0.2)])
    assert bad["drifted"] is True and "retire" in bad["recommendation"]
    assert decay_check(0.3, [])["status"] == "no_recent_data"


def test_monitor_idle_when_nothing_live():
    with tempfile.TemporaryDirectory() as root:
        reg = Registry(root)
        assert monitor(reg) == []          # nothing promoted -> nothing to monitor
        reg.close()
