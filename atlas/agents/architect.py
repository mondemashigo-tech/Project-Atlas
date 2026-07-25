"""The Architect — observes the lab and proposes structural improvements
(Volume 2 §5.11). It never edits the system itself; it surfaces bottlenecks and
health signals for a human to act on. Deterministic observations + optional
in-session narration.
"""
from __future__ import annotations

from typing import List


class Architect:
    name = "Architect"
    nature = "llm"

    def __init__(self, narrator=None):
        self.narrator = narrator

    def observe(self, store) -> dict:
        c = store.counts()
        tally = store.decision_tally()
        graveyard_rate = (c["graveyard"] / c["hypotheses"]) if c["hypotheses"] else 0.0
        return {"counts": c, "decisions": tally,
                "graveyard_rate": round(graveyard_rate, 3)}

    def suggestions(self, obs: dict) -> List[str]:
        s = []
        c = obs["counts"]
        if c["hypotheses"] == 0:
            return ["No hypotheses yet — start by running experiments."]
        if obs["graveyard_rate"] < 0.3:
            s.append("Low rejection rate — the Skeptic may be too lenient, or ideas "
                     "are pre-filtered. A healthy lab rejects most hypotheses.")
        else:
            s.append("Healthy rejection rate — most ideas die, as they should.")
        vetoes = sum(v for k, v in obs["decisions"].items() if k.endswith(":veto"))
        if vetoes == 0 and c["experiments"] > 5:
            s.append("No vetoes recorded despite several experiments — check the "
                     "risk/skeptic thresholds are actually biting.")
        s.append("Next structural step per roadmap: knowledge ingestion (M7) then "
                 "the governed autonomy loop (M8).")
        return s

    def report(self, store) -> str:
        obs = self.observe(store)
        lines = ["ARCHITECT — lab health",
                 f"  hypotheses={obs['counts']['hypotheses']} "
                 f"experiments={obs['counts']['experiments']} "
                 f"graveyard={obs['counts']['graveyard']} "
                 f"(rate {obs['graveyard_rate']})"]
        for s in self.suggestions(obs):
            lines.append(f"  - {s}")
        if self.narrator:
            try:
                lines.append("  " + self.narrator(f"Architect view of {obs}"))
            except Exception:
                pass
        return "\n".join(lines) + "\n"
