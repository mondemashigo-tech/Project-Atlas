"""The typed Event and its taxonomy.

Only event types that map to a REAL action in the current engine are defined
here. As more of the system is instrumented, add types alongside the real call
site that emits them — never speculatively.

Progress: many Atlas steps have no reliable percentage (the backtester runs a
frame in one shot with no callback). Such events leave progress_current/total as
None, which the UI must render as an *indeterminate* running state, never a fake
percentage.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

from ..schemas import utcnow_iso

# Event types actually emitted today (M1 instruments the council path).
EVENT_TYPES = {
    # experiment lifecycle (one council run)
    "experiment_started",
    "experiment_completed",
    # deterministic engine
    "backtest_completed",
    # council agents (each maps to a real agent call)
    "agent_started",
    "agent_completed",
    "skeptic_rejected",
    "hypothesis_registered",     # non-capital candidate created (human-gated beyond)
    "report_completed",
    # governance / system
    "governance_checked",
    "system_warning",
    "system_error",
}

SEVERITIES = {"info", "warning", "error"}


def new_event_id() -> str:
    return "EV-" + uuid.uuid4().hex[:12]


@dataclass
class Event:
    """A single, typed, persisted-and-streamable system event.

    `seq` is the monotonic stream cursor (assigned by the store on write); clients
    request `get_events(after_seq=...)` to catch up after a reconnect. `event_id`
    is a stable unique id for referencing a specific event.
    """
    event_type: str
    title: str = ""
    summary: str = ""
    agent_id: Optional[str] = None
    agent_name: Optional[str] = None
    task_id: Optional[str] = None
    cycle_id: Optional[str] = None
    hypothesis_id: Optional[str] = None
    experiment_id: Optional[str] = None
    strategy_id: Optional[str] = None
    severity: str = "info"
    status: Optional[str] = None                 # e.g. started | completed | blocked
    evidence_refs: List[str] = field(default_factory=list)
    progress_current: Optional[int] = None       # None => indeterminate
    progress_total: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    source_module: str = ""
    is_historical: bool = False
    event_id: str = field(default_factory=new_event_id)
    timestamp_utc: str = field(default_factory=utcnow_iso)
    created_at: str = field(default_factory=utcnow_iso)
    seq: Optional[int] = None                    # assigned on persist

    def __post_init__(self):
        if self.event_type not in EVENT_TYPES:
            raise ValueError(f"unknown event_type {self.event_type!r}; add it to "
                             "EVENT_TYPES beside the real call site that emits it")
        if self.severity not in SEVERITIES:
            raise ValueError(f"unknown severity {self.severity!r}")

    def to_dict(self) -> dict:
        return asdict(self)

    def to_row(self) -> tuple:
        """Column tuple for the events table (order matches store INSERT)."""
        return (
            self.event_id, self.event_type, self.timestamp_utc,
            self.agent_id, self.agent_name, self.task_id, self.cycle_id,
            self.hypothesis_id, self.experiment_id, self.strategy_id,
            self.severity, self.status, self.title, self.summary,
            json.dumps(self.evidence_refs), self.progress_current,
            self.progress_total, json.dumps(self.metadata), self.source_module,
            1 if self.is_historical else 0, self.created_at,
        )

    @classmethod
    def from_row(cls, row) -> "Event":
        """Rebuild from a sqlite3.Row of the events table (includes seq)."""
        ev = cls.__new__(cls)          # bypass __post_init__ validation on read
        ev.seq = row["seq"]
        ev.event_id = row["event_id"]
        ev.event_type = row["event_type"]
        ev.timestamp_utc = row["timestamp_utc"]
        ev.agent_id = row["agent_id"]
        ev.agent_name = row["agent_name"]
        ev.task_id = row["task_id"]
        ev.cycle_id = row["cycle_id"]
        ev.hypothesis_id = row["hypothesis_id"]
        ev.experiment_id = row["experiment_id"]
        ev.strategy_id = row["strategy_id"]
        ev.severity = row["severity"]
        ev.status = row["status"]
        ev.title = row["title"]
        ev.summary = row["summary"]
        ev.evidence_refs = json.loads(row["evidence_refs"] or "[]")
        ev.progress_current = row["progress_current"]
        ev.progress_total = row["progress_total"]
        ev.metadata = json.loads(row["metadata"] or "{}")
        ev.source_module = row["source_module"]
        ev.is_historical = bool(row["is_historical"])
        ev.created_at = row["created_at"]
        return ev
