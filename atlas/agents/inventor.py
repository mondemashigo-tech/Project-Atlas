"""The Inventor — Atlas designs its OWN strategies.

Where the Scientist only turns knobs on a fixed template, the Inventor composes
new strategies in the composable grammar: it picks features (including invented
formula indicators) and wires them into entry rules. The output is an ordinary
composed-template hypothesis, so it is pre-registered and run through the exact
same validation ladder as everything else — the p-hacking guard is not optional.

Two paths (same as the rest of the lab):
- **LLM generator** (best): an injected/So-configured callable that writes brand
  new feature+rule combinations from a theme. Wire it to Claude for real
  creativity.
- **Deterministic library** (always available): a set of hand-seeded *composed*
  archetypes that genuinely mix indicators (trend+RSI, Bollinger+zscore,
  breakout+volatility, an invented "stretch" reversion, slope momentum). Keeps
  the lab inventing even with no API key.

Safety: every candidate — LLM-written or seeded — is validated by *dry-running it
through the real engine* on a tiny synthetic frame (``_validate``). The engine's
own whitelists (feature kinds, formula primitives, rule operators, defined
references) are the gate, so a malformed or unsafe machine-written strategy is
rejected before it can be registered. No code is ever executed — strategies are
data.
"""
from __future__ import annotations

import copy
import json
import os
import re
from typing import Callable, Dict, List, Optional

import numpy as np
import pandas as pd

from ..research.fx.features import build_features, BUILTINS, PRIMITIVES
from ..research.fx.rules import evaluate

_DEFAULT_SPLIT = {"in_sample": ["2020-01-01", "2022-12-31"],
                  "out_sample": ["2023-01-01", "2025-12-31"]}
_DEFAULT_CRIT = {"success": {"profit_factor": 1.3, "min_trades": 150,
                             "expectancy": "positive"},
                 "failure": {"profit_factor": 1.0, "expectancy": "negative"}}
_DEFAULT_COSTS = {"spread_pips": 1.0, "commission_r": 0.03}
_DEFAULT_RISK = {"stop": {"kind": "atr", "atr_period": 14, "atr_mult": 1.5},
                 "target_r": 2.0, "max_trades_per_day": 3}

_ALLOWED_FEATURE_KINDS = set(BUILTINS) | {"formula"}


# --------------------------------------------------------------------------- #
# Deterministic composed archetypes — each genuinely mixes multiple concepts.
# --------------------------------------------------------------------------- #
def _arch_trend_rsi(fast=10, slow=50, rsi_p=14, buy_below=40, sell_above=60):
    return {
        "features": [
            {"name": "ema_f", "kind": "ema", "source": "close", "period": fast},
            {"name": "ema_s", "kind": "ema", "source": "close", "period": slow},
            {"name": "rsi", "kind": "rsi", "period": rsi_p},
            {"name": "atr14", "kind": "atr", "period": 14},
        ],
        "entry_long": {"all": [{"lhs": "ema_f", "cmp": ">", "rhs": "ema_s"},
                               {"lhs": "rsi", "cmp": "cross_above", "rhs": buy_below}]},
        "entry_short": {"all": [{"lhs": "ema_f", "cmp": "<", "rhs": "ema_s"},
                                {"lhs": "rsi", "cmp": "cross_below", "rhs": sell_above}]},
        "note": "trend filter + RSI pullback trigger",
    }


def _arch_bollinger_z(period=20, mult=2.0, z=2.0):
    return {
        "features": [
            {"name": "bb_up", "kind": "bb_upper", "source": "close",
             "period": period, "mult": mult},
            {"name": "bb_lo", "kind": "bb_lower", "source": "close",
             "period": period, "mult": mult},
            {"name": "z", "kind": "zscore", "source": "close", "period": period},
            {"name": "atr14", "kind": "atr", "period": 14},
        ],
        "entry_long": {"all": [{"lhs": "close", "cmp": "<", "rhs": "bb_lo"},
                               {"lhs": "z", "cmp": "<", "rhs": -abs(z)}]},
        "entry_short": {"all": [{"lhs": "close", "cmp": ">", "rhs": "bb_up"},
                                {"lhs": "z", "cmp": ">", "rhs": abs(z)}]},
        "note": "Bollinger band break + z-score confirmation (mean reversion)",
    }


def _arch_breakout_vol(channel=20, atr_p=14):
    return {
        "features": [
            {"name": "dc_hi", "kind": "donchian_high", "period": channel},
            {"name": "dc_lo", "kind": "donchian_low", "period": channel},
            {"name": "atr14", "kind": "atr", "period": atr_p},
            # volatility expansion: atr above its own recent average
            {"name": "atr_ma", "kind": "formula",
             "expr": {"fn": "sma", "args": ["atr14"], "period": 50}},
        ],
        "entry_long": {"all": [{"lhs": "close", "cmp": "cross_above", "rhs": "dc_hi"},
                               {"lhs": "atr14", "cmp": ">", "rhs": "atr_ma"}]},
        "entry_short": {"all": [{"lhs": "close", "cmp": "cross_below", "rhs": "dc_lo"},
                                {"lhs": "atr14", "cmp": ">", "rhs": "atr_ma"}]},
        "note": "channel breakout gated by volatility expansion",
    }


