"""Tube constriction / blockage module (spec. chapter 6).

Scenarios
---------
* ``open``                 -- no constriction (component has no effect)
* ``partial_compression``  -- tube squeezed over a length (e.g. clamp, roller): the cross
                              section is approximated as an ELLIPSE with conserved
                              perimeter (inextensible wall). Simplified substitute model.
* ``local``                -- short local stenosis with sudden contraction/expansion
* ``continuous``           -- constriction over a defined length, either uniform reduced
                              diameter or linear taper from the nominal to the minimum
                              diameter
* ``kink``                 -- kinked tube: CALIBRATABLE equivalent model consisting of an
                              additional loss coefficient and an optional equivalent
                              reduced diameter. Parameters must be determined
                              experimentally; defaults are placeholders.
* ``blocked``              -- complete blockage; the flow path is closed (Q = 0), which
                              the network solver treats exactly (no huge-resistance trick).

Degree specification (explicitly distinguished!)
-------------------------------------------------
* ``diameter_reduction``  s_d = 1 - d_eff/D           (for an ellipse: reduction of the small axis)
* ``area_reduction``      s_A = 1 - A_eff/A           (=> d_eff = D sqrt(1 - s_A) for circles)
* ``effective_diameter``  d_eff given directly
* ``effective_area``      A_eff given directly

Note: a 50 % diameter reduction corresponds to a 75 % area reduction for a circle and
increases the laminar resistance of the constricted length by a factor 16.
"""
from __future__ import annotations

import math
from typing import Literal

import numpy as np
from pydantic import BaseModel, Field
from scipy.optimize import brentq

from .fluids import FluidState
from .hydraulics import (
    DEFAULT_FRICTION,
    FrictionSettings,
    ellipse_laminar_resistance,
    ellipse_perimeter,
    flow_regime,
    friction_factor,
    k_sudden_contraction,
    k_sudden_expansion,
)

ConstrictionMode = Literal["open", "partial_compression", "local", "continuous", "kink", "blocked"]
DegreeSpec = Literal["diameter_reduction", "area_reduction", "effective_diameter", "effective_area"]

BLOCKED_THRESHOLD = 99.999  # percent; above this the path is treated as closed


