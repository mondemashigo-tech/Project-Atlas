"""Append-only research journal.

Every hypothesis run leaves a dated record — config fingerprint, verdict, and
the headline in/out-sample metrics — appended to a JSONL log (one run per line).
The discipline this enforces: results accumulate into a history you cannot
quietly rewrite, and the fingerprint changes the moment the hypothesis changes,
so you can always see whether a "better" number came from a real result or from
moving the goalposts.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Dict, List

_FP_KEYS = ("name", "version", "markets", "timeframes", "session", "weekdays",
            "trend", "entry", "risk", "costs", "data", "criteria", "optimize")
_SLIM = ("trades", "win_rate", "profit_factor", "expectancy_r", "total_r",
         "max_drawdown_r")


def fingerprint(cfg: dict) -> str:
    blob = json.dumps({k: cfg.get(k) for k in _FP_KEYS}, sort_keys=True, default=str)
    return hashlib.sha1(blob.encode()).hexdigest()[:12]


def _slim(m: dict) -> dict:
    return {k: m.get(k) for k in _SLIM if k in m}


def append(cfg: dict, results: dict, verdict_out: dict = None,
           path: str = "reports/journal.jsonl") -> dict:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    rec = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "name": cfg["name"],
        "version": str(cfg.get("version", "?")),
        "fingerprint": fingerprint(cfg),
        "markets": list(cfg["markets"]),
        "in_sample": _slim(results["in_sample"]["metrics"]),
        "out_sample": _slim(results["out_sample"]["metrics"]),
        "verdict_out": (verdict_out or {}).get("result"),
    }
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")
    return rec


def load(path: str = "reports/journal.jsonl") -> List[dict]:
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def render(records: List[dict]) -> str:
    if not records:
        return "JOURNAL\n  (empty)\n"
    lines = ["JOURNAL  (most recent last)"]
    for r in records:
        o = r.get("out_sample", {})
        lines.append(
            f"  {r['ts']}  {r['name']} v{r['version']} [{r['fingerprint']}]  "
            f"OOS T:{o.get('trades','-')} PF:{o.get('profit_factor','-')} "
            f"exp:{o.get('expectancy_r','-')}R  -> {r.get('verdict_out','-')}")
    return "\n".join(lines) + "\n"
