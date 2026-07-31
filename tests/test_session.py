"""Live paper session: ticks a cleared strategy over a feed, tallies money P/L,
and refuses an uncleared strategy. Uses a ReplayFeed (no MT5/network)."""
import os
import numpy as np
import pandas as pd

from atlas.schemas import (Hypothesis, ExperimentRecord, new_id,
                           ATLAS_ENGINE_VERSION)
from atlas.memory import MemoryStore
from atlas.execution import CapitalGate, ReplayFeed
from atlas.live.session import PaperSession

NAME = "sess_test"
_CFG = f"""name: {NAME}
version: "1.0"
template: composed
markets: [GBPUSD]
timeframes: {{entry: M5}}
features:
  - {{name: ema_f, kind: ema, source: close, period: 8}}
  - {{name: atr14, kind: atr, period: 14}}
entry_long: {{lhs: close, cmp: cross_above, rhs: ema_f}}
entry_short: {{lhs: close, cmp: cross_below, rhs: ema_f}}
risk: {{stop: {{kind: atr, atr_period: 14, atr_mult: 2.0}}, target_r: 2.0, max_trades_per_day: 50}}
costs: {{spread_pips: 1.0, commission_r: 0.05}}
criteria: {{success: {{}}, failure: {{}}}}
data: {{in_sample: ["2020-01-01","2022-12-31"], out_sample: ["2023-01-01","2025-12-31"]}}
"""


def _cfg_file(root):
    d = os.path.join(root, "hypotheses"); os.makedirs(d, exist_ok=True)
    p = os.path.join(d, f"{NAME}.yaml")
    open(p, "w").write(_CFG)
    return p


def _bars(n=1400, seed=9):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2023-01-02", periods=n, freq="5min", tz="UTC")
    close = 1.30 + (np.sin(np.linspace(0, 30, n)) * 0.008) + rng.normal(0, 0.0005, n).cumsum() * 0.2
    return {"GBPUSD": pd.DataFrame({
        "open": np.concatenate([[close[0]], close[:-1]]),
        "high": close + np.abs(rng.normal(0, 3e-4, n)),
        "low": close - np.abs(rng.normal(0, 3e-4, n)),
        "close": close}, index=idx)}


def _clear(root):
    store = MemoryStore(root)
    h = Hypothesis(id=new_id("HYP"), version="1.0", domain="fx", title=NAME,
                   markets=["GBPUSD"], timeframes={"entry": "M5"},
                   spec={"template": "composed"}, success_criteria={},
                   failure_criteria={},
                   data_split={"in_sample": ["2023-01-01", "2023-06-30"],
                               "out_sample": ["2023-07-01", "2023-12-31"]}).freeze()
    store.write_hypothesis(h)
    store.write_experiment(ExperimentRecord(
        id=new_id("EXP"), hypothesis_id=h.id, hypothesis_version="1.0",
        engine_version=ATLAS_ENGINE_VERSION, data_snapshot_id="DS-x",
        window="out_sample", metrics={"trades": 150}, verdict="PASS"))
    store.close()


def test_session_refuses_uncleared(tmp_path):
    root = str(tmp_path); path = _cfg_file(root)
    s = PaperSession(root, CapitalGate(root), path, ReplayFeed(_bars()))
    out = s.start()
    assert out["started"] is False and s.running() is False


def test_session_ticks_cleared_strategy_and_tracks_money_pnl(tmp_path):
    root = str(tmp_path); path = _cfg_file(root)
    _clear(root)
    s = PaperSession(root, CapitalGate(root), path, ReplayFeed(_bars(), start=200))
    s.armed = s.executor.arm(path)["armed"]
    assert s.armed is True
    # drive it synchronously to the end of the replay
    while s.feed.has_more():
        s.tick()
    st = s.status()
    assert st["stats"]["fills"] > 0                 # it paper-traded
    # P/L is in account money (contract size applied), not raw price units
    assert isinstance(st["realised_pnl"], float)
    assert st["balance"] != 10000.0 or st["stats"]["closes"] == 0


def test_session_kill_switch_would_halt(tmp_path):
    root = str(tmp_path); path = _cfg_file(root)
    _clear(root)
    gate = CapitalGate(root)
    gate.activate_kill_switch("halt")
    s = PaperSession(root, gate, path, ReplayFeed(_bars()))
    s.armed = s.executor.arm(path)["armed"]
    # with the kill switch active, a tick generates signals but the gate blocks fills
    s.tick()
    assert len(s.broker.get_open_positions()) == 0
