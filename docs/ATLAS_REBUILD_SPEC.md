# Project Atlas — Rebuild Specification (for Codex / any coding agent)

This document is a complete, self-contained brief to **rebuild Project Atlas from
scratch**. Hand it to a coding agent (Codex, Claude Code, etc.) as the source of
truth. It describes what Atlas is, its non-negotiable principles, the full module
map, the data model, every subsystem's contract, the build order, and the tests
that prove each piece. Build in the numbered order; each milestone ends green.

Reference implementation: `mondemashigo-tech/Project-Atlas` — 87 Python modules,
140 tests. Python 3.11+. Core deps: `pandas`, `numpy`, `pyyaml`, `pytest`.
Optional: `anthropic` (LLM features), `fastapi`+`uvicorn` (web app).

---

## 1. What Atlas is

Atlas is an **AI research laboratory for trading strategies**. It rigorously
tests whether a strategy/concept has a genuine edge **before any capital is
risked**. It generates its own strategies, sources ideas from the web, and judges
everything the same ruthless way — with pre-registration, out-of-sample budgets,
Monte-Carlo, walk-forward, and a graveyard for failures. A trading bot is a
future *execution-only* consumer that reads approved strategies; Atlas never
trades.

**Mental model:** a parent research system (council of agents + memory + registry
"airlock") wrapping a deterministic FX research engine. Humans gate every
capital-bearing step.

## 2. Non-negotiable principles

1. **SQLite is the source of truth.** A generated Obsidian-style Markdown vault
   mirrors it; the DB is never derived from Markdown.
2. **Deterministic core, generative edges.** Backtester/metrics/statistician/
   risk/portfolio are pure code that produce numbers. Scientist/Skeptic/
   Librarian/Reporter/Architect/Scout/Inventor are LLM/hybrid and must **never
   emit a number** — they interpret, critique, narrate.
3. **Pre-registration.** A hypothesis is frozen (content-hashed) at SPECIFIED
   before testing; rule drift is detected by hash mismatch.
4. **Nothing reaches capital without explicit human approval** — even at max
   autonomy. Capital transitions are gated behind a human token.
5. **Never fabricate results.** No invented backtests, verdicts, agent activity,
   or progress percentages. If data is missing, say so.
6. **Governance is the p-hacking guard.** Out-of-sample look budget +
   multiple-testing ledger + graveyard make open-ended generation honest.
7. **Additive migrations only.** Never drop/alter existing tables or data.

## 3. Repository layout (package `atlas/`)

```
atlas/
  __init__.py  __main__.py        # `python -m atlas`
  service.py                      # run_experiment / hypothesis_trades / regime_report
  snapshots.py                    # dataset snapshotting (provenance)
  schemas/models.py               # all dataclasses + id/hash/time helpers
  memory/store.py                 # MemoryStore: SQLite + Markdown vault mirror
  registry/                       # registry.py (airlock FSM), consumer.py (BotStub)
  risk/                           # policy.py (RiskPolicy), manager.py (RiskManager agent)
  portfolio/portfolio.py          # PortfolioBuilder + analytics
  governance/ledger.py            # OOSBudget, budget_status
  agents/                         # base, skeptic, statistician, historian, reporter,
                                  #   architect, librarian, scientist, inventor
  kernel/orchestrator.py          # the 7-layer decision ladder
  lab/                            # loop.py (autonomy loop), decay.py (monitoring)
  events/                         # model.py (Event + taxonomy), bus.py (EventBus)
  scout/                          # fetch, extract, llm, build, discover, scout
  research/fx/                    # the deterministic FX engine (see §7)
  interfaces/                     # cli.py, dashboard.py, dashboard_server.py
  live/                           # Atlas Live web app (see §11)
```

## 4. Data model (`atlas/schemas/models.py`)

Helpers: `new_id(prefix)` → `f"{prefix}-{uuid4().hex[:12]}"`; `utcnow_iso()`;
`content_hash(obj)` → stable sha256 of JSON-canonical form; `ATLAS_ENGINE_VERSION`.

Dataclasses (all with `to_dict`/`from_dict`):

- **Hypothesis** — `id, version, domain, title, markets, timeframes{bias?,entry},
  spec(rules), success_criteria, failure_criteria, data_split{in_sample,
  out_sample}, session?, filters?, risk_rules, directional_bias, status,
  preregistration_hash, created_at`. Methods: `compute_prereg_hash()` (hashes a
  fixed set of identity fields incl. strategy rule blocks + composed
  features/entry_long/entry_short), `freeze()` (sets hash, status SPECIFIED,
  idempotent), `validate()`, `from_fx_config(cfg)` (maps an FX YAML to schema).
  Statuses: DRAFT→SPECIFIED→…→GRAVEYARD.
