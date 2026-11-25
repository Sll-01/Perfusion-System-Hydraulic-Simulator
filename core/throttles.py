"""Throttle (adjustable restrictor) models (spec. chapter 9).

The opening degree theta in [0, 1] is mapped to a *relative flow capacity* g(theta)
by an opening characteristic.  A linear characteristic means that the *flow area*
(or Kv, or 1/R) scales linearly with the opening -- it does **not** mean that 50 % opening
gives 50 % flow, because the resulting flow depends on the remaining network.

Opening characteristics g(theta):
    linear              g = theta
    equal_percentage    g = r^(theta-1)   (r = rangeability), g(0) treated as closed
    quick_opening       g = sqrt(theta)
    table               piecewise-linear interpolation of an experimental opening table

Loss models:
    resistance        dp = R_open / g * Q                          (linear, laminar-type)
    orifice_diameter  dp = 128 mu L_t/(pi d^4) Q + rho Q^2 / (2 Cd^2 A^2), A = g A_max
    orifice_area      same as orifice_diameter, A_max given as area
    k_value           dp = K_open / g^2 * rho v_ref^2 / 2          (K ~ 1/A^2)
    kv                dp from Kv(theta) = g Kv_max (IEC 60534 definition, turbulent sizing)
    dp_curve          experimental dp(Q) curves at discrete openings, fitted with
                      dp = a Q + b Q^2 (a, b >= 0) and interpolated linearly in theta.

All throttles have a ``calibration_factor`` multiplying the pressure loss. It is the
default parameter for calibration with experimental data.
"""
from __future__ import annotations

import math
from typing import Literal

import numpy as np
from pydantic import Field

from .elements import HydraulicComponent, QuantityType
from .fluids import FluidState
from .hydraulics import CV_TO_KV, DEFAULT_FRICTION, FrictionSettings, kv_dp

ThrottleModel = Literal["resistance", "orifice_diameter", "orifice_area", "k_value", "kv", "dp_curve"]
Characteristic = Literal["linear", "equal_percentage", "quick_opening", "table"]

CLOSED_OPENING = 1e-9


