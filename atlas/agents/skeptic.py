"""The Skeptic — assumes every strategy is guilty until proven otherwise.

Deterministic rigor checks (the decision is code, not an LLM). It runs concrete
overfitting/fragility tests on an experiment and either concurs with a rejection,
vetoes a too-fragile "pass", or approves advancement. An optional narrator adds
in-session commentary but cannot change the ruling.
"""
from __future__ import annotations

from .base import Agent, AgentContext
from ..schemas import DecisionRecord

# Thresholds (conservative; prefer false negatives — Volume 1 §9).
_MIN_TRADES = 100          # below this, sample is thin
_MAX_P_TOTAL_NEG = 0.35    # bootstrap prob the edge is actually negative
_MIN_PF = 1.0


class Skeptic(Agent):
    name = "Skeptic"
    nature = "code"

    def run(self, ctx: AgentContext) -> DecisionRecord:
        m = ctx.experiment.metrics or {}
        verdict = (ctx.verdict or {}).get("result")
        checks, concerns = [], []

        trades = m.get("trades", 0)
        if trades == 0:
            return self._record(ctx, "statistical_validity", "reject",
                                "no trades generated", confidence="high",
                                next_action="graveyard")

        # sample size
        min_req = ctx.hypothesis.success_criteria.get("min_trades", _MIN_TRADES)
        if trades < min_req:
            concerns.append(f"thin sample ({trades} < {min_req})")
        checks.append(f"trades={trades}")

        # profit factor floor
        pf = m.get("profit_factor", 0)
        if pf < _MIN_PF:
            concerns.append(f"PF {pf} < {_MIN_PF} (not profitable)")
        checks.append(f"PF={pf}")

        # Monte Carlo: is the edge likely a coin flip?
        mc = ctx.experiment.monte_carlo
        if mc and mc.get("bootstrap"):
            p_neg = mc["bootstrap"].get("p_total_negative")
            checks.append(f"P(total<0)={p_neg}")
            if p_neg is not None and p_neg > _MAX_P_TOTAL_NEG:
                concerns.append(f"P(total<0)={p_neg} > {_MAX_P_TOTAL_NEG} "
                                f"(edge may be noise)")
        else:
            concerns.append("no Monte Carlo evidence")

        evidence = "; ".join(checks) + ((" | concerns: " + "; ".join(concerns))
                                        if concerns else "")

        if verdict != "PASS":
            decision, conf, nxt = "reject", "high", "graveyard"
        elif concerns:
            decision, conf, nxt = "veto", "high", "revise or gather more data"
        else:
            decision, conf, nxt = "approve", "medium", "advance to risk review"

        if self.narrator:                    # in-session LLM commentary (optional)
            try:
                evidence += " || " + self.narrator(
                    f"Skeptic notes on {ctx.hypothesis.title}: {evidence}")
            except Exception:
                pass
        return self._record(ctx, "statistical_validity", decision, evidence,
                            confidence=conf, next_action=nxt)
