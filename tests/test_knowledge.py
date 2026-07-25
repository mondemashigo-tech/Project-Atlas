"""Milestone 7 tests: Librarian ingestion + Scientist proposal/prioritisation."""
import os
import tempfile

from atlas.agents import Librarian, Scientist
from atlas.memory import MemoryStore
from atlas.schemas import Hypothesis


_BASE = {
    "name": "base", "version": "1.0", "template": "trend_continuation",
    "markets": ["GBPUSD"], "timeframes": {"bias": "H1", "entry": "M5"},
    "session": {"start": "00:00", "end": "23:59", "tz": "UTC"},
    "weekdays": [0, 1, 2, 3, 4], "trend": {"ema_fast": 50, "ema_slow": 200},
    "entry": {"pullback_ema": 20},
    "risk": {"stop": {"atr_mult": 1.0, "atr_period": 14, "swing_lookback": 20},
             "target_r": 2.0, "max_trades_per_day": 3},
    "costs": {"spread_pips": 1.0, "commission_r": 0.03},
    "criteria": {"success": {}, "failure": {}},
    "data": {"in_sample": ["2025-01-01", "2025-06-30"],
             "out_sample": ["2025-07-01", "2025-12-31"]},
}


# ---- Librarian -------------------------------------------------------------

def test_librarian_tags_and_stores():
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "note.md")
        with open(src, "w") as f:
            f.write("# London session breakouts\n\n"
                    "Momentum and trend continuation tend to work during the "
                    "London open. Watch volatility (ATR) and manage risk with a "
                    "stop loss.\n")
        store = MemoryStore(d)
        notes = Librarian().ingest(src, store)
        assert len(notes) == 1
        tags = set(notes[0].topic_tags)
        assert {"trend", "session"} <= tags        # keyword tagging worked
        assert os.path.exists(os.path.join(d, "vault", "knowledge", f"{notes[0].id}.md"))
        store.close()


def test_librarian_ingests_directory():
    with tempfile.TemporaryDirectory() as d:
        for i in range(3):
            with open(os.path.join(d, f"n{i}.txt"), "w") as f:
                f.write(f"Concept {i}: mean reversion fades overbought moves.")
        store = MemoryStore(d)
        notes = Librarian().ingest(d, store)
        assert len(notes) == 3
        assert all("mean_reversion" in n.topic_tags for n in notes)
        store.close()


# ---- Scientist -------------------------------------------------------------

def test_scientist_proposes_variants():
    variants = Scientist().propose(_BASE)
    assert len(variants) > 0
    names = [v["name"] for v in variants]
    assert all(n.startswith("base__") for n in names)
    # each variant differs from the base spec
    assert any(v["risk"]["target_r"] != 2.0 or v["trend"]["ema_fast"] != 50
               for v in variants)


def test_scientist_deprioritises_known_ideas():
    with tempfile.TemporaryDirectory() as d:
        store = MemoryStore(d)
        variants = Scientist().propose(_BASE)
        # Register one variant as already-tested (write its hypothesis).
        known = Hypothesis.from_fx_config(variants[0]).freeze()
        store.write_hypothesis(known)
        scored = Scientist().prioritise(variants, store)
        # The known variant must rank at/near the bottom (novelty 0).
        bottom = scored[-1]
        assert bottom[2] in ("already tested", "in graveyard — skip")
        # novel ones outrank known ones
        assert scored[0][1] >= bottom[1]
        store.close()
