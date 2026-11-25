"""Parameter studies, optimisation and experimental validation pages."""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

from core.optimization import OBJECTIVE_LABELS, DecisionVariable, OptimizationProblem, default_variables, optimize_system, result_table
from core.project import save_study
from core.sensitivity import (ParameterSpec, get_param, latin_hypercube_study, local_sensitivity, monte_carlo, parameter_catalog,
                              sweep_1d, sweep_grid, tube_tolerance_study)
from core.validation import TEMPLATES, CalibrationParameter, calibrate, compare, load_experimental_data
from visualization import plots

from .i18n import t
from .state import cfg, key, set_config, simulate

ROOT = Path(__file__).resolve().parents[1]

OUTPUT_LABELS = {
    "Q_total_ml_min": "Total flow [mL/min]", "pump_dp_pa": "Pump pressure difference [Pa]", "hydraulic_power_w": "Hydraulic power [W]",
    "Q_bypass_ml_min": "Bypass flow [mL/min]", "bypass_fraction_percent": "Bypass fraction [%]", "cv_percent": "CV of reactor flows [%]",
    "max_rel_dev_percent": "Max. relative deviation [%]", "max_reactor_inlet_pressure_pa": "Max. reactor inlet pressure [Pa]",
    "system_volume_ml": "Circuit volume [mL]", "min_max_ratio": "Q_min/Q_max [-]",
}


def _output_label(o: str) -> str:
    if o in OUTPUT_LABELS:
        return OUTPUT_LABELS[o]
    if o.startswith("Q_reactor_"):
        return f"Reactor {o.split('_')[2]} flow [mL/min]"
    if o.startswith("share_reactor_"):
        return f"Reactor {o.split('_')[2]} share [%]"
    if o.startswith("p_reactor_"):
        return f"Reactor {o.split('_')[2]} inlet pressure [Pa]"
    if o.startswith("dp_reactor_"):
        return f"Reactor {o.split('_')[2]} dp [Pa]"
    return o


def _param_input(label: str, k: str, catalog: dict[str, str], default: str | None = None) -> tuple[str, str]:
    opts = list(catalog) + ["<custom path>"]
    idx = opts.index(default) if default in opts else 0
    sel = st.selectbox(label, opts, idx, format_func=lambda p: catalog.get(p, p), key=key(k, "sel"))
    if sel == "<custom path>":
        sel = st.text_input("Configuration path (e.g. reactor_paths.0.reactor.scaffold.porosity, '*' = all list entries)",
                            "reactor_paths.0.reactor.scaffold.porosity", key=key(k, "custom"))
    return sel, catalog.get(sel, sel)


def _range_inputs(path: str, k: str, n_default: int = 15):
    try:
        nom = float(get_param(cfg(), path))
    except Exception:
        nom = 1.0
    c1, c2, c3, c4 = st.columns(4)
    lo = c1.number_input("from", value=nom * 0.5 if nom else 0.0, format="%.6g", key=key(k, "lo", path))
    hi = c2.number_input("to", value=nom * 1.5 if nom else 1.0, format="%.6g", key=key(k, "hi", path))
    n = int(c3.number_input("points", value=n_default, min_value=2, max_value=500, key=key(k, "n", path)))
    scale = c4.selectbox("scale", ["linear", "log"], key=key(k, "sc", path))
    return ParameterSpec(path=path, low=lo, high=hi, n=n, scale=scale)


