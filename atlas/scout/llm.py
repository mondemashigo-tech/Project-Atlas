"""LLM-backed rule extractor for the Scout.

The heuristic reader in ``extract.py`` only catches numbers that sit next to a
keyword it knows. Real articles bury the rules in prose. This module wires an
actual LLM (Anthropic SDK) to read arbitrary text and return the same
``{template, params, evidence}`` shape the rest of the Scout already consumes.

Design contract (so the pipe stays safe):
- The LLM is asked for STRICT JSON with a fixed schema.
- ``template`` is validated against the known set; anything else is rejected so
  the caller (``extract_rules``) falls back to the heuristic reader.
- ``params`` keys are validated against an allowlist of dotted paths per
  template; unknown paths are dropped, not trusted. The LLM cannot invent a
  parameter that the engine doesn't understand or smuggle in arbitrary config.
- Values are coerced to numbers; non-numeric values are dropped.
- Any failure (no SDK, no API key, bad JSON, API error) raises, and
  ``extract_rules`` catches it and uses the heuristic. Extraction never blocks
  the lab.

This never fabricates results. It only proposes a *rule set*; whether that rule
set has an edge is decided by the validation ladder, on real data, exactly as
for a hand-authored hypothesis.
"""
from __future__ import annotations

import json
import os
import re
from typing import Callable, Dict

# Allowed dotted parameter paths per template. The LLM may only fill these.
_ALLOWED_PATHS = {
    "trend_continuation": {
        "trend.ema_fast", "trend.ema_slow", "entry.pullback_ema",
        "risk.stop.atr_mult", "risk.stop.atr_period", "risk.target_r",
        "risk.max_trades_per_day",
    },
    "mean_reversion": {
        "meanrev.ma_period", "meanrev.entry_z",
        "risk.stop.atr_mult", "risk.stop.atr_period", "risk.target_r",
        "risk.max_trades_per_day",
    },
    "breakout": {
        "breakout.channel",
        "risk.stop.atr_mult", "risk.stop.atr_period", "risk.target_r",
        "risk.max_trades_per_day",
    },
    "orb": {
        "orb.range_minutes", "orb.ema",
        "risk.stop.atr_mult", "risk.stop.atr_period", "risk.target_r",
        "risk.max_trades_per_day",
    },
}

_TEMPLATES = sorted(_ALLOWED_PATHS)

_SYSTEM = (
    "You are a quantitative research assistant. You read a description of a "
    "trading strategy and translate it into ONE of a fixed set of parameterised "
    "templates. You never invent parameters. You never assess whether the "
    "strategy is profitable — a separate backtesting system decides that. You "
    "only report what the text actually says."
)

_INSTRUCTIONS = """\
Read the strategy description below and map it to exactly one template.

Templates and the ONLY parameters you may set for each (dotted paths):

- trend_continuation  (follow an established trend on a pullback)
    trend.ema_fast, trend.ema_slow, entry.pullback_ema,
    risk.stop.atr_mult, risk.stop.atr_period, risk.target_r, risk.max_trades_per_day
- mean_reversion  (fade an overextended move back toward a mean)
    meanrev.ma_period, meanrev.entry_z,
    risk.stop.atr_mult, risk.stop.atr_period, risk.target_r, risk.max_trades_per_day
- breakout  (enter on a break of an N-period high/low channel)
    breakout.channel,
    risk.stop.atr_mult, risk.stop.atr_period, risk.target_r, risk.max_trades_per_day
- orb  (opening-range breakout: trade a break of the first N minutes' range)
    orb.range_minutes, orb.ema,
    risk.stop.atr_mult, risk.stop.atr_period, risk.target_r, risk.max_trades_per_day

Rules:
- Choose the single template that best matches the described mechanism.
- Only include a parameter if the text gives (or clearly implies) a concrete
  value for it. Omit anything the text does not specify — do NOT guess.
- "1:2 risk reward" / "target twice the risk" -> risk.target_r = 2.
- "1.5 ATR stop" -> risk.stop.atr_mult = 1.5.
- All values must be plain numbers.
- "evidence" must quote or paraphrase the exact phrases you based each choice on.

Return STRICT JSON only, no prose, in this shape:
{"template": "<one of the four>", "params": {"<dotted.path>": <number>, ...}, "evidence": "<why>"}

Strategy description:
---
%s
---
"""

_SCHEMA = {
    "type": "object",
    "properties": {
        "template": {"type": "string", "enum": _TEMPLATES},
        "params": {"type": "object"},
        "evidence": {"type": "string"},
    },
    "required": ["template", "params"],
    "additionalProperties": False,
}


def _coerce_number(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, str):
        m = re.search(r"-?\d+(?:\.\d+)?", v)
        if m:
            f = float(m.group(0))
            return int(f) if f.is_integer() else f
    return None


def sanitise(out: Dict) -> Dict:
    """Validate/clean a raw LLM dict into a safe {template, params, evidence}.

    Raises ValueError if the template is not one we can build — the caller then
    falls back to the heuristic reader rather than trusting junk.
    """
    if not isinstance(out, dict):
        raise ValueError("extractor did not return an object")
    template = out.get("template")
    if template not in _ALLOWED_PATHS:
        raise ValueError(f"unknown template: {template!r}")

    allowed = _ALLOWED_PATHS[template]
    clean: Dict[str, object] = {}
    for path, val in (out.get("params") or {}).items():
        if path not in allowed:
            continue                      # drop anything off the allowlist
        num = _coerce_number(val)
        if num is not None:
            clean[path] = num

    evidence = out.get("evidence") or "llm extractor"
    return {"template": template, "params": clean, "evidence": str(evidence)[:800]}


def _parse_json(raw: str) -> Dict:
    raw = raw.strip()
    # strip ```json fences if the model added them
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.I).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # last resort: grab the first {...} block
        m = re.search(r"\{.*\}", raw, re.S)
        if not m:
            raise
        return json.loads(m.group(0))


def anthropic_extractor(model: str = "claude-opus-5",
                        max_tokens: int = 1024) -> Callable[[str], Dict]:
    """Return an ``extractor(text) -> {template, params, evidence}`` callable
    backed by the Anthropic API.

    Requires the ``anthropic`` package and an ``ANTHROPIC_API_KEY`` in the
    environment. Imports lazily so the portable core never depends on the SDK.
    The returned callable raises on any failure; ``extract_rules`` catches it and
    falls back to the heuristic reader.
    """
    try:
        import anthropic
    except ImportError as e:
        raise RuntimeError(
            "anthropic package not installed — run `pip install anthropic` and "
            "set ANTHROPIC_API_KEY to use the LLM extractor.") from e

    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY is not set — the LLM extractor "
                           "needs it. Falling back to the heuristic reader.")

    client = anthropic.Anthropic()

    def extractor(text: str) -> Dict:
        text = (text or "").strip()
        if not text:
            raise ValueError("empty text")
        msg = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=_SYSTEM,
            messages=[{"role": "user",
                       "content": _INSTRUCTIONS % text[:12000]}],
        )
        raw = "".join(getattr(b, "text", "") for b in msg.content).strip()
        return sanitise(_parse_json(raw))

    return extractor
