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
from .snapshots import make_snapshot


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

        # Provenance: snapshot the exact data this experiment sees.
        snap = make_snapshot(datasets, cfg["markets"], cfg["timeframes"]["entry"],
                             source=f"datasets:{os.path.abspath(datasets)}")
        snap = store.write_snapshot(snap)

        results = fx_runner.run_hypothesis(cfg, datasets)
        m = results[window]["metrics"]
        v = fx_verdict(m, cfg.get("criteria", {}))
        mc_res = fx_mc.analyze(results[window]["trades"]) if mc else None
        rec = ExperimentRecord(
            id=new_id("EXP"),
            hypothesis_id=hyp.id,
            hypothesis_version=hyp.version,
            engine_version=ATLAS_ENGINE_VERSION,
            data_snapshot_id=snap.id,
            window=window,
            metrics=m,
            verdict=v.get("result"),
            monte_carlo=mc_res,
        )
        store.write_experiment(rec, hyp)
        # Consume the false-discovery budget only for out-of-sample looks.
        if window == "out_sample" and snap.id:
            store.record_oos_test(snap.id, window, hyp.id, hyp.preregistration_hash)
        return hyp, rec, v
    finally:
        store.close()


def hypothesis_trades(hyp_path: str, root: str = ".", window: str = "full") -> list:
    """All realised trades for a hypothesis across its markets (for portfolio
    analysis)."""
    from .research.fx.strategies.base import Strategy
    from .research.fx.backtester import run as run_bt
    from .research.fx import data as fx_data, splits as fx_splits, datasources

    cfg = fx_config.load(hyp_path)
    datasets = os.path.join(root, "datasets")
    entry_tf = cfg["timeframes"]["entry"]
    context = datasources.build_context(cfg, datasets)
    spread = cfg.get("costs", {}).get("spread_pips", 1.0)
    comm = cfg.get("costs", {}).get("commission_r", 0.0)
    mtpd = cfg["risk"].get("max_trades_per_day", 3)
    out = []
    for sym in cfg["markets"]:
        try:
            df = fx_data.load_symbol(datasets, sym, entry_tf)
        except FileNotFoundError:
            continue
        if window == "in_sample":
            df = fx_splits.in_sample(df, cfg)
        elif window == "out_sample":
            df = fx_splits.out_sample(df, cfg)
        if len(df) < 300:
            continue
        strat = Strategy.create(cfg)
        out.extend(run_bt(sym, df, strat, spread_pips=spread, commission_r=comm,
                          max_trades_per_day=mtpd, context=context))
    return out


def regime_report(hyp_path: str, root: str = ".", window: str = "full") -> dict:
    """Per-symbol performance bucketed by market regime at entry (Volume 3 §12).
    Returns {symbol: {regime_label: metrics}}."""
    from .research.fx.strategies.base import Strategy
    from .research.fx.backtester import run as run_bt
    from .research.fx import data as fx_data, splits as fx_splits
    from .research.fx import regime as fx_regime, datasources

    cfg = fx_config.load(hyp_path)
    datasets = os.path.join(root, "datasets")
    entry_tf = cfg["timeframes"]["entry"]
    context = datasources.build_context(cfg, datasets)
    spread = cfg.get("costs", {}).get("spread_pips", 1.0)
    comm = cfg.get("costs", {}).get("commission_r", 0.0)
    mtpd = cfg["risk"].get("max_trades_per_day", 3)

    out = {}
    for sym in cfg["markets"]:
        try:
            df = fx_data.load_symbol(datasets, sym, entry_tf)
        except FileNotFoundError:
            continue
        if window == "in_sample":
            df = fx_splits.in_sample(df, cfg)
        elif window == "out_sample":
            df = fx_splits.out_sample(df, cfg)
        if len(df) < 300:
            continue
        strat = Strategy.create(cfg)
        trades = run_bt(sym, df, strat, spread_pips=spread, commission_r=comm,
                        max_trades_per_day=mtpd, context=context)
        out[sym] = fx_regime.breakdown(trades, df)
    return out
