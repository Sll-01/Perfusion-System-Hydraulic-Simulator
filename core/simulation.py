"""High-level steady-state simulation of a configured perfusion system.

``run_simulation(cfg)`` builds the network, solves it and post-processes all requested
quantities (per segment, per reactor, pump, bypass, distribution metrics, volumes,
warnings, convergence information). Everything is returned in SI units; conversion to
lab units happens in the UI / export layer.
"""
from __future__ import annotations

import datetime as _dt
import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import SOFTWARE_VERSION
from .fluids import FluidState, evaluate_fluid
from .network import HydraulicNetwork
from .solver import SolverResult, solve_network
from .system import PerfusionSystemConfig, build_network, internal_volume_breakdown
from .units import ML_MIN

DEGASSING_WARNING_PA = -20_000.0  # gauge; ASSUMED indicative threshold for degassing risk


REACTOR_COLUMNS = ["reactor", "edge", "group", "state", "Q_m3s", "Q_ml_min", "share_percent", "p_in_pa", "p_out_pa", "dp_pa",
                   "dp_scaffold_pa", "chamber_velocity_m_s", "superficial_velocity_m_s", "pore_velocity_estimate_m_s",
                   "Re_permeability", "shear_stress_estimate_pa", "R_secant", "residence_time_s", "volume_ml", "quantity_type"]


@dataclass
class Warning_:
    level: str  # info | warning | error
    message: str
    source: str = ""


@dataclass
class SimulationResult:
    config: PerfusionSystemConfig
    network: HydraulicNetwork
    fluid: FluidState
    solver: SolverResult
    edges: pd.DataFrame
    nodes: pd.DataFrame
    reactors: pd.DataFrame
    pump: dict
    bypass: dict
    distribution: dict
    volumes: dict
    warnings: list[Warning_] = field(default_factory=list)
    timestamp: str = ""
    software_version: str = SOFTWARE_VERSION

    @property
    def ok(self) -> bool:
        return self.solver.converged

    # --- convenient accessors (SI) ---------------------------------------------
    @property
    def q_total(self) -> float:
        return self.pump.get("Q", math.nan)

    def reactor_flows(self) -> np.ndarray:
        return self.reactors["Q_m3s"].to_numpy() if not self.reactors.empty else np.array([])

    def path_flow(self, group: str) -> float:
        """Flow through a parallel path (= flow of its first edge)."""
        sub = [e for e in self.network.edges.values() if e.group == group]
        if not sub:
            return 0.0
        return self.solver.edge_flows[sub[0].id]

    def summary(self) -> dict:
        d = {
            "converged": self.ok,
            "Q_total_ml_min": self.q_total / ML_MIN,
            "pump_dp_pa": self.pump.get("dp", math.nan),
            "hydraulic_power_w": self.pump.get("P_hyd", math.nan),
            "bypass_ml_min": self.bypass.get("Q", 0.0) / ML_MIN,
            "bypass_fraction": self.bypass.get("fraction", 0.0),
            "cv_reactors": self.distribution.get("cv", math.nan),
            "max_rel_dev": self.distribution.get("max_rel_dev", math.nan),
            "system_volume_ml": self.volumes.get("circuit_total", math.nan) * 1e6,
        }
        for i, q in enumerate(self.reactor_flows()):
            d[f"Q_reactor_{i+1}_ml_min"] = q / ML_MIN
        return d

    def to_dict(self) -> dict:
        return {
            "software_version": self.software_version,
            "timestamp": self.timestamp,
            "summary": self.summary(),
            "pump": {k: v for k, v in self.pump.items() if not isinstance(v, (list, dict))},
            "bypass": self.bypass,
            "distribution": self.distribution,
            "volumes_m3": self.volumes,
            "convergence": convergence_info(self.solver),
            "warnings": [w.__dict__ for w in self.warnings],
            "edges": self.edges.replace({np.inf: None, -np.inf: None}).astype(object).where(self.edges.notna(), None).to_dict(orient="records"),
            "nodes": self.nodes.astype(object).where(self.nodes.notna(), None).to_dict(orient="records"),
            "reactors": self.reactors.replace({np.inf: None}).astype(object).where(self.reactors.notna(), None).to_dict(orient="records"),
            "fluid": {"name": self.fluid.name, "T_c": self.fluid.temperature_c, "rho": self.fluid.density,
                      "mu": self.fluid.dynamic_viscosity, "nu": self.fluid.kinematic_viscosity,
                      "provenance": self.fluid.provenance},
        }


