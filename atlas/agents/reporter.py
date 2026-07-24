"""The Reporter — turns evidence into a readable decision memo.

Deterministic template (must not alter the meaning of the evidence, Volume 2
§5.12). Writes a markdown memo to the vault and returns a DecisionRecord. An
optional narrator adds an in-session prose summary.
"""
from __future__ import annotations

import os

from .base import Agent, AgentContext
from ..schemas import DecisionRecord


class Reporter(Agent):
    name = "Reporter"
    nature = "llm"           # narration is generative; the facts are copied verbatim

    def __init__(self, narrator=None, vault: str = "vault"):
        super().__init__(narrator)
        self.vault = vault

    def memo(self, ctx: AgentContext) -> str:
        h, e = ctx.hypothesis, ctx.experiment
        m = e.metrics or {}
        prior = ctx.extras.get("decisions", [])
        lines = [
            f"# Decision memo — {h.title}",
            "",
            f"- **Hypothesis:** {h.id} v{h.version}  ·  prereg `{h.preregistration_hash}`",
            f"- **Data snapshot:** {e.data_snapshot_id}",
            f"- **Window:** {e.window}  ·  **Engine:** {e.engine_version}",
            f"- **Verdict:** {e.verdict}",
            "",
            "## Evidence",
        ]
        if m.get("trades"):
            lines += [
                f"- trades {m['trades']}, win rate {m.get('win_rate')}%",
                f"- profit factor {m.get('profit_factor')}, expectancy "
                f"{m.get('expectancy_r')}R, total {m.get('total_r')}R",
                f"- max drawdown {m.get('max_drawdown_r')}R",
            ]
            if e.monte_carlo and e.monte_carlo.get("bootstrap"):
                b = e.monte_carlo["bootstrap"]
                lines.append(f"- Monte Carlo: P(total<0) {b.get('p_total_negative')}, "
                             f"median expectancy {b.get('expectancy_r',{}).get('p50')}R")
        else:
            lines.append("- no trades")
        if prior:
            lines += ["", "## Council"]
            for d in prior:
                lines.append(f"- **{d.agent}** ({d.phase}): {d.decision} — {d.evidence}")
        if self.narrator:
            try:
                lines += ["", "## Summary", self.narrator(
                    f"Summarise the decision on {h.title} given: {m}")]
            except Exception:
                pass
        return "\n".join(lines) + "\n"

    def run(self, ctx: AgentContext) -> DecisionRecord:
        text = self.memo(ctx)
        d = os.path.join(self.vault, "memos")
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, f"{ctx.experiment.id}.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return self._record(ctx, "reporting", "memo_written", f"memo at {path}",
                            confidence="high", next_action="human review")
