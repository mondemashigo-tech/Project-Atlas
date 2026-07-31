"""Grounded conversation for Atlas Live.

Hard rule: **answers are built from Atlas records** (SQLite, decisions, events,
memos, registry, knowledge). The language model, if a key is present, only
*phrases* the retrieved records and must not invent experiments, verdicts, or
numbers. With no key, a deterministic template answer is returned from the same
records. Every answer carries citations (record ids / memo paths). If the records
don't contain the answer, we say so.

This never runs shell commands and never mutates state — it is read-only.
"""
from __future__ import annotations

import os
import re
from typing import Dict, List, Optional, Tuple

from ..memory import MemoryStore
from ..registry import Registry
from ..schemas import new_id, utcnow_iso
from . import brief as briefmod

_ID_RE = re.compile(r"\b((?:EXP|HYP|STR|DS|KN|EV)-[0-9a-fA-F]+)\b")


def _ids(text: str) -> List[str]:
    return [m.group(1) for m in _ID_RE.finditer(text or "")]


# --------------------------------------------------------------------------- #
# Retrieval — each returns (facts, citations, records)
# --------------------------------------------------------------------------- #
def _why_rejected(store, ids: List[str]) -> Tuple[str, List[str], List[Dict]]:
    for _id in ids:
        exp = store.get_experiment(_id) if _id.startswith("EXP") else None
        hyp_id = exp.hypothesis_id if exp else (_id if _id.startswith("HYP") else None)
        if not hyp_id:
            continue
        decisions = store.list_decisions(hyp_id)
        skeptic = next((d for d in decisions if d.agent == "Skeptic"), None)
        gy = {g["hypothesis_id"]: g for g in store.list_graveyard()}.get(hyp_id)
        facts = []
        if exp:
            facts.append(f"Experiment {exp.id}: verdict {exp.verdict}, "
                         f"metrics {exp.metrics}.")
        if skeptic:
            facts.append(f"Skeptic decision: {skeptic.decision} — {skeptic.evidence}")
        if gy:
            facts.append(f"Buried in graveyard: {gy['reason']}")
        if facts:
            cites = [x for x in (exp.id if exp else None, hyp_id) if x]
            recs = [d.to_dict() for d in decisions]
            return " ".join(facts), cites, recs
    return ("", [], [])


def _recent_rejections(store) -> Tuple[str, List[str], List[Dict]]:
    gy = store.list_graveyard()
    if not gy:
        return ("No hypotheses are recorded in the graveyard.", [], [])
    top = gy[:8]
    facts = "Recently buried: " + "; ".join(
        f"{g['title']} ({g['hypothesis_id']}): {g['reason'][:80]}" for g in top)
    return facts, [g["hypothesis_id"] for g in top], top


def _currently_researching(store, runner_status: Dict) -> Tuple[str, List[str], List[Dict]]:
    exps = store.list_experiments(limit=5)
    running = runner_status.get("running")
    cur = runner_status.get("current")
    parts = []
    if running:
        parts.append(f"A council run is in progress on {cur}.")
    else:
        parts.append("No run is in progress right now — the lab is idle.")
    if exps:
        parts.append("Most recent experiments: " + "; ".join(
            f"{e.id} {e.verdict} ({(e.metrics or {}).get('trades')} trades)" for e in exps))
    return " ".join(parts), [e.id for e in exps], [e.to_dict() for e in exps]


def _candidates(store, root) -> Tuple[str, List[str], List[Dict]]:
    reg = Registry(root)
    try:
        cands = [r.to_dict() for r in reg.list()]
    finally:
        reg.close()
    if not cands:
        return ("There are no registry candidates yet — nothing has passed the "
                "full research ladder.", [], [])
    facts = "Registry candidates: " + "; ".join(
        f"{c.get('strategy_id')} [{c.get('status')}] from {c.get('experiment_ids')}"
        for c in cands[:8])
    return facts, [c.get("strategy_id") for c in cands[:8]], cands


