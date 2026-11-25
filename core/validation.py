"""Experimental validation and calibration (spec. chapter 17).

Data format
-----------
One row per stationary operating point (CSV or Excel). Column groups:

* metadata:       ``point_id``, ``time_s``, ``dataset`` (``calibration`` / ``validation``), ``notes``
* inputs:         ``pump_flow_ml_min``, ``pump_speed_rpm``, ``pump_dp_pa``, ``temperature_c``,
                  ``throttle_<k>_opening_percent``, ``bypass_opening_percent``, and generic
                  ``param:<config path>`` columns (tube dimensions, scaffold properties, ...)
* measurements:   ``Q_total_ml_min``, ``Q_reactor_<k>_ml_min``, ``Q_bypass_ml_min``,
                  ``pump_dp_pa``, ``dp_reactor_<k>_pa``, ``p_<node id>_pa`` (gauge pressure)
* uncertainties:  ``u_<measurement column>`` (standard uncertainty, same unit)

The column ``pump_dp_pa`` is an *input* for pump mode B and a *measurement* otherwise.

Statistics (documented assumptions)
----------------------------------
Deviation e_i = y_sim,i - y_exp,i. MAE, RMSE, bias = mean(e), SD(e) (n-1),
relative deviation e_i / y_exp,i. The 95 % confidence interval of the bias uses the
Student t distribution and assumes independent, normally distributed deviations. R^2 is
only reported for n >= 3 and non-zero variance of the measurements. These are statements
about model-vs-measurement agreement, not about the measurement uncertainty itself.

Calibration
-----------
Weighted non-linear least squares (scipy.optimize.least_squares) of selected configuration
parameters on the *calibration* subset; the calibrated model is then evaluated on the
*validation* subset (strict separation). Positive parameters can be fitted in log-space.
Approximate standard errors follow from the Jacobian (cov = s^2 (J^T J)^-1).
"""
from __future__ import annotations

import io
import math
import re
from pathlib import Path

import numpy as np
import pandas as pd
from pydantic import BaseModel
from scipy import optimize, stats

from .sensitivity import evaluate, get_param, set_param
from .system import PerfusionSystemConfig

INPUT_MAP = {
    "pump_flow_ml_min": "pump.flow_rate_ml_min",
    "pump_speed_rpm": "pump.speed_rpm",
    "temperature_c": "fluid.temperature_c",
    "bypass_opening_percent": "bypass.throttle.opening_percent",
}
MEASUREMENT_PATTERNS = [r"^Q_total_ml_min$", r"^Q_reactor_\d+_ml_min$", r"^Q_bypass_ml_min$", r"^pump_dp_pa$",
                        r"^dp_reactor_\d+_pa$", r"^p_[A-Za-z0-9_]+_pa$"]


def load_experimental_data(source, filename: str = "") -> pd.DataFrame:
    name = (filename or str(source)).lower()
    if isinstance(source, (bytes, bytearray)):
        source = io.BytesIO(source)
    if name.endswith((".xlsx", ".xls")):
        df = pd.read_excel(source)
    else:
        df = pd.read_csv(source, sep=None, engine="python", comment="#")
    df.columns = [str(c).strip() for c in df.columns]
    df = df.dropna(how="all")
    if df.empty:
        raise ValueError("Experimental data file contains no data rows.")
    return df


def measurement_columns(df: pd.DataFrame, pump_mode: str) -> list[str]:
    cols = []
    for c in df.columns:
        if c.startswith("u_") or c.startswith("param:"):
            continue
        if c == "pump_dp_pa" and pump_mode == "B_constant_pressure":
            continue
        if any(re.match(p, c) for p in MEASUREMENT_PATTERNS) and df[c].notna().any():
            cols.append(c)
    return cols


