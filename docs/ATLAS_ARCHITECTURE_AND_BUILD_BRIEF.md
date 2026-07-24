# Project Atlas — Architecture Review & Build Brief

*Source of truth: Atlas Volumes 1–5. This document maps the specification onto a
buildable system and onto the code that already exists in this repository. Where
the volumes conflict or leave gaps, this document calls it out and proposes the
most sensible default — it does not invent a different philosophy.*

Status legend: **[DONE]** already built here · **[PARTIAL]** partly built ·
**[TODO]** not yet built · **[ASSUMPTION]** my inference, labelled as such.

---

## 0. The reframing fact

A working slice of Atlas already exists in `project-atlas/` (this repo). It
implements a large part of the Volume 3 research engine and the Volume 4 package
layout: config-driven hypotheses, an event-driven backtester with costs,
R-unit metrics, PASS/REJECT verdicts against pre-registered criteria,
in/out-of-sample splits, walk-forward analysis, Monte Carlo (bootstrap +
shuffle), a grid optimiser with an overfit-gap flag, an append-only JSONL
research journal, a self-contained tabbed HTML dashboard, and two external data
sources (carry + news filter). 24 tests pass.

Therefore this is **not a greenfield build**. The correct plan is to *extend the
existing engine* toward the multi-agent laboratory — not restart. Restarting
would violate Volume 4's own guardrail ("keep the architecture modular so new
… can be added without rewriting the core").

---

## 1. Atlas system summary

Atlas turns trading ideas into **pre-registered hypotheses**, tests them through
a **validation ladder** (backtest → statistics → out-of-sample → walk-forward →
Monte Carlo → regime → paper → micro-live → portfolio → monitoring →
retirement), and **keeps only what survives**, archiving everything else with the
reason it died. A **council of specialised agents** (some generative, some
deterministic) does the work under one rule: *evidence decides, and the default
verdict is rejection.*

What makes it different from a trading bot:

| Trading bot | Atlas |
|---|---|
| Emits buy/sell signals | Emits verdicts on hypotheses |
| Optimises a strategy | Tries to *disprove* a hypothesis |
| Hides why | Traceable to data + exact rule version |
| Forgets | Institutional memory + hypothesis graveyard |
| One "brain" | Council with structured disagreement |
| Chases the best backtest | Prefers robust-and-moderate over brilliant-and-brittle |
| Deploys on a good result | Deploys only after a ladder of independent tests + human approval |

The first success metric is **clarity, not profit**: can the user see what was
tested, what failed, and why.

---

## 2. Architecture review — components, contradictions, gaps, risks

### 2.1 Core components (from Volumes 2 & 4)

Data layer · Hypothesis layer · Agent layer (council + orchestrator) · Backtest
layer · Validation layer · Risk layer · Portfolio layer · Reporting layer ·
Memory layer (working/research/experiment/graveyard/policy/knowledge). Decisions
flow through a **7-layer hierarchy** (data → rule → backtest → statistical →
risk → portfolio → deployment) that cannot be skipped without a logged waiver.

### 2.2 Contradictions and ambiguities (called out, per your instruction)

1. **Agent naming drift (V1 vs V2).** V1 lists *Hypothesis Generator* and
   *Archivist*; V2 renames them *Scientist* and *Memory Curator*, adds
   *Orchestrator, Historian, Architect, Reporter* (8 → 12 agents).
   **Resolution:** Volume 2 is authoritative on agents (it is the agent volume).
   Use its 12-agent roster; treat V1 names as aliases.

2. **Two repository schemes (V4).** V4 gives *both* a numbered-folder repo
   (`00_Dashboard/ … 14_Docs/`) *and* a Python package layout
   (`atlas/core, atlas/data, …`). These are different organizing axes.
   **Resolution:** the **Python package `atlas/` is the code home** (it is what
   exists and what is testable/importable); the numbered folders, if used at all,
   are top-level *artifact* directories (datasets, reports, logs, docs). Do not
   maintain both as code. **[ASSUMPTION]** the package layout wins.

3. **Multiple, non-aligned phase schemes.** V4 has 8 engineering phases; V5 has
   a 6-stage roadmap *and* 6 autonomy levels (0–5); we internally used "Phases
   1–4." Four numbering systems describe the same journey.
   **Resolution:** one canonical build sequence in §3, cross-referenced to V4
   phases and V5 autonomy levels. Autonomy level is an *operating* property, not
   a build phase — keep them separate.

