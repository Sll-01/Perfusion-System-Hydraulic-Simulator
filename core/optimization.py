"""Automatic optimisation of hydraulic settings (spec. chapter 16).

The optimisation problem

    min_x  J(x) + w * sum_i max(0, g_i(x))^2        x_lo <= x <= x_hi

is solved with derivative-free methods from SciPy (the network solution is piecewise
smooth only, e.g. regime switches, so gradient-free methods are more robust):

* ``local``  -- Powell's method with bounds (fast, local optimum)
* ``global`` -- differential evolution (stochastic global search, seed for reproducibility)

Objectives
----------
homogeneous          CV^2 of the reactor flows (most uniform distribution)
individual_targets   mean squared relative deviation from target reactor flows
min_pump_pressure    pump pressure difference
min_losses           hydraulic power Q * dp
min_volume           internal circuit volume
robust_tolerances    mean + 1 SD of CV over Monte-Carlo tube-diameter tolerances
robust_scaffold      mean + 1 SD of CV over Monte-Carlo scaffold permeabilities

Constraints (penalties, normalised): max. pump pressure, max. reactor inlet pressure,
max. pressure drop, max. deviation between reactors, total flow, bypass flow, wall
shear stress targets. Common random numbers are used for the robust objectives so that
the objective is deterministic.

If no feasible solution exists the module explains why (diagnostics based on limiting
configurations, e.g. all throttles fully open).
"""
from __future__ import annotations

import math
import time
from typing import Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field
from scipy import optimize

from .sensitivity import evaluate, expand_path, get_param, set_param
from .simulation import distribution_metrics
from .system import PerfusionSystemConfig

Objective = Literal["homogeneous", "individual_targets", "min_pump_pressure", "min_losses", "min_volume",
                    "robust_tolerances", "robust_scaffold"]

OBJECTIVE_LABELS = {
    "homogeneous": "1 - Homogeneous flow distribution",
    "individual_targets": "2 - Individual target reactor flows",
    "min_pump_pressure": "3 - Minimum pump pressure",
    "min_losses": "4 - Minimum hydraulic losses (power)",
    "min_volume": "5 - Minimum system volume",
    "robust_tolerances": "6 - Robust distribution (tube manufacturing tolerances)",
    "robust_scaffold": "7 - Robust distribution (scaffold resistance variation)",
}


class DecisionVariable(BaseModel):
    path: str
    low: float
    high: float
    label: str = ""


class OptimizationProblem(BaseModel):
    objective: Objective = "homogeneous"
    variables: list[DecisionVariable] = Field(default_factory=list)
    reactor_targets_ml_min: list[float] | None = None
    total_flow_ml_min: float | None = None
    bypass_target_ml_min: float | None = None
    max_pump_pressure_pa: float | None = None
    max_reactor_pressure_pa: float | None = None
    max_pressure_drop_pa: float | None = None
    max_reactor_deviation_percent: float | None = None
    shear_targets_pa: dict[str, float] = Field(default_factory=dict)
    shear_tolerance_percent: float = 10.0
    # robustness
    n_robust_samples: int = 16
    tube_tolerance_mm: float = 0.05
    permeability_cv: float = 0.3
    seed: int = 7
    # algorithm
    method: Literal["local", "global"] = "local"
    max_iterations: int = 60
    penalty_weight: float = 1e3
    constraint_tolerance: float = 1e-3


