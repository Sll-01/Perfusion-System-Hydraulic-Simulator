"""Interactive scientific figures (Plotly). All axes carry quantity and unit.

Colour rules: categorical series use a validated, colour-vision-deficiency-checked
palette in fixed order (reactor k always gets the same colour); magnitudes use a single
hue sequential scale; no dual axes.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from core.units import ML_MIN

SERIES = ["#257de0", "#f47230", "#00b894", "#f2a600", "#ee7fac", "#008a17", "#6a4ce2", "#ec4647"]
BYPASS_COLOR = "#666666"
TEXT = "#191919"
GRID = "#e6e6e6"
SEQ = [[0.0, "#cfe3fa"], [0.5, "#5aa0ec"], [1.0, "#0b3f86"]]
DIV = "RdBu_r"


def series_color(i: int) -> str:
    return SERIES[i % len(SERIES)]


def style(fig: go.Figure, title: str = "", x: str = "", y: str = "", height: int = 420, legend: bool = True) -> go.Figure:
    fig.update_layout(
        template="simple_white",
        title=dict(text=title, x=0.0, xanchor="left", font=dict(size=15, color=TEXT)),
        font=dict(family="Arial, Helvetica, sans-serif", size=13, color=TEXT),
        height=height,
        margin=dict(l=70, r=25, t=55 if title else 25, b=60),
        showlegend=legend,
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="right", x=1.0),
        hoverlabel=dict(bgcolor="white", font_size=12),
        paper_bgcolor="white",
        plot_bgcolor="white",
    )
    fig.update_xaxes(title_text=x, showgrid=False, ticks="outside", showline=True, linecolor="#888", mirror=False)
    fig.update_yaxes(title_text=y, showgrid=True, gridcolor=GRID, ticks="outside", showline=True, linecolor="#888", zeroline=False)
    return fig


# ---------------------------------------------------------------------------
# Single simulation result
# ---------------------------------------------------------------------------
def fig_reactor_flows(res, targets_ml_min=None) -> go.Figure:
    r = res.reactors
    names = list(r.reactor)
    q = list(r.Q_ml_min)
    colors = [series_color(i) for i in range(len(names))]
    if res.bypass.get("enabled"):
        names.append("Bypass")
        q.append(res.bypass["Q_ml_min"])
        colors.append(BYPASS_COLOR)
    fig = go.Figure(go.Bar(x=names, y=q, marker_color=colors, marker_line_width=0,
                           text=[f"{v:.3g}" for v in q], textposition="inside", insidetextanchor="end",
                           textfont=dict(color="white"), hovertemplate="%{x}<br>Q = %{y:.4g} mL/min<extra></extra>"))
    if len(r) > 1:
        m = float(r.Q_ml_min.mean())
        fig.add_hline(y=m, line_dash="dot", line_color="#666", annotation_text=f"reactor mean {m:.3g}",
                      annotation_position="bottom right", annotation_font_size=11)
    if targets_ml_min:
        fig.add_trace(go.Scatter(x=names[: len(targets_ml_min)], y=targets_ml_min, mode="markers", name="target",
                                 marker=dict(symbol="line-ew-open", size=28, line=dict(width=3, color=TEXT))))
    fig.update_traces(selector=dict(type="bar"), width=0.6)
    return style(fig, "Volumetric flow rate per flow path", "", "Flow rate Q [mL/min]", legend=bool(targets_ml_min))


def fig_flow_share(res) -> go.Figure:
    r = res.reactors
    names = list(r.reactor)
    share = list(r.share_percent)
    colors = [series_color(i) for i in range(len(names))]
    if res.bypass.get("enabled"):
        names.append("Bypass")
        share.append(100 * res.bypass["fraction"])
        colors.append(BYPASS_COLOR)
    fig = go.Figure(go.Bar(x=share, y=names, orientation="h", marker_color=colors,
                           text=[f"{v:.1f} %" for v in share], textposition="outside",
                           hovertemplate="%{y}: %{x:.2f} % of pump flow<extra></extra>"))
    fig.update_yaxes(autorange="reversed", showgrid=False)
    fig.update_xaxes(range=[0, max(share + [1]) * 1.2])
    return style(fig, "Percentage flow distribution", "Share of total pump flow [%]", "", legend=False)


def fig_pressure_profile(res) -> go.Figure:
    from core.simulation import path_profile

    fig = go.Figure()
    groups = [g for g in dict.fromkeys(res.edges.group) if g.startswith("reactor_") or g in ("bypass", "test")]
    for i, g in enumerate(groups):
        prof = path_profile(res, g)
        color = BYPASS_COLOR if g == "bypass" else series_color(i)
        name = g.replace("reactor_", "Reactor path ").replace("bypass", "Bypass").replace("test", "Test line")
        fig.add_trace(go.Scatter(x=prof.s_m, y=prof.p_pa / 100, mode="lines+markers", name=name, line=dict(color=color, width=2),
                                 marker=dict(size=7), customdata=prof.component,
                                 hovertemplate="%{customdata}<br>s = %{x:.3f} m<br>p = %{y:.3f} mbar<extra>" + name + "</extra>"))
    return style(fig, "Pressure distribution along the flow paths", "Position along flow path s [m] (lumped parts: 0.02 m)",
                 "Gauge pressure p [mbar]")


def fig_edge_quantity(res, column: str, label: str, title: str, log: bool = False, factor: float = 1.0) -> go.Figure:
    e = res.edges[(res.edges.kind != "pump")].copy()
    e = e[np.isfinite(pd.to_numeric(e[column], errors="coerce"))]
    vals = e[column].astype(float) * factor
    groups = list(dict.fromkeys(res.edges.group))
    gcol = {g: (BYPASS_COLOR if g == "bypass" else "#9c9c9c" if g in ("feed", "return") else series_color(groups.index(g) - 1 if g.startswith("reactor_") else 0))
            for g in groups}
    for g in groups:
        if g.startswith("reactor_"):
            gcol[g] = series_color(int(g.split("_")[1]) - 1)
    fig = go.Figure(go.Bar(x=vals, y=e.label, orientation="h", marker_color=[gcol.get(g, "#999") for g in e.group],
                           customdata=e.group, hovertemplate="%{y}<br>%{x:.4g}<extra>%{customdata}</extra>"))
    fig.update_yaxes(autorange="reversed", showgrid=False, tickfont=dict(size=10))
    if log:
        fig.update_xaxes(type="log")
    return style(fig, title, label, "", height=max(420, 16 * len(e) + 120), legend=False)


def fig_dp_components(res) -> go.Figure:
    return fig_edge_quantity(res, "dp_loss_pa", "Pressure loss dp [Pa]", "Pressure loss per component")


def fig_velocity(res) -> go.Figure:
    return fig_edge_quantity(res, "v_m_s", "Mean velocity v [mm/s]", "Mean flow velocity per component", factor=1e3)


def fig_reynolds(res) -> go.Figure:
    fig = fig_edge_quantity(res, "Re", "Reynolds number Re [-] (log scale)", "Reynolds number per component", log=True)
    fig.add_vline(x=2000, line_dash="dash", line_color="#666", annotation_text="Re = 2000")
    return fig


def fig_wall_shear(res) -> go.Figure:
    e = res.edges[res.edges.kind == "tube"]
    fig = go.Figure(go.Bar(x=e.wall_shear_pa * 1e3, y=e.label, orientation="h", marker_color="#257de0",
                           hovertemplate="%{y}<br>tau_w = %{x:.4g} mPa<extra></extra>"))
    fig.update_yaxes(autorange="reversed", showgrid=False, tickfont=dict(size=10))
    return style(fig, "Mean wall shear stress in tube segments", "Wall shear stress tau_w [mPa]", "",
                 height=max(380, 18 * len(e) + 120), legend=False)


def fig_reactor_quantity(res, column: str, label: str, title: str, factor: float = 1.0) -> go.Figure:
    r = res.reactors
    fig = go.Figure(go.Bar(x=r.reactor, y=r[column] * factor, marker_color=[series_color(i) for i in range(len(r))],
                           hovertemplate="%{x}<br>%{y:.4g}<extra></extra>", width=0.6))
    return style(fig, title, "", label, legend=False)


def fig_volume_breakdown(res) -> go.Figure:
    items = {k: v * 1e6 for k, v in res.volumes.items() if k not in ("circuit_total", "total_medium", "circulation_time_s") and v > 0}
    fig = go.Figure(go.Bar(x=list(items.values()), y=list(items.keys()), orientation="h", marker_color="#257de0",
                           text=[f"{v:.2f} mL" for v in items.values()], textposition="outside",
                           hovertemplate="%{y}: %{x:.3f} mL<extra></extra>"))
    fig.update_yaxes(showgrid=False)
    return style(fig, f"Medium volume (total {res.volumes['total_medium']*1e6:.2f} mL)", "Volume [mL]", "", height=320, legend=False)


def system_curve(cfg, q_max_ml_min: float | None = None, n: int = 25) -> pd.DataFrame:
    """Required pump pressure vs. total flow (system characteristic, mode-A sweep)."""
    from core.sensitivity import evaluate

    c = cfg.model_copy(deep=True)
    c.pump.mode = "A_constant_flow"
    qmax = q_max_ml_min or max(cfg.pump.flow_rate_ml_min * 2.5, 1.0)
    rows, prev = [], None
    for q in np.linspace(qmax / n, qmax, n):
        c.pump.flow_rate_ml_min = float(q)
        o, sol = evaluate(c, initial=prev)
        prev = sol if sol.converged else None
        rows.append({"Q_ml_min": q, "dp_pa": o["pump_dp_pa"]})
    return pd.DataFrame([{"Q_ml_min": 0.0, "dp_pa": 0.0}] + rows)


def fig_pump_system(cfg, res) -> go.Figure:
    q_op, dp_op = res.pump["Q_ml_min"], res.pump["dp"]
    qmax = max(q_op * 2.0, 1.0)
    pump = cfg.pump
    if pump.mode == "C_pump_curve":
        qmax = max(qmax, float(pump.curve_frame().flow_ml_min.max()) * 1.1)
    sc = system_curve(cfg, qmax)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=sc.Q_ml_min, y=sc.dp_pa / 100, name="System curve", mode="lines", line=dict(color=SERIES[0], width=2),
                             hovertemplate="Q = %{x:.3g} mL/min<br>dp = %{y:.4g} mbar<extra>system</extra>"))
    qq = np.linspace(0, qmax, 60)
    if pump.mode == "A_constant_flow":
        fig.add_trace(go.Scatter(x=[pump.flow_rate_ml_min] * 2, y=[0, sc.dp_pa.max() / 100 * 1.1], name="Pump (mode A: Q = const)",
                                 mode="lines", line=dict(color=SERIES[1], width=2)))
    elif pump.mode == "B_constant_pressure":
        fig.add_trace(go.Scatter(x=[0, qmax], y=[pump.pressure_difference_pa / 100] * 2, name="Pump (mode B: dp = const)",
                                 mode="lines", line=dict(color=SERIES[1], width=2)))
    elif pump.mode == "C_pump_curve":
        h = [pump.curve_head(q * ML_MIN)[0] / 100 for q in qq]
        fig.add_trace(go.Scatter(x=qq, y=h, name=f"Pump curve n = {pump.speed_rpm:g} rpm (interpolated)", mode="lines",
                                 line=dict(color=SERIES[1], width=2)))
        df = pump.curve_frame()
        for i, (sp, sub) in enumerate(df.groupby("speed_rpm")):
            fig.add_trace(go.Scatter(x=sub.flow_ml_min, y=sub.dp_pa / 100, mode="markers", name=f"measured / given, {sp:g} rpm",
                                     marker=dict(size=8, color=SERIES[(i + 3) % 8], line=dict(width=2, color="white"))))
    else:
        dps = np.linspace(0, max(sc.dp_pa.max(), dp_op) * 1.1, 40)
        qd = [(pump.volumetric_efficiency * pump.theoretical_flow() - pump.slip() * p) / ML_MIN for p in dps]
        fig.add_trace(go.Scatter(x=qd, y=dps / 100, name="Displacement pump model", mode="lines", line=dict(color=SERIES[1], width=2)))
    fig.add_trace(go.Scatter(x=[q_op], y=[dp_op / 100], mode="markers", name="Operating point",
                             marker=dict(size=12, color=TEXT, symbol="circle", line=dict(width=2, color="white")),
                             hovertemplate="Operating point<br>Q = %{x:.4g} mL/min<br>dp = %{y:.4g} mbar<extra></extra>"))
    fig.add_hline(y=pump.max_pressure_pa / 100, line_dash="dash", line_color="#ec4647",
                  annotation_text="max. permissible pump pressure", annotation_position="top left")
    fig.update_yaxes(range=[0, max(sc.dp_pa.max(), dp_op) / 100 * 1.3])
    return style(fig, "Pump characteristic, system characteristic and operating point", "Total flow rate Q [mL/min]",
                 "Pressure difference dp [mbar]")


def fig_residuals(res) -> go.Figure:
    h = res.solver.residual_history
    fig = go.Figure(go.Scatter(x=list(range(len(h))), y=np.maximum(h, 1e-18), mode="lines+markers", line=dict(color=SERIES[0], width=2)))
    fig.update_yaxes(type="log")
    return style(fig, "Newton convergence history", "Iteration [-]", "max. scaled residual ||F||_inf [-]", height=320, legend=False)


def fig_pulsation(t, q_m3s, f_hz) -> go.Figure:
    fig = go.Figure(go.Scatter(x=t, y=np.asarray(q_m3s) / ML_MIN, mode="lines", line=dict(color=SERIES[0], width=2)))
    return style(fig, f"Illustrative roller pulsation (f = {f_hz:.2f} Hz) - not a validated transient simulation",
                 "Time t [s]", "Pump flow Q(t) [mL/min]", height=330, legend=False)


# ---------------------------------------------------------------------------
# Studies
# ---------------------------------------------------------------------------
def fig_sweep(df: pd.DataFrame, x: str, ys: list[str], xlabel: str, ylabel: str, title: str, logx=False, logy=False,
              names: list[str] | None = None) -> go.Figure:
    fig = go.Figure()
    for i, y in enumerate(ys):
        if y not in df:
            continue
        name = (names[i] if names else y)
        color = BYPASS_COLOR if "bypass" in y.lower() else series_color(i)
        fig.add_trace(go.Scatter(x=df[x], y=df[y], mode="lines+markers", name=name, line=dict(color=color, width=2), marker=dict(size=7),
                                 hovertemplate=f"{name}<br>x = %{{x:.4g}}<br>y = %{{y:.4g}}<extra></extra>"))
    if logx:
        fig.update_xaxes(type="log")
    if logy:
        fig.update_yaxes(type="log")
    return style(fig, title, xlabel, ylabel, legend=len(ys) > 1)


def fig_heatmap(df: pd.DataFrame, x: str, y: str, z: str, xlabel: str, ylabel: str, zlabel: str, title: str) -> go.Figure:
    piv = df.pivot_table(index=y, columns=x, values=z)
    fig = go.Figure(go.Heatmap(x=piv.columns, y=piv.index, z=piv.values, colorscale=SEQ, colorbar=dict(title=zlabel),
                               hovertemplate=f"{xlabel}: %{{x:.4g}}<br>{ylabel}: %{{y:.4g}}<br>{zlabel}: %{{z:.4g}}<extra></extra>"))
    return style(fig, title, xlabel, ylabel, height=480, legend=False)


def fig_surface(df: pd.DataFrame, x: str, y: str, z: str, xlabel: str, ylabel: str, zlabel: str, title: str) -> go.Figure:
    piv = df.pivot_table(index=y, columns=x, values=z)
    fig = go.Figure(go.Surface(x=piv.columns, y=piv.index, z=piv.values, colorscale=SEQ, colorbar=dict(title=zlabel)))
    fig.update_layout(scene=dict(xaxis_title=xlabel, yaxis_title=ylabel, zaxis_title=zlabel))
    return style(fig, title, height=560, legend=False)


def fig_histogram(df: pd.DataFrame, col: str, label: str, title: str) -> go.Figure:
    fig = go.Figure(go.Histogram(x=df[col], marker_color=SERIES[0], marker_line=dict(color="white", width=1), nbinsx=30))
    m, s = df[col].mean(), df[col].std()
    fig.add_vline(x=m, line_dash="dash", line_color=TEXT, annotation_text=f"mean {m:.3g}, SD {s:.2g}")
    return style(fig, title, label, "Count [-]", legend=False)


def fig_tornado(sens: pd.DataFrame, output: str, labels: dict | None = None) -> go.Figure:
    s = sens[sens.output == output].copy()
    s["abs"] = s.elasticity.abs()
    s = s.sort_values("abs")
    names = [labels.get(p, p) if labels else p for p in s.parameter]
    colors = ["#ec4647" if v < 0 else "#257de0" for v in s.elasticity]
    fig = go.Figure(go.Bar(x=s.elasticity, y=names, orientation="h", marker_color=colors,
                           hovertemplate="%{y}<br>elasticity %{x:.3f}<extra></extra>"))
    fig.add_vline(x=0, line_color="#888")
    return style(fig, f"Normalised local sensitivity of '{output}'", "Elasticity (dy/y)/(dx/x) [-]", "",
                 height=max(320, 30 * len(s) + 120), legend=False)


def fig_parity(sim_df: pd.DataFrame, quantity: str, label: str) -> go.Figure:
    x = sim_df[quantity]
    y = sim_df[f"sim:{quantity}"]
    fig = go.Figure()
    err = sim_df.get(f"u_{quantity}")
    is_cal = sim_df["dataset"].astype(str).str.lower() == "calibration" if "dataset" in sim_df else pd.Series(False, index=sim_df.index)
    for i, (name, mask) in enumerate((("calibration data", is_cal), ("validation data", ~is_cal))):
        if mask.any():
            fig.add_trace(go.Scatter(x=x[mask], y=y[mask], mode="markers", name=name,
                                     marker=dict(size=9, color=SERIES[i], line=dict(width=2, color="white")),
                                     error_x=dict(type="data", array=(2 * err[mask]) if err is not None else None, visible=err is not None)))
    lo, hi = float(np.nanmin([x.min(), y.min()])), float(np.nanmax([x.max(), y.max()]))
    fig.add_trace(go.Scatter(x=[lo, hi], y=[lo, hi], mode="lines", name="y = x", line=dict(color="#888", dash="dash", width=1)))
    return style(fig, f"Simulation vs. experiment: {label}", f"Measured {label}", f"Simulated {label}")


def fig_compare_configs(results: dict) -> go.Figure:
    """Grouped bars of reactor & bypass flows for several configurations."""
    fig = go.Figure()
    for i, (name, res) in enumerate(results.items()):
        names = list(res.reactors.reactor)
        q = list(res.reactors.Q_ml_min)
        if res.bypass.get("enabled"):
            names.append("Bypass")
            q.append(res.bypass["Q_ml_min"])
        fig.add_trace(go.Bar(x=names, y=q, name=name, marker_color=series_color(i)))
    fig.update_layout(barmode="group", bargap=0.25, bargroupgap=0.08)
    return style(fig, "Comparison of configurations", "", "Flow rate Q [mL/min]")


def fig_opt_history(hist) -> go.Figure:
    fig = go.Figure(go.Scatter(y=np.maximum(np.asarray(hist, float), 1e-16), mode="lines", line=dict(color=SERIES[0], width=2)))
    fig.update_yaxes(type="log")
    return style(fig, "Optimisation progress (best objective incl. penalties)", "Function evaluation [-]", "Objective [-]",
                 height=320, legend=False)
