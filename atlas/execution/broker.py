"""Broker adapter interface + account modes + the typed order/account records.

The interface mirrors the vNext spec (14.2). Every concrete broker (paper today,
MT5 later) implements the same surface, so research and the executor never depend
on a specific broker. Account modes are explicit and carry their own capability:
only MICRO_LIVE and LIVE may ever send a real order, and even then only through
the CapitalGate.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class AccountMode(str, Enum):
    REPLAY = "REPLAY"        # historical replay; no orders
    OBSERVE = "OBSERVE"      # live data + signals; no orders
    PAPER = "PAPER"          # simulated fills; no broker order
    SHADOW = "SHADOW"        # record what WOULD be sent; no orders
    MICRO_LIVE = "MICRO_LIVE"  # tiny real risk; orders sent, tightly gated
    LIVE = "LIVE"            # full production; orders sent, gated

    @property
    def sends_orders(self) -> bool:
        """Only these two modes may reach a real broker."""
        return self in (AccountMode.MICRO_LIVE, AccountMode.LIVE)

    @property
    def is_live_capital(self) -> bool:
        return self.sends_orders


@dataclass
class OrderRequest:
    symbol: str
    direction: str                 # "BUY" | "SELL"
    volume: float                  # lots
    order_type: str = "market"     # "market" | "limit" | "stop"
    price: Optional[float] = None  # for pending orders
    stop: Optional[float] = None
    target: Optional[float] = None
    comment: str = "atlas"
    strategy_id: Optional[str] = None
    client_id: Optional[str] = None   # idempotency key (prevents duplicate sends)


@dataclass
class OrderResult:
    ok: bool
    mode: str
    order_id: Optional[str] = None
    fill_price: Optional[float] = None
    reason: str = ""
    simulated: bool = True         # True unless a real broker actually filled it


@dataclass
class Position:
    position_id: str
    symbol: str
    direction: str
    volume: float
    entry: float
    stop: Optional[float] = None
    target: Optional[float] = None
    pnl: float = 0.0


@dataclass
class AccountState:
    login: Optional[str] = None
    server: Optional[str] = None
    currency: str = "USD"
    balance: float = 0.0
    equity: float = 0.0
    margin: float = 0.0
    is_demo: Optional[bool] = None


@dataclass
class SymbolSpec:
    symbol: str
    digits: int = 5
    point: float = 0.00001
    volume_min: float = 0.01
    volume_step: float = 0.01
    volume_max: float = 100.0
    trade_allowed: bool = True


class BrokerAdapter(ABC):
    """The only surface that talks to a broker. Concrete adapters: PaperBroker
    (now), MT5Broker (later, on the user's machine)."""

    mode: AccountMode

    @abstractmethod
    def connect(self) -> bool: ...

    @abstractmethod
    def disconnect(self) -> None: ...

    @abstractmethod
    def health_check(self) -> dict: ...

    @abstractmethod
    def get_account_state(self) -> AccountState: ...

    @abstractmethod
    def get_symbol_spec(self, symbol: str) -> SymbolSpec: ...

    @abstractmethod
    def get_open_positions(self) -> List[Position]: ...

    @abstractmethod
    def place_order(self, req: OrderRequest, ref_price: Optional[float] = None
                    ) -> OrderResult: ...

    @abstractmethod
    def close_position(self, position_id: str, ref_price: Optional[float] = None
                       ) -> OrderResult: ...

    @abstractmethod
    def reconcile_state(self) -> dict: ...