def default_variables(cfg: PerfusionSystemConfig, include_pump: bool = False, min_opening: float = 5.0) -> list[DecisionVariable]:
    vars_ = [DecisionVariable(path=f"reactor_paths.{i}.throttle.opening_percent", low=min_opening, high=100.0,
                              label=f"Throttle {i+1} opening [%]") for i in range(cfg.n_reactors)]
    if cfg.bypass.enabled and cfg.layout == "full":
        vars_.append(DecisionVariable(path="bypass.throttle.opening_percent", low=min_opening, high=100.0,
                                      label="Bypass throttle opening [%]"))
    if include_pump:
        if cfg.pump.mode == "A_constant_flow":
            q = cfg.pump.flow_rate_ml_min
            vars_.append(DecisionVariable(path="pump.flow_rate_ml_min", low=0.2 * q, high=3 * q, label="Pump flow [mL/min]"))
        elif cfg.pump.mode in ("C_pump_curve", "D_displacement"):
            n = cfg.pump.speed_rpm
            vars_.append(DecisionVariable(path="pump.speed_rpm", low=0.2 * n, high=3 * n, label="Pump speed [rpm]"))
        else:
            p = cfg.pump.pressure_difference_pa
            vars_.append(DecisionVariable(path="pump.pressure_difference_pa", low=0.1 * p, high=5 * p, label="Pump dp [Pa]"))
    return vars_


class OptimizationResult(BaseModel):
    success: bool
    feasible: bool
    x: dict[str, float]
    objective_value: float
    metrics: dict[str, float]
    constraints: list[dict]
    outputs: dict[str, float]
    n_evaluations: int
    runtime_s: float
    method: str
    message: str
    explanations: list[str] = []
    history: list[float] = []


