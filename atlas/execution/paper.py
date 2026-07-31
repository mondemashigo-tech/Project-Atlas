"""PaperBroker — a simulated broker with ZERO ability to reach a real one.

Used for REPLAY / OBSERVE / PAPER / SHADOW. It can never be constructed in a
live-capital mode, so a paper broker can never masquerade as live. Fills are
simulated at a supplied reference price; positions and realised P/L are tracked
in memory. This is what powers the daily practical loop safely.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from ..schemas import new_id
from .broker import (AccountMode, BrokerAdapter, OrderRequest, OrderResult,
                     Position, AccountState, SymbolSpec)


class PaperBroker(BrokerAdapter):
    def __init__(self, mode: AccountMode = AccountMode.PAPER,
                 balance: float = 10000.0, contract_size: float = 100000.0):
        if mode.sends_orders:
            raise ValueError(f"PaperBroker cannot run in a live mode ({mode.value})")
        self.mode = mode
        self._balance = balance
        self._start_balance = balance
        self.contract_size = contract_size    # 1 standard lot = 100k units (FX)
        self._positions: Dict[str, Position] = {}
        self._connected = False
        self.intents: List[dict] = []          # SHADOW/OBSERVE record of intent

    @property
    def realised_pnl(self) -> float:
        return self._balance - self._start_balance

    def connect(self) -> bool:
        self._connected = True
        return True

    def disconnect(self) -> None:
        self._connected = False

    def health_check(self) -> dict:
        return {"connected": self._connected, "mode": self.mode.value,
                "sends_orders": False}

    def get_account_state(self) -> AccountState:
        unreal = sum(p.pnl for p in self._positions.values())
        return AccountState(currency="USD", balance=self._balance,
                            equity=self._balance + unreal, is_demo=True)

    def get_symbol_spec(self, symbol: str) -> SymbolSpec:
        digits = 3 if symbol.upper().endswith("JPY") else 5
        return SymbolSpec(symbol=symbol, digits=digits,
                          point=10 ** (-digits))

    def get_open_positions(self) -> List[Position]:
        return list(self._positions.values())

    def place_order(self, req: OrderRequest,
                    ref_price: Optional[float] = None) -> OrderResult:
        # OBSERVE / SHADOW: record what WOULD be sent, but never fill.
        if self.mode in (AccountMode.OBSERVE, AccountMode.SHADOW, AccountMode.REPLAY):
            self.intents.append({"symbol": req.symbol, "direction": req.direction,
                                 "volume": req.volume, "ref_price": ref_price,
                                 "mode": self.mode.value})
            return OrderResult(ok=True, mode=self.mode.value, simulated=True,
                               reason=f"{self.mode.value}: intent recorded, no fill")
        # PAPER: simulate a fill.
        if ref_price is None:
            return OrderResult(ok=False, mode=self.mode.value,
                               reason="no reference price to simulate a fill")
        pid = new_id("POS")
        self._positions[pid] = Position(
            position_id=pid, symbol=req.symbol, direction=req.direction,
            volume=req.volume, entry=ref_price, stop=req.stop, target=req.target)
        return OrderResult(ok=True, mode=self.mode.value, order_id=pid,
                           fill_price=ref_price, simulated=True,
                           reason="paper fill")

    def close_position(self, position_id: str,
                       ref_price: Optional[float] = None) -> OrderResult:
        pos = self._positions.pop(position_id, None)
        if pos is None:
            return OrderResult(ok=False, mode=self.mode.value,
                               reason="unknown position")
        if ref_price is not None:
            signed = 1 if pos.direction == "BUY" else -1
            # P/L in account currency: price move * lots * contract size
            pnl = signed * (ref_price - pos.entry) * pos.volume * self.contract_size
            self._balance += pnl
            pos.pnl = pnl
        return OrderResult(ok=True, mode=self.mode.value, order_id=position_id,
                           fill_price=ref_price, simulated=True, reason="paper close")

    def reconcile_state(self) -> dict:
        # a simulated broker is always self-consistent
        return {"ok": True, "open_positions": len(self._positions),
                "unknown_positions": 0}
