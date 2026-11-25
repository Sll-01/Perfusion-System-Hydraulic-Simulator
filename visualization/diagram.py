"""Interactive hydraulic system diagram (Plotly).

Edges are coloured (single-hue sequential scale) and sized by |Q|; arrows show the flow
direction; component markers carry the edge id as customdata so that a click in the
Streamlit UI selects the component for editing. Also exported as static figure.
"""
from __future__ import annotations

import math

import numpy as np
import plotly.graph_objects as go

from core.units import ML_MIN

from .plots import SEQ, TEXT, style

SYMBOLS = {
    "pump": ("circle", 30, "#f47230"),
    "throttle": ("bowtie", 20, "#6a4ce2"),
    "reactor": ("square", 32, "#00b894"),
    "splitter_channel": ("diamond", 9, "#888888"),
    "tube": ("circle", 7, "#bbbbbb"),
    "tee": ("triangle-right", 12, "#888888"),
    "resistor": ("square", 10, "#888888"),
}


def _interp_color(t: float) -> str:
    stops = [(0.0, (207, 227, 250)), (0.5, (90, 160, 236)), (1.0, (11, 63, 134))]
    t = min(max(t, 0.0), 1.0)
    for (t0, c0), (t1, c1) in zip(stops, stops[1:]):
        if t <= t1:
            w = (t - t0) / (t1 - t0)
            return "#%02x%02x%02x" % tuple(round(a + w * (b - a)) for a, b in zip(c0, c1))
    return "#0b3f86"


def _positions(res):
    net = res.network
    pos = {n.id: n.pos for n in net.nodes.values()}
    if "S1" in pos:
        y_hub = pos["S1"][1]
        for nid, x in (("reservoir", 0.0), ("pump_in", 1.0), ("pump_out", 2.0)):
            pos[nid] = (x, y_hub)
    return pos


def _edge_path(e, pos, y_bottom):
    a, b = pos[e.from_node], pos[e.to_node]
    if e.id == "return_tube":
        x_r = max(a[0], b[0]) + 0.6
        return [a, (x_r, a[1]), (x_r, y_bottom), (pos["reservoir"][0], y_bottom), b]
    if a[1] != b[1] and abs(a[0] - b[0]) > 1e-9:  # orthogonal routing (manifold style)
        if e.kind in ("splitter_channel", "tee") and e.to_node not in ("S2", "tee2"):
            return [a, (a[0], b[1]), b]
        return [a, (b[0], a[1]), b]
    return [a, b]


