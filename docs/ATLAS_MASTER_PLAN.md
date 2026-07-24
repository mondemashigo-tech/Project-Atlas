# Project Atlas — Master Plan (parent-system redesign)

*Supersedes the framing in `ATLAS_ARCHITECTURE_AND_BUILD_BRIEF.md` (which
remains valid for the research-engine internals). Source of truth: Atlas
Volumes 1–5. This document redesigns the project with **Atlas as the parent
system** and the trading bot as a future execution engine.*

Status legend: **[HAVE]** exists in this repo · **[WRAP]** exists, needs to be
wrapped/moved · **[NEW]** to build · **[LATER]** deferred · **[ASSUMPTION]**
labelled inference.

---

## 1. The pivot, precisely

- **Atlas = parent.** A research laboratory + knowledge system + governance layer.
  Its job: turn ideas into pre-registered hypotheses, run them through a
  validation ladder, keep only what survives, remember everything, and *approve*
  a rare few for execution. First domain is FX; the architecture is domain-
  agnostic so it can grow into a general research/decision assistant ("Jarvis").
- **The strategy engine is one module**, not the project (`atlas/research/fx/`).
- **The bot is a future execution engine.** It reads approved strategies from the
  Strategy Registry and executes them. It contains no research and no discretion.
- **The Strategy Registry is the airlock** between research and execution. Atlas
  writes (human-gated); the bot reads. This is the single most important new
  boundary in the redesign.
- **Front-ends (web, voice, Obsidian) are adapters over a library-first core** —
  designed for now, built later.

Non-goals (restated from the volumes + your instruction): not a signal service,
not a black box, not a self-deploying bot, not a monolith with hard-coded
strategy logic.

---

## 2. New top-level architecture

Atlas is a set of cooperating subsystems around a **kernel**. Everything is a
library call; CLI/API/voice/Obsidian are thin adapters on top.

```
                         ┌─────────────────────────────┐
      (you) ──▶ Interfaces (CLI now; web/voice/Obsidian later — thin adapters)
                         └──────────────┬──────────────┘
                                        │ commands / queries
                         ┌──────────────▼──────────────┐
                         │            KERNEL            │  orchestrator + workflow FSM
                         │  (routes tasks, drives the   │  (the 7-layer decision hierarchy)
                         │   validation ladder, no      │
                         │   skipping, logs everything) │
                         └───┬───────────┬───────────┬──┘
             ┌───────────────┘           │           └───────────────┐
   ┌─────────▼─────────┐   ┌─────────────▼─────────┐   ┌─────────────▼─────────┐
   │   COUNCIL (agents) │   │   RESEARCH MODULES     │   │  MEMORY & KNOWLEDGE    │
   │  deterministic code│   │  fx/ (the preserved    │   │  experiment store (DB) │
   │  + in-session LLM  │◀─▶│  engine: backtest,     │◀─▶│  graveyard, knowledge, │
   │  (Skeptic, Reporter│   │  validation, metrics)  │   │  policy, research notes│
   │  Scientist, ...)   │   │  future: other domains │   │  Obsidian markdown mirror
   └────────────────────┘   └───────────┬────────────┘   └────────────────────────┘
                                        │ approved + validated only
                              ┌─────────▼──────────┐
                              │  STRATEGY REGISTRY │  the airlock (versioned, human-gated)
                              │  status · alloc ·  │
                              │  risk · provenance │
                              └─────────┬──────────┘
                                        │ read-only, JSON contract
                              ┌─────────▼──────────┐
                              │  EXECUTION ENGINE  │  [LATER] the bot: executes approved
                              │  (the current bot) │  strategies, reports fills back
                              └────────────────────┘
```

Key properties:
- **One-way approval flow.** Research → Registry → Execution. The bot cannot reach
  into research; research cannot reach into execution except by writing an
  approved Registry record. Fills flow back to Memory for decay monitoring only.
- **Deterministic core, generative edges.** Numbers are produced by code agents
  (Backtester, Statistician, Risk, Portfolio); LLM agents generate/critique/
  report but never emit a number (Volume 2/3 guardrail).
- **Everything is a record.** Hypotheses, experiments, decisions, registry entries
  are immutable, versioned, provenance-linked (Volume 4 §13).

---

## 3. Repository structure

