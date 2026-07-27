"""Composable rule grammar — how Atlas expresses an entry/exit condition as a
combination of features, not hand-coded Python.

A rule is a JSON tree evaluated to a boolean ``pd.Series`` (one flag per bar):

- Comparison:  {"lhs": <ref>, "cmp": "<", "rhs": <ref-or-number>}
    cmp in: "<", "<=", ">", ">=", "==", "!=", "cross_above", "cross_below"
    A ref is a feature name, a base column ("close"), or a number.
- Boolean:     {"all": [rule, ...]}   (AND)
               {"any": [rule, ...]}   (OR)
               {"not": rule}
- Constant:    true / false           (rarely needed; handy as a default)

`cross_above` at bar i means lhs was <= rhs at i-1 and > rhs at i (a fresh
crossover), which is what most "signal line" strategies actually mean. All
comparisons read only the current and previous bar, so no look-ahead.

Safety mirrors the feature engine: a fixed dispatch table, no eval/exec, bounded
recursion. Unknown operators or references raise, so a malformed machine-written
rule is rejected rather than silently doing something surprising.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

_MAX_DEPTH = 32
_CMP = {"<", "<=", ">", ">=", "==", "!=", "cross_above", "cross_below"}


def _ref(name, df: pd.DataFrame, feats: pd.DataFrame) -> pd.Series:
    if isinstance(name, bool):
        raise ValueError("boolean is not a valid comparison operand")
    if isinstance(name, (int, float)):
        return pd.Series(float(name), index=df.index)
    if isinstance(name, str):
        if name in feats.columns:
            return feats[name]
        if name in df.columns:
            return df[name]
        raise ValueError(f"unknown reference in rule: {name!r}")
    raise ValueError(f"invalid rule operand: {name!r}")


def _compare(lhs: pd.Series, cmp: str, rhs: pd.Series) -> pd.Series:
    if cmp == "<":
        out = lhs < rhs
    elif cmp == "<=":
        out = lhs <= rhs
    elif cmp == ">":
        out = lhs > rhs
    elif cmp == ">=":
        out = lhs >= rhs
    elif cmp == "==":
        out = lhs == rhs
    elif cmp == "!=":
        out = lhs != rhs
    elif cmp == "cross_above":
        out = (lhs.shift(1) <= rhs.shift(1)) & (lhs > rhs)
    elif cmp == "cross_below":
        out = (lhs.shift(1) >= rhs.shift(1)) & (lhs < rhs)
    else:
        raise ValueError(f"unknown comparison operator: {cmp!r}")
    # NaN in either operand -> not a valid signal on that bar.
    return out.fillna(False).astype(bool)


def evaluate(rule, df: pd.DataFrame, feats: pd.DataFrame, depth: int = 0) -> pd.Series:
    """Evaluate a rule tree to a boolean Series aligned to `df`."""
    if depth > _MAX_DEPTH:
        raise ValueError("rule too deeply nested")
    if isinstance(rule, bool):
        return pd.Series(rule, index=df.index)
    if not isinstance(rule, dict):
        raise ValueError(f"invalid rule node: {rule!r}")

    if "all" in rule:
        clauses = rule["all"]
        if not isinstance(clauses, list) or not clauses:
            raise ValueError("'all' needs a non-empty list")
        out = pd.Series(True, index=df.index)
        for c in clauses:
            out &= evaluate(c, df, feats, depth + 1)
        return out
    if "any" in rule:
        clauses = rule["any"]
        if not isinstance(clauses, list) or not clauses:
            raise ValueError("'any' needs a non-empty list")
        out = pd.Series(False, index=df.index)
        for c in clauses:
            out |= evaluate(c, df, feats, depth + 1)
        return out
    if "not" in rule:
        return ~evaluate(rule["not"], df, feats, depth + 1)

    if "cmp" in rule:
        cmp = rule["cmp"]
        if cmp not in _CMP:
            raise ValueError(f"unknown comparison operator: {cmp!r}")
        lhs = _ref(rule.get("lhs"), df, feats)
        rhs = _ref(rule.get("rhs"), df, feats)
        return _compare(lhs, cmp, rhs)

    raise ValueError(f"unrecognised rule: {rule!r}")


def referenced_names(rule) -> set:
    """Collect all string feature/column names a rule references (for validation
    and for pruning unused features). Numbers and operators are ignored."""
    names = set()

    def walk(node):
        if isinstance(node, dict):
            if "cmp" in node:
                for side in ("lhs", "rhs"):
                    v = node.get(side)
                    if isinstance(v, str):
                        names.add(v)
            for key in ("all", "any"):
                if key in node:
                    for c in node[key]:
                        walk(c)
            if "not" in node:
                walk(node["not"])

    walk(rule)
    return names
