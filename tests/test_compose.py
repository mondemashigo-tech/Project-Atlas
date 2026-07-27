"""Composable engine: feature toolbox, invented formula indicators, rule grammar,
and an end-to-end composed strategy that trades on synthetic data.

No network, no API — pure engine validation.
"""
import numpy as np
import pandas as pd
import pytest

from atlas.research.fx.features import (build_features, eval_formula, BUILTINS,
                                        PRIMITIVES)
from atlas.research.fx.rules import evaluate, referenced_names
from atlas.research.fx.strategies.base import Strategy
import atlas.research.fx.strategies  # noqa: registers templates
from atlas.research.fx import backtester


def _synth(n=600, start=1.10, seed=1):
    """A gently trending, wiggly OHLC frame in UTC — enough for indicators."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2021-01-01", periods=n, freq="5min", tz="UTC")
    steps = rng.normal(0.0, 0.0004, n) + 0.00012      # slight upward drift
    close = start + np.cumsum(steps)
    high = close + np.abs(rng.normal(0, 0.0003, n))
    low = close - np.abs(rng.normal(0, 0.0003, n))
    openp = close - steps
    return pd.DataFrame({"open": openp, "high": high, "low": low, "close": close},
                        index=idx)


# --- feature toolbox --------------------------------------------------------
def test_builtin_features_build():
    df = _synth()
    feats = build_features(df, [
        {"name": "ema20", "kind": "ema", "source": "close", "period": 20},
        {"name": "rsi14", "kind": "rsi", "period": 14},
        {"name": "atr14", "kind": "atr", "period": 14},
        {"name": "z20", "kind": "zscore", "source": "close", "period": 20},
    ])
    assert list(feats.columns) == ["ema20", "rsi14", "atr14", "z20"]
    assert feats["ema20"].notna().sum() > 500
    # rsi bounded 0..100 where defined
    r = feats["rsi14"].dropna()
    assert r.min() >= 0 and r.max() <= 100


def test_invented_formula_indicator():
    """Atlas writes its OWN indicator: stretch = (close - sma(close,20)) / atr14."""
    df = _synth()
    feats = build_features(df, [
        {"name": "atr14", "kind": "atr", "period": 14},
        {"name": "stretch", "kind": "formula",
         "expr": {"fn": "div",
                  "args": [{"fn": "sub", "args": ["close",
                            {"fn": "sma", "args": ["close"], "period": 20}]},
                           "atr14"]}},
    ])
    # compute the same thing by hand and compare where both defined
    sma20 = df["close"].rolling(20).mean()
    atr14 = feats["atr14"]
    expected = (df["close"] - sma20) / atr14
    got = feats["stretch"]
    mask = expected.notna() & got.notna()
    assert mask.sum() > 400
    assert np.allclose(got[mask].to_numpy(), expected[mask].to_numpy())


def test_formula_rejects_unknown_primitive():
    df = _synth(50)
    with pytest.raises(ValueError):
        eval_formula({"fn": "os_system", "args": ["close"]}, df,
                     pd.DataFrame(index=df.index))


def test_formula_rejects_unknown_source():
    df = _synth(50)
    with pytest.raises(ValueError):
        eval_formula("nonexistent_col", df, pd.DataFrame(index=df.index))


def test_feature_name_cannot_shadow_base_column():
    df = _synth(50)
    with pytest.raises(ValueError):
        build_features(df, [{"name": "close", "kind": "ema", "period": 5}])


# --- rule grammar -----------------------------------------------------------
def test_rule_and_or_not_and_cross():
    df = _synth()
    feats = build_features(df, [
        {"name": "ema_f", "kind": "ema", "source": "close", "period": 10},
        {"name": "ema_s", "kind": "ema", "source": "close", "period": 40},
    ])
    m_and = evaluate({"all": [{"lhs": "close", "cmp": ">", "rhs": "ema_f"},
                              {"lhs": "ema_f", "cmp": ">", "rhs": "ema_s"}]},
                     df, feats)
    m_cross = evaluate({"lhs": "ema_f", "cmp": "cross_above", "rhs": "ema_s"},
                       df, feats)
    assert m_and.dtype == bool and m_cross.dtype == bool
    # a crossover is a strict subset of "fast above slow"
    above = evaluate({"lhs": "ema_f", "cmp": ">", "rhs": "ema_s"}, df, feats)
    assert (m_cross & ~above).sum() == 0
    assert m_cross.sum() >= 1


def test_rule_referenced_names():
    rule = {"all": [{"lhs": "close", "cmp": ">", "rhs": "ema_f"},
                    {"not": {"lhs": "rsi14", "cmp": ">", "rhs": 70}}]}
    assert referenced_names(rule) == {"close", "ema_f", "rsi14"}


def test_rule_rejects_unknown_operator_and_ref():
    df = _synth(50)
    feats = pd.DataFrame(index=df.index)
    with pytest.raises(ValueError):
        evaluate({"lhs": "close", "cmp": "approx", "rhs": 1}, df, feats)
    with pytest.raises(ValueError):
        evaluate({"lhs": "ghost", "cmp": ">", "rhs": 1}, df, feats)


# --- composed strategy end-to-end ------------------------------------------
def test_composed_strategy_builds_and_trades():
    df = _synth(1200, seed=7)
    cfg = {
        "name": "compose_test", "template": "composed", "markets": ["GBPUSD"],
        "timeframes": {"entry": "M5"},
        "features": [
            {"name": "ema_f", "kind": "ema", "source": "close", "period": 10},
            {"name": "ema_s", "kind": "ema", "source": "close", "period": 50},
            {"name": "atr14", "kind": "atr", "period": 14},
            {"name": "stretch", "kind": "formula",
             "expr": {"fn": "div", "args": [{"fn": "sub", "args": ["close", "ema_f"]},
                                            "atr14"]}},
        ],
        "entry_long": {"all": [{"lhs": "ema_f", "cmp": ">", "rhs": "ema_s"},
                               {"lhs": "close", "cmp": "cross_above", "rhs": "ema_f"}]},
        "entry_short": {"all": [{"lhs": "ema_f", "cmp": "<", "rhs": "ema_s"},
                                {"lhs": "close", "cmp": "cross_below", "rhs": "ema_f"}]},
        "risk": {"stop": {"kind": "atr", "atr_period": 14, "atr_mult": 1.5},
                 "target_r": 2.0, "max_trades_per_day": 5},
    }
    strat = Strategy.create(cfg)
    assert strat is not None
    trades = backtester.run("GBPUSD", df, strat, spread_pips=1.0,
                            commission_r=0.02, max_trades_per_day=5)
    # it should actually take trades, and every trade must be well-formed
    assert len(trades) > 0
    for t in trades:
        assert t.direction in ("BUY", "SELL")
        assert t.stop != t.entry and t.target != t.entry


def test_composed_requires_an_entry_rule():
    df = _synth(50)
    strat = Strategy.create({"name": "x", "template": "composed",
                             "markets": ["GBPUSD"], "timeframes": {"entry": "M5"},
                             "features": []})
    with pytest.raises(ValueError):
        strat.prepare(df, symbol="GBPUSD")


def test_composed_preregisters_distinctly():
    """Two composed strategies with different rules must hash differently, and the
    same rules must hash identically (pre-registration integrity)."""
    from atlas.schemas import Hypothesis
    base = {"name": "a", "template": "composed", "markets": ["GBPUSD"],
            "version": "1.0", "timeframes": {"entry": "M5"},
            "criteria": {"success": {}, "failure": {}},
            "data": {"in_sample": ["2020-01-01", "2022-12-31"],
                     "out_sample": ["2023-01-01", "2025-12-31"]},
            "features": [{"name": "rsi14", "kind": "rsi", "period": 14}],
            "entry_long": {"lhs": "rsi14", "cmp": "<", "rhs": 30},
            "risk": {"stop": {"kind": "atr"}, "target_r": 2.0}}
    other = dict(base)
    other["entry_long"] = {"lhs": "rsi14", "cmp": "<", "rhs": 25}   # different rule
    h1 = Hypothesis.from_fx_config(base).freeze()
    h1b = Hypothesis.from_fx_config(base).freeze()
    h2 = Hypothesis.from_fx_config(other).freeze()
    assert h1.preregistration_hash == h1b.preregistration_hash
    assert h1.preregistration_hash != h2.preregistration_hash
