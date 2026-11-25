"""Parameter studies, sensitivity analysis, Monte-Carlo / tolerance / uncertainty analysis
(spec. chapter 15).

Parameters are addressed by dotted configuration paths in *configuration units*
(e.g. ``reactor_paths.0.tube_to_reactor.inner_diameter_mm`` in mm,
``pump.flow_rate_ml_min`` in mL/min). A ``*`` wildcard applies the same value to all list
entries (``reactor_paths.*.throttle.opening_percent``).

Every study is reproducible: the base configuration, the parameter definitions, the random
seed and the software version are stored together with the results (see core.project).
"""
from __future__ import annotations

import itertools
import math
from typing import Callable, Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field
from scipy.stats import qmc

from . import SOFTWARE_VERSION
from .fluids import evaluate_fluid
from .simulation import distribution_metrics
from .solver import SolverResult, solve_network
from .system import PerfusionSystemConfig, build_network, get_by_path, set_by_path
from .units import ML_MIN


# ---------------------------------------------------------------------------
# Parameter handling
# ---------------------------------------------------------------------------
def expand_path(cfg, path: str) -> list[str]:
    """Expand '*' wildcards to concrete list indices."""
    parts = path.split(".")
    results = [""]
    for part in parts:
        new = []
        for prefix in results:
            if part == "*":
                obj = get_by_path(cfg, prefix.strip("."))
                new += [f"{prefix}.{i}" if prefix else str(i) for i in range(len(obj))]
            else:
                new.append(f"{prefix}.{part}" if prefix else part)
        results = new
    return results


def set_param(cfg, path: str, value) -> None:
    for p in expand_path(cfg, path):
        set_by_path(cfg, p, value)


def get_param(cfg, path: str):
    paths = expand_path(cfg, path)
    return get_by_path(cfg, paths[0])


class ParameterSpec(BaseModel):
    path: str
    label: str = ""
    low: float | None = None
    high: float | None = None
    n: int = 11
    scale: Literal["linear", "log"] = "linear"
    values: list[float] | None = None
    # uncertainty definition (Monte-Carlo)
    distribution: Literal["normal", "uniform", "lognormal", "fixed"] = "normal"
    nominal: float | None = None
    std: float | None = None
    tolerance: float | None = Field(None, description="+/- tolerance; normal: std = tol/2 (95 %), uniform: [nom-tol, nom+tol]")
    per_element: bool = Field(True, description="Wildcard paths: sample each element independently (MC)")

    def grid(self) -> np.ndarray:
        if self.values:
            return np.asarray(self.values, dtype=float)
        if self.low is None or self.high is None:
            raise ValueError(f"Range of parameter '{self.path}' undefined")
        if self.scale == "log":
            return np.logspace(math.log10(self.low), math.log10(self.high), self.n)
        return np.linspace(self.low, self.high, self.n)

    def display(self) -> str:
        return self.label or self.path


