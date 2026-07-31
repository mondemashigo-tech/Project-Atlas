"""MetaTrader 5 broker adapter.

Runs only where a MetaTrader 5 terminal is installed (the user's Windows machine).
The `MetaTrader5` package is imported lazily, so importing this module never
breaks environments without it (tests inject a stub).

Safety, layered:
- Credentials come from environment variables, never code/params.
- In REPLAY/OBSERVE/PAPER/SHADOW it reads real data but **simulates** fills — it
  never calls `order_send`.
- Only in MICRO_LIVE/LIVE does it place a real order, and only after the
  CapitalGate authorizes it (live enabled + no kill switch). Unknown broker
  positions block trading (reconciliation).

Request/connection shapes mirror the proven zpk-trade-scout bot (TRADE_ACTION_DEAL,
ORDER_TIME_GTC, ORDER_FILLING_IOC, magic + deviation) — harvested, not run.
"""
from __future__ import annotations

import os
from typing import List, Optional

from ..schemas import new_id
from .broker import (AccountMode, BrokerAdapter, OrderRequest, OrderResult,
                     Position, AccountState, SymbolSpec)

DEFAULT_MAGIC = 770077


class MT5Broker(BrokerAdapter):
    def __init__(self, mode: AccountMode = AccountMode.OBSERVE, gate=None,
                 magic: int = DEFAULT_MAGIC, deviation: int = 20, mt5=None):
        self.mode = mode
        self.gate = gate
        self.magic = magic
        self.deviation = deviation
        self._mt5 = mt5                 # inject a stub in tests; else lazy-imported
        self._connected = False
        self.intents: List[dict] = []

    def _lib(self):
        if self._mt5 is None:
            import MetaTrader5 as mt5   # noqa: only on the trading machine
            self._mt5 = mt5
        return self._mt5

    # -- connection --------------------------------------------------------
    def connect(self) -> bool:
        mt5 = self._lib()
        login = os.environ.get("ATLAS_MT5_LOGIN")
        pw = os.environ.get("ATLAS_MT5_PASSWORD")
        server = os.environ.get("ATLAS_MT5_SERVER")
        if login and pw and server:     # explicit login from env
            ok = mt5.initialize(login=int(login), password=pw, server=server)
        else:                            # attach to the already-logged-in terminal
            ok = mt5.initialize()
        self._connected = bool(ok)
        return self._connected

    def disconnect(self) -> None:
        try:
            self._lib().shutdown()
        except Exception:
            pass
        self._connected = False

    def health_check(self) -> dict:
        try:
            ti = self._lib().terminal_info()
            connected = bool(getattr(ti, "connected", self._connected))
        except Exception:
            connected = self._connected
        return {"connected": connected, "mode": self.mode.value,
                "sends_orders": self.mode.sends_orders}

    # -- account / market data --------------------------------------------
    def get_account_state(self) -> AccountState:
        a = self._lib().account_info()
        if a is None:
            return AccountState()
        # ACCOUNT_TRADE_MODE_DEMO == 0, REAL == 2
        trade_mode = getattr(a, "trade_mode", 0)
        return AccountState(login=str(getattr(a, "login", "")),
                            server=getattr(a, "server", None),
                            currency=getattr(a, "currency", "USD"),
                            balance=float(getattr(a, "balance", 0.0)),
                            equity=float(getattr(a, "equity", 0.0)),
                            margin=float(getattr(a, "margin", 0.0)),
                            is_demo=(trade_mode != 2))

    def get_symbol_spec(self, symbol: str) -> SymbolSpec:
        mt5 = self._lib()
        mt5.symbol_select(symbol, True)
        s = mt5.symbol_info(symbol)
        if s is None:
            return SymbolSpec(symbol=symbol, trade_allowed=False)
        return SymbolSpec(symbol=symbol, digits=int(getattr(s, "digits", 5)),
                          point=float(getattr(s, "point", 1e-5)),
                          volume_min=float(getattr(s, "volume_min", 0.01)),
                          volume_step=float(getattr(s, "volume_step", 0.01)),
                          volume_max=float(getattr(s, "volume_max", 100.0)),
                          trade_allowed=True)

    def get_price(self, symbol: str):
        t = self._lib().symbol_info_tick(symbol)
        return (float(t.bid), float(t.ask)) if t else (None, None)

    def get_open_positions(self) -> List[Position]:
        ps = self._lib().positions_get() or []
        out = []
        for p in ps:
            direction = "BUY" if getattr(p, "type", 0) == 0 else "SELL"
            out.append(Position(position_id=str(p.ticket), symbol=p.symbol,
                                direction=direction, volume=float(p.volume),
                                entry=float(p.price_open),
                                stop=float(getattr(p, "sl", 0) or 0) or None,
                                target=float(getattr(p, "tp", 0) or 0) or None,
                                pnl=float(getattr(p, "profit", 0.0))))
        return out

    # -- orders ------------------------------------------------------------
    def place_order(self, req: OrderRequest,
                    ref_price: Optional[float] = None) -> OrderResult:
        # Non-live modes: read real price, but SIMULATE — never send.
        if not self.mode.sends_orders:
            price = ref_price
            if price is None:
                bid, ask = self.get_price(req.symbol)
                price = ask if req.direction == "BUY" else bid
            self.intents.append({"symbol": req.symbol, "direction": req.direction,
                                 "volume": req.volume, "ref_price": price,
                                 "mode": self.mode.value})
            oid = new_id("SIM") if self.mode == AccountMode.PAPER else None
            return OrderResult(ok=True, mode=self.mode.value, order_id=oid,
                               fill_price=price, simulated=True,
                               reason=f"{self.mode.value}: simulated, no live order")

        # Live modes: HARD gate, reconciliation, then a real order.
        if self.gate is not None:
            self.gate.require(self.mode, req)          # raises GateError if blocked
        rec = self.reconcile_state()
        if rec.get("unknown_positions", 0) > 0:
            return OrderResult(ok=False, mode=self.mode.value, simulated=False,
                               reason="unknown broker positions — trading blocked "
                                      "until reconciled")
        mt5 = self._lib()
        t = mt5.symbol_info_tick(req.symbol)
        price = float(t.ask if req.direction == "BUY" else t.bid)
        otype = mt5.ORDER_TYPE_BUY if req.direction == "BUY" else mt5.ORDER_TYPE_SELL
        request = {
            "action": mt5.TRADE_ACTION_DEAL, "symbol": req.symbol,
            "volume": float(req.volume), "type": otype, "price": price,
            "sl": float(req.stop) if req.stop else 0.0,
            "tp": float(req.target) if req.target else 0.0,
            "deviation": self.deviation, "magic": self.magic,
            "comment": req.comment[:31], "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(request)
        if result is None:
            return OrderResult(ok=False, mode=self.mode.value, simulated=False,
                               reason=f"order_send failed: {mt5.last_error()}")
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            return OrderResult(ok=False, mode=self.mode.value, simulated=False,
                               reason=f"rejected retcode {result.retcode}: "
                                      f"{getattr(result, 'comment', '')}")
        return OrderResult(ok=True, mode=self.mode.value, simulated=False,
                           order_id=str(result.order), fill_price=price,
                           reason="live fill")

    def close_position(self, position_id: str,
                       ref_price: Optional[float] = None) -> OrderResult:
        if not self.mode.sends_orders:
            return OrderResult(ok=True, mode=self.mode.value, simulated=True,
                               reason=f"{self.mode.value}: simulated close")
        if self.gate is not None:
            self.gate.require(self.mode)
        mt5 = self._lib()
        pos = next((p for p in (mt5.positions_get() or [])
                    if str(p.ticket) == str(position_id)), None)
        if pos is None:
            return OrderResult(ok=False, mode=self.mode.value, simulated=False,
                               reason="unknown position")
        # close = opposite market order for the position volume
        closing = "SELL" if getattr(pos, "type", 0) == 0 else "BUY"
        t = mt5.symbol_info_tick(pos.symbol)
        price = float(t.bid if closing == "SELL" else t.ask)
        otype = mt5.ORDER_TYPE_SELL if closing == "SELL" else mt5.ORDER_TYPE_BUY
        request = {"action": mt5.TRADE_ACTION_DEAL, "symbol": pos.symbol,
                   "volume": float(pos.volume), "type": otype, "price": price,
                   "position": pos.ticket, "deviation": self.deviation,
                   "magic": self.magic, "comment": "atlas close",
                   "type_time": mt5.ORDER_TIME_GTC,
                   "type_filling": mt5.ORDER_FILLING_IOC}
        result = mt5.order_send(request)
        ok = result is not None and result.retcode == mt5.TRADE_RETCODE_DONE
        return OrderResult(ok=ok, mode=self.mode.value, simulated=False,
                           order_id=str(position_id), fill_price=price,
                           reason="live close" if ok else "close failed")

    def reconcile_state(self) -> dict:
        """Positions not opened by Atlas (foreign magic) are 'unknown' and must
        block new live orders (spec 21.3)."""
        ps = self._lib().positions_get() or []
        ours = [p for p in ps if getattr(p, "magic", None) == self.magic]
        unknown = [p for p in ps if getattr(p, "magic", None) != self.magic]
        return {"ok": len(unknown) == 0, "open_positions": len(ours),
                "unknown_positions": len(unknown)}
