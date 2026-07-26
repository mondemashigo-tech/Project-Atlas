"""The governed research loop (Volume 5 §5, §14).

A cycle: the Scientist proposes variants, prioritises them, and — at autonomy
level 3+ — the Orchestrator tests the top novel ones through the full council
ladder, recording every result. Failures are buried; full-ladder passes become
NON-capital registry candidates. A research report is written each cycle.

Governance, enforced here in code:
- **Autonomy ceiling L4.** `autonomy_level > MAX_AUTONOMY` is refused. L≤2 only
  proposes (no autonomous testing); L3+ tests; L4 also self-queues the next batch.
- **Sandbox cap.** At most `max_per_cycle` experiments per cycle.
- **No autonomous deployment.** The loop never promotes a strategy to
  paper/micro/live — that stays a human-gated registry action at every level.
- **OOS budget.** Enforced by the Orchestrator (a burned holdout blocks a pass).
"""
from __future__ import annotations

import os
import tempfile
from typing import Dict, List, Optional

import yaml

from ..agents import Scientist
from ..kernel import Orchestrator
from ..memory import MemoryStore
from ..risk import RiskPolicy
from ..research.fx import config as fx_config

MAX_AUTONOMY = 4       # L4 (sandbox self-queuing) is the ceiling — never exceed.


class ResearchLoop:
    def __init__(self, root: str = ".", autonomy_level: int = 3,
                 max_per_cycle: int = 5, risk_policy: Optional[RiskPolicy] = None,
                 data_utc_offset: float = 0):
        if autonomy_level > MAX_AUTONOMY:
            raise ValueError(f"autonomy level {autonomy_level} exceeds ceiling "
                             f"L{MAX_AUTONOMY} (sandbox self-queuing). Refused.")
        self.root = root
        self.autonomy_level = autonomy_level
        self.max_per_cycle = max_per_cycle
        self.risk_policy = risk_policy
        self.data_utc_offset = data_utc_offset

    def run_cycle(self, base_hyp_path: str, grid: Dict[str, list] = None,
                  window: str = "out_sample") -> dict:
        base = fx_config.load(base_hyp_path)
        sci = Scientist()
        store = MemoryStore(self.root)
        try:
            scored = sci.prioritise(sci.propose(base, grid), store)
        finally:
            store.close()
        selected = [cfg for cfg, _s, reason in scored if reason == "novel"][:self.max_per_cycle]

        report = {"base": base["name"], "autonomy_level": self.autonomy_level,
                  "proposed": len(scored), "selected": len(selected),
                  "tested": [], "candidates": [], "buried": []}

        if self.autonomy_level < 3:
            report["note"] = "autonomy < L3 — proposals only, no autonomous testing"
            report["proposals"] = [c["name"] for c in selected]
            self._write_report(report)
            return report

        orch = Orchestrator(self.root)
        for cfg in selected:
            clean = {k: v for k, v in cfg.items() if not k.startswith("_")}
            fd, path = tempfile.mkstemp(suffix=".yaml", dir=self.root)
            os.close(fd)
            with open(path, "w") as f:
                yaml.safe_dump(clean, f)
            try:
                res = orch.run(path, window=window, risk_policy=self.risk_policy,
                               data_utc_offset=self.data_utc_offset)
            finally:
                os.remove(path)
            report["tested"].append({
                "name": cfg["name"], "verdict": res["experiment"].verdict,
                "reached": res["reached_layer"], "advanced": res["advanced"]})
            if res["advanced"] and res.get("candidate_id"):
                report["candidates"].append({"name": cfg["name"],
                                             "candidate_id": res["candidate_id"]})

        store = MemoryStore(self.root)
        try:
            report["buried"] = [g["title"] for g in store.list_graveyard()]
        finally:
            store.close()
        self._write_report(report)
        return report

    def run(self, base_hyp_path: str, cycles: int = 1,
            grids: List[Dict[str, list]] = None, window: str = "out_sample") -> List[dict]:
        """Run several cycles. At L4 the loop self-queues successive batches
        (different grids); duplicates are skipped by the Scientist's novelty check,
        so it never re-tests a dead end."""
        out = []
        for i in range(cycles):
            grid = grids[i] if grids and i < len(grids) else None
            out.append(self.run_cycle(base_hyp_path, grid=grid, window=window))
            if self.autonomy_level < 4:
                break            # only L4 self-queues beyond one cycle
        return out

    def _write_report(self, report: dict) -> str:
        d = os.path.join(self.root, "vault", "reports")
        os.makedirs(d, exist_ok=True)
        from ..schemas import utcnow_iso
        ts = utcnow_iso().replace(":", "").replace("-", "")
        path = os.path.join(d, f"cycle_{ts}.md")
        lines = [f"# Research cycle — {report['base']} (L{report['autonomy_level']})",
                 "",
                 f"- proposed: {report['proposed']}  ·  selected: {report['selected']}",
                 f"- tested: {len(report['tested'])}  ·  "
                 f"candidates: {len(report['candidates'])}", ""]
        for t in report["tested"]:
            lines.append(f"  - {t['name']}: {t['verdict']} "
                         f"(reached {t['reached']}, advanced={t['advanced']})")
        if report["candidates"]:
            lines += ["", "## Candidates registered (NON-capital, human-gated)"]
            for c in report["candidates"]:
                lines.append(f"  - {c['name']} -> {c['candidate_id']}")
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        report["report_path"] = path
        return path
