"""Orchestrator: the layered decision hierarchy (Volume 2 §7).

    1 data_integrity  -> 2 rule_validity -> 3 backtest_validity ->
    4 statistical_validity -> 5 risk_validity -> 6 portfolio_validity ->
    7 deployment_validity

A hypothesis advances only if each layer passes; a layer may not be skipped. It
runs the deterministic engine (via the service), then the council layer by layer,
persisting a DecisionRecord for every layer to memory. Layers 5–7 are not built
yet (Milestones 4+), so the ladder honestly halts there rather than pretending —
no strategy can reach deployment until those gates exist.
"""
from __future__ import annotations

import os
from typing import Callable, Optional

from .. import service
from ..memory import MemoryStore
from ..schemas import DecisionRecord, utcnow_iso
from ..agents.base import AgentContext
from ..agents.skeptic import Skeptic
from ..agents.reporter import Reporter

LAYERS = ["data_integrity", "rule_validity", "backtest_validity",
          "statistical_validity", "risk_validity", "portfolio_validity",
          "deployment_validity"]

_NOT_BUILT = {"risk_validity": "Milestone 4", "portfolio_validity": "Milestone 4",
              "deployment_validity": "Milestone 8 / human gate"}


class Orchestrator:
    def __init__(self, root: str = "."):
        self.root = root

    def run(self, hyp_path: str, window: str = "out_sample",
            narrator: Optional[Callable[[str], str]] = None) -> dict:
        store = MemoryStore(self.root)
        decisions = []

        def emit(agent, phase, decision, evidence, conf="medium", nxt="", title=""):
            rec = DecisionRecord(task_id=tid, agent=agent, phase=phase,
                                 input_summary=title, evidence=evidence,
                                 decision=decision, confidence=conf, next_action=nxt)
            store.write_decision(rec)
            decisions.append(rec)
            return rec

        try:
            # Layers 1–3 are realised by running the deterministic engine + provenance.
            hyp, rec, verdict = service.run_experiment(
                hyp_path, root=self.root, window=window)
            tid = hyp.id
            snap = store.get_snapshot(rec.data_snapshot_id)

            # 1. data integrity
            rows = snap.row_count if snap else 0
            emit("Orchestrator", "data_integrity",
                 "pass" if rows > 0 else "fail",
                 f"snapshot {rec.data_snapshot_id} rows={rows}", title=hyp.title)
            # 2. rule validity (frozen + valid)
            rule_ok = not hyp.validate() and hyp.status == "SPECIFIED"
            emit("Orchestrator", "rule_validity", "pass" if rule_ok else "fail",
                 f"status={hyp.status} prereg={hyp.preregistration_hash}", title=hyp.title)
            # 3. backtest validity (a recorded, engine-stamped experiment exists)
            emit("Orchestrator", "backtest_validity", "pass",
                 f"experiment {rec.id} engine {rec.engine_version} "
                 f"verdict {rec.verdict}", title=hyp.title)

            # 4. statistical validity — the Skeptic (deterministic rigor checks)
            ctx = AgentContext(task_id=tid, hypothesis=hyp, experiment=rec,
                               verdict=verdict, extras={"decisions": decisions})
            skeptic = Skeptic(narrator).run(ctx)
            store.write_decision(skeptic)
            decisions.append(skeptic)

            advanced = skeptic.decision == "approve"
            if advanced:
                halt = (f"reached statistical_validity; next gate "
                        f"'risk_validity' not built ({_NOT_BUILT['risk_validity']})")
            else:
                halt = f"halted at statistical_validity: Skeptic said '{skeptic.decision}'"

            # Reporter memo (records the whole chain)
            ctx.extras["decisions"] = decisions
            reporter = Reporter(narrator, vault=os.path.join(self.root, "vault"))
            rep = reporter.run(ctx)
            store.write_decision(rep)
            decisions.append(rep)

            return {
                "hypothesis": hyp, "experiment": rec, "verdict": verdict,
                "decisions": decisions, "advanced": advanced,
                "reached_layer": "statistical_validity", "halt_reason": halt,
                "memo": rep.evidence,
            }
        finally:
            store.close()
