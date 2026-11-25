"""Scenarios & project management, scientific documentation and export pages."""
from __future__ import annotations

import datetime as _dt
from pathlib import Path

import pandas as pd
import streamlit as st

from core import APP_NAME, SOFTWARE_VERSION
from core.export import to_csv_zip_bytes, to_excel_bytes, to_json_str
from core.optimization import default_variables, optimize_system
from core.project import (ProjectFile, compare_configs, config_hash, dumps_project, duplicate_project, load_project, loads_project,
                          save_project, save_simulation_run)
from core.sensitivity import monte_carlo, sweep_1d
from core.simulation import run_simulation
from core.verification import report_markdown, run_reference_cases
from scenarios import SCENARIOS, SCENARIO_BY_KEY
from visualization import plots
from visualization.diagram import system_diagram
from visualization.export import export_figure

from .i18n import t
from .state import cfg, key, set_config, simulate

ROOT = Path(__file__).resolve().parents[1]


def page_scenarios_projects() -> None:
    st.title(t("Scenarios & Projects"))
    tab1, tab2, tab3 = st.tabs(["Predefined scenarios", t("Project"), "Compare configurations"])
    with tab1:
        st.warning("All scenarios use clearly marked EXAMPLE parameters until real measurements are available.")
        sk = st.selectbox("Scenario", [s.key for s in SCENARIOS], format_func=lambda k: SCENARIO_BY_KEY[k].title, key="sc_sel")
        sc = SCENARIO_BY_KEY[sk]
        st.write(sc.description)
        c1, c2 = st.columns(2)
        if c1.button(t("Load scenario"), key="sc_load"):
            set_config(sc.build(), note=f"loaded scenario {sc.key}")
            st.success(f"Loaded '{sc.title}'. All configuration pages now show this system.")
        if sc.study and c2.button("Run scenario study", key="sc_study"):
            base = sc.build()
            typ = sc.study["type"]
            with st.spinner("running ..."):
                if typ == "sweep_1d":
                    spec = sc.study["spec"]
                    df = sweep_1d(base, spec)
                    ys = ["pump_dp_pa"] if base.layout == "single_line" else [c for c in df.columns if c.startswith("Q_reactor_")] + (
                        ["Q_bypass_ml_min"] if "Q_bypass_ml_min" in df else [])
                    st.plotly_chart(plots.fig_sweep(df, spec.path, ys, spec.label, "Pump pressure difference [Pa]" if ys == ["pump_dp_pa"] else "Flow rate Q [mL/min]",
                                                    sc.title, logx=spec.scale == "log", logy=(sk in ("02_tube_diameters",)),
                                                    names=[y.replace("_ml_min", "") for y in ys]), width="stretch")
                    st.dataframe(df, width="stretch")
                elif typ == "compare":
                    results = {n: run_simulation(c) for n, c in sc.study["configs"]()}
                    st.plotly_chart(plots.fig_compare_configs(results), width="stretch")
                    st.dataframe(pd.DataFrame([{"configuration": n, **r.summary()} for n, r in results.items()]), width="stretch")
                elif typ == "monte_carlo":
                    df, summ = monte_carlo(base, sc.study["specs"], sc.study.get("n_samples", 200))
                    st.plotly_chart(plots.fig_histogram(df, "cv_percent", "CV of reactor flows [%]", "Effect of tube ID tolerances"), width="stretch")
                    st.dataframe(summ, width="stretch")
                elif typ == "optimize":
                    prob = sc.study["problem"].model_copy(deep=True)
                    prob.variables = default_variables(base)
                    res, cfg_opt = optimize_system(base, prob)
                    st.write("feasible:", res.feasible, res.metrics, res.x)
                    st.plotly_chart(plots.fig_reactor_flows(run_simulation(cfg_opt)), width="stretch")
                    st.session_state.sc_opt_cfg = cfg_opt
            if typ == "optimize":
                st.info("The optimised configuration can be applied on the Optimization page or loaded here.")
        if st.session_state.get("sc_opt_cfg") is not None and st.button("Load optimised scenario configuration", key="sc_optload"):
            set_config(st.session_state.sc_opt_cfg, note="loaded optimised scenario")
    with tab2:
        proj: ProjectFile = st.session_state.project
        c1, c2 = st.columns(2)
        proj.name = c1.text_input("Project name", proj.name, key=key("pj_name"))
        cfg().name = c2.text_input("Configuration name", cfg().name, key=key("pj_cfg"))
        cfg().description = st.text_area("Description", cfg().description, key=key("pj_desc"))
        st.caption(f"Project version {proj.project_version} - created {proj.created} - modified {proj.modified} - "
                   f"software V{SOFTWARE_VERSION} - config hash {config_hash(cfg())[:12]}")
        c1, c2 = st.columns([3, 1])
        note = c1.text_input("Change note", "", key="pj_note")
        if c2.button("New version", key="pj_ver") and note:
            proj.new_version(note)
            st.success(f"Version {proj.project_version} created.")
        st.dataframe(pd.DataFrame([e.model_dump() for e in proj.changelog]), hide_index=True, width="stretch")
        c1, c2, c3 = st.columns(3)
        c1.download_button("Download project (JSON)", dumps_project(proj, "json").encode(), f"{proj.name}.json", key="pj_dl_json")
        c2.download_button("Download project (YAML)", dumps_project(proj, "yaml").encode(), f"{proj.name}.yaml", key="pj_dl_yaml")
        if c3.button("Save to projects/ folder", key="pj_save"):
            p = save_project(proj, ROOT / "projects" / f"{proj.name.replace(' ', '_')}_v{proj.project_version}.json")
            st.success(f"Saved {p}")
        st.markdown(f"**{t('Load project')}**")
        up = st.file_uploader("Project / configuration file (JSON or YAML)", type=["json", "yaml", "yml"], key="pj_up")
        if up is not None and st.button("Load uploaded file", key="pj_load"):
            try:
                st.session_state.project = loads_project(up.getvalue())
                st.session_state.rev += 1
                st.rerun()
            except Exception as exc:
                st.error(f"Could not load: {exc}")
        files = sorted((ROOT / "projects").glob("*.json")) + sorted((ROOT / "projects").glob("*.y*ml"))
        if files:
            f = st.selectbox("Saved projects", files, format_func=lambda p: p.name, key="pj_files")
            c1, c2 = st.columns(2)
            if c1.button("Load selected", key="pj_load2"):
                st.session_state.project = load_project(f)
                st.session_state.rev += 1
                st.rerun()
            if c2.button("Duplicate current project", key="pj_dup"):
                dup = duplicate_project(proj, proj.name + " (copy)")
                st.session_state.project = dup
                st.session_state.rev += 1
                st.rerun()
        else:
            if st.button("Duplicate current project", key="pj_dup2"):
                st.session_state.project = duplicate_project(proj, proj.name + " (copy)")
                st.session_state.rev += 1
                st.rerun()
    with tab3:
        st.caption("Compare the current configuration with a saved project or a scenario (parameter differences and results).")
        src = st.radio("Compare with", ["scenario", "uploaded file"], horizontal=True, key="cmp_src")
        other = None
        if src == "scenario":
            k = st.selectbox("Scenario", [s.key for s in SCENARIOS], format_func=lambda k: SCENARIO_BY_KEY[k].title, key="cmp_sc")
            other = SCENARIO_BY_KEY[k].build()
        else:
            upc = st.file_uploader("Configuration", type=["json", "yaml", "yml"], key="cmp_up")
            if upc is not None:
                other = loads_project(upc.getvalue()).config
        if other is not None:
            diff = compare_configs(cfg(), other, "current", "other")
            st.write(f"{len(diff)} differing parameters")
            st.dataframe(diff, hide_index=True, width="stretch", height=300)
            results = {"current": simulate(), "other": run_simulation(other)}
            st.plotly_chart(plots.fig_compare_configs(results), width="stretch")
            st.dataframe(pd.DataFrame([{"configuration": n, **r.summary()} for n, r in results.items()]), width="stretch")