def _arch_stretch_reversion(ema_p=20, thresh=2.0):
    # Invented indicator: stretch = (close - ema) / atr  — normalised distance.
    return {
        "features": [
            {"name": "ema_p", "kind": "ema", "source": "close", "period": ema_p},
            {"name": "atr14", "kind": "atr", "period": 14},
            {"name": "stretch", "kind": "formula",
             "expr": {"fn": "div",
                      "args": [{"fn": "sub", "args": ["close", "ema_p"]}, "atr14"]}},
        ],
        "entry_long": {"lhs": "stretch", "cmp": "<", "rhs": -abs(thresh)},
        "entry_short": {"lhs": "stretch", "cmp": ">", "rhs": abs(thresh)},
        "note": "invented 'stretch' indicator = (close-ema)/atr; fade extremes",
    }


def _arch_slope_momentum(slope_p=20, rsi_p=14):
    return {
        "features": [
            {"name": "slope", "kind": "slope", "source": "close", "period": slope_p},
            {"name": "rsi", "kind": "rsi", "period": rsi_p},
            {"name": "atr14", "kind": "atr", "period": 14},
        ],
        "entry_long": {"all": [{"lhs": "slope", "cmp": ">", "rhs": 0},
                               {"lhs": "rsi", "cmp": "cross_above", "rhs": 50}]},
        "entry_short": {"all": [{"lhs": "slope", "cmp": "<", "rhs": 0},
                                {"lhs": "rsi", "cmp": "cross_below", "rhs": 50}]},
        "note": "regression-slope momentum + RSI midline trigger",
    }


_ARCHETYPES = [_arch_trend_rsi, _arch_bollinger_z, _arch_breakout_vol,
               _arch_stretch_reversion, _arch_slope_momentum]


def heuristic_invent(theme: str = "", n: int = 3) -> List[Dict]:
    """Return up to n seeded composed strategy bodies (features + entry rules).
    Theme is used only to bias ordering; the library is fixed and safe."""
    low = (theme or "").lower()
    order = list(_ARCHETYPES)
    # light thematic bias
    def score(fn):
        note = fn().get("note", "")
        return sum(w in low and w in note.lower() for w in
                   ("trend", "rsi", "breakout", "volatility", "revert",
                    "reversion", "bollinger", "momentum", "slope"))
    order.sort(key=score, reverse=True)
    return [fn() for fn in order[:max(1, n)]]


# --------------------------------------------------------------------------- #
# Validation — dry-run through the real engine on a tiny synthetic frame.
# --------------------------------------------------------------------------- #
def _dummy_frame(n: int = 120) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    close = 1.1 + np.cumsum(rng.normal(0, 0.0004, n))
    high = close + np.abs(rng.normal(0, 0.0003, n))
    low = close - np.abs(rng.normal(0, 0.0003, n))
    idx = pd.date_range("2021-01-01", periods=n, freq="5min", tz="UTC")
    return pd.DataFrame({"open": close, "high": high, "low": low, "close": close},
                        index=idx)


def _validate(body: Dict) -> None:
    """Raise if the composed body isn't safe/buildable. Structural checks first,
    then a real dry-run so the engine's whitelists are the final gate."""
    feats = body.get("features")
    if not isinstance(feats, list):
        raise ValueError("features must be a list")
    for f in feats:
        if f.get("kind") not in _ALLOWED_FEATURE_KINDS:
            raise ValueError(f"feature kind not allowed: {f.get('kind')!r}")
    if "entry_long" not in body and "entry_short" not in body:
        raise ValueError("need entry_long and/or entry_short")
    df = _dummy_frame()
    built = build_features(df, feats)               # raises on bad kind/primitive/ref
    for key in ("entry_long", "entry_short"):
        if key in body:
            evaluate(body[key], df, built)          # raises on bad op/ref


def build_invented(body: Dict, name: str, markets: List[str],
                   data_split: Dict = None) -> Dict:
    """Wrap a validated composed body into a full, testable hypothesis config."""
    cfg = {
        "name": name, "version": "0.1", "template": "composed",
        "markets": list(markets),
        "timeframes": {"entry": "M5"},
        "features": copy.deepcopy(body["features"]),
        "costs": dict(_DEFAULT_COSTS),
        "risk": copy.deepcopy(body.get("risk", _DEFAULT_RISK)),
        "criteria": copy.deepcopy(_DEFAULT_CRIT),
        "data": copy.deepcopy(data_split or _DEFAULT_SPLIT),
        "source": "inventor",
    }
    for key in ("entry_long", "entry_short", "session", "weekdays"):
        if key in body:
            cfg[key] = copy.deepcopy(body[key])
    if body.get("note"):
        cfg["note"] = body["note"]
    return cfg


