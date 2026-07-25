"""The Risk Manager — a deterministic hard gate.

Assesses whether a strategy is *dangerous* even when profitable, against a
RiskPolicy: historical drawdown ceiling, worst-case daily loss (trades/day × 1R),
per-trade risk fraction, and minimum sample. Has authority to veto (Volume 2 §5.7).
"""
from __future__ import annotations

from ..agents.base import Agent, AgentContext
from ..schemas import DecisionRecord
from .policy import RiskPolicy


class RiskManager(Agent):
    name = "RiskManager"
    nature = "code"

    def __init__(self, policy: RiskPolicy = None, narrator=None):
        super().__init__(narrator)
        self.policy = policy or RiskPolicy()

    def run(self, ctx: AgentContext) -> DecisionRecord:
        p = self.policy
        m = ctx.experiment.metrics or {}
        rr = ctx.hypothesis.risk_rules or {}
        checks, concerns = [], []

        maxdd = m.get("max_drawdown_r")
        if maxdd is not None:
            checks.append(f"maxDD={maxdd}R")
            if maxdd > p.max_drawdown_r:
                concerns.append(f"max drawdown {maxdd}R > {p.max_drawdown_r}R limit")

        mtpd = rr.get("max_trades_per_day", 3)
        checks.append(f"maxTradesPerDay={mtpd}")
        if mtpd > p.max_daily_loss_r:
            concerns.append(f"worst-case daily loss ~{mtpd}R > {p.max_daily_loss_r}R")

        risk_pct = rr.get("risk_pct", 1.0) / 100.0     # 1.0 -> 1%
        checks.append(f"riskPerTrade={risk_pct:.3%}")
        if risk_pct > p.risk_per_trade_max:
            concerns.append(f"per-trade risk {risk_pct:.2%} > {p.risk_per_trade_max:.2%}")

        trades = m.get("trades", 0)
        if trades < p.min_trades:
            concerns.append(f"thin sample ({trades} < {p.min_trades}) — risk profile unreliable")

        evidence = "; ".join(checks) + ((" | " + "; ".join(concerns)) if concerns else "")
        decision = "veto" if concerns else "pass"
        nxt = "block deployment" if concerns else "advance to portfolio review"
        if self.narrator:
            try:
                evidence += " || " + self.narrator(f"Risk view: {evidence}")
            except Exception:
                pass
        return self._record(ctx, "risk_validity", decision, evidence,
                            confidence="high", next_action=nxt)
