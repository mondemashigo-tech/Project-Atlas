"""Atlas CLI.

    python -m atlas.cli run hypotheses/london_trend_continuation.yaml [--mc]
    python -m atlas.cli wf  hypotheses/london_trend_continuation.yaml [--folds 5]
    python -m atlas.cli mc  hypotheses/london_trend_continuation.yaml [--sims 5000] [--window out_sample|in_sample|full]
    python -m atlas.cli export GBPUSD M5 3      # pull data via MT5 (bot machine)
"""
from __future__ import annotations

import argparse
import os
import sys

from . import config as config_mod
from . import data as data_mod
from . import montecarlo as mc_mod
from . import report as report_mod
from . import runner
from . import walkforward as wf_mod
from .backtester import trades_to_frame
from .strategies import trend_continuation  # noqa: registers the template


def _run(args):
    cfg = config_mod.load(args.hypothesis)
    results = runner.run_hypothesis(cfg, args.datasets)
    text = report_mod.render(cfg, results)
    if args.mc:
        text += "\n" + mc_mod.render(mc_mod.analyze(results["out_sample"]["trades"]))
    print(text)
    os.makedirs(args.reports, exist_ok=True)
    stem = os.path.join(args.reports, cfg["name"])
    with open(stem + "_report.txt", "w", encoding="utf-8") as f:
        f.write(text)
    for w in ("in_sample", "out_sample"):
        tr = trades_to_frame(results[w]["trades"])
        if len(tr):
            tr.to_csv(f"{stem}_{w}_trades.csv", index=False)
    print(f"\nSaved report + trades under {args.reports}/")


def _wf(args):
    cfg = config_mod.load(args.hypothesis)
    wf = wf_mod.walk_forward(cfg, args.datasets, folds=args.folds,
                             min_is_trades=args.min_is_trades)
    text = wf_mod.render(wf)
    print(text)
    os.makedirs(args.reports, exist_ok=True)
    with open(os.path.join(args.reports, cfg["name"] + "_walkforward.txt"),
              "w", encoding="utf-8") as f:
        f.write(text)
    print(f"\nSaved walk-forward report under {args.reports}/")


def _mc(args):
    cfg = config_mod.load(args.hypothesis)
    if args.window == "full":
        trades = runner.run_full(cfg, args.datasets)["trades"]
    else:
        trades = runner.run_hypothesis(cfg, args.datasets)[args.window]["trades"]
    text = f"window: {args.window}\n" + mc_mod.render(
        mc_mod.analyze(trades, n_sims=args.sims))
    print(text)
    os.makedirs(args.reports, exist_ok=True)
    with open(os.path.join(args.reports, cfg["name"] + "_montecarlo.txt"),
              "w", encoding="utf-8") as f:
        f.write(text)
    print(f"\nSaved Monte Carlo report under {args.reports}/")


def _export(args):
    path = data_mod.export_from_mt5(args.symbol, args.timeframe, args.years, args.datasets)
    print(f"exported -> {path}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="atlas")
    p.add_argument("--datasets", default="datasets")
    p.add_argument("--reports", default="reports")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="run a hypothesis backtest + verdict")
    r.add_argument("hypothesis")
    r.add_argument("--mc", action="store_true", help="append Monte Carlo on OOS trades")
    r.set_defaults(func=_run)

    w = sub.add_parser("wf", help="walk-forward analysis")
    w.add_argument("hypothesis")
    w.add_argument("--folds", type=int, default=5)
    w.add_argument("--min-is-trades", type=int, default=20, dest="min_is_trades")
    w.set_defaults(func=_wf)

    m = sub.add_parser("mc", help="Monte Carlo robustness on realised trades")
    m.add_argument("hypothesis")
    m.add_argument("--sims", type=int, default=5000)
    m.add_argument("--window", choices=["out_sample", "in_sample", "full"],
                   default="out_sample")
    m.set_defaults(func=_mc)

    e = sub.add_parser("export", help="export MT5 history to a dataset CSV")
    e.add_argument("symbol"); e.add_argument("timeframe")
    e.add_argument("years", type=float, nargs="?", default=3.0)
    e.set_defaults(func=_export)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
