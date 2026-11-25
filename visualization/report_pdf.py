"""Automatic scientific simulation report (PDF, ReportLab) -- spec. chapter 20."""
from __future__ import annotations

import datetime as _dt
import io
import math

import numpy as np
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from core import APP_NAME, SOFTWARE_VERSION
from core.project import config_hash
from core.simulation import SimulationResult, convergence_info
from core.units import ML_MIN

from . import plots
from .diagram import system_diagram
from .export import export_figure

EQUATIONS = [
    ("Continuity (node i)", "sum Q_in - sum Q_out = 0"),
    ("Branch equation", "p_in - p_out = dp_loss(Q) + rho g dz"),
    ("Reynolds number", "Re = rho v d / mu,  v = 4Q/(pi d^2)"),
    ("Darcy-Weisbach", "dp = f (L/d) rho v^2 / 2"),
    ("Laminar friction (Hagen-Poiseuille)", "f = 64/Re  <=>  dp = 128 mu L Q / (pi d^4)"),
    ("Turbulent friction (Colebrook-White)", "1/sqrt(f) = -2 log10( (eps/d)/3.7 + 2.51/(Re sqrt f) )"),
    ("Local losses", "dp = K rho v^2 / 2"),
    ("Sudden expansion (Borda-Carnot)", "K = (1 - A1/A2)^2"),
    ("Darcy law (scaffold)", "dp = mu H Q / (k A)"),
    ("Darcy-Forchheimer (optional)", "dp/H = mu u/k + beta rho u^2"),
    ("Wall shear stress", "tau_w = f rho v^2 / 8  (laminar: 32 mu Q/(pi d^3))"),
    ("Pore shear estimate (capillary model)", "tau = sqrt(2) mu u / sqrt(k eps)"),
    ("Hydraulic power", "P = Q dp_pump"),
]

ASSUMPTIONS = [
    "Steady, incompressible, isothermal, Newtonian flow; rigid tubes (no compliance).",
    "One-dimensional lumped-parameter network; no 3D effects (no CFD).",
    "Junction/splitter losses represented by constant, user-defined/calibratable loss coefficients.",
    "Fully developed flow assumed for friction; entrance effects only via K values.",
    "Transitional regime: friction factor interpolated (bridging assumption, not a physical model).",
    "Scaffold: homogeneous, isotropic porous medium; full flow through the scaffold (sealed periphery).",
    "Pore shear stress: straight cylindrical capillary model (estimate only).",
    "Culture medium properties and all component parameters are EXAMPLE values unless replaced by measured data.",
]

LIMITS = [
    "Not a substitute for 3D CFD or biological validation.",
    "Pulsation model (if used) is kinematic and illustrative; no transient hydraulics.",
    "Non-circular cross sections (compressed tube, kink) are simplified substitute models.",
    "K values from turbulent handbook data are uncertain at low Reynolds numbers.",
    "Results are only as accurate as the input parameters; calibrate with measurements.",
]


def _styles():
    ss = getSampleStyleSheet()
    ss.add(ParagraphStyle("small", parent=ss["Normal"], fontSize=8, leading=10))
    ss.add(ParagraphStyle("cell", parent=ss["Normal"], fontSize=7.5, leading=9))
    return ss


def _table(df: pd.DataFrame, ss, col_widths=None, max_rows=60) -> Table:
    df = df.head(max_rows)
    data = [[Paragraph(f"<b>{c}</b>", ss["cell"]) for c in df.columns]]
    for _, r in df.iterrows():
        row = []
        for v in r:
            if isinstance(v, float):
                txt = "-" if not np.isfinite(v) else f"{v:.4g}"
            else:
                txt = str(v)
            row.append(Paragraph(txt, ss["cell"]))
        data.append(row)
    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eef7")),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#bbbbbb")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return t


def _img(fig, width_cm=16.5):
    png, _ = export_figure(fig, "png", width_in=7.0, dpi=200)
    im = Image(io.BytesIO(png))
    ratio = im.imageHeight / im.imageWidth
    im.drawWidth = width_cm * cm
    im.drawHeight = width_cm * cm * ratio
    return im