def convergence_info(s: SolverResult) -> dict:
    return {
        "converged": s.converged,
        "method": s.method,
        "iterations": s.iterations,
        "max_mass_residual_m3s": s.max_mass_residual,
        "max_pressure_residual_pa": s.max_pressure_residual,
        "condition_number": s.condition_number,
        "flow_scale_m3s": s.q_scale,
        "pressure_scale_pa": s.p_scale,
        "messages": s.messages,
        "errors": s.errors,
    }


def distribution_metrics(q: np.ndarray, targets: np.ndarray | None = None) -> dict:
    """Quality metrics of the flow distribution between reactors (spec. 16)."""
    q = np.asarray(q, dtype=float)
    if q.size == 0:
        return {}
    mean = float(np.mean(q))
    std = float(np.std(q, ddof=0))
    d = {
        "mean": mean,
        "std": std,
        "cv": std / mean if mean > 0 else math.nan,
        "max_rel_dev": float(np.max(np.abs(q - mean)) / mean) if mean > 0 else math.nan,
        "min": float(np.min(q)),
        "max": float(np.max(q)),
        "min_max_ratio": float(np.min(q) / np.max(q)) if np.max(q) > 0 else math.nan,
        "uniformity_index": 1.0 - (std / mean if mean > 0 else math.nan),
    }
    if targets is not None:
        t = np.asarray(targets, dtype=float)
        d["rmse_vs_target"] = float(np.sqrt(np.mean((q - t) ** 2)))
        d["max_rel_dev_vs_target"] = float(np.max(np.abs(q - t) / np.where(t > 0, t, np.nan)))
    return d


