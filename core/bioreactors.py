"""Bioreactor model (spec. chapter 10).

A perfusion bioreactor is modelled as a series connection of

1. inlet channel (circular, Darcy-Weisbach)                       -> numerical/analytical
2. sudden expansion inlet channel -> chamber (Borda-Carnot K)      -> empirical
3. free chamber length (circular duct with chamber diameter)       -> analytical (laminar)
4. scaffold (Darcy / Darcy-Forchheimer), if present                -> analytical / empirical
5. sudden contraction chamber -> outlet channel                    -> empirical
6. outlet channel                                                  -> numerical/analytical
7. additional internal linear resistance and additional K values   -> user / calibration

If an experimental total resistance is given, it REPLACES items 1-7 (provenance
"experimentally calibrated").

Operating states (interpretation documented in the scientific documentation):
    empty                -- chamber without inserts, no scaffold, no holder
    no_scaffold          -- scaffold holder / mesh present (holder_K), no scaffold
    with_scaffold        -- scaffold with nominal permeability
    reduced_permeability -- scaffold permeability multiplied by permeability_factor (<1),
                            e.g. due to cell growth / ECM deposition
    partially_blocked    -- open scaffold (or chamber) cross-section reduced by blocked_fraction
    blocked              -- flow path closed (Q = 0)
"""
from __future__ import annotations

import math
from typing import Literal

from pydantic import Field

from .elements import HydraulicComponent, QuantityType
from .fluids import FluidState
from .hydraulics import DEFAULT_FRICTION, FrictionSettings, friction_factor, k_sudden_contraction, k_sudden_expansion
from .scaffolds import Scaffold

ReactorState = Literal["empty", "no_scaffold", "with_scaffold", "reduced_permeability", "partially_blocked", "blocked"]


def _duct_dp(Q, d, L, fluid, fs, rough=1.5e-6):
    if L <= 0 or Q == 0:
        return 0.0
    A = math.pi * d**2 / 4
    v = Q / A
    Re = fluid.density * v * d / fluid.dynamic_viscosity
    f = friction_factor(Re, rough / d, fs)
    return f * L / d * fluid.density * v**2 / 2