def _evidence_for(store, ids: List[str]) -> Tuple[str, List[str], List[Dict]]:
    for _id in ids:
        exp = store.get_experiment(_id) if _id.startswith("EXP") else None
        hyp_id = exp.hypothesis_id if exp else (_id if _id.startswith("HYP") else None)
        if not hyp_id:
            continue
        decisions = store.list_decisions(hyp_id)
        if decisions:
            facts = "Decision ladder: " + "; ".join(
                f"[{d.phase}] {d.agent}: {d.decision} — {d.evidence[:80]}"
                for d in decisions)
            return facts, [_id], [d.to_dict() for d in decisions]
    return ("", [], [])


def _knowledge_about(store, message: str) -> Tuple[str, List[str], List[Dict]]:
    terms = [w.lower() for w in re.findall(r"[a-zA-Z]{4,}", message)
             if w.lower() not in _STOP]
    notes = store.list_knowledge()
    hits = [n for n in notes
            if any(t in (n.title + " " + n.summary + " " + " ".join(n.topic_tags)).lower()
                   for t in terms)]
    if not hits:
        return ("No knowledge notes match that topic.", [], [])
    facts = "Knowledge: " + "; ".join(f"{n.title} [{','.join(n.topic_tags)}]: "
                                      f"{n.summary[:80]}" for n in hits[:6])
    return facts, [n.id for n in hits[:6]], [n.to_dict() for n in hits[:6]]


def _list_experiments(store) -> Tuple[str, List[str], List[Dict]]:
    exps = store.list_experiments(limit=40)
    if not exps:
        return ("No experiments are recorded yet.", [], [])
    facts = "Experiments (most recent first): " + "; ".join(
        f"{e.id} {e.verdict} ({(e.metrics or {}).get('trades')} trades, "
        f"PF {(e.metrics or {}).get('profit_factor')})" for e in exps[:20])
    return facts, [e.id for e in exps[:20]], [e.to_dict() for e in exps[:20]]


def _list_hypotheses(store) -> Tuple[str, List[str], List[Dict]]:
    exps = store.list_experiments(limit=60)
    rows, cites, seen = [], [], set()
    for e in exps:
        hid = e.hypothesis_id
        if hid in seen:
            continue
        seen.add(hid)
        h = store.get_hypothesis(hid)
        title = h.title if h else "?"
        status = h.status if h else "?"
        rows.append({"hypothesis_id": hid, "title": title, "status": status,
                     "last_verdict": e.verdict})
        cites.append(hid)
        if len(rows) >= 20:
            break
    if not rows:
        return ("No hypotheses have been run yet.", [], [])
    facts = "Hypotheses run: " + "; ".join(
        f"{r['title']} ({r['hypothesis_id']}) [{r['status']}], last verdict "
        f"{r['last_verdict']}" for r in rows)
    return facts, cites, rows


def _overview(store) -> Tuple[str, List[str], List[Dict]]:
    c = store.counts()
    facts = (f"Atlas has {c.get('experiments', 0)} experiments, "
             f"{c.get('hypotheses', 0)} hypotheses, "
             f"{c.get('knowledge', 0)} knowledge notes, "
             f"{c.get('graveyard', 0)} buried.")
    return facts, [], [c]


_STOP = {"what", "why", "which", "when", "have", "does", "atlas", "tell", "about",
         "know", "this", "that", "there", "were", "with", "from", "your", "you"}


