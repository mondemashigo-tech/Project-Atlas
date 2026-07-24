"""Strategy Registry: versioned, human-gated, auditable.

Rules enforced in code (Master Plan §5):
- A strategy may only move along the lifecycle FSM edges.
- Entering a capital-bearing status (paper/micro_live/live) REQUIRES a human
  approval token — no autonomous promotion, ever, at any autonomy level.
- The frozen executable spec never mutates in place; every transition bumps the
  record version and appends an approval + a DecisionRecord to the audit log.
- The bot only ever sees `export_json()` — enabled records in executable states.
- `kill_switch()` disables all strategies (reversible); the bot then halts.
"""
from __future__ import annotations

import json
import os
import sqlite3
from typing import List, Optional

from ..schemas import (StrategyRecord, DecisionRecord, new_id, utcnow_iso,
                       STRATEGY_LIFECYCLE, CAPITAL_BEARING_STATUSES)

_EXECUTABLE = ("paper", "micro_live", "live")


class RegistryError(Exception):
    pass


class Registry:
    def __init__(self, root: str = "."):
        self.db_path = os.path.join(root, "atlas_registry.db")
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript("""
        CREATE TABLE IF NOT EXISTS strategies (
            strategy_id TEXT PRIMARY KEY, status TEXT, version INTEGER,
            json TEXT, updated_at TEXT);
        CREATE TABLE IF NOT EXISTS transitions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, strategy_id TEXT,
            from_status TEXT, to_status TEXT, approved_by TEXT, note TEXT, at TEXT);
        """)
        self._conn.commit()

    # ---- writes ------------------------------------------------------------
    def add_candidate(self, rec: StrategyRecord) -> StrategyRecord:
        """Enter a strategy at status 'candidate' (not capital-bearing, no
        approval needed). Requires a valid record with validating experiments."""
        rec.status = "candidate"
        rec.ensure_valid()
        if self.get(rec.strategy_id):
            raise RegistryError(f"strategy {rec.strategy_id} already exists")
        self._save(rec)
        self._log(rec.strategy_id, None, "candidate", None, "created")
        return rec

    def transition(self, strategy_id: str, to_status: str,
                   approved_by: Optional[str] = None, note: str = "") -> DecisionRecord:
        rec = self.get(strategy_id)
        if not rec:
            raise RegistryError(f"unknown strategy {strategy_id}")
        allowed = STRATEGY_LIFECYCLE.get(rec.status, ())
        if to_status not in allowed:
            raise RegistryError(
                f"illegal transition {rec.status} -> {to_status} "
                f"(allowed: {allowed or 'none'})")
        if to_status in CAPITAL_BEARING_STATUSES and not approved_by:
            raise RegistryError(
                f"entering '{to_status}' is capital-bearing and requires a human "
                f"approval token (approved_by). Refused.")
        prev = rec.status
        rec.status = to_status
        rec.version += 1
        rec.updated_at = utcnow_iso()
        if approved_by:
            rec.approvals.append({"who": approved_by, "when": rec.updated_at,
                                  "transition": f"{prev}->{to_status}", "note": note})
        self._save(rec)
        self._log(strategy_id, prev, to_status, approved_by, note)
        return DecisionRecord(
            task_id=strategy_id, agent="Registry", phase="registry_transition",
            input_summary=f"{prev} -> {to_status}",
            evidence=f"approved_by={approved_by or 'n/a'}",
            decision=to_status, confidence="high",
            next_action=note or "")

    def promote(self, sid, to_status, approved_by, note=""):
        return self.transition(sid, to_status, approved_by, note)

    def retire(self, sid, note="retired"):
        return self.transition(sid, "retired", approved_by=None, note=note) \
            if "retired" in STRATEGY_LIFECYCLE.get(self._status(sid), ()) \
            else self._force_retire(sid, note)

    def _force_retire(self, sid, note):
        rec = self.get(sid)
        if not rec:
            raise RegistryError(f"unknown strategy {sid}")
        prev = rec.status
        rec.status = "retired"
        rec.version += 1
        rec.updated_at = utcnow_iso()
        self._save(rec)
        self._log(sid, prev, "retired", None, note)
        return DecisionRecord(task_id=sid, agent="Registry", phase="registry_transition",
                              input_summary=f"{prev} -> retired", evidence=note,
                              decision="retired", confidence="high")

    def kill_switch(self, reason: str = "manual kill-switch") -> int:
        """Disable ALL strategies (reversible). The bot's export goes empty, so it
        halts. Does not change status — flips an 'enabled' flag in monitoring."""
        n = 0
        for rec in self.list():
            if rec.monitoring_state.get("enabled", True):
                rec.monitoring_state["enabled"] = False
                rec.monitoring_state["disabled_reason"] = reason
                rec.updated_at = utcnow_iso()
                self._save(rec)
                self._log(rec.strategy_id, rec.status, rec.status, None,
                          f"KILL-SWITCH: {reason}")
                n += 1
        return n

    def reenable(self, strategy_id: str) -> None:
        rec = self.get(strategy_id)
        if rec:
            rec.monitoring_state["enabled"] = True
            rec.monitoring_state.pop("disabled_reason", None)
            self._save(rec)

    # ---- reads -------------------------------------------------------------
    def get(self, strategy_id: str) -> Optional[StrategyRecord]:
        row = self._conn.execute(
            "SELECT json FROM strategies WHERE strategy_id=?", (strategy_id,)).fetchone()
        return StrategyRecord.from_dict(json.loads(row["json"])) if row else None

    def _status(self, sid):
        r = self.get(sid)
        return r.status if r else None

    def list(self, status: str = None) -> List[StrategyRecord]:
        if status:
            rows = self._conn.execute(
                "SELECT json FROM strategies WHERE status=?", (status,)).fetchall()
        else:
            rows = self._conn.execute("SELECT json FROM strategies").fetchall()
        return [StrategyRecord.from_dict(json.loads(r["json"])) for r in rows]

    def transitions(self, strategy_id: str = None) -> List[dict]:
        if strategy_id:
            rows = self._conn.execute(
                "SELECT * FROM transitions WHERE strategy_id=? ORDER BY id",
                (strategy_id,)).fetchall()
        else:
            rows = self._conn.execute("SELECT * FROM transitions ORDER BY id").fetchall()
        return [dict(r) for r in rows]

    def export_json(self, path: str = None) -> list:
        """The bot's ONLY input: enabled strategies in executable states, reduced
        to what an executor needs. Read-only contract."""
        out = []
        for rec in self.list():
            if rec.status in _EXECUTABLE and rec.monitoring_state.get("enabled", True):
                out.append({
                    "strategy_id": rec.strategy_id,
                    "status": rec.status,
                    "allocation": rec.allocation,
                    "risk_limits": rec.risk_limits,
                    "spec": rec.frozen_executable_spec,
                    "version": rec.version,
                })
        if path:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(out, f, indent=2)
        return out

    # ---- internals ---------------------------------------------------------
    def _save(self, rec: StrategyRecord) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO strategies VALUES (?,?,?,?,?)",
            (rec.strategy_id, rec.status, rec.version,
             json.dumps(rec.to_dict()), rec.updated_at))
        self._conn.commit()

    def _log(self, sid, frm, to, by, note):
        self._conn.execute(
            "INSERT INTO transitions (strategy_id, from_status, to_status, "
            "approved_by, note, at) VALUES (?,?,?,?,?,?)",
            (sid, frm, to, by, note, utcnow_iso()))
        self._conn.commit()

    def close(self):
        self._conn.close()


def make_candidate(hypothesis_id, hypothesis_version, experiment_ids, spec,
                   allocation=0.0, risk_limits=None) -> StrategyRecord:
    """Helper: build a candidate StrategyRecord from a validated hypothesis."""
    return StrategyRecord(
        strategy_id=new_id("STR"),
        source_hypothesis_id=hypothesis_id,
        source_hypothesis_version=hypothesis_version,
        validating_experiment_ids=list(experiment_ids),
        frozen_executable_spec=dict(spec),
        allocation=allocation,
        risk_limits=risk_limits or {},
    )
