"""Milestone 6 tests: Statistician, Historian, Architect, and their wiring."""
import tempfile

from atlas.schemas import Hypothesis, ExperimentRecord, new_id, ATLAS_ENGINE_VERSION
from atlas.agents import Statistician, Historian, Architect, AgentContext
from atlas.memory import MemoryStore


def _hyp(title="t"):
    return Hypothesis(id=new_id("HYP"), version="1.0", domain="fx", title=title,
                      markets=["GBPUSD"], timeframes={"entry": "M5"},
                      spec={"template": "trend_continuation"},
                      success_criteria={}, failure_criteria={},
                      data_split={"in_sample": ["2025-01-01", "2025-06-30"],
                                  "out_sample": ["2025-07-01", "2025-12-31"]}).freeze()


def _ctx(metrics, mc=None, hyp=None):
    h = hyp or _hyp()
    e = ExperimentRecord(id=new_id("EXP"), hypothesis_id=h.id, hypothesis_version="1.0",
                         engine_version=ATLAS_ENGINE_VERSION, data_snapshot_id="DS",
                         window="out_sample", metrics=metrics, verdict="PASS",
                         monte_carlo=mc)
    return AgentContext(task_id=h.id, hypothesis=h, experiment=e)


# ---- Statistician ----------------------------------------------------------

def test_statistician_significant_positive():
    mc = {"bootstrap": {"total_r": {"p5": 10.0, "p95": 80.0}}}
    d = Statistician().run(_ctx({"trades": 300, "expectancy_r": 0.3}, mc))
    assert d.decision == "significant_positive" and d.confidence == "high"


def test_statistician_not_significant_when_band_straddles_zero():
    mc = {"bootstrap": {"total_r": {"p5": -20.0, "p95": 30.0}}}
    d = Statistician().run(_ctx({"trades": 300, "expectancy_r": 0.05}, mc))
    assert d.decision == "not_significant"


def test_statistician_insufficient_sample():
    d = Statistician().run(_ctx({"trades": 20, "expectancy_r": 0.3}))
    assert d.decision == "insufficient_sample" and d.confidence == "low"


# ---- Historian -------------------------------------------------------------

def test_historian_flags_duplicate():
    with tempfile.TemporaryDirectory() as d:
        store = MemoryStore(d)
        h1 = _hyp("first"); store.write_hypothesis(h1)
        # a second hypothesis with the SAME identity -> same prereg hash
        h2 = _hyp("first")           # identical fields => identical prereg hash
        dec = Historian(store).run(_ctx({"trades": 100}, hyp=h2))
        assert dec.decision == "duplicate" and h1.id in dec.evidence
        store.close()


def test_historian_novel_when_unseen():
    with tempfile.TemporaryDirectory() as d:
        store = MemoryStore(d)
        dec = Historian(store).run(_ctx({"trades": 100}, hyp=_hyp("brand new")))
        assert dec.decision == "novel"
        store.close()


# ---- Architect -------------------------------------------------------------

def test_architect_reports_health():
    with tempfile.TemporaryDirectory() as d:
        store = MemoryStore(d)
        h = _hyp("x"); store.write_hypothesis(h)
        store.bury(h.id, "no edge")
        obs = Architect().observe(store)
        assert obs["counts"]["hypotheses"] == 1 and obs["counts"]["graveyard"] == 1
        assert obs["graveyard_rate"] == 1.0
        rep = Architect().report(store)
        assert "ARCHITECT" in rep
        store.close()
