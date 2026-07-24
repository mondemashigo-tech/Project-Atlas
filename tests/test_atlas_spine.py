"""Milestone 1 tests: the Atlas parent spine — schemas, memory, registry, and the
research->memory service. No trading, no signals."""
import os
import tempfile

import numpy as np
import pandas as pd
import pytest

from atlas.schemas import (Hypothesis, ExperimentRecord, DecisionRecord,
                           StrategyRecord, SchemaError, new_id,
                           ATLAS_ENGINE_VERSION)
from atlas.memory import MemoryStore
from atlas.registry import Registry, RegistryError, BotStub
from atlas.registry.registry import make_candidate
from atlas import service


# ---- schemas ---------------------------------------------------------------

def _good_hypothesis():
    return Hypothesis(
        id=new_id("HYP"), version="1.0", domain="fx", title="t",
        markets=["GBPUSD"], timeframes={"bias": "H1", "entry": "M5"},
        spec={"template": "trend_continuation", "trend": {"ema_fast": 50}},
        success_criteria={"profit_factor": 1.5}, failure_criteria={},
        data_split={"in_sample": ["2023-01-01", "2023-12-31"],
                    "out_sample": ["2024-01-01", "2024-12-31"]})


def test_hypothesis_validation_and_freeze():
    h = _good_hypothesis()
    assert h.validate() == []
    h.freeze()
    assert h.status == "SPECIFIED" and h.preregistration_hash
    # Rule drift: mutate an identity field after freezing -> hash mismatch caught.
    h.spec["trend"]["ema_fast"] = 30
    assert any("rule drift" in e for e in h.validate())


def test_hypothesis_rejects_incomplete():
    h = _good_hypothesis()
    h.timeframes = {"bias": "H1"}          # missing entry
    with pytest.raises(SchemaError):
        h.ensure_valid()


def test_prereg_hash_changes_with_spec():
    a = _good_hypothesis(); b = _good_hypothesis()
    assert a.compute_prereg_hash() == b.compute_prereg_hash()
    b.data_split["out_sample"] = ["2025-01-01", "2025-12-31"]
    assert a.compute_prereg_hash() != b.compute_prereg_hash()


# ---- memory ----------------------------------------------------------------

def test_memory_experiment_roundtrip_and_mirror():
    with tempfile.TemporaryDirectory() as d:
        store = MemoryStore(d)
        h = _good_hypothesis().freeze()
        store.write_hypothesis(h)
        rec = ExperimentRecord(
            id=new_id("EXP"), hypothesis_id=h.id, hypothesis_version=h.version,
            engine_version=ATLAS_ENGINE_VERSION, data_snapshot_id=None,
            window="out_sample",
            metrics={"trades": 100, "win_rate": 40.0, "profit_factor": 1.6,
                     "expectancy_r": 0.2, "total_r": 20.0, "max_drawdown_r": 5.0,
                     "sharpe_per_trade": 0.1},
            verdict="PASS")
        store.write_experiment(rec, h)
        back = store.get_experiment(rec.id)
        assert back.to_dict() == rec.to_dict()          # identical round-trip
        # Obsidian mirror exists and is human-readable.
        md = os.path.join(d, "vault", "experiments", f"{rec.id}.md")
        assert os.path.exists(md)
        assert "profit_factor" in open(md).read()
        # Immutable: re-writing the same id is rejected.
        with pytest.raises(ValueError):
            store.write_experiment(rec, h)
        store.close()


# ---- registry --------------------------------------------------------------

def _candidate():
    return make_candidate("HYP-x", "1.0", ["EXP-1"],
                          spec={"template": "trend_continuation"},
                          allocation=0.0)


def test_registry_lifecycle_and_human_gate():
    with tempfile.TemporaryDirectory() as d:
        reg = Registry(d)
        rec = reg.add_candidate(_candidate())
        sid = rec.strategy_id
        # Capital-bearing transition WITHOUT approval token -> refused.
        with pytest.raises(RegistryError):
            reg.transition(sid, "paper")
        # Illegal edge (candidate -> live) -> refused.
        with pytest.raises(RegistryError):
            reg.transition(sid, "live", approved_by="monde")
        # Legal, human-approved promotion.
        dr = reg.transition(sid, "paper", approved_by="monde", note="looks ok")
        assert isinstance(dr, DecisionRecord) and reg.get(sid).status == "paper"
        assert reg.get(sid).approvals[-1]["who"] == "monde"
        # Export shows the paper strategy; bot stub places NO orders.
        exp = reg.export_json()
        assert len(exp) == 1 and exp[0]["strategy_id"] == sid
        assert any("NO ORDERS" in ln for ln in BotStub().plan(exp))
        # Kill-switch empties the bot's world.
        reg.kill_switch("test")
        assert reg.export_json() == []
        reg.close()


def test_registry_rejects_invalid_candidate():
    with tempfile.TemporaryDirectory() as d:
        reg = Registry(d)
        bad = StrategyRecord(strategy_id=new_id("STR"), source_hypothesis_id="",
                             source_hypothesis_version="1.0",
                             validating_experiment_ids=[], frozen_executable_spec={})
        with pytest.raises(SchemaError):
            reg.add_candidate(bad)
        reg.close()


# ---- end-to-end service ----------------------------------------------------

def test_service_run_produces_experiment_record():
    with tempfile.TemporaryDirectory() as d:
        # minimal dataset so the engine has something to chew (may still be 0 trades)
        ds = os.path.join(d, "datasets"); os.makedirs(ds)
        n = 6000
        idx = pd.date_range("2024-01-02", periods=n, freq="5min", tz="UTC")
        rng = np.random.default_rng(1)
        close = 1.30 + rng.normal(0.00005, 0.0008, n).cumsum()
        pd.DataFrame({"time": idx.astype(str), "open": close, "high": close + 4e-4,
                      "low": close - 4e-4, "close": close}).to_csv(
            os.path.join(ds, "GBPUSD_M5.csv"), index=False)
        hyp_path = os.path.join(d, "h.yaml")
        with open(hyp_path, "w") as f:
            f.write("""name: spine_test
version: "1.0"
template: trend_continuation
markets: [GBPUSD]
timeframes: {bias: H1, entry: M5}
session: {start: "00:00", end: "23:59", tz: UTC}
weekdays: [0,1,2,3,4]
trend: {ema_fast: 50, ema_slow: 200}
entry: {pullback_ema: 20}
risk: {stop: {atr_mult: 1.0, atr_period: 14, swing_lookback: 20}, target_r: 2.0, max_trades_per_day: 3}
costs: {spread_pips: 1.0, commission_r: 0.03}
criteria: {success: {profit_factor: 1.5, min_trades: 10, expectancy: positive}, failure: {profit_factor: 1.0, expectancy: negative}}
data: {in_sample: ["2024-01-01","2024-06-30"], out_sample: ["2024-01-02","2024-12-31"]}
""")
        hyp, rec, v = service.run_experiment(hyp_path, root=d, window="out_sample")
        assert hyp.status == "SPECIFIED" and hyp.preregistration_hash
        assert rec.engine_version == ATLAS_ENGINE_VERSION
        assert rec.verdict in ("PASS", "REJECT", "INCONCLUSIVE", "NO_TRADES")
        # It was persisted + mirrored.
        store = MemoryStore(d)
        assert store.get_experiment(rec.id) is not None
        store.close()
        assert os.path.exists(os.path.join(d, "vault", "experiments", f"{rec.id}.md"))
