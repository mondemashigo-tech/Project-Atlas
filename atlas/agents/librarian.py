"""The Librarian — ingests source material into tagged knowledge (Volume 2 §5.3,
Volume 5 §8). Deterministic core: read a text/markdown file, derive a title, tag
it against a topic taxonomy by keyword, and store a KnowledgeNote (mirrored to the
Obsidian vault). An optional narrator can improve the summary in-session; it never
invents facts about the source.
"""
from __future__ import annotations

import os
from typing import List

from ..schemas import KnowledgeNote, new_id
from ..memory import MemoryStore

TOPIC_KEYWORDS = {
    "trend": ["trend", "momentum", "moving average", "ema", "breakout continuation"],
    "mean_reversion": ["mean reversion", "revert", "overbought", "oversold",
                       "bollinger", "fade"],
    "breakout": ["breakout", "range break", "donchian", "channel"],
    "volatility": ["volatility", "atr", "range expansion", "vix"],
    "risk": ["risk", "position sizing", "drawdown", "stop loss", "kelly"],
    "execution": ["slippage", "spread", "liquidity", "microstructure", "fill"],
    "session": ["london", "new york", "asian", "session", "open"],
    "carry": ["carry", "interest rate", "differential", "swap"],
    "psychology": ["discipline", "revenge", "fomo", "psychology", "emotion"],
    "statistics": ["expectancy", "sample size", "significance", "overfit",
                   "walk-forward", "monte carlo"],
}


class Librarian:
    name = "Librarian"
    nature = "llm"

    def __init__(self, narrator=None):
        self.narrator = narrator

    def _tag(self, text: str) -> List[str]:
        low = text.lower()
        return [topic for topic, kws in TOPIC_KEYWORDS.items()
                if any(kw in low for kw in kws)]

    def _summarise(self, text: str) -> str:
        for para in text.split("\n\n"):
            p = para.strip().lstrip("#").strip()
            if len(p) > 40:
                return (p[:400] + "…") if len(p) > 400 else p
        return text.strip()[:400]

    def ingest_text(self, text: str, title: str, source: str,
                    store: MemoryStore) -> KnowledgeNote:
        note = KnowledgeNote(id=new_id("KN"), title=title,
                             topic_tags=self._tag(text) or ["uncategorized"],
                             summary=self._summarise(text), source=source)
        if self.narrator:
            try:
                note.lesson = self.narrator(f"One practical lesson from: {text[:1500]}")
            except Exception:
                pass
        store.write_knowledge(note)
        return note

    def ingest(self, path: str, store: MemoryStore) -> List[KnowledgeNote]:
        """Ingest a file or every .md/.txt in a directory."""
        paths = []
        if os.path.isdir(path):
            for root, _dirs, files in os.walk(path):
                for f in files:
                    if f.lower().endswith((".md", ".txt")):
                        paths.append(os.path.join(root, f))
        else:
            paths = [path]
        notes = []
        for p in sorted(paths):
            with open(p, encoding="utf-8", errors="ignore") as fh:
                text = fh.read()
            first = next((ln.lstrip("# ").strip() for ln in text.splitlines()
                          if ln.strip()), os.path.basename(p))
            notes.append(self.ingest_text(text, first[:120], p, store))
        return notes
