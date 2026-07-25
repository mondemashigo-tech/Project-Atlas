"""Milestone 5 tests: OOS budget / multiple-testing ledger, graveyard, policy,
and the orchestrator honouring the budget + auto-burial."""
import os
import tempfile

import numpy as np
import pandas as pd

from atlas.memory import MemoryStore
from atlas.governance import budget_status, OOSBudget
from atlas.schemas import Hypothesis, new_id
from atlas.kernel import Orchestrator
from atlas.risk import RiskPolicy


def _hyp(title="t"):
    return Hypothesis(id=new_id("HYP"), version="1.0", domain="fx", title=title,
                      markets=["GBPUSD"], timeframes={"entry": "M5"},
                      spec={"template": "x"}, success_criteria={}, failure_criteria={},
                      data_split={"in_sample": ["2025-01-01", "2025-06-30"],
                                  "out_sample": ["2025-07-01", "2025-12-31"]}).freeze()


def test_oos_ledger_counts_distinct_hypotheses():
    with tempfile.TemporaryDirectory() as d:
        store = MemoryStore(d)
        for i in range(3):
            h = _hyp(f"h{i}")
            store.record_oos_test("DS-1", "out_sample", h.id, h.preregistration_hash)
        # a re-run of the same hypothesis id doesn't add a new "look"
        store.record_oos_test("DS-1", "out_sample", "HYP-dup", "x")
        store.record_oos_test("DS-1", "out_sample", "HYP-dup", "x")
        assert store.oos_test_count("DS-1", "out_sample") == 4
        b = budget_status(store, "DS-1", "out_sample", OOSBudget(max_tests=4))
        assert b["burned"] is False and b["remaining"] == 0
        b2 = budget_status(store, "DS-1", "out_sample", OOSBudget(max_tests=3))
        assert b2["burned"] is True
        store.close()


def test_graveyard_and_policy():
    with tempfile.TemporaryDirectory() as d:
        store = MemoryStore(d)
        h = _hyp("doomed")
        store.write_hypothesis(h)
        store.bury(h.id, "no edge: PF 0.8")
        assert store.get_hypothesis(h.id).status == "GRAVEYARD"
        gy = store.list_graveyard()
        assert len(gy) == 1 and "no edge" in gy[0]["reason"]
        assert os.path.exists(os.path.join(d, "vault", "graveyard", f"{h.id}.md"))
        # policy memory round-trip
        store.set_policy("risk", {"max_drawdown_r": 30}, updated_by="monde")
        assert store.get_policy("risk")["max_drawdown_r"] == 30
        assert store.get_policy("missing", {"x": 1}) == {"x": 1}
        store.close()


def _dataset(root, seed=1, drift=0.00012):
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


def _losing_hyp_file(root):
    # ORB-less losing config: a mean-reversion in a trend tends to reject.
    p = os.path.join(root, "h.yaml")
    with open(p, "w") as f:
        f.write("""name: gov_losing
version: "1.0"
template: mean_reversion
markets: [GBPUSD]
timeframes: {entry: M5}
weekdays: [0,1,2,3,4]
meanrev: {ma_period: 20, entry_z: 2.0, exit: mean}
risk: {stop: {atr_mult: 1.5, atr_period: 14}, target_r: 1.5, max_trades_per_day: 5}
costs: {spread_pips: 1.0, commission_r: 0.05}
criteria: {success: {profit_factor: 1.5, min_trades: 50, expectancy: positive}, failure: {profit_factor: 1.2, expectancy: negative}}
data: {in_sample: ["2025-01-01","2025-06-30"], out_sample: ["2025-01-02","2025-12-31"]}
""")
    return p


def test_orchestrator_buries_rejected_hypothesis():
    with tempfile.TemporaryDirectory() as root:
        _dataset(root, drift=0.00025)      # strong trend -> mean-reversion loses
        res = Orchestrator(root).run(_losing_hyp_file(root), window="out_sample")
        phases = [d.phase for d in res["decisions"]]
        assert "governance" in phases
        # If the Skeptic rejected, the hypothesis must be in the graveyard.
        skeptic = [d for d in res["decisions"] if d.agent == "Skeptic"][0]
        store = MemoryStore(root)
        if skeptic.decision == "reject":
            assert any(g["hypothesis_id"] == res["hypothesis"].id
                       for g in store.list_graveyard())
        store.close()
