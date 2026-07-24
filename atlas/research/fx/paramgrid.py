"""Parameter-grid expansion, shared by walk-forward and the optimiser.

A hypothesis may carry an ``optimize:`` block mapping dotted config paths to
lists of candidate values, e.g.::

    optimize:
      trend.ema_fast: [30, 50, 80]
      risk.target_r: [1.5, 2.0, 2.5]

`expand` returns the full Cartesian product as (overrides, variant_cfg) pairs.
"""
from __future__ import annotations

import copy
import itertools
from typing import Dict, List, Tuple


def set_path(d: dict, dotted: str, value) -> None:
    keys = dotted.split(".")
    cur = d
    for k in keys[:-1]:
        cur = cur.setdefault(k, {})
    cur[keys[-1]] = value


def expand(cfg: dict, grid: dict = None) -> List[Tuple[Dict, dict]]:
    grid = grid if grid is not None else (cfg.get("optimize") or {})
    if not grid:
        return [({}, cfg)]
    keys = list(grid.keys())
    out = []
    for combo in itertools.product(*[grid[k] for k in keys]):
        overrides = dict(zip(keys, combo))
        variant = copy.deepcopy(cfg)
        for path, val in overrides.items():
            set_path(variant, path, val)
        out.append((overrides, variant))
    return out
