"""Configuration pages: fluid, pump, tubing, splitters, bioreactors, throttles, bypass."""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.fluids import FLUID_LABELS, FluidConfig, evaluate_fluid
from core.pumps import PUMP_MODE_LABELS, CurvePoint, import_pump_curve, pulsation_waveform
from core.sensitivity import ParameterSpec, sweep_1d
from core.simulation import run_simulation
from core.system import set_reactor_count
from core.units import ML_MIN
from visualization import plots

from . import widgets as W
from .i18n import t
from .pages_results import metrics_row, show_warnings, solver_badge
from .state import cfg, key, simulate


def page_fluid() -> None:
    st.title(t("Fluid Properties"))
    f = cfg().fluid
    top = st.container()
    c1, c2, c3 = st.columns(3)
    types = list(FLUID_LABELS)
    new_type = c1.selectbox(t("Fluid type"), types, types.index(f.fluid_type), format_func=lambda x: FLUID_LABELS[x], key=key("ftype"))
    if new_type != f.fluid_type:
        f.fluid_type = new_type
        f.name = FLUID_LABELS[new_type]
    f.name = c2.text_input(t("Name"), f.name, key=key("fname"))
    W.num(f, "temperature_c", t("Temperature"), "fluid", "degC", -5.0, 100.0, 0.5, container=c3)
    f.temperature_dependent = st.checkbox(t("Temperature-dependent properties"), f.temperature_dependent, key=key("ftd"),
                                          help="If off: properties evaluated at 37 degC (or the custom reference temperature) regardless of T.")
    if f.fluid_type == "custom":
        c1, c2, c3 = st.columns(3)
        W.num(f, "custom_density", t("Density"), "fluid", "kg/m^3", 1.0, step=1.0, container=c1)
        W.num(f, "custom_viscosity", t("Dynamic viscosity"), "fluid", "mPa s", 1e-6, step=0.01, fmt="%.4f", factor=1e3, container=c2)
        W.num(f, "custom_reference_temperature_c", "Reference temperature", "fluid", "degC", container=c3)
    elif f.fluid_type != "water":
        st.markdown("**Property ratios relative to water** (defaults are ASSUMPTIONS - enter measured values)")
        c1, c2 = st.columns(2)
        dr = c1.number_input("Density ratio rho/rho_water [-] (0 = default)", value=float(f.density_ratio or 0.0), min_value=0.0,
                             format="%.4f", key=key("fdr"))
        f.density_ratio = dr if dr > 0 else None
        vr = c2.number_input("Viscosity ratio mu/mu_water [-] (0 = default)", value=float(f.viscosity_ratio or 0.0), min_value=0.0,
                             format="%.4f", key=key("fvr"))
        f.viscosity_ratio = vr if vr > 0 else None
    st.markdown("**Direct overrides** (0 = not used; overrides take precedence over correlations)")
    c1, c2, c3 = st.columns(3)
    v = c1.number_input(f"{t('Density')} [kg/m^3]", value=float(f.density_override or 0.0), min_value=0.0, key=key("fdo"))
    f.density_override = v if v > 0 else None
    v = c2.number_input(f"{t('Dynamic viscosity')} [mPa s]", value=float((f.dynamic_viscosity_override or 0.0) * 1e3), min_value=0.0,
                        format="%.4f", key=key("fmo"))
    f.dynamic_viscosity_override = v * 1e-3 if v > 0 else None
    v = c3.number_input(f"{t('Kinematic viscosity')} [mm^2/s]", value=float((f.kinematic_viscosity_override or 0.0) * 1e6), min_value=0.0,
                        format="%.4f", key=key("fno"))
    f.kinematic_viscosity_override = v * 1e-6 if v > 0 else None
    W.num(cfg().reservoir, "fill_volume_ml", t("Reservoir fill volume"), "res", "mL", 0.0, step=1.0)
    f.notes = st.text_area("Notes / source of the values", f.notes, key=key("fnotes"))
    try:
        fs = evaluate_fluid(f)
    except Exception as exc:
        st.error(str(exc))
        return
    with top:
        c = st.columns(4)
        c[0].metric(t("Density"), f"{fs.density:.3f} kg/m^3")
        c[1].metric(t("Dynamic viscosity"), f"{fs.dynamic_viscosity*1e3:.4f} mPa s")
        c[2].metric(t("Kinematic viscosity"), f"{fs.kinematic_viscosity*1e6:.4f} mm^2/s")
        c[3].metric(t("Temperature"), f"{fs.temperature_c:g} degC")
        st.caption("Provenance: " + "; ".join(f"{k}: {v}" for k, v in fs.provenance.items()))
        for w in fs.warnings:
            st.warning(w)
    T = np.linspace(15, 45, 61)
    rows = []
    for tc in T:
        g = f.model_copy(update={"temperature_c": float(tc)})
        e = evaluate_fluid(g)
        rows.append((tc, e.dynamic_viscosity * 1e3, e.density))
    df = pd.DataFrame(rows, columns=["T", "mu", "rho"])
    c1, c2 = st.columns(2)
    c1.plotly_chart(plots.fig_sweep(df, "T", ["mu"], "Temperature T [degC]", "Dynamic viscosity mu [mPa s]",
                                    "Viscosity vs. temperature"), width="stretch")
    c2.plotly_chart(plots.fig_sweep(df, "T", ["rho"], "Temperature T [degC]", "Density rho [kg/m^3]", "Density vs. temperature"),
                    width="stretch")