- **DataSnapshot** — `id, source, symbols, timeframe, row_count, content_hash,
  date_range, created_at`. Immutable provenance of the exact data tested.
- **ExperimentRecord** (immutable) — `id, hypothesis_id, hypothesis_version,
  engine_version, data_snapshot_id, window, metrics(dict), verdict, monte_carlo,
  created_at`. Verdicts: PASS / REJECT / INCONCLUSIVE / NO_TRADES.
- **DecisionRecord** — `task_id, agent, phase, input_summary, evidence, decision,
  confidence, next_action, created_at`. One per council layer.
- **StrategyRecord** — registry entry: `strategy_id, hypothesis_id, version,
  experiment_ids, spec, status, allocation, risk_limits, approvals[], created_at`.
  Lifecycle FSM: candidate→paper→micro_live→live→retired; capital-bearing statuses
  {paper?,micro_live,live} require human approval to enter.
- **KnowledgeNote** — `id, title, topic_tags[], summary, source, lesson?`.

## 5. Memory store (`atlas/memory/store.py`)

`MemoryStore(root)` opens `<root>/atlas.db` (sqlite3, `row_factory=Row`) and
creates tables idempotently. Tables: `hypotheses, experiments, decisions,
knowledge, snapshots, oos_tests, graveyard, policy, events, conversations`
(schemas in §5.1). Also writes a Markdown mirror under `<root>/vault/`.

Key methods: write/get hypothesis; write/get/list experiments; write/list
decisions; write/list knowledge; write/get snapshot(+by hash); record_oos_test /
oos_test_count; bury / list_graveyard; set_policy / get_policy;
find_hypotheses_by_prereg; counts; decision_tally; write_event /
list_events(after_seq, filters) / latest_event_seq; write_conversation /
get_conversation.

### 5.1 SQLite schema (create idempotently, additive only)

```sql
hypotheses(id PK, version, title, status, preregistration_hash, json, created_at)
experiments(id PK, hypothesis_id, window, verdict, engine_version, json, created_at)
decisions(id AUTOINCREMENT PK, task_id, agent, phase, decision, json, created_at)
knowledge(id PK, title, tags, json, created_at)
snapshots(id PK, source, content_hash, json, created_at)
oos_tests(id AUTOINCREMENT PK, snapshot_id, window, hypothesis_id, prereg_hash, at)
graveyard(hypothesis_id PK, title, reason, at)
policy(key PK, json, updated_at, updated_by)
events(seq AUTOINCREMENT PK, event_id UNIQUE, event_type, timestamp_utc, agent_id,
       agent_name, task_id, cycle_id, hypothesis_id, experiment_id, strategy_id,
       severity, status, title, summary, evidence_refs, progress_current,
       progress_total, metadata, source_module, is_historical, created_at)
  + INDEX(task_id), INDEX(event_type)
conversations(id PK, created_at, transcript_source, routed_agent, user_message,
              answer, citations, records)
```

## 6. The FX research engine (`atlas/research/fx/`) — deterministic core

- **data.py** — load OHLC CSV → tz-aware DataFrame; `resample(df, timeframe)`
  (resolution-agnostic, no look-ahead). **histdata.py** — HistData EST→UTC
  importer. **datasources.py** — external context (carry/news) loaders.
- **indicators.py** — `ema, atr, rsi, swing_low, swing_high` (pure, vectorised).
- **features.py** — composable feature engine: a registry of built-in indicators
  (ema/sma/rsi/atr/rstd/zscore/roc/slope/bb_upper/bb_lower/donchian_*) **plus an
  invented-indicator formula DSL**. `eval_formula(node, df, feats)` walks a JSON
  tree dispatching only to a whitelist of primitives (add/sub/mul/div/neg/abs/
  min/max/clip/sma/rstd/rmin/rmax/rsum/ema/diff/shift/pct_change/zscore) — **no
  eval/exec, no imports, no attribute access**. `build_features(df, specs)` builds
  named series in order; later features may reference earlier ones.
- **rules.py** — composable boolean grammar over features: `{lhs,cmp,rhs}` with
  cmp in `<,<=,>,>=,==,!=,cross_above,cross_below`; `{all:[…]}/{any:[…]}/{not:…}`.
  `evaluate(rule, df, feats)`→bool Series; `referenced_names(rule)`. Same
  whitelist discipline; look-ahead-safe (reads only current/prior bar).
