"""Atlas core data models.

Plain dataclasses (stdlib only, to keep the core dependency-light and portable).
Each record carries a `validate()` returning a list of problems and an
`ensure_valid()` that raises. Serialisation is via `to_dict()` / `from_dict()`.

The Strategy Registry lifecycle and the "capital-bearing statuses" (which require
a human approval token to enter) are defined here so both the registry and its
tests share one source of truth.
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

# Bump when the engine's numeric behaviour changes, so old ExperimentRecords are
# never silently compared against new results (Volume 4 §13 reproducibility).
ATLAS_ENGINE_VERSION = "0.1.0"


class SchemaError(ValueError):
    """Raised when a record fails validation."""


# ---- helpers ---------------------------------------------------------------

def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def utcnow_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def content_hash(obj: Any) -> str:
    blob = json.dumps(obj, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


# ---- Hypothesis ------------------------------------------------------------

# Research lifecycle (Volume 3 §4). Frozen at SPECIFIED.
HYPOTHESIS_STATUSES = (
    "DRAFT", "SPECIFIED", "BACKTESTED", "STAT_VALIDATED", "OUT_OF_SAMPLE",
    "WALK_FORWARD", "MONTE_CARLO", "REGIME_TESTED", "PAPER", "MICRO_LIVE",
    "PORTFOLIO", "MONITORING", "RETIRED", "GRAVEYARD",
)

# Fields that define the *experiment identity*. Change any of them and the
# pre-registration hash changes — i.e. it is a new hypothesis, not a moved
# goalpost (Volume 1 pre-registration).
_PREREG_FIELDS = ("domain", "markets", "timeframes", "spec", "directional_bias",
                  "session", "filters", "risk_rules", "success_criteria",
                  "failure_criteria", "data_split")


@dataclass
class Hypothesis:
    id: str
    version: str
    domain: str
    title: str
    markets: List[str]
    timeframes: Dict[str, str]
    spec: Dict[str, Any]                 # the machine-readable rules
    success_criteria: Dict[str, Any]
    failure_criteria: Dict[str, Any]
    data_split: Dict[str, Any]           # {in_sample:[a,b], out_sample:[a,b]}
    directional_bias: str = "both"       # long | short | both
    session: Optional[Dict[str, Any]] = None
    filters: Dict[str, Any] = field(default_factory=dict)   # news/carry
    risk_rules: Dict[str, Any] = field(default_factory=dict)
    validation_plan: List[str] = field(default_factory=list)
    confidence_score: float = 0.0
    status: str = "DRAFT"
    preregistration_hash: Optional[str] = None
    created_at: str = field(default_factory=utcnow_iso)

    def compute_prereg_hash(self) -> str:
        return content_hash({k: getattr(self, k) for k in _PREREG_FIELDS})

    def freeze(self) -> "Hypothesis":
        """Lock the pre-registration hash and mark SPECIFIED. Idempotent."""
        if self.preregistration_hash is None:
            self.preregistration_hash = self.compute_prereg_hash()
        if self.status == "DRAFT":
            self.status = "SPECIFIED"
        return self

    def validate(self) -> List[str]:
        errs = []
        if not self.id:
            errs.append("id is required")
        if not self.markets:
            errs.append("markets must be non-empty")
        if "entry" not in (self.timeframes or {}):
            errs.append("timeframes.entry is required")
        for w in ("in_sample", "out_sample"):
            v = (self.data_split or {}).get(w)
            if not v or len(v) != 2:
                errs.append(f"data_split.{w} must be [start, end]")
        if self.directional_bias not in ("long", "short", "both"):
            errs.append("directional_bias must be long|short|both")
        if self.status not in HYPOTHESIS_STATUSES:
            errs.append(f"status must be one of {HYPOTHESIS_STATUSES}")
        if not self.spec:
            errs.append("spec (rules) must be non-empty")
        # If frozen, the hash must still match the identity fields.
        if self.preregistration_hash and \
                self.preregistration_hash != self.compute_prereg_hash():
            errs.append("preregistration_hash does not match spec — rule drift")
        return errs

    def ensure_valid(self) -> "Hypothesis":
        errs = self.validate()
        if errs:
            raise SchemaError(f"Hypothesis {self.id}: " + "; ".join(errs))
        return self

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Hypothesis":
        return cls(**d)

    @classmethod
    def from_fx_config(cls, cfg: dict) -> "Hypothesis":
        """Build a Hypothesis from a loaded FX hypothesis YAML (the existing
        research module's config), mapping its blocks onto the schema."""
        spec = {k: cfg[k] for k in ("trend", "entry", "meanrev", "breakout",
                                    "orb", "weekdays", "costs", "template",
                                    # composed strategies: the invented rules ARE
                                    # the identity — they must be pre-registered.
                                    "features", "entry_long", "entry_short",
                                    "exit") if k in cfg}
        filters = {k: cfg[k] for k in ("news_filter", "carry") if k in cfg}
        h = cls(
            id=new_id("HYP"),
            version=str(cfg.get("version", "1.0")),
            domain="fx",
            title=cfg["name"],
            markets=list(cfg["markets"]),
            timeframes=dict(cfg["timeframes"]),
            spec=spec,
            success_criteria=dict(cfg.get("criteria", {}).get("success", {})),
            failure_criteria=dict(cfg.get("criteria", {}).get("failure", {})),
            data_split=dict(cfg["data"]),
            session=cfg.get("session"),
            filters=filters,
            risk_rules=dict(cfg.get("risk", {})),
            validation_plan=list(cfg.get("validation_plan", [])),
        )
        return h


# ---- DataSnapshot ----------------------------------------------------------

@dataclass
class DataSnapshot:
    id: str
    source: str                          # e.g. "MT5:OctaFX-Demo", "HistData"
    symbols: List[str]
    timeframe: str
    span: List[str]                      # [first_iso, last_iso]
    row_count: int
    content_hash: str
    created_at: str = field(default_factory=utcnow_iso)

    def validate(self) -> List[str]:
        errs = []
        if not self.symbols:
            errs.append("symbols required")
        if self.row_count < 0:
            errs.append("row_count must be >= 0")
        return errs

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "DataSnapshot":
        return cls(**d)


# ---- ExperimentRecord (immutable evidence) ---------------------------------

@dataclass
class ExperimentRecord:
    id: str
    hypothesis_id: str
    hypothesis_version: str
    engine_version: str
    data_snapshot_id: Optional[str]
    window: str                          # in_sample | out_sample | full
    metrics: Dict[str, Any]
    verdict: Optional[str] = None
    monte_carlo: Optional[Dict[str, Any]] = None
    walk_forward: Optional[Dict[str, Any]] = None
    trade_log_ref: Optional[str] = None
    created_at: str = field(default_factory=utcnow_iso)

    def validate(self) -> List[str]:
        errs = []
        if not self.hypothesis_id:
            errs.append("hypothesis_id required")
        if not self.engine_version:
            errs.append("engine_version required")
        if self.window not in ("in_sample", "out_sample", "full"):
            errs.append("window must be in_sample|out_sample|full")
        return errs

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ExperimentRecord":
        return cls(**d)


# ---- DecisionRecord (agent ruling / audit unit) ----------------------------

@dataclass
class DecisionRecord:
    task_id: str
    agent: str
    phase: str
    input_summary: str
    evidence: str
    decision: str
    confidence: str = "medium"           # low | medium | high
    next_action: str = ""
    created_at: str = field(default_factory=utcnow_iso)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "DecisionRecord":
        return cls(**d)


# ---- StrategyRecord (the Registry airlock entry) ---------------------------

# Lifecycle FSM. A strategy may only move along these edges.
STRATEGY_STATUSES = ("candidate", "paper", "micro_live", "live", "retired")
STRATEGY_LIFECYCLE = {
    "candidate": ("paper", "retired"),
    "paper": ("micro_live", "retired", "candidate"),
    "micro_live": ("live", "retired", "paper"),
    "live": ("retired", "micro_live"),
    "retired": (),
}
# Entering any of these requires a human approval token (never autonomous).
CAPITAL_BEARING_STATUSES = ("paper", "micro_live", "live")


@dataclass
class StrategyRecord:
    strategy_id: str
    source_hypothesis_id: str
    source_hypothesis_version: str
    validating_experiment_ids: List[str]
    frozen_executable_spec: Dict[str, Any]
    status: str = "candidate"
    allocation: float = 0.0
    risk_limits: Dict[str, Any] = field(default_factory=dict)
    approvals: List[Dict[str, str]] = field(default_factory=list)
    version: int = 1
    monitoring_state: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utcnow_iso)
    updated_at: str = field(default_factory=utcnow_iso)

    def validate(self) -> List[str]:
        errs = []
        if not self.source_hypothesis_id:
            errs.append("source_hypothesis_id required")
        if not self.frozen_executable_spec:
            errs.append("frozen_executable_spec required")
        if self.status not in STRATEGY_STATUSES:
            errs.append(f"status must be one of {STRATEGY_STATUSES}")
        if not self.validating_experiment_ids:
            errs.append("at least one validating experiment is required")
        return errs

    def ensure_valid(self) -> "StrategyRecord":
        errs = self.validate()
        if errs:
            raise SchemaError(f"StrategyRecord {self.strategy_id}: " + "; ".join(errs))
        return self

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "StrategyRecord":
        return cls(**d)


# ---- KnowledgeNote (markdown-first, Obsidian) ------------------------------

@dataclass
class KnowledgeNote:
    id: str
    title: str
    topic_tags: List[str]
    summary: str
    source: str = ""
    links: List[str] = field(default_factory=list)
    lesson: str = ""
    created_at: str = field(default_factory=utcnow_iso)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "KnowledgeNote":
        return cls(**d)