def page_pump() -> None:
    st.title(t("Pump Configuration"))
    p = cfg().pump
    top = st.container()
    modes = list(PUMP_MODE_LABELS)
    p.name = st.text_input(t("Name"), p.name, key=key("pname"))
    p.mode = st.radio(t("Pump mode"), modes, modes.index(p.mode), format_func=lambda m: PUMP_MODE_LABELS[m], horizontal=True, key=key("pmode"))
    c1, c2, c3 = st.columns(3)
    if p.mode == "A_constant_flow":
        W.num(p, "flow_rate_ml_min", t("Flow rate"), "pump", "mL/min", 0.0, step=0.1, fmt="%.4f", container=c1)
    elif p.mode == "B_constant_pressure":
        W.num(p, "pressure_difference_pa", t("Pressure difference"), "pump", "mbar", step=1.0, fmt="%.3f", factor=0.01, container=c1)
    else:
        W.num(p, "speed_rpm", t("Speed"), "pump", "rpm", 0.0, step=1.0, container=c1)
    W.num(p, "max_pressure_pa", t("Max. permissible pressure"), "pump", "mbar", 0.01, step=10.0, factor=0.01, container=c2)
    p.provenance = c3.text_input("Provenance", p.provenance, key=key("pprov"))
    if p.mode == "C_pump_curve":
        st.markdown("**Experimental pump curve** (speed, flow, differential pressure, optional power / efficiency)")
        up = st.file_uploader("Import pump curve (CSV / Excel)", type=["csv", "xlsx", "xls"], key=key("pcurve_up"))
        if up is not None and st.button("Use imported curve", key=key("pcurve_use")):
            try:
                p.curve = import_pump_curve(up.getvalue(), up.name)
                st.session_state.rev += 1
                st.rerun()
            except Exception as exc:
                st.error(f"Import failed: {exc}")
        df = p.curve_frame()
        ed = W.stable_editor(df, "pcurve", num_rows="dynamic", width="stretch")
        pts = []
        for _, r in ed.dropna(subset=["flow_ml_min", "dp_pa"]).iterrows():
            pts.append(CurvePoint(speed_rpm=float(r.get("speed_rpm", 0) or 0), flow_ml_min=float(r.flow_ml_min), dp_pa=float(r.dp_pa),
                                  power_w=None if pd.isna(r.get("power_w")) else float(r.get("power_w")),
                                  efficiency=None if pd.isna(r.get("efficiency")) else float(r.get("efficiency"))))
        if pts:
            p.curve = pts
        st.caption("Between measured speeds the curves are interpolated linearly; outside, affinity scaling (Q~n, dp~n^2) is used "
                   "and flagged as extrapolation. The default curve is a synthetic EXAMPLE.")
    if p.mode == "D_displacement":
        st.markdown("**Displacement / peristaltic substitute model** (Q = eta_v n V_rev - C_slip dp) - parameters are ASSUMPTIONS")
        c1, c2, c3, c4 = st.columns(4)
        v = c1.number_input("Displacement per rev. [mL] (0 = from geometry)", value=float(p.displacement_ml_per_rev or 0.0), min_value=0.0,
                            format="%.5f", key=key("pdisp"))
        p.displacement_ml_per_rev = v if v > 0 else None
        W.num(p, "pump_tube_inner_diameter_mm", "Pump tube ID", "pump", "mm", 0.01, step=0.1, container=c2)
        W.num(p, "track_radius_mm", "Roller track radius", "pump", "mm", 0.01, step=0.5, container=c3)
        p.n_rollers = int(c4.number_input("Number of rollers", value=int(p.n_rollers), min_value=1, step=1, key=key("proll")))
        c1, c2, c3 = st.columns(3)
        W.num(p, "volumetric_efficiency", "Volumetric efficiency", "pump", "-", 0.01, 1.0, 0.01, container=c1)
        W.num(p, "slip_coefficient_ml_min_per_kpa", "Slip coefficient", "pump", "mL/min per kPa", 0.0, step=0.01, fmt="%.4f", container=c2)
        c3.metric("Theoretical flow", f"{p.theoretical_flow()/ML_MIN:.4g} mL/min", f"V_rev = {p.displacement_volume()*1e6:.4g} mL", delta_color="off")
    res = simulate()
    with top:
        solver_badge(res)
        metrics_row(res)
    st.plotly_chart(plots.fig_pump_system(cfg(), res), width="stretch")
    with st.expander("Optional pulsation model (illustrative, NOT a validated transient simulation)"):
        pu = p.pulsation
        pu.enabled = st.checkbox("Show pulsation", pu.enabled, key=key("pulse_on"))
        if pu.enabled:
            c1, c2, c3 = st.columns(3)
            W.num(pu, "relative_amplitude", "Relative amplitude (ASSUMPTION)", "pulse", "-", 0.0, 1.0, 0.05, container=c1)
            pu.n_periods = int(c2.number_input("Periods", value=int(pu.n_periods), min_value=1, key=key("pper")))
            n_rpm = p.speed_rpm if p.mode in ("C_pump_curve", "D_displacement") else c3.number_input("Speed for pulsation [rpm]", value=float(p.speed_rpm), key=key("prpm"))
            tt, q, f = pulsation_waveform(res.pump["Q"], n_rpm, p.n_rollers, pu.relative_amplitude, pu.n_periods, pu.points_per_period)
            st.plotly_chart(plots.fig_pulsation(tt, q, f), width="stretch")
            st.caption("Quasi-steady assumption: without compliance and inertia, the flow distribution follows Q(t) instantaneously. "
                       "Shown only to illustrate the time scale of roller pulsation; validate with transient measurements.")


