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
from ..memory import MemoryStore
from ..registry import Registry, BotStub


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

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