def apply_inputs(base: PerfusionSystemConfig, row: pd.Series) -> PerfusionSystemConfig:
    cfg = base.model_copy(deep=True)
    for col, val in row.items():
        if pd.isna(val):
            continue
        if col in INPUT_MAP:
            set_param(cfg, INPUT_MAP[col], float(val))
        elif col == "pump_dp_pa" and cfg.pump.mode == "B_constant_pressure":
            cfg.pump.pressure_difference_pa = float(val)
        elif m := re.match(r"^throttle_(\d+)_opening_percent$", col):
            k = int(m.group(1)) - 1
            if k < cfg.n_reactors:
                cfg.reactor_paths[k].throttle.opening_percent = float(val)
        elif col.startswith("param:"):
            set_param(cfg, col[len("param:"):], float(val))
    return cfg


def simulate_rows(base: PerfusionSystemConfig, df: pd.DataFrame) -> pd.DataFrame:
    """Simulate every operating point; returns a frame with ``sim:<column>`` entries."""
    meas = measurement_columns(df, base.pump.mode)
    out_rows = []
    prev = None
    for _, row in df.iterrows():
        cfg = apply_inputs(base, row)
        o, sol = evaluate(cfg, initial=prev)
        prev = sol if sol.converged else None
        r = {}
        for c in meas:
            if c.startswith("p_") and c.endswith("_pa") and c != "pump_dp_pa":
                node = c[2:-3]
                r[f"sim:{c}"] = sol.node_pressures.get(node, math.nan)
            else:
                r[f"sim:{c}"] = o.get(c, math.nan)
        r["sim:converged"] = sol.converged
        out_rows.append(r)
    return pd.concat([df.reset_index(drop=True), pd.DataFrame(out_rows)], axis=1)


def comparison_metrics(sim: np.ndarray, exp: np.ndarray, u: np.ndarray | None = None, confidence: float = 0.95) -> dict:
    sim, exp = np.asarray(sim, float), np.asarray(exp, float)
    mask = np.isfinite(sim) & np.isfinite(exp)
    sim, exp = sim[mask], exp[mask]
    n = len(sim)
    if n == 0:
        return {"n": 0}
    e = sim - exp
    d = {
        "n": n,
        "MAE": float(np.mean(np.abs(e))),
        "RMSE": float(np.sqrt(np.mean(e**2))),
        "bias": float(np.mean(e)),
        "SD": float(np.std(e, ddof=1)) if n > 1 else math.nan,
        "mean_rel_dev_percent": float(np.mean(e / np.where(exp != 0, exp, np.nan)) * 100) if np.any(exp != 0) else math.nan,
        "max_abs_dev": float(np.max(np.abs(e))),
    }
    if n > 1:
        t = stats.t.ppf(0.5 + confidence / 2, n - 1)
        half = t * d["SD"] / math.sqrt(n)
        d["bias_CI_low"], d["bias_CI_high"] = d["bias"] - half, d["bias"] + half
    if n >= 3 and np.var(exp) > 0:
        d["R2"] = float(1 - np.sum(e**2) / np.sum((exp - exp.mean()) ** 2))
    if u is not None:
        u = np.asarray(u, float)[mask]
        ok = np.isfinite(u) & (u > 0)
        if ok.any():
            d["fraction_within_2u_percent"] = float(np.mean(np.abs(e[ok]) <= 2 * u[ok]) * 100)
    return d