def _all_tubes():
    c = cfg()
    tubes = {"suction_tube": ("Suction tube", c.suction_tube), "pump_outlet_tube": ("Pump outlet tube", c.pump_outlet_tube),
             "return_tube": ("Return tube", c.return_tube)}
    if c.layout == "single_line":
        tubes["single_line.test_tube"] = ("Test tube", c.single_line.test_tube)
    for i, p in enumerate(c.reactor_paths):
        for attr in ("tube_to_throttle", "tube_to_reactor", "tube_to_collector"):
            tubes[f"reactor_paths.{i}.{attr}"] = (getattr(p, attr).name, getattr(p, attr))
    if c.bypass.enabled:
        tubes["bypass.tube_upstream"] = ("Bypass upstream", c.bypass.tube_upstream)
        tubes["bypass.tube_downstream"] = ("Bypass downstream", c.bypass.tube_downstream)
    return tubes


def page_tubing() -> None:
    st.title(t("Tubing Configuration"))
    top = st.container()
    tubes = _all_tubes()
    sel = st.selectbox("Tube segment", list(tubes), format_func=lambda k: tubes[k][0], key=key("tube_sel"))
    with st.container(border=True):
        W.tube_editor(tubes[sel][1], f"tube:{sel}")
    with st.expander("Apply ID / length to several segments"):
        targets = st.multiselect("Segments", list(tubes), format_func=lambda k: tubes[k][0], key=key("tube_multi"))
        c1, c2 = st.columns(2)
        new_id = c1.number_input("New inner diameter [mm] (0 = keep)", value=0.0, min_value=0.0, step=0.05, key=key("tm_id"))
        new_len = c2.number_input("New length [m] (0 = keep)", value=0.0, min_value=0.0, step=0.01, key=key("tm_len"))
        if st.button(t("Apply"), key=key("tm_apply")):
            for k in targets:
                if new_id > 0:
                    tubes[k][1].inner_diameter_mm = new_id
                if new_len > 0:
                    tubes[k][1].length_m = new_len
            st.session_state.rev += 1
            st.rerun()
    res = simulate()
    with top:
        solver_badge(res)
    e = res.edges[res.edges.kind == "tube"]
    st.subheader("All tube segments")
    view = pd.DataFrame({"segment": e.label, "L [m]": [tubes.get(p, (None, None))[1].length_m if p in tubes else np.nan for p in e.config_path],
                         "ID [mm]": e.inner_diameter_mm, "Q [mL/min]": e.Q_ml_min, "v [mm/s]": e.v_m_s * 1e3, "Re": e.Re, "regime": e.regime,
                         "R [Pa s/m^3]": e.R_secant, "dp [Pa]": e.dp_loss_pa, "tau_w [mPa]": e.wall_shear_pa * 1e3,
                         "V [uL]": e.volume_m3 * 1e9, "t_res [s]": e.residence_time_s, "p_in [Pa]": e.p_in_pa, "p_out [Pa]": e.p_out_pa})
    st.dataframe(view.replace([np.inf], np.nan), hide_index=True, width="stretch")
    st.metric("Total medium-wetted volume (circuit + reservoir fill)", f"{res.volumes['total_medium']*1e6:.3f} mL",
              f"circuit {res.volumes['circuit_total']*1e6:.3f} mL", delta_color="off")
    show_warnings(res, limit=10)