4. **Spec stack vs pragmatic minimalism.** V4 recommends Poetry/uv, SQLite/
   Postgres, Plotly/Matplotlib, FastAPI. The existing build deliberately uses
   stdlib + pandas/numpy + hand-rolled SVG so it runs on the trading machine's
   bare Python with no heavy deps. **Resolution:** keep the **core dependency-
   light and portable**; add the heavier tools as *optional adapters* (a Postgres
   memory backend, a Plotly report theme) behind interfaces, only when scale
   demands. V4's own goal ("maintainability, modularity") supports this.

5. **"Agents" implies 12 LLMs — but several must be deterministic.** V2/V3
   demand a backtester that is *deterministic and reproducible* and a guardrail
   that *"no agent may invent backtest results."* An LLM Backtester would violate
   both. **Resolution (headline):** split the council by nature —
   - **Deterministic code agents** (never generative): Backtester, Statistician,
     Risk Manager, Portfolio Builder, and the numeric part of the Historian.
     These produce *numbers*.
   - **LLM agents** (generative/interpretive): Scientist, Librarian, Skeptic,
     Reporter, Architect, and the Orchestrator's routing narration.
   - **Hybrid:** Memory Curator (deterministic storage, LLM summarisation).
   This is already how the engine works (metrics/backtest are pure Python). It is
   the most important architectural decision in the whole system.

6. **Data assumptions vs reality.** V3 assumes ~10 years of data, tick data, a
   news calendar, and holiday tables. Reality (just discovered): the live feed is
   an OctaFX demo with ~16 months of M5 and no supplied calendar/rates. **The
   true bottleneck for Atlas is data acquisition, not code.** Flagged again in §7
   and §8.

### 2.3 Missing pieces (gaps to build)

- **The council + orchestrator** (Volume 2) — not built. Only the deterministic
  engine exists.
- **Typed hypothesis schema** (V4 §9) — we validate a YAML dict against core
  keys; there is no typed/immutable object with `id`, `validation_plan`,
  `confidence_score`, `directional_bias`, `news_filter` as first-class fields.
  **[PARTIAL]**
- **Risk & portfolio modules** (V4 §11, V5 §13) — not built as gates; risk lives
  only in the per-hypothesis `risk:` block.
- **Memory beyond the journal** — the journal is experiment+graveyard memory in
  one JSONL. Research/knowledge/policy/pattern memory layers are absent. **[PARTIAL]**
- **Knowledge ingestion** (V5 §8) — reading books/papers into tagged knowledge —
  not built.
- **Regime testing, paper-trading, micro-live, decay monitoring** ladder stages —
  not built.
- **Multiple-testing / false-discovery control** — the loop can "use up" the OOS
  set by testing many variants; no OOS budget or correction exists yet. **Serious.**
- **Immutable experiment IDs, engine-version stamping, replay** (V4 §13) — partial
  (journal has a config fingerprint; no engine-version snapshot or replay).

### 2.4 Top design risks (expanded in §8)

Overfitting-by-council (many hypotheses → false positives); LLM agents fabricating
or laundering numbers; data thinness masquerading as "no edge everywhere";
premature autonomy; memory bloat/noise; and stack sprawl making the system
unmaintainable.

---

## 3. Build plan (phased, dependency-ordered)

Principle from V1/V4: build the **honest engine first**, add intelligence on top,
add autonomy last, and never let a later layer bypass an earlier one.

### Phase A — Engine hardening *(mostly [DONE]; finish the edges)*
Goal: the deterministic research engine is trustworthy and reproducible.
- [DONE] backtester, metrics (R units), verdicts, in/out-of-sample split,
  walk-forward, Monte Carlo, optimiser, journal, HTML dashboard, carry+news.
- [TODO] **typed, immutable hypothesis schema** with `id`, `version`,
  `validation_plan`, `confidence_score`, `news_filter`, `directional_bias`
  (V4 §9); refuse to run if mandatory fields missing.
- [TODO] **engine-version + data-snapshot stamping** on every run; **replay**
  from an experiment ID (V4 §13, §17 acceptance criteria).
