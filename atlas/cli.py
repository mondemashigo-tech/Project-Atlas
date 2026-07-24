"""Atlas CLI.

    python -m atlas.cli run  hypotheses/london_trend_continuation.yaml [--mc] [--html]
    python -m atlas.cli wf   hypotheses/london_trend_continuation.yaml [--folds 5]
    python -m atlas.cli mc   hypotheses/london_trend_continuation.yaml [--sims 5000] [--window out_sample|in_sample|full]
    python -m atlas.cli opt  hypotheses/london_trend_continuation.yaml [--objective total_r] [--min-trades 30]
    python -m atlas.cli html hypotheses/london_trend_continuation.yaml   # full dashboard (run + wf + mc)
    python -m atlas.cli journal                                          # show the research log
    python -m atlas.cli export GBPUSD M5 3                               # pull data via MT5 (bot machine)
"""
from __future__ import annotations

import argparse
import os
import sys

from . import config as config_mod
from . import dashboard as dash_mod
from . import data as data_mod
from . import journal as journal_mod
from . import montecarlo as mc_mod
from . import optimizer as opt_mod
from . import report as report_mod
from . import runner
from . import walkforward as wf_mod
from .backtester import trades_to_frame
from .metrics import verdict
from .strategies import trend_continuation  # noqa: registers the template


def _journal_path(args):
    return os.path.join(args.reports, "journal.jsonl")


def _run(args):
    cfg = config_mod.load(args.hypothesis)
    results = runner.run_hypothesis(cfg, args.datasets)
    text = report_mod.render(cfg, results)
    mc = None
    if args.mc:
        mc = mc_mod.analyze(results["out_sample"]["trades"])
        text += "\n" + mc_mod.render(mc)
    print(text)

    os.makedirs(args.reports, exist_ok=True)
    stem = os.path.join(args.reports, cfg["name"])
    with open(stem + "_report.txt", "w", encoding="utf-8") as f:
        f.write(text)
    for w in ("in_sample", "out_sample"):
        tr = trades_to_frame(results[w]["trades"])
        if len(tr):
            tr.to_csv(f"{stem}_{w}_trades.csv", index=False)

    v_out = verdict(results["out_sample"]["metrics"], cfg.get("criteria", {}))
    journal_mod.append(cfg, results, v_out, path=_journal_path(args))

    if args.html:
        htmlp = stem + "_dashboard.html"
        with open(htmlp, "w", encoding="utf-8") as f:
            f.write(dash_mod.render(cfg, results, mc=mc,
                                    journal_records=journal_mod.load(_journal_path(args))))
        print(f"Wrote dashboard -> {htmlp}")
    print(f"\nSaved report + trades + journal under {args.reports}/")


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


def _opt(args):
    cfg = config_mod.load(args.hypothesis)
    if not cfg.get("optimize"):
        print("No 'optimize:' grid in this hypothesis — nothing to search.")
        return
    opt = opt_mod.optimize(cfg, args.datasets, objective=args.objective,
                           min_trades=args.min_trades)
    text = opt_mod.render(opt)
    print(text)
    os.makedirs(args.reports, exist_ok=True)
    with open(os.path.join(args.reports, cfg["name"] + "_optimize.txt"),
              "w", encoding="utf-8") as f:
        f.write(text)
    print(f"\nSaved optimiser report under {args.reports}/")


def _html(args):
    cfg = config_mod.load(args.hypothesis)
    results = runner.run_hypothesis(cfg, args.datasets)
    mc = mc_mod.analyze(results["out_sample"]["trades"])
    wf = wf_mod.walk_forward(cfg, args.datasets, folds=args.folds)
    v_out = verdict(results["out_sample"]["metrics"], cfg.get("criteria", {}))
    os.makedirs(args.reports, exist_ok=True)
    journal_mod.append(cfg, results, v_out, path=_journal_path(args))
    htmlp = os.path.join(args.reports, cfg["name"] + "_dashboard.html")
    with open(htmlp, "w", encoding="utf-8") as f:
        f.write(dash_mod.render(cfg, results, mc=mc, wf=wf,
                                journal_records=journal_mod.load(_journal_path(args))))
    print(f"Wrote dashboard -> {htmlp}")


def _journal(args):
    print(journal_mod.render(journal_mod.load(_journal_path(args))))


def _export(args):
    path = data_mod.export_from_mt5(args.symbol, args.timeframe, args.years, args.datasets)
    print(f"exported -> {path}")


def _mt5check(args):
    d = data_mod.mt5_diagnostics(args.symbols)
    if not d.get("ok"):
        print("MT5 NOT CONNECTED:", d.get("error"))
        return
    a = d["account"] or {}
    print(f"account: login {a.get('login')} | server {a.get('server')} | "
          f"{a.get('company')} | {a.get('currency')}")
    print(f"symbols available in terminal: {d['symbols_total']}")
    for s, info in d["requested"].items():
        print(f"\n{s}:")
        print(f"  exact name selected : {info['exact_selected']}")
        print(f"  M5 bars available   : {info['m5_bars']}")
        if info["m5_bars"]:
            print(f"  range               : {info['first']}  ->  {info['last']}")
        print(f"  name matches ('{s[:6]}'): {info['name_matches'] or 'NONE'}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="atlas")
    p.add_argument("--datasets", default="datasets")
    p.add_argument("--reports", default="reports")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="run a hypothesis backtest + verdict")
    r.add_argument("hypothesis")
    r.add_argument("--mc", action="store_true", help="append Monte Carlo on OOS trades")
    r.add_argument("--html", action="store_true", help="also write the HTML dashboard")
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

    o = sub.add_parser("opt", help="grid-search optimiser (IS ranked, OOS reported)")
    o.add_argument("hypothesis")
    o.add_argument("--objective", default="total_r")
    o.add_argument("--min-trades", type=int, default=30, dest="min_trades")
    o.set_defaults(func=_opt)

    h = sub.add_parser("html", help="full HTML dashboard (run + walk-forward + Monte Carlo)")
    h.add_argument("hypothesis")
    h.add_argument("--folds", type=int, default=5)
    h.set_defaults(func=_html)

    j = sub.add_parser("journal", help="print the research journal")
    j.set_defaults(func=_journal)

    e = sub.add_parser("export", help="export MT5 history to a dataset CSV")
    e.add_argument("symbol"); e.add_argument("timeframe")
    e.add_argument("years", type=float, nargs="?", default=3.0)
    e.set_defaults(func=_export)

    ck = sub.add_parser("mt5check", help="diagnose MT5 connection, symbols, history")
    ck.add_argument("symbols", nargs="+")
    ck.set_defaults(func=_mt5check)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