class Inventor:
    name = "Inventor"
    nature = "hybrid"

    def __init__(self, generator: Optional[Callable[[str, int], List[Dict]]] = None):
        # generator(theme, n) -> [composed body dict]; falls back to heuristic.
        self.generator = generator

    def invent(self, theme: str = "", markets: List[str] = None, n: int = 3,
               data_split: Dict = None, name_prefix: str = None) -> List[Dict]:
        """Return up to n full, validated composed hypothesis configs. Invalid
        candidates (from either path) are dropped, not raised."""
        markets = markets or ["GBPUSD", "USDJPY"]
        bodies: List[Dict] = []
        if self.generator:
            try:
                bodies = list(self.generator(theme, n) or [])
            except Exception:
                bodies = []
        if not bodies:
            bodies = heuristic_invent(theme, n)

        prefix = name_prefix or ("invented_" + re.sub(r"[^a-z0-9]+", "_",
                                                       (theme or "mix").lower()).strip("_"))
        out = []
        for k, body in enumerate(bodies[:n]):
            try:
                _validate(body)
            except Exception:
                continue
            name = f"{prefix}_{k+1}"
            out.append(build_invented(body, name, markets, data_split))
        return out


# --------------------------------------------------------------------------- #
# LLM generator (optional) — Claude writes new feature+rule combinations.
# --------------------------------------------------------------------------- #
_SYSTEM = (
    "You are a quantitative strategy designer. You invent trading strategies by "
    "composing indicators into entry rules. You output ONLY strategies in the "
    "provided JSON grammar. You never claim a strategy is profitable — a "
    "backtester decides that. You never write code; you only compose from the "
    "allowed feature kinds and formula primitives."
)


def _grammar_doc() -> str:
    return (
        "Feature kinds (each -> a named numeric series):\n"
        f"  {', '.join(sorted(BUILTINS))}\n"
        "Or kind='formula' with an 'expr' tree over primitives:\n"
        f"  {', '.join(sorted(PRIMITIVES))}\n"
        "  expr node = number | \"close\"/\"high\"/\"low\"/\"open\" | earlier feature "
        "name | {\"fn\": <primitive>, \"args\": [node,...], <kwargs like period/span>}\n"
        "Rules -> boolean:\n"
        "  {\"lhs\": <feat/col/number>, \"cmp\": <\"<\",\"<=\",\">\",\">=\",\"==\","
        "\"!=\",\"cross_above\",\"cross_below\">, \"rhs\": <feat/col/number>}\n"
        "  {\"all\":[rule,...]} | {\"any\":[rule,...]} | {\"not\": rule}\n"
    )


_PROMPT = """\
Invent %d DISTINCT forex intraday strategies on the theme: %s

Each strategy MIXES at least two different ideas (e.g. a trend filter AND a
momentum trigger, or a volatility feature AND a mean-reversion band). Use the
grammar below. You MAY invent a new indicator with kind='formula'.

%s

Return STRICT JSON only — an array of objects, each:
{"features": [ {feature spec}, ... ],
 "entry_long": <rule>, "entry_short": <rule>,
 "risk": {"stop": {"kind":"atr","atr_period":14,"atr_mult":1.5}, "target_r": 2.0,
          "max_trades_per_day": 3},
 "note": "one line on what it mixes"}
Rules may only reference features you defined (by name) or base columns
close/open/high/low. Keep each strategy simple (2-4 features).
"""


def anthropic_generator(model: str = "claude-opus-5",
                        max_tokens: int = 4096) -> Callable[[str, int], List[Dict]]:
    """Return a ``generator(theme, n) -> [composed body]`` backed by Claude.
    Requires the anthropic package and ANTHROPIC_API_KEY. Raises on setup failure
    so the Inventor falls back to the seeded library."""
    try:
        import anthropic
    except ImportError as e:
        raise RuntimeError("anthropic not installed — `pip install anthropic`.") from e
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY not set.")
    client = anthropic.Anthropic()

    def generator(theme: str, n: int = 3) -> List[Dict]:
        msg = client.messages.create(
            model=model, max_tokens=max_tokens, system=_SYSTEM,
            messages=[{"role": "user",
                       "content": _PROMPT % (n, theme or "any edge", _grammar_doc())}])
        raw = "".join(getattr(b, "text", "") for b in msg.content).strip()
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.I).strip()
        m = re.search(r"\[.*\]", raw, re.S)
        data = json.loads(m.group(0) if m else raw)
        return data if isinstance(data, list) else []

    return generator
