"""Research governance — the controls that make autonomous testing safe:
a multiple-testing ledger and an out-of-sample budget (Volume 3 §11; required
before L4 autonomy per the Master Plan)."""
from .ledger import OOSBudget, budget_status

__all__ = ["OOSBudget", "budget_status"]
