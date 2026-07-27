"""Morning brief — assembled from real recorded activity.

If nothing ran in the window, it says so plainly (no invented summary). Every
number comes from persisted events / experiments / registry rows.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, List

from ..memory import MemoryStore
from ..registry import Registry


def _parse(ts: str) -> datetime:
    try:
        return datetime.fromisoformat((ts or "").replace("Z", "+00:00"))
    except Exception:
        return datetime.fromtimestamp(0, tz=timezone.utc)


def morning_brief(root: str, hours: int = 24) -> Dict:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    store = MemoryStore(root)
    try:
        all_events = store.list_events(limit=100000)
        window = [e for e in all_events if _parse(e.timestamp_utc) >= cutoff]
        experiments = [e for e in store.list_experiments(limit=1000)
                       if _parse(e.created_at) >= cutoff]
        graveyard = store.list_graveyard()
    finally:
        store.close()

    def count(etype):
        return sum(1 for e in window if e.event_type == etype)

    if not window and not experiments:
        return {
            "no_activity": True,
            "window_hours": hours,
            "headline": f"No research activity recorded in the last {hours}h.",
            "text": (f"No overnight run was recorded in the last {hours} hours. "
                     "Nothing to report — the lab was idle."),
        }

    active_agents = sorted({e.agent_name for e in window if e.agent_name})
    errors = [e for e in window if e.event_type == "system_error"]
    warnings = [e for e in window if e.severity == "warning"]
    rejected = count("skeptic_rejected")
    advanced = count("hypothesis_registered")
    completed = count("experiment_completed")
    verdicts: Dict[str, int] = {}
    for e in window:
        if e.event_type == "experiment_completed":
            v = (e.metadata or {}).get("verdict", "?")
            verdicts[v] = verdicts.get(v, 0) + 1

    reg = Registry(root)
    try:
        candidates = [r.to_dict() for r in reg.list()]
    finally:
        reg.close()
    awaiting = [c for c in candidates if c.get("status") == "candidate"]

    lines: List[str] = []
    lines.append(f"In the last {hours}h: {completed} experiment(s) completed, "
                 f"{rejected} rejected, {advanced} advanced to a candidate.")
    if verdicts:
        lines.append("Verdicts: " + ", ".join(f"{k} x{v}" for k, v in verdicts.items()) + ".")
    if active_agents:
        lines.append("Active agents: " + ", ".join(active_agents) + ".")
    if warnings:
        lines.append(f"{len(warnings)} warning(s) (e.g. governance/OOS budget).")
    if errors:
        lines.append(f"⚠ {len(errors)} system error(s) — see the console.")
    if awaiting:
        lines.append(f"{len(awaiting)} candidate(s) awaiting your review "
                     "(promotion to capital is human-gated).")
    else:
        lines.append("No human decisions are required right now.")

    return {
        "no_activity": False,
        "window_hours": hours,
        "headline": (f"{completed} completed · {rejected} rejected · "
                     f"{advanced} advanced"),
        "generated": completed,
        "rejected": rejected,
        "advanced": advanced,
        "verdicts": verdicts,
        "active_agents": active_agents,
        "warnings": len(warnings),
        "errors": len(errors),
        "candidates_awaiting_review": len(awaiting),
        "graveyard_total": len(graveyard),
        "text": " ".join(lines),
    }
