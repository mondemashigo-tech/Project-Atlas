"""Atlas CLI — thin adapter over the library.

    python -m atlas run <hypothesis.yaml>     # research -> immutable ExperimentRecord + vault mirror
    python -m atlas experiments                # list recorded experiments
    python -m atlas registry list|export       # inspect the airlock
    python -m atlas bot                         # what the stub executor WOULD run (no orders)

The FX research module keeps its own CLI at `python -m atlas.research.fx.cli`.
"""
from __future__ import annotations

import argparse
import os
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
    res = Orchestrator(args.root).run(args.hypothesis, window=args.window,
                                      data_utc_offset=args.data_utc_offset)
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


def _scout(args):
    from ..scout import Scout
    extractor = None
    # Use the LLM extractor when asked, or auto-detect a key unless --no-llm.
    want_llm = args.llm or (not args.no_llm and os.environ.get("ANTHROPIC_API_KEY"))
    if want_llm:
        from ..scout.llm import anthropic_extractor
        try:
            extractor = anthropic_extractor(model=args.llm_model)
            print(f"  reader   : LLM ({args.llm_model})")
        except Exception as e:
            print(f"  reader   : heuristic (LLM unavailable: {e})")
    sc = Scout(extractor=extractor)
    if args.test:
        info = sc.scout_and_test(args.source, root=args.root, markets=args.markets,
                                 data_utc_offset=args.data_utc_offset)
    else:
        info = sc.scout(args.source, root=args.root, markets=args.markets)
    print(f"scouted: {info['name']}")
    print(f"  template : {info['template']}")
    print(f"  extracted: {info['evidence']}")
    print(f"  hypothesis written -> {info['path']}")
    if args.test:
        print(f"  VERDICT  : {info['verdict']}  (reached {info['reached_layer']}, "
              f"advanced={info['advanced']})")
    else:
        print(f"  run it:  py -m atlas council {info['path']} --window out_sample")


def _discover(args):
    from ..scout import Scout
    from ..scout.discover import anthropic_searcher
    # the LLM reader is the right partner for discovered prose; auto-use if keyed
    extractor = None
    if not args.no_llm and (args.llm or os.environ.get("ANTHROPIC_API_KEY")):
        from ..scout.llm import anthropic_extractor
        try:
            extractor = anthropic_extractor(model=args.llm_model)
        except Exception as e:
            print(f"  reader   : heuristic (LLM unavailable: {e})")
    fx_only = not args.all_markets
    try:
        searcher = anthropic_searcher(model=args.llm_model,
                                      max_searches=args.max_searches,
                                      fx_only=fx_only)
    except Exception as e:
        print(f"discovery unavailable: {e}")
        print("Set ANTHROPIC_API_KEY and `pip install anthropic` to let the "
              "Scout find its own URLs.")
        return
    sc = Scout(extractor=extractor)
    scope = "forex-only" if fx_only else "all markets"
    print(f"searching the web for: {args.query!r}  ({scope}, up to {args.max} sources)")
    out = sc.discover(args.query, root=args.root, markets=args.markets,
                      max_results=args.max, test=args.test, fx_only=fx_only,
                      data_utc_offset=args.data_utc_offset, searcher=searcher)
    if not out["urls"]:
        print("no candidate URLs found.")
    for url in out["urls"]:
        print(f"  found: {url}")
    print(f"\nscouted {len(out['results'])} source(s):")
    for info in out["results"]:
        line = f"  {info['template']:18s} <- {info.get('source', info['name'])}"
        if args.test:
            line += f"  VERDICT {info['verdict']} (reached {info['reached_layer']})"
        print(line)
        print(f"      hypothesis -> {info['path']}")
    for sk in out.get("skipped", []):
        print(f"  off-market, skipped: {sk['url']}  ({sk['reason']})")
    for err in out["errors"]:
        print(f"  error, skipped: {err['url']}  ({err['error']})")
    if not args.test and out["results"]:
        print("\nrun the whole batch through the council with --test next time.")


def _invent(args):
    import yaml
    from ..agents.inventor import Inventor
    generator = None
    want_llm = args.llm or (not args.no_llm and os.environ.get("ANTHROPIC_API_KEY"))
    if want_llm:
        from ..agents.inventor import anthropic_generator
        try:
            generator = anthropic_generator(model=args.llm_model)
            print(f"  designer : LLM ({args.llm_model})")
        except Exception as e:
            print(f"  designer : seeded library (LLM unavailable: {e})")
    else:
        print("  designer : seeded library")

    cfgs = Inventor(generator).invent(theme=args.theme, markets=args.markets,
                                      n=args.n)
    if not cfgs:
        print("no valid strategies invented.")
        return
    d = os.path.join(args.root, "hypotheses", "invented")
    os.makedirs(d, exist_ok=True)
    print(f"invented {len(cfgs)} composed strateg(ies) on theme {args.theme!r}:")
    for cfg in cfgs:
        path = os.path.join(d, f"{cfg['name']}.yaml")
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(cfg, f, sort_keys=False)
        print(f"\n  {cfg['name']}  — {cfg.get('note', 'composed')}")
        print(f"      hypothesis -> {path}")
        if args.test:
            res = Orchestrator(args.root).run(path, window="out_sample",
                                              data_utc_offset=args.data_utc_offset)
            print(f"      VERDICT {res['experiment'].verdict} "
                  f"(reached {res['reached_layer']}, advanced={res['advanced']})")
    if not args.test:
        print("\n  test them:  py -m atlas council <path> --window out_sample")


