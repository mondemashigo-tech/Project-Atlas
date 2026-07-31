"""Atlas Pulse — the live trading cockpit's state manager.

Holds the current account mode, the broker adapter, and the capital gate, and
reports a safe status snapshot for the cockpit UI. Defaults to a PaperBroker in
OBSERVE mode (no live capability). On the trading machine, set env
`ATLAS_BROKER=mt5` to use the MT5 adapter for real account/price data — still in
a non-live mode until deliberately promoted.

The cockpit is read + the kill switch. It cannot promote to live capital; that
path stays behind the CapitalGate and explicit enablement.
"""
from __future__ import annotations

import os
from dataclasses import asdict

from ..execution import AccountMode, CapitalGate, PaperBroker


class PulseManager:
    def __init__(self, root: str = ".", mode: AccountMode = AccountMode.OBSERVE):
        self.root = root
        self.mode = mode
        self.gate = CapitalGate(root, live_enabled=False)
        self.broker = self._make_broker()
        self.broker_error = None
        try:
            self.broker.connect()
        except Exception as e:                       # MT5 not present / not logged in
            self.broker_error = f"{type(e).__name__}: {e}"

    def _make_broker(self):
        if os.environ.get("ATLAS_BROKER", "").lower() == "mt5":
            try:
                from ..execution.mt5_broker import MT5Broker
                return MT5Broker(mode=self.mode, gate=self.gate)
            except Exception:
                pass                                 # fall back to safe paper
        return PaperBroker(mode=self.mode)

    def status(self) -> dict:
        broker_kind = type(self.broker).__name__
        out = {
            "mode": self.mode.value,
            "sends_orders": self.mode.sends_orders,
            "live_enabled": self.gate.live_enabled,
            "kill_switch": self.gate.kill_switch_active(),
            "broker": broker_kind,
            "broker_error": self.broker_error,
        }
        for key, fn in (("health", self.broker.health_check),
                        ("reconcile", self.broker.reconcile_state)):
            try:
                out[key] = fn()
            except Exception as e:
                out[key] = {"error": f"{type(e).__name__}: {e}"}
        try:
            out["account"] = asdict(self.broker.get_account_state())
        except Exception as e:
            out["account"] = {"error": f"{type(e).__name__}: {e}"}
        try:
            out["positions"] = [asdict(p) for p in self.broker.get_open_positions()]
        except Exception as e:
            out["positions"] = []
            out["positions_error"] = f"{type(e).__name__}: {e}"
        out["recent_intents"] = list(getattr(self.broker, "intents", []))[-25:]
        ex = getattr(self, "_executor", None)
        if ex is not None:
            out["armed_strategy"] = {"name": ex.name, "armed": ex.armed,
                                     "clearance": ex.clearance}
        return out

    def activate_kill(self, reason: str = "manual (cockpit)") -> dict:
        self.gate.activate_kill_switch(reason)
        return self.status()

    def clear_kill(self, by: str = "human (cockpit)") -> dict:
        self.gate.clear_kill_switch(by)
        return self.status()

    # -- executor: arm a strategy (gated behind its research verdict) -------
    def arm(self, hyp_name: str) -> dict:
        from ..execution import Executor
        from .runner import Runner
        path = Runner(self.root, None).resolve_hypothesis(hyp_name)   # path-confined
        ex = Executor(self.root, self.broker, self.gate, self.mode,
                      emit=lambda **k: None)
        self._executor = ex
        return ex.arm(path)

    def replay(self, hyp_name: str, hub=None) -> dict:
        """Paper-trade a strategy over the root's historical data, streaming
        activity to the console. Only fills if the strategy is cleared."""
        import glob
        import pandas as pd
        from ..execution import Executor, ReplayFeed, PaperBroker, AccountMode
        from ..memory import MemoryStore
        from ..events import EventBus
        from .runner import Runner
        path = Runner(self.root, None).resolve_hypothesis(hyp_name)
        cfg = __import__("atlas.research.fx.config", fromlist=["load"]).load(path)
        bars = {}
        for sym in cfg.get("markets", []):
            f = glob.glob(os.path.join(self.root, "datasets", f"{sym}_M5.csv"))
            if not f:
                continue
            df = pd.read_csv(f[0])
            df["time"] = pd.to_datetime(df["time"], utc=True)
            bars[sym] = df.set_index("time")[["open", "high", "low", "close"]]
        if not bars:
            return {"ok": False, "reason": "no datasets found under datasets/ for "
                    "this strategy's markets"}
        store = MemoryStore(self.root)
        bus = EventBus(store)
        if hub is not None:
            bus.subscribe(lambda e: hub.broadcast(e.to_dict()))
        try:
            ex = Executor(self.root, PaperBroker(mode=AccountMode.PAPER),
                          self.gate, AccountMode.PAPER,
                          emit=lambda **k: bus.publish(_ev(**k)))
            ex.arm(path)
            return ex.run_replay(ReplayFeed(bars))
        finally:
            store.close()


def _ev(**kwargs):
    from ..events import Event
    return Event(source_module="execution.executor", **kwargs)
