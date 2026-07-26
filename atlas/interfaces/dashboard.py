"""Local Atlas dashboard — a self-contained HTML view of the live lab state.

Reads the memory + registry SQLite databases at an Atlas root and renders one
tabbed, GitHub-dark page: Overview, Experiments, Graveyard, Registry, Governance,
Knowledge, Data. No external assets, no framework. Open the file in a browser, or
run `atlas dashboard --serve` for an auto-refreshing local page.
"""
from __future__ import annotations

import html

from ..memory import MemoryStore
from ..registry import Registry
from ..governance import budget_status, OOSBudget
from ..agents import Architect

_V = {"PASS": "#3fb950", "REJECT": "#f85149", "INCONCLUSIVE": "#d29922",
      "NO_TRADES": "#8b949e", None: "#8b949e"}
_S = {"candidate": "#8b949e", "paper": "#d29922", "micro_live": "#58a6ff",
      "live": "#3fb950", "retired": "#6e7681"}


def _e(x):
    return html.escape(str(x))


def _stat(label, value, sub=""):
    s = f'<div class="sub">{_e(sub)}</div>' if sub else ""
    return (f'<div class="stat"><div class="lbl">{_e(label)}</div>'
            f'<div class="val">{_e(value)}</div>{s}</div>')


def render(root: str = ".", refresh_secs: int = 0) -> str:
    store = MemoryStore(root)
    reg = Registry(root)
    try:
        counts = store.counts()
        exps = store.list_experiments(200)
        gy = store.list_graveyard()
        snaps = store.list_snapshots()
        know = store.list_knowledge()
        strategies = reg.list()
        executable = reg.export_json()
        arch = Architect()
        obs = arch.observe(store)
        suggestions = arch.suggestions(obs)

        # verdict tally
        vt = {}
        for e in exps:
            vt[e.verdict] = vt.get(e.verdict, 0) + 1

        # ---- Overview ----
        cards = '<div class="stats">' + "".join([
            _stat("Hypotheses", counts["hypotheses"]),
            _stat("Experiments", counts["experiments"]),
            _stat("Graveyard", counts["graveyard"], f"rate {obs['graveyard_rate']}"),
            _stat("Registry", len(strategies), f"{len(executable)} executable"),
            _stat("PASS", vt.get("PASS", 0)),
            _stat("REJECT", vt.get("REJECT", 0)),
        ]) + "</div>"
        sug = "".join(f"<li>{_e(s)}</li>" for s in suggestions)
        overview = (cards + "<h3>Lab health (Architect)</h3>"
                    f"<ul class='notes'>{sug}</ul>")

        # ---- Experiments ----
        rows = ""
        for e in exps:
            m = e.metrics or {}
            col = _V.get(e.verdict, "#8b949e")
            met = (f"T:{m['trades']} PF:{m.get('profit_factor')} "
                   f"exp:{m.get('expectancy_r')}R" if m.get("trades") else "no trades")
            rows += (f"<tr><td>{_e(e.created_at)}</td><td><code>{_e(e.id)}</code></td>"
                     f"<td>{_e(e.window)}</td><td>{_e(met)}</td>"
                     f"<td style='color:{col};font-weight:600'>{_e(e.verdict)}</td></tr>")
        experiments = (_table(["When", "Experiment", "Window", "Metrics", "Verdict"], rows)
                       if rows else _muted("No experiments yet. Run `atlas council` or `atlas loop`."))

        # ---- Graveyard ----
        rows = "".join(
            f"<tr><td>{_e(g['at'])}</td><td>{_e(g['title'])}</td>"
            f"<td class='muted'>{_e(g['reason'][:160])}</td></tr>" for g in gy)
        graveyard = (_table(["When", "Hypothesis", "Reason"], rows)
                     if rows else _muted("Graveyard empty."))

        # ---- Registry ----
        rows = ""
        for s in strategies:
            col = _S.get(s.status, "#8b949e")
            en = s.monitoring_state.get("enabled", True)
            rows += (f"<tr><td><code>{_e(s.strategy_id)}</code></td>"
                     f"<td style='color:{col};font-weight:600'>{_e(s.status)}</td>"
                     f"<td>v{s.version}</td><td>{_e(s.allocation)}</td>"
                     f"<td>{'yes' if en else 'no'}</td></tr>")
        registry = ((_table(["Strategy", "Status", "Ver", "Alloc", "Enabled"], rows)
                     if rows else _muted("No strategies registered."))
                    + f"<h3>Executable by the bot</h3>"
                    + (_muted("Nothing approved to capital (airlock closed).")
                       if not executable else
                       _table(["Strategy", "Status", "Alloc"],
                              "".join(f"<tr><td><code>{_e(x['strategy_id'])}</code></td>"
                                      f"<td>{_e(x['status'])}</td><td>{_e(x['allocation'])}"
                                      f"</td></tr>" for x in executable))))

        # ---- Governance ----
        rows = ""
        for s in snaps:
            b = budget_status(store, s.id, "out_sample", OOSBudget())
            flag = " ⚠ BURNED" if b["burned"] else ""
            rows += (f"<tr><td><code>{_e(s.id)}</code></td>"
                     f"<td>{_e(s.symbols)} {_e(s.timeframe)}</td>"
                     f"<td>{b['count']}/{b['budget']}{flag}</td>"
                     f"<td>{_e(s.span[0])} → {_e(s.span[1])}</td><td>{s.row_count}</td></tr>")
        governance = (_table(["Holdout snapshot", "Market", "OOS looks", "Span", "Rows"], rows)
                      if rows else _muted("No snapshots recorded yet."))

        # ---- Knowledge ----
        rows = "".join(
            f"<tr><td>{_e(k.title)}</td><td>{_e(', '.join(k.topic_tags))}</td>"
            f"<td class='muted'>{_e(k.summary[:140])}</td></tr>" for k in know)
        knowledge = (_table(["Title", "Tags", "Summary"], rows)
                     if rows else _muted("No knowledge ingested. Use `atlas ingest`."))

        tabs = [("Overview", overview), ("Experiments", experiments),
                ("Graveyard", graveyard), ("Registry", registry),
                ("Governance", governance), ("Knowledge", knowledge)]
        nav = "".join(f'<button class="tabbtn{" active" if i==0 else ""}" '
                      f'onclick="show({i})">{_e(n)}</button>'
                      for i, (n, _) in enumerate(tabs))
        panels = "".join(f'<section class="tab{" active" if i==0 else ""}" id="t{i}">{b}</section>'
                         for i, (_, b) in enumerate(tabs))
        meta = f'<meta http-equiv="refresh" content="{refresh_secs}">' if refresh_secs else ""
        return _TEMPLATE.format(nav=nav, panels=panels, meta=meta, root=_e(root))
    finally:
        store.close()
        reg.close()


