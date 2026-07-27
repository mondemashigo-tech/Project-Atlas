"""Atlas typed event spine — the real-time nervous system for Atlas Live.

Events are emitted by the engine as it actually works, persisted to SQLite, and
streamed to connected clients. They are pure side-effects: with no bus attached,
the engine behaves exactly as before. Nothing here fabricates activity — every
event corresponds to a real call site in the research flow.
"""
from .model import Event, EVENT_TYPES, SEVERITIES
from .bus import EventBus

__all__ = ["Event", "EventBus", "EVENT_TYPES", "SEVERITIES"]
