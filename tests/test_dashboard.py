"""Dashboard render test — populated and empty roots."""
import tempfile

from atlas.interfaces import dashboard
from atlas.memory import MemoryStore
from atlas.schemas import Hypothesis, ExperimentRecord, new_id, ATLAS_ENGINE_VERSION


def test_dashboard_empty_root_renders():
    with tempfile.TemporaryDirectory() as d:
        htmlp = dashboard.render(d)
        assert htmlp.startswith("<!doctype html>")
        for tab in ("Overview", "Experiments", "Graveyard", "Registry",
                    "Governance", "Knowledge"):
            assert tab in htmlp


def test_dashboard_shows_experiment_and_graveyard():
    with tempfile.TemporaryDirectory() as d:
        store = MemoryStore(d)
        h = Hypothesis(id=new_id("HYP"), version="1.0", domain="fx", title="demo",
                       markets=["GBPUSD"], timeframes={"entry": "M5"},
                       spec={"template": "x"}, success_criteria={}, failure_criteria={},
                       data_split={"in_sample": ["2025-01-01", "2025-06-30"],
                                   "out_sample": ["2025-07-01", "2025-12-31"]}).freeze()
        store.write_hypothesis(h)
        rec = ExperimentRecord(id=new_id("EXP"), hypothesis_id=h.id,
                               hypothesis_version="1.0", engine_version=ATLAS_ENGINE_VERSION,
                               data_snapshot_id="DS", window="out_sample",
                               metrics={"trades": 100, "profit_factor": 0.8,
                                        "expectancy_r": -0.1}, verdict="REJECT")
        store.write_experiment(rec, h)
        store.bury(h.id, "no edge: PF 0.8")
        store.close()
        htmlp = dashboard.render(d, refresh_secs=10)
        assert "REJECT" in htmlp and rec.id in htmlp
        assert "no edge" in htmlp
        assert 'http-equiv="refresh"' in htmlp        # serve refresh honoured