- **strategies/** — `base.Strategy` (registry + `create(cfg)`, `prepare`,
  `signal_at(i)->Signal|None`). Templates: `trend_continuation, mean_reversion,
  breakout, orb`, and **`composed`** (assembles features + entry_long/entry_short
  rules + session + ATR/swing risk — the template Atlas invents into). A
  `Signal(direction, entry, stop, target, reason)`.
- **backtester.py** — event-driven walk over entry bars; fills at next bar open
  with modelled spread+commission; resolves stop/target bar-by-bar (stop-first on
  ambiguous bars); one position/symbol; per-day trade cap; **no look-ahead**
  (`signal_at(i)` never sees `i+1`). Returns `Trade[]` (R-unit P/L after costs).
- **metrics.py** — trades→metrics (trades, profit_factor, expectancy_r, win rate,
  R stats); `judge(metrics, criteria)`→verdict (NO_TRADES if 0 trades).
- **montecarlo.py** — bootstrap + trade-order shuffle → P(total<0), expectancy
  bands. **walkforward.py**, **splits.py** — in/out-of-sample & rolling windows.
- **optimizer.py**, **paramgrid.py** (`expand(cfg, grid)`), **regime.py**,
  **filters.py** (carry/news gates), **report.py**, **charts.py**, **journal.py**,
  **runner.py**, **config.py** (`load(path)` validates required keys), **cli.py**
  (engine-level CLI incl. MT5 export/mt5check).

## 7. Service layer (`atlas/service.py`)

`run_experiment(hyp_path, root, window, mc, data_utc_offset)`: load+freeze
hypothesis → snapshot data (provenance) → backtest → compute metrics + Monte
Carlo → judge verdict → persist ExperimentRecord → record OOS test. Returns
`(hypothesis, experiment_record, verdict)`. Also `hypothesis_trades`,
`regime_report`.

## 8. Agents / council (`atlas/agents/`)

Each agent: `name`, `nature` (deterministic|hybrid|llm), `run(ctx)->DecisionRecord`.
`AgentContext(task_id, hypothesis, experiment, verdict, extras)`. Optional
`narrator` (LLM callable) may enrich text but never changes rulings/numbers.

- **Statistician** (deterministic) — significance, expectancy, bootstrap bands;
  decisions: significant_positive/negative, not_significant, insufficient_sample,
  no_data.
- **Skeptic** (hybrid, hard veto) — rejects losing/fragile edges (PF<1,
  P(total<0) high, tiny sample); decisions: approve/veto/reject.
- **Historian** — novelty via prereg hash (has this exact idea been tested?).
- **Reporter** — writes the memo (and morning brief) from the recorded chain.
- **Architect** — system-health observation for the dashboard.
- **Librarian** — ingests text → tagged KnowledgeNote (topic taxonomy).
- **Scientist** — proposes param-grid variants + prioritises by novelty/simplicity.
- **Inventor** — designs **new composed strategies** (mixes indicators, writes
  invented formula indicators). Deterministic archetype library + optional LLM
  generator; every candidate is **dry-run through the real engine** before it's
  accepted (the whitelist is the safety gate). Never executes code.
- **RiskManager** (`atlas/risk/`, deterministic) — hard gate vs RiskPolicy
  (max_drawdown_r, max_daily_loss_r, risk_per_trade_max, min_trades).

## 9. Orchestrator — the 7-layer ladder (`atlas/kernel/orchestrator.py`)

`Orchestrator(root).run(hyp_path, window, narrator, risk_policy, data_utc_offset,
bus=None)`. Layers (a layer may not be skipped; halt on first failure):

1. data_integrity (snapshot rows>0) 2. rule_validity (frozen+valid) 3.
backtest_validity (engine-stamped experiment exists) 4. statistical_validity
(Statistician quantifies → Skeptic judges; reject ⇒ auto-bury) 5. risk_validity
(RiskManager) 6. portfolio_validity 7. deployment_validity (**human-gated** — auto
registers a NON-capital candidate only). Governance check (OOS budget) sits
before advancement. Reporter writes the memo. Returns
`{hypothesis, experiment, verdict, decisions, advanced, reached_layer,
candidate_id, halt_reason, memo}`. **Emits typed events to `bus` if given
(default no-op); behaviour identical without a bus.**

## 10. Governance, registry, autonomy

- **governance/ledger.py** — `OOSBudget(max_tests)`, `budget_status(store,
  snapshot, window, budget)` → burned?/count/remaining. The multiple-testing
  guard.
- **registry/registry.py** — the airlock. `add_candidate`, `transition`
  (capital-bearing targets require an approval token), `promote/retire`,
  `kill_switch/reenable`, `list`, `export_json` (what a future bot reads).
  `consumer.py` `BotStub` executes **nothing**.
- **lab/loop.py** — `ResearchLoop(root, autonomy_level≤4, …)`: Scientist proposes
  → orchestrator tests → buries failures; never promotes to capital. `decay.py`
  monitors live strategies.

## 11. Event spine + Atlas Live web app

- **events/model.py** — typed `Event` (fields incl. seq cursor, event_type from a
  fixed taxonomy, agent, ids, severity, status, evidence_refs, progress
  *nullable→indeterminate*, metadata, is_historical). Validates unknown
  type/severity. **events/bus.py** — `EventBus(store)`: publish (persist→assign
  seq→stream), subscribe/unsubscribe, get_events(after_seq), replay(task_id).
  `NullBus` = no-op default so the engine is unchanged without a bus.
- **live/** (FastAPI + SSE + self-contained vanilla-JS SPA, no build step):
  `app.py` (routes), `services.py` (read helpers, store-per-request),
  `roster.py` (real council + state derived from events; idle unless recent
  started event), `runner.py` (background council run + **run_idea**: Scout a
  plain-English idea then test it), `hub.py` (SQLite-free SSE fan-out),
  `chat.py` (grounded answers built from records + citations; LLM only phrases,
  never invents), `brief.py` (morning brief; honest no-activity path), `web/`
  (index.html/styles.css/app.js). Endpoints: overview, health, agents(+detail/
  query), events(+SSE stream honouring Last-Event-ID), experiments(+detail),
  hypotheses(list+detail), graveyard/registry/knowledge/governance, morning-brief,
  chat, research/run (existing hypothesis), research/idea (free-text→Scout→test).
  **Read-mostly; local-only bind; never capital; no shell exec.**

## 12. Scout (`atlas/scout/`)

`fetch` (URL/file/raw text→text), `extract` (heuristic rule extraction),
`llm.py` (`anthropic_extractor` — LLM reads any article into {template,params},
validated against template/param allowlists), `build` (skeleton→hypothesis),
`discover.py` (Anthropic web-search server tool finds forex articles; FX-only
gate), `scout.py` (`Scout.scout / scout_and_test / discover`). Turns outside
ideas into pre-registered hypotheses tested the same way.

## 13. CLI (`atlas/interfaces/cli.py`) — `python -m atlas <cmd>`

`run, council, experiments, registry, bot, governance, graveyard, architect,
dashboard(--serve), loop, monitor, scout, discover, invent, ingest, propose,
portfolio, regime, data(import/resample/snapshot/mt5check/export), live`.
Global `--root`. `dashboard --serve` uses the hardened threaded server
(`dashboard_server.py`) that swallows benign client disconnects.

## 14. Build order (each milestone ends with passing tests)

1. **Schemas + MemoryStore** (tables, Markdown mirror) — round-trip tests.
2. **FX engine**: data/indicators/backtester/metrics + trend_continuation — a
   synthetic-data backtest produces well-formed trades; no look-ahead test.
3. **service.run_experiment** + snapshots — provenance + verdict.
4. **Agents + Orchestrator ladder** — invariant: never auto-deploy.
5. **Risk + Portfolio gates.**
6. **Memory governance**: OOS budget, graveyard, policy.
7. **Full council** (Historian/Statistician/Skeptic/Reporter) on real-ish data.
8. **Knowledge ingestion + Scientist idea generation + autonomy loop.**
9. **Composable engine (features+rules+composed) + Inventor** — invented-indicator
   correctness vs hand-computed; safety tests reject `__import__`/unknown kinds.
10. **Scout** (fetch/extract/llm/build/discover) — end-to-end from a local file.
11. **Event spine** — real council run emits ordered events; NullBus emits none.
12. **Atlas Live** — API + SSE replay + grounded chat + brief + idea-run; verify
    under a real server.

## 15. Testing expectations

~140 tests, all offline (no live API/network). Patterns: build a temp root, write
a synthetic OHLC CSV under `datasets/`, write a hypothesis YAML, run the
orchestrator, assert on decisions/verdict/events. LLM features are tested with
**stubbed** extractors/generators — never a real API call. Safety tests must
prove: no look-ahead, invented indicators can't execute code, engine emits no
events without a bus, nothing auto-promotes to capital.

## 16. Coding conventions

Small pure functions; dataclasses for records; config-as-data (strategies are
YAML, not code); every LLM call has a deterministic fallback; honest failure
states over fabrication. Author commits as the project owner; **never** embed
model identifiers in code/commits.

---

*Rebuild in the numbered order. When a milestone's tests are green, move on. The
whole point of Atlas is that it tells the truth about whether an edge is real —
so build the judge (engine + ladder + governance) before the generators
(Scientist/Inventor/Scout), and keep humans on every capital gate.*
