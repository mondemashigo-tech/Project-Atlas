"""Inventor: seeded archetypes, the safety validation gate, a stubbed LLM
generator, and that invented configs are real, buildable, pre-registrable
hypotheses. No API calls."""
import pytest

from atlas.agents.inventor import (Inventor, heuristic_invent, build_invented,
                                    _validate)
from atlas.research.fx.strategies.base import Strategy
import atlas.research.fx.strategies  # noqa: registers templates
from atlas.schemas import Hypothesis


def test_heuristic_invents_composed_bodies():
    bodies = heuristic_invent("trend momentum", n=3)
    assert 1 <= len(bodies) <= 3
    for b in bodies:
        assert "features" in b and ("entry_long" in b or "entry_short" in b)


def test_every_archetype_is_valid_and_buildable():
    bodies = heuristic_invent("", n=99)          # all of them
    assert len(bodies) >= 5
    for b in bodies:
        _validate(b)                              # must not raise
        cfg = build_invented(b, "arch_test", ["GBPUSD"])
        assert Strategy.create(cfg) is not None


def test_validate_rejects_bad_feature_kind():
    with pytest.raises(ValueError):
        _validate({"features": [{"name": "x", "kind": "os_system"}],
                   "entry_long": {"lhs": "x", "cmp": ">", "rhs": 0}})


def test_validate_rejects_rule_referencing_undefined_feature():
    with pytest.raises(ValueError):
        _validate({"features": [{"name": "rsi", "kind": "rsi", "period": 14}],
                   "entry_long": {"lhs": "ghost", "cmp": ">", "rhs": 0}})


def test_validate_rejects_malicious_formula_primitive():
    with pytest.raises(ValueError):
        _validate({"features": [{"name": "evil", "kind": "formula",
                    "expr": {"fn": "__import__", "args": ["os"]}}],
                   "entry_long": {"lhs": "evil", "cmp": ">", "rhs": 0}})


def test_inventor_falls_back_to_heuristic_on_bad_generator():
    # generator raises -> Inventor uses the seeded library, still returns configs
    inv = Inventor(generator=lambda theme, n: (_ for _ in ()).throw(RuntimeError()))
    cfgs = inv.invent("anything", markets=["GBPUSD"], n=2)
    assert len(cfgs) == 2
    for cfg in cfgs:
        assert cfg["template"] == "composed"
        assert Strategy.create(cfg) is not None


def test_inventor_uses_stub_generator_and_drops_invalid():
    good = {"features": [{"name": "rsi", "kind": "rsi", "period": 14},
                         {"name": "atr14", "kind": "atr", "period": 14}],
            "entry_long": {"lhs": "rsi", "cmp": "<", "rhs": 30},
            "note": "rsi oversold"}
    bad = {"features": [{"name": "x", "kind": "totally_fake"}],
           "entry_long": {"lhs": "x", "cmp": ">", "rhs": 0}}
    inv = Inventor(generator=lambda theme, n: [good, bad])
    cfgs = inv.invent("rsi", markets=["GBPUSD"], n=5)
    assert len(cfgs) == 1                          # the bad one was dropped
    assert cfgs[0]["entry_long"]["rhs"] == 30
    assert Strategy.create(cfgs[0]) is not None


def test_invented_config_preregisters():
    cfgs = Inventor().invent("mix", markets=["GBPUSD"], n=1)
    h = Hypothesis.from_fx_config(cfgs[0]).freeze()
    assert h.preregistration_hash and not h.validate()