- [TODO] **regime tagging** of trades (trend/range/high-vol/low-vol) so
  regime-testing (V3 §12) is possible.
- Depends on: nothing new. **Do first** — everything else reads these outputs.

### Phase B — Data foundation *(the real bottleneck)*
Goal: enough clean, multi-year, timezone-correct data to make verdicts mean
something.
- [TODO] acquire deep history (HistData/Dukascopy multi-year M1→resample, or a
  paid feed) — see §7.
- [TODO] session-calendar + holiday tables; broker-time→UTC normalisation
  (partly [DONE] via `data_utc_offset`).
- [TODO] news calendar + rates as first-class datasets (loaders [DONE]; data [TODO]).
- Depends on: nothing. **Can run in parallel with A.** Blocks any *trusted* verdict.

### Phase C — Risk & portfolio gates
Goal: hard safety gates (V4 §11) and cross-strategy view (V5 §13).
- [TODO] `atlas/risk`: per-trade %, daily/weekly loss, max exposure, correlation
  limit, kill-switch — as a **hard gate**, not advice.
- [TODO] `atlas/portfolio`: correlation matrix, combined equity/drawdown,
  capital-efficiency ranking across surviving hypotheses.
- Depends on: A (needs trade logs + metrics). Precedes any deployment talk.

### Phase D — Memory & governance spine
Goal: partitioned, searchable, un-rewritable memory (V2 §8, V5 §15).
- [PARTIAL→TODO] split memory into working / research / experiment / graveyard /
  policy / knowledge stores behind one `atlas/memory` interface (SQLite default,
  Postgres adapter optional). Journal becomes the experiment+graveyard backend.
- [TODO] **multiple-testing ledger**: count hypotheses tested against each OOS
  set; expose a false-discovery warning; enforce an **OOS budget**.
- Depends on: A. Enables the council to be honest.

### Phase E — The council (orchestrated, mostly deterministic)
Goal: Volume 2 in software, with the deterministic/LLM split from §2.2(5).
- [TODO] `atlas/agents`: a common message schema (V2 §6), an explicit
  **Orchestrator state machine** driving the 7-layer hierarchy, and agent
  contracts (input/output/tools/prohibitions).
- Build order within E: Orchestrator + message bus → wrap existing engine as the
  deterministic agents (Backtester, Statistician, Risk, Portfolio) → add LLM
  agents (Skeptic, Scientist, Librarian, Historian, Reporter) one at a time,
  each behind an interface, each writing a traceable decision record.
- Depends on: A, C, D. **This is where "bot" becomes "lab."**

### Phase F — Knowledge ingestion & idea generation (Autonomy L1–L2)
Goal: V5 §8–§10. Librarian ingests sources → tagged knowledge; Scientist
proposes + prioritises hypotheses; human chooses what to test.
- Depends on: D (knowledge memory), E (agents).

### Phase G — Autonomy loop under governance (Autonomy L3–L5)
Goal: scheduled research cycles (daily/weekly/monthly), decay monitoring,
research reports, sandbox autonomy with human approval gates (V5 §14–§17).
- Depends on: everything. **Last.** Earned, not switched on.

**Keep simple in v1 (per V1 "reliability over flash"):** deterministic engine +
typed schema + memory + one or two LLM agents (Skeptic and Reporter add the most
value first — the Skeptic enforces rigor, the Reporter makes results legible).
**Defer:** full 12-agent autonomy, paper/live execution, knowledge ingestion at
scale, Postgres/FastAPI, until the engine + data + risk are solid.

---

## 4. Technical architecture

### 4.1 Packages (extends the existing `atlas/`)
```
atlas/
  core/         [TODO] types, enums, ids, engine-version, result records
  data/         [DONE] loaders, resample, MT5 export, tz; [TODO] calendar/holidays
  hypotheses/   [PARTIAL] typed schema + validator + versioning (today: config.py)
  strategies/   [DONE] registry + templates (trend_continuation, mean_reversion, breakout)
  backtest/     [DONE] event loop, fills, costs, trade logs (today: backtester.py)
  validation/   [DONE] metrics, walk-forward, monte carlo, verdict, splits, optimizer
  risk/         [TODO] hard gates: per-trade, daily/weekly, exposure, kill-switch
  portfolio/    [TODO] correlation, combined DD, capital allocation
  reporting/    [DONE] text report, SVG charts, HTML dashboard; [TODO] PDF adapter
  memory/       [PARTIAL] journal (JSONL); [TODO] partitioned stores + search
  agents/       [TODO] message schema, orchestrator FSM, agent contracts
  config/       [DONE] loader + validation
  cli/          [DONE] run/wf/mc/opt/html/journal/export/mt5check
```
**[ASSUMPTION]** map V4's numbered folders to: `03_Data→datasets/`,
`08_Reports→reports/`, `12_Logs→logs/`, `14_Docs→docs/`; the rest live *inside*
`atlas/` as packages.

