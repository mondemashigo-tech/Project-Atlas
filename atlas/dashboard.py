"""Self-contained HTML report / dashboard for a hypothesis run.

One file, no external assets, no JS libraries — inline SVG charts (see
`charts.py`) and a few lines of vanilla JS for the tabs. Opens in any browser
and prints straight to PDF. Tabs: Overview, Walk-forward, Monte Carlo, Trades,
Journal. Theme is GitHub-dark to match the operator's other tooling.
"""
from __future__ import annotations

import html
from typing import Dict, List

from . import charts
from .metrics import verdict

_VERDICT_COLOUR = {"PASS": "#3fb950", "REJECT": "#f85149",
                   "INCONCLUSIVE": "#d29922", "NO_TRADES": "#8b949e",
                   "NO DATA": "#8b949e"}


def _esc(x) -> str:
    return html.escape(str(x))


def _stat(label: str, value, sub: str = "") -> str:
    subhtml = f'<div class="sub">{_esc(sub)}</div>' if sub else ""
    return (f'<div class="stat"><div class="lbl">{_esc(label)}</div>'
            f'<div class="val">{_esc(value)}</div>{subhtml}</div>')


def _metrics_row(m: dict) -> str:
    if not m.get("trades"):
        return '<div class="stats"><div class="stat"><div class="val">no trades</div></div></div>'
    pf = m["profit_factor"]
    exp = m["expectancy_r"]
    return '<div class="stats">' + "".join([
        _stat("Trades", m["trades"]),
        _stat("Win rate", f"{m['win_rate']}%"),
        _stat("Profit factor", pf, "PF>1 = profitable"),
        _stat("Expectancy", f"{exp}R", "per trade"),
        _stat("Total", f"{m['total_r']}R"),
        _stat("Max DD", f"{m['max_drawdown_r']}R"),
        _stat("Sharpe", m["sharpe_per_trade"], "per trade"),
    ]) + "</div>"


def _verdict_badge(v: dict) -> str:
    res = v.get("result", "NO DATA")
    col = _VERDICT_COLOUR.get(res, "#8b949e")
    items = "".join(f'<li class="ok">PASS &nbsp;{_esc(p)}</li>' for p in v.get("passed", []))
    items += "".join(f'<li class="no">FAIL &nbsp;{_esc(f)}</li>' for f in v.get("failed", []))
    lst = f'<ul class="crit">{items}</ul>' if items else ""
    return (f'<span class="badge" style="background:{col}22;color:{col};'
            f'border:1px solid {col}">{_esc(res)}</span>{lst}')


def _per_market_table(per_market: dict) -> str:
    rows = ""
    for sym, m in (per_market or {}).items():
        if not m.get("trades"):
            rows += f"<tr><td>{_esc(sym)}</td><td colspan='5'>no trades</td></tr>"
            continue
        rows += (f"<tr><td>{_esc(sym)}</td><td>{m['trades']}</td>"
                 f"<td>{m['win_rate']}%</td><td>{m['profit_factor']}</td>"
                 f"<td>{m['expectancy_r']}R</td><td>{m['total_r']}R</td></tr>")
    if not rows:
        return ""
    return ('<table><thead><tr><th>Market</th><th>Trades</th><th>WR</th>'
            '<th>PF</th><th>Exp</th><th>Total</th></tr></thead>'
            f'<tbody>{rows}</tbody></table>')


def _trades_table(trades: List, limit: int = 300) -> str:
    if not trades:
        return "<p class='muted'>No trades.</p>"
    rows = ""
    for t in trades[:limit]:
        cls = "win" if t.pnl_r > 0 else ("loss" if t.pnl_r < 0 else "")
        rows += (f"<tr class='{cls}'><td>{_esc(t.symbol)}</td><td>{_esc(t.direction)}</td>"
                 f"<td>{_esc(t.entry_time)}</td><td>{t.entry}</td><td>{t.stop}</td>"
                 f"<td>{t.target}</td><td>{_esc(t.exit_reason)}</td>"
                 f"<td>{t.pnl_r}R</td></tr>")
    more = (f"<p class='muted'>Showing first {limit} of {len(trades)} trades.</p>"
            if len(trades) > limit else "")
    return ('<table><thead><tr><th>Sym</th><th>Dir</th><th>Entry time</th>'
            '<th>Entry</th><th>Stop</th><th>Target</th><th>Exit</th><th>P/L</th>'
            f'</tr></thead><tbody>{rows}</tbody></table>{more}')


