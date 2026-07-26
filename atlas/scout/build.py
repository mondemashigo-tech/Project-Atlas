"""Turn extracted rules into a full, testable hypothesis config.

Each strategy family has a skeleton; the Scout fills in the parameters it
extracted and leaves sensible defaults for the rest. The result is a normal
hypothesis dict — indistinguishable, once written, from a hand-authored one, and
subject to exactly the same validation ladder.
"""
from __future__ import annotations

import copy
from typing import Dict, List

_DEFAULT_SPLIT = {"in_sample": ["2020-01-01", "2022-12-31"],
                  "out_sample": ["2023-01-01", "2025-12-31"]}
_DEFAULT_CRIT = {"success": {"profit_factor": 1.3, "min_trades": 150,
                             "expectancy": "positive"},
                 "failure": {"profit_factor": 1.0, "expectancy": "negative"}}
_DEFAULT_COSTS = {"spread_pips": 1.0, "commission_r": 0.03}

SKELETONS = {
    "trend_continuation": {
        "timeframes": {"bias": "H1", "entry": "M5"},
        "session": {"start": "00:00", "end": "23:59", "tz": "UTC"},
        "weekdays": [0, 1, 2, 3, 4],
        "trend": {"ema_fast": 50, "ema_slow": 200}, "entry": {"pullback_ema": 20},
        "risk": {"stop": {"atr_mult": 1.0, "atr_period": 14, "swing_lookback": 20},
                 "target_r": 2.0, "max_trades_per_day": 3},
    },
    "mean_reversion": {
        "timeframes": {"entry": "M5"}, "weekdays": [0, 1, 2, 3, 4],
        "meanrev": {"ma_period": 20, "entry_z": 2.0, "exit": "mean"},
        "risk": {"stop": {"atr_mult": 1.5, "atr_period": 14}, "target_r": 1.5,
                 "max_trades_per_day": 3},
    },
    "breakout": {
        "timeframes": {"entry": "M5"}, "weekdays": [0, 1, 2, 3, 4],
        "breakout": {"channel": 20},
        "risk": {"stop": {"atr_mult": 1.0, "atr_period": 14}, "target_r": 2.0,
                 "max_trades_per_day": 3},
    },
    "orb": {
        "timeframes": {"entry": "M5"},
        "session": {"start": "08:00", "end": "11:00", "tz": "Europe/London"},
        "weekdays": [0, 1, 2, 3, 4],
        "orb": {"range_minutes": 5, "ema": 20},
        "risk": {"stop": {"type": "opposite_range", "atr_mult": 1.0, "atr_period": 14},
                 "target_r": 2.0, "max_trades_per_day": 1},
    },
}


def _set_path(d: dict, dotted: str, value) -> None:
    keys = dotted.split(".")
    cur = d
    for k in keys[:-1]:
        cur = cur.setdefault(k, {})
    cur[keys[-1]] = value


def build_hypothesis(extracted: dict, name: str, markets: List[str],
                     data_split: Dict = None) -> dict:
    """extracted = {template, params:{dotted_path: value}, ...}."""
    template = extracted.get("template", "trend_continuation")
    if template not in SKELETONS:
        template = "trend_continuation"
    cfg = copy.deepcopy(SKELETONS[template])
    cfg.update({
        "name": name, "version": "0.1", "template": template,
        "markets": list(markets),
        "costs": dict(_DEFAULT_COSTS),
        "criteria": copy.deepcopy(_DEFAULT_CRIT),
        "data": copy.deepcopy(data_split or _DEFAULT_SPLIT),
    })
    for path, val in (extracted.get("params") or {}).items():
        _set_path(cfg, path, val)
    cfg["source"] = extracted.get("source", "scout")
    return cfg