# ---------------------------------------------------------------------------
# Fast evaluation
# ---------------------------------------------------------------------------
def evaluate(cfg: PerfusionSystemConfig, initial: SolverResult | None = None,
             shear_segments: list[str] | None = None) -> tuple[dict, SolverResult]:
    """Solve the configuration and extract scalar key outputs (SI units)."""
    fluid = evaluate_fluid(cfg.fluid)
    net = build_network(cfg)
    st = cfg.solver.model_copy()
    if st.flow_scale_m3s is None:
        kind, a, _ = cfg.pump.linear_guess()
        st.flow_scale_m3s = a if (kind == "flow" and a > 0) else 1e-7
    sol = solve_network(net, fluid, st, initial=initial)
    p, q = sol.node_pressures, sol.edge_flows
    out: dict[str, float] = {"converged": float(sol.converged)}
    Qp = q.get("pump", math.nan)
    out["Q_total_ml_min"] = Qp / ML_MIN
    out["pump_dp_pa"] = p["pump_out"] - p["pump_in"]
    out["hydraulic_power_w"] = Qp * out["pump_dp_pa"]
    rq = []
    for e in net.edges.values():
        if e.kind == "reactor":
            k = e.id.split("_")[-1]
            Q = q[e.id]
            rq.append(Q)
            out[f"Q_reactor_{k}_ml_min"] = Q / ML_MIN
            out[f"share_reactor_{k}_percent"] = 100 * Q / Qp if Qp else math.nan
            out[f"p_reactor_{k}_in_pa"] = p[e.from_node]
            out[f"dp_reactor_{k}_pa"] = p[e.from_node] - p[e.to_node]
    if "bypass_throttle" in q:
        out["Q_bypass_ml_min"] = q["bypass_throttle"] / ML_MIN
        out["bypass_fraction_percent"] = 100 * q["bypass_throttle"] / Qp if Qp else math.nan
    if len(rq) > 1:
        dm = distribution_metrics(np.array(rq))
        out["cv_percent"] = 100 * dm["cv"]
        out["max_rel_dev_percent"] = 100 * dm["max_rel_dev"]
        out["min_max_ratio"] = dm["min_max_ratio"]
    rx_in = [v for k, v in out.items() if k.startswith("p_reactor_") and np.isfinite(v)]
    out["max_reactor_inlet_pressure_pa"] = max(rx_in) if rx_in else math.nan
    finite_p = [v for v in p.values() if np.isfinite(v)]
    out["max_pressure_pa"] = max(finite_p) if finite_p else math.nan
    out["min_pressure_pa"] = min(finite_p) if finite_p else math.nan
    out["system_volume_ml"] = net.total_volume_m3() * 1e6 + (
        (cfg.splitter_in.hub_volume() + cfg.splitter_out.hub_volume()) * 1e6 if cfg.layout == "full" else 0.0)
    if shear_segments:
        fs = st.friction()
        for sid in shear_segments:
            if sid in net.edges:
                det = net.edges[sid].element.details(q[sid], fluid, fs)
                out[f"wall_shear_{sid}_pa"] = det.get("wall_shear_stress", math.nan)
    return out, sol


# ---------------------------------------------------------------------------
# Studies
# ---------------------------------------------------------------------------
def _run_points(base: PerfusionSystemConfig, specs: list[ParameterSpec], points: np.ndarray,
                progress: Callable[[float], None] | None = None, shear_segments=None) -> pd.DataFrame:
    rows = []
    prev = None
    n = len(points)
    for i, pt in enumerate(points):
        cfg = base.model_copy(deep=True)
        for s, v in zip(specs, pt):
            set_param(cfg, s.path, float(v))
        try:
            out, sol = evaluate(cfg, initial=prev, shear_segments=shear_segments)
            prev = sol if sol.converged else None
        except Exception as exc:  # invalid configuration point
            out = {"converged": 0.0, "error": str(exc)}
        row = {s.path: float(v) for s, v in zip(specs, pt)}
        row.update(out)
        rows.append(row)
        if progress:
            progress((i + 1) / n)
    return pd.DataFrame(rows)


def sweep_1d(base, spec: ParameterSpec, progress=None, shear_segments=None) -> pd.DataFrame:
    return _run_points(base, [spec], spec.grid().reshape(-1, 1), progress, shear_segments)


def sweep_grid(base, specs: list[ParameterSpec], progress=None) -> pd.DataFrame:
    """Full-factorial study over 1..n parameters (2D: heat maps / surfaces)."""
    grids = [s.grid() for s in specs]
    pts = np.array(list(itertools.product(*grids)), dtype=float)
    return _run_points(base, specs, pts, progress)


