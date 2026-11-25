"""Common base class for passive hydraulic components.

A passive component is described by its *loss characteristic* ``dp_loss(Q)`` (pressure
drop in flow direction caused by friction and local losses, Q >= 0) and optionally by a
geodetic height difference ``dz = z_out - z_in``. The pressure difference between inlet
and outlet node is

    p_in - p_out = sign(Q) * dp_loss(|Q|) + rho g dz

Reverse flow is handled by antisymmetric extension of the loss characteristic, i.e. the
same component characteristic is assumed for both flow directions (documented model
limitation for asymmetric parts such as nozzles or check valves).
"""
from __future__ import annotations

import math

from pydantic import BaseModel, ConfigDict

from .fluids import FluidState
from .hydraulics import DEFAULT_FRICTION, FrictionSettings


class QuantityType:
    """Classification of results (spec. chapter 24)."""

    ANALYTICAL = "analytical"
    NUMERICAL = "numerical"
    EMPIRICAL = "empirical estimate"
    ESTIMATE = "model-based estimate"
    CALIBRATED = "experimentally calibrated"
    VALIDATED = "experimentally validated"
    ASSUMPTION = "assumption"


class HydraulicComponent(BaseModel):
    """Base class of all passive components (pydantic model with physics methods)."""

    model_config = ConfigDict(validate_assignment=False, extra="ignore")

    name: str = "component"

    # --- to be overridden -----------------------------------------------------
    def loss(self, Q: float, fluid: FluidState, fs: FrictionSettings = DEFAULT_FRICTION) -> float:
        """Pressure loss [Pa] for a non-negative flow rate Q [m^3/s]."""
        raise NotImplementedError

    def is_closed(self) -> bool:
        return False

    def elevation_change_m(self) -> float:
        return 0.0

    def volume_m3(self) -> float:
        return 0.0

    def details(self, Q: float, fluid: FluidState, fs: FrictionSettings = DEFAULT_FRICTION) -> dict:
        return {}

    def quantity_type(self) -> str:
        return QuantityType.NUMERICAL

    # --- generic --------------------------------------------------------------
    def pressure_drop(self, Q: float, fluid: FluidState, fs: FrictionSettings = DEFAULT_FRICTION) -> float:
        """Signed loss for arbitrary flow direction (antisymmetric extension)."""
        if self.is_closed():
            return math.nan
        if Q >= 0:
            return self.loss(Q, fluid, fs)
        return -self.loss(-Q, fluid, fs)

    def hydrostatic(self, fluid: FluidState) -> float:
        from .units import G_STANDARD

        return fluid.density * G_STANDARD * self.elevation_change_m()

    def resistance_secant(self, Q: float, fluid: FluidState, fs: FrictionSettings = DEFAULT_FRICTION) -> float:
        """Secant hydraulic resistance R = dp/Q [Pa s/m^3]."""
        if self.is_closed():
            return math.inf
        if abs(Q) < 1e-30:
            return self.resistance_differential(0.0, fluid, fs)
        return self.pressure_drop(Q, fluid, fs) / Q

    def resistance_differential(self, Q: float, fluid: FluidState, fs: FrictionSettings = DEFAULT_FRICTION,
                                q_scale: float = 1e-8) -> float:
        """Differential hydraulic resistance d(dp)/dQ by central differences."""
        if self.is_closed():
            return math.inf
        h = 1e-6 * max(abs(Q), q_scale)
        if Q - h < 0 <= Q:  # one-sided near zero to stay in the Q >= 0 branch
            return (self.loss(Q + h, fluid, fs) - self.loss(max(Q, 0.0), fluid, fs)) / h
        return (self.pressure_drop(Q + h, fluid, fs) - self.pressure_drop(Q - h, fluid, fs)) / (2 * h)


class LinearResistor(HydraulicComponent):
    """Ideal linear resistor dp = R Q (e.g. experimentally determined resistance)."""

    resistance: float = 1e9  # Pa s/m^3
    closed: bool = False
    volume_ml: float = 0.0

    def loss(self, Q, fluid, fs=DEFAULT_FRICTION):
        return self.resistance * Q

    def is_closed(self):
        return self.closed

    def volume_m3(self):
        return self.volume_ml * 1e-6

    def details(self, Q, fluid, fs=DEFAULT_FRICTION):
        return {"dp_total": self.pressure_drop(Q, fluid, fs), "R_secant": self.resistance}


class IdealConnector(HydraulicComponent):
    """Loss-free connection (dp = 0)."""

    def loss(self, Q, fluid, fs=DEFAULT_FRICTION):
        return 0.0

    def details(self, Q, fluid, fs=DEFAULT_FRICTION):
        return {"dp_total": 0.0}

    def quantity_type(self):
        return QuantityType.ASSUMPTION


class SeriesComponent(HydraulicComponent):
    """Generic series connection of components (used for scripting / custom networks)."""

    parts: list = []

    def loss(self, Q, fluid, fs=DEFAULT_FRICTION):
        return sum(p.loss(Q, fluid, fs) for p in self.parts)

    def is_closed(self):
        return any(p.is_closed() for p in self.parts)

    def elevation_change_m(self):
        return sum(p.elevation_change_m() for p in self.parts)

    def volume_m3(self):
        return sum(p.volume_m3() for p in self.parts)
