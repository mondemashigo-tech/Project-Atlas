"""Read-services for Atlas Live.

Every function opens a short-lived MemoryStore (or Registry), reads, and closes.
Opening per call keeps each request on its own SQLite connection, which sidesteps
cross-thread connection sharing under the API's threadpool. All data comes from
the source of truth — nothing is synthesised.
"""
from __future__ import annotations

import glob
import os
from typing import Dict, List, Optional

from ..memory import MemoryStore
from ..registry import Registry
from . import roster


def available_hypotheses(root: str) -> List[Dict]:
    """Runnable hypothesis files under <root>/hypotheses/** (name = what the run
    trigger accepts). Names are unique basenames without extension."""
    base = os.path.join(root, "hypotheses")
    out, seen = [], set()
    for path in sorted(glob.glob(os.path.join(base, "**", "*.y*ml"), recursive=True)):
        name = os.path.splitext(os.path.basename(path))[0]
        if name in seen:
            continue
        seen.add(name)
        rel = os.path.relpath(path, root).replace(os.sep, "/")
        out.append({"name": name, "path": rel})
    return out


def _open(root: str) -> MemoryStore:
    return MemoryStore(root)


# ---- overview / health -----------------------------------------------------
def overview(root: str) -> Dict:
    store = _open(root)
    try:
        counts = store.counts()
        tally = store.decision_tally()
        recent = [_exp_summary(e) for e in store.list_experiments(limit=8)]
        gy = store.list_graveyard()
        return {
            "counts": counts,
            "decision_tally": tally,
            "recent_experiments": recent,
            "graveyard_count": len(gy),
            "latest_event_seq": store.latest_event_seq(),
        }
    finally:
        store.close()


def system_health(root: str) -> Dict:
    db = os.path.join(root, "atlas.db")
    store = _open(root)
    try:
        return {
            "status": "ok",
            "db_path": store.db_path if hasattr(store, "db_path") else db,
            "counts": store.counts(),
            "latest_event_seq": store.latest_event_seq(),
        }
    finally:
        store.close()


# ---- experiments -----------------------------------------------------------
def _exp_summary(e) -> Dict:
    m = e.metrics or {}
    return {
        "id": e.id, "hypothesis_id": e.hypothesis_id,
        "window": e.window, "verdict": e.verdict,
        "engine_version": e.engine_version, "created_at": e.created_at,
        "trades": m.get("trades"), "profit_factor": m.get("profit_factor"),
        "expectancy_r": m.get("expectancy_r"),
    }


def list_experiments(root: str, limit: int = 50) -> List[Dict]:
    store = _open(root)
    try:
        return [_exp_summary(e) for e in store.list_experiments(limit=limit)]
    finally:
        store.close()


def get_experiment(root: str, exp_id: str) -> Optional[Dict]:
    store = _open(root)
    try:
        e = store.get_experiment(exp_id)
        if not e:
            return None
        hyp = store.get_hypothesis(e.hypothesis_id)
        decisions = [d.to_dict() for d in store.list_decisions(e.hypothesis_id)]
        events = [_event_dict(ev) for ev in store.list_events(task_id=e.hypothesis_id,
                                                              limit=500)]
        return {
            "experiment": e.to_dict(),
            "hypothesis": hyp.to_dict() if hyp else None,
            "decisions": decisions,
            "events": events,
        }
    finally:
        store.close()


# ---- hypotheses ------------------------------------------------------------
def get_hypothesis(root: str, hyp_id: str) -> Optional[Dict]:
    store = _open(root)
    try:
        h = store.get_hypothesis(hyp_id)
        return h.to_dict() if h else None
    finally:
        store.close()


# ---- graveyard / registry / knowledge / governance -------------------------
def graveyard(root: str) -> List[Dict]:
    store = _open(root)
    try:
        return store.list_graveyard()
    finally:
        store.close()


def registry(root: str) -> List[Dict]:
    reg = Registry(root)
    try:
        return [r.to_dict() for r in reg.list()]
    finally:
        reg.close()


def knowledge(root: str) -> List[Dict]:
    store = _open(root)
    try:
        return [n.to_dict() for n in store.list_knowledge()]
    finally:
        store.close()


def governance(root: str) -> Dict:
    store = _open(root)
    try:
        snaps = store.list_snapshots()
        looks = {}
        for s in snaps:
            looks[s.id] = store.oos_test_count(s.id, "out_sample")
        return {
            "oos_looks": looks,
            "graveyard_count": len(store.list_graveyard()),
            "decision_tally": store.decision_tally(),
        }
    finally:
        store.close()


# ---- agents ----------------------------------------------------------------
def _event_dict(ev) -> Dict:
    return ev.to_dict()


def agents(root: str) -> List[Dict]:
    """Live council state derived from recent events (idle if no recent event)."""
    store = _open(root)
    try:
        recent = store.list_events(after_seq=max(0, store.latest_event_seq() - 200),
                                   limit=200)
    finally:
        store.close()
    states = roster.derive_states(recent)
    return [states[a["id"]] for a in roster.ROSTER]


def agent_detail(root: str, agent_id: str) -> Optional[Dict]:
    meta = roster.get(agent_id)
    if not meta:
        return None
    store = _open(root)
    try:
        evs = store.list_events(agent_id=agent_id, limit=50)
        recent = store.list_events(after_seq=max(0, store.latest_event_seq() - 200),
                                   limit=200)
    finally:
        store.close()
    state = roster.derive_states(recent).get(agent_id, {})
    return {
        **state,
        "activity": [_event_dict(e) for e in reversed(evs)],   # newest first
    }


# ---- events ----------------------------------------------------------------
def list_events(root: str, after_seq: int = 0, **filters) -> List[Dict]:
    store = _open(root)
    try:
        return [_event_dict(e) for e in store.list_events(after_seq=after_seq,
                                                          **filters)]
    finally:
        store.close()