def page_splitters() -> None:
    st.title(t("Splitter Configuration"))
    c = cfg()
    top = st.container()
    if c.layout != "full":
        st.info("Splitters are only used in the full layout.")
        return
    st.caption("Unknown geometry-dependent losses are represented by adjustable / calibratable K values. "
               "This is a 1D network model - no 3D CFD of the splitter is performed or implied.")
    n = c.n_reactors
    tab1, tab2 = st.tabs([c.splitter_in.name, c.splitter_out.name])
    with tab1:
        W.splitter_editor(c.splitter_in, n, "sp_in")
    with tab2:
        W.splitter_editor(c.splitter_out, n, "sp_out")
    st.markdown("**Bypass integration**")
    integ = ["integrated_port", "tee_pieces"]
    c.bypass.integration = st.radio("Bypass connection", integ, integ.index(c.bypass.integration), horizontal=True, key=key("bp_integ"),
                                    format_func=lambda x: {"integrated_port": "Splitters with integrated bypass port (5-way)",
                                                           "tee_pieces": "4-way splitters + T-pieces"}[x])
    if c.bypass.integration == "integrated_port":
        st.caption("Bypass port channel of splitter 1 / splitter 2:")
        c.bypass.splitter_port_in = W.port_editor_table([c.bypass.splitter_port_in], "bp_port_in")[0]
        c.bypass.splitter_port_out = W.port_editor_table([c.bypass.splitter_port_out], "bp_port_out")[0]
    else:
        st.caption("T-piece in feed line / return line:")
        W.tee_editor(c.bypass.tee_in, "tee_in")
        W.tee_editor(c.bypass.tee_out, "tee_out")
    res = simulate()
    with top:
        solver_badge(res)
        metrics_row(res)
    sc = res.edges[res.edges.kind.isin(["splitter_channel", "tee"])]
    st.dataframe(pd.DataFrame({"channel": sc.label, "Q [mL/min]": sc.Q_ml_min, "dp [Pa]": sc.dp_pa, "Re": sc.Re}), hide_index=True,
                 width="stretch")
    st.plotly_chart(plots.fig_flow_share(res), width="stretch")