### 4.2 Data flow (unchanged from V4 §6, already realised for the engine)
`data → hypothesis(spec) → orchestrator → backtester → validation → risk →
reporting → memory`. Nothing bypasses this without a logged waiver.

### 4.3 Storage
- Datasets: CSV/Parquet snapshots, versioned (Parquet for scale). **[PARTIAL]** (CSV).
- Experiments/graveyard/knowledge: **SQLite** default (single-file, portable),
  **Postgres** adapter optional. Today: JSONL journal — fine for now, migrate
  behind the `memory` interface.
- Reports: HTML/CSV/JSON under `reports/`. **[DONE]**.

### 4.4 Internal interfaces (not a network API in v1)
Agents talk via **in-process structured messages** (V2 §6 schema) written to the
memory log — not HTTP. FastAPI only if/when a UI or remote control is needed
(defer). Every agent implements `handle(message) -> DecisionRecord`.

### 4.5 Agent orchestration
An explicit **finite state machine** = the 7-layer decision hierarchy. The
Orchestrator advances a hypothesis one layer at a time; each layer is an agent
(or agent group) that returns pass / fail / waive-with-reason. No skipping.

### 4.6 Memory design (V2 §8)
`working` (per-task, ephemeral) · `research` (findings, searchable by
pair/session/regime/concept) · `experiment` (immutable run records) · `graveyard`
(failures + reason) · `policy` (human-reviewed rules: risk limits, testing
standards) · `knowledge` (concepts from sources). Agents **never** mutate memory
directly — only through the Memory Curator (V2 §11).

### 4.7 Backtesting flow (V3 §6, V4 §10) — **[DONE]**
Event-driven, next-bar fill + spread, bar-by-bar SL/TP, R-unit P/L net of costs,
no look-ahead (`signal_at(i)` cannot see `i+1`), returns trade-level logs.
Configurable realism (spread, commission) already supported; add slippage +
execution-delay knobs. **[TODO: slippage]**

### 4.8 Reporting flow — **[DONE]** for the engine
Text report + tabbed HTML dashboard (Overview/Walk-forward/Monte Carlo/Trades/
Journal) + CSV trade logs + JSONL journal. Add a Reporter *agent* on top (Phase E)
to write decision memos (V4 §15). **[TODO: PDF via optional adapter]**.

### 4.9 Configuration system — **[DONE, extend]**
YAML hypotheses, frozen thresholds, in/out-sample split, optional
carry/news/session blocks, CLI flags for realism knobs. Extend to the typed
schema (V4 §9) and add environment configs (dev/research/prod-like, V4 §14).

### 4.10 Testing approach (V4 §12) — **[PARTIAL, strong]**
24 tests today: unit (indicators, metrics, filters), integration (end-to-end
backtests), data-source, verdict logic. **[TODO]** regression tests that pin
known metric outputs on a fixed dataset (reproducibility guarantee), and
data-quality tests (timestamps, gaps, session labels).

---

## 5. Agent implementation plan (Volume 2 roster)

Format per agent: responsibility · input · output · tools · prohibitions ·
communication · memory access. **Nature** = code / LLM / hybrid (§2.2-5).