def system_diagram(res, selected: str | None = None, show_labels: bool = True, height: int = 640) -> go.Figure:
    net = res.network
    pos = _positions(res)
    flows = res.solver.edge_flows
    p = res.solver.node_pressures
    qmax = max([abs(v) for v in flows.values() if np.isfinite(v)] + [1e-30])
    ys = [xy[1] for xy in pos.values()]
    y_bottom = min(ys) - 1.0
    fig = go.Figure()
    marker_x, marker_y, marker_sym, marker_size, marker_col, marker_id, marker_text, marker_line = [], [], [], [], [], [], [], []
    annotations = []
    for e in net.edges.values():
        q = flows.get(e.id, 0.0)
        closed = e.is_closed()
        frac = abs(q) / qmax if np.isfinite(q) else 0
        color = "#d0d0d0" if closed or frac < 1e-9 else _interp_color(0.15 + 0.85 * frac)
        width = 1.5 if closed else 1.5 + 7.0 * frac
        path = _edge_path(e, pos, y_bottom)
        xs, ys_ = zip(*path)
        fig.add_trace(go.Scatter(x=xs, y=ys_, mode="lines", line=dict(color=color, width=width, dash="dot" if closed else "solid"),
                                 hoverinfo="skip", showlegend=False))
        # marker in the middle of the longest straight sub-segment
        segs = list(zip(path, path[1:]))
        (x0, y0), (x1, y1) = max(segs, key=lambda s: math.hypot(s[1][0] - s[0][0], s[1][1] - s[0][1]))
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        sym, size, col = SYMBOLS.get(e.kind, ("circle", 8, "#999"))
        row = res.edges[res.edges.id == e.id].iloc[0]
        pa, pb = p.get(e.from_node, math.nan), p.get(e.to_node, math.nan)
        info = [f"<b>{e.label}</b>", f"Q = {q / ML_MIN:.4g} mL/min" + (" (closed)" if closed else ""),
                f"p_in = {pa/100:.3f} mbar, p_out = {pb/100:.3f} mbar"]
        if e.is_pump:
            info.append(f"pump dp = {(pb - pa)/100:.3f} mbar")
        else:
            info.append(f"dp = {(pa - pb):.4g} Pa")
        if e.kind == "tube":
            info.append(f"ID = {e.element.inner_diameter_mm:.3g} mm, L = {e.element.length_m:.3g} m, Re = {row.get('Re', float('nan')):.3g}")
        if e.kind == "throttle":
            info.append(f"opening = {e.element.opening_percent:.0f} %  ({e.element.model})")
        if e.kind == "reactor":
            info.append(f"state = {e.element.state}")
        marker_x.append(mx)
        marker_y.append(my)
        marker_sym.append(sym)
        marker_size.append(size)
        marker_col.append(col if not closed else "#cccccc")
        marker_id.append(e.id)
        marker_text.append("<br>".join(info))
        marker_line.append(3 if e.id == selected else 1)
        # flow direction arrow
        if not closed and abs(q) > 1e-6 * qmax and math.hypot(x1 - x0, y1 - y0) > 0.3:
            d = 1 if q > 0 else -1
            ux, uy = (x1 - x0), (y1 - y0)
            L = math.hypot(ux, uy)
            ux, uy = ux / L * d, uy / L * d
            ax, ay = mx + 0.28 * ux, my + 0.28 * uy
            annotations.append(dict(x=ax + 0.12 * ux, y=ay + 0.12 * uy, ax=ax - 0.12 * ux, ay=ay - 0.12 * uy, xref="x", yref="y",
                                    axref="x", ayref="y", showarrow=True, arrowhead=2, arrowsize=1.2, arrowwidth=1.5, arrowcolor=TEXT))
        if show_labels and e.kind in ("reactor", "throttle", "pump"):
            lbl = f"{q / ML_MIN:.3g} mL/min"
            if e.kind == "throttle":
                lbl += f"<br>{e.element.opening_percent:.0f} %"
            if e.kind == "reactor":
                lbl += f"<br>dp {pa - pb:.3g} Pa"
            if e.kind == "pump":
                lbl = f"{e.label}<br>{q / ML_MIN:.3g} mL/min<br>{(pb - pa)/100:.3g} mbar"
            annotations.append(dict(x=mx, y=my - 0.33, text=lbl, showarrow=False, font=dict(size=10, color=TEXT), yanchor="top"))
        if show_labels and e.kind == "tube" and e.group not in ("feed", "return"):
            annotations.append(dict(x=mx, y=my + 0.12, text=f"Ø{e.element.inner_diameter_mm:.2g}", showarrow=False,
                                    font=dict(size=9, color="#666"), yanchor="bottom"))
    fig.add_trace(go.Scatter(x=marker_x, y=marker_y, mode="markers", customdata=marker_id, text=marker_text,
                             hovertemplate="%{text}<extra></extra>", showlegend=False,
                             marker=dict(symbol=marker_sym, size=marker_size, color=marker_col,
                                         line=dict(width=marker_line, color=TEXT))))
    # nodes: reservoir, hubs, labelled with pressure
    for n in net.nodes.values():
        x, y = pos[n.id]
        if n.kind == "reservoir":
            fig.add_trace(go.Scatter(x=[x], y=[y], mode="markers+text", text=["Reservoir"], textposition="top center",
                                     marker=dict(symbol="square", size=34, color="#cfe3fa", line=dict(width=1.5, color=TEXT)),
                                     hovertemplate=f"Reservoir (reference)<br>p = {p[n.id]:.1f} Pa<br>fill {res.config.reservoir.fill_volume_ml:g} mL<extra></extra>",
                                     showlegend=False, customdata=["reservoir"]))
        elif n.kind in ("splitter_hub", "tee"):
            fig.add_trace(go.Scatter(x=[x], y=[y], mode="markers+text", text=[n.label.split(" (")[0]],
                                     textposition="middle left" if n.id in ("S1", "tee1") else "middle right",
                                     textfont=dict(size=10), customdata=["splitter_in" if n.id == "S1" else "splitter_out" if n.id == "S2" else n.id],
                                     marker=dict(symbol="diamond", size=18, color="#9c9c9c", line=dict(width=1, color=TEXT)),
                                     hovertemplate=f"{n.label}<br>p = {p.get(n.id, math.nan)/100:.3f} mbar<extra></extra>", showlegend=False))
        elif n.kind == "port" and res.config.layout == "full" and n.id in ("s1_in", "s2_out"):
            continue
    # colour bar legend for flow magnitude
    fig.add_trace(go.Scatter(x=[None], y=[None], mode="markers", showlegend=False, hoverinfo="skip",
                             marker=dict(colorscale=SEQ, cmin=0, cmax=qmax / ML_MIN, color=[0], showscale=True,
                                         colorbar=dict(title="|Q| [mL/min]", thickness=12, len=0.6))))
    fig.update_layout(annotations=annotations)
    fig.update_xaxes(visible=False, range=[-0.6, max(xy[0] for xy in pos.values()) + 1.0])
    fig.update_yaxes(visible=False, range=[y_bottom - 0.5, max(ys) + 0.9], scaleanchor=None)
    style(fig, "Hydraulic system diagram (line width and colour ~ |Q|, dotted = closed)", height=height, legend=False)
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False, showgrid=False)
    fig.update_layout(clickmode="event+select", dragmode="pan")
    return fig
