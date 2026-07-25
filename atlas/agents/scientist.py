"""The Scientist — generates testable hypotheses and prioritises them (Volume 2
§5.2, Volume 5 §9-10).

Deterministic core: from a base hypothesis config, produce variants via a
parameter grid (parameter-boundary exploration) and rank them by novelty (not
already tested/buried), simplicity, and whether they were pre-registered cleanly.
An optional narrator proposes genuinely new ideas in-session; the deterministic
path guarantees the lab keeps moving without one.
"""
from __future__ import annotations

import copy
from typing import Dict, List, Tuple

from ..schemas import Hypothesis
from ..research.fx.paramgrid import expand


class Scientist:
    name = "Scientist"
    nature = "llm"

    def __init__(self, narrator=None):
        self.narrator = narrator

    def propose(self, base_cfg: dict, grid: Dict[str, list] = None) -> List[dict]:
        """Return variant configs. With no grid, use a sensible default for the
        template. Each variant is renamed to encode its overrides."""
        if grid is None:
            grid = self._default_grid(base_cfg)
        variants = []
        for overrides, cfg in expand(base_cfg, grid):
            if not overrides:
                continue
            v = copy.deepcopy(cfg)
            tag = ",".join(f"{k.split('.')[-1]}={val}" for k, val in overrides.items())
            v["name"] = f"{base_cfg['name']}__{tag}"
            v["_overrides"] = overrides
            variants.append(v)
        return variants

    def _default_grid(self, cfg: dict) -> Dict[str, list]:
        t = cfg.get("template")
        if t == "trend_continuation":
            return {"risk.target_r": [1.5, 2.0, 2.5], "trend.ema_fast": [30, 50, 80]}
        if t == "mean_reversion":
            return {"meanrev.entry_z": [1.5, 2.0, 2.5], "risk.target_r": [1.0, 1.5]}
        if t == "breakout":
            return {"breakout.channel": [10, 20, 40], "risk.target_r": [1.5, 2.0, 3.0]}
        return {"risk.target_r": [1.5, 2.0, 2.5]}

    def prioritise(self, variants: List[dict], store) -> List[Tuple[dict, float, str]]:
        """Score each variant (higher = test sooner). Novelty dominates: anything
        matching a prior/buried hypothesis is deprioritised."""
        scored = []
        for cfg in variants:
            hyp = Hypothesis.from_fx_config(cfg).freeze()
            prior = store.find_hypotheses_by_prereg(hyp.preregistration_hash) if store else []
            buried = any(p["status"] == "GRAVEYARD" for p in prior)
            novelty = 0.0 if prior else 1.0
            n_over = len(cfg.get("_overrides", {}))
            simplicity = 1.0 / (1.0 + n_over)
            score = round(0.7 * novelty + 0.3 * simplicity, 3)
            reason = ("already tested" if prior and not buried else
                      "in graveyard — skip" if buried else "novel")
            scored.append((cfg, score, reason))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored

    def render(self, scored: List[Tuple[dict, float, str]]) -> str:
        lines = [f"SCIENTIST — {len(scored)} proposed hypotheses (ranked)"]
        for cfg, score, reason in scored:
            lines.append(f"  {score:>5}  {cfg['name']:45} — {reason}")
        return "\n".join(lines) + "\n"
