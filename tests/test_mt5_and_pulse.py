"""MT5 adapter (with an injected stub — no MetaTrader5 needed) and the Pulse
cockpit endpoints. Proves the adapter never sends orders in non-live modes and
that live orders are gated."""
import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from atlas.execution import AccountMode, CapitalGate, OrderRequest
from atlas.execution.mt5_broker import MT5Broker
from atlas.live import create_app


class _Tick:
    bid = 1.2499
    ask = 1.2501


class _Acct:
    login = 999; server = "OctaFX-Demo"; currency = "USD"
    balance = 5000.0; equity = 5010.0; margin = 0.0; trade_mode = 0   # demo


class _Result:
    def __init__(self, retcode, order=123):
        self.retcode = retcode; self.order = order; self.comment = "ok"


class FakeMT5:
    """Minimal stand-in for the MetaTrader5 module."""
    TRADE_ACTION_DEAL = 1; ORDER_TYPE_BUY = 0; ORDER_TYPE_SELL = 1
    ORDER_TIME_GTC = 0; ORDER_FILLING_IOC = 1; TRADE_RETCODE_DONE = 10009

    def __init__(self):
        self.sent = []
    def initialize(self, **k): return True
    def shutdown(self): pass
    def terminal_info(self): return type("T", (), {"connected": True})()
    def account_info(self): return _Acct()
    def symbol_select(self, s, on): return True
    def symbol_info(self, s): return type("S", (), {"digits": 5, "point": 1e-5,
        "volume_min": 0.01, "volume_step": 0.01, "volume_max": 100})()
    def symbol_info_tick(self, s): return _Tick()
    def positions_get(self): return []
    def last_error(self): return "none"
    def order_send(self, request):
        self.sent.append(request); return _Result(self.TRADE_RETCODE_DONE)


def test_mt5_observe_reads_data_but_never_sends():
    fake = FakeMT5()
    b = MT5Broker(mode=AccountMode.OBSERVE, mt5=fake)
    b.connect()
    acc = b.get_account_state()
    assert acc.is_demo is True and acc.balance == 5000.0
    r = b.place_order(OrderRequest("GBPUSD", "BUY", 0.01))
    assert r.ok and r.simulated and fake.sent == []       # NO real order
    assert b.intents and b.intents[-1]["mode"] == "OBSERVE"


def test_mt5_live_blocked_without_gate_enable():
    fake = FakeMT5()
    gate = CapitalGate(".", live_enabled=False)
    b = MT5Broker(mode=AccountMode.LIVE, gate=gate, mt5=fake)
    from atlas.execution import GateError
    with pytest.raises(GateError):
        b.place_order(OrderRequest("GBPUSD", "BUY", 0.01))
    assert fake.sent == []                                 # still no order


def test_mt5_live_sends_only_when_enabled(tmp_path):
    fake = FakeMT5()
    gate = CapitalGate(str(tmp_path), live_enabled=True)
    b = MT5Broker(mode=AccountMode.LIVE, gate=gate, mt5=fake)
    r = b.place_order(OrderRequest("GBPUSD", "BUY", 0.01))
    assert r.ok and r.simulated is False and len(fake.sent) == 1
    assert fake.sent[0]["type"] == fake.ORDER_TYPE_BUY
    # kill switch stops even an enabled live account
    gate.activate_kill_switch("halt")
    from atlas.execution import GateError
    with pytest.raises(GateError):
        b.place_order(OrderRequest("GBPUSD", "BUY", 0.01))
    assert len(fake.sent) == 1


def test_mt5_unknown_positions_block_live(tmp_path):
    fake = FakeMT5()
    fake.positions_get = lambda: [type("P", (), {"ticket": 5, "symbol": "GBPUSD",
        "type": 0, "volume": 0.1, "price_open": 1.25, "sl": 0, "tp": 0,
        "profit": 0, "magic": 111})()]    # foreign magic -> unknown
    gate = CapitalGate(str(tmp_path), live_enabled=True)
    b = MT5Broker(mode=AccountMode.LIVE, gate=gate, mt5=fake)
    r = b.place_order(OrderRequest("GBPUSD", "BUY", 0.01))
    assert r.ok is False and "unknown" in r.reason and fake.sent == []


# ---- Pulse endpoints -------------------------------------------------------
def test_pulse_status_defaults_safe(tmp_path):
    c = TestClient(create_app(str(tmp_path)))
    s = c.get("/api/pulse").json()
    assert s["mode"] == "OBSERVE" and s["sends_orders"] is False
    assert s["live_enabled"] is False and s["kill_switch"] is False
    assert s["broker"] == "PaperBroker"


def test_pulse_kill_switch_roundtrip(tmp_path):
    c = TestClient(create_app(str(tmp_path)))
    assert c.post("/api/pulse/kill", json={"reason": "test"}).json()["kill_switch"] is True
    assert c.get("/api/pulse").json()["kill_switch"] is True     # persisted
    assert c.post("/api/pulse/clear-kill").json()["kill_switch"] is False
