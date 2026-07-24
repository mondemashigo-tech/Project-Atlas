"""Dependency-free inline SVG charts for the HTML report.

No matplotlib, no JS charting library — we emit SVG markup directly so a report
is a single self-contained file that opens anywhere. Everything is in R units.
"""
from __future__ import annotations

from typing import List, Sequence

_AXIS = "#8b949e"
_GRID = "#30363d"
_UP = "#3fb950"
_DOWN = "#f85149"
_LINE = "#58a6ff"


def _pts(xs, ys):
    return " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))


def equity_curve_svg(pnl_r: Sequence[float], width: int = 720, height: int = 240,
                     pad: int = 34) -> str:
    """Cumulative equity (R) with a zero line and peak-to-trough shading."""
    equity, cum = [], 0.0
    for x in pnl_r:
        cum += x
        equity.append(cum)
    if not equity:
        return _empty(width, height, "no trades")
    lo = min(0.0, min(equity))
    hi = max(0.0, max(equity))
    span = (hi - lo) or 1.0
    n = len(equity)

    def X(i):
        return pad + (width - 2 * pad) * (i / max(1, n - 1))

    def Y(v):
        return pad + (height - 2 * pad) * (1 - (v - lo) / span)

    xs = [X(i) for i in range(n)]
    ys = [Y(v) for v in equity]
    zero_y = Y(0.0)
    final = equity[-1]
    colour = _UP if final >= 0 else _DOWN

    # area under the curve down to the zero line
    area = f"{xs[0]:.1f},{zero_y:.1f} " + _pts(xs, ys) + f" {xs[-1]:.1f},{zero_y:.1f}"
    return f"""<svg viewBox="0 0 {width} {height}" width="100%" preserveAspectRatio="xMidYMid meet" role="img">
  <rect x="0" y="0" width="{width}" height="{height}" fill="none"/>
  <line x1="{pad}" y1="{zero_y:.1f}" x2="{width-pad}" y2="{zero_y:.1f}" stroke="{_GRID}" stroke-dasharray="4 3"/>
  <polygon points="{area}" fill="{colour}" opacity="0.12"/>
  <polyline points="{_pts(xs, ys)}" fill="none" stroke="{colour}" stroke-width="2"/>
  <text x="{pad}" y="{pad-12}" fill="{_AXIS}" font-size="11">equity (R)</text>
  <text x="{width-pad}" y="{pad-12}" fill="{colour}" font-size="12" text-anchor="end">{final:+.1f}R</text>
  <text x="{pad-6}" y="{Y(hi)+4:.1f}" fill="{_AXIS}" font-size="10" text-anchor="end">{hi:.1f}</text>
  <text x="{pad-6}" y="{Y(lo)+4:.1f}" fill="{_AXIS}" font-size="10" text-anchor="end">{lo:.1f}</text>
</svg>"""


def histogram_svg(values: Sequence[float], bins: int = 24, width: int = 360,
                  height: int = 180, pad: int = 26, marker: float = None,
                  label: str = "") -> str:
    vals = [v for v in values if v is not None]
    if not vals:
        return _empty(width, height, "no data")
    lo, hi = min(vals), max(vals)
    if hi == lo:
        hi = lo + 1.0
    step = (hi - lo) / bins
    counts = [0] * bins
    for v in vals:
        k = min(bins - 1, int((v - lo) / step))
        counts[k] += 1
    cmax = max(counts) or 1
    bw = (width - 2 * pad) / bins
    bars = []
    for k, c in enumerate(counts):
        bh = (height - 2 * pad) * (c / cmax)
        x = pad + k * bw
        y = height - pad - bh
        bars.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{max(1,bw-1):.1f}" '
                    f'height="{bh:.1f}" fill="{_LINE}" opacity="0.7"/>')
    mark = ""
    if marker is not None and lo <= marker <= hi:
        mx = pad + (width - 2 * pad) * ((marker - lo) / (hi - lo))
        mark = (f'<line x1="{mx:.1f}" y1="{pad}" x2="{mx:.1f}" y2="{height-pad}" '
                f'stroke="{_DOWN}" stroke-width="2"/>'
                f'<text x="{mx:.1f}" y="{pad-4}" fill="{_DOWN}" font-size="10" '
                f'text-anchor="middle">{marker:.2f}</text>')
    return f"""<svg viewBox="0 0 {width} {height}" width="100%" preserveAspectRatio="xMidYMid meet" role="img">
  {''.join(bars)}
  {mark}
  <text x="{pad}" y="{height-6}" fill="{_AXIS}" font-size="10">{lo:.2f}</text>
  <text x="{width-pad}" y="{height-6}" fill="{_AXIS}" font-size="10" text-anchor="end">{hi:.2f}</text>
  <text x="{width/2:.0f}" y="{pad-8}" fill="{_AXIS}" font-size="11" text-anchor="middle">{label}</text>
</svg>"""


def _empty(width, height, msg):
    return (f'<svg viewBox="0 0 {width} {height}" width="100%" role="img">'
            f'<text x="{width/2:.0f}" y="{height/2:.0f}" fill="{_AXIS}" '
            f'font-size="12" text-anchor="middle">{msg}</text></svg>')
