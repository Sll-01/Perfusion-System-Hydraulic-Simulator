"""Porous scaffold model (spec. chapter 10).

Darcy's law (default):           dp = mu H Q / (k A)
Darcy-Forchheimer (optional):    dp = H (mu u / k + beta rho u^2),  u = Q / A

* superficial (Darcy) velocity   u   = Q / A
* mean interstitial (pore) vel.  u_p = u / eps    (Dupuit-Forchheimer relation)
* permeability Reynolds number   Re_k = rho u sqrt(k) / mu  -- used as indicator for the
  validity of Darcy's law (Re_k of order 1 or larger: inertial effects, use Forchheimer)

Shear stress estimate -- *explicitly documented pore model* (estimate only!)
--------------------------------------------------------------------------
Cylindrical-capillary (bundle-of-tubes) model: the pore space consists of straight,
parallel, non-connected cylindrical capillaries of equal radius r. Poiseuille flow in
each capillary gives  k = eps r^2 / 8  =>  r = sqrt(8 k / eps).  The mean wall shear stress
in a capillary is tau = 4 mu u_p / r, hence

    tau_pore = 4 mu (u/eps) / sqrt(8 k / eps) = sqrt(2) mu u / sqrt(k eps)

Tortuosity, pore-size distribution and local shear peaks are NOT represented; the value
is an order-of-magnitude estimate of the *mean* wall shear stress and must be labelled as
such. Micro-CT based CFD is required for local shear distributions.
"""
from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, Field

from .elements import QuantityType
from .fluids import FluidState


class Scaffold(BaseModel):
    name: str = "scaffold"
    diameter_mm: float = Field(8.0, gt=0)
    height_mm: float = Field(3.0, gt=0)
    area_override_mm2: float | None = None
    porosity: float = Field(0.8, gt=0, lt=1)
    permeability_m2: float = Field(1e-10, gt=0, description="Darcy permeability k (EXAMPLE VALUE)")
    use_forchheimer: bool = False
    forchheimer_beta_per_m: float | None = Field(None, description="Forchheimer coefficient beta [1/m]")
    forchheimer_cf: float = Field(0.55, description="Dimensionless Forchheimer C_F (beta = C_F/sqrt(k)), ASSUMPTION")
    pore_model: Literal["cylindrical_capillary"] = "cylindrical_capillary"
    provenance: str = "example parameters (ASSUMPTION)"

    def area(self) -> float:
        if self.area_override_mm2:
            return self.area_override_mm2 * 1e-6
        return math.pi * (self.diameter_mm * 1e-3) ** 2 / 4

    def bulk_volume(self) -> float:
        return self.area() * self.height_mm * 1e-3

    def beta(self) -> float:
        if self.forchheimer_beta_per_m is not None:
            return self.forchheimer_beta_per_m
        return self.forchheimer_cf / math.sqrt(self.permeability_m2)

    def loss(self, Q: float, fluid: FluidState, k_factor: float = 1.0, area_factor: float = 1.0) -> float:
        """Pressure loss across the scaffold (Q >= 0)."""
        k = self.permeability_m2 * k_factor
        A = self.area() * area_factor
        H = self.height_mm * 1e-3
        u = Q / A
        dp = H * fluid.dynamic_viscosity * u / k
        if self.use_forchheimer:
            beta = self.beta() / math.sqrt(k_factor)  # beta ~ 1/sqrt(k) for constant C_F
            dp += H * beta * fluid.density * u**2
        return dp

    def details(self, Q: float, fluid: FluidState, k_factor: float = 1.0, area_factor: float = 1.0) -> dict:
        k = self.permeability_m2 * k_factor
        A = self.area() * area_factor
        eps = self.porosity
        u = abs(Q) / A
        mu, rho = fluid.dynamic_viscosity, fluid.density
        Re_k = rho * u * math.sqrt(k) / mu
        r_pore = math.sqrt(8 * k / eps)
        return {
            "scaffold_area_m2": A,
            "effective_permeability_m2": k,
            "superficial_velocity": u,
            "pore_velocity_estimate": u / eps,
            "Re_permeability": Re_k,
            "darcy_valid": Re_k < 1.0,
            "dp_scaffold": self.loss(abs(Q), fluid, k_factor, area_factor),
            "equivalent_pore_radius_m": r_pore,
            "shear_stress_pore_model": math.sqrt(2) * mu * u / math.sqrt(k * eps),
            "shear_stress_model": "cylindrical capillary bundle (estimate)",
            "quantity_type_dp": QuantityType.ANALYTICAL if not self.use_forchheimer else QuantityType.EMPIRICAL,
            "quantity_type_shear": QuantityType.ESTIMATE,
        }
