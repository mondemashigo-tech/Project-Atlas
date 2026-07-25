"""Partitioned memory backed by SQLite, mirrored to an Obsidian vault.

Design decision (Master Plan §8): **SQLite is the source of truth**; the vault
markdown is a generated mirror for human/Obsidian reading. Structured records are
never written *only* to markdown. Immutable records (experiments, decisions) are
insert-only; re-inserting the same id is rejected.
"""
from __future__ import annotations

import json
import os
import sqlite3
from typing import List, Optional

from ..schemas import (ExperimentRecord, DecisionRecord, Hypothesis,
                       KnowledgeNote, DataSnapshot, utcnow_iso)


class MemoryStore:
    def __init__(self, root: str = "."):
        self.root = root
        self.db_path = os.path.join(root, "atlas_memory.db")
        self.vault = os.path.join(root, "vault")
        os.makedirs(self.vault, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self) -> None:
        c = self._conn
        c.executescript("""
        CREATE TABLE IF NOT EXISTS hypotheses (
            id TEXT PRIMARY KEY, version TEXT, title TEXT, status TEXT,
            preregistration_hash TEXT, json TEXT, created_at TEXT);
        CREATE TABLE IF NOT EXISTS experiments (
            id TEXT PRIMARY KEY, hypothesis_id TEXT, window TEXT, verdict TEXT,
            engine_version TEXT, json TEXT, created_at TEXT);
        CREATE TABLE IF NOT EXISTS decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT, agent TEXT,
            phase TEXT, decision TEXT, json TEXT, created_at TEXT);
        CREATE TABLE IF NOT EXISTS knowledge (
            id TEXT PRIMARY KEY, title TEXT, tags TEXT, json TEXT, created_at TEXT);
        CREATE TABLE IF NOT EXISTS snapshots (
            id TEXT PRIMARY KEY, source TEXT, content_hash TEXT, json TEXT, created_at TEXT);
        CREATE TABLE IF NOT EXISTS oos_tests (
            id INTEGER PRIMARY KEY AUTOINCREMENT, snapshot_id TEXT, window TEXT,
            hypothesis_id TEXT, prereg_hash TEXT, at TEXT);
        CREATE TABLE IF NOT EXISTS graveyard (
            hypothesis_id TEXT PRIMARY KEY, title TEXT, reason TEXT, at TEXT);
        CREATE TABLE IF NOT EXISTS policy (
            key TEXT PRIMARY KEY, json TEXT, updated_at TEXT, updated_by TEXT);
        """)
        c.commit()

    # ---- hypotheses --------------------------------------------------------
    def write_hypothesis(self, h: Hypothesis) -> Hypothesis:
        h.ensure_valid()
        self._conn.execute(
            "INSERT OR REPLACE INTO hypotheses VALUES (?,?,?,?,?,?,?)",
            (h.id, h.version, h.title, h.status, h.preregistration_hash,
             json.dumps(h.to_dict()), h.created_at))
        self._conn.commit()
        return h

    def get_hypothesis(self, hid: str) -> Optional[Hypothesis]:
        row = self._conn.execute(
            "SELECT json FROM hypotheses WHERE id=?", (hid,)).fetchone()
        return Hypothesis.from_dict(json.loads(row["json"])) if row else None

    def find_hypotheses_by_prereg(self, prereg_hash: str) -> List[dict]:
        rows = self._conn.execute(
            "SELECT id, title, status FROM hypotheses WHERE preregistration_hash=?",
            (prereg_hash,)).fetchall()
        return [dict(r) for r in rows]

    def counts(self) -> dict:
        def n(sql):
            return int(self._conn.execute(sql).fetchone()[0])
        return {
            "hypotheses": n("SELECT COUNT(*) FROM hypotheses"),
            "experiments": n("SELECT COUNT(*) FROM experiments"),
            "graveyard": n("SELECT COUNT(*) FROM graveyard"),
            "decisions": n("SELECT COUNT(*) FROM decisions"),
            "candidates": n("SELECT COUNT(*) FROM snapshots"),
        }

    def decision_tally(self) -> dict:
        rows = self._conn.execute(
            "SELECT agent, decision, COUNT(*) c FROM decisions GROUP BY agent, decision"
        ).fetchall()
        return {f"{r['agent']}:{r['decision']}": int(r["c"]) for r in rows}

    # ---- experiments (immutable) ------------------------------------------
    def write_experiment(self, rec: ExperimentRecord,
                         hypothesis: Hypothesis = None) -> ExperimentRecord:
        errs = rec.validate()
        if errs:
            raise ValueError("ExperimentRecord invalid: " + "; ".join(errs))
        exists = self._conn.execute(
            "SELECT 1 FROM experiments WHERE id=?", (rec.id,)).fetchone()
        if exists:
            raise ValueError(f"experiment {rec.id} already exists (immutable)")
        self._conn.execute(
            "INSERT INTO experiments VALUES (?,?,?,?,?,?,?)",
            (rec.id, rec.hypothesis_id, rec.window, rec.verdict,
             rec.engine_version, json.dumps(rec.to_dict()), rec.created_at))
        self._conn.commit()
        self._mirror_experiment(rec, hypothesis)
        return rec

    def get_experiment(self, eid: str) -> Optional[ExperimentRecord]:
        row = self._conn.execute(
            "SELECT json FROM experiments WHERE id=?", (eid,)).fetchone()
        return ExperimentRecord.from_dict(json.loads(row["json"])) if row else None

    def list_experiments(self, limit: int = 100) -> List[ExperimentRecord]:
        rows = self._conn.execute(
            "SELECT json FROM experiments ORDER BY created_at DESC LIMIT ?",
            (limit,)).fetchall()
        return [ExperimentRecord.from_dict(json.loads(r["json"])) for r in rows]

    # ---- decisions ---------------------------------------------------------
    def write_decision(self, rec: DecisionRecord) -> DecisionRecord:
        self._conn.execute(
            "INSERT INTO decisions (task_id, agent, phase, decision, json, created_at)"
            " VALUES (?,?,?,?,?,?)",
            (rec.task_id, rec.agent, rec.phase, rec.decision,
             json.dumps(rec.to_dict()), rec.created_at))
        self._conn.commit()
        return rec

    def list_decisions(self, task_id: str = None) -> List[DecisionRecord]:
        if task_id:
            rows = self._conn.execute(
                "SELECT json FROM decisions WHERE task_id=? ORDER BY id", (task_id,)).fetchall()
        else:
            rows = self._conn.execute("SELECT json FROM decisions ORDER BY id").fetchall()
        return [DecisionRecord.from_dict(json.loads(r["json"])) for r in rows]

    # ---- snapshots ---------------------------------------------------------
    def get_snapshot_by_hash(self, source: str, chash: str) -> Optional[DataSnapshot]:
        row = self._conn.execute(
            "SELECT json FROM snapshots WHERE source=? AND content_hash=?",
            (source, chash)).fetchone()
        return DataSnapshot.from_dict(json.loads(row["json"])) if row else None

    def write_snapshot(self, snap: DataSnapshot) -> DataSnapshot:
        """Store a snapshot, reusing an existing one with the same source+hash so
        identical data maps to one stable id (deduplication for provenance)."""
        existing = self.get_snapshot_by_hash(snap.source, snap.content_hash)
        if existing:
            return existing
        self._conn.execute(
            "INSERT INTO snapshots VALUES (?,?,?,?,?)",
            (snap.id, snap.source, snap.content_hash,
             json.dumps(snap.to_dict()), snap.created_at))
        self._conn.commit()
        return snap

    def get_snapshot(self, sid: str) -> Optional[DataSnapshot]:
        row = self._conn.execute(
            "SELECT json FROM snapshots WHERE id=?", (sid,)).fetchone()
        return DataSnapshot.from_dict(json.loads(row["json"])) if row else None

    def list_snapshots(self) -> List[DataSnapshot]:
        rows = self._conn.execute(
            "SELECT json FROM snapshots ORDER BY created_at DESC").fetchall()
        return [DataSnapshot.from_dict(json.loads(r["json"])) for r in rows]

    # ---- multiple-testing ledger (OOS budget) ------------------------------
    def record_oos_test(self, snapshot_id: str, window: str, hypothesis_id: str,
                        prereg_hash: str = "") -> None:
        """Log that a hypothesis was tested against a snapshot's window. Only
        out-of-sample looks consume the false-discovery budget."""
        self._conn.execute(
            "INSERT INTO oos_tests (snapshot_id, window, hypothesis_id, prereg_hash, at)"
            " VALUES (?,?,?,?,?)",
            (snapshot_id, window, hypothesis_id, prereg_hash, utcnow_iso()))
        self._conn.commit()

    def oos_test_count(self, snapshot_id: str, window: str = "out_sample") -> int:
        """Distinct hypotheses tested against this snapshot's OOS window — the
        number of 'looks' at the holdout (multiple-comparisons risk)."""
        row = self._conn.execute(
            "SELECT COUNT(DISTINCT hypothesis_id) c FROM oos_tests "
            "WHERE snapshot_id=? AND window=?", (snapshot_id, window)).fetchone()
        return int(row["c"]) if row else 0

    # ---- graveyard ---------------------------------------------------------
    def bury(self, hypothesis_id: str, reason: str) -> None:
        h = self.get_hypothesis(hypothesis_id)
        title = h.title if h else hypothesis_id
        if h:
            h.status = "GRAVEYARD"
            self.write_hypothesis(h)
        self._conn.execute(
            "INSERT OR REPLACE INTO graveyard VALUES (?,?,?,?)",
            (hypothesis_id, title, reason,
             utcnow_iso()))
        self._conn.commit()
        d = os.path.join(self.vault, "graveyard")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, f"{hypothesis_id}.md"), "w", encoding="utf-8") as f:
            f.write(f"# GRAVEYARD — {title}\n\n#atlas #graveyard\n\n"
                    f"**Reason:** {reason}\n")

    def list_graveyard(self) -> List[dict]:
        rows = self._conn.execute(
            "SELECT * FROM graveyard ORDER BY at DESC").fetchall()
        return [dict(r) for r in rows]

    # ---- policy memory (human-reviewed) ------------------------------------
    def set_policy(self, key: str, value: dict, updated_by: str = "human") -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO policy VALUES (?,?,?,?)",
            (key, json.dumps(value),
             utcnow_iso(),
             updated_by))
        self._conn.commit()

    def get_policy(self, key: str, default: dict = None) -> Optional[dict]:
        row = self._conn.execute("SELECT json FROM policy WHERE key=?", (key,)).fetchone()
        return json.loads(row["json"]) if row else default

    # ---- knowledge ---------------------------------------------------------
    def write_knowledge(self, note: KnowledgeNote) -> KnowledgeNote:
        self._conn.execute(
            "INSERT OR REPLACE INTO knowledge VALUES (?,?,?,?,?)",
            (note.id, note.title, ",".join(note.topic_tags),
             json.dumps(note.to_dict()), note.created_at))
        self._conn.commit()
        self._mirror_knowledge(note)
        return note

    # ---- Obsidian mirror ---------------------------------------------------
    def _mirror_experiment(self, rec: ExperimentRecord, h: Hypothesis) -> str:
        d = os.path.join(self.vault, "experiments")
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, f"{rec.id}.md")
        m = rec.metrics or {}
        lines = [
            "---",
            f"id: {rec.id}",
            f"hypothesis: {rec.hypothesis_id} v{rec.hypothesis_version}",
            f"engine_version: {rec.engine_version}",
            f"window: {rec.window}",
            f"verdict: {rec.verdict}",
            f"created_at: {rec.created_at}",
            "tags: [atlas, experiment]",
            "---",
            f"# Experiment {rec.id}",
            "",
            f"**Hypothesis:** {(h.title if h else rec.hypothesis_id)} "
            f"({rec.hypothesis_id} v{rec.hypothesis_version})",
            f"**Window:** {rec.window}  ·  **Verdict:** {rec.verdict}",
            "",
            "## Metrics",
        ]
        if m.get("trades"):
            for k in ("trades", "win_rate", "profit_factor", "expectancy_r",
                      "total_r", "max_drawdown_r", "sharpe_per_trade"):
                if k in m:
                    lines.append(f"- **{k}**: {m[k]}")
        else:
            lines.append("- no trades")
        if rec.monte_carlo and rec.monte_carlo.get("bootstrap"):
            b = rec.monte_carlo["bootstrap"]
            lines += ["", "## Monte Carlo",
                      f"- P(total<0): {b.get('p_total_negative')}",
                      f"- median expectancy R: {b.get('expectancy_r',{}).get('p50')}"]
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        return path

    def _mirror_knowledge(self, note: KnowledgeNote) -> str:
        d = os.path.join(self.vault, "knowledge")
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, f"{note.id}.md")
        tags = " ".join(f"#{t}" for t in note.topic_tags)
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"# {note.title}\n\n{tags}\n\n{note.summary}\n\n"
                    f"**Lesson:** {note.lesson}\n\nSource: {note.source}\n")
        return path

    def close(self) -> None:
        self._conn.close()
