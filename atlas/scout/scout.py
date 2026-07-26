"""The Scout agent. Sources an idea, formalises it, and (optionally) tests it."""
from __future__ import annotations

import os
import re
from typing import Callable, Dict, List, Optional

import yaml

from .fetch import fetch
from .extract import extract_rules
from .build import build_hypothesis
from ..memory import MemoryStore
from ..agents.librarian import Librarian


def _slug(source: str, template: str) -> str:
    base = re.sub(r"^https?://", "", source)
    base = re.sub(r"[^a-zA-Z0-9]+", "_", base).strip("_")[:40] or "source"
    return f"scout_{template}_{base}".lower()


class Scout:
    name = "Scout"
    nature = "hybrid"

    def __init__(self, extractor: Optional[Callable[[str], Dict]] = None):
        # extractor(text)->{template,params}: wire to an LLM for good extraction.
        self.extractor = extractor

    def scout(self, source: str, root: str = ".", markets: List[str] = None,
              data_split: Dict = None, name: str = None, text: str = None) -> Dict:
        """Fetch a source, extract rules, build a pre-registered hypothesis, store
        a knowledge note, and write the hypothesis YAML under hypotheses/scouted/.
        Returns a summary (does not test). `text` lets a caller pass already-fetched
        content so a URL isn't fetched twice."""
        text = text if text is not None else fetch(source)
        extracted = extract_rules(text, self.extractor)
        extracted["source"] = source
        markets = markets or ["GBPUSD", "USDJPY"]
        name = name or _slug(source, extracted["template"])
        cfg = build_hypothesis(extracted, name, markets, data_split)

        store = MemoryStore(root)
        try:
            Librarian(self.extractor).ingest_text(
                text[:4000], f"Scouted: {name}", str(source), store)
        finally:
            store.close()

        d = os.path.join(root, "hypotheses", "scouted")
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, f"{name}.yaml")
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(cfg, f, sort_keys=False)

        return {"name": name, "template": extracted["template"],
                "params": extracted.get("params", {}),
                "evidence": extracted.get("evidence", ""), "path": path, "cfg": cfg}

    def scout_and_test(self, source: str, root: str = ".", markets: List[str] = None,
                       data_utc_offset: float = 0, data_split: Dict = None,
                       name: str = None, text: str = None) -> Dict:
        """Scout an idea and immediately run it through the full council."""
        from ..kernel import Orchestrator
        info = self.scout(source, root, markets, data_split, name, text=text)
        res = Orchestrator(root).run(info["path"], window="out_sample",
                                     data_utc_offset=data_utc_offset)
        info.update({"verdict": res["experiment"].verdict,
                     "reached_layer": res["reached_layer"],
                     "advanced": res["advanced"],
                     "candidate_id": res.get("candidate_id")})
        return info

    def discover(self, query: str, root: str = ".", markets: List[str] = None,
                 max_results: int = 5, test: bool = False,
                 data_utc_offset: float = 0, fx_only: bool = True,
                 searcher: Optional[Callable[[str, int], List[str]]] = None) -> Dict:
        """Find candidate articles for a topic, then scout (and optionally test)
        each one. `searcher(query, max_results)->[url,...]` is injectable; by
        default it uses the Anthropic web-search server tool.

        With `fx_only` (default), each source is fetched once and gated: pieces
        that read as equity/options/crypto rather than spot FX are skipped, so we
        never test an off-market idea on GBPUSD/USDJPY and mislabel the result.

        Returns {"query", "urls", "results":[...], "skipped":[...], "errors":[...]}.
        Individual source failures are captured, never fatal — the sweep goes on.
        """
        if searcher is None:
            from .discover import anthropic_searcher
            searcher = anthropic_searcher(fx_only=fx_only)
        urls = searcher(query, max_results)

        results, skipped, errors = [], [], []
        for url in urls:
            try:
                text = fetch(url)
                if fx_only:
                    from .discover import is_fx_source
                    if not is_fx_source(text):
                        skipped.append({"url": url,
                                        "reason": "off-market (not spot FX)"})
                        continue
                if test:
                    info = self.scout_and_test(url, root, markets,
                                               data_utc_offset=data_utc_offset,
                                               text=text)
                else:
                    info = self.scout(url, root, markets, text=text)
                results.append(info)
            except Exception as e:               # a dead link mustn't stop the sweep
                errors.append({"url": url, "error": f"{type(e).__name__}: {e}"})
        return {"query": query, "urls": urls, "results": results,
                "skipped": skipped, "errors": errors}
