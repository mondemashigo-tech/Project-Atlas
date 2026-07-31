"""Atlas Live FastAPI application.

A thin, read-mostly HTTP surface over the Atlas engine plus a Server-Sent-Events
stream for the typed event spine. Routes call services; no research logic lives
here. The one state-changing route (`/api/research/run`) triggers a research-only
council run — it can never promote to capital.

Security posture (MVP): bind to 127.0.0.1 (the CLI default), read-only except the
research trigger, no shell execution, inputs validated, hypothesis paths confined
to the run root. LAN/remote/auth are configuration for later milestones.
"""
from __future__ import annotations

import json
import os
import queue
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import services, brief as briefmod, chat as chatmod
from .hub import Hub
from .runner import Runner

_WEB = os.path.join(os.path.dirname(__file__), "web")


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    agent_id: Optional[str] = None
    transcript_source: str = "text"


class RunIn(BaseModel):
    hypothesis: str = Field(min_length=1, max_length=200)
    window: str = "out_sample"
    data_utc_offset: float = 0.0


class IdeaIn(BaseModel):
    idea: str = Field(min_length=8, max_length=4000)
    window: str = "out_sample"
    data_utc_offset: float = 0.0


def create_app(root: str = ".", allow_run: bool = True) -> FastAPI:
    root = os.path.abspath(root)
    app = FastAPI(title="Atlas Live", version="0.1.0")
    app.state.root = root
    app.state.hub = Hub()
    app.state.runner = Runner(root, app.state.hub)

    # ---- overview / health -------------------------------------------------
    @app.get("/api/overview")
    def overview():
        return services.overview(root)

    @app.get("/api/system/health")
    def health():
        return services.system_health(root)

    # ---- agents ------------------------------------------------------------
    @app.get("/api/agents")
    def agents():
        return {"agents": services.agents(root),
                "runner": app.state.runner.status()}

    @app.get("/api/agents/{agent_id}")
    def agent(agent_id: str):
        d = services.agent_detail(root, agent_id)
        if d is None:
            raise HTTPException(404, "unknown agent")
        return d

    @app.get("/api/agents/{agent_id}/activity")
    def agent_activity(agent_id: str):
        d = services.agent_detail(root, agent_id)
        if d is None:
            raise HTTPException(404, "unknown agent")
        return {"activity": d["activity"]}

    @app.post("/api/agents/{agent_id}/query")
    def agent_query(agent_id: str, body: ChatIn):
        if services_roster_missing(agent_id):
            raise HTTPException(404, "unknown agent")
        return chatmod.answer(root, body.message, agent_id=agent_id,
                              transcript_source=body.transcript_source,
                              runner_status=app.state.runner.status())

    # ---- events ------------------------------------------------------------
    @app.get("/api/events")
    def events(after_seq: int = 0, task_id: Optional[str] = None,
               event_type: Optional[str] = None, agent_id: Optional[str] = None,
               severity: Optional[str] = None, limit: int = 500):
        f = {k: v for k, v in dict(task_id=task_id, event_type=event_type,
                                   agent_id=agent_id, severity=severity).items()
             if v is not None}
        return {"events": services.list_events(root, after_seq=after_seq,
                                               limit=min(limit, 2000), **f)}

    @app.get("/api/events/stream")
    def stream(request: Request, after_seq: int = 0):
        # EventSource auto-reconnect sends Last-Event-ID (the last seq we emitted);
        # honour it so a reconnecting browser replays exactly what it missed.
        leid = request.headers.get("last-event-id")
        if leid and leid.isdigit():
            after_seq = int(leid)
        return StreamingResponse(_sse(app, root, after_seq),
                                 media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache",
                                          "X-Accel-Buffering": "no"})

    # ---- research records --------------------------------------------------
    @app.get("/api/experiments")
    def experiments(limit: int = 50):
        return {"experiments": services.list_experiments(root, limit=min(limit, 500))}

    @app.get("/api/experiments/{exp_id}")
    def experiment(exp_id: str):
        d = services.get_experiment(root, exp_id)
        if d is None:
            raise HTTPException(404, "unknown experiment")
        return d

    @app.get("/api/hypotheses")
    def hypotheses_list():
        return {"hypotheses": services.available_hypotheses(root)}

    @app.get("/api/hypotheses/{hyp_id}")
    def hypothesis(hyp_id: str):
        d = services.get_hypothesis(root, hyp_id)
        if d is None:
            raise HTTPException(404, "unknown hypothesis")
        return d

    @app.get("/api/graveyard")
    def graveyard():
        return {"graveyard": services.graveyard(root)}

    @app.get("/api/registry")
    def registry():
        return {"registry": services.registry(root)}

    @app.get("/api/knowledge")
    def knowledge():
        return {"knowledge": services.knowledge(root)}

    @app.get("/api/governance")
    def governance():
        return services.governance(root)

    # ---- reports -----------------------------------------------------------
    @app.get("/api/reports/morning-brief")
    def morning_brief(hours: int = 24):
        return briefmod.morning_brief(root, hours=hours)

    # ---- conversation ------------------------------------------------------
    @app.post("/api/chat")
    def chat(body: ChatIn):
        return chatmod.answer(root, body.message, agent_id=body.agent_id,
                              transcript_source=body.transcript_source,
                              runner_status=app.state.runner.status())

    # ---- research trigger (research-only; never capital) -------------------
    @app.post("/api/research/run")
    def research_run(body: RunIn):
        if not allow_run:
            raise HTTPException(403, "research runs are disabled on this instance")
        try:
            return app.state.runner.run_council(
                body.hypothesis, window=body.window,
                data_utc_offset=body.data_utc_offset)
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.post("/api/research/idea")
    def research_idea(body: IdeaIn):
        """Paste a plain-English idea; the Scout formalises it and the council
        tests it. Research-only — never capital."""
        if not allow_run:
            raise HTTPException(403, "research runs are disabled on this instance")
        return app.state.runner.run_idea(
            body.idea, window=body.window, data_utc_offset=body.data_utc_offset)

    @app.get("/api/research/status")
    def research_status():
        return app.state.runner.status()

    # ---- frontend ----------------------------------------------------------
    if os.path.isdir(_WEB):
        app.mount("/static", StaticFiles(directory=_WEB), name="static")

        @app.get("/", response_class=HTMLResponse)
        def index():
            idx = os.path.join(_WEB, "index.html")
            if os.path.isfile(idx):
                with open(idx, encoding="utf-8") as f:
                    return HTMLResponse(f.read())
            return HTMLResponse("<h1>Atlas Live</h1><p>frontend not built</p>")

    return app


