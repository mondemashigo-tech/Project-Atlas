"""Library-first orchestration for Atlas v1.

Thin functions that the CLI (and later a web/voice/Obsidian front-end) call. This
is the seam that will grow into the Kernel/Orchestrator; for now it wires the FX
research module to memory and the registry without any autonomy.
"""
from __future__ import annotations

import os
from typing import Optional, Tuple

from .research.fx import config as fx_config
from .research.fx import runner as fx_runner
from .research.fx import montecarlo as fx_mc
from .research.fx.metrics import verdict as fx_verdict
from .schemas import (Hypothesis, ExperimentRecord, new_id,
                      ATLAS_ENGINE_VERSION)
from .memory import MemoryStore


def run_experiment(hyp_path: str, root: str = ".", window: str = "out_sample",
                   mc: bool = True) -> Tuple[Hypothesis, ExperimentRecord, dict]:
    """Load an FX hypothesis, freeze it (pre-registration), run the deterministic
    engine, and record an immutable ExperimentRecord in memory (+ Obsidian mirror).
    Returns (hypothesis, experiment_record, verdict). Produces no signals."""
    cfg = fx_config.load(hyp_path)
    hyp = Hypothesis.from_fx_config(cfg).freeze().ensure_valid()

    store = MemoryStore(root)
    try:
        store.write_hypothesis(hyp)
        datasets = os.path.join(root, "datasets")
        results = fx_runner.run_hypothesis(cfg, datasets)
        m = results[window]["metrics"]
        v = fx_verdict(m, cfg.get("criteria", {}))
        mc_res = fx_mc.analyze(results[window]["trades"]) if mc else None
        rec = ExperimentRecord(
            id=new_id("EXP"),
            hypothesis_id=hyp.id,
            hypothesis_version=hyp.version,
            engine_version=ATLAS_ENGINE_VERSION,
            data_snapshot_id=None,          # wired in Milestone 2 (DataSnapshot)
            window=window,
            metrics=m,
            verdict=v.get("result"),
            monte_carlo=mc_res,
        )
        store.write_experiment(rec, hyp)
        return hyp, rec, v
    finally:
        store.close()
