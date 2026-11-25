"""Data export of simulation results (CSV, Excel, JSON) -- spec. chapter 20.

Figures and the PDF report are produced in :mod:`visualization` (they need plotting
libraries); this module only depends on pandas/openpyxl.
"""
from __future__ import annotations

import io
import json
import zipfile

import numpy as np
import pandas as pd

from . import APP_NAME, SOFTWARE_VERSION
from .project import config_hash, flatten
from .simulation import SimulationResult, convergence_info

LAB_UNITS = {
    "Q_ml_min": "mL/min", "p_in_pa": "Pa", "p_out_pa": "Pa", "dp_pa": "Pa", "v_m_s": "m/s", "R_secant": "Pa s/m^3",
    "wall_shear_pa": "Pa", "volume_m3": "m^3", "residence_time_s": "s",
}


def result_tables(res: SimulationResult) -> dict[str, pd.DataFrame]:
    summary = pd.DataFrame([{"quantity": k, "value": v} for k, v in res.summary().items()])
    meta = pd.DataFrame([
        {"key": "software", "value": APP_NAME}, {"key": "software_version", "value": SOFTWARE_VERSION},
        {"key": "timestamp", "value": res.timestamp}, {"key": "configuration", "value": res.config.name},
        {"key": "config_sha256", "value": config_hash(res.config)},
        {"key": "fluid", "value": res.fluid.name}, {"key": "temperature_c", "value": res.fluid.temperature_c},
        {"key": "density_kg_m3", "value": res.fluid.density}, {"key": "dynamic_viscosity_pa_s", "value": res.fluid.dynamic_viscosity},
        {"key": "kinematic_viscosity_m2_s", "value": res.fluid.kinematic_viscosity},
    ])
    conv = pd.DataFrame([{"key": k, "value": str(v)} for k, v in convergence_info(res.solver).items()])
    residuals = pd.DataFrame(
        [{"equation": f"mass balance {k}", "residual": v, "unit": "m^3/s"} for k, v in res.solver.mass_residuals.items()]
        + [{"equation": f"pressure {k}", "residual": v, "unit": "Pa"} for k, v in res.solver.pressure_residuals.items()]
    )
    warnings = pd.DataFrame([w.__dict__ for w in res.warnings], columns=["level", "message", "source"])
    vol = pd.DataFrame([{"group": k, "volume_ml": v * 1e6 if "time" not in k else np.nan, "value_si": v} for k, v in res.volumes.items()])
    cfg = pd.DataFrame([{"parameter": k, "value": str(v)} for k, v in flatten(res.config.model_dump(mode="json")).items()])
    pump = pd.DataFrame([{"quantity": k, "value": v} for k, v in res.pump.items()])
    byp = pd.DataFrame([{"quantity": k, "value": v} for k, v in res.bypass.items()])
    dist = pd.DataFrame([{"metric": k, "value": v} for k, v in res.distribution.items()])
    return {
        "Metadata": meta, "Summary": summary, "Segments": res.edges, "Reactors": res.reactors, "Nodes": res.nodes,
        "Pump": pump, "Bypass": byp, "Distribution": dist, "Volumes": vol, "Convergence": conv,
        "Residuals": residuals, "Warnings": warnings, "Configuration": cfg,
    }


def to_excel_bytes(res: SimulationResult, extra: dict[str, pd.DataFrame] | None = None) -> bytes:
    buf = io.BytesIO()
    tables = result_tables(res)
    tables.update(extra or {})
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        for name, df in tables.items():
            d = df.copy()
            for c in d.columns:
                if d[c].dtype == object:
                    d[c] = d[c].map(lambda v: str(v) if isinstance(v, (list, dict, tuple)) else v)
            d = d.replace([np.inf, -np.inf], np.nan)
            d.to_excel(xw, sheet_name=name[:31], index=False)
    return buf.getvalue()


def to_json_str(res: SimulationResult) -> str:
    data = res.to_dict()
    data["configuration"] = res.config.model_dump(mode="json")
    data["software"] = APP_NAME
    return json.dumps(data, indent=2, default=lambda o: None if isinstance(o, float) and not np.isfinite(o) else str(o))


def to_csv_zip_bytes(res: SimulationResult, extra: dict[str, pd.DataFrame] | None = None) -> bytes:
    buf = io.BytesIO()
    tables = result_tables(res)
    tables.update(extra or {})
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, df in tables.items():
            z.writestr(f"{name}.csv", df.to_csv(index=False))
    return buf.getvalue()


def dataframe_to_excel_bytes(frames: dict[str, pd.DataFrame]) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        for name, df in frames.items():
            df.replace([np.inf, -np.inf], np.nan).to_excel(xw, sheet_name=name[:31], index=False)
    return buf.getvalue()