Target layout (Atlas as the top-level package). **[ASSUMPTION]** the Python
package is the code home; V4's numbered folders become artifact dirs.

```
atlas/                     # THE PARENT SYSTEM (python package)
  kernel/          [NEW]   orchestrator, workflow state machine, message bus
  schemas/         [NEW]   typed core data models (see §4) + validators + versioning
  agents/          [NEW]   council: base contracts, deterministic agents, in-session LLM agents
  memory/          [WRAP]  experiment store (SQLite) + graveyard + knowledge + policy;
                           Obsidian-markdown mirror; (today: journal.py)
  registry/        [NEW]   Strategy Registry: StrategyRecord, lifecycle FSM, gated writes,
                           JSON export = the bot's contract
  research/                domain research modules
    fx/            [WRAP]  the PRESERVED engine, moved intact:
                             backtester, strategies/, validation (metrics, walkforward,
                             montecarlo, optimizer, splits), data, datasources, filters,
                             charts, dashboard, report, config
  interfaces/      [NEW]   CLI now; API surface designed for web/voice/Obsidian
  config/          [WRAP]  environment + loaders
vault/             [NEW]   Obsidian vault (markdown): knowledge/, hypotheses/, graveyard/,
                           research-notes/  — the human-readable face of memory
datasets/                  versioned data snapshots
reports/                   generated artifacts (html/csv/json)
tests/                     unit / integration / regression / data-quality
docs/                      the 5 volumes + this plan + the engine brief
```

**Hosting reality (flagged):** Atlas currently lives as `project-atlas/` on a
branch *inside the bot repo* (`zpk-trade-scout`), because repo creation is blocked
here (403). That **inverts** the intended parent/child relationship (the bot repo
contains its own parent). Target end-state: **Atlas is its own top-level repo; the
bot becomes a consumer/submodule.** Until you create the repo, we keep building
in `project-atlas/` and migrate later — the internal structure above is designed
so the move is a `git mv`, not a rewrite.

---

## 4. Core data models (build these first)

Typed, validated, versioned, immutable-once-committed. These are the vocabulary
of the whole system.

1. **`Hypothesis`** — the research unit.
   `id, version, domain, title, markets, timeframes, spec(rules), directional_bias,
   session, filters(news/carry), risk_rules, validation_plan, success_criteria,
   failure_criteria, data_split, preregistration_hash, confidence_score, status`.
   *Immutable once SPECIFIED; editing forks a new id/version (no rule drift).*

2. **`DataSnapshot`** — reproducibility anchor.
   `id, source, symbols, timeframe, span, row_count, content_hash, created_at`.

3. **`ExperimentRecord`** — the immutable evidence unit.
   `id, hypothesis_id, hypothesis_version, engine_version, data_snapshot_id,
   window(in/out/full), metrics, monte_carlo, walk_forward, verdict, trade_log_ref,
   created_at`. *Never mutated; the audit trail.*

4. **`DecisionRecord`** — the Volume 2 agent message + ruling.
   `task_id, agent, phase, input_summary, evidence, decision, confidence,
   next_action, created_at`. *Every agent emits one per task.*

5. **`StrategyRecord`** — the Registry entry (the airlock contract, §5).
   `strategy_id, source_hypothesis_id+version, validating_experiment_ids,
   frozen_executable_spec, status(candidate|paper|micro_live|live|retired),
   allocation, risk_limits, approvals[{who,when,note}], version,
   monitoring_state(decay/drift), created_at, updated_at`.

6. **`KnowledgeNote` / `GraveyardEntry`** — markdown-first (Obsidian), with
   structured front-matter: `topic tags, source, summary, links, lesson`.

Implement as typed classes (dataclasses/pydantic) with a validator that **refuses
incomplete or malformed records**. The engine must not run a Hypothesis missing
mandatory fields (V4 §9).

---

## 5. The Strategy Registry (Atlas ↔ bot boundary)

The Registry is the **only** thing the execution engine ever sees. It is the
contract that keeps research and execution cleanly separated.

**What it stores:** `StrategyRecord`s (§4-5) — a *frozen executable spec* plus its
status, allocation, risk limits, provenance (which hypothesis + experiments
validated it), approvals, version, and live-monitoring state.