def page_documentation() -> None:
    st.title(t("Scientific Documentation"))
    docs = {
        "Scientific documentation": ROOT / "documentation" / "scientific_documentation.md",
        "Verification report (reference cases)": ROOT / "documentation" / "verification_report.md",
        "Test documentation": ROOT / "documentation" / "test_documentation.md",
        "User guide / installation": ROOT / "README.md",
    }
    sel = st.selectbox("Document", list(docs), key="doc_sel")
    p = docs[sel]
    if p.exists():
        st.markdown(p.read_text(encoding="utf-8"))
    else:
        st.warning(f"{p} not found.")
    st.divider()
    if st.button("Re-run analytical reference cases now", key="doc_ref"):
        cases = run_reference_cases()
        st.markdown(report_markdown(cases))
        st.success(f"{sum(c.passed for c in cases)} / {len(cases)} reference cases passed.")


FIGURES = {
    "System diagram": lambda r: system_diagram(r, height=640),
    "Flow per bioreactor": lambda r: plots.fig_reactor_flows(r),
    "Percentage flow distribution": lambda r: plots.fig_flow_share(r),
    "Pressure along flow paths": lambda r: plots.fig_pressure_profile(r),
    "Pressure loss per component": lambda r: plots.fig_dp_components(r),
    "Velocity per component": lambda r: plots.fig_velocity(r),
    "Reynolds number": lambda r: plots.fig_reynolds(r),
    "Wall shear stress": lambda r: plots.fig_wall_shear(r),
    "Pump / system curve": lambda r: plots.fig_pump_system(r.config, r),
    "Volume breakdown": lambda r: plots.fig_volume_breakdown(r),
}