# --------------------------------------------------------------------------- #
# Routing
# --------------------------------------------------------------------------- #
def _route(message: str) -> str:
    m = (message or "").lower()
    ids = _ids(message)
    if any(w in m for w in ("overnight", "asleep", "last night", "morning brief",
                            "while i was")):
        return "brief"
    if ids and any(w in m for w in ("why", "reject", "fail", "buried")):
        return "why_rejected"
    if ids and "evidence" in m:
        return "evidence"
    if any(w in m for w in ("list hypothes", "which hypothes", "what hypothes",
                            "have you run", "what have you run", "what did you run",
                            "which of the hypothes")):
        return "list_hypotheses"
    if any(w in m for w in ("list experiment", "retrieve the experiment",
                            "retrieve experiment", "which experiment",
                            "show me the experiment", "the experiments",
                            "what experiments", "enumerate", "all experiments")):
        return "list_experiments"
    if any(w in m for w in ("reject", "buried", "graveyard", "failed today")):
        return "recent_rejections"
    if any(w in m for w in ("researching", "running", "doing now", "currently",
                            "right now", "in progress")):
        return "researching"
    if any(w in m for w in ("candidate", "strongest", "best", "promising",
                            "closest to")):
        return "candidates"
    if any(w in m for w in ("know about", "historian", "tested", "seen this",
                            "before", "knowledge")):
        return "knowledge"
    return "overview"


def _retrieve(root: str, message: str, intent: str,
              runner_status: Dict) -> Tuple[str, List[str], List[Dict]]:
    store = MemoryStore(root)
    try:
        ids = _ids(message)
        if intent == "brief":
            b = briefmod.morning_brief(root)
            return b["text"], [], [b]
        if intent == "why_rejected":
            out = _why_rejected(store, ids)
            return out if out[0] else _recent_rejections(store)
        if intent == "evidence":
            out = _evidence_for(store, ids)
            return out if out[0] else _overview(store)
        if intent == "list_experiments":
            return _list_experiments(store)
        if intent == "list_hypotheses":
            return _list_hypotheses(store)
        if intent == "recent_rejections":
            return _recent_rejections(store)
        if intent == "researching":
            return _currently_researching(store, runner_status)
        if intent == "candidates":
            return _candidates(store, root)
        if intent == "knowledge":
            return _knowledge_about(store, message)
        return _overview(store)
    finally:
        store.close()


# --------------------------------------------------------------------------- #
# Answer composition
# --------------------------------------------------------------------------- #
_SYSTEM = (
    "You are Atlas's Reporter. You are given RECORDS retrieved from Atlas's own "
    "database. Answer the user's question USING ONLY these records. Cite record "
    "ids inline. If the records do not contain the answer, say you do not have "
    "enough recorded evidence. Never invent experiments, verdicts, numbers, or "
    "agent reasoning. Be concise and factual."
)


def _llm_phrase(message: str, facts: str, records: List[Dict],
                model: str = "claude-opus-5") -> Optional[str]:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic, json
        client = anthropic.Anthropic()
        content = (f"User question: {message}\n\nRetrieved facts:\n{facts}\n\n"
                   f"Records (JSON):\n{json.dumps(records, default=str)[:6000]}\n\n"
                   "Answer using only the above.")
        msg = client.messages.create(model=model, max_tokens=700, system=_SYSTEM,
                                      messages=[{"role": "user", "content": content}])
        return "".join(getattr(b, "text", "") for b in msg.content).strip() or None
    except Exception:
        return None


def answer(root: str, message: str, agent_id: Optional[str] = None,
           transcript_source: str = "text", runner_status: Optional[Dict] = None,
           use_llm: bool = True) -> Dict:
    runner_status = runner_status or {"running": False, "current": None}
    intent = _route(message)
    facts, citations, records = _retrieve(root, message, intent, runner_status)

    grounded = bool(records) and bool(facts.strip())
    llm_text = _llm_phrase(message, facts, records) if (use_llm and grounded) else None
    text = llm_text or (facts if grounded else
                        "I don't have enough recorded evidence to answer that.")

    convo = {
        "id": new_id("CONV"), "created_at": utcnow_iso(),
        "transcript_source": transcript_source,
        "routed_agent": agent_id or "Reporter",
        "user_message": message, "answer": text,
        "citations": citations, "records": records,
    }
    store = MemoryStore(root)
    try:
        store.write_conversation(convo)
    finally:
        store.close()

    return {"conversation_id": convo["id"], "intent": intent, "answer": text,
            "citations": citations, "grounded": grounded,
            "routed_agent": convo["routed_agent"], "llm_used": llm_text is not None}