def services_roster_missing(agent_id: str) -> bool:
    from . import roster
    return roster.get(agent_id) is None


def _frame(ev: dict) -> str:
    # No custom `event:` field: a named SSE event would be delivered only to a
    # matching addEventListener, bypassing EventSource.onmessage. We keep the
    # default `message` type and carry the event_type inside the JSON payload.
    return f"id: {ev.get('seq','')}\ndata: {json.dumps(ev, default=str)}\n\n"


def _sse(app: FastAPI, root: str, after_seq: int):
    """SSE generator: register first (no gap), replay persisted events after the
    client's cursor, then stream live — de-duping anything already replayed."""
    hub: Hub = app.state.hub
    q = hub.register()
    try:
        replayed = services.list_events(root, after_seq=after_seq, limit=2000)
        last = replayed[-1]["seq"] if replayed else after_seq
        for ev in replayed:
            yield _frame(ev)
        yield ": connected\n\n"
        while True:
            try:
                item = q.get(timeout=15)
                seq = item.get("seq")
                if seq is not None and last is not None and seq <= last:
                    continue                       # already sent during replay
                if seq is not None:
                    last = seq
                yield _frame(item)
            except queue.Empty:
                yield ": keepalive\n\n"            # keep the connection warm
    finally:
        hub.unregister(q)
