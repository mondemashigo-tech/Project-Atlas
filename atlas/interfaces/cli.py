"""Atlas CLI — thin adapter over the library.

    python -m atlas run <hypothesis.yaml>     # research -> immutable ExperimentRecord + vault mirror
    python -m atlas experiments                # list recorded experiments
    python -m atlas registry list|export       # inspect the airlock
    python -m atlas bot                         # what the stub executor WOULD run (no orders)

The FX research module keeps its own CLI at `python -m atlas.research.fx.cli`.
"""
from __future__ import annotations

import argparse
import sys

from .. import service
from ..kernel import Orchestrator
from ..memory import MemoryStore
from ..registry import Registry, BotStub
from ..snapshots import make_snapshot
from ..portfolio import analyze as portfolio_analyze
from ..portfolio import portfolio as portfolio_mod
from ..research.fx import histdata as fx_histdata
from ..research.fx import regime as fx_regime


def _run(args):
    hyp, rec, v = service.run_experiment(args.hypothesis, root=args.root,
                                         window=args.window, mc=not args.no_mc)
    print(f"hypothesis {hyp.id} v{hyp.version}  [{hyp.status}]  "
          f"prereg={hyp.preregistration_hash}")
    print(f"experiment {rec.id}  window={rec.window}  verdict={rec.verdict}")
    m = rec.metrics
    if m.get("trades"):
        print(f"  trades {m['trades']} | PF {m['profit_factor']} | "
              f"exp {m['expectancy_r']}R | total {m['total_r']}R")
    else:
        print("  NO TRADES (no dataset, or none matched the window)")
    print(f"  recorded in {args.root}/atlas_memory.db and mirrored to "
          f"{args.root}/vault/experiments/{rec.id}.md")


def _experiments(args):
    store = MemoryStore(args.root)
    try:
        for r in store.list_experiments():
            print(f"{r.created_at}  {r.id}  {r.hypothesis_id} [{r.window}] "
                  f"-> {r.verdict}")
    finally:
        store.close()


def _registry(args):
    reg = Registry(args.root)
    try:
        if args.action == "list":
            for r in reg.list():
                en = r.monitoring_state.get("enabled", True)
                print(f"{r.strategy_id}  {r.status}  v{r.version}  "
                      f"alloc={r.allocation}  enabled={en}")
        elif args.action == "export":
            for e in reg.export_json():
                print(e)
            if not reg.export_json():
                print("(nothing approved for execution)")
    finally:
        reg.close()


def _bot(args):
    reg = Registry(args.root)
    try:
        for line in BotStub().plan(reg.export_json()):
            print(line)
    finally:
        reg.close()


def _council(args):
    res = Orchestrator(args.root).run(args.hypothesis, window=args.window)
    h, e = res["hypothesis"], res["experiment"]
    print(f"hypothesis {h.id} v{h.version} [{h.status}]  experiment {e.id}  "
          f"verdict {e.verdict}")
    print("decision ladder:")
    for d in res["decisions"]:
        print(f"  [{d.phase}] {d.agent}: {d.decision}  — {d.evidence[:90]}")
    print(f"reached layer: {res['reached_layer']}  ·  advanced: {res['advanced']}")
    if res.get("candidate_id"):
        print(f"registered candidate: {res['candidate_id']} (promotion is human-gated)")
    print(f"halt: {res['halt_reason']}")
    print(f"memo: {res['memo']}")


def _portfolio(args):
    import os as _os
    book = {}
    for hp in args.hypotheses:
        name = _os.path.splitext(_os.path.basename(hp))[0]
        book[name] = service.hypothesis_trades(hp, root=args.root, window=args.window)
    print(portfolio_mod.render(portfolio_analyze(book)), end="")


def _governance(args):
    from ..governance import budget_status, OOSBudget
    store = MemoryStore(args.root)
    try:
        snaps = store.list_snapshots()
        if not snaps:
            print("no snapshots recorded yet")
            return
        print("OUT-OF-SAMPLE BUDGET (looks per holdout)")
        for s in snaps:
            b = budget_status(store, s.id, "out_sample", OOSBudget())
            flag = "  <-- BURNED (refresh data)" if b["burned"] else ""
            print(f"  {s.id}  {b['count']}/{b['budget']} looks  "
                  f"[{s.symbols} {s.timeframe}]{flag}")
    finally:
        store.close()


