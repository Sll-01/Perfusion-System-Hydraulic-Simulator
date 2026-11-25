"""Pump models (spec. chapter 7).

The pump is an *active* network branch from ``pump_in`` to ``pump_out``. Its relation
between flow rate Q and pressure rise dp_pump = p_out - p_in is written as a residual
r(Q, dp_pump) = 0 that is solved simultaneously with the network equations:

* Mode A  constant total flow          r = Q - Q_set
* Mode B  constant pressure difference r = dp_pump - dp_set
* Mode C  experimental pump curve      r = dp_pump - H(Q; n)   (interpolated curve)
* Mode D  positive displacement /      r = Q - (eta_v Q_th(n) - C_slip dp_pump)
          peristaltic substitute model     Q_th = n/60 * V_rev

All default pump parameters are EXAMPLE ASSUMPTIONS until replaced by measurements of the
Stackable Perfusion Pump. The optional pulsation model is a purely kinematic illustration
of roller pulsation, not a validated transient flow simulation (no compliance, inertia or
wave propagation).
"""
from __future__ import annotations

import io
import math
from typing import Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from .units import ML_MIN

PumpMode = Literal["A_constant_flow", "B_constant_pressure", "C_pump_curve", "D_displacement"]

PUMP_MODE_LABELS = {
    "A_constant_flow": "A - constant total flow rate",
    "B_constant_pressure": "B - constant pressure difference",
    "C_pump_curve": "C - experimental pump curve",
    "D_displacement": "D - displacement (peristaltic) model",
}


class CurvePoint(BaseModel):
    speed_rpm: float = 0.0
    flow_ml_min: float
    dp_pa: float
    power_w: float | None = None
    efficiency: float | None = None


def _example_curve() -> list[CurvePoint]:
    # EXAMPLE / ASSUMPTION: synthetic curve of a small pump at two speeds
    pts = []
    for n, q0, p0 in ((30.0, 6.0, 8000.0), (60.0, 12.0, 16000.0)):
        for frac in np.linspace(0, 1, 6):
            pts.append(CurvePoint(speed_rpm=n, flow_ml_min=q0 * frac, dp_pa=p0 * (1 - frac**1.5)))
    return pts


class PulsationConfig(BaseModel):
    enabled: bool = False
    relative_amplitude: float = Field(0.3, ge=0, le=1.0, description="Peak-to-mean amplitude (ASSUMPTION)")
    n_periods: int = 3
    points_per_period: int = 60