class Constriction(BaseModel):
    name: str = "constriction"
    mode: ConstrictionMode = "local"
    specification: DegreeSpec = "diameter_reduction"
    degree_percent: float = Field(50.0, ge=0.0, le=100.0)
    effective_diameter_mm: float | None = None
    effective_area_mm2: float | None = None
    length_mm: float = Field(5.0, ge=0.0, description="Axial length of the constricted section")
    position_mm: float = Field(0.0, ge=0.0, description="Distance of constriction start from tube inlet")
    geometry: Literal["circular", "elliptical"] = "circular"
    taper: Literal["uniform", "linear"] = "uniform"
    include_transition_losses: bool | None = Field(
        None, description="Sudden contraction/expansion losses (default: True for 'local', else False)"
    )
    extra_K: float = Field(0.0, ge=0.0, description="Additional local loss coefficient (ref. nominal tube velocity)")
    kink_K: float = Field(2.0, ge=0.0, description="Kink equivalent K (PLACEHOLDER, calibrate experimentally)")
    n_slices: int = 40

    # ------------------------------------------------------------------
    def is_blocked(self) -> bool:
        if self.mode == "blocked":
            return True
        if self.mode in ("open",):
            return False
        if self.specification in ("diameter_reduction", "area_reduction"):
            return self.degree_percent >= BLOCKED_THRESHOLD
        if self.specification == "effective_diameter":
            return (self.effective_diameter_mm or 0.0) <= 0.0
        return (self.effective_area_mm2 or 0.0) <= 0.0

    def is_active(self) -> bool:
        if self.mode == "open":
            return False
        if self.mode == "kink":
            return True
        return self.is_blocked() or self.remaining_area_fraction(1.0) < 1.0 - 1e-12

    def transition_losses(self) -> bool:
        if self.include_transition_losses is not None:
            return self.include_transition_losses
        return self.mode == "local"

    # --- geometry ------------------------------------------------------
    def effective_circular_diameter(self, D: float) -> float:
        """Equivalent circular diameter of the narrowest section [m] (circular model)."""
        s = self.degree_percent / 100.0
        if self.mode in ("open",):
            return D
        if self.specification == "diameter_reduction":
            return D * (1.0 - s)
        if self.specification == "area_reduction":
            return D * math.sqrt(max(1.0 - s, 0.0))
        if self.specification == "effective_diameter":
            return min((self.effective_diameter_mm or 0.0) * 1e-3, D)
        return min(math.sqrt(4.0 * (self.effective_area_mm2 or 0.0) * 1e-6 / math.pi), D)

    def remaining_area_fraction(self, D: float) -> float:
        a, b = self.ellipse_axes(D) if self.geometry == "elliptical" else (None, None)
        if a is not None:
            return (math.pi * a * b) / (math.pi * D**2 / 4)
        return (self.effective_circular_diameter(D) / D) ** 2

    def ellipse_axes(self, D: float) -> tuple[float, float]:
        """Semi-axes (a >= b) of the squeezed tube with conserved perimeter pi*D.

        * diameter_reduction: small axis 2b = D (1 - s_d)
        * area_reduction / effective area: b chosen such that pi a b = A_eff
        """
        R = D / 2.0
        P = math.pi * D
        if self.specification in ("diameter_reduction", "effective_diameter"):
            if self.specification == "diameter_reduction":
                b = R * (1.0 - self.degree_percent / 100.0)
            else:
                b = min((self.effective_diameter_mm or 0.0) * 1e-3 / 2.0, R)
            b = max(b, 1e-12 * R)
            a = brentq(lambda a_: ellipse_perimeter(a_, b) - P, b, P / 2.0 + R) if b < R else R
            return a, b
        # area based
        if self.specification == "area_reduction":
            A_eff = math.pi * R**2 * (1.0 - self.degree_percent / 100.0)
        else:
            A_eff = min((self.effective_area_mm2 or 0.0) * 1e-6, math.pi * R**2)
        if A_eff >= math.pi * R**2 * (1 - 1e-12):
            return R, R

        def area_of_b(b_):
            a_ = brentq(lambda a__: ellipse_perimeter(a__, b_) - P, b_, P / 2.0 + R) if b_ < R else R
            return math.pi * a_ * b_ - A_eff, a_

        b = brentq(lambda b_: area_of_b(b_)[0], 1e-9 * R, R * (1 - 1e-12))
        return area_of_b(b)[1], b

    # --- hydraulics ------------------------------------------------------
    def _section_dp(self, Q, fluid: FluidState, fs: FrictionSettings, D: float, L: float, rough: float):
        """Frictional pressure drop over the constricted length (positive Q)."""
        rho, mu = fluid.density, fluid.dynamic_viscosity
        if L <= 0:
            return 0.0
        if self.geometry == "elliptical" and self.mode != "kink":
            a, b = self.ellipse_axes(D)
            A = math.pi * a * b
            Dh = 4 * A / ellipse_perimeter(a, b)
            v = Q / A
            Re = rho * v * Dh / mu
            if Re < fs.re_laminar:
                return ellipse_laminar_resistance(mu, L, a, b) * Q  # exact laminar solution
            f = friction_factor(Re, rough / Dh, fs)
            return f * L / Dh * rho * v**2 / 2
        d_min = self.effective_circular_diameter(D)
        if self.mode == "continuous" and self.taper == "linear":
            # numerical integration over slices (midpoint rule), vectorised
            n = max(self.n_slices, 4)
            x = (np.arange(n) + 0.5) / n
            d = D + (d_min - D) * x
            A = np.pi * d**2 / 4
            v = Q / A
            Re = rho * v * d / mu
            f = np.atleast_1d(friction_factor(Re, rough / d, fs))
            return float(np.sum(f * (L / n) / d * rho * v**2 / 2))
        A = math.pi * d_min**2 / 4
        v = Q / A
        Re = rho * v * d_min / mu
        f = friction_factor(Re, rough / d_min, fs)
        return f * L / d_min * rho * v**2 / 2

    def loss(self, Q: float, fluid: FluidState, fs: FrictionSettings, D: float, roughness: float = 0.0) -> float:
        """Total pressure loss caused by the constricted section [Pa] (Q >= 0).

        The loss replaces the friction of the *nominal* tube over ``length_mm``; the tube
        model subtracts this length from its straight friction length (no double counting).
        """
        if not self.is_active():
            return 0.0
        rho = fluid.density
        A_nom = math.pi * D**2 / 4
        v_nom = Q / A_nom
        L = self.length_mm * 1e-3
        dp = 0.0
        if self.mode == "kink":
            # equivalent model: reduced diameter over the kink length + calibratable K
            if self.degree_percent > 0 or self.specification in ("effective_diameter", "effective_area"):
                dp += self._section_dp(Q, fluid, fs, D, L, roughness)
            else:
                dp += _nominal_friction(Q, fluid, fs, D, L, roughness)
            dp += self.kink_K * rho * v_nom**2 / 2
        else:
            dp += self._section_dp(Q, fluid, fs, D, L, roughness)
            if self.transition_losses():
                frac = self.remaining_area_fraction(D)
                d_eq = D * math.sqrt(frac)
                v_c = Q / (A_nom * frac)
                dp += k_sudden_contraction(D, d_eq) * rho * v_c**2 / 2  # ref. downstream velocity
                dp += k_sudden_expansion(d_eq, D) * rho * v_c**2 / 2  # ref. upstream velocity
        dp += self.extra_K * rho * v_nom**2 / 2
        return dp

    def details(self, Q: float, fluid: FluidState, D: float) -> dict:
        frac = self.remaining_area_fraction(D) if not self.is_blocked() else 0.0
        d_eq = D * math.sqrt(frac)
        out = {
            "mode": self.mode,
            "remaining_area_fraction": frac,
            "area_reduction_percent": 100 * (1 - frac),
            "equivalent_diameter_m": d_eq,
            "blocked": self.is_blocked(),
            "model_type": "simplified substitute model" if self.mode in ("partial_compression", "kink") or self.geometry == "elliptical" else "1D model",
        }
        if frac > 0:
            v = Q / (math.pi * d_eq**2 / 4)
            out["velocity_in_constriction_m_s"] = v
            out["Re_in_constriction"] = fluid.density * v * d_eq / fluid.dynamic_viscosity
            out["regime_in_constriction"] = flow_regime(out["Re_in_constriction"])
        if self.geometry == "elliptical" and not self.is_blocked():
            a, b = self.ellipse_axes(D)
            out["ellipse_semi_axes_m"] = (a, b)
        return out


def _nominal_friction(Q, fluid, fs, D, L, rough):
    A = math.pi * D**2 / 4
    v = Q / A
    Re = fluid.density * v * D / fluid.dynamic_viscosity
    f = friction_factor(Re, rough / D, fs)
    return f * L / D * fluid.density * v**2 / 2
