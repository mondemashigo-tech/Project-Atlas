"""Composable feature engine — the vocabulary Atlas invents strategies from.

Two kinds of feature, both producing a named numeric ``pd.Series`` aligned to the
entry-timeframe frame:

1. **Built-in indicators** — vetted, look-ahead-safe functions (ema, sma, rsi,
   atr, bollinger, zscore, slope, ...). Referenced by ``kind``.

2. **Invented indicators (formula)** — Atlas writes its OWN indicators as an
   expression tree over a whitelist of primitives, e.g.
   ``(close - sma(close,20)) / atr(14)``. This is how the lab creates genuinely
   new features without anyone hand-coding them.

Safety: invented indicators are DATA, not code. ``eval_formula`` walks a JSON
tree and dispatches only to a fixed table of primitive functions — there is no
``eval``/``exec``, no attribute access, no imports. An LLM cannot smuggle
arbitrary Python through a formula; the worst it can do is write a useless
indicator, which the validation ladder then discards. Every primitive is
vectorised and only ever reads the current-or-earlier bar (rolling/ewm/shift with
non-negative periods), so features cannot introduce look-ahead.
"""
from __future__ import annotations

from typing import Dict, List
import numpy as np
import pandas as pd

from .indicators import ema, atr, rsi, swing_low, swing_high

_BASE_COLS = ("open", "high", "low", "close", "volume")
_MAX_DEPTH = 32


# --------------------------------------------------------------------------- #
# Built-in indicators: fn(df, feats, **params) -> Series
# `feats` is the frame of already-built features (so an indicator may build on
# an earlier one by naming it as its `source`).
# --------------------------------------------------------------------------- #
def _src(df: pd.DataFrame, feats: pd.DataFrame, name) -> pd.Series:
    """Resolve a source: a base OHLC column, an already-built feature, or a
    constant number."""
    if isinstance(name, (int, float)):
        return pd.Series(float(name), index=df.index)
    if name in feats.columns:
        return feats[name]
    if name in df.columns:
        return df[name]
    raise ValueError(f"unknown source column/feature: {name!r}")


def _f_ema(df, feats, source="close", period=20):
    return ema(_src(df, feats, source), int(period))


def _f_sma(df, feats, source="close", period=20):
    return _src(df, feats, source).rolling(int(period)).mean()


def _f_rsi(df, feats, source="close", period=14):
    return rsi(_src(df, feats, source), int(period))


def _f_atr(df, feats, period=14):
    return atr(df, int(period))


def _f_rstd(df, feats, source="close", period=20):
    return _src(df, feats, source).rolling(int(period)).std()


def _f_zscore(df, feats, source="close", period=20):
    s = _src(df, feats, source)
    m = s.rolling(int(period)).mean()
    sd = s.rolling(int(period)).std()
    return (s - m) / sd


def _f_roc(df, feats, source="close", period=10):
    return _src(df, feats, source).pct_change(int(period))


def _f_slope(df, feats, source="close", period=20):
    """Least-squares slope of the last `period` values, per bar (units/bar)."""
    s = _src(df, feats, source)
    p = int(period)
    x = np.arange(p)
    xm = x.mean()
    denom = ((x - xm) ** 2).sum()

    def _slp(win):
        return ((x - xm) * (win - win.mean())).sum() / denom if denom else np.nan

    return s.rolling(p).apply(_slp, raw=True)


def _f_bb_upper(df, feats, source="close", period=20, mult=2.0):
    s = _src(df, feats, source)
    return s.rolling(int(period)).mean() + float(mult) * s.rolling(int(period)).std()


def _f_bb_lower(df, feats, source="close", period=20, mult=2.0):
    s = _src(df, feats, source)
    return s.rolling(int(period)).mean() - float(mult) * s.rolling(int(period)).std()


def _f_swing_low(df, feats, lookback=20):
    return swing_low(df, int(lookback))


def _f_swing_high(df, feats, lookback=20):
    return swing_high(df, int(lookback))


def _f_donchian_high(df, feats, period=20):
    return df["high"].shift(1).rolling(int(period)).max()


def _f_donchian_low(df, feats, period=20):
    return df["low"].shift(1).rolling(int(period)).min()


BUILTINS = {
    "ema": _f_ema, "sma": _f_sma, "rsi": _f_rsi, "atr": _f_atr,
    "rstd": _f_rstd, "zscore": _f_zscore, "roc": _f_roc, "slope": _f_slope,
    "bb_upper": _f_bb_upper, "bb_lower": _f_bb_lower,
    "swing_low": _f_swing_low, "swing_high": _f_swing_high,
    "donchian_high": _f_donchian_high, "donchian_low": _f_donchian_low,
}