class _Evaluator:
    def __init__(self, base: PerfusionSystemConfig, prob: OptimizationProblem):
        self.base = base
        self.prob = prob
        self.n_eval = 0
        self.prev = None
        self.history: list[float] = []
        self.best = (math.inf, None)
        rng = np.random.default_rng(prob.seed)
        n = base.n_reactors
        self.tube_noise = rng.normal(0, prob.tube_tolerance_mm / 2, (prob.n_robust_samples, n, 3))
        self.perm_noise = rng.lognormal(-0.5 * math.log(1 + prob.permeability_cv**2),
                                        math.sqrt(math.log(1 + prob.permeability_cv**2)), (prob.n_robust_samples, n))

    def apply(self, x) -> PerfusionSystemConfig:
        cfg = self.base.model_copy(deep=True)
        for v, val in zip(self.prob.variables, x):
            set_param(cfg, v.path, float(val))
        return cfg

    def outputs(self, cfg):
        out, sol = evaluate(cfg, initial=self.prev, shear_segments=list(self.prob.shear_targets_pa) or None)
        if sol.converged:
            self.prev = sol
        return out, sol

    def reactor_q(self, out) -> np.ndarray:
        n = self.base.n_reactors
        return np.array([out.get(f"Q_reactor_{k+1}_ml_min", math.nan) for k in range(n)])

    def robust_cv(self, cfg, kind: str) -> tuple[float, float]:
        cvs = []
        for s in range(self.prob.n_robust_samples):
            c = cfg.model_copy(deep=True)
            for i, path in enumerate(c.reactor_paths):
                if kind == "tol":
                    for j, t in enumerate(("tube_to_throttle", "tube_to_reactor", "tube_to_collector")):
                        tube = getattr(path, t)
                        tube.inner_diameter_mm = max(tube.inner_diameter_mm + self.tube_noise[s, i, j], 1e-3)
                else:
                    path.reactor.scaffold.permeability_m2 *= self.perm_noise[s, i]
            o, _ = evaluate(c, initial=self.prev)
            q = self.reactor_q(o)
            cvs.append(distribution_metrics(q)["cv"] if np.all(np.isfinite(q)) and q.mean() > 0 else 10.0)
        return float(np.mean(cvs)), float(np.std(cvs))

    def constraints(self, out: dict) -> list[dict]:
        p = self.prob
        cons = []

        def add(name, value, limit, kind="max", scale=None):
            scale = scale or max(abs(limit), 1e-12)
            viol = (value - limit) / scale if kind == "max" else (limit - value) / scale
            if kind == "eq":
                viol = abs(value - limit) / scale - 0.01  # 1 % band
            cons.append({"constraint": name, "value": value, "limit": limit, "type": kind, "violation": max(viol, 0.0)})

        if p.max_pump_pressure_pa is not None:
            add("Pump pressure [Pa]", out["pump_dp_pa"], p.max_pump_pressure_pa)
        if p.max_reactor_pressure_pa is not None:
            add("Max. reactor inlet pressure [Pa]", out["max_reactor_inlet_pressure_pa"], p.max_reactor_pressure_pa)
        if p.max_pressure_drop_pa is not None:
            add("System pressure drop [Pa]", out["pump_dp_pa"], p.max_pressure_drop_pa)
        if p.max_reactor_deviation_percent is not None and "max_rel_dev_percent" in out:
            add("Max. deviation between reactors [%]", out["max_rel_dev_percent"], p.max_reactor_deviation_percent, scale=100)
        if p.total_flow_ml_min is not None:
            add("Total flow [mL/min]", out["Q_total_ml_min"], p.total_flow_ml_min, "eq")
        if p.bypass_target_ml_min is not None and "Q_bypass_ml_min" in out:
            add("Bypass flow [mL/min]", out["Q_bypass_ml_min"], p.bypass_target_ml_min, "eq",
                scale=max(p.bypass_target_ml_min, 0.05 * max(out["Q_total_ml_min"], 1e-9)))
        for seg, tau in p.shear_targets_pa.items():
            val = out.get(f"wall_shear_{seg}_pa", math.nan)
            add(f"Wall shear {seg} [Pa]", val, tau, "eq", scale=tau)
            cons[-1]["violation"] = max(abs(val - tau) / tau - p.shear_tolerance_percent / 100, 0.0)
        if p.objective != "individual_targets" and p.reactor_targets_ml_min:
            q = self.reactor_q(out)
            t = np.array(p.reactor_targets_ml_min[: len(q)])
            rmse = float(np.sqrt(np.mean(((q - t) / t) ** 2)))
            cons.append({"constraint": "Reactor target flows (rel. RMSE)", "value": rmse, "limit": 0.01, "type": "max",
                         "violation": max(rmse - 0.01, 0)})
        return cons

    def objective(self, cfg, out) -> float:
        p = self.prob
        q = self.reactor_q(out)
        if p.objective == "homogeneous":
            dm = distribution_metrics(q)
            return dm["cv"] ** 2 * 1e2
        if p.objective == "individual_targets":
            t = np.array(p.reactor_targets_ml_min[: len(q)])
            return float(np.mean(((q - t) / t) ** 2)) * 1e2
        if p.objective == "min_pump_pressure":
            return out["pump_dp_pa"] / 1000.0
        if p.objective == "min_losses":
            return out["hydraulic_power_w"] * 1e3
        if p.objective == "min_volume":
            return out["system_volume_ml"]
        m, s = self.robust_cv(cfg, "tol" if p.objective == "robust_tolerances" else "perm")
        return (m + s) * 10

    def __call__(self, x) -> float:
        self.n_eval += 1
        cfg = self.apply(x)
        try:
            out, sol = self.outputs(cfg)
        except Exception:
            return 1e9
        if not sol.converged or not np.isfinite(out.get("pump_dp_pa", math.nan)):
            return 1e9
        J = self.objective(cfg, out)
        pen = sum(c["violation"] ** 2 for c in self.constraints(out))
        val = float(J + self.prob.penalty_weight * pen)
        if not np.isfinite(val):
            val = 1e9
        if val < self.best[0]:
            self.best = (val, np.array(x, dtype=float))
        self.history.append(min(val, self.history[-1]) if self.history else val)
        return val


