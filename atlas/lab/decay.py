"""Decay / drift monitoring (Volume 5 §12).

An edge that worked can fade. Given a strategy's historical expectancy and its
recent realised trades, flag when recent performance has decayed enough to warrant
demotion or retirement. Without live fills there is nothing to monitor yet — the
capability exists and reports honestly that it is idle.
"""
from __future__ import annotations

from typing import List


def decay_check(historical_expectancy_r: float, recent_trades: List,
                drop_threshold: float = 0.5) -> dict:
    """Compare recent expectancy to the historical figure. `drifted` is True when
    recent expectancy falls below `drop_threshold` × historical (or goes negative
    while the strategy was supposed to be positive)."""
    if not recent_trades:
        return {"status": "no_recent_data", "drifted": False}
    recent = sum(t.pnl_r for t in recent_trades) / len(recent_trades)
    drifted = False
    if historical_expectancy_r > 0:
        drifted = recent < historical_expectancy_r * drop_threshold
    else:
        drifted = recent < historical_expectancy_r
    return {
        "status": "ok",
        "historical_expectancy_r": round(historical_expectancy_r, 4),
        "recent_expectancy_r": round(recent, 4),
        "delta_r": round(recent - historical_expectancy_r, 4),
        "n_recent": len(recent_trades),
        "drifted": bool(drifted),
        "recommendation": "demote/retire — investigate regime change" if drifted else "hold",
    }


def monitor(registry) -> List[dict]:
    """Check every executable registry strategy for decay. Needs live fills fed
    back into monitoring_state; until then, reports idle."""
    out = []
    for rec in registry.list():
        if rec.status in ("paper", "micro_live", "live"):
            recent = rec.monitoring_state.get("recent_trades", [])
            hist = rec.monitoring_state.get("historical_expectancy_r", 0.0)
            res = decay_check(hist, recent)
            out.append({"strategy_id": rec.strategy_id, "status": rec.status, **res})
    return out