def page_studies() -> None:
    st.title(t("Parameter Studies"))
    c = cfg()
    cat = parameter_catalog(c)
    kinds = ["1D sweep", "2D sweep (heat map / surface)", "Multi-dimensional (Latin hypercube)", "Local sensitivity analysis",
             "Monte-Carlo uncertainty analysis", "Manufacturing tolerances (tube ID)"]
    kind = st.radio(t("Study type"), kinds, horizontal=True, key=key("stype"))
    prog = st.progress(0.0)
    out = None
    if kind == kinds[0]:
        path, lbl = _param_input("Parameter", "s1", cat, "reactor_paths.*.tube_to_reactor.inner_diameter_mm")
        spec = _range_inputs(path, "s1")
        if st.button(t("Run"), key=key("run1")):
            out = ("1d", sweep_1d(c, spec, progress=prog.progress), {"spec": spec.model_dump(), "label": lbl})
    elif kind == kinds[1]:
        p1, l1 = _param_input("Parameter x", "s2x", cat, "bypass.throttle.opening_percent")
        s1 = _range_inputs(p1, "s2x", 10)
        p2, l2 = _param_input("Parameter y", "s2y", cat, "pump.flow_rate_ml_min")
        s2 = _range_inputs(p2, "s2y", 10)
        if st.button(t("Run"), key=key("run2")):
            out = ("2d", sweep_grid(c, [s1, s2], progress=prog.progress), {"specs": [s1.model_dump(), s2.model_dump()], "labels": [l1, l2]})
    elif kind == kinds[2]:
        paths = st.multiselect("Parameters", list(cat), default=list(cat)[:3], format_func=lambda p: cat[p], key=key("lhs_p"))
        specs = [_range_inputs(p, f"lhs{i}", 2) for i, p in enumerate(paths)]
        n = int(st.number_input("samples", value=100, min_value=5, max_value=5000, key=key("lhs_n")))
        seed = int(st.number_input("random seed", value=1, key=key("lhs_seed")))
        if st.button(t("Run"), key=key("run3")) and specs:
            out = ("lhs", latin_hypercube_study(c, specs, n, seed, prog.progress), {"specs": [s.model_dump() for s in specs], "seed": seed})
    elif kind == kinds[3]:
        paths = st.multiselect("Parameters", list(cat), default=[p for p in cat if p.startswith("reactor_paths.0.")][:6] or list(cat)[:5],
                               format_func=lambda p: cat[p], key=key("ls_p"))
        step = st.number_input("relative step", value=0.01, min_value=1e-5, max_value=0.2, format="%.4f", key=key("ls_step"))
        if st.button(t("Run"), key=key("run4")) and paths:
            out = ("sens", local_sensitivity(c, paths, rel_step=step), {"paths": paths, "rel_step": step})
    elif kind == kinds[4]:
        st.caption("Define uncertain parameters with distributions. For '*' paths every element is sampled independently.")
        paths = st.multiselect("Uncertain parameters", list(cat), default=["reactor_paths.*.reactor.scaffold.permeability_m2"],
                               format_func=lambda p: cat[p], key=key("mc_p"))
        specs = []
        for i, p in enumerate(paths):
            c1, c2, c3 = st.columns(3)
            dist = c1.selectbox(f"{cat[p]}: distribution", ["normal", "uniform", "lognormal"], key=key("mcd", p))
            nom = float(get_param(c, p))
            sd = c2.number_input("std. deviation (or half-width for uniform)", value=abs(nom) * 0.1, format="%.4g", key=key("mcs", p))
            c3.caption(f"nominal: {nom:.4g}")
            specs.append(ParameterSpec(path=p, distribution=dist, std=sd if dist != "uniform" else None,
                                       tolerance=sd if dist == "uniform" else None))
        n = int(st.number_input("samples", value=200, min_value=10, max_value=10000, key=key("mc_n")))
        seed = int(st.number_input("random seed", value=42, key=key("mc_seed")))
        if st.button(t("Run"), key=key("run5")) and specs:
            df, summ = monte_carlo(c, specs, n, seed, prog.progress)
            out = ("mc", df, {"specs": [s.model_dump() for s in specs], "seed": seed, "n": n})
            st.session_state.study_summary = summ
    else:
        st.caption("Small deviations of the tube inner diameters (all three tubes of every reactor path, independent) and their "
                   "effect on the flow distribution between the bioreactors.")
        c1, c2, c3, c4 = st.columns(4)
        tol = c1.number_input("tolerance +/- [mm]", value=0.05, min_value=0.0, step=0.01, format="%.3f", key=key("tol"))
        dist = c2.selectbox("distribution", ["normal", "uniform"], key=key("tol_d"), help="normal: tolerance = 2 sigma")
        n = int(c3.number_input("samples", value=200, min_value=10, key=key("tol_n")))
        seed = int(c4.number_input("seed", value=42, key=key("tol_s")))
        feed = st.checkbox("include feed/return tubes", key=key("tol_feed"))
        if st.button(t("Run"), key=key("run6")):
            df, summ = tube_tolerance_study(c, tol, n, seed, dist, feed, prog.progress)
            out = ("mc", df, {"type": "tube tolerance", "tolerance_mm": tol, "distribution": dist, "seed": seed, "n": n})
            st.session_state.study_summary = summ
    if out is not None:
        st.session_state.study = out
    if "study" not in st.session_state:
        return
    typ, df, meta = st.session_state.study
    st.divider()
    st.subheader(t("Results"))
    outputs = [o for o in df.columns if o in OUTPUT_LABELS or o.startswith(("Q_reactor_", "share_reactor_", "p_reactor_", "dp_reactor_"))]
    if typ == "1d":
        x = meta["spec"]["path"]
        default = [o for o in outputs if o.startswith("Q_reactor_")] + (["Q_bypass_ml_min"] if "Q_bypass_ml_min" in outputs else [])
        ys = st.multiselect("Outputs (same unit recommended - no dual axes)", outputs, default=default or outputs[:1],
                            format_func=_output_label, key="s1_out")
        st.plotly_chart(plots.fig_sweep(df, x, ys, meta["label"], _output_label(ys[0]) if ys else "", f"Influence of {meta['label']}",
                                        logx=meta["spec"]["scale"] == "log", names=[_output_label(y) for y in ys]), width="stretch")
        y2 = st.selectbox("Second figure", outputs, outputs.index("pump_dp_pa") if "pump_dp_pa" in outputs else 0, format_func=_output_label, key="s1_out2")
        st.plotly_chart(plots.fig_sweep(df, x, [y2], meta["label"], _output_label(y2), f"{_output_label(y2)} vs. {meta['label']}",
                                        logx=meta["spec"]["scale"] == "log"), width="stretch")
    elif typ == "2d":
        x, y = meta["specs"][0]["path"], meta["specs"][1]["path"]
        z = st.selectbox("Output", outputs, outputs.index("cv_percent") if "cv_percent" in outputs else 0, format_func=_output_label, key="s2_z")
        c1, c2 = st.columns(2)
        c1.plotly_chart(plots.fig_heatmap(df, x, y, z, meta["labels"][0], meta["labels"][1], _output_label(z), "Heat map"), width="stretch")
        c2.plotly_chart(plots.fig_surface(df, x, y, z, meta["labels"][0], meta["labels"][1], _output_label(z), "3D parameter surface"),
                        width="stretch")
    elif typ == "lhs":
        z = st.selectbox("Output", outputs, format_func=_output_label, key="lhs_z")
        params = [s["path"] for s in meta["specs"]]
        corr = df[params + [z]].corr(method="spearman")[z].drop(z)
        st.dataframe(corr.rename("Spearman rank correlation with output"), width="stretch")
        xp = st.selectbox("Scatter vs.", params, key="lhs_x")
        import plotly.graph_objects as go

        fig = go.Figure(go.Scatter(x=df[xp], y=df[z], mode="markers", marker=dict(size=7, color=plots.SERIES[0])))
        st.plotly_chart(plots.style(fig, "Latin-hypercube samples", xp, _output_label(z), legend=False), width="stretch")
    elif typ == "sens":
        o = st.selectbox("Output", sorted(df.output.unique()), format_func=_output_label, key="sens_o")
        st.plotly_chart(plots.fig_tornado(df, o, cat), width="stretch")
        st.caption("Elasticity S = (dy/y)/(dx/x): S = -4 means +1 % parameter -> -4 % output (e.g. laminar dp vs. tube diameter).")
    elif typ == "mc":
        summ = st.session_state.get("study_summary")
        o = st.selectbox("Output", outputs, outputs.index("cv_percent") if "cv_percent" in outputs else 0, format_func=_output_label, key="mc_o")
        st.plotly_chart(plots.fig_histogram(df, o, _output_label(o), f"Distribution of {_output_label(o)} ({len(df)} samples)"), width="stretch")
        if summ is not None:
            st.dataframe(summ.loc[[x for x in outputs if x in summ.index]], width="stretch")
        st.caption("Statistics are sample estimates; percentiles 2.5/97.5 give an empirical 95 % range. Reproducible via the random seed.")
    with st.expander("Raw data"):
        st.dataframe(df, width="stretch")
    c1, c2 = st.columns(2)
    c1.download_button("CSV", df.to_csv(index=False).encode(), "parameter_study.csv", "text/csv", key="st_csv")
    if c2.button("Save study reproducibly (results/ folder)", key="st_save"):
        d = save_study(df, cfg(), {"type": typ, **meta}, ROOT / "results", f"study_{typ}")
        st.success(f"Saved to {d}")