| Agent | Nature | Responsibility | Input → Output | May NOT | Memory it reads |
|---|---|---|---|---|---|
| **Orchestrator** | code (+LLM narration) | Drive the 7-layer FSM; route tasks; block skips | task/hypothesis → next-agent assignment, state | Approve strategies; invent results | working, policy |
| **Scientist** | LLM | Generate testable hypotheses + variants | observation/knowledge → hypothesis spec(s) | Claim profitability; present intuition as fact | research, knowledge, graveyard |
| **Librarian** | LLM | Ingest sources → tagged concepts | book/paper/notes → knowledge records | Decide tradability | knowledge (write via Curator) |
| **Skeptic** | LLM | Attack every idea; find overfitting/leakage/regime-dependence | hypothesis + results → failure modes, veto | Protect an idea it likes | experiment, graveyard, research |
| **Statistician** | **code** | Significance, expectancy, CIs, sample-size, false-discovery | trade logs → confidence metrics, warnings | Call a result real too early | experiment |
| **Backtester** | **code** | Deterministic simulation with costs | spec + data → trade log, equity, metrics | Change rules to improve results; look ahead | datasets |
| **Risk Manager** | **code** | Hard gates: sizing, daily/weekly loss, exposure, kill-switch | spec + trade log → pass/veto | Approve aggressive leverage | policy |
| **Portfolio Builder** | **code** | Correlation, diversification, capital efficiency | surviving strategies → allocation view | Treat one strategy as the whole answer | experiment, research |
| **Historian** | hybrid | Find duplicates/analogs in the archive | new hypothesis → prior-match report | Let a recycled dead end through | experiment, graveyard |
| **Memory Curator** | hybrid | Sole writer of durable memory; summarise | any agent output → stored records | Store raw chat noise; lose experiments | all (write authority) |
| **Architect** | LLM | Propose structural improvements to Atlas itself | system logs → change proposals (versioned) | Self-edit rules without review | policy, logs |
| **Reporter** | LLM | Turn evidence into readable memos | results → decision memo | Alter the meaning of evidence | experiment (read-only) |

**Communication:** every message uses the V2 schema
`{task_id, agent, phase, input_summary, evidence, decision, confidence,
next_action}` and is appended to the memory log (auditable, deterministic).
**Conflict handling (V2 §10):** Scientist vs Skeptic → no advance until evidence
resolves; Backtester vs Statistician → rerun/recompute; Risk veto → stop unless
human override (logged); Historian duplicate → merge or reject. Preserve both the
claim and the critique.

---

## 6. Hypothesis & research workflow (implementation-ready, enforceable)

The workflow is a **state machine over an immutable hypothesis record**. Each
transition is gated; the engine enforces the gate, so discipline is code, not
etiquette.

States: `DRAFT → SPECIFIED → BACKTESTED → STAT_VALIDATED → OUT_OF_SAMPLE →
WALK_FORWARD → MONTE_CARLO → REGIME_TESTED → PAPER → MICRO_LIVE → PORTFOLIO →
MONITORING → (RETIRED | GRAVEYARD)`.

Enforceable rules (each is a code check the Orchestrator runs before a transition):
1. **DRAFT→SPECIFIED**: all mandatory schema fields present (typed validator) →
   else refuse. *Pre-registration lock: success/failure criteria + data split are
   hashed now and frozen.* (V1 pre-registration; V3 §4.)
2. **SPECIFIED→BACKTESTED**: run only the frozen rules; stamp engine version +
   data snapshot. (V3 §6.)
3. **BACKTESTED→STAT_VALIDATED**: Statistician computes expectancy, PF, CIs,
   sample-size adequacy; **increments the multiple-testing counter** for that OOS
   set. (V3 §9.)
4. **→OUT_OF_SAMPLE**: evaluate on data untouched during specification; the
   verdict is computed here and is the number that counts. (V1 separation.)
5. **→WALK_FORWARD / MONTE_CARLO / REGIME**: robustness gates (already built for
   WF+MC; regime [TODO]). A result must be *directionally consistent* IS↔OOS
   (V3 §10 "Separation") to pass.
6. **→PAPER→MICRO_LIVE**: **human approval required** (V1 guardrail, V5 §14). No
   auto-advance to capital, ever.
7. **Any failure** → `GRAVEYARD` with a plain-language reason + surviving lesson
   (V3 §14). Nothing is deleted.
8. **No rule drift** (V1 §5): editing rules forks a *new* hypothesis id/version;
   the original stays frozen with its result.

Confidence score (V3 §13) is attached and updated at each state (advisory, 0–95%+).

---

## 7. Data & validation requirements

### 7.1 Data Atlas needs (V3 §7) vs what exists
- **Price** OHLC at timeframe (+tick where possible). *Have:* ~16 months M5,
  2 pairs, demo. *Need:* multi-year, multi-pair, multi-regime.