def _ingest(args):
    from ..agents import Librarian
    store = MemoryStore(args.root)
    try:
        notes = Librarian().ingest(args.path, store)
        for n in notes:
            print(f"{n.id}  {n.title}  tags={n.topic_tags}")
        print(f"ingested {len(notes)} note(s) into {args.root}/vault/knowledge/")
    finally:
        store.close()


def _propose(args):
    from ..agents import Scientist
    from ..research.fx import config as fx_config
    base = fx_config.load(args.base)
    store = MemoryStore(args.root)
    try:
        sci = Scientist()
        scored = sci.prioritise(sci.propose(base), store)
        print(sci.render(scored), end="")
    finally:
        store.close()


def _loop(args):
    from ..lab import ResearchLoop
    loop = ResearchLoop(root=args.root, autonomy_level=args.autonomy,
                        max_per_cycle=args.max_per_cycle,
                        data_utc_offset=args.data_utc_offset)
    for r in loop.run(args.base, cycles=args.cycles, window=args.window):
        print(f"cycle [L{r['autonomy_level']}] proposed {r['proposed']} "
              f"selected {r['selected']} tested {len(r['tested'])} "
              f"candidates {len(r['candidates'])}")
        for t in r["tested"]:
            print(f"  {t['name']}: {t['verdict']} "
                  f"(reached {t['reached']}, advanced={t['advanced']})")
        if r.get("note"):
            print(f"  note: {r['note']}")
        print(f"  report: {r.get('report_path')}")
    print("NOTE: the loop never promotes to capital — that stays human-gated.")


def _monitor(args):
    from ..lab import monitor
    reg = Registry(args.root)
    try:
        rows = monitor(reg)
        if not rows:
            print("no executable strategies to monitor (nothing promoted to capital)")
        for r in rows:
            print(r)
    finally:
        reg.close()


def _dashboard(args):
    import os as _os
    from . import dashboard as dash
    if args.serve:
        import http.server
        root, port, refresh = args.root, args.port, args.refresh

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                body = dash.render(root, refresh_secs=refresh).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        srv = http.server.HTTPServer(("127.0.0.1", port), H)
        print(f"Atlas dashboard live at  http://127.0.0.1:{port}  "
              f"(auto-refresh {refresh}s)\nPress Ctrl+C to stop.")
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped.")
    else:
        out = _os.path.join(args.root, "atlas_dashboard.html")
        with open(out, "w", encoding="utf-8") as f:
            f.write(dash.render(args.root))
        print(f"wrote {out}  — open it in a browser (re-run to refresh)")