def page_optimization() -> None:
    st.title(t("Optimization"))
    c = cfg()
    n = c.n_reactors
    obj = st.selectbox(t("Objective"), list(OBJECTIVE_LABELS), format_func=lambda o: OBJECTIVE_LABELS[o], key=key("o_obj"))
    prob = OptimizationProblem(objective=obj)
    st.markdown(f"**Targets & {t('Constraints')}** (leave 0 to disable)")
    if obj == "individual_targets" or st.checkbox("Specify target reactor flows", key=key("o_tgt_on")):
        cols = st.columns(n)
        prob.reactor_targets_ml_min = [cols[i].number_input(f"Reactor {i+1} target [mL/min]", value=1.0, min_value=0.0, key=key("o_t", i))
                                       for i in range(n)]
    c1, c2, c3, c4 = st.columns(4)

    def opt(col, label, k, default=0.0):
        v = col.number_input(label, value=default, min_value=0.0, format="%.4g", key=key("o", k))
        return v if v > 0 else None

    prob.total_flow_ml_min = opt(c1, "Total flow [mL/min]", "tot")
    prob.bypass_target_ml_min = opt(c2, "Bypass flow [mL/min]", "byp") if c.bypass.enabled else None
    prob.max_pump_pressure_pa = opt(c3, "Max. pump pressure [Pa]", "pmax")
    prob.max_reactor_pressure_pa = opt(c4, "Max. reactor pressure [Pa]", "rmax")
    c1, c2, c3, c4 = st.columns(4)
    prob.max_pressure_drop_pa = opt(c1, "Max. pressure drop [Pa]", "dpmax")
    prob.max_reactor_deviation_percent = opt(c2, "Max. deviation between reactors [%]", "dev")
    tubes = [e for e in ("pump_outlet_tube",) + tuple(f"tube_thr_rx{i+1}" for i in range(n))]
    seg = c3.selectbox("Wall shear target segment", ["-"] + tubes, key=key("o_seg"))
    tau = c4.number_input("Target wall shear [mPa]", value=0.0, min_value=0.0, key=key("o_tau"))
    if seg != "-" and tau > 0:
        prob.shear_targets_pa = {seg: tau / 1000}
    st.markdown(f"**{t('Decision variables')}**")
    variables = []
    min_open = st.slider("Minimum throttle opening [%] (constructive limit)", 0.5, 50.0, 5.0, key=key("o_minop"))
    for v in default_variables(c, include_pump=False, min_opening=min_open):
        if st.checkbox(v.label, True, key=key("o_var", v.path)):
            variables.append(v)
    pv = default_variables(c, include_pump=True)[-1]
    if st.checkbox(f"{pv.label} ({pv.low:.3g} ... {pv.high:.3g})", False, key=key("o_pump")):
        variables.append(pv)
    cat = parameter_catalog(c)
    geo = st.multiselect("Additional geometric variables (tube IDs/lengths, ...)",
                         [p for p in cat if ("inner_diameter" in p or "length_m" in p)], format_func=lambda p: cat[p], key=key("o_geo"))
    for p in geo:
        nom = float(get_param(c, p))
        c1, c2 = st.columns(2)
        lo = c1.number_input(f"{cat[p]} min", value=nom * 0.5, key=key("o_glo", p))
        hi = c2.number_input(f"{cat[p]} max", value=nom * 2.0, key=key("o_ghi", p))
        variables.append(DecisionVariable(path=p, low=lo, high=hi, label=cat[p]))
    prob.variables = variables
    if obj in ("robust_tolerances", "robust_scaffold"):
        c1, c2, c3 = st.columns(3)
        prob.n_robust_samples = int(c1.number_input("Monte-Carlo samples per evaluation", value=12, min_value=4, key=key("o_rs")))
        prob.tube_tolerance_mm = c2.number_input("Tube ID tolerance (2 sigma) [mm]", value=0.05, key=key("o_rt"))
        prob.permeability_cv = c3.number_input("Permeability CV [-]", value=0.3, key=key("o_rp"))
        st.caption("Robust objectives are expensive (samples x evaluations); use few iterations first.")
    c1, c2, c3 = st.columns(3)
    prob.method = c1.selectbox("Method", ["local", "global"], key=key("o_m"),
                               format_func=lambda m: {"local": "local (Powell, multi-start)", "global": "global (differential evolution)"}[m])
    prob.max_iterations = int(c2.number_input("Max. iterations", value=40, min_value=1, key=key("o_it")))
    prob.seed = int(c3.number_input("Seed", value=7, key=key("o_seed")))
    if st.button(t("Run"), type="primary", key=key("o_run")):
        if not variables:
            st.error("Select at least one decision variable.")
        else:
            bar = st.progress(0.0)
            try:
                with st.spinner("Optimising ..."):
                    res, cfg_opt = optimize_system(c, prob, progress=bar.progress)
                st.session_state.opt = (res, cfg_opt, prob)
            except Exception as exc:
                st.error(str(exc))
    if "opt" not in st.session_state:
        return
    res, cfg_opt, prob = st.session_state.opt
    st.divider()
    if res.feasible:
        st.success(f"Feasible solution found ({res.method}, {res.n_evaluations} evaluations, {res.runtime_s:.1f} s).")
    else:
        st.error("No feasible solution found. Reasons:")
        for e in res.explanations:
            st.write("- " + e)
    st.dataframe(result_table(res, prob), hide_index=True, width="stretch")
    st.markdown("**Quality metrics**")
    st.dataframe(pd.DataFrame([res.metrics]), hide_index=True, width="stretch")
    if res.constraints:
        st.dataframe(pd.DataFrame(res.constraints), hide_index=True, width="stretch")
    from core.simulation import run_simulation

    r_opt = run_simulation(cfg_opt)
    c1, c2 = st.columns(2)
    c1.plotly_chart(plots.fig_reactor_flows(r_opt, prob.reactor_targets_ml_min), width="stretch")
    c2.plotly_chart(plots.fig_opt_history(res.history), width="stretch")
    if st.button(t("Apply optimised settings"), key="o_apply"):
        set_config(cfg_opt, note=f"applied optimisation ({prob.objective})")
        st.success("Optimised settings applied to the current configuration.")


