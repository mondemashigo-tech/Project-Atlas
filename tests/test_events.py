"""Atlas Live M1: the typed event spine.

Covers the Event schema, the events table + persistence, the EventBus
(publish/subscribe/get_events/replay), and — the real proof — that running one
actual council experiment emits typed events in the correct order, persists them,
and can be replayed after a simulated reconnect. No fabricated activity: an
untouched engine (NullBus) emits nothing.
"""
import os
import tempfile

import numpy as np
import pandas as pd
import pytest

from atlas.events import Event, EventBus, EVENT_TYPES
from atlas.events.bus import NullBus
from atlas.memory import MemoryStore
from atlas.kernel import Orchestrator


# ---- schema ---------------------------------------------------------------
def test_event_rejects_unknown_type_and_severity():
    with pytest.raises(ValueError):
        Event(event_type="not_a_real_type")
    with pytest.raises(ValueError):
        Event(event_type="experiment_started", severity="critical")


def test_event_row_roundtrip(tmp_path):
    store = MemoryStore(str(tmp_path))
    ev = Event(event_type="agent_completed", agent_name="Skeptic",
               summary="reject", evidence_refs=["EXP-1"], metadata={"k": 1})
    store.write_event(ev)
    assert ev.seq == 1                       # cursor assigned on write
    back = store.list_events()[0]
    assert back.event_type == "agent_completed" and back.agent_name == "Skeptic"
    assert back.evidence_refs == ["EXP-1"] and back.metadata == {"k": 1}
    assert back.seq == 1
    store.close()


# ---- bus ------------------------------------------------------------------
def test_bus_persists_streams_and_catches_up(tmp_path):
    store = MemoryStore(str(tmp_path))
    bus = EventBus(store)
    seen = []
    unsub = bus.subscribe(lambda e: seen.append(e.event_type))

    bus.emit("experiment_started")
    bus.emit("backtest_completed", agent_name="Backtester")
    assert seen == ["experiment_started", "backtest_completed"]   # live stream

    # a client reconnecting after seq 1 gets only what it missed
    missed = bus.get_events(after_seq=1)
    assert [e.event_type for e in missed] == ["backtest_completed"]

    unsub()
    bus.emit("experiment_completed")
    assert "experiment_completed" not in seen                     # unsubscribed
    assert len(bus.get_events(after_seq=0)) == 3                  # but still persisted
    store.close()


def test_null_bus_emits_nothing(tmp_path):
    store = MemoryStore(str(tmp_path))
    bus = NullBus()
    bus.emit("experiment_started")
    assert store.list_events() == []          # nothing persisted
    store.close()


# ---- end-to-end: a real council run emits ordered, persisted events -------
def _dataset(root, seed=1, drift=0.00025):
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
    p = os.path.join(root, "h.yaml")
    with open(p, "w") as f:
        f.write("""name: ev_losing
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


def test_council_run_emits_ordered_events():
    with tempfile.TemporaryDirectory() as root:
        _dataset(root)
        store = MemoryStore(root)
        bus = EventBus(store)
        streamed = []
        bus.subscribe(lambda e: streamed.append(e))

        res = Orchestrator(root).run(_losing_hyp_file(root), window="out_sample",
                                     bus=bus)
        exp_id = res["experiment"].id
        hyp_id = res["hypothesis"].id

        types = [e.event_type for e in streamed]
        # the real lifecycle, in order
        assert types[0] == "experiment_started"
        assert types[-1] == "experiment_completed"
        # every emitted type is in the taxonomy
        assert set(types) <= EVENT_TYPES
        # the deterministic engine and the council agents all reported
        assert "backtest_completed" in types
        for agent in ("Historian", "Statistician", "Skeptic", "Reporter"):
            assert any(e.agent_name == agent for e in streamed), agent
        # a losing hypothesis must produce a skeptic rejection, before the report
        assert "skeptic_rejected" in types
        assert types.index("skeptic_rejected") < types.index("report_completed")
        # backtest completes before any statistical review starts
        assert types.index("backtest_completed") < types.index("skeptic_rejected")

        # persisted + correlated to the real experiment/hypothesis
        completed = [e for e in streamed if e.event_type == "experiment_completed"][0]
        assert completed.experiment_id == exp_id
        assert completed.hypothesis_id == hyp_id
        assert completed.metadata["verdict"] == res["experiment"].verdict

        # reconnect/replay: everything is durable and ordered by seq
        replayed = bus.replay(task_id=hyp_id)
        assert [e.event_type for e in replayed] == \
            [e.event_type for e in streamed if e.task_id == hyp_id]
        seqs = [e.seq for e in store.list_events()]
        assert seqs == sorted(seqs)
        store.close()


def test_untouched_engine_emits_no_events():
    """Running WITHOUT a bus must not persist any events (engine unchanged)."""
    with tempfile.TemporaryDirectory() as root:
        _dataset(root)
        Orchestrator(root).run(_losing_hyp_file(root), window="out_sample")
        store = MemoryStore(root)
        assert store.list_events() == []
        store.close()
