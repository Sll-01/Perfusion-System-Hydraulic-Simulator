"""Tube segment model (spec. chapter 5).

Pressure loss of a tube segment (Q >= 0):

    dp = dp_friction(L_straight) + sum(dp_constrictions) + (sum K_i) rho v^2 / 2

* ``dp_friction`` -- Darcy-Weisbach with regime-dependent friction factor
  (laminar: f = 64/Re, identical to Hagen-Poiseuille).
* ``L_straight``  -- tube length minus the lengths of constricted sections, which are
  computed by :mod:`core.constrictions` (no double counting).
* ``K_i``         -- bends, fittings (constant K or 2-K method), area changes at the
  segment outlet and user-defined additional coefficients. All referenced to the mean
  velocity of the nominal tube cross section.

Material roughness values are typical handbook orders of magnitude (ASSUMPTIONS); they
only matter for turbulent flow, which is unusual in low-throughput perfusion systems.
"""
from __future__ import annotations

import math
from typing import Literal

from pydantic import Field

from .constrictions import Constriction
from .elements import HydraulicComponent, QuantityType
from .fluids import FluidState
from .hydraulics import (
    DEFAULT_FRICTION,
    FrictionSettings,
    flow_regime,
    friction_factor,
    friction_method_label,
    hagen_poiseuille_resistance,
    k_sudden_contraction,
    k_sudden_expansion,
    two_k_coefficient,
)
from pydantic import BaseModel

# Typical absolute roughness [m] -- ASSUMED order-of-magnitude values, verify for real tubing
MATERIAL_ROUGHNESS_M: dict[str, float] = {
    "silicone": 1.5e-6,
    "PVC": 1.5e-6,
    "PTFE": 1.0e-6,
    "FEP": 1.0e-6,
    "PharmaPure / TPE": 1.5e-6,
    "polyurethane": 1.5e-6,
    "stainless steel": 1.5e-5,
    "glass": 1.0e-6,
    "custom": 1.5e-6,
}


class Bend(BaseModel):
    count: int = Field(1, ge=0)
    angle_deg: float = 90.0
    bend_radius_mm: float = 10.0
    K: float = Field(0.3, ge=0.0, description="Loss coefficient per bend (ASSUMPTION unless calibrated)")


class Fitting(BaseModel):
    name: str = "connector"
    count: int = Field(1, ge=0)
    K: float = Field(0.1, ge=0.0, description="Constant loss coefficient (or K_inf for 2-K)")
    K1: float = Field(0.0, ge=0.0, description="2-K method laminar coefficient K1 (0 = constant K)")
    volume_ul: float = Field(0.0, ge=0.0, description="Internal volume of one fitting [uL]")


class AreaChange(BaseModel):
    """Sudden area change at the outlet of the segment into a connected diameter."""

    kind: Literal["contraction", "expansion"] = "expansion"
    connected_diameter_mm: float = 3.0
    K_override: float | None = None


