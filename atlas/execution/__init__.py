"""Atlas execution boundary — the separately-governed practical/market half.

Research (the council + ladder) decides *whether* a strategy has an edge. This
package decides *how* an approved strategy reaches a broker — and, above all,
makes sure nothing touches real capital without explicit, auditable permission.

Design (from the Atlas vNext spec, Part 14/21):
- `BrokerAdapter` is the only thing that talks to a broker; research never does.
- `AccountMode` is explicit and shown everywhere: REPLAY/OBSERVE/PAPER/SHADOW send
  no live orders; only MICRO_LIVE/LIVE can, and only through the CapitalGate.
- `CapitalGate` hard-blocks live orders unless live is explicitly enabled AND no
  kill switch is active. The kill switch is persistent — it survives restart.
- `PaperBroker` simulates fills with zero ability to reach a real broker.

Nothing here is wired to a real MT5 terminal yet; that adapter is added later and
runs only on the user's machine, behind this same gate, demo-first.
"""
from .broker import (AccountMode, BrokerAdapter, OrderRequest, OrderResult,
                     Position, AccountState, SymbolSpec)
from .gate import CapitalGate, GateError
from .paper import PaperBroker
from .feed import ReplayFeed, MT5Feed
from .executor import Executor, research_clearance

__all__ = ["AccountMode", "BrokerAdapter", "OrderRequest", "OrderResult",
           "Position", "AccountState", "SymbolSpec", "CapitalGate", "GateError",
           "PaperBroker", "make_mt5_broker", "ReplayFeed", "MT5Feed", "Executor",
           "research_clearance"]


def make_mt5_broker(*args, **kwargs):
    """Lazy factory so importing the package never requires MetaTrader5."""
    from .mt5_broker import MT5Broker
    return MT5Broker(*args, **kwargs)
