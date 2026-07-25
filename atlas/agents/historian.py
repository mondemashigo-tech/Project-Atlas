"""The Historian — protects Atlas from re-testing dead ends (Volume 2 §5.9).

Compares a new hypothesis against the archive by pre-registration hash: an exact
match is a duplicate experiment (same identity fields), which should be merged
rather than re-run. Reads memory; emits a DecisionRecord.
"""
from __future__ import annotations

from .base import Agent, AgentContext
from ..schemas import DecisionRecord


class Historian(Agent):
    name = "Historian"
    nature = "hybrid"

    def __init__(self, store, narrator=None):
        super().__init__(narrator)
        self.store = store

    def run(self, ctx: AgentContext) -> DecisionRecord:
        h = ctx.hypothesis
        matches = [m for m in self.store.find_hypotheses_by_prereg(h.preregistration_hash)
                   if m["id"] != h.id]
        if matches:
            ids = ", ".join(m["id"] for m in matches[:5])
            buried = [m for m in matches if m["status"] == "GRAVEYARD"]
            note = f"duplicate of {ids}"
            if buried:
                note += f" (already in graveyard: {buried[0]['id']})"
            return self._record(ctx, "novelty", "duplicate", note,
                                confidence="high", next_action="merge with prior")
        return self._record(ctx, "novelty", "novel",
                            f"no prior hypothesis with prereg {h.preregistration_hash}",
                            confidence="medium", next_action="proceed")