def page_reactors() -> None:
    st.title(t("Bioreactor Configuration"))
    c = cfg()
    top = st.container()
    n_new = st.number_input(t("Number of reactors"), value=c.n_reactors, min_value=1, max_value=16, step=1, key=key("nreact"))
    if n_new != c.n_reactors:
        set_reactor_count(c, int(n_new))
        st.session_state.rev += 1
        st.rerun()
    tabs = st.tabs([p.reactor.name for p in c.reactor_paths])
    for i, tab in enumerate(tabs):
        with tab:
            W.reactor_editor(c.reactor_paths[i].reactor, f"rx{i}")
            if i == 0 and st.button(t("Apply to all reactors"), key=key("rx_all")):
                for j, p in enumerate(c.reactor_paths[1:], start=2):
                    nm = p.reactor.name
                    p.reactor = c.reactor_paths[0].reactor.model_copy(deep=True)
                    p.reactor.name = nm
                st.session_state.rev += 1
                st.rerun()
    res = simulate()
    with top:
        solver_badge(res)
        metrics_row(res)
    r = res.reactors
    st.dataframe(pd.DataFrame({"reactor": r.reactor, "state": r.state, "Q [mL/min]": r.Q_ml_min, "p_in [Pa]": r.p_in_pa,
                               "p_out [Pa]": r.p_out_pa, "dp [Pa]": r.dp_pa, "dp scaffold [Pa]": r.dp_scaffold_pa,
                               "u_s [mm/s]": r.superficial_velocity_m_s * 1e3, "u_pore est. [mm/s]": r.pore_velocity_estimate_m_s * 1e3,
                               "tau est. [mPa]": r.shear_stress_estimate_pa * 1e3, "R [Pa s/m^3]": r.R_secant,
                               "t_res [s]": r.residence_time_s}).replace([np.inf], np.nan), hide_index=True, width="stretch")
    st.caption("Classification: flows/pressures numerical; superficial velocity calculated; pore velocity and shear stress are "
               "model-based estimates (documented capillary pore model). No value is experimentally validated yet.")
    st.plotly_chart(plots.fig_reactor_flows(res), width="stretch")
    show_warnings(res, limit=8)


def page_throttles() -> None:
    st.title(t("Throttle Configuration"))
    c = cfg()
    top = st.container()
    st.caption("Each change recomputes all flows and pressures of the system. Note: 50 % opening does NOT mean 50 % flow - "
               "the flow depends on the throttle characteristic and on all other resistances of the network.")
    ths = [(f"reactor_paths.{i}.throttle", p.throttle) for i, p in enumerate(c.reactor_paths)]
    if c.bypass.enabled and c.layout == "full":
        ths.append(("bypass.throttle", c.bypass.throttle))
    cols = st.columns(len(ths))
    for (path, th), col in zip(ths, cols):
        th.opening_percent = col.slider(f"{th.name} [%]", 0.0, 100.0, float(th.opening_percent), 0.5, key=key("qs", path))
    tabs = st.tabs([th.name for _, th in ths])
    for (path, th), tab in zip(ths, tabs):
        with tab:
            W.throttle_editor(th, f"thr:{path}", show_opening=False)
            th2 = th.model_copy()
            ops = np.linspace(0, 100, 101)
            cap = []
            for o in ops:
                th2.opening_percent = float(o)
                cap.append(th2.relative_capacity())
            fig = go.Figure(go.Scatter(x=ops, y=cap, mode="lines", line=dict(color=plots.SERIES[0], width=2)))
            st.plotly_chart(plots.style(fig, t("Throttle opening characteristic"), "Opening [%]", "Relative flow capacity g [-]",
                                        height=300, legend=False), width="stretch", key=key("thrchar", path))
            if st.button("Compute flow vs. opening for this throttle", key=key("thrsweep", path)):
                df = sweep_1d(c, ParameterSpec(path=f"{path}.opening_percent", low=2, high=100, n=25))
                ycols = [k for k in df.columns if k.startswith("Q_reactor_") or k == "Q_bypass_ml_min"]
                st.plotly_chart(plots.fig_sweep(df, f"{path}.opening_percent", ycols, f"{th.name} opening [%]", "Flow rate Q [mL/min]",
                                                "Influence of throttle setting on all flow paths",
                                                names=[y.replace("_ml_min", "").replace("Q_", "") for y in ycols]), width="stretch")
    res = simulate()
    with top:
        solver_badge(res)
        metrics_row(res)
        st.plotly_chart(plots.fig_reactor_flows(res), width="stretch", key="thr_flows")


