"""The council roster and how each agent's live state is derived.

Honesty first (Atlas Live principle): the roster lists the *real* actors in the
repo — not a made-up "seven". State is derived only from persisted events; if an
agent has no recent event it is **idle**, never a fake animation.

The Atlas Live brief assumed seven council agents; the engine actually has more.
We show them all, grouped by function, and drive state from real events. This is
the honest resolution of that mismatch (see current_system_baseline.md).
"""
from __future__ import annotations

import time
from typing import Dict, List, Optional

# Canonical roster: id, display name, role, nature, functional group.
# `emits_events=True` marks agents currently instrumented in the council path
# (M1). Others are real but not yet emitting live events — shown, honestly, as
# idle until their paths are instrumented.
ROSTER: List[Dict] = [
    {"id": "scientist", "name": "Scientist", "group": "generate", "nature": "hybrid",
     "role": "Proposes hypothesis variants by parameter exploration.", "emits_events": False},
    {"id": "inventor", "name": "Inventor", "group": "generate", "nature": "hybrid",
     "role": "Designs new composed strategies (mixes indicators; writes its own).", "emits_events": False},
    {"id": "scout", "name": "Scout", "group": "generate", "nature": "hybrid",
     "role": "Sources outside ideas from the web and turns them into hypotheses.", "emits_events": False},
    {"id": "backtester", "name": "Backtester", "group": "test", "nature": "deterministic",
     "role": "Runs the event-driven backtest — produces the numbers.", "emits_events": True},
    {"id": "historian", "name": "Historian", "group": "review", "nature": "hybrid",
     "role": "Checks novelty — has this exact idea been tested before?", "emits_events": True},
    {"id": "statistician", "name": "Statistician", "group": "review", "nature": "deterministic",
     "role": "Quantifies significance, expectancy, bootstrap bands.", "emits_events": True},
    {"id": "skeptic", "name": "Skeptic", "group": "review", "nature": "hybrid",
     "role": "Judges the evidence and rejects fragile or losing edges.", "emits_events": True},
    {"id": "riskmanager", "name": "RiskManager", "group": "gate", "nature": "deterministic",
     "role": "Hard risk gate — vetoes anything breaching risk policy.", "emits_events": True},
    {"id": "librarian", "name": "Librarian", "group": "knowledge", "nature": "hybrid",
     "role": "Ingests source material into tagged knowledge.", "emits_events": False},
    {"id": "reporter", "name": "Reporter", "group": "report", "nature": "hybrid",
     "role": "Writes the memo and the morning brief from the recorded chain.", "emits_events": True},
    {"id": "architect", "name": "Architect", "group": "report", "nature": "hybrid",
     "role": "Observes overall system health.", "emits_events": False},
]

_BY_ID = {a["id"]: a for a in ROSTER}

# How long after its last event an agent is still considered "active".
ACTIVE_WINDOW_SECS = 8

# event_type -> the state an agent is shown in while that's its latest event.
_STARTED_STATE = {
    "backtester": "testing", "historian": "searching", "statistician": "analyzing",
    "skeptic": "reviewing", "riskmanager": "reviewing", "reporter": "reporting",
}


def get(agent_id: str) -> Optional[Dict]:
    return _BY_ID.get(agent_id)


def _parse_ts(ts: str) -> float:
    try:
        from datetime import datetime
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def derive_states(events: List, now: Optional[float] = None) -> Dict[str, Dict]:
    """Given recent events (oldest→newest), return per-agent live state.

    An agent is `active` (in a work-specific state like testing/reviewing) only if
    its most recent event is a *started* event within ACTIVE_WINDOW_SECS; a
    *completed* event, or anything older, returns it to `idle`. Agents with no
    events are `idle`. Nothing is invented.
    """
    now = now if now is not None else time.time()
    latest: Dict[str, object] = {}
    for e in events:
        aid = getattr(e, "agent_id", None)
        if aid in _BY_ID:
            latest[aid] = e

    out: Dict[str, Dict] = {}
    for a in ROSTER:
        aid = a["id"]
        state, detail, last_ts, refs = "idle", "", None, []
        e = latest.get(aid)
        if e is not None:
            last_ts = getattr(e, "timestamp_utc", None)
            age = now - _parse_ts(last_ts or "")
            etype = getattr(e, "event_type", "")
            status = getattr(e, "status", None)
            detail = getattr(e, "title", "") or getattr(e, "summary", "")
            refs = [r for r in (getattr(e, "experiment_id", None),
                                getattr(e, "hypothesis_id", None)) if r]
            # Active only while the latest event is a *started* one within the
            # window; any completion (incl. skeptic_rejected) returns to idle.
            if status == "started" and age <= ACTIVE_WINDOW_SECS:
                state = _STARTED_STATE.get(aid, "analyzing")
            else:
                state = "idle"
        out[aid] = {**a, "state": state, "detail": detail,
                    "last_activity": last_ts, "refs": refs}
    return out
