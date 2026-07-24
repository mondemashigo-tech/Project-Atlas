# Project Atlas

A modular quantitative FX hypothesis-testing platform. It exists to answer one
question honestly, *before* any money is risked:

> **Does this strategy have a real, out-of-sample edge that survives costs?**

Atlas does not try to make a strategy look good. It tries to make it *fail* —
on data it never saw — against thresholds frozen in advance. If a hypothesis
survives that, it earns a live trial. If it doesn't, we learn cheaply.

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

## Layout

| Path | Purpose |
|---|---|
| `atlas/indicators.py` | ema, atr, rsi, swing high/low (pure vectorized) |
| `atlas/data.py` | portable CSV loader + resampler (not tied to live MT5) |
| `atlas/strategies/` | config-driven strategy registry + templates |
| `atlas/backtester.py` | event loop, next-bar fill + spread, bar-by-bar SL/TP |
| `atlas/metrics.py` | PF, expectancy, drawdown, Sharpe — all in R units |
| `atlas/splits.py` | in-sample / out-of-sample separation |
| `atlas/{config,report,runner,cli}.py` | load -> run -> judge -> report |
| `hypotheses/` | pre-registered hypotheses (frozen thresholds) |
| `tests/` | pipeline tests (synthetic data, no MT5 needed) |

## Usage

```bash
pip install -r requirements.txt

# Run a pre-registered hypothesis end-to-end
python -m atlas.cli run hypotheses/london_trend_continuation.yaml

# Pull real history from MT5 into a dataset CSV (run on the bot machine)
python -m atlas.cli export GBPUSD M5 3

# Tests
pytest -q
```

## Status

- **Phase 1 — spine**: backtest, metrics, verdicts, splits, CLI. ✅ Complete, tests passing.
- **Phase 2 — robustness**: walk-forward analysis + Monte Carlo resampling. In progress.
- **Phase 3 — surface**: dashboard, HTML/PDF/CSV reports, trade journal, optimizer.
- **Phase 4 — data**: rate differentials (carry), economic calendar (news filter).

> Living here as a branch of `zpk-trade-scout` for now; designed to split cleanly
> into its own repo.
