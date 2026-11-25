"""Bypass line model (spec. chapter 11).

The bypass is a fifth parallel flow path between distributor and collector consisting of

    upstream tube  ->  bypass throttle  ->  downstream tube

Two physical integration variants are supported:

* ``integrated_port`` -- the splitters have an additional port (5-way); the bypass is
  connected via an additional splitter channel to both hubs.
* ``tee_pieces``      -- 4-way splitters plus one T-piece in the feed line (before the
  distributor) and one T-piece in the return line (after the collector). The T-pieces
  are modelled as junction nodes with run and branch loss coefficients.

Mass conservation Q_pump = sum(Q_reactor_i) + Q_bypass holds exactly at the junction
nodes for both variants (verified in the test-suite).
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .elements import HydraulicComponent, QuantityType
from .hydraulics import DEFAULT_FRICTION
from .splitters import SplitterPort
from .throttles import Throttle
from .tubing import Tube


class TeePiece(BaseModel):
    name: str = "T-piece"
    inner_diameter_mm: float = 1.6
    K_run: float = Field(0.4, ge=0, description="Run (straight-through) loss coefficient (ASSUMPTION)")
    K_branch: float = Field(1.0, ge=0, description="Branch loss coefficient (ASSUMPTION)")
    volume_ul: float = 15.0


class TeeChannel(HydraulicComponent):
    tee: TeePiece = Field(default_factory=TeePiece)
    branch: bool = False

    def loss(self, Q, fluid, fs=DEFAULT_FRICTION):
        import math

        d = self.tee.inner_diameter_mm * 1e-3
        v = Q / (math.pi * d**2 / 4)
        K = self.tee.K_branch if self.branch else self.tee.K_run
        return K * fluid.density * v**2 / 2

    def volume_m3(self):
        return self.tee.volume_ul * 1e-9 / 2  # split between run and branch element

    def details(self, Q, fluid, fs=DEFAULT_FRICTION):
        return {"Q": Q, "dp_total": self.pressure_drop(Q, fluid, fs), "volume_m3": self.volume_m3()}

    def quantity_type(self):
        return QuantityType.EMPIRICAL


class BypassConfig(BaseModel):
    enabled: bool = True
    integration: Literal["integrated_port", "tee_pieces"] = "integrated_port"
    tube_upstream: Tube = Field(default_factory=lambda: Tube(name="bypass tube (splitter 1 -> throttle)", length_m=0.15))
    throttle: Throttle = Field(default_factory=lambda: Throttle(name="bypass throttle", opening_percent=30.0))
    tube_downstream: Tube = Field(default_factory=lambda: Tube(name="bypass tube (throttle -> splitter 2)", length_m=0.15))
    splitter_port_in: SplitterPort = Field(default_factory=lambda: SplitterPort(name="bypass port"))
    splitter_port_out: SplitterPort = Field(default_factory=lambda: SplitterPort(name="bypass port"))
    tee_in: TeePiece = Field(default_factory=lambda: TeePiece(name="T-piece feed"))
    tee_out: TeePiece = Field(default_factory=lambda: TeePiece(name="T-piece return"))
    extra_resistance: float = Field(0.0, ge=0, description="Additional linear resistance [Pa s/m^3]")
