"""Execution safety spine: account modes, the capital gate (with a persistent
kill switch), and the paper broker's zero-live-capability guarantee.

These are the highest-stakes tests in Atlas — they prove money cannot move
without explicit permission. No broker, no network.
"""
import pytest

from atlas.execution import (AccountMode, CapitalGate, GateError, PaperBroker,
                             OrderRequest)


# ---- account modes ---------------------------------------------------------
def test_only_micro_and_full_live_send_orders():
    sending = {m for m in AccountMode if m.sends_orders}
    assert sending == {AccountMode.MICRO_LIVE, AccountMode.LIVE}
    for m in (AccountMode.REPLAY, AccountMode.OBSERVE, AccountMode.PAPER,
              AccountMode.SHADOW):
        assert not m.sends_orders


# ---- capital gate ----------------------------------------------------------
def test_gate_blocks_live_unless_enabled(tmp_path):
    gate = CapitalGate(str(tmp_path), live_enabled=False)
    ok, reason = gate.authorize(AccountMode.LIVE, OrderRequest("GBPUSD", "BUY", 0.01))
    assert ok is False and "not enabled" in reason
    with pytest.raises(GateError):
        gate.require(AccountMode.MICRO_LIVE)
    # non-live modes are allowed (when not killed)
    assert gate.authorize(AccountMode.PAPER)[0] is True


def test_gate_allows_live_only_when_explicitly_enabled(tmp_path):
    gate = CapitalGate(str(tmp_path), live_enabled=True)
    assert gate.authorize(AccountMode.LIVE, OrderRequest("GBPUSD", "BUY", 0.01))[0] is True


def test_kill_switch_blocks_everything_and_persists(tmp_path):
    gate = CapitalGate(str(tmp_path), live_enabled=True)
    gate.activate_kill_switch("test stop")
    # blocks even paper/observe
    assert gate.authorize(AccountMode.PAPER)[0] is False
    assert gate.authorize(AccountMode.LIVE)[0] is False
    # persists: a brand-new gate on the same root still sees it active (survives restart)
    fresh = CapitalGate(str(tmp_path), live_enabled=True)
    assert fresh.kill_switch_active() is True
    assert fresh.authorize(AccountMode.PAPER)[0] is False
    # clearing re-enables non-live orders
    fresh.clear_kill_switch("human")
    assert CapitalGate(str(tmp_path)).kill_switch_active() is False


# ---- paper broker ----------------------------------------------------------
def test_paper_broker_cannot_run_live():
    for m in (AccountMode.MICRO_LIVE, AccountMode.LIVE):
        with pytest.raises(ValueError):
            PaperBroker(mode=m)


def test_paper_fill_and_close_tracks_pnl():
    b = PaperBroker(mode=AccountMode.PAPER, balance=10000)
    b.connect()
    r = b.place_order(OrderRequest("GBPUSD", "BUY", 1.0), ref_price=1.2500)
    assert r.ok and r.simulated and r.order_id
    assert len(b.get_open_positions()) == 1
    c = b.close_position(r.order_id, ref_price=1.2600)   # +0.01 * 1.0
    assert c.ok and b.get_account_state().balance == pytest.approx(10000 + 0.01)
    assert b.health_check()["sends_orders"] is False


def test_observe_and_shadow_record_intent_but_never_fill():
    for mode in (AccountMode.OBSERVE, AccountMode.SHADOW):
        b = PaperBroker(mode=mode)
        r = b.place_order(OrderRequest("USDJPY", "SELL", 0.5), ref_price=150.0)
        assert r.ok and r.simulated
        assert len(b.get_open_positions()) == 0        # no fill
        assert b.intents and b.intents[-1]["mode"] == mode.value


def test_reconcile_paper_has_no_unknown_positions():
    b = PaperBroker(mode=AccountMode.PAPER)
    assert b.reconcile_state()["unknown_positions"] == 0
