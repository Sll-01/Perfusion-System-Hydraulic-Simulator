"""Flow splitter (distributor) and collector models (spec. chapter 8).

A splitter is represented as a *hub node* plus one channel element per port:

    common port channel  :  inlet  -> hub      (distributor)   /  hub -> outlet (collector)
    branch port channel k:  hub    -> port k   (distributor)   /  port k -> hub (collector)

Each channel element consists of an internal circular channel (length, diameter,
Darcy-Weisbach), a local loss coefficient K (referenced to the channel velocity) and an
optional additional linear resistance. Geometry-dependent junction losses, which in
reality depend on the flow ratio between the branches, are NOT predicted -- they are
represented by user-adjustable / experimentally calibratable K values. The model is a
1D lumped-parameter network and does not replace 3D CFD of the splitter.

Modes
-----
* ``symmetric``              all branch ports use the parameters of branch_ports[0]
* ``asymmetric``             each branch port has its own geometry
* ``ideal``                  loss-free distributor (all channel losses = 0)
* ``individual_resistances`` channels described only by user-given linear resistances
"""
from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, Field

from .elements import HydraulicComponent, QuantityType
from .fluids import FluidState
from .hydraulics import DEFAULT_FRICTION, FrictionSettings, friction_factor

SplitterMode = Literal["symmetric", "asymmetric", "ideal", "individual_resistances"]


class SplitterPort(BaseModel):
    name: str = "port"
    port_diameter_mm: float = Field(1.6, gt=0)
    channel_diameter_mm: float = Field(1.6, gt=0)
    channel_length_mm: float = Field(8.0, ge=0)
    K: float = Field(0.5, ge=0, description="Local loss coefficient (ASSUMPTION / calibrate)")
    resistance: float = Field(0.0, ge=0, description="Additional / individual linear resistance [Pa s/m^3]")
    angle_deg: float = 90.0
    position: tuple[float, float] = (0.0, 0.0)


class SplitterChannel(HydraulicComponent):
    """Hydraulic element of a single splitter channel (built from a SplitterPort)."""

    port: SplitterPort = Field(default_factory=SplitterPort)
    mode: SplitterMode = "symmetric"

    def loss(self, Q, fluid: FluidState, fs: FrictionSettings = DEFAULT_FRICTION):
        if self.mode == "ideal":
            return 0.0
        if self.mode == "individual_resistances":
            return self.port.resistance * Q
        d = self.port.channel_diameter_mm * 1e-3
        A = math.pi * d**2 / 4
        v = Q / A
        Re = fluid.density * v * d / fluid.dynamic_viscosity
        L = self.port.channel_length_mm * 1e-3
        dp = 0.0
        if L > 0 and Q > 0:
            f = friction_factor(Re, 1.5e-6 / d, fs)
            dp += f * L / d * fluid.density * v**2 / 2
        dp += self.port.K * fluid.density * v**2 / 2
        dp += self.port.resistance * Q
        return dp

    def volume_m3(self):
        d = self.port.channel_diameter_mm * 1e-3
        return math.pi * d**2 / 4 * self.port.channel_length_mm * 1e-3

    def details(self, Q, fluid, fs=DEFAULT_FRICTION):
        d = self.port.channel_diameter_mm * 1e-3
        v = abs(Q) / (math.pi * d**2 / 4)
        return {"Q": Q, "dp_total": self.pressure_drop(Q, fluid, fs), "v": v,
                "Re": fluid.density * v * d / fluid.dynamic_viscosity, "volume_m3": self.volume_m3(),
                "R_secant": self.resistance_secant(Q, fluid, fs)}

    def quantity_type(self):
        return QuantityType.ASSUMPTION if self.mode == "ideal" else QuantityType.EMPIRICAL


class Splitter(BaseModel):
    name: str = "4-way splitter"
    role: Literal["distributor", "collector"] = "distributor"
    geometry: str = "radial manifold (example)"
    mode: SplitterMode = "symmetric"
    common_port: SplitterPort = Field(
        default_factory=lambda: SplitterPort(name="common", channel_length_mm=5.0, K=0.5)
    )
    branch_ports: list[SplitterPort] = Field(default_factory=lambda: [SplitterPort(name=f"port {i+1}") for i in range(4)])
    hub_volume_ul: float = Field(50.0, ge=0)
    provenance: str = "example geometry; K values are ASSUMPTIONS to be calibrated"

    def port(self, i: int) -> SplitterPort:
        """Effective parameters of branch port i (0-based) according to the mode."""
        if not self.branch_ports:
            return SplitterPort(name=f"port {i+1}")
        if self.mode == "symmetric":
            p = self.branch_ports[0].model_copy()
            p.name = f"port {i+1}"
            return p
        if i < len(self.branch_ports):
            return self.branch_ports[i]
        return self.branch_ports[-1].model_copy(update={"name": f"port {i+1}"})

    def ensure_ports(self, n: int) -> None:
        while len(self.branch_ports) < n:
            src = self.branch_ports[-1] if self.branch_ports else SplitterPort()
            self.branch_ports.append(src.model_copy(update={"name": f"port {len(self.branch_ports)+1}"}))

    def channel(self, i: int | None) -> SplitterChannel:
        port = self.common_port if i is None else self.port(i)
        return SplitterChannel(name=f"{self.name} {port.name}", port=port, mode=self.mode)

    def hub_volume(self) -> float:
        return self.hub_volume_ul * 1e-9