def optimize_system(base: PerfusionSystemConfig, prob: OptimizationProblem, progress=None) -> tuple[OptimizationResult, PerfusionSystemConfig]:
    if not prob.variables:
        prob = prob.model_copy(update={"variables": default_variables(base)})
    if prob.objective == "individual_targets" and not prob.reactor_targets_ml_min:
        raise ValueError("Objective 'individual_targets' needs reactor target flows.")
    ev = _Evaluator(base, prob)
    bounds = [(v.low, v.high) for v in prob.variables]
    x0 = np.array([min(max(float(get_param(base, v.path)), v.low), v.high) for v in prob.variables])
    t0 = time.time()
    if prob.method == "global":
        cb = (lambda xk, convergence=None: progress(min(ev.n_eval / (prob.max_iterations * 10 * len(bounds)), 1.0))) if progress else None
        res = optimize.differential_evolution(ev, bounds, maxiter=prob.max_iterations, popsize=10, seed=prob.seed,
                                              tol=1e-8, polish=True, x0=x0, callback=cb, updating="immediate")
        method = "differential evolution (SciPy) + polish"
    else:
        cb = (lambda xk: progress(min(ev.n_eval / (prob.max_iterations * 60), 1.0))) if progress else None
        # multi-start local search: current setting, centre and upper part of the box
        lo, hi = np.array([b[0] for b in bounds]), np.array([b[1] for b in bounds])
        starts = [x0, lo + 0.5 * (hi - lo), lo + 0.25 * (hi - lo)]
        res = None
        for xs in starts:
            r = optimize.minimize(ev, xs, method="Powell", bounds=bounds, callback=cb,
                                  options={"maxiter": prob.max_iterations, "xtol": 1e-4, "ftol": 1e-10})
            if res is None or r.fun < res.fun:
                res = r
            if res.fun < 1e-8:
                break
        method = "Powell (SciPy, bounded, multi-start)"
    x_best = ev.best[1] if ev.best[1] is not None else res.x
    cfg_opt = ev.apply(x_best)
    out, sol = evaluate(cfg_opt, shear_segments=list(prob.shear_targets_pa) or None)
    cons = ev.constraints(out)
    feasible = bool(sol.converged and all(c["violation"] <= prob.constraint_tolerance for c in cons))
    q = ev.reactor_q(out)
    metrics = {}
    if len(q) > 0:
        dm = distribution_metrics(q, np.array(prob.reactor_targets_ml_min[: len(q)]) if prob.reactor_targets_ml_min else None)
        metrics = {"mean_ml_min": dm["mean"], "std_ml_min": dm["std"], "cv_percent": 100 * dm["cv"],
                   "max_rel_dev_percent": 100 * dm["max_rel_dev"]}
        if "rmse_vs_target" in dm:
            metrics["rmse_vs_target_ml_min"] = dm["rmse_vs_target"]
    if prob.objective in ("robust_tolerances", "robust_scaffold"):
        m, s = ev.robust_cv(cfg_opt, "tol" if prob.objective == "robust_tolerances" else "perm")
        metrics["robust_mean_cv_percent"] = 100 * m
        metrics["robust_std_cv_percent"] = 100 * s
    explanations = [] if feasible else diagnose_infeasibility(base, prob, out, cons)
    if prob.objective == "individual_targets" and metrics.get("rmse_vs_target_ml_min", 0) > 0.01 * np.mean(prob.reactor_targets_ml_min):
        feasible = False
        explanations = explanations or diagnose_infeasibility(base, prob, out, cons)
    result = OptimizationResult(
        success=bool(sol.converged), feasible=feasible,
        x={v.path: float(val) for v, val in zip(prob.variables, x_best)},
        objective_value=float(ev(x_best)), metrics=metrics, constraints=cons,
        outputs={k: float(v) for k, v in out.items() if isinstance(v, (int, float))},
        n_evaluations=ev.n_eval, runtime_s=time.time() - t0, method=method,
        message=str(getattr(res, "message", "")), explanations=explanations, history=ev.history,
    )
    return result, cfg_opt


