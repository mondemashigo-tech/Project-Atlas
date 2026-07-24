"""Load and validate a hypothesis config (YAML). A hypothesis is frozen once
written — the platform's job is to test it, not to let us quietly edit it."""
from __future__ import annotations

import yaml

REQUIRED = ["name", "markets", "timeframes", "session", "trend", "entry",
            "risk", "criteria", "data"]


def load(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    missing = [k for k in REQUIRED if k not in cfg]
    if missing:
        raise ValueError(f"{path}: missing required keys {missing}")
    for tf in ("bias", "entry"):
        if tf not in cfg["timeframes"]:
            raise ValueError(f"{path}: timeframes.{tf} is required")
    for win in ("in_sample", "out_sample"):
        if win not in cfg["data"] or len(cfg["data"][win]) != 2:
            raise ValueError(f"{path}: data.{win} must be [start, end]")
    return cfg
