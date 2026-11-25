"""Analytically verifiable reference cases (spec. chapter 23).

Each case documents: description, expected value (analytical), actual value (software),
tolerance and result. ``run_reference_cases()`` is executed by the test-suite and by
``tools/generate_verification_report.py`` which writes
``documentation/verification_report.md``.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .elements import LinearResistor
from .fluids import FluidConfig, FluidState, evaluate_fluid, water_density, water_viscosity
from .hydraulics import (
    friction_factor,
    friction_factor_colebrook,
    hagen_poiseuille_resistance,
    linear_taper_laminar_resistance,
    ellipse_laminar_resistance,
)
from .network import HydraulicNetwork
from .pumps import PumpConfig
from .scaffolds import Scaffold
from .solver import solve_network
from .tubing import Tube
from .units import ML_MIN, convert


@dataclass
class RefCase:
    id: str
    title: str
    description: str
    expected: float
    actual: float
    tolerance: float  # relative unless abs_tol
    unit: str
    abs_tol: bool = False
    classification: str = "analytical"

    @property
    def deviation(self) -> float:
        if self.abs_tol:
            return abs(self.actual - self.expected)
        return abs(self.actual - self.expected) / abs(self.expected) if self.expected != 0 else abs(self.actual)

    @property
    def passed(self) -> bool:
        return bool(np.isfinite(self.actual) and self.deviation <= self.tolerance)


WATER20 = FluidState("water 20 degC", 20.0, 998.2, 1.0016e-3)


def _single_tube_network(tube, pump: PumpConfig) -> HydraulicNetwork:
    net = HydraulicNetwork("single tube")
    net.add_node("R", kind="reservoir", fixed_pressure=0.0)
    net.add_node("a")
    net.add_node("b")
    net.add_edge("pump", "R", "a", pump, "pump")
    net.add_edge("tube", "a", "b", tube, "tube")
    net.add_edge("ret", "b", "R", LinearResistor(resistance=0.0), "resistor")
    return net


def _parallel_network(resistances, pump: PumpConfig):
    net = HydraulicNetwork("parallel")
    net.add_node("R", kind="reservoir", fixed_pressure=0.0)
    net.add_node("in")
    for i, r in enumerate(resistances):
        el = LinearResistor(resistance=r if r is not None else 1.0, closed=r is None)
        net.add_edge(f"r{i}", "in", "R", el, "resistor")
    net.add_edge("pump", "R", "in", pump, "pump")
    return net


def run_reference_cases() -> list[RefCase]:
    cases: list[RefCase] = []
    mu, rho = WATER20.dynamic_viscosity, WATER20.density
    d, L = 1.6e-3, 1.0
    Q = 5 * ML_MIN

    # 1 Hagen-Poiseuille vs tube model
    R_hp = 128 * mu * L / (math.pi * d**4)
    t = Tube(length_m=L, inner_diameter_mm=1.6, fittings=[], bends=[])
    cases.append(RefCase("V01", "Hagen-Poiseuille pressure drop",
                         "Tube L=1 m, d=1.6 mm, Q=5 mL/min, water 20 degC: dp = 128 mu L Q/(pi d^4)",
                         R_hp * Q, t.pressure_drop(Q, WATER20), 1e-10, "Pa"))
    # 2 R ~ L
    t2 = Tube(length_m=2 * L, inner_diameter_mm=1.6)
    cases.append(RefCase("V02", "Laminar resistance proportional to length", "R(2L)/R(L) = 2",
                         2.0, t2.pressure_drop(Q, WATER20) / t.pressure_drop(Q, WATER20), 1e-10, "-"))
    # 3 R ~ d^-4
    t3 = Tube(length_m=L, inner_diameter_mm=0.8)
    cases.append(RefCase("V03", "Laminar resistance ~ d^-4", "R(d/2)/R(d) = 16 (laminar)",
                         16.0, t3.pressure_drop(Q, WATER20) / t.pressure_drop(Q, WATER20), 1e-10, "-"))
    # 4 Reynolds number
    v = Q / (math.pi * d**2 / 4)
    cases.append(RefCase("V04", "Reynolds number", "Re = rho v d / mu",
                         rho * v * d / mu, t.details(Q, WATER20)["Re"], 1e-12, "-"))
    # 5 wall shear stress laminar
    cases.append(RefCase("V05", "Laminar wall shear stress", "tau_w = 32 mu Q / (pi d^3)",
                         32 * mu * Q / (math.pi * d**3), t.details(Q, WATER20)["wall_shear_stress"], 1e-10, "Pa"))
    # 6 Colebrook implicit equation satisfied
    Re, eps = 1e5, 1e-4
    f = float(friction_factor_colebrook(np.array([Re]), eps)[0])
    rhs = -2 * math.log10(eps / 3.7 + 2.51 / (Re * math.sqrt(f)))
    cases.append(RefCase("V06", "Colebrook-White residual", "1/sqrt(f) - RHS = 0 at Re=1e5, eps/d=1e-4",
                         0.0, 1 / math.sqrt(f) - rhs, 1e-9, "-", abs_tol=True, classification="numerical"))
    # 7 Blasius comparison smooth pipe (empirical)
    Re = 2e4
    cases.append(RefCase("V07", "Smooth turbulent friction vs. Blasius", "f_Colebrook(Re=2e4, smooth) vs 0.3164 Re^-0.25 (empirical, 3 %)",
                         0.3164 * Re**-0.25, float(friction_factor(Re, 0.0)), 0.03, "-", classification="empirical"))
    # 8 Darcy law
    sc = Scaffold(diameter_mm=8, height_mm=3, permeability_m2=1e-10, porosity=0.8)
    A = math.pi * 0.008**2 / 4
    cases.append(RefCase("V08", "Darcy flow through scaffold", "dp = mu H Q /(k A)",
                         mu * 0.003 * Q / (1e-10 * A), sc.loss(Q, WATER20), 1e-12, "Pa"))
    # 9 elliptical duct reduces to circle
    cases.append(RefCase("V09", "Elliptical duct, a=b", "R_ellipse(a=b=d/2) = R_HP",
                         R_hp, ellipse_laminar_resistance(mu, L, d / 2, d / 2), 1e-12, "Pa s/m^3"))
    # 10 linear taper reduces to cylinder
    cases.append(RefCase("V10", "Linear taper d1=d2", "R_taper(d,d) = R_HP",
                         R_hp, linear_taper_laminar_resistance(mu, L, d, d), 1e-12, "Pa s/m^3"))
    # 11 series resistances in network
    pumpA = PumpConfig(mode="A_constant_flow", flow_rate_ml_min=5.0)
    net = HydraulicNetwork("series")
    net.add_node("R", fixed_pressure=0.0)
    net.add_node("a")
    net.add_node("b")
    net.add_node("c")
    net.add_edge("pump", "R", "a", pumpA, "pump")
    net.add_edge("r1", "a", "b", LinearResistor(resistance=1e9), "resistor")
    net.add_edge("r2", "b", "c", LinearResistor(resistance=3e9), "resistor")
    net.add_edge("r3", "c", "R", LinearResistor(resistance=2e9), "resistor")
    s = solve_network(net, WATER20)
    cases.append(RefCase("V11", "Series resistances", "dp_pump = (R1+R2+R3) Q", 6e9 * Q,
                         s.node_pressures["a"] - s.node_pressures["R"], 1e-9, "Pa", classification="numerical"))
    # 12 parallel resistances, flow split
    net = _parallel_network([1e9, 2e9, 4e9], pumpA)
    s = solve_network(net, WATER20)
    G = 1 / 1e9 + 1 / 2e9 + 1 / 4e9
    cases.append(RefCase("V12", "Parallel resistances: flow share", "Q1/Q = (1/R1)/sum(1/Ri) = 4/7",
                         (1 / 1e9) / G, s.edge_flows["r0"] / Q, 1e-9, "-", classification="numerical"))
    cases.append(RefCase("V13", "Parallel resistances: pressure", "dp = Q / sum(1/Ri)",
                         Q / G, s.node_pressures["in"], 1e-9, "Pa", classification="numerical"))
    # 14 mass conservation
    cases.append(RefCase("V14", "Mass conservation at junction", "Q_pump - sum(Q_i) = 0",
                         0.0, (s.edge_flows["pump"] - sum(s.edge_flows[f"r{i}"] for i in range(3))) / Q, 1e-10, "-",
                         abs_tol=True, classification="numerical"))
    # 15 closed path
    net = _parallel_network([1e9, None, 1e9], pumpA)
    s = solve_network(net, WATER20)
    cases.append(RefCase("V15", "Blocked parallel path", "Q_blocked = 0, others share Q/2",
                         Q / 2, s.edge_flows["r0"], 1e-9, "m^3/s", classification="numerical"))
    cases.append(RefCase("V16", "Blocked parallel path: zero flow", "Q_blocked == 0 exactly",
                         0.0, s.edge_flows["r1"], 0.0, "m^3/s", abs_tol=True, classification="numerical"))
    # 17 identical parallel paths
    net = _parallel_network([3e9] * 4, pumpA)
    s = solve_network(net, WATER20)
    qs = np.array([s.edge_flows[f"r{i}"] for i in range(4)])
    cases.append(RefCase("V17", "Identical parallel paths", "max |Q_i - Q/4| / (Q/4) = 0",
                         0.0, float(np.max(np.abs(qs - Q / 4)) / (Q / 4)), 1e-10, "-", abs_tol=True, classification="numerical"))
    # 18 pump mode B reproduces mode A operating point
    tube = Tube(length_m=1.0, inner_diameter_mm=1.6)
    sA = solve_network(_single_tube_network(tube, pumpA), WATER20)
    dpA = sA.node_pressures["a"]
    pumpB = PumpConfig(mode="B_constant_pressure", pressure_difference_pa=dpA)
    sB = solve_network(_single_tube_network(tube, pumpB), WATER20)
    cases.append(RefCase("V18", "Pump mode B consistency", "Mode B with dp from mode A gives Q = 5 mL/min",
                         Q, sB.edge_flows["pump"], 1e-8, "m^3/s", classification="numerical"))
    # 19 mode C: linear pump curve dp = p0 (1 - Q/Qmax) intersect linear system R
    from .pumps import CurvePoint

    p0, qmax = 2000.0, 20.0
    pumpC = PumpConfig(mode="C_pump_curve", speed_rpm=10.0,
                       curve=[CurvePoint(speed_rpm=10.0, flow_ml_min=q, dp_pa=p0 * (1 - q / qmax)) for q in (0, 10, 20)])
    Rsys = 1e10
    net = HydraulicNetwork("C")
    net.add_node("R", fixed_pressure=0.0)
    net.add_node("a")
    net.add_edge("pump", "R", "a", pumpC, "pump")
    net.add_edge("r", "a", "R", LinearResistor(resistance=Rsys), "resistor")
    s = solve_network(net, WATER20)
    q_exp = p0 / (Rsys + p0 / (qmax * ML_MIN))
    cases.append(RefCase("V19", "Pump curve operating point", "Intersection of linear pump and system curve",
                         q_exp, s.edge_flows["pump"], 1e-8, "m^3/s", classification="numerical"))
    # 20 mode D with slip: Q = Qth - C dp, dp = R Q  => Q = Qth/(1 + C R)
    pumpD = PumpConfig(mode="D_displacement", speed_rpm=60.0, displacement_ml_per_rev=0.1, volumetric_efficiency=1.0,
                       slip_coefficient_ml_min_per_kpa=0.5)
    net = HydraulicNetwork("D")
    net.add_node("R", fixed_pressure=0.0)
    net.add_node("a")
    net.add_edge("pump", "R", "a", pumpD, "pump")
    net.add_edge("r", "a", "R", LinearResistor(resistance=Rsys), "resistor")
    s = solve_network(net, WATER20)
    qth = 60 / 60 * 0.1e-6
    C = 0.5 * ML_MIN / 1000
    cases.append(RefCase("V20", "Displacement pump with slip", "Q = Q_th / (1 + C_slip R)",
                         qth / (1 + C * Rsys), s.edge_flows["pump"], 1e-8, "m^3/s", classification="numerical"))
    # 21 hydrostatics
    tube_up = Tube(length_m=0.5, inner_diameter_mm=1.6, elevation_change_mm=200.0)
    sH = solve_network(_single_tube_network(tube_up, pumpA), WATER20)
    exp = tube_up.pressure_drop(Q, WATER20) + rho * 9.80665 * 0.2
    cases.append(RefCase("V21", "Hydrostatic head", "p_in - p_out = dp_friction + rho g dz",
                         exp, sH.node_pressures["a"] - sH.node_pressures["b"], 1e-9, "Pa", classification="numerical"))
    # 22 unit conversions
    cases.append(RefCase("V22", "Unit conversion mL/min -> m^3/s", "1 mL/min = 1/60e6 m^3/s", 1 / 60e6, convert(1, "mL/min", "m3/s"), 1e-15, "m^3/s"))
    cases.append(RefCase("V23", "Unit conversion mmHg -> Pa", "1 mmHg = 133.322387415 Pa", 133.322387415, convert(1, "mmHg", "Pa"), 1e-15, "Pa"))
    # 24 water properties (empirical correlation vs. tabulated reference values)
    cases.append(RefCase("V24", "Water viscosity 20 degC", "Tabulated reference 1.0016 mPa s (1 %)", 1.0016e-3, water_viscosity(20.0), 0.01, "Pa s",
                         classification="empirical"))
    cases.append(RefCase("V25", "Water viscosity 37 degC", "Tabulated reference 0.6913 mPa s (1.5 %)", 0.6913e-3, water_viscosity(37.0), 0.015,
                         "Pa s", classification="empirical"))
    cases.append(RefCase("V26", "Water density 20 degC", "Tabulated reference 998.21 kg/m^3 (0.01 %)", 998.21, water_density(20.0), 1e-4,
                         "kg/m^3", classification="empirical"))
    cases.append(RefCase("V27", "Water density 37 degC", "Tabulated reference 993.33 kg/m^3 (0.02 %)", 993.33, water_density(37.0), 2e-4,
                         "kg/m^3", classification="empirical"))
    # 28 constriction: 50 % diameter reduction over L_c -> laminar resistance x16 on that length
    from .constrictions import Constriction

    Lc = 0.1
    tc = Tube(length_m=1.0, inner_diameter_mm=1.6,
              constrictions=[Constriction(mode="continuous", taper="uniform", specification="diameter_reduction", degree_percent=50, length_mm=100)])
    exp = 128 * mu * (L - Lc) / (math.pi * d**4) * Q + 128 * mu * Lc / (math.pi * (d / 2) ** 4) * Q
    cases.append(RefCase("V28", "Uniform constriction (laminar)", "50 % diameter reduction over 0.1 m: R = R(0.9 m, d) + R(0.1 m, d/2)",
                         exp, tc.pressure_drop(Q, WATER20), 1e-9, "Pa"))
    # 29 area vs diameter reduction
    c_a = Constriction(specification="area_reduction", degree_percent=75)
    cases.append(RefCase("V29", "Area vs. diameter reduction", "75 % area reduction = 50 % diameter reduction",
                         d / 2, c_a.effective_circular_diameter(d), 1e-12, "m"))
    # 30 fluid evaluation (medium = ratio x water)
    fl = evaluate_fluid(FluidConfig(fluid_type="culture_medium", temperature_c=37, viscosity_ratio=1.1))
    cases.append(RefCase("V30", "Medium viscosity from user ratio", "mu = 1.1 mu_water(37 degC)", 1.1 * water_viscosity(37), fl.dynamic_viscosity, 1e-12, "Pa s"))
    return cases


def report_markdown(cases: list[RefCase]) -> str:
    lines = [
        "| ID | Test case | Description | Expected | Actual | Deviation | Tolerance | Class | Result |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for c in cases:
        dev = f"{c.deviation:.2e}" + ("" if c.abs_tol else " (rel.)")
        tol = f"{c.tolerance:.0e}" + ("" if c.abs_tol else " (rel.)")
        lines.append(f"| {c.id} | {c.title} | {c.description} | {c.expected:.6g} {c.unit} | {c.actual:.6g} {c.unit} | {dev} | {tol} | "
                     f"{c.classification} | {'PASS' if c.passed else 'FAIL'} |")
    return "\n".join(lines)