def _table(headers, rows):
    h = "".join(f"<th>{_e(x)}</th>" for x in headers)
    return f'<table><thead><tr>{h}</tr></thead><tbody>{rows}</tbody></table>'


def _muted(msg):
    return f"<p class='muted'>{_e(msg)}</p>"


_TEMPLATE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">{meta}
<title>Atlas — research lab</title><style>
*{{box-sizing:border-box}} body{{margin:0;background:#0d1117;color:#c9d1d9;
font:14px/1.5 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif}}
header{{padding:20px 26px 12px;border-bottom:1px solid #21262d}}
h1{{margin:0;font-size:20px}} h1 .a{{color:#58a6ff}}
.subtitle{{color:#8b949e;font-size:12px;margin-top:3px}}
h3{{margin:20px 0 8px;font-size:12px;text-transform:uppercase;letter-spacing:.6px;color:#8b949e}}
nav{{display:flex;gap:4px;padding:10px 26px 0;border-bottom:1px solid #21262d;flex-wrap:wrap;
position:sticky;top:0;background:#0d1117}}
.tabbtn{{background:none;border:0;color:#8b949e;padding:9px 14px;font-size:13px;cursor:pointer;
border-bottom:2px solid transparent}}
.tabbtn:hover{{color:#c9d1d9}} .tabbtn.active{{color:#c9d1d9;border-bottom-color:#f78166}}
main{{padding:8px 26px 60px;max-width:1100px}}
.tab{{display:none}} .tab.active{{display:block}}
.stats{{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px;margin:8px 0}}
.stat{{background:#161b22;border:1px solid #21262d;border-radius:8px;padding:12px 14px}}
.stat .lbl{{color:#8b949e;font-size:11px;text-transform:uppercase;letter-spacing:.5px}}
.stat .val{{font-size:24px;font-weight:600;margin-top:3px}} .stat .sub{{color:#6e7681;font-size:11px}}
table{{width:100%;border-collapse:collapse;margin:6px 0;font-size:12.5px}}
th,td{{text-align:left;padding:6px 10px;border-bottom:1px solid #21262d;vertical-align:top}}
th{{color:#8b949e}} code{{background:#161b22;padding:1px 5px;border-radius:4px;font-size:11px}}
.muted{{color:#6e7681}} ul.notes{{padding-left:18px}} ul.notes li{{margin:3px 0}}
footer{{color:#6e7681;font-size:11px;padding:16px 26px;border-top:1px solid #21262d}}
</style></head><body>
<header><h1><span class="a">ATLAS</span> · research lab</h1>
<div class="subtitle">live state from {root} — SQLite is the source of truth</div></header>
<nav>{nav}</nav><main>{panels}</main>
<footer>Out-of-sample is the verdict · nothing reaches capital without a human · nothing is deleted.</footer>
<script>function show(n){{document.querySelectorAll('.tab').forEach((s,i)=>s.classList.toggle('active',i===n));
document.querySelectorAll('.tabbtn').forEach((b,i)=>b.classList.toggle('active',i===n));}}</script>
</body></html>"""
