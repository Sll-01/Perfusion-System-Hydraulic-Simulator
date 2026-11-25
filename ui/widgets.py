"""Reusable parameter editors (they modify the configuration objects in place)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from core.bioreactors import Bioreactor
from core.bypass import TeePiece
from core.constrictions import Constriction
from core.pumps import PumpConfig
from core.splitters import Splitter, SplitterPort
from core.throttles import Throttle
from core.tubing import MATERIAL_ROUGHNESS_M, AreaChange, Bend, Fitting, Tube

from .i18n import t
from .state import key


def num(obj, field: str, label: str, k: str, unit: str = "", min_value=None, max_value=None, step=None, fmt=None,
        factor: float = 1.0, help: str | None = None, container=st) -> float:
    """number_input bound to obj.field; ``factor`` converts config units -> display units."""
    val = getattr(obj, field)
    if val is None:
        val = 0.0
    shown = container.number_input(f"{label} [{unit}]" if unit else label, value=float(val) * factor,
                                   min_value=None if min_value is None else float(min_value),
                                   max_value=None if max_value is None else float(max_value),
                                   step=step, format=fmt, key=key(k, field), help=help)
    setattr(obj, field, shown / factor)
    return shown


def stable_editor(df: pd.DataFrame, k: str, **kw) -> pd.DataFrame:
    """data_editor whose *input* frame stays fixed for a widget key (edits are kept by
    Streamlit as a delta against this frame, so the input must not change)."""
    base_key = "base:" + key(k)
    if base_key not in st.session_state:
        st.session_state[base_key] = df
    return st.data_editor(st.session_state[base_key], key=key(k), **kw)


def _table_editor(items: list, model_cls, k: str, columns: list[str]):
    df = pd.DataFrame([{c: getattr(i, c) for c in columns} for i in items], columns=columns)
    edited = stable_editor(df, k, num_rows="dynamic", width="stretch")
    out = []
    for _, r in edited.iterrows():
        data = {c: r[c] for c in columns if pd.notna(r[c])}
        try:
            out.append(model_cls(**data))
        except Exception as exc:
            st.warning(f"Invalid row ignored: {exc}")
    return out


def tube_editor(tube: Tube, k: str, compact: bool = False) -> None:
    c1, c2, c3 = st.columns(3)
    tube.name = c1.text_input(t("Name"), tube.name, key=key(k, "name"))
    num(tube, "length_m", t("Length"), k, "m", 0.0, None, 0.01, "%.4f", container=c2)
    num(tube, "inner_diameter_mm", t("Inner diameter"), k, "mm", 0.01, None, 0.05, "%.4f", container=c3)
    c1, c2, c3 = st.columns(3)
    od = c1.number_input(f"{t('Outer diameter')} [mm]", value=float(tube.outer_diameter_mm or 0.0), step=0.1, format="%.3f",
                         key=key(k, "od"), help="0 = not specified")
    tube.outer_diameter_mm = od if od > 0 else None
    wt = tube.wall_thickness()
    c2.metric(f"{t('Wall thickness')} [mm]", f"{wt:.3f}" if wt is not None else "-")
    mats = list(MATERIAL_ROUGHNESS_M)
    tube.material = c3.selectbox(t("Material"), mats, index=mats.index(tube.material) if tube.material in mats else len(mats) - 1,
                                 key=key(k, "mat"))
    c1, c2, c3 = st.columns(3)
    r = c1.number_input(f"{t('Roughness')} [um]", value=float(tube.roughness_um if tube.roughness_um is not None else tube.roughness_m() * 1e6),
                        step=0.5, format="%.2f", key=key(k, "rough"), help="Typical material value (ASSUMPTION); only relevant for turbulent flow")
    tube.roughness_um = r
    num(tube, "elevation_change_mm", t("Height difference"), k, "mm", step=10.0, fmt="%.1f", help="z_out - z_in", container=c2)
    num(tube, "extra_K", t("Additional K"), k, "-", 0.0, step=0.1, fmt="%.3f", container=c3)
    if compact:
        return
    with st.expander(f"{t('Bends')} / {t('Fittings / connectors')} / {t('Area changes')}"):
        st.caption("Bends: K per bend. Fittings: constant K, or 2-K method if K1 > 0. Area change: sudden change at segment outlet.")
        tube.bends = _table_editor(tube.bends, Bend, f"{k}:bends", ["count", "angle_deg", "bend_radius_mm", "K"])
        tube.fittings = _table_editor(tube.fittings, Fitting, f"{k}:fit", ["name", "count", "K", "K1", "volume_ul"])
        tube.area_changes = _table_editor(tube.area_changes, AreaChange, f"{k}:ac", ["kind", "connected_diameter_mm", "K_override"])
    with st.expander(f"{t('Constrictions')} ({len(tube.constrictions)})"):
        constriction_editor(tube, k)


def constriction_editor(tube: Tube, k: str) -> None:
    st.caption("Diameter reduction and area reduction are different quantities: 50 % diameter reduction = 75 % area reduction "
               "(laminar resistance of the constricted length x16). 'kink' and 'partial_compression' are simplified, calibratable "
               "substitute models.")
    if st.button("+ add constriction", key=key(k, "addc")):
        tube.constrictions.append(Constriction(name=f"constriction {len(tube.constrictions)+1}", position_mm=min(100.0, tube.length_m * 500)))
        st.rerun()
    for j, c in enumerate(list(tube.constrictions)):
        kk = f"{k}:c{j}"
        st.markdown(f"**{c.name}**")
        c1, c2, c3, c4 = st.columns(4)
        modes = ["open", "partial_compression", "local", "continuous", "kink", "blocked"]
        c.mode = c1.selectbox("Mode", modes, modes.index(c.mode), key=key(kk, "mode"))
        specs = ["diameter_reduction", "area_reduction", "effective_diameter", "effective_area"]
        c.specification = c2.selectbox("Specification", specs, specs.index(c.specification), key=key(kk, "spec"))
        if c.specification in ("diameter_reduction", "area_reduction"):
            c.degree_percent = c3.slider("Degree [%]", 0.0, 100.0, float(c.degree_percent), 0.5, key=key(kk, "deg"))
        elif c.specification == "effective_diameter":
            c.effective_diameter_mm = c3.number_input("Remaining diameter [mm]", value=float(c.effective_diameter_mm or tube.inner_diameter_mm / 2),
                                                      min_value=0.0, step=0.05, key=key(kk, "ed"))
        else:
            c.effective_area_mm2 = c3.number_input("Remaining area [mm^2]", value=float(c.effective_area_mm2 or tube.area * 1e6 / 2),
                                                   min_value=0.0, step=0.05, key=key(kk, "ea"))
        geos = ["circular", "elliptical"]
        c.geometry = c4.selectbox("Geometry", geos, geos.index(c.geometry), key=key(kk, "geo"),
                                  help="elliptical = squeezed tube with conserved perimeter (simplified substitute model)")
        c1, c2, c3, c4 = st.columns(4)
        num(c, "length_mm", "Length", kk, "mm", 0.0, step=1.0, container=c1)
        num(c, "position_mm", "Position from inlet", kk, "mm", 0.0, step=5.0, container=c2)
        num(c, "extra_K", "Additional K", kk, "-", 0.0, step=0.1, container=c3)
        if c.mode == "kink":
            num(c, "kink_K", "Kink K (calibrate!)", kk, "-", 0.0, step=0.5, container=c4)
        elif c.mode == "continuous":
            c.taper = c4.selectbox("Taper", ["uniform", "linear"], ["uniform", "linear"].index(c.taper), key=key(kk, "tap"))
        frac = c.remaining_area_fraction(tube.d) if not c.is_blocked() else 0.0
        st.caption(f"Remaining area {100*frac:.1f} %, equivalent diameter {tube.inner_diameter_mm * frac**0.5:.3f} mm"
                   + (" - BLOCKED (path closed)" if c.is_blocked() else ""))
        if st.button(f"remove {c.name}", key=key(kk, "rm")):
            tube.constrictions.pop(j)
            st.rerun()


def throttle_editor(th: Throttle, k: str, show_opening: bool = True) -> None:
    c1, c2, c3 = st.columns(3)
    if not show_opening:
        c1.metric(f"{t('Opening')} [%]", f"{th.opening_percent:.1f}")
    else:
        th.opening_percent = c1.slider(f"{t('Opening')} [%]", 0.0, 100.0, float(th.opening_percent), 0.5, key=key(k, "op"))
    models = ["resistance", "orifice_diameter", "orifice_area", "k_value", "kv", "dp_curve"]
    th.model = c2.selectbox(t("Model"), models, models.index(th.model), key=key(k, "model"))
    chars = ["linear", "equal_percentage", "quick_opening", "table"]
    th.characteristic = c3.selectbox(t("Characteristic"), chars, chars.index(th.characteristic), key=key(k, "char"),
                                     help="Maps opening to relative flow capacity (area, Kv or 1/R). Opening != flow fraction!")
    c1, c2, c3, c4 = st.columns(4)
    if th.model == "resistance":
        num(th, "resistance_open", "R at 100 %", k, "Pa s/m^3", 0.0, fmt="%.3e", container=c1)
    elif th.model == "orifice_diameter":
        num(th, "max_diameter_mm", "Eff. diameter at 100 %", k, "mm", 0.001, step=0.05, fmt="%.3f", container=c1)
    elif th.model == "orifice_area":
        th.max_area_mm2 = c1.number_input("Eff. area at 100 % [mm^2]", value=float(th.max_area_mm2 or th.max_area() * 1e6),
                                          min_value=1e-6, format="%.4f", key=key(k, "amax"))
    elif th.model == "k_value":
        num(th, "K_open", "K at 100 %", k, "-", 0.0, step=0.1, container=c1)
        num(th, "reference_diameter_mm", "Reference diameter", k, "mm", 0.01, step=0.1, container=c2)
    elif th.model == "kv":
        th.kv_max = c1.number_input("Kv at 100 % [m^3/h]", value=float(th.kv_max or 0.01), min_value=1e-9, format="%.5f", key=key(k, "kv"))
        c2.caption(f"Cv = {th.kv_max / 0.865:.5f}")
    if th.model in ("orifice_diameter", "orifice_area"):
        num(th, "discharge_coefficient", "Discharge coeff. Cd", k, "-", 0.01, 1.0, 0.05, container=c2)
        num(th, "throttle_length_mm", "Viscous gap length", k, "mm", 0.0, step=0.5, container=c3)
    num(th, "calibration_factor", "Calibration factor", k, "-", 1e-6, step=0.1, fmt="%.4f", container=c4)
    if th.characteristic == "equal_percentage":
        num(th, "rangeability", "Rangeability", k, "-", 1.01, step=5.0)
    if th.characteristic == "table":
        st.caption("Experimental opening characteristic: opening [%] -> relative capacity [0..1]")
        df = pd.DataFrame(th.opening_table, columns=["opening_percent", "relative_capacity"])
        ed = stable_editor(df, f"{k}:otab", num_rows="dynamic")
        th.opening_table = [(float(a), float(b)) for a, b in ed.dropna().to_numpy()]
    if th.model == "dp_curve":
        st.caption("Experimental pressure-drop curves: fitted dp = a Q + b Q^2 per opening, interpolated linearly in opening.")
        df = pd.DataFrame(th.dp_curve_points or [(100.0, 1.0, 10.0)], columns=["opening_percent", "Q_ml_min", "dp_pa"])
        ed = stable_editor(df, f"{k}:dpc", num_rows="dynamic")
        th.dp_curve_points = [tuple(map(float, r)) for r in ed.dropna().to_numpy()]
    th.provenance = st.text_input("Provenance / note", th.provenance, key=key(k, "prov"))


def reactor_editor(r: Bioreactor, k: str) -> None:
    states = ["empty", "no_scaffold", "with_scaffold", "reduced_permeability", "partially_blocked", "blocked"]
    c1, c2, c3 = st.columns(3)
    r.name = c1.text_input(t("Name"), r.name, key=key(k, "name"))
    r.state = c2.selectbox(t("State"), states, states.index(r.state), key=key(k, "state"))
    if r.state == "reduced_permeability":
        num(r, "permeability_factor", "Permeability factor k/k0", k, "-", 1e-6, 1.0, 0.05, "%.4f", container=c3)
    elif r.state == "partially_blocked":
        num(r, "blocked_fraction", "Blocked area fraction", k, "-", 0.0, 0.999, 0.05, container=c3)
    elif r.state == "no_scaffold":
        num(r, "holder_K", "Scaffold holder K", k, "-", 0.0, step=0.1, container=c3)
    st.markdown("**Chamber & channels**")
    c1, c2, c3, c4 = st.columns(4)
    num(r, "chamber_diameter_mm", "Chamber diameter", k, "mm", 0.01, step=0.5, container=c1)
    num(r, "chamber_height_mm", "Chamber height", k, "mm", 0.01, step=0.5, container=c2)
    cv = c3.number_input("Chamber volume [mL] (0 = from geometry)", value=float(r.chamber_volume_ml or 0.0), min_value=0.0,
                         format="%.4f", key=key(k, "cvol"))
    r.chamber_volume_ml = cv if cv > 0 else None
    c4.metric("Chamber volume used [mL]", f"{r.chamber_volume()*1e6:.4f}")
    c1, c2, c3, c4 = st.columns(4)
    num(r, "inlet_diameter_mm", "Inlet diameter", k, "mm", 0.01, step=0.1, container=c1)
    num(r, "outlet_diameter_mm", "Outlet diameter", k, "mm", 0.01, step=0.1, container=c2)
    num(r, "inlet_channel_length_mm", "Inlet channel length", k, "mm", 0.0, step=0.5, container=c3)
    num(r, "outlet_channel_length_mm", "Outlet channel length", k, "mm", 0.0, step=0.5, container=c4)
    c1, c2, c3, c4 = st.columns(4)
    num(r, "internal_resistance", "Internal resistance", k, "Pa s/m^3", 0.0, fmt="%.3e", container=c1)
    num(r, "extra_K", "Additional K", k, "-", 0.0, step=0.1, container=c2)
    ik = c3.number_input("Inlet K (-1 = Borda-Carnot)", value=float(r.inlet_K if r.inlet_K is not None else -1), key=key(k, "ik"))
    r.inlet_K = None if ik < 0 else ik
    ok = c4.number_input("Outlet K (-1 = contraction estimate)", value=float(r.outlet_K if r.outlet_K is not None else -1), key=key(k, "okk"))
    r.outlet_K = None if ok < 0 else ok
    num(r, "elevation_change_mm", t("Height difference"), k, "mm", step=5.0)
    st.markdown(f"**{t('Scaffold')}**")
    s = r.scaffold
    c1, c2, c3, c4 = st.columns(4)
    num(s, "diameter_mm", "Scaffold diameter", f"{k}:s", "mm", 0.01, step=0.5, container=c1)
    num(s, "height_mm", "Scaffold height", f"{k}:s", "mm", 0.01, step=0.5, container=c2)
    num(s, "porosity", t("Porosity"), f"{k}:s", "-", 0.01, 0.999, 0.01, container=c3)
    num(s, "permeability_m2", t("Permeability"), f"{k}:s", "m^2", 1e-20, fmt="%.3e", container=c4)
    c1, c2, c3, c4 = st.columns(4)
    ao = c1.number_input("Scaffold area override [mm^2] (0 = from diameter)", value=float(s.area_override_mm2 or 0.0), min_value=0.0, key=key(k, "sao"))
    s.area_override_mm2 = ao if ao > 0 else None
    s.use_forchheimer = c2.checkbox("Darcy-Forchheimer", s.use_forchheimer, key=key(k, "forch"))
    if s.use_forchheimer:
        num(s, "forchheimer_cf", "Forchheimer C_F (ASSUMPTION)", f"{k}:s", "-", 0.0, step=0.05, container=c3)
    exp = c4.number_input("Experimental total R [Pa s/m^3] (0 = model)", value=float(r.experimental_resistance or 0.0), min_value=0.0,
                          format="%.3e", key=key(k, "exr"))
    r.experimental_resistance = exp if exp > 0 else None
    r.provenance = st.text_input("Provenance / note", r.provenance, key=key(k, "prov"))


def port_editor_table(ports: list[SplitterPort], k: str) -> list[SplitterPort]:
    cols = ["name", "port_diameter_mm", "channel_diameter_mm", "channel_length_mm", "K", "resistance", "angle_deg"]
    df = pd.DataFrame([{c: getattr(p, c) for c in cols} for p in ports], columns=cols)
    ed = stable_editor(df, k, width="stretch", num_rows="fixed")
    return [SplitterPort(**{c: r[c] for c in cols}) for _, r in ed.iterrows()]


def splitter_editor(sp: Splitter, n_ports: int, k: str) -> None:
    c1, c2, c3 = st.columns(3)
    sp.name = c1.text_input(t("Name"), sp.name, key=key(k, "name"))
    modes = ["symmetric", "asymmetric", "ideal", "individual_resistances"]
    sp.mode = c2.selectbox("Mode", modes, modes.index(sp.mode), key=key(k, "mode"))
    sp.geometry = c3.text_input("Geometry description", sp.geometry, key=key(k, "geo"))
    num(sp, "hub_volume_ul", "Hub internal volume", k, "uL", 0.0, step=5.0)
    sp.ensure_ports(n_ports)
    st.caption("Common port (inlet of distributor / outlet of collector):")
    sp.common_port = port_editor_table([sp.common_port], f"{k}:common")[0]
    st.caption("Branch ports" + (" (symmetric mode: only the first row is used)" if sp.mode == "symmetric" else "")
               + (" (ideal: all losses = 0)" if sp.mode == "ideal" else "")
               + (" (only column 'resistance' is used)" if sp.mode == "individual_resistances" else ""))
    sp.branch_ports = port_editor_table(sp.branch_ports[:n_ports], f"{k}:branch") + sp.branch_ports[n_ports:]


def tee_editor(tee: TeePiece, k: str) -> None:
    c1, c2, c3, c4 = st.columns(4)
    num(tee, "inner_diameter_mm", "T-piece ID", k, "mm", 0.01, step=0.1, container=c1)
    num(tee, "K_run", "K run", k, "-", 0.0, step=0.1, container=c2)
    num(tee, "K_branch", "K branch", k, "-", 0.0, step=0.1, container=c3)
    num(tee, "volume_ul", "Volume", k, "uL", 0.0, step=1.0, container=c4)


def pump_quick_editor(p: PumpConfig, k: str) -> None:
    from core.pumps import PUMP_MODE_LABELS

    modes = list(PUMP_MODE_LABELS)
    p.mode = st.selectbox(t("Pump mode"), modes, modes.index(p.mode), format_func=lambda m: PUMP_MODE_LABELS[m], key=key(k, "mode"))
    if p.mode == "A_constant_flow":
        num(p, "flow_rate_ml_min", t("Flow rate"), k, "mL/min", 0.0, step=0.1, fmt="%.4f")
    elif p.mode == "B_constant_pressure":
        num(p, "pressure_difference_pa", t("Pressure difference"), k, "mbar", step=1.0, fmt="%.3f", factor=0.01)
    else:
        num(p, "speed_rpm", t("Speed"), k, "rpm", 0.0, step=1.0)
