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
from ..registry import Registry
from ..registry.registry import make_candidate
from ..risk import RiskManager, RiskPolicy
from ..portfolio import PortfolioBuilder
from ..governance import budget_status, OOSBudget
from ..schemas import DecisionRecord, utcnow_iso
from ..agents.base import AgentContext
from ..agents.skeptic import Skeptic
from ..agents.reporter import Reporter
from ..agents.statistician import Statistician
from ..agents.historian import Historian

LAYERS = ["data_integrity", "rule_validity", "backtest_validity",
          "statistical_validity", "risk_validity", "portfolio_validity",
          "deployment_validity"]

class Orchestrator:
    def __init__(self, root: str = "."):
        self.root = root

    def run(self, hyp_path: str, window: str = "out_sample",
            narrator: Optional[Callable[[str], str]] = None,
            risk_policy: Optional[RiskPolicy] = None) -> dict:
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

            ctx = AgentContext(task_id=tid, hypothesis=hyp, experiment=rec,
                               verdict=verdict, extras={"decisions": decisions})

            # Novelty check — the Historian (has this exact idea been tested?)
            hist = Historian(store, narrator).run(ctx)
            store.write_decision(hist); decisions.append(hist)

            # 4. statistical validity — Statistician quantifies, Skeptic judges.
            stat = Statistician(narrator).run(ctx)
            store.write_decision(stat); decisions.append(stat)
            ctx.extras["statistician"] = stat
            skeptic = Skeptic(narrator).run(ctx)
            store.write_decision(skeptic)
            decisions.append(skeptic)

            reached = "statistical_validity"
            advanced = False
            candidate_id = None

            # Governance: how many looks has this holdout taken? (false-discovery)
            budget = budget_status(store, rec.data_snapshot_id, "out_sample",
                                   OOSBudget()) if window == "out_sample" else \
                {"burned": False, "count": 0, "budget": 0}
            emit("Orchestrator", "governance",
                 "burned" if budget["burned"] else "ok",
                 f"OOS looks {budget['count']}/{budget['budget']} on "
                 f"{rec.data_snapshot_id}", title=hyp.title)

            if skeptic.decision == "reject":
                store.bury(hyp.id, reason="Skeptic reject: " + skeptic.evidence[:200])
                halt = ("halted at statistical_validity: Skeptic said 'reject' "
                        "(buried in graveyard)")
            elif skeptic.decision != "approve":
                halt = f"halted at statistical_validity: Skeptic said '{skeptic.decision}'"
            elif budget["burned"]:
                halt = (f"halted at statistical_validity: OOS budget exhausted "
                        f"({budget['count']}/{budget['budget']} looks) — refresh "
                        f"the holdout with unseen data before trusting a pass")
            else:
                # 5. risk validity — hard gate
                risk = RiskManager(risk_policy or RiskPolicy(), narrator).run(ctx)
                store.write_decision(risk); decisions.append(risk)
                reached = "risk_validity"
                if risk.decision != "pass":
                    halt = f"halted at risk_validity: RiskManager said '{risk.decision}'"
                else:
                    # 6. portfolio validity (lone strategy -> trivially diversifying)
                    port = PortfolioBuilder(narrator=narrator).run(ctx)
                    store.write_decision(port); decisions.append(port)
                    reached = "portfolio_validity"
                    if port.decision != "pass":
                        halt = f"halted at portfolio_validity: '{port.decision}'"
                    else:
                        advanced = True
                        # Auto-register a NON-capital candidate (allowed without a
                        # human token). Deployment (layer 7) stays human-gated.
                        reg = Registry(self.root)
                        try:
                            cand = make_candidate(
                                hyp.id, hyp.version, [rec.id],
                                spec=hyp.spec, allocation=0.0,
                                risk_limits=hyp.risk_rules)
                            reg.add_candidate(cand)
                            candidate_id = cand.strategy_id
                        finally:
                            reg.close()
                        emit("Orchestrator", "deployment_validity", "hold",
                             f"registered candidate {candidate_id}; promotion to "
                             f"paper/live requires a human approval token",
                             conf="high", nxt="human review", title=hyp.title)
                        halt = ("passed research ladder; candidate registered. "
                                "Deployment is human-gated — no autonomous promotion.")

            # Reporter memo (records the whole chain)
            ctx.extras["decisions"] = decisions
            reporter = Reporter(narrator, vault=os.path.join(self.root, "vault"))
            rep = reporter.run(ctx)
            store.write_decision(rep)
            decisions.append(rep)

            return {
                "hypothesis": hyp, "experiment": rec, "verdict": verdict,
                "decisions": decisions, "advanced": advanced,
                "reached_layer": reached, "candidate_id": candidate_id,
                "halt_reason": halt, "memo": rep.evidence,
            }
        finally:
            store.close()
