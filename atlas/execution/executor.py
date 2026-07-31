"""The executor — turns an APPROVED strategy into (paper/live) market activity.

The gate that matters here is **research clearance**: the executor refuses to
trade a strategy unless that strategy has earned it — a registry candidate exists
for it, or its latest recorded experiment verdict is PASS. A REJECTed, untested,
or inconclusive strategy is never traded; the executor will still *observe* and
report the would-be signal (as blocked), so you learn without risking anything.

Each step it rebuilds the strategy on the feed's recent bars, reads the signal on
the latest bar, manages open positions against stop/target, and routes new
signals through the account gate to the broker. In OBSERVE/PAPER/SHADOW the broker
simulates; only MICRO_LIVE/LIVE (behind the CapitalGate) can send a real order.
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional

from ..memory import MemoryStore
from ..registry import Registry
from ..research.fx.config import load as load_cfg
from ..research.fx.strategies.base import Strategy
import atlas.research.fx.strategies  # noqa: registers templates
from .broker import AccountMode, OrderRequest
from .gate import GateError


def research_clearance(root: str, strategy_name: str) -> dict:
    """Is this strategy cleared to trade? Cleared iff a registry candidate exists
    for it OR its latest experiment verdict is PASS. Returns the basis + evidence
    so the decision is auditable."""
    store = MemoryStore(root)
    try:
        matching_exps, hyp_ids = [], set()
        for e in store.list_experiments(limit=2000):
            h = store.get_hypothesis(e.hypothesis_id)
            if h and h.title == strategy_name:
                matching_exps.append(e)
                hyp_ids.add(e.hypothesis_id)
    finally:
        store.close()

    latest_verdict = matching_exps[0].verdict if matching_exps else None
    strategy_id = None
    reg = Registry(root)
    try:
        for r in reg.list():
            if r.source_hypothesis_id in hyp_ids:
                strategy_id = r.strategy_id
                break
    finally:
        reg.close()

    if strategy_id is not None:
        return {"cleared": True, "basis": "registry_candidate",
                "reason": f"registry candidate {strategy_id} (passed the ladder)",
                "verdict": latest_verdict, "strategy_id": strategy_id,
                "experiments": len(matching_exps)}
    if latest_verdict == "PASS":
        return {"cleared": True, "basis": "pass_verdict",
                "reason": "latest experiment verdict is PASS",
                "verdict": latest_verdict, "strategy_id": None,
                "experiments": len(matching_exps)}
    if not matching_exps:
        reason = "not cleared: no recorded experiment for this strategy yet — " \
                 "run the council on it first"
    else:
        reason = f"not cleared: latest verdict is {latest_verdict} " \
                 "(needs a PASS / registry candidate)"
    return {"cleared": False, "basis": "none", "reason": reason,
            "verdict": latest_verdict, "strategy_id": None,
            "experiments": len(matching_exps)}


class Executor:
    def __init__(self, root: str, broker, gate, mode: AccountMode,
                 volume: float = 0.01, emit: Optional[Callable] = None):
        self.root = root
        self.broker = broker
        self.gate = gate
        self.mode = mode
        self.volume = volume
        self.emit = emit or (lambda **k: None)
        self.cfg: Optional[dict] = None
        self.name: Optional[str] = None
        self.clearance: Optional[dict] = None
        self.armed = False
        self._open: Dict[str, str] = {}          # symbol -> position_id

    def arm(self, hyp_path: str) -> dict:
        """Load a hypothesis file and decide whether it's cleared to trade."""
        cfg = load_cfg(hyp_path)
        self.cfg = cfg
        self.name = cfg["name"]
        self.clearance = research_clearance(self.root, self.name)
        self.armed = self.clearance["cleared"]
        self.emit(event_type="strategy_armed", agent_name="Executor",
                  severity="info" if self.armed else "warning",
                  title=f"{'armed' if self.armed else 'blocked'}: {self.name}",
                  summary=self.clearance["reason"],
                  metadata={"armed": self.armed, **self.clearance})
        return {"armed": self.armed, "name": self.name, "clearance": self.clearance}

    def _manage_exits(self, feed) -> List[dict]:
        actions = []
        for pos in list(self.broker.get_open_positions()):
            bars = feed.recent_bars(pos.symbol, 2)
            if not len(bars):
                continue
            hi = float(bars["high"].iloc[-1]); lo = float(bars["low"].iloc[-1])
            hit_stop = (pos.stop is not None and
                        (lo <= pos.stop if pos.direction == "BUY" else hi >= pos.stop))
            hit_tp = (pos.target is not None and
                      (hi >= pos.target if pos.direction == "BUY" else lo <= pos.target))
            if hit_stop or hit_tp:
                exit_price = pos.stop if hit_stop else pos.target
                self.broker.close_position(pos.position_id, ref_price=exit_price)
                self._open.pop(pos.symbol, None)
                actions.append({"type": "close", "symbol": pos.symbol,
                                "reason": "stop" if hit_stop else "target",
                                "price": exit_price})
                self.emit(event_type="position_closed", agent_name="Executor",
                          title=f"closed {pos.symbol}",
                          summary=f"{'stop' if hit_stop else 'target'} @ {exit_price}",
                          strategy_id=(self.clearance or {}).get("strategy_id"))
        return actions

    def step(self, feed) -> List[dict]:
        """One tick: manage exits, then look for a new signal per market."""
        if not self.cfg:
            return []
        actions = self._manage_exits(feed)
        for symbol in self.cfg.get("markets", []):
            bars = feed.recent_bars(symbol, 600)
            if len(bars) < 50:
                continue
            strat = Strategy.create(self.cfg)
            try:
                strat.prepare(bars, symbol=symbol)
                sig = strat.signal_at(len(bars) - 1)
            except Exception:
                continue
            if sig is None:
                continue
            price = float(bars["close"].iloc[-1])
            self.emit(event_type="signal_generated", agent_name="Executor",
                      title=f"signal {sig.direction} {symbol}",
                      summary=f"{self.name} @ {price} (mode {self.mode.value})",
                      strategy_id=(self.clearance or {}).get("strategy_id"))
            if not self.armed:
                actions.append({"type": "blocked", "symbol": symbol,
                                "direction": sig.direction,
                                "reason": self.clearance["reason"]})
                self.emit(event_type="order_blocked", agent_name="Executor",
                          severity="warning", title=f"blocked {symbol}",
                          summary=self.clearance["reason"])
                continue
            if symbol in self._open:                 # one position per symbol
                continue
            req = OrderRequest(symbol, sig.direction, self.volume, stop=sig.stop,
                               target=sig.target, comment=f"atlas {self.name[:18]}",
                               strategy_id=(self.clearance or {}).get("strategy_id"))
            allowed, reason = self.gate.authorize(self.mode, req)
            if not allowed:
                actions.append({"type": "blocked", "symbol": symbol, "reason": reason})
                self.emit(event_type="order_blocked", agent_name="Executor",
                          severity="warning", title=f"gate blocked {symbol}",
                          summary=reason)
                continue
            try:
                res = self.broker.place_order(req, ref_price=price)
            except GateError as e:
                actions.append({"type": "blocked", "symbol": symbol, "reason": str(e)})
                continue
            if res.ok and res.order_id:
                self._open[symbol] = res.order_id
            actions.append({"type": "fill", "symbol": symbol,
                            "direction": sig.direction, "price": price,
                            "simulated": res.simulated, "order_id": res.order_id,
                            "reason": res.reason})
            self.emit(event_type="paper_fill", agent_name="Executor",
                      title=f"{'sim' if res.simulated else 'LIVE'} fill {sig.direction} {symbol}",
                      summary=f"{self.name} @ {price} ({res.reason})",
                      strategy_id=(self.clearance or {}).get("strategy_id"),
                      metadata={"simulated": res.simulated, "mode": self.mode.value})
        return actions

    def run_replay(self, feed, max_steps: int = 100000) -> dict:
        """Step a ReplayFeed to the end (or max_steps), collecting activity."""
        fills = closes = blocked = signals = 0
        while feed.has_more() and max_steps > 0:
            for a in self.step(feed):
                signals += 1
                fills += a["type"] == "fill"
                closes += a["type"] == "close"
                blocked += a["type"] == "blocked"
            feed.advance()
            max_steps -= 1
        acct = self.broker.get_account_state()
        return {"name": self.name, "armed": self.armed,
                "clearance": self.clearance, "fills": fills, "closes": closes,
                "blocked": blocked, "balance": acct.balance, "equity": acct.equity}