- **Time**: tz-aware, session labels, weekday/calendar. *Partly have* (tz offset
  handled; session labels/holidays [TODO]).
- **Cost**: spread, commission, swap. *Have* spread+commission modelling;
  swap/slippage [TODO].
- **News**: high-impact calendar. *Loader done; data [TODO].*
- **Volatility/regime**: ATR/range/regime tags. *ATR done; regime tags [TODO].*
- **Reference**: holidays, session opens/closes. *[TODO].*

**Recommendation:** treat data acquisition as **Phase B, in parallel and blocking
trust.** Best pragmatic source for deep FX history: **Dukascopy** (tick/M1, many
years, free) or **HistData** (M1 monthly CSV) → resample to M5/H1. Atlas already
ingests any `time,open,high,low,close` CSV, so these drop in. Demo-broker history
is too thin and single-regime to trust a verdict on (as the London result just
showed — 9 months, one regime).

### 7.2 How the backtester should behave — **[DONE, extend]**
Event-driven, no look-ahead, next-bar fill, spread+commission per trade, bar-by-
bar SL/TP (stop-first on ambiguous bars = conservative), trade-level logs, R-unit
P/L, deterministic. **[TODO]** slippage + execution-delay knobs; configurable
realism profiles (V4 §10).

### 7.3 Validation & anti-overfitting (V3 §11) — **[DONE, harden]**
- In-sample to inspect, **out-of-sample to judge** — [DONE].
- Walk-forward (expanding window, optional grid) — [DONE].
- Monte Carlo bootstrap (trade composition) + shuffle (ordering luck) — [DONE].
- Parameter sensitivity — [PARTIAL] via optimiser leaderboard + overfit-gap flag.
- **Multiple-testing / false-discovery control** — **[TODO, important]**: an OOS
  budget + a tested-count ledger + a warning when many variants share one OOS set.
- Regime testing across trend/range/vol — [TODO].
- Symbol testing across pairs — [DONE] (per-market OOS).
- **Filter-stacking detector** (V3 §11): warn when added conditions cut trade
  count without lifting risk-adjusted return — **[TODO]**.

### 7.4 Costs/slippage/execution realism
Spread + commission [DONE]; slippage, swap/overnight, execution delay, and
session/holiday gaps [TODO]. Realism must be *configurable* so the same
hypothesis can be re-judged under harsher assumptions (V4 §10).

---

## 8. Risks & failure modes

- **Overfitting-by-council (highest research risk).** A tireless Scientist +
  shared OOS set = guaranteed false positives via multiple comparisons. Mitigate:
  OOS budget, pre-registration hash-lock, false-discovery ledger, and a Skeptic
  that can veto on "too many variants tested." (V3 §9, §11.)
- **LLM agents laundering numbers.** If any generative agent is allowed to
  *produce* metrics, results become fiction. Mitigate: the deterministic/LLM
  split (§2.2-5); LLM agents may *interpret* numbers, never *emit* them; every
  number carries a provenance stamp.
- **Data thinness misread as truth.** Thin, single-regime demo data makes every
  strategy look edgeless (or lucky). Mitigate: Phase B deep data; label every
  verdict with its data span + regime coverage; forbid "validated" status on <N
  months / <M regimes.
- **Premature autonomy / self-deploy.** V5's autonomy levels exist precisely to
  prevent this. Mitigate: hard human gate at PAPER→LIVE; kill-switch; autonomy is
  earned per §3 Phase G, never defaulted on.
- **Memory bloat / noise.** Storing chat instead of durable records makes memory
  useless. Mitigate: Curator-only writes, typed records, summaries separated from
  raw logs (V4 §13).
- **Stack sprawl / maintainability.** Adopting Postgres/FastAPI/Plotly too early
  bloats the core. Mitigate: dependency-light core, optional adapters behind
  interfaces (§2.2-4).
- **Governance drift.** Agents editing their own rules. Mitigate: versioned
  prompts/rules, Architect proposes but humans approve, overrides logged (V5 §15).
- **Reproducibility rot.** Code changes silently change past results. Mitigate:
  engine-version + data-snapshot stamping + regression tests pinning known
  outputs (V4 §13, §17).

---

## 9. Open questions — RESOLVED decisions + remaining

