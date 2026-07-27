"""The EventBus — publish, persist, stream, and replay.

Design (matches the Atlas Live brief):
1. Persist important events to SQLite (durable, survives restart).
2. Stream them to connected subscribers (live UI).
3. Let clients reconnect and request missed events (get_events / replay).

The bus is deliberately small and synchronous: publish writes to the store, then
fans out to subscribers. Subscriber errors are isolated so one bad handler can't
break emission or the research run. If constructed with no store, events still
stream to live subscribers but aren't persisted (used only in tests).
"""
from __future__ import annotations

import threading
from typing import Callable, List, Optional

from .model import Event


class EventBus:
    def __init__(self, store=None):
        self.store = store
        self._subscribers: List[Callable[[Event], None]] = []
        self._lock = threading.Lock()

    # -- publish / persist --------------------------------------------------
    def publish(self, event: Event) -> Event:
        if self.store is not None:
            self.store.write_event(event)      # assigns event.seq
        for handler in list(self._subscribers):
            try:
                handler(event)
            except Exception:
                # A subscriber must never break emission or the research run.
                pass
        return event

    def emit(self, event_type: str, **kwargs) -> Event:
        """Convenience: build + publish in one call."""
        return self.publish(Event(event_type=event_type, **kwargs))

    # -- subscribe (live streaming) ----------------------------------------
    def subscribe(self, handler: Callable[[Event], None]) -> Callable[[], None]:
        """Register a live handler. Returns an unsubscribe callable."""
        with self._lock:
            self._subscribers.append(handler)

        def _unsub():
            with self._lock:
                if handler in self._subscribers:
                    self._subscribers.remove(handler)
        return _unsub

    # -- catch-up / replay (reconnect) -------------------------------------
    def get_events(self, after_seq: int = 0, **filters) -> List[Event]:
        """Persisted events with seq > after_seq (oldest first). Requires a store."""
        if self.store is None:
            return []
        return self.store.list_events(after_seq=after_seq, **filters)

    def replay(self, task_id: Optional[str] = None,
               cycle_id: Optional[str] = None) -> List[Event]:
        """All persisted events for a given run (task or cycle), in order."""
        if self.store is None:
            return []
        if task_id is not None:
            return self.store.list_events(task_id=task_id, limit=100000)
        evs = self.store.list_events(limit=100000)
        if cycle_id is not None:
            evs = [e for e in evs if e.cycle_id == cycle_id]
        return evs

    def latest_seq(self) -> int:
        return self.store.latest_event_seq() if self.store is not None else 0


class NullBus(EventBus):
    """A no-op bus: publish does nothing. Lets instrumented code call the bus
    unconditionally while keeping the engine's default behaviour unchanged."""
    def __init__(self):
        super().__init__(store=None)

    def publish(self, event: Event) -> Event:
        return event