def page_export() -> None:
    st.title(t("Export"))
    res = simulate()
    st.subheader(t("Data"))
    stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M")
    c1, c2, c3 = st.columns(3)
    c1.download_button("Excel (all tables)", to_excel_bytes(res), f"perfusion_results_{stamp}.xlsx", key="ex_xlsx")
    c2.download_button("CSV (ZIP of all tables)", to_csv_zip_bytes(res), f"perfusion_results_{stamp}.zip", key="ex_zip")
    c3.download_button("JSON (results + configuration + version)", to_json_str(res).encode(), f"perfusion_results_{stamp}.json", key="ex_json")
    if st.button("Save run to results/ folder", key="ex_save"):
        st.success(f"Saved to {save_simulation_run(res, ROOT / 'results', 'export')}")
    st.subheader(t("Figures"))
    fsel = st.selectbox("Figure", list(FIGURES), key="ex_fig")
    fmt = st.radio("Format", ["png", "svg", "pdf", "html"], horizontal=True, key="ex_fmt",
                   format_func=lambda f: {"png": "PNG (300 dpi)", "svg": "SVG", "pdf": "PDF", "html": "interactive HTML"}[f])
    fig = FIGURES[fsel](res)
    st.plotly_chart(fig, width="stretch", key="ex_preview")
    if st.button("Prepare figure file", key="ex_prep"):
        with st.spinner("rendering ..."):
            data, engine = export_figure(fig, fmt)
        st.session_state.ex_file = (data, f"{fsel.replace(' ', '_').replace('/', '-')}.{fmt}", engine)
    if "ex_file" in st.session_state:
        data, name, engine = st.session_state.ex_file
        st.download_button(f"Download {name}", data, name, key="ex_dl")
        st.caption(f"Rendered with {engine}." + (" Kaleido/Chrome not available - Matplotlib fallback used (simplified styling)."
                                                  if engine != "kaleido" and engine != "plotly" else ""))
    st.subheader("Scientific simulation report (PDF)")
    c1, c2 = st.columns(2)
    title = c1.text_input("Report title", f"Hydraulic simulation report - {cfg().name}", key="rep_title")
    author = c2.text_input("Author", "", key="rep_author")
    inc_exp = st.checkbox("Include last experimental comparison (Experimental Validation page)",
                          value="exp_result" in st.session_state, key="rep_exp")
    if st.button(t("Generate PDF report"), type="primary", key="rep_gen"):
        from visualization.report_pdf import build_report

        with st.spinner("building report (renders all figures) ..."):
            pdf = build_report(res, title, author, st.session_state.get("exp_result") if inc_exp else None)
        st.session_state.rep_pdf = pdf
    if "rep_pdf" in st.session_state:
        st.download_button("Download report PDF", st.session_state.rep_pdf, f"simulation_report_{stamp}.pdf", "application/pdf", key="rep_dl")
