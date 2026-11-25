"""Dashboard, interactive system diagram and simulation results pages."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import streamlit as st

from core.project import save_simulation_run
from core.simulation import convergence_info
from core.system import get_by_path
from visualization import plots
from visualization.diagram import system_diagram

from .i18n import t
from .state import cfg, key, simulate
from . import widgets as W

PROJECT_ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]


def show_warnings(res, limit: int | None = None) -> None:
    ws = sorted(res.warnings, key=lambda w: {"error": 0, "warning": 1, "info": 2}[w.level])
    if not ws:
        st.success(t("No warnings."))
        return
    for w in ws[:limit] if limit else ws:
        {"error": st.error, "warning": st.warning, "info": st.info}[w.level](w.message)


def metrics_row(res) -> None:
    s = res.summary()
    cv = s["cv_reactors"]
    c = st.columns(3)
    c[0].metric(t("Total flow"), f"{s['Q_total_ml_min']:.4g} mL/min")
    c[1].metric(t("Pump pressure difference"), f"{s['pump_dp_pa']/100:.4g} mbar", f"{s['pump_dp_pa']:.4g} Pa", delta_color="off")
    c[2].metric(t("Hydraulic power"), f"{s['hydraulic_power_w']*1e6:.4g} uW")
    c = st.columns(3)
    c[0].metric(t("Bypass flow"), f"{s['bypass_ml_min']:.4g} mL/min", f"{100*s['bypass_fraction']:.1f} % of Q", delta_color="off")
    c[1].metric(t("Flow uniformity (CV)"), f"{100*cv:.2f} %" if np.isfinite(cv) else "-",
                help="Coefficient of variation of the reactor flows (0 % = perfectly uniform)")
    c[2].metric(t("System volume"), f"{s['system_volume_ml']:.3g} mL", t("circuit, excl. reservoir"), delta_color="off")


def solver_badge(res) -> None:
    s = res.solver
    if s.converged:
        st.caption(f"{t('Solver')}: {t('converged')} ({s.method}, {s.iterations} {t('iterations')}), "
                   f"max mass residual {s.max_mass_residual:.2e} m^3/s, max pressure residual {s.max_pressure_residual:.2e} Pa")
    else:
        st.error(f"{t('Solver')}: {t('NOT converged')} - " + "; ".join(s.errors + s.messages))


def page_dashboard() -> None:
    res = simulate()
    st.title(t("Dashboard"))
    st.caption(f"**{cfg().name}** - " + t("Example parameters - not measured. Replace with real data."))
    solver_badge(res)
    metrics_row(res)
    if not res.reactors.empty:
        cols = st.columns(max(len(res.reactors), 1))
        for i, (_, r) in enumerate(res.reactors.iterrows()):
            cols[i].metric(r.reactor, f"{r.Q_ml_min:.3g} mL/min", f"{r.share_percent:.1f} % of Q", delta_color="off")
    c1, c2 = st.columns([3, 2])
    with c1:
        st.plotly_chart(system_diagram(res, height=560), width="stretch", key="dash_diag")
    with c2:
        st.plotly_chart(plots.fig_reactor_flows(res), width="stretch")
        st.plotly_chart(plots.fig_flow_share(res), width="stretch")
    st.subheader(t("Warnings"))
    show_warnings(res)


def _edit_component(path: str, edge_kind: str) -> None:
    from core.bioreactors import Bioreactor
    from core.bypass import TeePiece
    from core.pumps import PumpConfig
    from core.splitters import Splitter, SplitterPort
    from core.throttles import Throttle
    from core.tubing import Tube

    obj = get_by_path(cfg(), path) if path else None
    k = f"diag:{path}"
    if isinstance(obj, Tube):
        W.tube_editor(obj, k)
    elif isinstance(obj, Throttle):
        W.throttle_editor(obj, k)
    elif isinstance(obj, Bioreactor):
        W.reactor_editor(obj, k)
    elif isinstance(obj, PumpConfig):
        W.pump_quick_editor(obj, k)
    elif isinstance(obj, SplitterPort):
        parent_path = path.rsplit(".", 2)[0] if ".branch_ports." in path else None
        if parent_path:
            sp = get_by_path(cfg(), parent_path)
            if sp.mode == "symmetric":
                st.info("Splitter in symmetric mode: edit port 1 (applies to all ports) or switch to asymmetric on the splitter page.")
        c1, c2, c3 = st.columns(3)
        W.num(obj, "channel_diameter_mm", "Channel diameter", k, "mm", 0.01, step=0.1, container=c1)
        W.num(obj, "channel_length_mm", "Channel length", k, "mm", 0.0, step=0.5, container=c2)
        W.num(obj, "K", "K", k, "-", 0.0, step=0.1, container=c3)
    elif isinstance(obj, Splitter):
        W.splitter_editor(obj, cfg().n_reactors, k)
    elif isinstance(obj, TeePiece):
        W.tee_editor(obj, k)
    else:
        st.info("No editable parameters for this element.")


def page_diagram() -> None:
    st.title(t("System Diagram"))
    st.caption(t("Click a component in the diagram or select it here to edit its parameters."))
    top = st.container()
    res0 = st.session_state.get("last_result") or simulate()
    edges = {e.id: e for e in res0.network.edges.values()}
    options = list(edges)
    # a click in the diagram (stored by Streamlit under the chart key) selects the component
    ev = st.session_state.get(key("diag_chart"))
    try:
        pts = ev["selection"]["points"] if ev else []
    except Exception:
        pts = []
    if pts:
        cd = pts[0].get("customdata")
        cd = cd[0] if isinstance(cd, list) else cd
        if cd in edges and cd != st.session_state.get("last_click"):
            st.session_state.last_click = cd
            st.session_state[key("diag_sel")] = cd
    sel = st.session_state.get("selected_edge")
    if sel not in options:
        sel = next((e for e in options if e.startswith("throttle")), options[0])
    choice = st.selectbox(t("Select component"), options, index=options.index(sel),
                          format_func=lambda e: f"{edges[e].label}  [{edges[e].kind}]", key=key("diag_sel"))
    st.session_state.selected_edge = choice
    e = edges[choice]
    with st.container(border=True):
        st.markdown(f"**{e.label}** - `{e.config_path}`")
        _edit_component(e.config_path, e.kind)
    res = simulate()
    with top:
        solver_badge(res)
        metrics_row(res)
        labels = st.toggle("Show labels", True, key="diag_labels")
        st.plotly_chart(system_diagram(res, selected=choice, show_labels=labels, height=680), width="stretch",
                        on_select="rerun", selection_mode="points", key=key("diag_chart"))


def page_results() -> None:
    res = simulate()
    st.title(t("Simulation Results"))
    solver_badge(res)
    metrics_row(res)
    tabs = st.tabs([t("Reactors"), t("Segments"), t("Nodes"), t("Plots"), "Pump & bypass", "Volumes", t("Convergence"), t("Warnings")])
    with tabs[0]:
        r = res.reactors.copy()
        if not r.empty:
            view = pd.DataFrame({
                "reactor": r.reactor, "state": r.state, "Q [mL/min]": r.Q_ml_min, "share [%]": r.share_percent,
                "p_in [Pa]": r.p_in_pa, "p_out [Pa]": r.p_out_pa, "dp [Pa]": r.dp_pa, "dp scaffold [Pa]": r.dp_scaffold_pa,
                "chamber v [mm/s]": r.chamber_velocity_m_s * 1e3, "superficial u [mm/s]": r.superficial_velocity_m_s * 1e3,
                "pore velocity est. [mm/s]": r.pore_velocity_estimate_m_s * 1e3, "Re_k [-]": r.Re_permeability,
                "pore shear est. [mPa]": r.shear_stress_estimate_pa * 1e3, "R [Pa s/m^3]": r.R_secant,
                "residence time [s]": r.residence_time_s, "volume [mL]": r.volume_ml, "classification": r.quantity_type,
            })
            st.dataframe(view, width="stretch", hide_index=True)
            st.caption("Q, p: numerical network solution. Superficial velocity: calculated (Q/A). Pore velocity: estimate "
                       "(Dupuit-Forchheimer u/eps). Pore shear: model-based ESTIMATE (cylindrical capillary model). "
                       "No quantity is experimentally validated until compared with measurements.")
            c1, c2 = st.columns(2)
            c1.plotly_chart(plots.fig_reactor_quantity(res, "dp_pa", "Differential pressure dp [Pa]", "Reactor differential pressure"), width="stretch")
            c2.plotly_chart(plots.fig_reactor_quantity(res, "shear_stress_estimate_pa", "Estimated pore shear stress [mPa]",
                                                       "Scaffold shear stress (capillary-model estimate)", factor=1e3), width="stretch")
    with tabs[1]:
        e = res.edges
        view = pd.DataFrame({
            "component": e.label, "kind": e.kind, "path": e.group, "Q [mL/min]": e.Q_ml_min, "v [mm/s]": e.get("v_m_s") * 1e3,
            "Re": e.get("Re"), "regime": e.get("regime"), "p_in [Pa]": e.p_in_pa, "p_out [Pa]": e.p_out_pa,
            "dp loss [Pa]": e.get("dp_loss_pa"), "dp hydrostatic [Pa]": e.get("dp_hydrostatic_pa"), "R [Pa s/m^3]": e.get("R_secant"),
            "tau_w [mPa]": e.get("wall_shear_pa") * 1e3, "volume [uL]": e.get("volume_m3") * 1e9,
            "residence [s]": e.get("residence_time_s"), "ID [mm]": e.get("inner_diameter_mm"), "method": e.get("friction_method"),
            "classification": e.get("quantity_type"),
        })
        st.dataframe(view.replace([np.inf], np.nan), width="stretch", hide_index=True, height=600)
    with tabs[2]:
        n = res.nodes.copy()
        n["p [mbar]"] = n.p_pa / 100
        st.dataframe(n[["id", "label", "kind", "p_pa", "p [mbar]", "fixed"]], width="stretch", hide_index=True)
    with tabs[3]:
        st.plotly_chart(plots.fig_pressure_profile(res), width="stretch")
        c1, c2 = st.columns(2)
        c1.plotly_chart(plots.fig_dp_components(res), width="stretch")
        c2.plotly_chart(plots.fig_velocity(res), width="stretch")
        c1, c2 = st.columns(2)
        c1.plotly_chart(plots.fig_reynolds(res), width="stretch")
        c2.plotly_chart(plots.fig_wall_shear(res), width="stretch")
    with tabs[4]:
        st.plotly_chart(plots.fig_pump_system(cfg(), res), width="stretch")
        st.json({k: (v if not isinstance(v, float) or math.isfinite(v) else None) for k, v in res.pump.items()})
        st.json(res.bypass)
    with tabs[5]:
        st.plotly_chart(plots.fig_volume_breakdown(res), width="stretch")
        if "circulation_time_s" in res.volumes:
            st.metric("Mean circulation time (total medium / Q)", f"{res.volumes['circulation_time_s']/60:.3g} min")
    with tabs[6]:
        st.json(convergence_info(res.solver))
        st.markdown("**Residuals per equation** (mass balance in m^3/s, pressure equations in Pa)")
        rr = pd.DataFrame([{"equation": f"mass balance @ {k}", "residual": v, "unit": "m^3/s"} for k, v in res.solver.mass_residuals.items()]
                          + [{"equation": f"pressure eq. {k}", "residual": v, "unit": "Pa"} for k, v in res.solver.pressure_residuals.items()])
        st.dataframe(rr, width="stretch", hide_index=True)
        st.plotly_chart(plots.fig_residuals(res), width="stretch")
    with tabs[7]:
        show_warnings(res)
    label = st.text_input("Run label", "simulation", key="runlabel")
    if st.button(t("Save run"), key="saverun"):
        d = save_simulation_run(res, PROJECT_ROOT / "results", label)
        st.success(f"Saved to {d}")
