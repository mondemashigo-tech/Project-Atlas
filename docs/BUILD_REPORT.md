# Atlas — Build Report

A checkable record of everything built on the `feature/atlas-live` branch, with
the exact commands to verify each part yourself. Repo:
`mondemashigo-tech/Project-Atlas`. Branch: `feature/atlas-live`.

## How to get it and run the checks

```
git fetch origin
git checkout feature/atlas-live
git pull origin feature/atlas-live
py -m pip install fastapi "uvicorn[standard]"      # only needed for the web app
py -m pytest -q                                    # expect: 166 passed
py -m atlas live                                   # http://127.0.0.1:8800
```

**Headline number to confirm:** `py -m pytest -q` → **166 passed**. If that
passes, every claim below is backed by a test.

## Commits on this branch (newest first)

| Commit | What |
|---|---|
| `752ead7` | Executor loop gated behind research verdict + Pulse arm/replay |
| `015f05c` | MT5 broker adapter + Atlas Pulse cockpit |
| `ee6e645` | Execution boundary: safety spine (modes + capital gate + paper broker) |
| `c48c85e` | BOS + Retracement strategy template (from your video spec) |
| `6ba8a7d` | Codex rebuild specification |
| `1a6c2b2` | Paste-an-idea flow + hypothesis picker + chat listing |
| `e4eabd6` | Atlas Live MVP: web app, SSE console, chamber, chat, voice, brief |
| `170688a` | Typed event model, bus, council instrumentation |
| `9195ae5` | Protect current system + hardened dashboard server |

`git log --oneline origin/main..HEAD` reproduces this list.

---

## 1. Atlas Live web app (M0–M8)

**What it is:** an inspectable web UI over the research engine — Council Chamber,
live Console, Experiments, Registry, Graveyard, Knowledge, Governance, Morning
Brief, grounded chat, read-only voice.

**Files:** `atlas/live/` (app.py, services.py, roster.py, runner.py, hub.py,
chat.py, brief.py, pulse.py, web/{index.html,styles.css,app.js});
`atlas/events/` (model.py, bus.py); `atlas/interfaces/dashboard_server.py`.

**Check it:**
- `py -m atlas live` → open http://127.0.0.1:8800. Click through every tab.
- Council Chamber shows the real 10-actor council, all **idle** (no fake activity).
- Trigger a run (or paste an idea) → the Console streams real events; refresh the
  browser mid-run → history replays (nothing lost).
- Ask in chat: "what happened overnight?", "list the experiments", "why was
  EXP-… rejected?" → answers cite real record ids.
- Tests: `py -m pytest tests/test_live_api.py tests/test_events.py -q` (30 tests).

