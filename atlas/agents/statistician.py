"""The Statistician — quantifies whether a result is likely real or random.

Deterministic (nature=code). Uses the Monte Carlo bootstrap already attached to
the experiment to judge significance: if the 5th–95th percentile band of total R
sits entirely on one side of zero, the edge is 'significant' at that level; if it
straddles zero it is 'not_significant'. Also checks sample adequacy. It does not
gate — it reports a confidence signal the Skeptic and council use (Volume 2 §5.5).
"""
from __future__ import annotations

from .base import Agent, AgentContext
from ..schemas import DecisionRecord

_TARGET_N = 100


class Statistician(Agent):
    name = "Statistician"
    nature = "code"

    def run(self, ctx: AgentContext) -> DecisionRecord:
        m = ctx.experiment.metrics or {}
        n = m.get("trades", 0)
        checks = [f"n={n}", f"expectancy={m.get('expectancy_r')}R",
                  f"sharpe/trade={m.get('sharpe_per_trade')}"]

        if n == 0:
            return self._record(ctx, "statistical_validity", "no_data",
                                "no trades", confidence="high")
        if n < _TARGET_N:
            return self._record(ctx, "statistical_validity", "insufficient_sample",
                                f"n={n} < {_TARGET_N}", confidence="low")

        mc = ctx.experiment.monte_carlo
        decision, conf = "not_significant", "medium"
        if mc and mc.get("bootstrap"):
            tot = mc["bootstrap"].get("total_r", {})
            p5, p95 = tot.get("p5"), tot.get("p95")
            checks.append(f"total_r 5-95%: [{p5}, {p95}]")
            if p5 is not None and p95 is not None:
                if p5 > 0:
                    decision, conf = "significant_positive", "high"
                elif p95 < 0:
                    decision, conf = "significant_negative", "high"
                else:
                    decision, conf = "not_significant", "medium"
        else:
            checks.append("no Monte Carlo band")
            conf = "low"

        return self._record(ctx, "statistical_validity", decision,
                            "; ".join(checks), confidence=conf)