def run_simulation(cfg: PerfusionSystemConfig, initial: SolverResult | None = None) -> SimulationResult:
    fluid = evaluate_fluid(cfg.fluid)
    net = build_network(cfg)
    st = cfg.solver.model_copy()
    if st.flow_scale_m3s is None:
        kind, a, _ = cfg.pump.linear_guess()
        st.flow_scale_m3s = a if (kind == "flow" and a > 0) else 1e-7
    sol = solve_network(net, fluid, st, initial=initial)
    fs = st.friction()
    warnings: list[Warning_] = [Warning_("warning", w, "fluid") for w in fluid.warnings]

    # ---------- edges --------------------------------------------------------
    rows = []
    for e in net.edges.values():
        Q = sol.edge_flows.get(e.id, 0.0)
        pa, pb = sol.node_pressures.get(e.from_node, math.nan), sol.node_pressures.get(e.to_node, math.nan)
        row = {
            "id": e.id, "label": e.label, "kind": e.kind, "group": e.group, "from": e.from_node, "to": e.to_node,
            "Q_m3s": Q, "Q_ml_min": Q / ML_MIN, "p_in_pa": pa, "p_out_pa": pb, "dp_pa": pa - pb,
            "closed": e.is_closed(), "config_path": e.config_path,
        }
        if e.is_pump:
            row.update({"dp_pa": pb - pa, "quantity_type": "numerical"})
        else:
            try:
                det = e.element.details(Q, fluid, fs) if not e.is_closed() else e.element.details(0.0, fluid, fs)
            except Exception as exc:  # pragma: no cover - defensive
                det = {}
                warnings.append(Warning_("warning", f"Detail evaluation failed for {e.id}: {exc}", e.id))
            row.update({
                "v_m_s": det.get("v", math.nan),
                "Re": det.get("Re", math.nan),
                "regime": det.get("regime", ""),
                "dp_loss_pa": det.get("dp_total", math.nan),
                "dp_hydrostatic_pa": e.element.hydrostatic(fluid),
                "R_secant": det.get("R_secant", math.inf if e.is_closed() else math.nan),
                "wall_shear_pa": det.get("wall_shear_stress", math.nan),
                "volume_m3": e.element.volume_m3(),
                "residence_time_s": (e.element.volume_m3() / abs(Q)) if abs(Q) > 0 else math.inf,
                "inner_diameter_mm": getattr(e.element, "inner_diameter_mm", math.nan),
                "opening_percent": getattr(e.element, "opening_percent", math.nan) if e.kind == "throttle" else math.nan,
                "friction_method": det.get("friction_method", ""),
                "quantity_type": e.element.quantity_type() if hasattr(e.element, "quantity_type") else "",
            })
            if e.kind == "tube":
                warnings += [Warning_("warning", w, e.id) for w in e.element.geometry_warnings()]
            if e.kind == "throttle":
                warnings += [Warning_("info", w, e.id) for w in e.element.model_warnings(Q, fluid)]
            if e.kind == "reactor" and sol.converged:
                warnings += [Warning_("warning", w, e.id) for w in e.element.model_warnings(Q, fluid)]
            Re = row["Re"]
            if not row["regime"] and isinstance(Re, float) and np.isfinite(Re):
                from .hydraulics import flow_regime

                row["regime"] = flow_regime(Re, st.re_laminar, st.re_turbulent)
            if isinstance(Re, float) and np.isfinite(Re) and Re > st.re_laminar:
                warnings.append(Warning_("warning", f"{e.label}: Re = {Re:.0f} -> {row['regime']} flow.", e.id))
            if not e.is_closed() and Q < -1e-9 * (sol.q_scale or 1e-8):
                warnings.append(Warning_("warning", f"Reverse flow in '{e.label}' (Q = {Q / ML_MIN:.4g} mL/min).", e.id))
        rows.append(row)
    edges_df = pd.DataFrame(rows)

    nodes_df = pd.DataFrame([
        {"id": n.id, "label": n.label, "kind": n.kind, "p_pa": sol.node_pressures.get(n.id, math.nan),
         "fixed": n.fixed_pressure is not None, "x": n.pos[0], "y": n.pos[1]}
        for n in net.nodes.values()
    ])

    # ---------- pump ---------------------------------------------------------
    pe = net.edges["pump"]
    Qp = sol.edge_flows["pump"]
    dpp = sol.node_pressures["pump_out"] - sol.node_pressures["pump_in"]
    pump = {"mode": cfg.pump.mode, "Q": Qp, "Q_ml_min": Qp / ML_MIN, "dp": dpp, "P_hyd": Qp * dpp,
            "p_in": sol.node_pressures["pump_in"], "p_out": sol.node_pressures["pump_out"]}
    pel = cfg.pump.electrical_power(Qp) if cfg.pump.mode == "C_pump_curve" else None
    if pel:
        pump["P_el"] = pel
        pump["efficiency"] = Qp * dpp / pel if pel > 0 else math.nan
    if cfg.pump.mode == "D_displacement":
        pump["Q_theoretical"] = cfg.pump.theoretical_flow()
    if sol.converged:
        if dpp > cfg.pump.max_pressure_pa:
            warnings.append(Warning_("error", f"Required pump pressure {dpp/100:.1f} mbar exceeds the maximum permissible "
                                     f"{cfg.pump.max_pressure_pa/100:.1f} mbar.", "pump"))
        if cfg.pump.mode == "A_constant_flow" and dpp < 0:
            warnings.append(Warning_("warning", "Negative pump pressure difference in mode A: the system would drive "
                                     "the flow itself (hydrostatic head) - check elevations.", "pump"))
        if cfg.pump.mode == "C_pump_curve":
            _, ex = cfg.pump.curve_head(Qp)
            if ex:
                warnings.append(Warning_("warning", "Operating point lies outside the measured pump curve (extrapolated).", "pump"))
        if cfg.pump.mode == "D_displacement" and Qp <= 0:
            warnings.append(Warning_("error", "Displacement pump delivers no net flow (slip >= theoretical flow).", "pump"))
        pmin = min(v for v in sol.node_pressures.values() if np.isfinite(v))
        if pmin + 101_325 < fluid.vapor_pressure:
            warnings.append(Warning_("error", "Absolute pressure below vapour pressure -> cavitation/boiling; model invalid.", "system"))
        elif pmin < DEGASSING_WARNING_PA:
            warnings.append(Warning_("warning", f"Minimum gauge pressure {pmin/100:.1f} mbar: risk of degassing / bubble formation "
                                     "(indicative threshold -200 mbar, ASSUMPTION).", "system"))

    # ---------- reactors -----------------------------------------------------
    rrows = []
    reactor_edges = [e for e in net.edges.values() if e.kind == "reactor"]
    q_sum_paths = 0.0
    for e in reactor_edges:
        Q = sol.edge_flows[e.id]
        q_sum_paths += Q
        el = e.element
        det = el.details(Q, fluid, fs)
        pa, pb = sol.node_pressures[e.from_node], sol.node_pressures[e.to_node]
        rrows.append({
            "reactor": el.name, "edge": e.id, "group": e.group, "state": el.state,
            "Q_m3s": Q, "Q_ml_min": Q / ML_MIN,
            "share_percent": 100 * Q / Qp if Qp else math.nan,
            "p_in_pa": pa, "p_out_pa": pb, "dp_pa": pa - pb,
            "dp_scaffold_pa": det.get("dp_scaffold", 0.0),
            "chamber_velocity_m_s": det.get("chamber_mean_velocity", 0.0),
            "superficial_velocity_m_s": det.get("superficial_velocity", math.nan),
            "pore_velocity_estimate_m_s": det.get("pore_velocity_estimate", math.nan),
            "Re_permeability": det.get("Re_permeability", math.nan),
            "shear_stress_estimate_pa": det.get("shear_stress_pore_model", math.nan),
            "R_secant": det.get("R_secant", math.inf),
            "residence_time_s": det.get("residence_time_s", math.inf),
            "volume_ml": el.volume_m3() * 1e6,
            "quantity_type": det.get("quantity_type", "numerical"),
        })
        if el.is_closed():
            warnings.append(Warning_("info", f"{el.name} is blocked (Q = 0).", e.id))
        elif sol.converged and abs(Q) < 1e-6 * max(abs(Qp), 1e-15):
            warnings.append(Warning_("warning", f"{el.name}: practically no flow.", e.id))
    reactors_df = pd.DataFrame(rrows, columns=REACTOR_COLUMNS)

    # ---------- bypass -------------------------------------------------------
    bypass = {"enabled": cfg.layout == "full" and cfg.bypass.enabled}
    if bypass["enabled"]:
        qb = sol.edge_flows.get("bypass_throttle", 0.0)
        bypass.update({
            "Q": qb, "Q_ml_min": qb / ML_MIN, "fraction": qb / Qp if Qp else math.nan,
            "dp": sol.node_pressures["bp_a"] - sol.node_pressures["bp_b"],
            "dp_throttle": sol.node_pressures["bp_thr_in"] - sol.node_pressures["bp_thr_out"]
            if np.isfinite(sol.node_pressures.get("bp_thr_out", math.nan)) else math.nan,
        })
        q_sum_paths += qb
    if cfg.layout == "full":
        bal = Qp - q_sum_paths
        bypass["mass_balance_error_m3s"] = bal
        pump["mass_balance_check"] = bal

    distribution = distribution_metrics(reactors_df["Q_m3s"].to_numpy()) if len(reactors_df) > 1 else {}
    if distribution and distribution.get("cv", 0) > 0.05 and sol.converged:
        warnings.append(Warning_("info", f"Reactor flow distribution CV = {100*distribution['cv']:.1f} % (> 5 %).", "distribution"))

    vb = internal_volume_breakdown(cfg)
    circuit = sum(v for k, v in vb.items() if k != "reservoir (fill)")
    volumes = dict(vb)
    volumes["circuit_total"] = circuit
    volumes["total_medium"] = circuit + vb["reservoir (fill)"]
    if Qp > 0:
        volumes["circulation_time_s"] = volumes["total_medium"] / Qp

    for m in sol.messages:
        warnings.append(Warning_("info", m, "solver"))
    for m in sol.errors:
        warnings.append(Warning_("error", m, "solver"))

    return SimulationResult(
        config=cfg, network=net, fluid=fluid, solver=sol, edges=edges_df, nodes=nodes_df, reactors=reactors_df,
        pump=pump, bypass=bypass, distribution=distribution, volumes=volumes, warnings=warnings,
        timestamp=_dt.datetime.now().isoformat(timespec="seconds"),
    )


def path_profile(res: SimulationResult, group: str) -> pd.DataFrame:
    """Pressure along a flow path (feed -> path group -> return) with cumulative length."""
    net = res.network
    seq = [e for e in net.edges.values() if e.group == "feed"]
    seq += [e for e in net.edges.values() if e.group == group]
    seq += [e for e in net.edges.values() if e.group == "return"]
    rows = []
    s = 0.0
    first = True
    for e in seq:
        if first:
            rows.append({"node": e.from_node, "s_m": 0.0, "p_pa": res.solver.node_pressures[e.from_node], "component": "start"})
            first = False
        L = getattr(e.element, "length_m", None)
        if L is None:
            L = 0.02  # nominal plotting length of lumped components
        s += L
        rows.append({"node": e.to_node, "s_m": s, "p_pa": res.solver.node_pressures[e.to_node], "component": e.label})
    return pd.DataFrame(rows)
