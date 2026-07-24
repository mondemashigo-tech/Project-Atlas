"""Agent contracts.

An agent takes an AgentContext and returns a DecisionRecord. Deterministic agents
(nature='code') compute their ruling from the evidence. LLM agents
(nature='llm') carry an optional `narrator` callable that, when running
in-session, adds human-language reasoning — but the *decision* of a code agent is
never produced by an LLM (Volume 2/3 guardrail: no agent invents numbers).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from ..schemas import Hypothesis, ExperimentRecord, DecisionRecord


@dataclass
class AgentContext:
    task_id: str
    hypothesis: Hypothesis
    experiment: ExperimentRecord
    verdict: dict = field(default_factory=dict)
    extras: dict = field(default_factory=dict)     # wf, mc, prior decisions, ...


class Agent:
    name = "agent"
    nature = "code"          # code | llm | hybrid

    def __init__(self, narrator: Optional[Callable[[str], str]] = None):
        # narrator(prompt)->text is supplied only when running in-session; unused
        # by deterministic agents' rulings.
        self.narrator = narrator

    def run(self, ctx: AgentContext) -> DecisionRecord:
        raise NotImplementedError

    def _record(self, ctx: AgentContext, phase: str, decision: str,
                evidence: str, confidence: str = "medium",
                next_action: str = "", input_summary: str = "") -> DecisionRecord:
        return DecisionRecord(
            task_id=ctx.task_id, agent=self.name, phase=phase,
            input_summary=input_summary or ctx.hypothesis.title,
            evidence=evidence, decision=decision,
            confidence=confidence, next_action=next_action)
