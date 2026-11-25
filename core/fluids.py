"""Fluid property models.

Provenance of the property values (see documentation chapter 4):

* **Water** -- density: Tanaka et al. (2001) recommended density equation for SMOW,
  valid 0..40 degC (outside this range a warning is issued). Dynamic viscosity: Vogel-type
  empirical correlation mu = A 10^(B/(T-C)), A = 2.414e-5 Pa s, B = 247.8 K, C = 140 K.
  The test-suite checks the correlation against tabulated reference values for liquid
  water at 0.1 MPa (deviation < 1 % between 10 and 60 degC).
* **Physiological saline (0.9 % NaCl)** -- modelled as water multiplied by property
  ratios. The default ratios are ASSUMPTIONS (approximate values) and should be replaced
  by measured values.
* **Cell culture medium** -- there is no universal set of properties: viscosity depends
  strongly on serum content, supplements and temperature. The default ratios relative to
  water are explicit ASSUMPTIONS that must be overridden with measured values (e.g.
  rotational or capillary viscometry at 37 degC).
* **Custom fluid** -- user given values at a reference temperature, optionally scaled
  with the temperature dependence of water.

All overrides take precedence over correlations.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

from .units import ZERO_CELSIUS_K

FluidType = Literal["water", "saline", "culture_medium", "custom"]

# ---------------------------------------------------------------------------
# Water correlations
# ---------------------------------------------------------------------------
_TANAKA = dict(a1=-3.983035, a2=301.797, a3=522528.9, a4=69.34881, a5=999.974950)


def water_density(t_c: float) -> float:
    """Density of (air-free) water [kg/m^3], Tanaka et al. 2001, valid 0..40 degC."""
    a = _TANAKA
    return a["a5"] * (1.0 - (t_c + a["a1"]) ** 2 * (t_c + a["a2"]) / (a["a3"] * (t_c + a["a4"])))


def water_viscosity(t_c: float) -> float:
    """Dynamic viscosity of water [Pa s], Vogel-type empirical correlation."""
    T = t_c + ZERO_CELSIUS_K
    return 2.414e-5 * 10.0 ** (247.8 / (T - 140.0))


# Default property ratios relative to water (ASSUMPTIONS, to be replaced by measurements)
DEFAULT_RATIOS: dict[str, dict[str, float]] = {
    "water": {"density": 1.0, "viscosity": 1.0},
    "saline": {"density": 1.0046, "viscosity": 1.02},
    "culture_medium": {"density": 1.007, "viscosity": 1.05},
    "custom": {"density": 1.0, "viscosity": 1.0},
}

FLUID_LABELS = {
    "water": "Water",
    "saline": "Physiological saline (0.9 % NaCl)",
    "culture_medium": "Cell culture medium",
    "custom": "Custom fluid",
}


class FluidConfig(BaseModel):
    """User configuration of the working fluid."""

    fluid_type: FluidType = "culture_medium"
    name: str = "Cell culture medium (example values)"
    temperature_c: float = Field(37.0, description="Fluid temperature [degC]")
    temperature_dependent: bool = Field(
        True, description="Evaluate properties with temperature correlations (else constant values)"
    )
    density_ratio: float | None = Field(None, description="Override of rho_fluid / rho_water [-]")
    viscosity_ratio: float | None = Field(None, description="Override of mu_fluid / mu_water [-]")
    density_override: float | None = Field(None, description="Fixed density [kg/m^3]")
    dynamic_viscosity_override: float | None = Field(None, description="Fixed dynamic viscosity [Pa s]")
    kinematic_viscosity_override: float | None = Field(
        None, description="Fixed kinematic viscosity [m^2/s] (dynamic viscosity = nu*rho)"
    )
    # custom fluid definition
    custom_density: float = 1000.0
    custom_viscosity: float = 1.0e-3
    custom_reference_temperature_c: float = 20.0
    vapor_pressure_pa: float = Field(6_300.0, description="Vapour pressure (approx. water at 37 degC) [Pa]")
    notes: str = "Default culture-medium properties are ASSUMPTIONS (ratio to water); replace by measured values."


@dataclass(frozen=True)
class FluidState:
    """Evaluated fluid properties at a given temperature (SI units)."""

    name: str
    temperature_c: float
    density: float
    dynamic_viscosity: float
    vapor_pressure: float = 6_300.0
    provenance: dict = field(default_factory=dict)
    warnings: tuple = ()

    @property
    def kinematic_viscosity(self) -> float:
        return self.dynamic_viscosity / self.density


def evaluate_fluid(cfg: FluidConfig) -> FluidState:
    """Evaluate density and viscosity for the configured fluid and temperature."""
    warnings: list[str] = []
    prov: dict[str, str] = {}
    t = cfg.temperature_c
    t_eval = t if cfg.temperature_dependent else 37.0 if cfg.fluid_type != "custom" else cfg.custom_reference_temperature_c
    if cfg.temperature_dependent and not (0.0 <= t <= 40.0):
        warnings.append(
            f"Temperature {t:.1f} degC outside validity range 0..40 degC of the water density equation."
        )
    if cfg.temperature_dependent and not (0.0 <= t <= 100.0):
        warnings.append("Temperature outside liquid-water range; viscosity correlation invalid.")

    if cfg.fluid_type == "custom":
        t_ref = cfg.custom_reference_temperature_c
        if cfg.temperature_dependent:
            rho = cfg.custom_density * water_density(t) / water_density(t_ref)
            mu = cfg.custom_viscosity * water_viscosity(t) / water_viscosity(t_ref)
            prov["density"] = "user value scaled with water temperature dependence (assumption)"
            prov["viscosity"] = "user value scaled with water temperature dependence (assumption)"
        else:
            rho, mu = cfg.custom_density, cfg.custom_viscosity
            prov["density"] = prov["viscosity"] = "user value (constant)"
    else:
        ratios = DEFAULT_RATIOS[cfg.fluid_type]
        r_rho = cfg.density_ratio if cfg.density_ratio is not None else ratios["density"]
        r_mu = cfg.viscosity_ratio if cfg.viscosity_ratio is not None else ratios["viscosity"]
        rho = r_rho * water_density(t_eval)
        mu = r_mu * water_viscosity(t_eval)
        if cfg.fluid_type == "water":
            prov["density"] = "correlation (Tanaka et al. 2001)"
            prov["viscosity"] = "correlation (Vogel-type, empirical)"
        else:
            src_rho = "user ratio" if cfg.density_ratio is not None else "ASSUMED default ratio"
            src_mu = "user ratio" if cfg.viscosity_ratio is not None else "ASSUMED default ratio"
            prov["density"] = f"water correlation x {r_rho:g} ({src_rho})"
            prov["viscosity"] = f"water correlation x {r_mu:g} ({src_mu})"
            if cfg.fluid_type == "culture_medium" and cfg.viscosity_ratio is None and cfg.dynamic_viscosity_override is None:
                warnings.append(
                    "Culture-medium viscosity is an ASSUMPTION (1.05 x water). Measure the actual medium at 37 degC."
                )

    if cfg.density_override is not None:
        rho = cfg.density_override
        prov["density"] = "user override (constant)"
    if cfg.dynamic_viscosity_override is not None:
        mu = cfg.dynamic_viscosity_override
        prov["viscosity"] = "user override (constant)"
    elif cfg.kinematic_viscosity_override is not None:
        mu = cfg.kinematic_viscosity_override * rho
        prov["viscosity"] = "from user kinematic viscosity override"

    if rho <= 0 or mu <= 0:
        raise ValueError("Density and viscosity must be positive.")
    return FluidState(
        name=cfg.name or FLUID_LABELS[cfg.fluid_type],
        temperature_c=t,
        density=float(rho),
        dynamic_viscosity=float(mu),
        vapor_pressure=cfg.vapor_pressure_pa,
        provenance=prov,
        warnings=tuple(warnings),
    )


def preset(fluid_type: FluidType, temperature_c: float = 37.0) -> FluidConfig:
    names = {
        "water": "Water",
        "saline": "Physiological saline 0.9 % NaCl (approximate ratios)",
        "culture_medium": "Cell culture medium (ASSUMED ratios, replace by measurements)",
        "custom": "Custom fluid",
    }
    return FluidConfig(fluid_type=fluid_type, name=names[fluid_type], temperature_c=temperature_c)
