"""Performance metrics. Everything is in R units (P/L per unit of risk), which
is scale-invariant, so results don't depend on account size or position sizing."""
from __future__ import annotations

from typing import List
import math

from .backtester import Trade


def compute(trades: List[Trade]) -> dict:
    n = len(trades)
    if n == 0:
        return {"trades": 0}
    r = [t.pnl_r for t in trades]
    wins = [x for x in r if x > 0]
    losses = [x for x in r if x < 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    total = sum(r)

    # Equity curve in R, and max drawdown off the running peak.
    equity, peak, max_dd = 0.0, 0.0, 0.0
    for x in r:
        equity += x
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)

    mean = total / n
    sd = math.sqrt(sum((x - mean) ** 2 for x in r) / n) if n > 1 else 0.0
    return {
        "trades": n,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / n * 100, 2),
        "expectancy_r": round(mean, 4),
        "total_r": round(total, 2),
        "profit_factor": round(gross_win / gross_loss, 3) if gross_loss else float("inf"),
        "avg_win_r": round(gross_win / len(wins), 3) if wins else 0.0,
        "avg_loss_r": round(-gross_loss / len(losses), 3) if losses else 0.0,
        "max_drawdown_r": round(max_dd, 2),
        "largest_win_r": round(max(r), 3),
        "largest_loss_r": round(min(r), 3),
        "sharpe_per_trade": round(mean / sd, 3) if sd else 0.0,
    }


def verdict(metrics: dict, criteria: dict) -> dict:
    """Judge metrics against pre-registered success/failure criteria."""
    if metrics.get("trades", 0) == 0:
        return {"result": "NO_TRADES", "reasons": ["no trades generated"]}
    succ = criteria.get("success", {})
    fail = criteria.get("failure", {})
    pf = metrics["profit_factor"]
    exp = metrics["expectancy_r"]

    passed, failed = [], []
    if "profit_factor" in succ:
        (passed if pf >= succ["profit_factor"] else failed).append(
            f"PF {pf} vs >= {succ['profit_factor']}")
    if "min_trades" in succ:
        (passed if metrics["trades"] >= succ["min_trades"] else failed).append(
            f"trades {metrics['trades']} vs >= {succ['min_trades']}")
    if succ.get("expectancy") == "positive":
        (passed if exp > 0 else failed).append(f"expectancy {exp} vs > 0")

    is_fail = ("profit_factor" in fail and pf < fail["profit_factor"]) or \
              (fail.get("expectancy") == "negative" and exp < 0)
    result = "PASS" if not failed else ("REJECT" if is_fail else "INCONCLUSIVE")
    return {"result": result, "passed": passed, "failed": failed}
