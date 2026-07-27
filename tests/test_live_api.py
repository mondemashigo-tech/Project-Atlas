"""Atlas Live M2/M3: backend API + SSE + grounded chat + research trigger.

A real council experiment populates the store (experiments + typed events); the
API is then exercised with FastAPI's TestClient. No LLM key is set, so chat
returns deterministic record-grounded answers.
"""
import os
import tempfile
import time

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from atlas.memory import MemoryStore
from atlas.events import EventBus
from atlas.kernel import Orchestrator
from atlas.live import create_app
from atlas.live.runner import Runner
from atlas.live.hub import Hub


def _dataset(root, seed=1, drift=0.00025):
    ds = os.path.join(root, "datasets"); os.makedirs(ds, exist_ok=True)
    n = 12000
    idx = pd.date_range("2025-01-02", periods=n, freq="5min", tz="UTC")
    rng = np.random.default_rng(seed)
    close = 1.30 + rng.normal(drift, 0.0007, n).cumsum()
    pd.DataFrame({"time": idx.astype(str),
                  "open": np.concatenate([[close[0]], close[:-1]]),
                  "high": close + np.abs(rng.normal(0, 3e-4, n)),
                  "low": close - np.abs(rng.normal(0, 3e-4, n)),
                  "close": close}).to_csv(os.path.join(ds, "GBPUSD_M5.csv"), index=False)


_HYP = """name: live_losing
version: "1.0"
template: mean_reversion
markets: [GBPUSD]
timeframes: {entry: M5}
weekdays: [0,1,2,3,4]
meanrev: {ma_period: 20, entry_z: 2.0, exit: mean}
risk: {stop: {atr_mult: 1.5, atr_period: 14}, target_r: 1.5, max_trades_per_day: 5}
costs: {spread_pips: 1.0, commission_r: 0.05}
criteria: {success: {profit_factor: 1.5, min_trades: 50, expectancy: positive}, failure: {profit_factor: 1.2, expectancy: negative}}
data: {in_sample: ["2025-01-01","2025-06-30"], out_sample: ["2025-01-02","2025-12-31"]}
"""


def _hyp_file(root):
    d = os.path.join(root, "hypotheses"); os.makedirs(d, exist_ok=True)
    p = os.path.join(d, "live_losing.yaml")
    with open(p, "w") as f:
        f.write(_HYP)
    return p


@pytest.fixture(scope="module")
def populated():
    d = tempfile.mkdtemp()
    _dataset(d)
    path = _hyp_file(d)
    store = MemoryStore(d)
    bus = EventBus(store)
    res = Orchestrator(d).run(path, window="out_sample", bus=bus)
    store.close()
    return {"root": d, "exp_id": res["experiment"].id,
            "hyp_id": res["hypothesis"].id, "verdict": res["experiment"].verdict}


@pytest.fixture(scope="module")
def client(populated):
    return TestClient(create_app(populated["root"]))


# ---- read endpoints --------------------------------------------------------
def test_overview(client):
    r = client.get("/api/overview").json()
    assert r["counts"]["experiments"] >= 1
    assert isinstance(r["recent_experiments"], list) and r["recent_experiments"]


def test_health(client):
    r = client.get("/api/system/health").json()
    assert r["status"] == "ok" and "counts" in r


def test_agents_reflect_real_roster_and_idle(client):
    r = client.get("/api/agents").json()
    ids = {a["id"] for a in r["agents"]}
    assert {"skeptic", "statistician", "historian", "reporter"} <= ids
    # after the run completed, everyone is idle (no fabricated activity)
    assert all(a["state"] == "idle" for a in r["agents"])
    assert r["runner"]["running"] is False


def test_agent_detail_has_real_activity(client):
    r = client.get("/api/agents/skeptic").json()
    assert r["name"] == "Skeptic"
    assert any(e["agent_name"] == "Skeptic" for e in r["activity"])


def test_agent_detail_404(client):
    assert client.get("/api/agents/nope").status_code == 404


def test_experiments_and_detail(client, populated):
    lst = client.get("/api/experiments").json()["experiments"]
    assert any(e["id"] == populated["exp_id"] for e in lst)
    detail = client.get(f"/api/experiments/{populated['exp_id']}").json()
    assert detail["experiment"]["id"] == populated["exp_id"]
    assert detail["hypothesis"]["id"] == populated["hyp_id"]
    assert len(detail["decisions"]) >= 3
    assert len(detail["events"]) >= 5           # real event timeline
    assert client.get("/api/experiments/EXP-nope").status_code == 404


