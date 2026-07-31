"""Background research runner for Atlas Live.

Triggers a REAL council experiment in a background thread, publishing typed
events to a per-thread store and mirroring them to the live hub for streaming.
This is what makes the Council Chamber and Live Console light up with genuine
activity — never a simulation.

Safety:
- **Research only.** It runs the same `Orchestrator.run` the CLI uses; it can
  register a non-capital candidate but can never promote to capital (that stays
  human-gated inside the registry).
- **Path-confined.** The hypothesis file must resolve to a path *inside* the run
  root — no arbitrary filesystem reads via the API.
- **Single-flight.** Only one run at a time (the engine is synchronous/heavy).
"""
from __future__ import annotations

import os
import threading
from typing import Optional

from ..memory import MemoryStore
from ..events import EventBus
from ..kernel import Orchestrator


class Runner:
    def __init__(self, root: str, hub):
        self.root = os.path.abspath(root)
        self.hub = hub
        self._lock = threading.Lock()
        self._running = False
        self._current: Optional[str] = None

    def is_running(self) -> bool:
        return self._running

    def status(self) -> dict:
        return {"running": self._running, "current": self._current}

    def resolve_hypothesis(self, name: str) -> str:
        """Resolve a hypothesis name/relative path to a real file INSIDE root.
        Raises ValueError on traversal or a missing file."""
        candidates = []
        if name.endswith((".yaml", ".yml")):
            candidates.append(os.path.join(self.root, name))
        else:
            for sub in ("hypotheses", os.path.join("hypotheses", "scouted"),
                        os.path.join("hypotheses", "invented"), "."):
                candidates.append(os.path.join(self.root, sub, name + ".yaml"))
        for path in candidates:
            real = os.path.abspath(path)
            if os.path.commonpath([real, self.root]) != self.root:
                continue                       # traversal attempt — reject
            if os.path.isfile(real):
                return real
        raise ValueError(f"hypothesis not found under root: {name!r}")

    def run_council(self, hyp_name: str, window: str = "out_sample",
                    data_utc_offset: float = 0) -> dict:
        path = self.resolve_hypothesis(hyp_name)     # raises if unsafe/missing
        with self._lock:
            if self._running:
                return {"started": False, "reason": "a run is already in progress"}
            self._running = True
            self._current = os.path.basename(path)
        t = threading.Thread(target=self._run,
                             args=(path, window, data_utc_offset), daemon=True)
        t.start()
        return {"started": True, "hypothesis": os.path.basename(path)}

    def _run(self, path: str, window: str, offset: float) -> None:
        store = MemoryStore(self.root)               # this thread's own connection
        bus = EventBus(store)
        bus.subscribe(lambda e: self.hub.broadcast(e.to_dict()))
        try:
            Orchestrator(self.root).run(path, window=window,
                                        data_utc_offset=offset, bus=bus)
        except Exception:
            pass                                     # a system_error event was emitted
        finally:
            store.close()
            with self._lock:
                self._running = False
                self._current = None

    def run_idea(self, idea: str, window: str = "out_sample",
                 data_utc_offset: float = 0, markets=None) -> dict:
        """Turn a plain-English idea into a pre-registered hypothesis (via the
        Scout) and run it through the council — research only, streaming events."""
        idea = (idea or "").strip()
        if len(idea) < 8:
            return {"started": False, "reason": "describe the idea in a bit more detail"}
        with self._lock:
            if self._running:
                return {"started": False, "reason": "a run is already in progress"}
            self._running = True
            self._current = "idea: " + idea[:40]
        t = threading.Thread(target=self._run_idea,
                             args=(idea, window, data_utc_offset, markets), daemon=True)
        t.start()
        return {"started": True, "idea": idea[:80]}

    def _run_idea(self, idea, window, offset, markets):
        from ..scout import Scout
        from ..scout.llm import anthropic_extractor
        from ..events import Event
        store = MemoryStore(self.root)
        bus = EventBus(store)
        bus.subscribe(lambda e: self.hub.broadcast(e.to_dict()))
        try:
            extractor = None
            if os.environ.get("ANTHROPIC_API_KEY"):
                try:
                    extractor = anthropic_extractor()
                except Exception:
                    extractor = None
            bus.publish(Event(event_type="agent_started", agent_name="Scout",
                              status="started", source_module="live.runner",
                              title="scouting idea",
                              summary=idea[:120]))
            info = Scout(extractor).scout(idea, root=self.root,
                                          markets=markets or ["GBPUSD", "USDJPY"])
            bus.publish(Event(event_type="agent_completed", agent_name="Scout",
                              status="completed", source_module="live.runner",
                              title="idea formalised",
                              summary=f"template={info['template']} → {os.path.basename(info['path'])}",
                              evidence_refs=[info["path"]]))
            Orchestrator(self.root).run(info["path"], window=window,
                                        data_utc_offset=offset, bus=bus)
        except Exception as exc:
            try:
                bus.publish(Event(event_type="system_error", severity="error",
                                  status="blocked", source_module="live.runner",
                                  title="idea run failed",
                                  summary=f"{type(exc).__name__}: {exc}"))
            except Exception:
                pass
        finally:
            store.close()
            with self._lock:
                self._running = False
                self._current = None