class Throttle(HydraulicComponent):
    name: str = "throttle"
    opening_percent: float = Field(100.0, ge=0.0, le=100.0)
    model: ThrottleModel = "orifice_diameter"
    characteristic: Characteristic = "linear"
    rangeability: float = Field(30.0, gt=1.0)
    opening_table: list[tuple[float, float]] = Field(
        default_factory=lambda: [(0.0, 0.0), (100.0, 1.0)],
        description="Experimental opening characteristic: (opening %, relative capacity 0..1)",
    )
    # model parameters (EXAMPLE VALUES -- not measured)
    resistance_open: float = Field(5e9, gt=0, description="R at 100 % opening [Pa s/m^3]")
    max_diameter_mm: float = Field(1.0, gt=0, description="Effective orifice diameter at 100 % [mm]")
    max_area_mm2: float | None = Field(None, description="Effective orifice area at 100 % [mm^2]")
    throttle_length_mm: float = Field(2.0, ge=0, description="Length of the viscous throttling gap [mm]")
    discharge_coefficient: float = Field(0.7, gt=0, le=1.0, description="Cd (ASSUMPTION)")
    reference_diameter_mm: float = Field(1.6, gt=0, description="Velocity reference diameter for K [mm]")
    K_open: float = Field(2.0, ge=0, description="Loss coefficient at 100 % opening")
    kv_max: float | None = Field(None, description="Kv at 100 % [m^3/h]")
    cv_max: float | None = Field(None, description="Cv at 100 % [US gpm/psi^0.5] (alternative to Kv)")
    dp_curve_points: list[tuple[float, float, float]] = Field(
        default_factory=list, description="Experimental points (opening %, Q [mL/min], dp [Pa])"
    )
    calibration_factor: float = Field(1.0, gt=0)
    internal_volume_ul: float = 20.0
    provenance: str = "example parameters (ASSUMPTION)"

    # ------------------------------------------------------------------
    @property
    def theta(self) -> float:
        return self.opening_percent / 100.0

    def is_closed(self) -> bool:
        return self.relative_capacity() <= CLOSED_OPENING

    def relative_capacity(self, theta: float | None = None) -> float:
        th = self.theta if theta is None else theta
        if th <= 0:
            return 0.0
        if self.characteristic == "linear":
            return th
        if self.characteristic == "equal_percentage":
            return self.rangeability ** (th - 1.0)
        if self.characteristic == "quick_opening":
            return math.sqrt(th)
        tab = sorted(self.opening_table)
        x = [p[0] / 100.0 for p in tab]
        y = [p[1] for p in tab]
        return float(np.interp(th, x, y))

    def max_area(self) -> float:
        if self.model == "orifice_area" and self.max_area_mm2:
            return self.max_area_mm2 * 1e-6
        return math.pi * (self.max_diameter_mm * 1e-3) ** 2 / 4

    def effective_area(self) -> float:
        return self.relative_capacity() * self.max_area()

    def effective_diameter(self) -> float:
        return math.sqrt(4 * self.effective_area() / math.pi)

    def kv(self) -> float:
        kmax = self.kv_max if self.kv_max is not None else (self.cv_max * CV_TO_KV if self.cv_max else 0.01)
        return self.relative_capacity() * kmax

    def volume_m3(self) -> float:
        return self.internal_volume_ul * 1e-9

    # --- dp curve fitting --------------------------------------------------
    def _curve_coefficients(self):
        """Fit dp = a Q + b Q^2 (a,b >= 0) for each measured opening; returns arrays."""
        pts = np.array(self.dp_curve_points, dtype=float)
        if pts.size == 0:
            raise ValueError(f"{self.name}: dp_curve model selected but no curve points given.")
        out = []
        for op in np.unique(pts[:, 0]):
            sel = pts[pts[:, 0] == op]
            Q = sel[:, 1] * 1e-6 / 60
            dp = sel[:, 2]
            A = np.column_stack([Q, Q**2])
            from scipy.optimize import nnls

            coef, _ = nnls(A, dp)
            out.append((op / 100.0, coef[0], coef[1]))
        out.sort()
        return np.array(out)

    def loss(self, Q, fluid: FluidState, fs: FrictionSettings = DEFAULT_FRICTION) -> float:
        g = self.relative_capacity()
        rho, mu = fluid.density, fluid.dynamic_viscosity
        if self.model == "resistance":
            dp = self.resistance_open / g * Q
        elif self.model in ("orifice_diameter", "orifice_area"):
            A = g * self.max_area()
            d = math.sqrt(4 * A / math.pi)
            dp_visc = 128 * mu * self.throttle_length_mm * 1e-3 / (math.pi * d**4) * Q
            dp_orif = rho * Q**2 / (2 * self.discharge_coefficient**2 * A**2)
            dp = dp_visc + dp_orif
        elif self.model == "k_value":
            A_ref = math.pi * (self.reference_diameter_mm * 1e-3) ** 2 / 4
            v = Q / A_ref
            dp = self.K_open / g**2 * rho * v**2 / 2
        elif self.model == "kv":
            dp = kv_dp(Q, self.kv(), rho)
        else:  # dp_curve
            c = self._curve_coefficients()
            th = self.theta
            a = float(np.interp(th, c[:, 0], c[:, 1]))
            b = float(np.interp(th, c[:, 0], c[:, 2]))
            dp = a * Q + b * Q**2
        return self.calibration_factor * dp

    def details(self, Q, fluid, fs=DEFAULT_FRICTION) -> dict:
        out = {
            "opening_percent": self.opening_percent,
            "relative_capacity": self.relative_capacity(),
            "model": self.model,
            "characteristic": self.characteristic,
            "closed": self.is_closed(),
            "volume_m3": self.volume_m3(),
        }
        if self.is_closed():
            out.update(Q=0.0, dp_total=math.nan)
            return out
        out["Q"] = Q
        out["dp_total"] = self.pressure_drop(Q, fluid, fs)
        out["R_secant"] = self.resistance_secant(Q, fluid, fs)
        if self.model in ("orifice_diameter", "orifice_area"):
            A = self.effective_area()
            d = self.effective_diameter()
            v = abs(Q) / A
            out.update(effective_diameter_m=d, effective_area_m2=A, v=v,
                       Re=fluid.density * v * d / fluid.dynamic_viscosity)
        return out

    def quantity_type(self) -> str:
        if self.model == "dp_curve" or self.characteristic == "table":
            return QuantityType.CALIBRATED
        return QuantityType.EMPIRICAL

    def model_warnings(self, Q: float, fluid: FluidState) -> list[str]:
        w = []
        if self.model == "kv":
            w.append(f"{self.name}: Kv model is a turbulent valve-sizing relation; at low Re it is only indicative.")
        if self.model in ("orifice_diameter", "orifice_area") and not self.is_closed():
            d = self.effective_diameter()
            v = abs(Q) / self.effective_area()
            Re = fluid.density * v * d / fluid.dynamic_viscosity
            if Re > 2000:
                w.append(f"{self.name}: Re in throttle gap = {Re:.0f} (> 2000).")
        if self.model == "dp_curve" and self.dp_curve_points:
            ops = sorted({p[0] for p in self.dp_curve_points})
            if not (ops[0] <= self.opening_percent <= ops[-1]):
                w.append(f"{self.name}: opening {self.opening_percent:.0f} % outside measured range -> extrapolation (clamped).")
        return w