def build_report(res: SimulationResult, title: str = "Hydraulic simulation report", author: str = "",
                 experimental: tuple[pd.DataFrame, pd.DataFrame] | None = None, include_figures: bool = True) -> bytes:
    ss = _styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=1.8 * cm, bottomMargin=1.8 * cm,
                            title=title, author=author or APP_NAME)
    s = []
    H1, H2, N = ss["Heading1"], ss["Heading2"], ss["Normal"]
    s.append(Paragraph(title, ss["Title"]))
    s.append(Paragraph(f"{APP_NAME} V{SOFTWARE_VERSION}", N))
    s.append(Paragraph(f"Date: {_dt.datetime.now():%Y-%m-%d %H:%M} &nbsp;&nbsp; Configuration: {res.config.name}", N))
    s.append(Paragraph(f"Configuration SHA-256: {config_hash(res.config)[:16]}...", ss["small"]))
    if author:
        s.append(Paragraph(f"Author: {author}", N))
    s.append(Spacer(1, 0.3 * cm))
    s.append(Paragraph(f"<i>{res.config.description}</i>", ss["small"]))

    s.append(Paragraph("1 Summary", H1))
    summ = res.summary()
    rows = [("Converged", str(summ["converged"])), ("Pump mode", res.config.pump.mode),
            ("Total flow rate", f"{summ['Q_total_ml_min']:.4g} mL/min"), ("Pump pressure difference", f"{summ['pump_dp_pa']:.4g} Pa"),
            ("Hydraulic power", f"{summ['hydraulic_power_w']*1e3:.4g} mW"),
            ("Bypass flow", f"{summ['bypass_ml_min']:.4g} mL/min ({100*summ['bypass_fraction']:.2f} %)"),
            ("CV of reactor flows", f"{100*summ['cv_reactors']:.3g} %" if np.isfinite(summ['cv_reactors']) else "-"),
            ("Circuit volume (excl. reservoir)", f"{summ['system_volume_ml']:.3f} mL"),
            ("Fluid", f"{res.fluid.name}, {res.fluid.temperature_c:g} degC, rho = {res.fluid.density:.2f} kg/m^3, mu = {res.fluid.dynamic_viscosity*1e3:.4f} mPa s")]
    s.append(_table(pd.DataFrame(rows, columns=["Quantity", "Value"]), ss, [6 * cm, 11 * cm]))

    s.append(Paragraph("2 Hydraulic schematic", H1))
    if include_figures:
        s.append(_img(system_diagram(res, show_labels=True, height=600)))
    s.append(Paragraph("Line width and colour scale with |Q|; dotted lines denote closed components.", ss["small"]))

    s.append(Paragraph("3 Input parameters", H1))
    from core.project import flatten

    flat = flatten(res.config.model_dump(mode="json"))
    keys = [k for k in flat if not k.startswith(("pump.curve", "solver"))]
    s.append(_table(pd.DataFrame([(k, str(flat[k])) for k in keys], columns=["Parameter path", "Value"]), ss, [9 * cm, 8 * cm], max_rows=400))

    s.append(PageBreak())
    s.append(Paragraph("4 Equations", H1))
    s.append(_table(pd.DataFrame(EQUATIONS, columns=["Relation", "Equation"]), ss, [6 * cm, 11 * cm]))
    s.append(Paragraph("5 Model assumptions", H1))
    for a in ASSUMPTIONS:
        s.append(Paragraph("&bull; " + a, N))

    s.append(Paragraph("6 Results", H1))
    s.append(Paragraph("6.1 Bioreactors", H2))
    r = res.reactors
    if not r.empty:
        rt = pd.DataFrame({
            "Reactor": r.reactor, "State": r.state, "Q [mL/min]": r.Q_ml_min, "Share [%]": r.share_percent,
            "p_in [Pa]": r.p_in_pa, "dp [Pa]": r.dp_pa, "dp scaffold [Pa]": r.dp_scaffold_pa,
            "u_s [mm/s]": r.superficial_velocity_m_s * 1e3, "tau_pore est. [mPa]": r.shear_stress_estimate_pa * 1e3,
            "t_res [s]": r.residence_time_s,
        })
        s.append(_table(rt, ss))
        s.append(Paragraph("tau_pore: model-based estimate (capillary model). Flows: numerical network solution.", ss["small"]))
    s.append(Paragraph("6.2 Segments", H2))
    e = res.edges
    et = pd.DataFrame({"Component": e.label, "Q [mL/min]": e.Q_ml_min, "p_in [Pa]": e.p_in_pa, "dp [Pa]": e.dp_pa,
                       "Re": e.get("Re"), "Regime": e.get("regime"), "tau_w [mPa]": e.get("wall_shear_pa") * 1e3,
                       "V [uL]": e.get("volume_m3") * 1e9})
    s.append(_table(et, ss, max_rows=80))
    if include_figures:
        s.append(PageBreak())
        s.append(Paragraph("7 Diagrams", H1))
        for fig in (plots.fig_reactor_flows(res), plots.fig_flow_share(res), plots.fig_pressure_profile(res), plots.fig_dp_components(res),
                    plots.fig_pump_system(res.config, res)):
            s.append(_img(fig))
            s.append(Spacer(1, 0.2 * cm))

    s.append(Paragraph("8 Warnings", H1))
    if res.warnings:
        s.append(_table(pd.DataFrame([w.__dict__ for w in res.warnings]), ss, [2 * cm, 12 * cm, 3 * cm]))
    else:
        s.append(Paragraph("No warnings.", N))
    s.append(Paragraph("9 Convergence information", H1))
    ci = convergence_info(res.solver)
    s.append(_table(pd.DataFrame([(k, str(v)) for k, v in ci.items()], columns=["Item", "Value"]), ss, [6 * cm, 11 * cm]))
    s.append(Paragraph("Convergence criteria: max |mass residual| <= tol_mass_rel * Q_s and max |pressure residual| <= tol_p.", ss["small"]))
    s.append(Paragraph("10 Model limits", H1))
    for a in LIMITS:
        s.append(Paragraph("&bull; " + a, N))
    if experimental is not None:
        sim_df, metrics = experimental
        s.append(Paragraph("11 Comparison with experiment", H1))
        s.append(_table(metrics, ss))
        s.append(Paragraph("Confidence intervals assume independent, normally distributed deviations (t distribution).", ss["small"]))
    s.append(Spacer(1, 0.5 * cm))
    s.append(Paragraph("Classification: flows/pressures = numerical network solution; laminar tube losses = analytical; "
                       "turbulent friction, local losses = empirical; pore shear = model-based estimate; "
                       "values marked calibrated/validated only where experimental data were used.", ss["small"]))

    def _footer(canvas, doc_):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.drawString(2 * cm, 1 * cm, f"{APP_NAME} V{SOFTWARE_VERSION} - {res.config.name}")
        canvas.drawRightString(A4[0] - 2 * cm, 1 * cm, f"page {doc_.page}")
        canvas.restoreState()

    doc.build(s, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()
