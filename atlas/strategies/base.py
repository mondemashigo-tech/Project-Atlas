"""Strategy interface. A strategy is config-driven: its behaviour is fully
determined by the hypothesis YAML, so variants are data, not code."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
import pandas as pd


@dataclass
class Signal:
    direction: str      # "BUY" or "SELL"
    entry: float
    stop: float
    target: float
    reason: str = ""


class Strategy:
    """Base class. Subclasses precompute indicators, then answer one question
    per entry bar: given everything visible AT this bar's close, is there a
    trade? Look-ahead is prevented by only ever reading up to the current bar."""

    name = "base"

    def __init__(self, config: dict):
        self.config = config

    def prepare(self, entry_df: pd.DataFrame, symbol: str = None,
                context: dict = None) -> None:
        """Precompute indicator columns on the entry-timeframe frame. `symbol`
        and `context` (loaded external data sources) are optional and only used
        by strategies that apply carry / news filters."""
        raise NotImplementedError

    def signal_at(self, i: int) -> Optional[Signal]:
        """Return a Signal for entry bar index i, or None. Must not read i+1…"""
        raise NotImplementedError

    # Registry so the CLI can build a strategy from a config string.
    _registry: dict = {}

    @classmethod
    def register(cls, key):
        def deco(sub):
            cls._registry[key] = sub
            return sub
        return deco

    @classmethod
    def create(cls, config: dict) -> "Strategy":
        key = config.get("template", "trend_continuation")
        if key not in cls._registry:
            raise ValueError(f"Unknown strategy template '{key}'. "
                             f"Known: {list(cls._registry)}")
        return cls._registry[key](config)