class PumpConfig(BaseModel):
    name: str = "Stackable Perfusion Pump (example parameters)"
    mode: PumpMode = "A_constant_flow"
    flow_rate_ml_min: float = Field(5.0, ge=0)
    pressure_difference_pa: float = Field(2000.0)
    speed_rpm: float = Field(30.0, ge=0)
    curve: list[CurvePoint] = Field(default_factory=_example_curve)
    # displacement / peristaltic parameters (ASSUMPTIONS)
    displacement_ml_per_rev: float | None = Field(None, description="Displaced volume per revolution [mL]")
    pump_tube_inner_diameter_mm: float = Field(1.6, gt=0)
    track_radius_mm: float = Field(10.5, gt=0, description="Roller track radius used if displacement is not given")
    n_rollers: int = Field(3, ge=1)
    volumetric_efficiency: float = Field(0.95, gt=0, le=1.0)
    slip_coefficient_ml_min_per_kpa: float = Field(0.0, ge=0, description="Pressure dependent back-flow")
    max_pressure_pa: float = Field(30_000.0, gt=0, description="Max. permissible pump outlet pressure difference")
    pulsation: PulsationConfig = Field(default_factory=PulsationConfig)
    provenance: str = "ASSUMPTION - replace with measured data of the Stackable Perfusion Pump"

    # --- displacement model -----------------------------------------------
    def displacement_volume(self) -> float:
        """V_rev [m^3]; estimate A_tube * 2 pi R_track if not given (rough geometric estimate)."""
        if self.displacement_ml_per_rev:
            return self.displacement_ml_per_rev * 1e-6
        d = self.pump_tube_inner_diameter_mm * 1e-3
        return math.pi * d**2 / 4 * 2 * math.pi * self.track_radius_mm * 1e-3

    def theoretical_flow(self) -> float:
        return self.speed_rpm / 60.0 * self.displacement_volume()

    def slip(self) -> float:
        """C_slip in m^3/(s Pa)."""
        return self.slip_coefficient_ml_min_per_kpa * ML_MIN / 1000.0

    # --- curve model -----------------------------------------------------------
    def curve_frame(self) -> pd.DataFrame:
        return pd.DataFrame([p.model_dump() for p in self.curve])

    def curve_head(self, Q: float, speed: float | None = None) -> tuple[float, bool]:
        """Interpolated pressure rise H(Q; n) [Pa]; returns (H, extrapolated?)."""
        n = self.speed_rpm if speed is None else speed
        df = self.curve_frame()
        if df.empty:
            raise ValueError("Pump curve is empty.")
        q_ml = Q / ML_MIN
        speeds = np.sort(df["speed_rpm"].unique())
        extrap = False

        def head_at(sp):
            sub = df[df["speed_rpm"] == sp].sort_values("flow_ml_min")
            x, y = sub["flow_ml_min"].to_numpy(), sub["dp_pa"].to_numpy()
            if len(x) == 1:
                return y[0], True
            if q_ml < x[0]:
                return y[0] + (y[1] - y[0]) / (x[1] - x[0]) * (q_ml - x[0]), True
            if q_ml > x[-1]:
                return y[-1] + (y[-1] - y[-2]) / (x[-1] - x[-2]) * (q_ml - x[-1]), True
            return float(np.interp(q_ml, x, y)), False

        if len(speeds) == 1 or n <= speeds[0] or n >= speeds[-1]:
            sp = speeds[0] if n <= speeds[0] else speeds[-1]
            h, e = head_at(sp)
            extrap = e or (len(speeds) > 1 and not (speeds[0] <= n <= speeds[-1])) or (len(speeds) == 1 and n != sp)
            if sp != n and sp > 0:
                # affinity-type scaling (Q ~ n, dp ~ n^2) as documented extrapolation
                h_scaled, _ = head_at_scaled(df, sp, n, q_ml)
                return h_scaled, True
            return h, extrap
        i = np.searchsorted(speeds, n)
        s0, s1 = speeds[i - 1], speeds[i]
        h0, e0 = head_at(s0)
        h1, e1 = head_at(s1)
        w = (n - s0) / (s1 - s0)
        return (1 - w) * h0 + w * h1, e0 or e1

    # --- residual for network solver ----------------------------------------
    def residual(self, Q: float, dp_pump: float, p_scale: float, q_scale: float) -> float:
        """Scaled residual of the pump relation."""
        if self.mode == "A_constant_flow":
            return (Q - self.flow_rate_ml_min * ML_MIN) / q_scale
        if self.mode == "B_constant_pressure":
            return (dp_pump - self.pressure_difference_pa) / p_scale
        if self.mode == "C_pump_curve":
            return (dp_pump - self.curve_head(Q)[0]) / p_scale
        q_target = self.volumetric_efficiency * self.theoretical_flow() - self.slip() * dp_pump
        return (Q - q_target) / q_scale

    def linear_guess(self) -> tuple[str, float, float]:
        """Linearised pump relation for the initial guess: returns (kind, a, b) meaning
        'flow': Q = a - b dp  or  'pressure': dp = a - b Q."""
        if self.mode == "A_constant_flow":
            return "flow", self.flow_rate_ml_min * ML_MIN, 0.0
        if self.mode == "D_displacement":
            return "flow", self.volumetric_efficiency * self.theoretical_flow(), self.slip()
        if self.mode == "B_constant_pressure":
            return "pressure", self.pressure_difference_pa, 0.0
        h0, _ = self.curve_head(0.0)
        q1 = max(self.curve_frame()["flow_ml_min"].max(), 1e-6) * ML_MIN
        h1, _ = self.curve_head(q1)
        return "pressure", h0, max((h0 - h1) / q1, 0.0)

    def electrical_power(self, Q: float) -> float | None:
        df = self.curve_frame()
        if df.empty or df["power_w"].isna().all():
            return None
        sub = df[df["speed_rpm"] == df["speed_rpm"].iloc[(df["speed_rpm"] - self.speed_rpm).abs().argmin()]]
        sub = sub.dropna(subset=["power_w"]).sort_values("flow_ml_min")
        if sub.empty:
            return None
        return float(np.interp(Q / ML_MIN, sub["flow_ml_min"], sub["power_w"]))


