"""Live paper session — the daily practical loop.

Runs a CLEARED strategy against a live feed on an interval, simulating fills at
real prices and tallying P/L in account currency. It never sends a real order
(PAPER mode + the gate); it refuses to start for a strategy that hasn't earned
clearance. On the trading machine the feed is MT5 (real OctaFX ticks); for demo
it replays the root's datasets as if live.

This is what shows "what we could make" — but only for a strategy that actually
passed validation. Nothing here can lose real money.
"""
from __future__ import annotations

import os
import threading
from typing import Optional

from ..memory import MemoryStore
from ..events import EventBus, Event
from ..schemas import utcnow_iso
from ..execution import (PaperBroker, AccountMode, Executor, ReplayFeed, MT5Feed,
                         CapitalGate)


class PaperSession:
    def __init__(self, root: str, gate: CapitalGate, hyp_path: str, feed,
                 hub=None, interval_secs: float = 60.0,
                 start_balance: float = 10000.0):
        self.root = root
        self.gate = gate
        self.hub = hub
        self.hyp_path = hyp_path
        self.feed = feed
        self.interval = max(0.5, interval_secs)
        self.broker = PaperBroker(mode=AccountMode.PAPER, balance=start_balance)
        self.executor = Executor(root, self.broker, gate, AccountMode.PAPER)
        self.armed = False
        self.clearance = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self.stats = {"ticks": 0, "signals": 0, "fills": 0, "closes": 0,
                      "blocked": 0, "last_tick": None}

    def tick(self) -> list:
        """One step: manage exits + look for a signal. Advances a replay feed."""
        actions = self.executor.step(self.feed)
        self.stats["ticks"] += 1
        for a in actions:
            self.stats["signals"] += 1
            self.stats["fills"] += a["type"] == "fill"
            self.stats["closes"] += a["type"] == "close"
            self.stats["blocked"] += a["type"] == "blocked"
        self.stats["last_tick"] = utcnow_iso()
        if hasattr(self.feed, "advance"):
            self.feed.advance()
        return actions

    def start(self) -> dict:
        info = self.executor.arm(self.hyp_path)          # clearance gate
        self.armed = info["armed"]
        self.clearance = info["clearance"]
        if not self.armed:
            return {"started": False, "reason": self.clearance["reason"],
                    "clearance": self.clearance}
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return {"started": True, "name": info["name"], "interval": self.interval}

    def _run(self) -> None:
        store = MemoryStore(self.root)
        bus = EventBus(store)
        if self.hub is not None:
            bus.subscribe(lambda e: self.hub.broadcast(e.to_dict()))
        self.executor.emit = lambda **k: bus.publish(
            Event(source_module="live.session", **k))
        try:
            while not self._stop.is_set():
                if self.gate.kill_switch_active():
                    break                                # kill switch halts the loop
                try:
                    self.tick()
                except Exception:
                    pass
                if hasattr(self.feed, "has_more") and not self.feed.has_more():
                    break                                # replay exhausted
                self._stop.wait(self.interval)
        finally:
            store.close()

    def stop(self) -> dict:
        self._stop.set()
        return {"stopped": True}

    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def status(self) -> dict:
        acct = self.broker.get_account_state()
        return {
            "running": self.running(), "armed": self.armed,
            "clearance": self.clearance, "name": self.executor.name,
            "stats": self.stats, "balance": round(acct.balance, 2),
            "equity": round(acct.equity, 2),
            "realised_pnl": round(self.broker.realised_pnl, 2),
            "open_positions": len(self.broker.get_open_positions()),
        }


def build_feed(root: str, cfg: dict):
    """MT5 live feed on the trading machine (ATLAS_BROKER=mt5); otherwise a replay
    of the root's datasets as if live (for demo)."""
    if os.environ.get("ATLAS_BROKER", "").lower() == "mt5":
        return MT5Feed(timeframe=cfg.get("timeframes", {}).get("entry", "M5")), 60.0
    import glob
    import pandas as pd
    bars = {}
    for sym in cfg.get("markets", []):
        f = glob.glob(os.path.join(root, "datasets", f"{sym}_M5.csv"))
        if f:
            df = pd.read_csv(f[0])
            df["time"] = pd.to_datetime(df["time"], utc=True)
            bars[sym] = df.set_index("time")[["open", "high", "low", "close"]]
    return (ReplayFeed(bars) if bars else None), 1.0
