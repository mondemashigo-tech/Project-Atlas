"""Extract candidate trading rules from source text.

Two paths:
- **LLM extractor** (best): an injected callable `extractor(text) -> dict` that
  returns {template, params}. Wire it to an LLM (or run in-session) and it reads
  free prose reliably. This is the intended production path.
- **Deterministic fallback** (crude but dependency-free): keyword-match the
  strategy family and regex out the obvious numbers (EMA/MA period, ATR multiple,
  R:R, opening-range minutes). Good enough to *queue something testable* when no
  LLM is available; it will miss nuance, which is fine — the validation ladder is
  what decides, not the extractor.

Honesty: the fallback is a rough reader. It never fabricates a rule it can't find
a basis for; unknown parameters keep the skeleton defaults.
"""
from __future__ import annotations

import re
from typing import Callable, Dict, Optional

_FAMILY_KEYWORDS = {
    "orb": ["opening range", "orb", "first candle", "first 5-min", "first 15-min",
            "range breakout"],
    "mean_reversion": ["mean reversion", "revert", "overbought", "oversold",
                       "rsi", "bollinger", "fade", "z-score", "z score"],
    "breakout": ["breakout", "donchian", "channel break", "range break",
                 "20-day high", "new high"],
    "trend_continuation": ["trend", "pullback", "continuation", "with the trend",
                           "ema", "moving average", "retest"],
}


def _detect_family(text: str) -> str:
    low = text.lower()
    scores = {fam: sum(low.count(k) for k in kws)
              for fam, kws in _FAMILY_KEYWORDS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "trend_continuation"


def _num(pattern: str, text: str, cast=float):
    m = re.search(pattern, text, re.I)
    if m:
        try:
            return cast(m.group(1))
        except (ValueError, IndexError):
            return None
    return None


def heuristic_extract(text: str) -> Dict:
    fam = _detect_family(text)
    params: Dict[str, object] = {}

    ema = _num(r"(\d{1,3})[- ]?(?:period[- ]?)?(?:ema|moving average|ma)\b", text, int) \
        or _num(r"(?:ema|ma)[- ]?(\d{1,3})", text, int)
    atr_mult = _num(r"(\d(?:\.\d)?)\s*(?:x|times|\*)?\s*atr", text)
    rr = _num(r"1\s*[:x]\s*(\d(?:\.\d)?)", text) or _num(r"(\d)\s*r\b\s*target", text)
    orange = _num(r"first\s*(\d{1,2})[- ]?min", text, int) \
        or _num(r"(\d{1,2})[- ]?minute\s*(?:opening\s*)?range", text, int)

    if fam == "trend_continuation":
        if ema:
            params["entry.pullback_ema"] = ema
    elif fam == "mean_reversion":
        if ema:
            params["meanrev.ma_period"] = ema
        z = _num(r"(\d(?:\.\d)?)\s*(?:standard deviation|std|sigma|z)", text)
        if z:
            params["meanrev.entry_z"] = z
    elif fam == "breakout":
        chan = _num(r"(\d{1,3})[- ]?(?:day|bar|period)\s*(?:high|channel|breakout)", text, int)
        if chan:
            params["breakout.channel"] = chan
    elif fam == "orb":
        if orange:
            params["orb.range_minutes"] = orange
        if ema:
            params["orb.ema"] = ema

    if atr_mult:
        params["risk.stop.atr_mult"] = atr_mult
    if rr:
        params["risk.target_r"] = rr

    return {"template": fam, "params": params,
            "evidence": f"family={fam} via keywords; params={params or 'defaults'}"}


def extract_rules(text: str, extractor: Optional[Callable[[str], Dict]] = None) -> Dict:
    """Return {template, params, evidence}. Uses the LLM extractor if given and it
    returns a usable dict; otherwise the deterministic fallback."""
    if extractor:
        try:
            out = extractor(text)
            if isinstance(out, dict) and out.get("template"):
                out.setdefault("params", {})
                out.setdefault("evidence", "llm extractor")
                return out
        except Exception:
            pass
    return heuristic_extract(text)