def head_at_scaled(df: pd.DataFrame, sp_ref: float, n: float, q_ml: float):
    """Affinity-law scaling of the curve measured at sp_ref to speed n (extrapolation!)."""
    r = n / sp_ref
    sub = df[df["speed_rpm"] == sp_ref].sort_values("flow_ml_min")
    x, y = sub["flow_ml_min"].to_numpy() * r, sub["dp_pa"].to_numpy() * r**2
    if len(x) == 1:
        return y[0], True
    if q_ml > x[-1]:
        return y[-1] + (y[-1] - y[-2]) / (x[-1] - x[-2]) * (q_ml - x[-1]), True
    if q_ml < x[0]:
        return y[0], True
    return float(np.interp(q_ml, x, y)), True


# ---------------------------------------------------------------------------
# Import of experimental pump curves
# ---------------------------------------------------------------------------
PUMP_CURVE_COLUMNS = {
    "speed_rpm": ["speed_rpm", "speed", "n_rpm", "drehzahl", "rpm"],
    "flow_ml_min": ["flow_ml_min", "q_ml_min", "flow", "volumenstrom", "q"],
    "dp_pa": ["dp_pa", "dp", "differential_pressure_pa", "differenzdruck_pa", "pressure_pa"],
    "power_w": ["power_w", "power", "leistung_w", "p_el_w"],
    "efficiency": ["efficiency", "eta", "wirkungsgrad"],
}


def _normalise_columns(df: pd.DataFrame, mapping: dict[str, list[str]]) -> pd.DataFrame:
    rename = {}
    lower = {c.lower().strip(): c for c in df.columns}
    for target, aliases in mapping.items():
        for a in aliases:
            if a in lower:
                rename[lower[a]] = target
                break
    return df.rename(columns=rename)


def import_pump_curve(source, filename: str = "") -> list[CurvePoint]:
    """Import a pump curve from CSV or Excel (path, bytes or file-like).

    Required columns: flow_ml_min, dp_pa; optional: speed_rpm, power_w, efficiency.
    Pressure may alternatively be given as ``dp_mbar``.
    """
    name = (filename or str(source)).lower()
    if isinstance(source, (bytes, bytearray)):
        source = io.BytesIO(source)
    if name.endswith((".xlsx", ".xls")):
        df = pd.read_excel(source)
    else:
        df = pd.read_csv(source, sep=None, engine="python")
    if "dp_mbar" in [c.lower() for c in df.columns]:
        col = [c for c in df.columns if c.lower() == "dp_mbar"][0]
        df["dp_pa"] = df[col] * 100.0
    df = _normalise_columns(df, PUMP_CURVE_COLUMNS)
    missing = [c for c in ("flow_ml_min", "dp_pa") if c not in df.columns]
    if missing:
        raise ValueError(f"Pump curve file lacks required columns: {missing}")
    if "speed_rpm" not in df.columns:
        df["speed_rpm"] = 0.0
    pts = []
    for _, r in df.dropna(subset=["flow_ml_min", "dp_pa"]).iterrows():
        pts.append(CurvePoint(
            speed_rpm=float(r["speed_rpm"]), flow_ml_min=float(r["flow_ml_min"]), dp_pa=float(r["dp_pa"]),
            power_w=float(r["power_w"]) if "power_w" in df.columns and pd.notna(r.get("power_w")) else None,
            efficiency=float(r["efficiency"]) if "efficiency" in df.columns and pd.notna(r.get("efficiency")) else None,
        ))
    if not pts:
        raise ValueError("No valid pump curve points found.")
    return pts


# ---------------------------------------------------------------------------
# Optional pulsation model (illustrative, NOT a validated transient simulation)
# ---------------------------------------------------------------------------
def pulsation_waveform(q_mean: float, speed_rpm: float, n_rollers: int, rel_amplitude: float,
                       n_periods: int = 3, points_per_period: int = 60):
    """Kinematic roller-pump pulsation: Q(t) = Q_mean (1 + a s(t)).

    s(t) is a zero-mean, unit-peak periodic function built from a rectified sine with the
    roller passing frequency f = n * N_rollers / 60. Returns (t [s], Q [m^3/s], f [Hz]).
    """
    f = max(speed_rpm, 1e-9) * n_rollers / 60.0
    T = 1.0 / f
    t = np.linspace(0, n_periods * T, n_periods * points_per_period + 1)
    s = np.abs(np.sin(np.pi * f * t))
    s = (s - 2 / np.pi) / (1 - 2 / np.pi)  # zero mean, peak 1
    return t, q_mean * (1 + rel_amplitude * s), f