def _architect(args):
    from ..agents import Architect
    store = MemoryStore(args.root)
    try:
        print(Architect().report(store), end="")
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
    from ..research.fx.data import load_csv, resample
    ds = _os.path.join(args.root, "datasets")
    if args.action == "import-histdata":
        path = fx_histdata.import_histdata(args.paths, ds, args.symbol)
        print(f"imported -> {path}")
        for tf in (args.resample or []):
            r = resample(load_csv(path), tf)
            outp = _os.path.join(ds, f"{args.symbol.upper()}_{tf.upper()}.csv")
            r.reset_index().to_csv(outp, index=False)
            print(f"resampled {len(r)} bars -> {outp}")
    elif args.action == "resample":
        src = _os.path.join(ds, f"{args.symbol.upper()}_{args.timeframe.upper()}.csv")
        for tf in (args.resample or []):
            r = resample(load_csv(src), tf)
            outp = _os.path.join(ds, f"{args.symbol.upper()}_{tf.upper()}.csv")
            r.reset_index().to_csv(outp, index=False)
            print(f"resampled {len(r)} bars -> {outp}")
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

    ar = sub.add_parser("architect", help="lab health + structural suggestions")
    ar.set_defaults(func=_architect)

    db = sub.add_parser("dashboard", help="visual dashboard of the live lab state")
    db.add_argument("--serve", action="store_true", help="run a live local web server")
    db.add_argument("--port", type=int, default=8787)
    db.add_argument("--refresh", type=int, default=15, help="serve auto-refresh seconds")
    db.set_defaults(func=_dashboard)

    lp = sub.add_parser("loop", help="governed research loop (propose->test->record)")
    lp.add_argument("base", help="base hypothesis YAML")
    lp.add_argument("--cycles", type=int, default=1)
    lp.add_argument("--autonomy", type=int, default=3, help="autonomy level (<=4)")
    lp.add_argument("--max-per-cycle", type=int, default=5, dest="max_per_cycle")
    lp.add_argument("--window", default="out_sample",
                    choices=["out_sample", "in_sample", "full"])
    lp.add_argument("--data-utc-offset", type=float, default=0, dest="data_utc_offset",
                    help="hours to subtract from data timestamps (broker time -> UTC)")
    lp.set_defaults(func=_loop)

    mn = sub.add_parser("monitor", help="decay/drift monitoring of executable strategies")
    mn.set_defaults(func=_monitor)

    sc = sub.add_parser("scout", help="Scout: source an idea (URL/file/text) -> hypothesis")
    sc.add_argument("source", help="a URL, a local file, or raw text")
    sc.add_argument("--markets", nargs="+", default=["GBPUSD", "USDJPY"])
    sc.add_argument("--test", action="store_true", help="also run it through the council")
    sc.add_argument("--data-utc-offset", type=float, default=0, dest="data_utc_offset")
    sc.add_argument("--llm", action="store_true",
                    help="force the LLM reader (needs ANTHROPIC_API_KEY)")
    sc.add_argument("--no-llm", action="store_true",
                    help="force the heuristic reader even if a key is set")
    sc.add_argument("--llm-model", default="claude-opus-5", dest="llm_model",
                    help="model for the LLM reader (default: claude-opus-5)")
    sc.set_defaults(func=_scout)

    dc = sub.add_parser("discover",
                        help="Scout: find its own URLs on a topic (web search) -> hypotheses")
    dc.add_argument("query", help="a topic, e.g. 'opening range breakout intraday forex'")
    dc.add_argument("--markets", nargs="+", default=["GBPUSD", "USDJPY"])
    dc.add_argument("--max", type=int, default=3, help="max sources to scout (default 3)")
    dc.add_argument("--max-searches", type=int, default=5, dest="max_searches",
                    help="max web searches the model may run (default 5)")
    dc.add_argument("--test", action="store_true", help="run each through the council")
    dc.add_argument("--all-markets", action="store_true", dest="all_markets",
                    help="don't restrict to forex (default: forex-only, fair on your FX data)")
    dc.add_argument("--data-utc-offset", type=float, default=0, dest="data_utc_offset")
    dc.add_argument("--llm", action="store_true", help="force the LLM reader")
    dc.add_argument("--no-llm", action="store_true", help="use the heuristic reader")
    dc.add_argument("--llm-model", default="claude-opus-5", dest="llm_model",
                    help="model for search + reader (default: claude-opus-5)")
    dc.set_defaults(func=_discover)

    iv = sub.add_parser("invent",
                        help="Inventor: design NEW composed strategies (mix indicators)")
    iv.add_argument("theme", nargs="?", default="",
                    help="a theme, e.g. 'trend plus momentum' or 'volatility mean reversion'")
    iv.add_argument("--markets", nargs="+", default=["GBPUSD", "USDJPY"])
    iv.add_argument("--n", type=int, default=3, help="how many to invent (default 3)")
    iv.add_argument("--test", action="store_true", help="run each through the council")
    iv.add_argument("--data-utc-offset", type=float, default=0, dest="data_utc_offset")
    iv.add_argument("--llm", action="store_true",
                    help="use the LLM designer (needs ANTHROPIC_API_KEY)")
    iv.add_argument("--no-llm", action="store_true",
                    help="use the seeded archetype library only")
    iv.add_argument("--llm-model", default="claude-opus-5", dest="llm_model")
    iv.set_defaults(func=_invent)

    ig = sub.add_parser("ingest", help="Librarian: ingest a file/dir into knowledge")
    ig.add_argument("path")
    ig.set_defaults(func=_ingest)

    pr = sub.add_parser("propose", help="Scientist: propose + rank hypothesis variants")
    pr.add_argument("base", help="base hypothesis YAML")
    pr.set_defaults(func=_propose)

    co = sub.add_parser("council", help="run the decision ladder (orchestrator + agents)")
    co.add_argument("hypothesis")
    co.add_argument("--window", default="out_sample",
                    choices=["out_sample", "in_sample", "full"])
    co.add_argument("--data-utc-offset", type=float, default=0, dest="data_utc_offset",
                    help="hours to subtract from data timestamps (broker time -> UTC)")
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

    dp = sub.add_parser("data", help="data foundation: import HistData, resample, snapshots")
    dp.add_argument("action", choices=["import-histdata", "resample", "snapshot"])
    dp.add_argument("--symbol", help="symbol for import-histdata/resample (e.g. GBPUSD)")
    dp.add_argument("--paths", nargs="+", help="HistData .csv/.zip files or a glob")
    dp.add_argument("--resample", nargs="+",
                    help="timeframes to resample to, e.g. M5 H1 (import writes M1 first)")
    dp.add_argument("--symbols", nargs="+", help="symbols for snapshot")
    dp.add_argument("--timeframe", default="M5",
                    help="source TF for resample / TF for snapshot")
    dp.set_defaults(func=_data)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
