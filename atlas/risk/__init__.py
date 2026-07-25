"""Risk layer — a hard gate, not advice (Volume 4 §11). The RiskManager can veto
a strategy even when it is profitable, if it violates the risk policy."""
from .policy import RiskPolicy
from .manager import RiskManager

__all__ = ["RiskPolicy", "RiskManager"]