def page_validation() -> None:
    st.title(t("Experimental Validation"))
    c = cfg()
    with st.expander(t("Templates") + " for experimental series", expanded=False):
        buf = io.BytesIO()
        tmp = ROOT / "experimental_data" / "templates"
        with zipfile.ZipFile(buf, "w") as z:
            for name, tpl in TEMPLATES.items():
                content = f"# {tpl['description']}\n" + ",".join(tpl["columns"]) + "\n"
                z.writestr(f"{name}.csv", content)
        st.download_button("Download all templates (ZIP)", buf.getvalue(), "experimental_templates.zip", key="tpl_zip")
        st.dataframe(pd.DataFrame([{"template": k, "description": v["description"], "columns": ", ".join(v["columns"])} for k, v in TEMPLATES.items()]),
                     hide_index=True, width="stretch")
        st.caption(f"Templates are also stored in {tmp}. Column 'dataset' = calibration | validation; u_<column> = standard uncertainty. "
                   "Pressures as gauge pressure in Pa at the network node named in the column (p_<node>_pa).")
    up = st.file_uploader(t("Upload experimental data (CSV/Excel)"), type=["csv", "xlsx", "xls"], key="exp_up")
    if up is None:
        st.info("No data loaded. A synthetic demonstration data set can be generated from the current model (clearly labelled synthetic).")
        if st.button("Generate SYNTHETIC demo data (model + 3 % noise)", key="synth"):
            from core.sensitivity import evaluate
            from core.validation import apply_inputs

            rng = np.random.default_rng(0)
            rows = []
            for i, q in enumerate(np.linspace(2, 8, 8)):
                row = {"point_id": i, "dataset": "calibration" if i % 2 == 0 else "validation", "pump_flow_ml_min": q, "notes": "SYNTHETIC"}
                o, _ = evaluate(apply_inputs(c, pd.Series(row)))
                for k in range(1, c.n_reactors + 1):
                    row[f"Q_reactor_{k}_ml_min"] = o[f"Q_reactor_{k}_ml_min"] * (1 + 0.03 * rng.standard_normal())
                    row[f"u_Q_reactor_{k}_ml_min"] = 0.03 * o[f"Q_reactor_{k}_ml_min"]
                row["pump_dp_pa"] = o["pump_dp_pa"] * 1.15 * (1 + 0.02 * rng.standard_normal())
                row["u_pump_dp_pa"] = 0.02 * o["pump_dp_pa"]
                rows.append(row)
            st.session_state.exp_df = pd.DataFrame(rows)
    else:
        try:
            st.session_state.exp_df = load_experimental_data(up.getvalue(), up.name)
        except Exception as exc:
            st.error(f"Import failed: {exc}")
    if "exp_df" not in st.session_state:
        return
    df = st.session_state.exp_df
    st.dataframe(df, width="stretch", height=220)
    subset = st.radio("Compare on", ["all rows", "calibration rows", "validation rows"], horizontal=True, key="exp_subset")
    d = df
    if subset != "all rows" and "dataset" in df:
        d = df[df["dataset"].astype(str).str.lower() == subset.split()[0]]
    sim, metrics = compare(c, d)
    st.session_state.exp_result = (sim, metrics)
    st.markdown("**Comparison metrics** (deviation = simulation - experiment)")
    st.dataframe(metrics, hide_index=True, width="stretch")
    st.caption("95 % CI of the bias assumes independent, normally distributed deviations (Student t). R^2 only for n >= 3. "
               "fraction_within_2u: share of points whose deviation is within the expanded measurement uncertainty (k = 2).")
    if not metrics.empty:
        q = st.selectbox("Quantity", list(metrics.quantity), key="exp_q")
        st.plotly_chart(plots.fig_parity(sim, q, q), width="stretch")
    with st.expander("Per-point results"):
        st.dataframe(sim, width="stretch")
    st.subheader(t("Calibration"))
    st.caption("Least-squares fit on the rows with dataset = calibration; evaluate afterwards on the validation rows (strict separation).")
    cat = parameter_catalog(c)
    cal_opts = {"reactor_paths.*.throttle.calibration_factor": "All reactor throttles: calibration factor [-]",
                "splitter_in.branch_ports.0.K": "Splitter 1 port K (symmetric) [-]",
                "reactor_paths.*.reactor.scaffold.permeability_m2": "All scaffolds: permeability [m^2]",
                "fluid.viscosity_ratio": "Medium viscosity ratio [-]",
                "pump.volumetric_efficiency": "Pump volumetric efficiency [-]", **cat}
    sel = st.multiselect("Parameters to calibrate", list(cal_opts), default=["fluid.viscosity_ratio"], format_func=lambda p: cal_opts[p], key="cal_p")
    params = []
    for p in sel:
        try:
            nom = float(get_param(c, p) or 1.0)
        except Exception:
            nom = 1.0
        c1, c2, c3 = st.columns(3)
        lo = c1.number_input(f"{cal_opts[p]} min", value=nom / 10, format="%.4g", key=f"cal_lo_{p}")
        hi = c2.number_input(f"{cal_opts[p]} max", value=nom * 10, format="%.4g", key=f"cal_hi_{p}")
        lg = c3.checkbox("log-scale", True, key=f"cal_log_{p}")
        params.append(CalibrationParameter(path=p, low=lo, high=hi, log_scale=lg))
    if st.button("Run calibration", key="cal_run") and params:
        try:
            if "fluid.viscosity_ratio" in sel and c.fluid.viscosity_ratio is None:
                c.fluid.viscosity_ratio = 1.0 if c.fluid.fluid_type == "water" else 1.05
            with st.spinner("Calibrating ..."):
                cal_cfg, info = calibrate(c, df, params)
            st.session_state.cal = (cal_cfg, info)
        except Exception as exc:
            st.error(str(exc))
    if "cal" in st.session_state:
        cal_cfg, info = st.session_state.cal
        st.json(info)
        if "dataset" in df:
            val = df[df["dataset"].astype(str).str.lower() == "validation"]
            if not val.empty:
                _, m = compare(cal_cfg, val)
                st.markdown("**Calibrated model on VALIDATION rows**")
                st.dataframe(m, hide_index=True, width="stretch")
        if st.button("Apply calibrated parameters to configuration", key="cal_apply"):
            set_config(cal_cfg, note="applied experimental calibration")
            st.success("Applied. Results based on these parameters are 'experimentally calibrated' - validation requires independent data.")
