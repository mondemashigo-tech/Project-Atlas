"""Atlas CLI.

    python -m atlas.cli run hypotheses/london_trend_continuation.yaml
    python -m atlas.cli export GBPUSD M5 3      # pull data via MT5 (bot machine)
"""
from __future__ import annotations

import argparse
import os
import sys

from . import config as config_mod
from . import data as data_mod
from . import report as report_mod
from . import runner
from .backtester import trades_to_frame
from .strategies import trend_continuation  # noqa: registers the template


def _run(args):
    cfg = config_mod.load(args.hypothesis)
    results = runner.run_hypothesis(cfg, args.datasets)
    text = report_mod.render(cfg, results)
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
    r.set_defaults(func=_run)

    e = sub.add_parser("export", help="export MT5 history to a dataset CSV")
    e.add_argument("symbol"); e.add_argument("timeframe")
    e.add_argument("years", type=float, nargs="?", default=3.0)
    e.set_defaults(func=_export)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