def _graveyard(args):
    store = MemoryStore(args.root)
    try:
        rows = store.list_graveyard()
        if not rows:
            print("graveyard is empty")
            return
        for r in rows:
            print(f"{r['at']}  {r['hypothesis_id']}  {r['title']}\n    {r['reason'][:100]}")
    finally:
        store.close()


def _regime(args):
    report = service.regime_report(args.hypothesis, root=args.root, window=args.window)
    if not report:
        print("no trades / no data")
        return
    for sym, bd in report.items():
        print(f"\n[{sym}]")
        print(fx_regime.render(bd), end="")


def _data(args):
    import os as _os
    ds = _os.path.join(args.root, "datasets")
    if args.action == "import-histdata":
        path = fx_histdata.import_histdata(args.paths, ds, args.symbol)
        print(f"imported -> {path}")
    elif args.action == "snapshot":
        snap = make_snapshot(ds, args.symbols, args.timeframe,
                             source=f"datasets:{_os.path.abspath(ds)}")
        store = MemoryStore(args.root)
        try:
            snap = store.write_snapshot(snap)
        finally:
            store.close()
        print(f"snapshot {snap.id}  symbols={snap.symbols}  rows={snap.row_count}")
        print(f"  span {snap.span[0]} -> {snap.span[1]}  hash={snap.content_hash}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="atlas")
    p.add_argument("--root", default=".", help="Atlas data root (db + vault + datasets)")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="run a hypothesis -> immutable experiment record")
    r.add_argument("hypothesis")
    r.add_argument("--window", default="out_sample",
                   choices=["out_sample", "in_sample", "full"])
    r.add_argument("--no-mc", action="store_true")
    r.set_defaults(func=_run)

    e = sub.add_parser("experiments", help="list recorded experiments")
    e.set_defaults(func=_experiments)

    rg = sub.add_parser("registry", help="inspect the strategy registry")
    rg.add_argument("action", choices=["list", "export"])
    rg.set_defaults(func=_registry)

    b = sub.add_parser("bot", help="what the stub executor WOULD run (no orders)")
    b.set_defaults(func=_bot)

    gv = sub.add_parser("governance", help="out-of-sample budget / multiple-testing ledger")
    gv.set_defaults(func=_governance)

    gy = sub.add_parser("graveyard", help="list buried (rejected) hypotheses")
    gy.set_defaults(func=_graveyard)

    co = sub.add_parser("council", help="run the decision ladder (orchestrator + agents)")
    co.add_argument("hypothesis")
    co.add_argument("--window", default="out_sample",
                    choices=["out_sample", "in_sample", "full"])
    co.set_defaults(func=_council)

    pf = sub.add_parser("portfolio", help="portfolio analysis across hypotheses")
    pf.add_argument("hypotheses", nargs="+")
    pf.add_argument("--window", default="full",
                    choices=["out_sample", "in_sample", "full"])
    pf.set_defaults(func=_portfolio)

    rg2 = sub.add_parser("regime", help="per-regime performance breakdown of a hypothesis")
    rg2.add_argument("hypothesis")
    rg2.add_argument("--window", default="full",
                     choices=["out_sample", "in_sample", "full"])
    rg2.set_defaults(func=_regime)

    dp = sub.add_parser("data", help="data foundation: import HistData, take snapshots")
    dp.add_argument("action", choices=["import-histdata", "snapshot"])
    dp.add_argument("--symbol", help="symbol for import-histdata (e.g. GBPUSD)")
    dp.add_argument("--paths", nargs="+", help="HistData .csv/.zip files or a glob")
    dp.add_argument("--symbols", nargs="+", help="symbols for snapshot")
    dp.add_argument("--timeframe", default="M5", help="timeframe for snapshot")
    dp.set_defaults(func=_data)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