**Lifecycle (a state machine, human-gated at every capital-bearing step):**
```
candidate ──approve(paper)──▶ paper ──approve(micro)──▶ micro_live
   ▲                                                        │
   │                                             approve(live) │
   └────────── demote/retire ◀── monitoring ◀── live ◀────────┘
```
- **Atlas writes**, and only after the full validation ladder passes *and* a human
  approves the transition. Registry writes are gated in code; no agent (even at
  L4 autonomy) may promote a strategy to any capital-bearing status without a
  logged human approval.
- **The bot reads** entries with status ∈ {paper, micro_live, live} from a
  **read-only JSON/DB export**, executes *exactly* the frozen spec at the given
  allocation and risk limits, and reports fills back.
- **Fills flow back to Memory**, feeding decay/drift monitoring (V5 §12). If an
  edge decays, Atlas demotes/retires the record → the bot stops trading it.
- **Kill-switch:** one call sets all live records to `disabled`; the bot halts.
- **Versioned + auditable:** every transition writes a `DecisionRecord` and bumps
  the record version; the frozen spec never mutates in place (a change forks a new
  strategy_id, mirroring "no rule drift").

This is how "Atlas researches and validates; the bot executes only approved
strategies" becomes a concrete, enforceable interface rather than a slogan.

---

## 6. Minimum viable Atlas v1 (build order)

v1 is the **foundation that makes Atlas the parent** — not data, not autonomy,
not the full council. Explicitly ordered; each step depends on the one above.

1. **Schemas** (`atlas/schemas`) — the six data models (§4), typed + validated.
   *Nothing else can be built cleanly without these.*
2. **Preserve the engine** — move the current code intact into `atlas/research/fx/`;
   keep all 24 tests green. *No behaviour change; just its new place in the system.*
3. **Memory + provenance** (`atlas/memory`) — SQLite experiment store writing
   immutable `ExperimentRecord`s + an Obsidian-markdown mirror; migrate the journal
   behind this interface. Every run now leaves a reproducible, provenance-stamped
   record.
