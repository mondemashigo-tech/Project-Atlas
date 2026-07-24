# Project Atlas

**An AI research laboratory** (and the foundation for a future assistant). Atlas
turns ideas into pre-registered hypotheses, tests them against unseen data,
rejects weak ideas fast, remembers everything, and *approves* a rare few for
execution. It answers one question honestly, *before* any money is risked:

> **Does this strategy have a real, out-of-sample edge that survives costs?**

Atlas does not try to make a strategy look good. It tries to make it *fail* — on
data it never saw — against thresholds frozen in advance. See the full design in
`docs/ATLAS_MASTER_PLAN.md` (Volumes 1–5 are the source of truth).

**Atlas is the parent system.** The FX strategy engine is *one research module*
(`atlas/research/fx/`). The trading bot is a future **execution engine** that
only ever reads approved strategies from the **Strategy Registry** — the airlock
between research and execution. Atlas researches and validates; the bot executes
only what Atlas has approved (human-gated).

## Why this exists

The predecessor bot (`zpk-trade-scout`) went "green" live (+$164) but a proper
403-trade backtest proved the strategy had **no edge**: profit factor 0.80,
expectancy −$6.80/trade. The green number was luck plus selection-biased manual
closes. Atlas is the fix: strategy is downstream of edge, so we test for edge
first, rigorously, and only then automate.

## How it works

```
hypothesis.yaml  ->  load data  ->  split in/out-of-sample  ->  backtest
                                                                    |
                          verdict  <-  metrics (R units)  <---------+
```

- **Pre-registered hypotheses** (`hypotheses/*.yaml`): thresholds are frozen
  before the run. No moving the goalposts.
- **In-sample / out-of-sample split**: inspect on in-sample, *judge* on
  out-of-sample only.
- **R-unit metrics**: everything is measured in units of risk (R), so results
  are scale-invariant and comparable across markets and account sizes.
- **Costs baked in**: spread + commission are charged on every trade.

## Layout (parent system)

| Path | Purpose |
|---|---|
| `atlas/schemas/` | core data models: Hypothesis, DataSnapshot, ExperimentRecord, DecisionRecord, StrategyRecord, KnowledgeNote |
| `atlas/memory/` | SQLite experiment store (source of truth) + Obsidian markdown mirror in `vault/` |
| `atlas/registry/` | Strategy Registry airlock: lifecycle FSM, human-gated writes, read-only export, kill-switch, stub bot consumer |
| `atlas/service.py` | library-first orchestration (research → memory), the seam that grows into the Kernel |
| `atlas/interfaces/` | thin CLI adapter (`python -m atlas …`); web/voice/Obsidian later |
| `atlas/research/fx/` | the FX research module (the preserved engine, below) |

### Inside the FX research module (`atlas/research/fx/`)

| Path | Purpose |
|---|---|
| `indicators.py` | ema, atr, rsi, swing high/low (pure vectorized) |
| `data.py` | portable CSV loader + resampler; MT5 export + `mt5check` diagnostic |
| `strategies/` | config-driven registry + templates: `trend_continuation` (pullback), `mean_reversion` (z-score fade), `breakout` (Donchian channel) |
| `backtester.py` | event loop, next-bar fill + spread, bar-by-bar SL/TP |
| `metrics.py` | PF, expectancy, drawdown, Sharpe — all in R units |
| `splits.py` | in-sample / out-of-sample separation |
| `walkforward.py` | anchored walk-forward + optional param-grid optimisation |
| `montecarlo.py` | bootstrap + shuffle resampling of the trade sequence |
| `optimizer.py` | grid search (ranked IS, reported OOS, overfit-gap flag) |
| `journal.py` | append-only JSONL research log with config fingerprints |
| `charts.py`, `dashboard.py` | dependency-free inline SVG + tabbed HTML report |
| `datasources.py`, `filters.py` | carry (rates) + economic-calendar loaders and entry filters |
| `{config,report,runner,cli}.py` | load -> run -> judge -> report |
| `hypotheses/` | pre-registered hypotheses (frozen thresholds) |
| `tests/` | spine + pipeline + robustness + reporting + data-source tests (synthetic, no MT5) |

## Usage

```bash
pip install -r requirements.txt

# --- Atlas parent CLI ---
# Run a hypothesis -> immutable ExperimentRecord (SQLite) + Obsidian vault mirror
python -m atlas run hypotheses/london_trend_continuation.yaml
python -m atlas experiments          # list recorded experiments
python -m atlas registry list        # inspect the airlock
python -m atlas bot                  # what the stub executor WOULD run (no orders)

# --- FX research module CLI (deeper analysis on the engine directly) ---
python -m atlas.research.fx.cli run hypotheses/london_trend_continuation.yaml --mc
python -m atlas.research.fx.cli wf  hypotheses/london_trend_continuation.yaml --folds 5
python -m atlas.research.fx.cli export GBPUSD M5 3   # pull MT5 history (bot machine)

# Tests
pytest -q
```

## Status

**Atlas parent spine (Milestone 1)** ✅ — core schemas, SQLite memory + Obsidian
mirror, Strategy Registry airlock (human-gated, kill-switch, stub consumer),
library-first service + CLI. The FX engine is preserved as a research module.

**FX research module** ✅ — backtest, R-unit metrics, verdicts, in/out-of-sample
splits, walk-forward, Monte Carlo (bootstrap + shuffle), optimiser, journal, SVG
charts, tabbed HTML dashboard, carry + economic-calendar filters.

**Next:** Milestone 2 — HistData importer + `DataSnapshot` wiring (deep
multi-regime data). Milestone 3 — Kernel FSM + Skeptic & Reporter agents.

### Data sources (Phase 4)

Two optional, portable CSV sources sit alongside the price data and act as entry
filters. A hypothesis that references neither behaves exactly as before.

| File | Schema | Effect |
|---|---|---|
| `datasets/rates.csv` | `time, currency, rate` | With `carry: {require_aligned: true}`, only take trades aligned with the pair's rate differential (long the higher-yielding currency). Missing data → abstain, never guess. |
| `datasets/calendar.csv` | `time, currency, impact` | With `news_filter: {enabled: true, ...}`, block entries inside a blackout window around high-impact events for either currency of the pair. |

See `hypotheses/london_trend_carry_news.yaml` for the config. Both filters are
look-ahead safe (rates use as-of lookup; the calendar blocks a symmetric window
around the event time).

### Robustness, in one paragraph

A backtest is one draw from a distribution. Atlas measures the distribution.
*Walk-forward* re-optimises on an expanding in-sample window and judges only on
the next never-seen slice — if performance collapses out-of-sample, that's
curve-fitting, not edge. *Monte Carlo* bootstraps the realised trades (does the
result survive a different mix of trades?) and shuffles their order (did the
worst drawdown just depend on lucky sequencing?). A strategy that only looks
good in one arrangement of one sample is not an edge.

> Living here as a branch of `zpk-trade-scout` for now; designed to split cleanly
> into its own repo.