class Bioreactor(HydraulicComponent):
    name: str = "bioreactor"
    state: ReactorState = "with_scaffold"
    chamber_volume_ml: float | None = Field(None, description="Override of the chamber volume [mL]")
    chamber_diameter_mm: float = Field(8.0, gt=0)
    chamber_height_mm: float = Field(10.0, gt=0)
    inlet_diameter_mm: float = Field(1.6, gt=0)
    outlet_diameter_mm: float = Field(1.6, gt=0)
    inlet_channel_length_mm: float = Field(5.0, ge=0)
    outlet_channel_length_mm: float = Field(5.0, ge=0)
    internal_resistance: float = Field(0.0, ge=0, description="Additional linear resistance [Pa s/m^3]")
    inlet_K: float | None = Field(None, description="Inlet loss coefficient (None = Borda-Carnot, ref. inlet velocity)")
    outlet_K: float | None = Field(None, description="Outlet loss coefficient (None = contraction estimate)")
    extra_K: float = Field(0.0, ge=0, description="Additional K referenced to inlet channel velocity")
    holder_K: float = Field(0.5, ge=0, description="Scaffold holder K for state 'no_scaffold' (ASSUMPTION)")
    scaffold: Scaffold = Field(default_factory=Scaffold)
    permeability_factor: float = Field(0.2, gt=0, le=1, description="k multiplier in state reduced_permeability")
    blocked_fraction: float = Field(0.5, ge=0, lt=1, description="Blocked area fraction in state partially_blocked")
    experimental_resistance: float | None = Field(
        None, description="Measured total resistance [Pa s/m^3]; replaces the internal model"
    )
    elevation_change_mm: float = 0.0
    provenance: str = "example geometry (ASSUMPTION)"

    # --- state helpers -------------------------------------------------------
    def has_scaffold(self) -> bool:
        return self.state in ("with_scaffold", "reduced_permeability", "partially_blocked")

    def k_factor(self) -> float:
        return self.permeability_factor if self.state == "reduced_permeability" else 1.0

    def area_factor(self) -> float:
        return 1.0 - self.blocked_fraction if self.state == "partially_blocked" else 1.0

    def is_closed(self) -> bool:
        return self.state == "blocked"

    def elevation_change_m(self) -> float:
        return self.elevation_change_mm * 1e-3

    # --- geometry --------------------------------------------------------------
    def chamber_area(self) -> float:
        return math.pi * (self.chamber_diameter_mm * 1e-3) ** 2 / 4

    def chamber_volume(self) -> float:
        if self.chamber_volume_ml:
            return self.chamber_volume_ml * 1e-6
        return self.chamber_area() * self.chamber_height_mm * 1e-3

    def volume_m3(self) -> float:
        v = self.chamber_volume()
        v += math.pi * (self.inlet_diameter_mm * 1e-3) ** 2 / 4 * self.inlet_channel_length_mm * 1e-3
        v += math.pi * (self.outlet_diameter_mm * 1e-3) ** 2 / 4 * self.outlet_channel_length_mm * 1e-3
        if self.has_scaffold():
            v -= self.scaffold.bulk_volume() * (1 - self.scaffold.porosity)
        return max(v, 0.0)

    def geometry_warnings(self) -> list[str]:
        w = []
        if self.has_scaffold():
            if self.scaffold.diameter_mm > self.chamber_diameter_mm + 1e-9:
                w.append(f"{self.name}: scaffold diameter larger than chamber diameter.")
            if self.scaffold.height_mm > self.chamber_height_mm + 1e-9:
                w.append(f"{self.name}: scaffold height larger than chamber height.")
            if self.scaffold.diameter_mm < self.chamber_diameter_mm - 1e-9:
                w.append(
                    f"{self.name}: scaffold diameter < chamber diameter. The model assumes the entire flow passes "
                    "through the scaffold (sealed periphery); bypass flow around the scaffold is NOT modelled."
                )
        return w

    # --- hydraulics -------------------------------------------------------------
    def loss_parts(self, Q: float, fluid: FluidState, fs: FrictionSettings = DEFAULT_FRICTION) -> dict:
        rho = fluid.density
        d_in, d_out = self.inlet_diameter_mm * 1e-3, self.outlet_diameter_mm * 1e-3
        D = self.chamber_diameter_mm * 1e-3
        v_in = Q / (math.pi * d_in**2 / 4)
        v_out = Q / (math.pi * d_out**2 / 4)
        parts = {}
        if self.experimental_resistance is not None:
            parts["experimental"] = self.experimental_resistance * Q
            return parts
        parts["inlet_channel"] = _duct_dp(Q, d_in, self.inlet_channel_length_mm * 1e-3, fluid, fs)
        K_in = self.inlet_K if self.inlet_K is not None else k_sudden_expansion(d_in, D)
        parts["inlet_expansion"] = K_in * rho * v_in**2 / 2
        free_len = self.chamber_height_mm * 1e-3
        if self.has_scaffold():
            free_len = max(free_len - self.scaffold.height_mm * 1e-3, 0.0)
            parts["scaffold"] = self.scaffold.loss(Q, fluid, self.k_factor(), self.area_factor())
        elif self.state == "no_scaffold":
            v_ch = Q / self.chamber_area()
            parts["holder"] = self.holder_K * rho * v_ch**2 / 2
        parts["chamber"] = _duct_dp(Q, D, free_len, fluid, fs)
        K_out = self.outlet_K if self.outlet_K is not None else k_sudden_contraction(D, d_out)
        parts["outlet_contraction"] = K_out * rho * v_out**2 / 2
        parts["outlet_channel"] = _duct_dp(Q, d_out, self.outlet_channel_length_mm * 1e-3, fluid, fs)
        parts["internal_resistance"] = self.internal_resistance * Q
        parts["extra_local"] = self.extra_K * rho * v_in**2 / 2
        return parts

    def loss(self, Q, fluid, fs=DEFAULT_FRICTION):
        return sum(self.loss_parts(Q, fluid, fs).values())

    def details(self, Q, fluid, fs=DEFAULT_FRICTION) -> dict:
        vol = self.volume_m3()
        out = {"state": self.state, "volume_m3": vol, "closed": self.is_closed()}
        if self.is_closed():
            out.update(Q=0.0, dp_total=math.nan, residence_time_s=math.inf)
            return out
        qa = abs(Q)
        parts = self.loss_parts(qa, fluid, fs)
        out.update({
            "Q": Q,
            "dp_total": math.copysign(sum(parts.values()), Q) if qa > 0 else 0.0,
            "dp_parts": parts,
            "R_secant": self.resistance_secant(Q, fluid, fs),
            "chamber_mean_velocity": qa / self.chamber_area(),
            "inlet_velocity": qa / (math.pi * (self.inlet_diameter_mm * 1e-3) ** 2 / 4),
            "residence_time_s": vol / qa if qa > 0 else math.inf,
            "quantity_type": QuantityType.CALIBRATED if self.experimental_resistance is not None else QuantityType.NUMERICAL,
        })
        if self.has_scaffold():
            sd = self.scaffold.details(qa, fluid, self.k_factor(), self.area_factor())
            out.update(sd)
        return out

    def model_warnings(self, Q: float, fluid: FluidState) -> list[str]:
        w = self.geometry_warnings()
        if self.has_scaffold() and not self.is_closed():
            d = self.scaffold.details(abs(Q), fluid, self.k_factor(), self.area_factor())
            if not d["darcy_valid"] and not self.scaffold.use_forchheimer:
                w.append(f"{self.name}: Re_k = {d['Re_permeability']:.2f} >= 1 -> Darcy's law questionable; enable Forchheimer.")
        return w