def _wf_tab(wf: dict) -> str:
    if not wf:
        return "<p class='muted'>Run <code>atlas wf</code> to populate walk-forward.</p>"
    if wf.get("error"):
        return f"<p class='muted'>{_esc(wf['error'])}</p>"
    rows = ""
    for f in wf["folds"]:
        im, om = f["is"], f["oos"]
        rows += (f"<tr><td>{f['fold']}</td>"
                 f"<td>{_esc(f['is_range'][0])}&rarr;{_esc(f['is_range'][1])}</td>"
                 f"<td>{_esc(f['oos_range'][0])}&rarr;{_esc(f['oos_range'][1])}</td>"
                 f"<td>{_esc(f['chosen']) if f['chosen'] else '&mdash;'}</td>"
                 f"<td>{im.get('trades',0)} / {om.get('trades',0)}</td>"
                 f"<td>{om.get('profit_factor','-')}</td>"
                 f"<td>{om.get('expectancy_r','-')}R</td>"
                 f"<td>{om.get('total_r','-')}R</td></tr>")
    agg = wf["aggregate_oos"]
    wfe = wf["walk_forward_efficiency"]
    return (
        '<div class="stats">'
        + _stat("Walk-forward efficiency", wfe if wfe is not None else "n/a",
                "mean OOS exp / mean IS exp")
        + _stat("Consistency", wf["consistency"], "fraction of folds OOS-positive")
        + _stat("OOS trades", agg.get("trades", 0))
        + _stat("OOS total", f"{agg.get('total_r', 0)}R")
        + "</div>"
        + '<table><thead><tr><th>Fold</th><th>In-sample</th><th>Out-of-sample</th>'
        '<th>Chosen</th><th>IS/OOS trades</th><th>OOS PF</th><th>OOS Exp</th>'
        f'<th>OOS Total</th></tr></thead><tbody>{rows}</tbody></table>')


def _mc_tab(mc: dict) -> str:
    if not mc or mc.get("trades", 0) == 0:
        return "<p class='muted'>Run <code>atlas mc</code> (or <code>run --mc</code>) to populate Monte Carlo.</p>"
    b, s = mc["bootstrap"], mc["shuffle"]

    def band(d):
        return _stat(f"", f"{d['p50']}", f"p5 {d['p5']} … p95 {d['p95']}")

    cards = '<div class="stats">' + "".join([
        _stat("P(total < 0)", b["p_total_negative"], "bootstrap"),
        _stat("P(expectancy < 0)", b["p_expectancy_negative"], "bootstrap"),
        _stat("Median total", f"{b['total_r']['p50']}R", f"p5 {b['total_r']['p5']} … p95 {b['total_r']['p95']}"),
        _stat("Median PF", b["profit_factor"]["p50"], f"p5 {b['profit_factor']['p5']} … p95 {b['profit_factor']['p95']}"),
        _stat("Realised max DD", f"{s['realised_max_drawdown_r']}R"),
        _stat("P(DD ≥ realised)", s["p_worse_than_realised"], "shuffle"),
    ]) + "</div>"
    # histograms need the raw sim arrays; we only kept percentiles, so draw the
    # percentile bands as labelled mini-cards above. The equity curve on Overview
    # already shows the realised path.
    note = ("<p class='muted'>Bootstrap resamples trades with replacement "
            f"({b['n_sims']} sims on {mc['trades']} trades); shuffle permutes their order. "
            "A real edge keeps P(total&lt;0) low and shows the realised drawdown near "
            "the middle of the shuffle distribution, not the lucky tail.</p>")
    return cards + note


def _journal_tab(records: List[dict]) -> str:
    if not records:
        return "<p class='muted'>No journal entries yet. Every <code>atlas run</code> appends one.</p>"
    rows = ""
    for r in reversed(records):
        o = r.get("out_sample", {})
        res = r.get("verdict_out", "-")
        col = _VERDICT_COLOUR.get(res, "#8b949e")
        rows += (f"<tr><td>{_esc(r['ts'])}</td><td>{_esc(r['name'])} v{_esc(r['version'])}</td>"
                 f"<td><code>{_esc(r['fingerprint'])}</code></td>"
                 f"<td>{o.get('trades','-')}</td><td>{o.get('profit_factor','-')}</td>"
                 f"<td>{o.get('expectancy_r','-')}R</td>"
                 f"<td style='color:{col}'>{_esc(res)}</td></tr>")
    return ('<table><thead><tr><th>When (UTC)</th><th>Hypothesis</th><th>Fingerprint</th>'
            '<th>OOS trades</th><th>OOS PF</th><th>OOS Exp</th><th>Verdict</th>'
            f'</tr></thead><tbody>{rows}</tbody></table>')