def page_bypass() -> None:
    st.title(t("Bypass Configuration"))
    c = cfg()
    b = c.bypass
    top = st.container()
    b.enabled = st.toggle(t("Bypass enabled"), b.enabled, key=key("bp_on"))
    if b.enabled:
        integ = ["integrated_port", "tee_pieces"]
        b.integration = st.radio(t("Integration"), integ, integ.index(b.integration), horizontal=True, key=key("bp_integ2"))
        st.markdown("**Bypass throttle**")
        W.throttle_editor(b.throttle, "bp_thr")
        W.num(b, "extra_resistance", "Additional linear resistance", "bp", "Pa s/m^3", 0.0, fmt="%.3e")
        with st.expander("Bypass tube upstream (splitter 1 -> throttle)"):
            W.tube_editor(b.tube_upstream, "bp_up")
        with st.expander("Bypass tube downstream (throttle -> splitter 2)"):
            W.tube_editor(b.tube_downstream, "bp_down")
    res = simulate()
    with top:
        solver_badge(res)
        metrics_row(res)
        if b.enabled and res.ok:
            q = res.solver.edge_flows
            st.caption(f"Mass balance: Q_pump = {res.pump['Q_ml_min']:.6g} mL/min = sum(Q_reactor) + Q_bypass = "
                       f"{(sum(res.reactor_flows()) + res.bypass['Q'])/ML_MIN:.6g} mL/min "
                       f"(difference {res.bypass.get('mass_balance_error_m3s', 0):.2e} m^3/s). "
                       f"Bypass dp = {res.bypass['dp']:.4g} Pa.")
    st.subheader(t("Comparison with / without bypass"))
    on = c.model_copy(deep=True)
    on.bypass.enabled = True
    off = c.model_copy(deep=True)
    off.bypass.enabled = False
    r_on, r_off = run_simulation(on), run_simulation(off)
    comp = pd.DataFrame([{"configuration": n, **{k: v for k, v in r.summary().items() if k != "converged"}} for n, r in
                         (("with bypass", r_on), ("without bypass", r_off))])
    st.dataframe(comp, hide_index=True, width="stretch")
    st.plotly_chart(plots.fig_compare_configs({"with bypass": r_on, "without bypass": r_off}), width="stretch")
    if b.enabled and st.button("Bypass opening study (5 ... 100 %)", key=key("bp_study")):
        df = sweep_1d(c, ParameterSpec(path="bypass.throttle.opening_percent", low=5, high=100, n=20))
        ycols = [k for k in df.columns if k.startswith("Q_reactor_")] + ["Q_bypass_ml_min"]
        st.plotly_chart(plots.fig_sweep(df, "bypass.throttle.opening_percent", ycols, "Bypass throttle opening [%]", "Flow rate Q [mL/min]",
                                        "Bypass opening vs. flow distribution", names=[y.replace("_ml_min", "") for y in ycols]),
                        width="stretch")
        st.plotly_chart(plots.fig_sweep(df, "bypass.throttle.opening_percent", ["pump_dp_pa"], "Bypass throttle opening [%]",
                                        "Pump pressure difference [Pa]", "Effect on the pump operating point"), width="stretch")