4. **Strategy Registry** (`atlas/registry`) — `StrategyRecord` schema + lifecycle
   FSM + human-gated write API + read-only JSON export (the bot's future contract).
   Built with a stub bot consumer; no real execution yet.
5. **Kernel skeleton** (`atlas/kernel`) — an explicit orchestrator FSM = the
   7-layer hierarchy, driving one hypothesis end-to-end. Wrap the engine as the
   deterministic agents (Backtester, Statistician, Risk, Portfolio).
6. **First two LLM agents, in-session** (`atlas/agents`) — **Skeptic** (enforces
   rigor, can veto) and **Reporter** (writes the decision memo). Highest value
   first; the rest of the council follows later, one at a time.
7. **Interface discipline** — keep all logic in library functions; the CLI is a
   thin adapter, so web/voice/Obsidian attach later without a rewrite.

**Wait / [LATER]:** HistData importer & deep data (needed for *trusted* verdicts,
but not part of the foundation — build right after v1), full 12-agent council,
knowledge ingestion at scale, decay monitoring, paper/live execution, the actual
bot wiring, web/voice/Obsidian front-ends, L3→L4 autonomy.

---

## 7. Preserve / archive / rebuild (from the current backtester)

**PRESERVE — move intact into `atlas/research/fx/` (proven, 24 tests):**
backtester, strategies/ (trend_continuation, mean_reversion, breakout, common,
base/registry), validation (metrics, walkforward, montecarlo, optimizer, splits),
data (loaders, resample, MT5 export, mt5check), datasources + filters (carry/news),
charts, dashboard, report. These are good research code; they just stop being the
top of the tree.

**WRAP / REBUILD into Atlas primitives:**
- `config.py` → typed `Hypothesis` schema (§4-1) with a hard validator.
- `journal.py` → `atlas/memory` experiment store (immutable `ExperimentRecord`s +
  provenance + Obsidian mirror). The journal is the right idea; it graduates into
  the memory layer.
- `runner.py` / `cli.py` → `atlas/kernel` orchestrator + `atlas/interfaces` CLI.

**ARCHIVE / LEAVE AS-IS (separate concern):**
- `zpk_bot.py` and the live bot scripts stay where they are — they are the *future
  execution engine*, not part of Atlas core. Do not fold them into Atlas now; they
  will later become a Registry consumer.
- The demo hypotheses + dashboards remain as examples/fixtures.

**Nothing is deleted** (Volume 1 guardrail). The pivot is a *re-rooting*, not a
teardown.

---

## 8. Contradictions, risks, missing pieces

1. **Repo inversion (structural).** Atlas-the-parent currently lives inside the
   bot repo. Until you create a standalone `atlas` repo, the hierarchy is upside
   down. *Mitigation:* structure now so the move is `git mv`; create the repo when
   you can. **This is the one thing only you can unblock.**
2. **Registry leak risk.** If any path lets the bot read research state directly
   (or research call execution directly), the separation collapses. *Mitigation:*
   the Registry JSON export is the *only* bot input; enforce in code + tests.
3. **L4 autonomy vs registry writes.** Autonomous promotion to capital is the
   nightmare case. *Mitigation:* registry writes to paper/micro/live are **always**
   human-gated, even at L4; the false-discovery ledger + OOS budget +
   pre-registration hash-lock are prerequisites for L4 (carried over from the prior
   brief).
4. **Obsidian as database (anti-pattern).** Markdown is great for human/knowledge
   layers, bad as the system-of-record for structured experiment data (querying,
   concurrency, integrity). *Mitigation:* **SQLite is the source of truth; the
   Obsidian vault is a generated mirror.** Never write structured records only to
   markdown.
5. **Front-end lock-in.** Building CLI-first in a way that can't be wrapped by web/
   voice. *Mitigation:* library-first; CLI/API/voice are adapters over the same
   functions.
6. **Data thinness (unchanged reality).** Trusted verdicts still need deep multi-
   regime data; the foundation doesn't fix that, it just precedes it. *Mitigation:*
   HistData importer is the very next thing after v1; label every verdict with its
   data span + regime coverage; forbid `VALIDATED` on thin data.
7. **Scope gravity.** The Jarvis framing invites over-building. *Mitigation:*
   Volume 1's "reliability over flash" — ship the v1 spine, keep the council to two
   agents, defer everything in §6's LATER list.

---

## 9. First implementation milestone (exact)

**Milestone 1 — "Atlas Kernel v0: schemas + memory + registry, engine preserved."**

Deliverables:
1. `atlas/schemas/`: `Hypothesis`, `DataSnapshot`, `ExperimentRecord`,
   `DecisionRecord`, `StrategyRecord`, `KnowledgeNote` as typed, validated classes
   with a strict validator (refuse incomplete records) + a `preregistration_hash`
   helper.
2. `atlas/research/fx/`: the current engine moved here **unchanged**; imports
   updated; **all 24 existing tests pass from the new location**.
3. `atlas/memory/`: SQLite experiment store that writes an immutable
   `ExperimentRecord` for every run + a matching markdown file under `vault/`
   (Obsidian mirror). Journal data migrates behind this interface.
4. `atlas/registry/`: `StrategyRecord` + lifecycle FSM + a **human-gated**
   `promote()/demote()/retire()` API (each writes a `DecisionRecord`) + a read-only
   `export_json()` = the bot's future contract. A stub `registry_consumer` proves
   the contract without executing anything.
5. `atlas/interfaces/cli.py`: thin adapter exposing `run`, `experiments`,
   `registry` commands over the library; existing engine CLI keeps working.
6. Tests: schema validation (accept good, reject malformed), memory round-trip
   (write → read → identical), registry lifecycle (illegal transitions rejected,
   capital-bearing transitions require an approval token), plus the preserved 24.

**Acceptance:**
- Running a hypothesis produces an immutable `ExperimentRecord` in SQLite **and** a
  human-readable markdown mirror in `vault/`.
- A validated strategy can be placed in the Registry only through the gated API,
  and the bot-facing `export_json()` reflects only approved statuses.
- Illegal registry transitions and incomplete hypotheses are rejected in code.
- All prior engine tests still pass after the move.
- No trading, no signals, no autonomy — just the auditable spine.

Milestone 2 (preview): HistData importer + `DataSnapshot` wiring → re-judge the
three hypotheses on deep multi-regime data. Milestone 3: kernel FSM + Skeptic +
Reporter agents.

---

*Versioned with the code. Update on any architecture change (V5 §15 governance).*