def latin_hypercube_study(base, specs: list[ParameterSpec], n_samples: int, seed: int = 1, progress=None) -> pd.DataFrame:
    """Multi-dimensional study by Latin-Hypercube sampling of the given ranges."""
    sampler = qmc.LatinHypercube(d=len(specs), seed=seed)
    u = sampler.random(n_samples)
    pts = np.empty_like(u)
    for j, s in enumerate(specs):
        if s.scale == "log":
            pts[:, j] = 10 ** (math.log10(s.low) + u[:, j] * (math.log10(s.high) - math.log10(s.low)))
        else:
            pts[:, j] = s.low + u[:, j] * (s.high - s.low)
    return _run_points(base, specs, pts, progress)


def local_sensitivity(base, paths: list[str], outputs: list[str] | None = None, rel_step: float = 0.01) -> pd.DataFrame:
    """Normalised local sensitivities (elasticities) by central differences:

        S_ij = (d y_i / y_i) / (d x_j / x_j)

    S = 1 means 1 % change of the parameter changes the output by 1 %.
    """
    y0, sol0 = evaluate(base)
    outputs = outputs or [k for k in y0 if k != "converged"]
    rows = []
    for path in paths:
        x0 = float(get_param(base, path))
        if x0 == 0:
            continue
        h = rel_step * abs(x0)
        res = {}
        for sign in (+1, -1):
            cfg = base.model_copy(deep=True)
            set_param(cfg, path, x0 + sign * h)
            res[sign], _ = evaluate(cfg, initial=sol0)
        for o in outputs:
            yo = y0.get(o, math.nan)
            if not np.isfinite(yo) or yo == 0:
                s = math.nan
            else:
                s = (res[1][o] - res[-1][o]) / (2 * h) * x0 / yo
            rows.append({"parameter": path, "output": o, "elasticity": s, "nominal_parameter": x0, "nominal_output": yo})
    return pd.DataFrame(rows)


