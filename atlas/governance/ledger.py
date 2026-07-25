"""Out-of-sample budget / multiple-testing control.

Every distinct hypothesis tested against a holdout snapshot is a "look" at that
data. Enough looks and *something* passes by chance (false discovery). The budget
caps how many looks a holdout may take before it is "burned" and must be
refreshed with new, unseen data. This is what lets autonomy (L4) queue many
experiments without silently manufacturing false positives.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class OOSBudget:
    max_tests: int = 20      # distinct hypotheses per holdout before it's burned


def budget_status(store, snapshot_id: str, window: str = "out_sample",
                  budget: OOSBudget = None) -> dict:
    budget = budget or OOSBudget()
    count = store.oos_test_count(snapshot_id, window)
    return {
        "snapshot_id": snapshot_id,
        "window": window,
        "count": count,
        "budget": budget.max_tests,
        "remaining": max(0, budget.max_tests - count),
        "burned": count > budget.max_tests,
    }
