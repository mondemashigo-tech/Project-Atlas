"""DataSnapshot construction — the reproducibility anchor.

A snapshot captures *which data* an experiment ran on: the symbols, timeframe,
exact date span, row count, and a content hash. ExperimentRecords reference a
snapshot id so any verdict can be tied back to the precise data behind it
(Volume 4 §13).
"""
from __future__ import annotations

import os
from typing import List

from .schemas import DataSnapshot, new_id, content_hash
from .research.fx import data as fx_data


def make_snapshot(datasets_dir: str, symbols: List[str], timeframe: str,
                  source: str) -> DataSnapshot:
    spans, total, sig = [], 0, []
    present = []
    for sym in symbols:
        try:
            df = fx_data.load_symbol(datasets_dir, sym, timeframe)
        except FileNotFoundError:
            continue
        if not len(df):
            continue
        present.append(sym)
        first, last = str(df.index.min()), str(df.index.max())
        spans.append((first, last))
        total += len(df)
        sig.append((sym.upper(), first, last, len(df)))
    span = [min(s[0] for s in spans), max(s[1] for s in spans)] if spans else ["", ""]
    return DataSnapshot(
        id=new_id("DS"),
        source=source,
        symbols=present,
        timeframe=timeframe,
        span=span,
        row_count=total,
        content_hash=content_hash(sorted(sig)),
    )