**Honest limits:** the standalone CLI/nightly runs don't emit live events yet
(only the web app's own runs do); they still write records the UI reads.

## 2. Paste-an-idea flow

**What it is:** the Chamber's "Test a new idea" box — paste plain English, the
Scout formalises it into a hypothesis and the council tests it.

**Check it:** Chamber → "Test a new idea" → paste a strategy description → watch
the console. Or the dropdown "Run an existing hypothesis". Tests inside
`test_live_api.py` (`test_idea_run_starts_and_completes`, `test_hypotheses_list`).

**Honest limit:** without `ANTHROPIC_API_KEY` set, extraction uses a keyword
heuristic — nuanced ideas map approximately. With the key, the LLM reader is far
better.

## 3. BOS + Retracement strategy (your video spec)

**What it is:** a faithful, stateful implementation of the Break-of-Structure +
Retracement strategy — genuine break vs liquidity sweep, retest, confirmation,
entry — not a plain breakout.

**Files:** `atlas/research/fx/strategies/bos_retrace.py`;
`hypotheses/bos_retrace_v0_1.yaml`.

**Check it (on your laptop, real data):**
```
py -m atlas council hypotheses\bos_retrace_v0_1.yaml --window out_sample --data-utc-offset 3
```
Tests: `py -m pytest tests/test_bos_retrace.py -q` (5 tests: builds, trades, no
look-ahead, distinct pre-registration, shipped YAML loads).

**Honest note:** it's selective (needs displacement + retest + confirmation), so
it trades rarely; on a small sample the council correctly says INCONCLUSIVE. Its
real verdict is whatever your data says.

## 4. Execution boundary — safety spine

**What it is:** the controls that make sure money can't move without permission.

**Files:** `atlas/execution/broker.py` (AccountMode, BrokerAdapter, typed
records), `gate.py` (CapitalGate + persistent kill switch), `paper.py`
(PaperBroker).

**Check it:** `py -m pytest tests/test_execution.py -q` (8 tests). Key guarantees
proven:
- Only `MICRO_LIVE`/`LIVE` modes can ever send an order.
- The gate blocks live orders unless live is explicitly enabled.
- The kill switch blocks **everything** and **survives restart** (it's a file).
- PaperBroker cannot even be constructed in a live mode.

## 5. MT5 broker adapter + Atlas Pulse cockpit

**What it is:** the real MetaTrader 5 connection (your OctaFX terminal) behind the
same gate, plus the live cockpit screen.

**Files:** `atlas/execution/mt5_broker.py`; `atlas/live/pulse.py`; Pulse view in
`web/app.js`; endpoints in `app.py`.

**Check it:**
- Cockpit: `py -m atlas live` → **Pulse** tab (shows OBSERVE / PaperBroker / kill
  switch — safe by default).
- Real MT5 data (laptop, terminal open on demo): `$env:ATLAS_BROKER="mt5"` then
  `py -m atlas live` → Pulse shows your real account/prices, still OBSERVE (no
  orders).
- Tests: `py -m pytest tests/test_mt5_and_pulse.py -q` (6 tests, MT5 stubbed):
  OBSERVE reads data but never sends; LIVE blocked without enable and stopped by
  the kill switch; unknown broker positions block trading.

**Credentials:** set via env only — `ATLAS_MT5_LOGIN`, `ATLAS_MT5_PASSWORD`,
`ATLAS_MT5_SERVER`. Never put them in chat or code.

## 6. Executor loop — gated behind the research verdict

**What it is:** turns an **approved** strategy into paper/live activity, and
**refuses to trade anything that hasn't earned it**.

**Files:** `atlas/execution/executor.py` (research_clearance + Executor),
`feed.py` (ReplayFeed + MT5Feed); Pulse `arm`/`replay`.

**Check it:**
- In the Pulse tab, "arm a strategy": type `bos_retrace_v0_1` → **Check
  clearance**. Until BOS passes the council on your data, it shows **BLOCKED**.
- "Paper-trade on history" runs it over your `datasets/` CSVs — a REJECTed/
  untested strategy generates signals but **0 fills** (observed, not traded).
- Proven live: `demo_mr` (a REJECTed strategy) arms BLOCKED → 1,496 signals
  observed, **0 paper trades**.
- Tests: `py -m pytest tests/test_executor.py -q` (7 tests): clearance
  untested/reject/pass/candidate; blocks uncleared; paper-trades cleared; never
  fills in OBSERVE.

**The gate, in one sentence:** a strategy is cleared to trade only if a registry
candidate exists for it (it passed the whole ladder) or its latest experiment
verdict is PASS — otherwise it is observed, never traded.

## 7. Codex rebuild spec

`docs/ATLAS_REBUILD_SPEC.md` — the complete brief to rebuild Atlas elsewhere.

## Documentation index (`docs/atlas_live/` + `docs/`)

`BUILD_REPORT.md` (this), `ATLAS_REBUILD_SPEC.md`, and under `atlas_live/`:
`current_system_baseline.md`, `event_model.md`, `architecture.md`, `api.md`,
`frontend.md`, `voice.md`, `security.md`, `testing.md`, `deployment.md`,
`jarvis_integration.md`, `README.md`, `ADR-001-web-application-architecture.md`,
`ADR-002-voice-architecture.md`.

---

## What is NOT done (so you can hold me to it)

- **No live trading.** There is no path to a real order yet — MICRO_LIVE/LIVE are
  blocked behind the gate, and nothing in the UI can enable them. This is
  deliberate.
- **No real-time live loop yet.** The executor runs on replay/history and via the
  Pulse buttons. A background scheduler that ticks every M5 bar against live MT5
  data during the London session is the next build.
- **Standalone CLI / nightly runs don't emit live events** (only web-app runs do).
- **The vNext spec's bigger items are not built:** durable jobs/checkpoints,
  knowledge graph, similarity search, the full data catalogue, blind/revealed
  agent review, the per-agent decision JSON contract, and the promotion wizard.
- **Everything is on `feature/atlas-live`**, not merged to `main` — your normal
  `git pull` on `main` won't see it until we merge.

## Bottom line

`py -m pytest -q` → **166 passed**. The research lab, the web app, the BOS
strategy, and a fully-gated execution boundary (paper only, kill switch, verdict
gate) are built and tested. Real capital remains untouchable until we
deliberately build and enable the live path.