class Tube(HydraulicComponent):
    name: str = "tube"
    length_m: float = Field(0.3, ge=0.0)
    inner_diameter_mm: float = Field(1.6, gt=0.0)
    outer_diameter_mm: float | None = 3.2
    wall_thickness_mm: float | None = None
    material: str = "silicone"
    roughness_um: float | None = None
    elevation_change_mm: float = 0.0
    bends: list[Bend] = []
    fittings: list[Fitting] = []
    area_changes: list[AreaChange] = []
    extra_K: float = Field(0.0, ge=0.0)
    constrictions: list[Constriction] = []
    notes: str = ""

    # --- geometry --------------------------------------------------------
    @property
    def d(self) -> float:
        return self.inner_diameter_mm * 1e-3

    @property
    def area(self) -> float:
        return math.pi * self.d**2 / 4

    def roughness_m(self) -> float:
        if self.roughness_um is not None:
            return self.roughness_um * 1e-6
        return MATERIAL_ROUGHNESS_M.get(self.material, MATERIAL_ROUGHNESS_M["custom"])

    def wall_thickness(self) -> float | None:
        """Wall thickness [mm] from outer diameter if not given explicitly."""
        if self.wall_thickness_mm is not None:
            return self.wall_thickness_mm
        if self.outer_diameter_mm is not None:
            return (self.outer_diameter_mm - self.inner_diameter_mm) / 2
        return None

    def geometry_warnings(self) -> list[str]:
        w = []
        if self.outer_diameter_mm is not None and self.outer_diameter_mm <= self.inner_diameter_mm:
            w.append(f"{self.name}: outer diameter <= inner diameter.")
        if (self.wall_thickness_mm is not None and self.outer_diameter_mm is not None
                and abs((self.outer_diameter_mm - self.inner_diameter_mm) / 2 - self.wall_thickness_mm) > 1e-3):
            w.append(f"{self.name}: wall thickness inconsistent with inner/outer diameter.")
        Lc = sum(c.length_mm for c in self.constrictions if c.is_active()) * 1e-3
        if Lc > self.length_m + 1e-12:
            w.append(f"{self.name}: total constriction length exceeds tube length.")
        for c in self.constrictions:
            if c.is_active() and c.position_mm * 1e-3 + c.length_mm * 1e-3 > self.length_m + 1e-9:
                w.append(f"{self.name}: constriction '{c.name}' extends beyond tube end.")
        return w

    def is_closed(self) -> bool:
        return any(c.is_blocked() for c in self.constrictions if c.mode != "open")

    def elevation_change_m(self) -> float:
        return self.elevation_change_mm * 1e-3

    def volume_m3(self) -> float:
        v = self.area * self.length_m
        # reduce by constricted volume (approximate: uniform remaining area)
        for c in self.constrictions:
            if c.is_active() and not c.is_blocked():
                frac = c.remaining_area_fraction(self.d)
                if c.mode == "continuous" and c.taper == "linear":
                    frac = (1 + math.sqrt(frac) + frac) / 3  # mean area of linear taper
                v -= (1 - frac) * self.area * c.length_mm * 1e-3
        v += sum(f.count * f.volume_ul * 1e-9 for f in self.fittings)
        return max(v, 0.0)

    # --- loss coefficients --------------------------------------------------
    def sum_K(self, Re: float) -> float:
        K = self.extra_K
        K += sum(b.count * b.K for b in self.bends)
        for f in self.fittings:
            if f.K1 > 0:
                K += f.count * two_k_coefficient(f.K1, f.K, Re, self.d)
            else:
                K += f.count * f.K
        for ac in self.area_changes:
            K += self.area_change_K(ac)
        return K

    def area_change_K(self, ac: AreaChange) -> float:
        """K referenced to this segment's velocity."""
        if ac.K_override is not None:
            return ac.K_override
        d2 = ac.connected_diameter_mm * 1e-3
        if ac.kind == "expansion":
            return k_sudden_expansion(self.d, d2)
        k_down = k_sudden_contraction(self.d, d2)
        return k_down * (self.d / d2) ** 4

    def straight_length(self) -> float:
        Lc = sum(c.length_mm for c in self.constrictions if c.is_active()) * 1e-3
        return max(self.length_m - Lc, 0.0)

    # --- hydraulics -----------------------------------------------------------
    def _state(self, Q, fluid: FluidState):
        v = Q / self.area
        Re = fluid.density * v * self.d / fluid.dynamic_viscosity
        return v, Re

    def loss_parts(self, Q: float, fluid: FluidState, fs: FrictionSettings = DEFAULT_FRICTION) -> dict:
        v, Re = self._state(Q, fluid)
        rho = fluid.density
        f = friction_factor(Re, self.roughness_m() / self.d, fs)
        dp_fric = f * self.straight_length() / self.d * rho * v**2 / 2
        dp_local = self.sum_K(Re) * rho * v**2 / 2
        dp_constr = sum(c.loss(Q, fluid, fs, self.d, self.roughness_m()) for c in self.constrictions)
        return {"v": v, "Re": Re, "f": f, "dp_friction": dp_fric, "dp_local": dp_local, "dp_constriction": dp_constr}

    def loss(self, Q, fluid, fs=DEFAULT_FRICTION):
        p = self.loss_parts(Q, fluid, fs)
        return p["dp_friction"] + p["dp_local"] + p["dp_constriction"]

    def details(self, Q, fluid, fs=DEFAULT_FRICTION) -> dict:
        if self.is_closed():
            return {"closed": True, "Q": 0.0, "v": 0.0, "Re": 0.0, "regime": "no flow (blocked)",
                    "volume_m3": self.volume_m3(), "dp_total": math.nan}
        qa = abs(Q)
        p = self.loss_parts(qa, fluid, fs)
        mu = fluid.dynamic_viscosity
        tau = p["f"] * fluid.density * p["v"] ** 2 / 8 if qa > 0 else 0.0
        vol = self.volume_m3()
        dp = math.copysign(p["dp_friction"] + p["dp_local"] + p["dp_constriction"], Q) if qa > 0 else 0.0
        return {
            "closed": False,
            "Q": Q,
            "v": math.copysign(p["v"], Q),
            "Re": p["Re"],
            "regime": flow_regime(p["Re"], fs.re_laminar, fs.re_turbulent),
            "friction_method": friction_method_label(p["Re"], fs),
            "friction_factor": p["f"] if qa > 0 else math.nan,
            "dp_friction": p["dp_friction"],
            "dp_local": p["dp_local"],
            "dp_constriction": p["dp_constriction"],
            "dp_total": dp,
            "dp_hydrostatic": self.hydrostatic(fluid),
            "R_poiseuille": hagen_poiseuille_resistance(mu, self.length_m, self.d),
            "R_secant": self.resistance_secant(Q, fluid, fs),
            "wall_shear_stress": tau,
            "volume_m3": vol,
            "residence_time_s": vol / qa if qa > 0 else math.inf,
            "dynamic_pressure": fluid.density * p["v"] ** 2 / 2,
            "sum_K": self.sum_K(p["Re"]),
            "inner_diameter_m": self.d,
            "constrictions": [c.details(qa, fluid, self.d) for c in self.constrictions if c.is_active()],
            "quantity_type": QuantityType.ANALYTICAL if p["Re"] < fs.re_laminar and not self.constrictions
            and self.sum_K(p["Re"]) == 0 else QuantityType.NUMERICAL,
        }