def diagnose_infeasibility(base: PerfusionSystemConfig, prob: OptimizationProblem, out: dict, cons: list[dict]) -> list[str]:
    """Explain why no feasible solution was found using limiting configurations."""
    expl = []
    thr_vars = [v for v in prob.variables if "throttle.opening_percent" in v.path]
    # 1) minimum pressure demand: all throttles at their maximum opening
    cfg_open = base.model_copy(deep=True)
    for v in thr_vars:
        set_param(cfg_open, v.path, v.high)
    try:
        o_open, _ = evaluate(cfg_open)
    except Exception:
        o_open = {}
    if prob.max_pump_pressure_pa is not None and o_open and o_open["pump_dp_pa"] > prob.max_pump_pressure_pa:
        expl.append(
            f"Even with all throttles at maximum opening the pump must deliver {o_open['pump_dp_pa']:.0f} Pa "
            f"> limit {prob.max_pump_pressure_pa:.0f} Pa. Reduce the flow rate, enlarge tube diameters or shorten tubes."
        )
    if prob.max_reactor_pressure_pa is not None and o_open and o_open["max_reactor_inlet_pressure_pa"] > prob.max_reactor_pressure_pa:
        expl.append(
            f"Minimum achievable reactor inlet pressure is {o_open['max_reactor_inlet_pressure_pa']:.0f} Pa "
            f"> limit {prob.max_reactor_pressure_pa:.0f} Pa (pressure is dominated by downstream resistances)."
        )
    # 2) target flows: sum consistency (mode A, pump flow fixed)
    pump_var = any(v.path.startswith("pump.") for v in prob.variables)
    if prob.reactor_targets_ml_min:
        tsum = sum(prob.reactor_targets_ml_min[: base.n_reactors]) + (prob.bypass_target_ml_min or 0.0)
        if base.pump.mode == "A_constant_flow" and not pump_var:
            q_tot = base.pump.flow_rate_ml_min
            if base.bypass.enabled and prob.bypass_target_ml_min is None:
                if tsum > q_tot * (1 + 1e-3):
                    expl.append(f"Sum of reactor targets ({tsum:.3g} mL/min) exceeds the fixed pump flow ({q_tot:.3g} mL/min).")
            elif abs(tsum - q_tot) > 1e-3 * q_tot:
                expl.append(f"Mass conservation: sum of targets ({tsum:.3g} mL/min) != fixed pump flow ({q_tot:.3g} mL/min). "
                            "Q_pump = sum(Q_reactor) + Q_bypass must hold.")
        # 3) maximum achievable share per reactor: own throttle open, others minimum
        if thr_vars:
            for i, t in enumerate(prob.reactor_targets_ml_min[: base.n_reactors]):
                cfg_i = base.model_copy(deep=True)
                for v in thr_vars:
                    set_param(cfg_i, v.path, v.high if v.path.startswith(f"reactor_paths.{i}.") else v.low)
                try:
                    o_i, _ = evaluate(cfg_i)
                except Exception:
                    continue
                share_max = o_i.get(f"share_reactor_{i+1}_percent", math.nan)
                tshare = 100 * t / (out["Q_total_ml_min"] or math.nan)
                if np.isfinite(share_max) and tshare > share_max * 1.001:
                    expl.append(
                        f"Reactor {i+1}: target share {tshare:.1f} % of the total flow exceeds the maximum achievable "
                        f"share {share_max:.1f} % (own throttle fully open, all others at minimum opening). Throttles can "
                        "only add resistance; reduce the resistance of this path (tube ID/length, scaffold) instead."
                    )
    for c in cons:
        if c["violation"] > prob.constraint_tolerance:
            expl.append(f"Constraint not satisfied: {c['constraint']} = {c['value']:.4g} (limit {c['limit']:.4g}).")
    if not expl:
        expl.append("The optimiser did not find a feasible point within the iteration budget; try the global method or relax limits.")
    return expl


def result_table(res: OptimizationResult, prob: OptimizationProblem) -> pd.DataFrame:
    rows = [{"variable": v.label or v.path, "path": v.path, "optimum": res.x[v.path], "low": v.low, "high": v.high}
            for v in prob.variables]
    return pd.DataFrame(rows)