def monte_carlo(base, specs: list[ParameterSpec], n_samples: int = 200, seed: int = 42,
                progress=None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Monte-Carlo uncertainty / tolerance propagation.

    For wildcard parameters with ``per_element`` each list element is sampled
    independently (e.g. manufacturing tolerance of every tube individually).
    Returns (samples, summary statistics).
    """
    rng = np.random.default_rng(seed)
    expanded: list[ParameterSpec] = []
    for s in specs:
        paths = expand_path(base, s.path) if s.per_element else [s.path]
        for p in paths:
            nom = s.nominal if s.nominal is not None else float(get_param(base, p))
            expanded.append(s.model_copy(update={"path": p, "nominal": nom}))
    samples = np.empty((n_samples, len(expanded)))
    for j, s in enumerate(expanded):
        nom = s.nominal
        if s.distribution == "fixed":
            samples[:, j] = nom
        elif s.distribution == "uniform":
            tol = s.tolerance if s.tolerance is not None else (s.std or 0) * math.sqrt(3)
            lo = s.low if s.low is not None else nom - tol
            hi = s.high if s.high is not None else nom + tol
            samples[:, j] = rng.uniform(lo, hi, n_samples)
        elif s.distribution == "lognormal":
            sd = s.std if s.std is not None else (s.tolerance or 0) / 2
            sigma = math.sqrt(math.log(1 + (sd / nom) ** 2))
            samples[:, j] = rng.lognormal(math.log(nom) - sigma**2 / 2, sigma, n_samples)
        else:
            sd = s.std if s.std is not None else (s.tolerance or 0) / 2
            samples[:, j] = rng.normal(nom, sd, n_samples)
    df = _run_points(base, expanded, samples, progress)
    num = df.select_dtypes(include=[np.number])
    num = num[num.get("converged", 1) == 1] if "converged" in num else num
    summary = pd.DataFrame({
        "mean": num.mean(), "std": num.std(ddof=1), "min": num.min(),
        "p2.5": num.quantile(0.025), "p50": num.quantile(0.5), "p97.5": num.quantile(0.975), "max": num.max(),
    })
    df.attrs.update({"seed": seed, "n_samples": n_samples, "software_version": SOFTWARE_VERSION})
    return df, summary


def tube_tolerance_study(base, tolerance_mm: float = 0.05, n_samples: int = 200, seed: int = 42,
                         distribution: str = "normal", include_feed: bool = False, progress=None):
    """Manufacturing-tolerance study of the tube inner diameters in all reactor paths."""
    specs = [ParameterSpec(path=f"reactor_paths.*.{t}.inner_diameter_mm", distribution=distribution, tolerance=tolerance_mm)
             for t in ("tube_to_throttle", "tube_to_reactor", "tube_to_collector")]
    if include_feed:
        specs += [ParameterSpec(path=f"{t}.inner_diameter_mm", distribution=distribution, tolerance=tolerance_mm)
                  for t in ("suction_tube", "pump_outlet_tube", "return_tube")]
    return monte_carlo(base, specs, n_samples, seed, progress)


def parameter_catalog(cfg: PerfusionSystemConfig) -> dict[str, str]:
    """Commonly varied parameters: path -> human readable label (with unit)."""
    cat = {
        "pump.flow_rate_ml_min": "Pump flow rate [mL/min]",
        "pump.pressure_difference_pa": "Pump pressure difference [Pa]",
        "pump.speed_rpm": "Pump speed [rpm]",
        "fluid.temperature_c": "Temperature [degC]",
        "reactor_paths.*.throttle.opening_percent": "All reactor throttles: opening [%]",
        "reactor_paths.*.tube_to_reactor.inner_diameter_mm": "All tubes throttle->reactor: ID [mm]",
        "reactor_paths.*.tube_to_reactor.length_m": "All tubes throttle->reactor: length [m]",
        "reactor_paths.*.reactor.scaffold.permeability_m2": "All scaffolds: permeability [m^2]",
        "suction_tube.inner_diameter_mm": "Suction tube ID [mm]",
        "pump_outlet_tube.inner_diameter_mm": "Pump outlet tube ID [mm]",
        "pump_outlet_tube.length_m": "Pump outlet tube length [m]",
        "return_tube.inner_diameter_mm": "Return tube ID [mm]",
        "return_tube.length_m": "Return tube length [m]",
    }
    if cfg.bypass.enabled:
        cat["bypass.throttle.opening_percent"] = "Bypass throttle opening [%]"
        cat["bypass.tube_upstream.inner_diameter_mm"] = "Bypass tube (upstream) ID [mm]"
    for i, p in enumerate(cfg.reactor_paths):
        k = i + 1
        cat[f"reactor_paths.{i}.throttle.opening_percent"] = f"Throttle {k} opening [%]"
        cat[f"reactor_paths.{i}.reactor.scaffold.permeability_m2"] = f"Scaffold {k} permeability [m^2]"
        for t, lbl in (("tube_to_throttle", "splitter->throttle"), ("tube_to_reactor", "throttle->reactor"),
                       ("tube_to_collector", "reactor->splitter")):
            cat[f"reactor_paths.{i}.{t}.inner_diameter_mm"] = f"R{k} tube {lbl} ID [mm]"
            cat[f"reactor_paths.{i}.{t}.length_m"] = f"R{k} tube {lbl} length [m]"
            tube = getattr(p, t)
            for j, _ in enumerate(tube.constrictions):
                cat[f"reactor_paths.{i}.{t}.constrictions.{j}.degree_percent"] = f"R{k} tube {lbl} constriction {j+1} degree [%]"
    if cfg.layout == "single_line":
        cat["single_line.test_tube.inner_diameter_mm"] = "Test tube ID [mm]"
        cat["single_line.test_tube.length_m"] = "Test tube length [m]"
        for j, _ in enumerate(cfg.single_line.test_tube.constrictions):
            cat[f"single_line.test_tube.constrictions.{j}.degree_percent"] = f"Test tube constriction {j+1} degree [%]"
    return cat
