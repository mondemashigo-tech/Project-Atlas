"""Render a plain-text research report for a hypothesis run."""
from __future__ import annotations

from .metrics import verdict


def _block(title, m, v):
    if m.get("trades", 0) == 0:
        return f"{title}\n  NO TRADES\n"
    lines = [
        title,
        f"  trades {m['trades']} | WR {m['win_rate']}% | PF {m['profit_factor']} | "
        f"expectancy {m['expectancy_r']}R | total {m['total_r']}R",
        f"  avg win {m['avg_win_r']}R | avg loss {m['avg_loss_r']}R | "
        f"max DD {m['max_drawdown_r']}R | sharpe/trade {m['sharpe_per_trade']}",
        f"  VERDICT: {v['result']}",
    ]
    for p in v.get("passed", []):
        lines.append(f"    PASS  {p}")
    for frec in v.get("failed", []):
        lines.append(f"    FAIL  {frec}")
    return "\n".join(lines) + "\n"


def render(cfg: dict, results: dict) -> str:
    crit = cfg["criteria"]
    out = ["=" * 78,
           f"ATLAS HYPOTHESIS REPORT — {cfg['name']} v{cfg.get('version', '?')}",
           "=" * 78,
           f"markets: {', '.join(cfg['markets'])} | "
           f"bias {cfg['timeframes']['bias']} / entry {cfg['timeframes']['entry']} | "
           f"session {cfg['session']['start']}-{cfg['session']['end']} "
           f"{cfg['session'].get('tz', 'UTC')}",
           f"success: {crit.get('success')}",
           f"failure: {crit.get('failure')}",
           "-" * 78]
    for window in ("in_sample", "out_sample"):
        m = results[window]["metrics"]
        v = verdict(m, crit)
        out.append(_block(f"[{window.upper()}]", m, v))
    # Per-market on out-of-sample (the honest number).
    if results["out_sample"].get("per_market"):
        out.append("PER MARKET (out-of-sample)")
        for sym, mm in results["out_sample"]["per_market"].items():
            if mm.get("trades", 0):
                out.append(f"  {sym:8} T:{mm['trades']:4} WR:{mm['win_rate']:5}% "
                           f"PF:{mm['profit_factor']} exp:{mm['expectancy_r']}R")
        out.append("")
    out.append("=" * 78)
    return "\n".join(out)
