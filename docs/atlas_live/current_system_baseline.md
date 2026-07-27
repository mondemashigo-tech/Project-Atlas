# Atlas — Current System Baseline (pre–Atlas Live)

Snapshot of the system **before** the Atlas Live web application, captured by
inspecting the repository (not inferred). This is the ground truth every later
Atlas Live milestone builds on and must not regress.

- **Branch at capture:** `feature/atlas-live` (cut from `main`)
- **Base commit:** `f0ce85b` (main)
- **Test status:** `pytest -q` → **107 passed** (engine/backend only; no UI/API/event tests existed).
- **Platform of record:** cross-platform Python; runs on the user's Windows laptop (`C:\Users\monde\Atlas-Lab`), pulling from `mondemashigo-tech/Project-Atlas`.

---

## Application entry points

- **CLI:** `python -m atlas <command>` → `atlas/interfaces/cli.py`.
  Subcommands: `run, experiments, registry, bot, governance, graveyard,
  architect, dashboard, loop, monitor, scout, discover, invent, ingest, propose,
  council, portfolio, regime, data`.
- **Nightly automation:** `scripts/atlas_nightly.ps1` (Windows Task Scheduler)
  shells out to the same CLI commands. It does **not** emit events or notify.
- No web framework, no server process beyond the ad-hoc dashboard server.

## Current dashboard implementation

- **Renderer:** `atlas/interfaces/dashboard.py` → `render(root, refresh_secs)`
  returns one self-contained HTML string (GitHub-dark CSS; tabs: Overview,
  Experiments, Graveyard, Registry, Governance, Knowledge). No CSS/JS files, no
  build step, no client state. Client refresh = `<meta http-equiv="refresh">`
  (`dashboard.py:132`).
- **Serving (original):** inline in `cli.py` `_dashboard` — single-threaded
  `http.server.HTTPServer`, `do_GET` re-rendered the whole page per request and
  wrote it with no guard. **No SSE, no WebSocket, no partial updates.**
- **Serving (as of M0):** replaced by `atlas/interfaces/dashboard_server.py` —
  `ThreadingHTTPServer`, guarded response write, `handle_error` swallows the
  connection-reset family. Same HTML output; now disconnect-safe. Static-file
  mode (`dashboard` without `--serve`) is unchanged.

## Database (source of truth)

- **SQLite** via `atlas/memory/store.py` (`MemoryStore(root)`), DB under the run
  root. The Obsidian markdown **vault is a generated mirror**, never the DB.
- **Schema** (`store.py:31-52`), 8 tables:
  - `hypotheses(id, version, title, status, preregistration_hash, json, created_at)`
  - `experiments(id, hypothesis_id, window, verdict, engine_version, json, created_at)`
  - `decisions(id AUTOINCREMENT, task_id, agent, phase, decision, json, created_at)`
  - `knowledge(id, title, tags, json, created_at)`
  - `snapshots(id, source, content_hash, json, created_at)`
  - `oos_tests(id AUTOINCREMENT, snapshot_id, window, hypothesis_id, prereg_hash, at)`
  - `graveyard(hypothesis_id, title, reason, at)`
  - `policy(key, json, updated_at, updated_by)`

## Existing "event-like" objects

- The **`decisions` table** is the closest thing to an event log: the
  orchestrator writes one row per council layer (`agent, phase, decision, json`).
  It is a **per-decision audit trail, not a typed real-time event stream** — no
  event-type taxonomy, no severity, no streaming, no progress fields.
- `DecisionRecord` (`atlas/schemas/models.py`) is the in-memory shape behind it.
- **A typed real-time event model does not exist** and is the subject of Atlas
  Live milestone M1.

## Council agents (actual)

Agent classes in `atlas/agents/` (8): **Architect, Historian, Inventor,
Librarian, Reporter, Scientist, Skeptic, Statistician** (+ `base.Agent`).
Additional council actors: **Scout** (`atlas/scout/scout.py`) and **RiskManager**
(`atlas/risk/`). **Total distinct actors: 10 — not 7.**

Orchestrator ladder (`atlas/kernel/orchestrator.py`) invokes, per run:
Historian (novelty) → Statistician (quantify) → Skeptic (judge) → RiskManager
(risk gate) → Reporter (memo). Scientist/Inventor generate upstream; Librarian
ingests; Scout sources; Architect observes for the dashboard.

> **Product mismatch to resolve:** the Atlas Live brief assumes "seven council
> agents." The repo has the set above. The "7" appears to originate in the
> design volumes, which are **not in this repo** and cannot be verified here.
> Decision deferred to the user (audit question Q-4).

## Execution model

- **Fully synchronous.** `orchestrator.run()` → `service.run_experiment()` →
  `backtester.run()` inline. No task queue, no workers.
- **No progress callbacks** exist in `atlas/research/fx/backtester.py`; real
  percentage progress is not currently obtainable. A council run completes in
  seconds, so **the system is idle except during an active run** — a defining
  constraint for any "live" UI.

## Scout functions

`atlas/scout/`: `fetch.py` (URL/file → text), `extract.py` (heuristic rule
extraction), `llm.py` (LLM extractor), `discover.py` (Anthropic web-search URL
discovery + FX gate), `build.py` (skeletons → hypothesis), `scout.py`
(`Scout.scout/scout_and_test/discover`). CLI: `scout`, `discover`.

## Reports & vault structure

- `atlas/agents/reporter.py` writes memos to `<root>/vault/memos/`; loop/cycle
  reports to `<root>/vault/reports/`; knowledge to `<root>/vault/knowledge/`.
  Nightly logs to `<root>/vault/logs/`. All generated from SQLite; markdown is a
  mirror.

## Test coverage (at baseline)

- **107 tests**, all engine/backend: `test_scout`, `test_compose`,
  `test_inventor`, plus milestone tests for memory, orchestrator, risk,
  portfolio, montecarlo, etc. **No API/UI/event tests** (nothing to test yet).
- **M0 adds** `tests/test_dashboard_server.py` (3 tests: serves HTML, survives a
  mid-request client disconnect, `handle_error` swallows benign resets).

## Known errors / limitations at baseline

- **`WinError 10053` / `ConnectionAbortedError`:** diagnosed as a **benign client
  disconnect** made frequent by the `<meta refresh>` design and surfaced as a
  non-fatal console traceback (unguarded `wfile.write` on a single-threaded
  server). **Fixed in M0** by `dashboard_server.py`. The Atlas Live SSE design
  removes the root cause (no full-page refresh churn).
- No live view, no event stream, no conversation, no voice — the scope of Atlas
  Live.
- No authentication (local `127.0.0.1` only).
- Dashboard re-renders the whole page and scans the DB on every request (fine at
  current data sizes; the API will paginate).

## Fallback guarantee

The existing dashboard remains available throughout Atlas Live via
`python -m atlas dashboard --serve` (now hardened) and static
`python -m atlas dashboard`. It will not be removed until the new interface is
proven.