**Resolved (2026-07-24, by the researcher — preserved per V5 §15 governance):**
1. **Data source & depth → HistData.com.** Build the importer for HistData M1
   monthly CSVs per pair; resample to M5/H1. Deep, free, simple to ingest. Atlas
   already reads `time,open,high,low,close`, so it drops in. *(Unblocks Phase B.)*
2. **LLM agent runtime → in-session.** LLM agents run inside Claude Code
   sessions, human in the loop — cheap, auditable, matches current workflow.
   No always-on service in v1. *(Sets Phase E architecture.)*
3. **Autonomy ceiling → L4 (sandbox self-queuing).** Atlas may eventually queue
   and prioritise its *own* experiments within a sandbox, with periodic human
   review. **Implication (important & honest):** autonomous testing burns the
   out-of-sample budget far faster than manual testing, so the **multiple-testing
   ledger + OOS budget + pre-registration hash-lock become non-optional
   prerequisites** for L4 — they must exist and be proven at L3 before L4 is ever
   switched on. L4 is *earned*, never defaulted (V5 §17). The sandbox must be
   hard-walled from any live path; PAPER→LIVE stays human-gated regardless.

**Remaining (need answers before the relevant phase):**
4. **Memory backend.** SQLite-only, or Postgres from the start? *(Default:
   SQLite; revisit at scale. Not blocking until Phase D.)*
5. **OOS budget policy.** How many hypotheses may share one out-of-sample set
   before it is "burned" and must be refreshed with new data? *(Needed to make
   L4 autonomy safe; decide during Phase D.)*
6. **Execution realism target.** Which broker/account model should slippage +
   costs mirror, given the account may change? *(Affects realism defaults;
   decide during Phase A slippage work.)*

---

## 10. Next deliverable — implementation brief for Claude Code

**Objective.** Extend the existing `project-atlas/` engine into the Atlas
laboratory of Volumes 1–5, in dependency order, without rewriting the core and
without violating any Volume 1 guardrail.

**Do first (Phase A + B, parallel):**
1. Introduce `atlas/core` with immutable `ExperimentRecord` (id, hypothesis
   fingerprint, engine version, data snapshot id, timestamps) and a typed
   `Hypothesis` schema (V4 §9 fields) with a validator that refuses incomplete
   specs. Migrate `config.py`/`runner.py` to stamp every run.
2. Add regime tagging to trade records; add a regime-testing validation pass.
3. Stand up data acquisition: a Dukascopy/HistData importer → `datasets/` (CSV/
   Parquet), plus session-calendar + holiday tables. Re-run the three current
   hypotheses on multi-year data.

**Then (Phase C, D):**
4. `atlas/risk` hard gates + `atlas/portfolio` correlation/DD/allocation.
5. `atlas/memory` interface with partitioned stores (SQLite), the journal as its
   experiment/graveyard backend, and a **multiple-testing ledger + OOS budget**.

**Then (Phase E):**
6. `atlas/agents`: V2 message schema + Orchestrator FSM = the 7-layer hierarchy;
   wrap the deterministic engine as Backtester/Statistician/Risk/Portfolio
   agents; add the **Skeptic** and **Reporter** LLM agents first (highest value),
   each writing a `DecisionRecord`. Others follow one at a time.

**Then (Phase F, G):** knowledge ingestion + idea generation (L1–L2), then the
governed autonomy loop with scheduled cycles, decay monitoring, and human gates
(L3+).

**Invariants (enforce in code, from V1/V2/V4 guardrails):**
- Out-of-sample is the verdict; in-sample only for inspection.
- No generative agent emits a number; deterministic agents produce all metrics.
- Pre-registration is hash-locked; rule changes fork a new hypothesis.
- No skipping the 7 layers without a logged waiver.
- No PAPER→LIVE without human approval; kill-switch always available.
- Nothing is deleted; failures go to the graveyard with a reason.
- Every run is reproducible from config + data snapshot + engine version.

**Acceptance (V4 §17):** a hypothesis can be defined, tested, validated, and
archived without touching the engine; any backtest replays from stored config +
data; failures are clearly rejected + archived; successes are still forced
through every required stage; reports are generated automatically and match the
data.

---

*End of brief. This document is versioned with the code it describes; update it
when the architecture changes (V5 §15 governance).*