def render(cfg: dict, results: dict, mc: dict = None, wf: dict = None,
           journal_records: List[dict] = None) -> str:
    crit = cfg.get("criteria", {})
    v_out = verdict(results["out_sample"]["metrics"], crit)
    oos_trades = results["out_sample"]["trades"]
    equity = charts.equity_curve_svg([t.pnl_r for t in oos_trades])

    title = _esc(cfg["name"])
    sub = (f"{_esc(', '.join(cfg['markets']))} &nbsp;·&nbsp; "
           f"bias {_esc(cfg['timeframes']['bias'])} / entry {_esc(cfg['timeframes']['entry'])} "
           f"&nbsp;·&nbsp; session {_esc(cfg['session']['start'])}-{_esc(cfg['session']['end'])} "
           f"{_esc(cfg['session'].get('tz', 'UTC'))}")

    overview = (
        '<h3>Out-of-sample verdict</h3>'
        + _verdict_badge(v_out)
        + '<h3>Out-of-sample metrics</h3>' + _metrics_row(results["out_sample"]["metrics"])
        + '<h3>Out-of-sample equity curve</h3>'
        + f'<div class="chart">{equity}</div>'
        + '<h3>In-sample metrics (for inspection only)</h3>'
        + _metrics_row(results["in_sample"]["metrics"])
        + '<h3>Per market (out-of-sample)</h3>'
        + (_per_market_table(results["out_sample"].get("per_market")) or
           "<p class='muted'>—</p>"))

    tabs = [
        ("Overview", overview),
        ("Walk-forward", _wf_tab(wf)),
        ("Monte Carlo", _mc_tab(mc)),
        ("Trades", _trades_table(oos_trades)),
        ("Journal", _journal_tab(journal_records or [])),
    ]
    nav = "".join(
        f'<button class="tabbtn{" active" if i == 0 else ""}" '
        f'onclick="showTab({i})">{_esc(name)}</button>'
        for i, (name, _) in enumerate(tabs))
    panels = "".join(
        f'<section class="tab{" active" if i == 0 else ""}" id="tab{i}">{body}</section>'
        for i, (_, body) in enumerate(tabs))

    return _TEMPLATE.format(title=title, sub=sub, nav=nav, panels=panels)


_TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Atlas — {title}</title>
<style>
  :root {{ color-scheme: dark; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; background:#0d1117; color:#c9d1d9;
    font:14px/1.5 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif; }}
  header {{ padding:22px 26px 14px; border-bottom:1px solid #21262d; }}
  h1 {{ margin:0; font-size:20px; letter-spacing:.2px; }}
  h1 .atlas {{ color:#58a6ff; }}
  .subtitle {{ color:#8b949e; margin-top:4px; font-size:13px; }}
  h3 {{ margin:22px 0 8px; font-size:13px; text-transform:uppercase;
    letter-spacing:.6px; color:#8b949e; font-weight:600; }}
  nav {{ display:flex; gap:4px; padding:10px 26px 0; border-bottom:1px solid #21262d;
    position:sticky; top:0; background:#0d1117; flex-wrap:wrap; }}
  .tabbtn {{ background:none; border:0; color:#8b949e; padding:9px 14px;
    font-size:13px; cursor:pointer; border-bottom:2px solid transparent; }}
  .tabbtn:hover {{ color:#c9d1d9; }}
  .tabbtn.active {{ color:#c9d1d9; border-bottom-color:#f78166; }}
  main {{ padding:8px 26px 60px; max-width:1080px; }}
  .tab {{ display:none; }} .tab.active {{ display:block; }}
  .stats {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(150px,1fr));
    gap:10px; margin:6px 0 4px; }}
  .stat {{ background:#161b22; border:1px solid #21262d; border-radius:8px; padding:12px 14px; }}
  .stat .lbl {{ color:#8b949e; font-size:11px; text-transform:uppercase; letter-spacing:.5px; }}
  .stat .val {{ font-size:22px; font-weight:600; margin-top:3px; }}
  .stat .sub {{ color:#6e7681; font-size:11px; margin-top:2px; }}
  .badge {{ display:inline-block; padding:5px 14px; border-radius:999px;
    font-weight:700; letter-spacing:.5px; font-size:14px; }}
  ul.crit {{ list-style:none; padding:0; margin:10px 0 0; font-size:12px; }}
  ul.crit li {{ padding:2px 0; }} .crit .ok {{ color:#3fb950; }} .crit .no {{ color:#f85149; }}
  table {{ width:100%; border-collapse:collapse; margin:6px 0; font-size:12.5px; }}
  th,td {{ text-align:left; padding:6px 10px; border-bottom:1px solid #21262d; }}
  th {{ color:#8b949e; font-weight:600; }}
  tr.win td:last-child {{ color:#3fb950; }} tr.loss td:last-child {{ color:#f85149; }}
  .chart {{ background:#161b22; border:1px solid #21262d; border-radius:8px; padding:12px; }}
  .muted {{ color:#6e7681; }} code {{ background:#161b22; padding:1px 5px; border-radius:4px; }}
  footer {{ color:#6e7681; font-size:11px; padding:18px 26px; border-top:1px solid #21262d; }}
  @media print {{ nav {{ display:none; }} .tab {{ display:block !important; }}
    body {{ background:#fff; color:#000; }} }}
</style></head>
<body>
<header><h1><span class="atlas">ATLAS</span> · {title}</h1>
<div class="subtitle">{sub}</div></header>
<nav>{nav}</nav>
<main>{panels}</main>
<footer>Generated by Project Atlas · out-of-sample is the verdict; in-sample is for inspection only.</footer>
<script>
function showTab(n){{
  document.querySelectorAll('.tab').forEach((s,i)=>s.classList.toggle('active',i===n));
  document.querySelectorAll('.tabbtn').forEach((b,i)=>b.classList.toggle('active',i===n));
}}
</script>
</body></html>"""