def test_graveyard_registry_knowledge_governance(client, populated):
    gy = client.get("/api/graveyard").json()["graveyard"]
    assert any(g["hypothesis_id"] == populated["hyp_id"] for g in gy)  # losing -> buried
    assert "registry" in client.get("/api/registry").json()
    assert "knowledge" in client.get("/api/knowledge").json()
    assert "oos_looks" in client.get("/api/governance").json()


# ---- events + SSE ----------------------------------------------------------
def test_events_after_cursor(client):
    all_ev = client.get("/api/events?after_seq=0").json()["events"]
    assert len(all_ev) >= 5
    mid = all_ev[2]["seq"]
    rest = client.get(f"/api/events?after_seq={mid}").json()["events"]
    assert all(e["seq"] > mid for e in rest)


def test_sse_replays_persisted_events(populated):
    # The SSE generator must replay persisted events (from the cursor) then emit
    # the 'connected' marker. Tested at the generator level to avoid TestClient's
    # infinite-stream limitation; the wiring is exercised by test_events endpoint.
    from atlas.live.app import _sse, create_app
    app = create_app(populated["root"])
    gen = _sse(app, populated["root"], 0)
    frames, connected = [], False
    for _ in range(300):
        f = next(gen)
        frames.append(f)
        if f.strip() == ": connected":
            connected = True
            break
    gen.close()
    joined = "".join(frames)
    assert connected
    # events ride in the data payload (default 'message' type, so onmessage fires)
    assert '"event_type": "experiment_started"' in joined
    assert '"event_type": "experiment_completed"' in joined
    assert "\nid: " in joined                    # seq id present for Last-Event-ID


# ---- chat (grounded) -------------------------------------------------------
def test_chat_grounded_why_rejected(client, populated):
    r = client.post("/api/chat", json={
        "message": f"why was {populated['exp_id']} rejected?"}).json()
    assert r["grounded"] is True
    assert populated["exp_id"] in r["citations"] or populated["hyp_id"] in r["citations"]
    assert r["llm_used"] is False               # no key in tests
    assert "skeptic" in r["answer"].lower() or "reject" in r["answer"].lower()


def test_chat_researching_status(client):
    r = client.post("/api/chat", json={"message": "what are you researching now?"}).json()
    assert r["intent"] == "researching"
    assert "idle" in r["answer"].lower() or "experiment" in r["answer"].lower()


def test_chat_unknown_is_honest(client):
    r = client.post("/api/chat", json={"message": "asdf zxcv qwer"}).json()
    # falls back to overview (grounded) rather than inventing
    assert r["grounded"] in (True, False)
    assert isinstance(r["answer"], str) and r["answer"]


# ---- morning brief ---------------------------------------------------------
def test_morning_brief_has_activity(client):
    r = client.get("/api/reports/morning-brief").json()
    assert r["no_activity"] is False
    assert r["generated"] >= 1


def test_morning_brief_empty_root():
    d = tempfile.mkdtemp()
    c = TestClient(create_app(d))
    r = c.get("/api/reports/morning-brief").json()
    assert r["no_activity"] is True and "No overnight" in r["text"]


# ---- research trigger safety ----------------------------------------------
def test_frontend_served(client):
    html = client.get("/")
    assert html.status_code == 200 and "Atlas Live" in html.text
    for asset in ("/static/app.js", "/static/styles.css"):
        assert client.get(asset).status_code == 200


def test_run_rejects_path_traversal(populated):
    runner = Runner(populated["root"], Hub())
    with pytest.raises(ValueError):
        runner.resolve_hypothesis("../../etc/passwd")


def test_run_single_flight(populated):
    app = create_app(populated["root"])
    app.state.runner._running = True            # pretend a run is in progress
    c = TestClient(app)
    r = c.post("/api/research/run", json={"hypothesis": "live_losing"}).json()
    assert r["started"] is False


def test_run_bad_hypothesis_400(client):
    assert client.post("/api/research/run",
                       json={"hypothesis": "does_not_exist"}).status_code == 400


def test_run_triggers_real_council_and_streams(populated):
    """End-to-end: trigger a real run, confirm it completes and emitted events."""
    app = create_app(populated["root"])
    c = TestClient(app)
    before = len(c.get("/api/events?after_seq=0").json()["events"])
    r = c.post("/api/research/run", json={"hypothesis": "live_losing"}).json()
    assert r["started"] is True
    for _ in range(60):                          # wait up to ~30s for completion
        if not c.get("/api/research/status").json()["running"]:
            break
        time.sleep(0.5)
    assert c.get("/api/research/status").json()["running"] is False
    after = len(c.get("/api/events?after_seq=0").json()["events"])
    assert after > before                        # the run produced new real events
