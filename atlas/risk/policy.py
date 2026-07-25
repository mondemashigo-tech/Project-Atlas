"""Risk policy — the limits the Risk Manager enforces. Everything is in R units
(scale-invariant) except per-trade risk which is a fraction of capital. Policy
lives in memory as 'policy memory' (Volume 2 §8) and is human-reviewed."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RiskPolicy:
    risk_per_trade_max: float = 0.01     # 1% of capital per trade, max
    max_daily_loss_r: float = 3.0        # worst-case R lost in a day
    max_weekly_loss_r: float = 6.0
    max_open_exposure_r: float = 3.0     # total R at risk across open trades
    max_drawdown_r: float = 40.0         # historical max drawdown ceiling
    min_trades: int = 100                # too few trades -> can't trust the risk profile
