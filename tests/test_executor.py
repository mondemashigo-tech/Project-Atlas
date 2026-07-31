"""Executor + research-clearance gate: a strategy is only traded once it has
earned it (registry candidate or PASS verdict); otherwise signals are observed
and blocked. Paper fills happen only for cleared strategies. No broker/network."""
import os
import numpy as np
import pandas as pd
import pytest

from atlas.schemas import (Hypothesis, ExperimentRecord, new_id,
                           ATLAS_ENGINE_VERSION)
from atlas.memory import MemoryStore
from atlas.registry import Registry
from atlas.registry.registry import make_candidate
from atlas.execution import (Executor, ReplayFeed, PaperBroker, CapitalGate,
                             AccountMode, research_clearance)

NAME = "exec_test"
_CFG = f"""name: {NAME}
version: "1.0"
template: composed
markets: [GBPUSD]
timeframes: {{entry: M5}}
features:
  - {{name: ema_f, kind: ema, source: close, period: 5}}
  - {{name: atr14, kind: atr, period: 14}}
entry_long: {{lhs: close, cmp: cross_above, rhs: ema_f}}
entry_short: {{lhs: close, cmp: cross_below, rhs: ema_f}}
risk: {{stop: {{kind: atr, atr_period: 14, atr_mult: 1.5}}, target_r: 2.0, max_trades_per_day: 50}}
costs: {{spread_pips: 1.0, commission_r: 0.05}}
criteria: {{success: {{}}, failure: {{}}}}
data: {{in_sample: ["2020-01-01","2022-12-31"], out_sample: ["2023-01-01","2025-12-31"]}}
"""


def _bars(n=1500, seed=5):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2023-01-02", periods=n, freq="5min", tz="UTC")
    close = 1.30 + rng.normal(0, 0.0006, n).cumsum()
    return {"GBPUSD": pd.DataFrame({
        "open": np.concatenate([[close[0]], close[:-1]]),
        "high": close + np.abs(rng.normal(0, 3e-4, n)),
        "low": close - np.abs(rng.normal(0, 3e-4, n)),
        "close": close}, index=idx)}


def _write_cfg(root):
    d = os.path.join(root, "hypotheses"); os.makedirs(d, exist_ok=True)
    p = os.path.join(d, f"{NAME}.yaml")
    with open(p, "w") as f:
        f.write(_CFG)
    return p


def _record(root, verdict, with_candidate=False):
    """Put a hypothesis (title == NAME) + experiment (+candidate) on record."""
    store = MemoryStore(root)
    h = Hypothesis(id=new_id("HYP"), version="1.0", domain="fx", title=NAME,
                   markets=["GBPUSD"], timeframes={"entry": "M5"},
                   spec={"template": "composed"}, success_criteria={},
                   failure_criteria={},
                   data_split={"in_sample": ["2023-01-01", "2023-06-30"],
                               "out_sample": ["2023-07-01", "2023-12-31"]}).freeze()
    store.write_hypothesis(h)
    exp = ExperimentRecord(id=new_id("EXP"), hypothesis_id=h.id,
                           hypothesis_version="1.0",
                           engine_version=ATLAS_ENGINE_VERSION,
                           data_snapshot_id="DS-x", window="out_sample",
                           metrics={"trades": 120}, verdict=verdict)
    store.write_experiment(exp)
    store.close()
    if with_candidate:
        reg = Registry(root)
        reg.add_candidate(make_candidate(h.id, "1.0", [exp.id], spec=h.spec,
                                         allocation=0.0, risk_limits={}))
        reg.close()
    return h


# ---- clearance gate --------------------------------------------------------
def test_clearance_untested_not_cleared(tmp_path):
    c = research_clearance(str(tmp_path), NAME)
    assert c["cleared"] is False and "no recorded experiment" in c["reason"]


def test_clearance_reject_not_cleared(tmp_path):
    _record(str(tmp_path), "REJECT")
    c = research_clearance(str(tmp_path), NAME)
    assert c["cleared"] is False and c["verdict"] == "REJECT"


def test_clearance_pass_verdict_clears(tmp_path):
    _record(str(tmp_path), "PASS")
    c = research_clearance(str(tmp_path), NAME)
    assert c["cleared"] is True and c["basis"] == "pass_verdict"


def test_clearance_registry_candidate_clears(tmp_path):
    _record(str(tmp_path), "REJECT", with_candidate=True)   # even a REJECT verdict...
    c = research_clearance(str(tmp_path), NAME)
    assert c["cleared"] is True and c["basis"] == "registry_candidate"
    assert c["strategy_id"]


# ---- executor gating -------------------------------------------------------
def test_executor_blocks_uncleared_strategy(tmp_path):
    root = str(tmp_path); path = _write_cfg(root)
    _record(root, "REJECT")                                 # not cleared
    ex = Executor(root, PaperBroker(mode=AccountMode.PAPER),
                  CapitalGate(root), AccountMode.PAPER)
    armed = ex.arm(path)
    assert armed["armed"] is False
    out = ex.run_replay(ReplayFeed(_bars()))
    assert out["fills"] == 0 and out["blocked"] > 0         # signals seen, none traded


def test_executor_paper_trades_cleared_strategy(tmp_path):
    root = str(tmp_path); path = _write_cfg(root)
    _record(root, "REJECT", with_candidate=True)            # cleared via candidate
    broker = PaperBroker(mode=AccountMode.PAPER)
    ex = Executor(root, broker, CapitalGate(root), AccountMode.PAPER)
    armed = ex.arm(path)
    assert armed["armed"] is True
    out = ex.run_replay(ReplayFeed(_bars()))
    assert out["fills"] > 0                                  # it actually paper-traded
    assert out["blocked"] == 0


def test_executor_observe_never_fills_even_when_cleared(tmp_path):
    root = str(tmp_path); path = _write_cfg(root)
    _record(root, "REJECT", with_candidate=True)
    broker = PaperBroker(mode=AccountMode.OBSERVE)           # observe: intents only
    ex = Executor(root, broker, CapitalGate(root), AccountMode.OBSERVE)
    ex.arm(path)
    ex.run_replay(ReplayFeed(_bars()))
    assert len(broker.get_open_positions()) == 0            # observed, never filled
    assert broker.intents                                    # but signals were recorded