def compare(base: PerfusionSystemConfig, df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Simulate and compare all measured quantities. Returns (per-point frame, metrics frame)."""
    sim = simulate_rows(base, df)
    rows = []
    for c in measurement_columns(df, base.pump.mode):
        u = sim[f"u_{c}"].to_numpy() if f"u_{c}" in sim else None
        m = comparison_metrics(sim[f"sim:{c}"].to_numpy(), sim[c].to_numpy(), u)
        m["quantity"] = c
        rows.append(m)
        sim[f"dev:{c}"] = sim[f"sim:{c}"] - sim[c]
        sim[f"reldev%:{c}"] = 100 * sim[f"dev:{c}"] / sim[c].replace(0, np.nan)
    metrics = pd.DataFrame(rows)
    if not metrics.empty:
        metrics = metrics[["quantity"] + [c for c in metrics.columns if c != "quantity"]]
    return sim, metrics


class CalibrationParameter(BaseModel):
    path: str
    low: float
    high: float
    log_scale: bool = True
    label: str = ""


def calibrate(base: PerfusionSystemConfig, df: pd.DataFrame, params: list[CalibrationParameter],
              use_relative: bool = True, max_nfev: int = 200) -> tuple[PerfusionSystemConfig, dict]:
    """Calibrate configuration parameters on the rows with dataset == 'calibration' (or all
    rows if no dataset column exists)."""
    cal = df[df["dataset"].astype(str).str.lower() == "calibration"] if "dataset" in df else df
    if cal.empty:
        raise ValueError("No calibration rows (dataset == 'calibration').")
    meas = measurement_columns(cal, base.pump.mode)
    if not meas:
        raise ValueError("No measured quantities found in calibration data.")

    def to_x(vals):
        return np.array([math.log10(v) if p.log_scale else v for v, p in zip(vals, params)])

    def from_x(x):
        return [10**xi if p.log_scale else xi for xi, p in zip(x, params)]

    def apply(x):
        cfg = base.model_copy(deep=True)
        for p, v in zip(params, from_x(x)):
            set_param(cfg, p.path, float(v))
        return cfg

    def residuals(x):
        cfg = apply(x)
        sim = simulate_rows(cfg, cal)
        r = []
        for c in meas:
            y, ys = sim[c].to_numpy(float), sim[f"sim:{c}"].to_numpy(float)
            if f"u_{c}" in sim and sim[f"u_{c}"].notna().all() and (sim[f"u_{c}"] > 0).all():
                w = sim[f"u_{c}"].to_numpy(float)
            elif use_relative:
                w = np.maximum(np.abs(y), 1e-12)
            else:
                w = np.ones_like(y)
            rr = (ys - y) / w
            r.append(np.where(np.isfinite(rr), rr, 1e3))
        return np.concatenate(r)

    x0 = to_x([min(max(float(get_param(base, p.path)), p.low), p.high) for p in params])
    lb = to_x([p.low for p in params])
    ub = to_x([p.high for p in params])
    sol = optimize.least_squares(residuals, x0, bounds=(lb, ub), max_nfev=max_nfev, diff_step=1e-3)
    n, k = len(sol.fun), len(params)
    s2 = float(np.sum(sol.fun**2) / max(n - k, 1))
    try:
        cov = np.linalg.inv(sol.jac.T @ sol.jac) * s2
        se = np.sqrt(np.diag(cov))
    except np.linalg.LinAlgError:
        se = np.full(k, np.nan)
    values = from_x(sol.x)
    info = {
        "success": bool(sol.success),
        "message": sol.message,
        "parameters": [
            {"path": p.path, "value": v, "std_error_transformed": float(s),
             "note": "SE in log10 space" if p.log_scale else "SE in parameter units",
             "at_bound": bool(np.isclose(xi, lo) or np.isclose(xi, hi))}
            for p, v, s, xi, lo, hi in zip(params, values, se, sol.x, lb, ub)
        ],
        "cost": float(sol.cost),
        "n_residuals": n,
        "n_calibration_points": len(cal),
        "residual_std": math.sqrt(s2),
    }
    return apply(sol.x), info


# ---------------------------------------------------------------------------
# Templates for experimental series
# ---------------------------------------------------------------------------
TEMPLATES: dict[str, dict] = {
    "01_single_tube": {
        "description": "Single straight tube: flow vs. pressure drop (layout single_line)",
        "columns": ["point_id", "dataset", "temperature_c", "pump_flow_ml_min", "param:single_line.test_tube.inner_diameter_mm",
                    "param:single_line.test_tube.length_m", "p_test_in_pa", "p_test_out_pa", "u_p_test_in_pa", "u_p_test_out_pa", "notes"],
    },
    "02_tube_diameters": {
        "description": "Different tube inner diameters at constant length",
        "columns": ["point_id", "dataset", "temperature_c", "pump_flow_ml_min", "param:single_line.test_tube.inner_diameter_mm",
                    "p_test_in_pa", "p_test_out_pa", "u_p_test_in_pa", "notes"],
    },
    "03_tube_lengths": {
        "description": "Different tube lengths at constant diameter",
        "columns": ["point_id", "dataset", "temperature_c", "pump_flow_ml_min", "param:single_line.test_tube.length_m",
                    "p_test_in_pa", "p_test_out_pa", "u_p_test_in_pa", "notes"],
    },
    "04_constrictions": {
        "description": "Tube constriction (degree / length) vs. pressure drop",
        "columns": ["point_id", "dataset", "temperature_c", "pump_flow_ml_min", "param:single_line.test_tube.constrictions.0.degree_percent",
                    "param:single_line.test_tube.constrictions.0.length_mm", "p_test_in_pa", "p_test_out_pa", "notes"],
    },
    "05_throttle_characterisation": {
        "description": "Throttle characterisation: opening vs. flow and pressure drop (single_line with throttle)",
        "columns": ["point_id", "dataset", "temperature_c", "pump_flow_ml_min", "throttle_1_opening_percent",
                    "p_test_out_pa", "p_thr_out_pa", "u_p_test_out_pa", "notes"],
    },
    "06_pump_curve": {
        "description": "Pump characteristic: speed, flow, differential pressure, optional power (import in Pump page)",
        "columns": ["speed_rpm", "flow_ml_min", "dp_pa", "power_w", "efficiency", "u_flow_ml_min", "u_dp_pa", "notes"],
    },
    "07_splitter_characterisation": {
        "description": "Splitter characterisation: flow per outlet with identical downstream paths",
        "columns": ["point_id", "dataset", "temperature_c", "pump_flow_ml_min", "Q_reactor_1_ml_min", "Q_reactor_2_ml_min",
                    "Q_reactor_3_ml_min", "Q_reactor_4_ml_min", "p_S1_pa", "u_Q_reactor_1_ml_min", "notes"],
    },
    "08_single_bioreactor": {
        "description": "Single bioreactor (with/without scaffold): flow vs. differential pressure",
        "columns": ["point_id", "dataset", "temperature_c", "pump_flow_ml_min", "param:reactor_paths.0.reactor.scaffold.permeability_m2",
                    "p_thr_out_pa", "p_rx_out_pa", "u_p_thr_out_pa", "notes"],
    },
    "09_four_parallel_reactors": {
        "description": "Four parallel bioreactors without bypass",
        "columns": ["point_id", "dataset", "temperature_c", "pump_flow_ml_min", "throttle_1_opening_percent", "throttle_2_opening_percent",
                    "throttle_3_opening_percent", "throttle_4_opening_percent", "Q_reactor_1_ml_min", "Q_reactor_2_ml_min",
                    "Q_reactor_3_ml_min", "Q_reactor_4_ml_min", "pump_dp_pa", "u_Q_reactor_1_ml_min", "notes"],
    },
    "10_full_system_bypass": {
        "description": "Complete system with bypass",
        "columns": ["point_id", "time_s", "dataset", "temperature_c", "pump_speed_rpm", "pump_flow_ml_min", "throttle_1_opening_percent",
                    "throttle_2_opening_percent", "throttle_3_opening_percent", "throttle_4_opening_percent", "bypass_opening_percent",
                    "Q_total_ml_min", "Q_reactor_1_ml_min", "Q_reactor_2_ml_min", "Q_reactor_3_ml_min", "Q_reactor_4_ml_min",
                    "Q_bypass_ml_min", "pump_dp_pa", "p_rx1_in_pa", "u_Q_reactor_1_ml_min", "u_pump_dp_pa", "notes"],
    },
}


def write_templates(directory: str | Path) -> list[Path]:
    d = Path(directory)
    d.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, t in TEMPLATES.items():
        p = d / f"{name}.csv"
        with open(p, "w", encoding="utf-8", newline="") as fh:
            fh.write(f"# {t['description']}\n")
            fh.write("# Units: flow mL/min, pressure Pa (gauge), length m / mm as in column name, temperature degC.\n")
            fh.write("# Columns u_<name> hold standard uncertainties. 'dataset' = calibration | validation.\n")
            fh.write(",".join(t["columns"]) + "\n")
        paths.append(p)
    return paths
