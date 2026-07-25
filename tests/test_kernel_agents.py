"""Milestone 3 tests: agents (Skeptic, Reporter) and the Orchestrator ladder."""
import os
import tempfile

import numpy as np
import pandas as pd

from atlas.schemas import Hypothesis, ExperimentRecord, new_id, ATLAS_ENGINE_VERSION
from atlas.agents import Skeptic, Reporter, AgentContext
from atlas.kernel import Orchestrator, LAYERS


def _hyp():
    return Hypothesis(
        id=new_id("HYP"), version="1.0", domain="fx", title="t",
        markets=["GBPUSD"], timeframes={"bias": "H1", "entry": "M5"},
        spec={"template": "trend_continuation"},
        success_criteria={"profit_factor": 1.3, "min_trades": 100},
        failure_criteria={},
        data_split={"in_sample": ["2025-01-01", "2025-06-30"],
                    "out_sample": ["2025-07-01", "2025-12-31"]}).freeze()


def _exp(metrics, verdict, mc=None):
    return ExperimentRecord(
        id=new_id("EXP"), hypothesis_id="H", hypothesis_version="1.0",
        engine_version=ATLAS_ENGINE_VERSION, data_snapshot_id="DS-1",
        window="out_sample", metrics=metrics, verdict=verdict, monte_carlo=mc)


def _ctx(metrics, verdict, mc=None):
    return AgentContext(task_id="T", hypothesis=_hyp(),
                        experiment=_exp(metrics, verdict, mc), verdict={"result": verdict})


# ---- Skeptic ---------------------------------------------------------------

def test_skeptic_rejects_losing_verdict():
    d = Skeptic().run(_ctx({"trades": 300, "profit_factor": 0.8}, "REJECT"))
    assert d.decision == "reject" and d.agent == "Skeptic"


def test_skeptic_vetoes_fragile_pass():
    # PASS verdict but Monte Carlo says the edge is nearly a coin flip -> veto.
    mc = {"trades": 300, "bootstrap": {"p_total_negative": 0.45,
          "expectancy_r": {"p50": 0.02}}}
    d = Skeptic().run(_ctx({"trades": 300, "profit_factor": 1.4}, "PASS", mc))
    assert d.decision == "veto"


def test_skeptic_approves_robust_pass():
    mc = {"trades": 400, "bootstrap": {"p_total_negative": 0.02,
          "expectancy_r": {"p50": 0.3}}}
    d = Skeptic().run(_ctx({"trades": 400, "profit_factor": 1.8}, "PASS", mc))
    assert d.decision == "approve"


def test_skeptic_narrator_hook_does_not_change_ruling():
    mc = {"trades": 400, "bootstrap": {"p_total_negative": 0.02,
          "expectancy_r": {"p50": 0.3}}}
    d = Skeptic(narrator=lambda p: "LLM says looks fine").run(
        _ctx({"trades": 400, "profit_factor": 1.8}, "PASS", mc))
    assert d.decision == "approve" and "LLM says" in d.evidence


# ---- Reporter --------------------------------------------------------------

def test_reporter_writes_memo():
    with tempfile.TemporaryDirectory() as tmp:
        ctx = _ctx({"trades": 200, "win_rate": 45.0, "profit_factor": 1.5,
                    "expectancy_r": 0.2, "total_r": 40.0, "max_drawdown_r": 8.0}, "PASS")
        d = Reporter(vault=os.path.join(tmp, "vault")).run(ctx)
        assert d.decision == "memo_written"
        path = os.path.join(tmp, "vault", "memos", f"{ctx.experiment.id}.md")
        assert os.path.exists(path)
        assert "Decision memo" in open(path).read()


# ---- Orchestrator ----------------------------------------------------------

def _dataset(root, trending=True):
    ds = os.path.join(root, "datasets"); os.makedirs(ds)
    n = 12000
    idx = pd.date_range("2025-01-02", periods=n, freq="5min", tz="UTC")
    rng = np.random.default_rng(1)
    drift = 0.00012 if trending else 0.0
    close = 1.30 + rng.normal(drift, 0.0007, n).cumsum()
    pd.DataFrame({"time": idx.astype(str),
                  "open": np.concatenate([[close[0]], close[:-1]]),
                  "high": close + np.abs(rng.normal(0, 3e-4, n)),
                  "low": close - np.abs(rng.normal(0, 3e-4, n)),
                  "close": close}).to_csv(os.path.join(ds, "GBPUSD_M5.csv"), index=False)


def _write_hyp(root):
    p = os.path.join(root, "h.yaml")
    with open(p, "w") as f:
        f.write("""name: kernel_test
version: "1.0"
template: trend_continuation
markets: [GBPUSD]
timeframes: {bias: H1, entry: M5}
session: {start: "00:00", end: "23:59", tz: UTC}
weekdays: [0,1,2,3,4]
trend: {ema_fast: 50, ema_slow: 200}
entry: {pullback_ema: 20}
risk: {stop: {atr_mult: 1.0, atr_period: 14, swing_lookback: 20}, target_r: 2.0, max_trades_per_day: 5}
costs: {spread_pips: 1.0, commission_r: 0.03}
criteria: {success: {profit_factor: 1.3, min_trades: 10, expectancy: positive}, failure: {profit_factor: 1.0, expectancy: negative}}
data: {in_sample: ["2025-01-01","2025-06-30"], out_sample: ["2025-01-02","2025-12-31"]}
""")
    return p


def test_orchestrator_runs_ladder_and_records_decisions():
    with tempfile.TemporaryDirectory() as root:
        _dataset(root)
        res = Orchestrator(root).run(_write_hyp(root), window="out_sample")
        phases = [d.phase for d in res["decisions"]]
        # layers 1-4 present, plus a reporting memo
        for layer in ("data_integrity", "rule_validity", "backtest_validity",
                      "statistical_validity", "reporting"):
            assert layer in phases
        # Core invariant: never auto-deploy. If it advanced the whole ladder, a
        # non-capital candidate was registered and deployment stays human-gated.
        if res["advanced"]:
            assert res["candidate_id"] and "human-gated" in res["halt_reason"]
        else:
            assert "halted" in res["halt_reason"]
        # decisions were persisted to memory
        from atlas.memory import MemoryStore
        store = MemoryStore(root)
        assert len(store.list_decisions(res["hypothesis"].id)) >= 4
        store.close()