# --------------------------------------------------------------------------- #
# Formula primitives for INVENTED indicators. Each takes evaluated Series/scalars.
# Only names in this table can ever run — no eval/exec, no attribute access.
# --------------------------------------------------------------------------- #
def _p_add(a, b): return a + b
def _p_sub(a, b): return a - b
def _p_mul(a, b): return a * b
def _p_div(a, b): return a / b
def _p_neg(a): return -a
def _p_abs(a): return a.abs() if isinstance(a, pd.Series) else abs(a)
def _p_min(a, b): return np.minimum(a, b)
def _p_max(a, b): return np.maximum(a, b)


def _p_clip(a, lo=None, hi=None):
    return a.clip(lower=lo, upper=hi)


def _as_series(x, like):
    return x if isinstance(x, pd.Series) else pd.Series(float(x), index=like.index)


def _p_sma(a, period=20): return _as_series(a, a).rolling(int(period)).mean()
def _p_rstd(a, period=20): return _as_series(a, a).rolling(int(period)).std()
def _p_rmin(a, period=20): return _as_series(a, a).rolling(int(period)).min()
def _p_rmax(a, period=20): return _as_series(a, a).rolling(int(period)).max()
def _p_rsum(a, period=20): return _as_series(a, a).rolling(int(period)).sum()
def _p_ema(a, span=20): return _as_series(a, a).ewm(span=int(span), adjust=False).mean()
def _p_diff(a, period=1): return _as_series(a, a).diff(int(period))
def _p_shift(a, period=1): return _as_series(a, a).shift(max(0, int(period)))
def _p_pct_change(a, period=1): return _as_series(a, a).pct_change(int(period))


def _p_zscore(a, period=20):
    s = _as_series(a, a)
    return (s - s.rolling(int(period)).mean()) / s.rolling(int(period)).std()


PRIMITIVES = {
    "add": _p_add, "sub": _p_sub, "mul": _p_mul, "div": _p_div,
    "neg": _p_neg, "abs": _p_abs, "min": _p_min, "max": _p_max, "clip": _p_clip,
    "sma": _p_sma, "rstd": _p_rstd, "rmin": _p_rmin, "rmax": _p_rmax,
    "rsum": _p_rsum, "ema": _p_ema, "diff": _p_diff, "shift": _p_shift,
    "pct_change": _p_pct_change, "zscore": _p_zscore,
}


def eval_formula(node, df: pd.DataFrame, feats: pd.DataFrame, depth: int = 0):
    """Evaluate an invented-indicator expression tree.

    A node is one of:
    - a number      -> constant
    - a string      -> a base column ('close') or an already-built feature name
    - {"fn": name, "args": [child, ...], **kwargs}  -> a whitelisted primitive

    Returns a Series (or scalar for pure-constant leaves). Raises ValueError on
    anything not on the whitelist, unknown source, or excessive depth.
    """
    if depth > _MAX_DEPTH:
        raise ValueError("formula too deeply nested")
    if isinstance(node, bool):
        raise ValueError("booleans are not valid in an indicator formula")
    if isinstance(node, (int, float)):
        return float(node)
    if isinstance(node, str):
        return _src(df, feats, node)
    if isinstance(node, dict) and "fn" in node:
        fn = node["fn"]
        if fn not in PRIMITIVES:
            raise ValueError(f"unknown formula primitive: {fn!r}")
        args = [eval_formula(a, df, feats, depth + 1) for a in node.get("args", [])]
        kwargs = {k: v for k, v in node.items() if k not in ("fn", "args")}
        return PRIMITIVES[fn](*args, **kwargs)
    raise ValueError(f"invalid formula node: {node!r}")


def build_feature(spec: dict, df: pd.DataFrame, feats: pd.DataFrame) -> pd.Series:
    """Build one feature Series from its spec, given features already built."""
    kind = spec.get("kind")
    if kind == "formula":
        if "expr" not in spec:
            raise ValueError(f"formula feature {spec.get('name')!r} needs 'expr'")
        out = eval_formula(spec["expr"], df, feats)
        return _as_series(out, df)
    if kind in BUILTINS:
        params = {k: v for k, v in spec.items() if k not in ("name", "kind")}
        return BUILTINS[kind](df, feats, **params)
    raise ValueError(f"unknown feature kind: {kind!r} "
                     f"(known: {sorted(BUILTINS)} or 'formula')")


def build_features(df: pd.DataFrame, specs: List[dict]) -> pd.DataFrame:
    """Build all named features in order. Later features may reference earlier
    ones (and any base OHLC column) by name. Returns a frame indexed like `df`."""
    feats = pd.DataFrame(index=df.index)
    for spec in specs or []:
        name = spec.get("name")
        if not name:
            raise ValueError(f"feature spec missing 'name': {spec!r}")
        if name in _BASE_COLS:
            raise ValueError(f"feature name {name!r} shadows a base column")
        feats[name] = build_feature(spec, df, feats)
    return feats
