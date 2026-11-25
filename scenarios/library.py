"""Predefined simulation scenarios (spec. chapter 18).

ALL PARAMETERS ARE CLEARLY MARKED EXAMPLE VALUES. They are chosen to be plausible for a
low-throughput perfusion system (tube ID 1.6 mm, flow rates of a few mL/min, scaffold
permeability 1e-10 m^2) but are NOT measured. Replace them by real data.

Each scenario provides a configuration and, where meaningful, a suggested study
(parameter sweep, comparison or optimisation) that the UI or a script can execute.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from core.bypass import BypassConfig
from core.constrictions import Constriction
from core.optimization import OptimizationProblem, default_variables
from core.sensitivity import ParameterSpec
from core.system import EXAMPLE_NOTE, PerfusionSystemConfig, default_system


@dataclass
class Scenario:
    key: str
    title: str
    description: str
    build: Callable[[], PerfusionSystemConfig]
    study: dict = field(default_factory=dict)  # {"type": "sweep_1d"|"compare"|"optimize"|"monte_carlo", ...}


def _single_tube() -> PerfusionSystemConfig:
    c = default_system(1, bypass=False)
    c.layout = "single_line"
    c.name = "Scenario 1 - single straight tube (example)"
    c.description = EXAMPLE_NOTE
    c.single_line.test_tube.length_m = 1.0
    c.single_line.test_tube.inner_diameter_mm = 1.6
    c.suction_tube.length_m = 0.05
    c.pump_outlet_tube.length_m = 0.05
    c.return_tube.length_m = 0.05
    for t in (c.suction_tube, c.pump_outlet_tube, c.return_tube, c.single_line.test_tube):
        t.fittings = []
    c.pump.flow_rate_ml_min = 5.0
    return c


def _single_constriction(degree: float = 50.0, blocked: bool = False) -> PerfusionSystemConfig:
    c = _single_tube()
    c.name = "Scenario 5 - completely blocked tube" if blocked else "Scenario 4 - partial tube constriction (example)"
    c.single_line.test_tube.constrictions = [
        Constriction(name="clamp", mode="blocked" if blocked else "local", specification="diameter_reduction",
                     degree_percent=100.0 if blocked else degree, length_mm=5.0, position_mm=500.0)
    ]
    if blocked:
        c.pump.mode = "B_constant_pressure"
        c.pump.pressure_difference_pa = 2000.0
    return c


def _four_identical() -> PerfusionSystemConfig:
    c = default_system(4, bypass=False)
    c.name = "Scenario 6 - four identical parallel bioreactors (example)"
    return c


def _different_lengths() -> PerfusionSystemConfig:
    c = _four_identical()
    c.name = "Scenario 7 - four reactors with different tube lengths (example)"
    for i, p in enumerate(c.reactor_paths):
        p.tube_to_reactor.length_m = [0.10, 0.15, 0.20, 0.30][i]
    return c


def _different_diameters() -> PerfusionSystemConfig:
    c = _four_identical()
    c.name = "Scenario 8 - four reactors with different tube diameters (example)"
    for i, p in enumerate(c.reactor_paths):
        p.tube_to_reactor.inner_diameter_mm = [1.5, 1.6, 1.7, 1.6][i]
        p.tube_to_collector.inner_diameter_mm = [1.6, 1.55, 1.6, 1.65][i]
    return c


def _different_permeability() -> PerfusionSystemConfig:
    c = _four_identical()
    c.name = "Scenario 9 - four reactors with different scaffold permeabilities (example)"
    for i, p in enumerate(c.reactor_paths):
        p.reactor.scaffold.permeability_m2 = [1e-10, 5e-11, 1e-11, 2e-12][i]
    return c


def _individual_throttles() -> PerfusionSystemConfig:
    c = _four_identical()
    c.name = "Scenario 10 - four reactors with individual throttle settings (example)"
    for i, p in enumerate(c.reactor_paths):
        p.throttle.opening_percent = [100.0, 70.0, 50.0, 30.0][i]
    return c


def _full_system() -> PerfusionSystemConfig:
    c = default_system(4, bypass=True)
    c.name = "Scenario 11 - complete system with adjustable bypass (example)"
    return c


def _blocked_reactor() -> PerfusionSystemConfig:
    c = _full_system()
    c.name = "Scenario 12 - completely blocked bioreactor (example)"
    c.reactor_paths[1].reactor.state = "blocked"
    return c


def _increasing_scaffold() -> PerfusionSystemConfig:
    c = _full_system()
    c.name = "Scenario 13 - increasing scaffold resistance in reactor 1 (example)"
    return c


def _optimisation_case() -> PerfusionSystemConfig:
    c = _different_permeability()
    c.bypass.enabled = True
    c.name = "Scenario 14 - optimisation of all five throttles (example)"
    return c


def _no_bypass() -> PerfusionSystemConfig:
    c = _full_system()
    c.bypass.enabled = False
    c.name = "Without bypass"
    return c


def _splitter_variants() -> list[tuple[str, PerfusionSystemConfig]]:
    out = []
    for mode in ("ideal", "symmetric", "asymmetric"):
        c = _full_system()
        c.splitter_in.mode = c.splitter_out.mode = mode
        if mode == "asymmetric":
            for i, p in enumerate(c.splitter_in.branch_ports):
                p.channel_length_mm = [6.0, 8.0, 10.0, 12.0][i % 4]
                p.K = [0.3, 0.5, 0.8, 1.2][i % 4]
        c.name = f"Splitter: {mode}"
        out.append((mode, c))
    c = _full_system()
    c.bypass.integration = "tee_pieces"
    c.name = "Splitter: 4-way + T-pieces for bypass"
    out.append(("tee", c))
    return out


SCENARIOS: list[Scenario] = [
    Scenario("01_single_tube", "1 - Single straight tube",
             "Reservoir -> pump -> 1 m tube (ID 1.6 mm) -> reservoir. Analytically verifiable (Hagen-Poiseuille).",
             _single_tube,
             {"type": "sweep_1d", "spec": ParameterSpec(path="pump.flow_rate_ml_min", low=0.5, high=20, n=20, label="Flow [mL/min]")}),
    Scenario("02_tube_diameters", "2 - Comparison of tube inner diameters",
             "Pressure drop of the single tube for inner diameters 0.8 ... 3.2 mm (dp ~ 1/d^4 in laminar flow).",
             _single_tube,
             {"type": "sweep_1d", "spec": ParameterSpec(path="single_line.test_tube.inner_diameter_mm", low=0.8, high=3.2, n=17, label="Tube ID [mm]")}),
    Scenario("03_tube_lengths", "3 - Comparison of tube lengths",
             "Pressure drop of the single tube for lengths 0.1 ... 2 m (dp ~ L).",
             _single_tube,
             {"type": "sweep_1d", "spec": ParameterSpec(path="single_line.test_tube.length_m", low=0.1, high=2.0, n=20, label="Tube length [m]")}),
    Scenario("04_partial_constriction", "4 - Partial tube constriction",
             "Local stenosis (5 mm long) in the single tube; degree 0 ... 95 % diameter reduction.",
             _single_constriction,
             {"type": "sweep_1d", "spec": ParameterSpec(path="single_line.test_tube.constrictions.0.degree_percent", low=0, high=95, n=20, label="Diameter reduction [%]")}),
    Scenario("05_blocked_tube", "5 - Completely blocked tube",
             "Pump mode B (2000 Pa) against a fully blocked tube: Q = 0 is obtained exactly. (Mode A would be reported as impossible.)",
             lambda: _single_constriction(blocked=True)),
    Scenario("06_four_identical", "6 - Four identical parallel bioreactors",
             "Symmetric system without bypass: identical flow distribution expected (verification case).", _four_identical),
    Scenario("07_different_lengths", "7 - Four reactors, different tube lengths",
             "Tube throttle->reactor 0.10/0.15/0.20/0.30 m.", _different_lengths),
    Scenario("08_different_diameters", "8 - Four reactors, different tube diameters",
             "Small diameter deviations (+/- 0.1 mm) and their effect on the distribution.", _different_diameters),
    Scenario("09_different_permeability", "9 - Four reactors, different scaffold permeabilities",
             "k = 1e-10, 5e-11, 1e-11, 2e-12 m^2.", _different_permeability),
    Scenario("10_individual_throttles", "10 - Four reactors with individual throttles",
             "Throttle openings 100/70/50/30 %. Note: opening != flow fraction.", _individual_throttles),
    Scenario("11_full_system_bypass", "11 - Complete system with adjustable bypass",
             "Standard configuration; study: bypass opening 5 ... 100 %.", _full_system,
             {"type": "sweep_1d", "spec": ParameterSpec(path="bypass.throttle.opening_percent", low=5, high=100, n=20, label="Bypass opening [%]")}),
    Scenario("12_blocked_reactor", "12 - Completely blocked bioreactor",
             "Reactor 2 blocked; redistribution to the other paths and the bypass.", _blocked_reactor),
    Scenario("13_increasing_scaffold_resistance", "13 - Increasing scaffold resistance",
             "Permeability of scaffold 1 decreasing from 1e-9 to 1e-13 m^2 (log sweep).", _increasing_scaffold,
             {"type": "sweep_1d", "spec": ParameterSpec(path="reactor_paths.0.reactor.scaffold.permeability_m2", low=1e-13, high=1e-9, n=25, scale="log", label="Permeability scaffold 1 [m^2]")}),
    Scenario("14_optimize_throttles", "14 - Optimisation of all five throttle settings",
             "Different scaffold permeabilities; homogeneous reactor flows with bypass target 1 mL/min (example targets).", _optimisation_case,
             {"type": "optimize", "problem": OptimizationProblem(objective="homogeneous", bypass_target_ml_min=1.0)}),
    Scenario("15_with_without_bypass", "15 - Comparison with and without bypass",
             "Same system with enabled vs. disabled bypass.", _full_system,
             {"type": "compare", "configs": lambda: [("with bypass", _full_system()), ("without bypass", _no_bypass())]}),
    Scenario("16_manufacturing_tolerances", "16 - Manufacturing tolerances",
             "Monte-Carlo: tube IDs in all reactor paths +/- 0.05 mm (normal, 2 sigma), 200 samples.", _four_identical,
             {"type": "monte_carlo", "specs": [ParameterSpec(path=f"reactor_paths.*.{t}.inner_diameter_mm", distribution="normal", tolerance=0.05)
                                                for t in ("tube_to_throttle", "tube_to_reactor", "tube_to_collector")],
              "n_samples": 200}),
    Scenario("17_splitter_variants", "17 - Comparison of splitter configurations",
             "Ideal vs. symmetric vs. asymmetric splitters vs. 4-way splitter with T-pieces for the bypass.", _full_system,
             {"type": "compare", "configs": _splitter_variants}),
]

SCENARIO_BY_KEY = {s.key: s for s in SCENARIOS}


def optimisation_problem_for(cfg: PerfusionSystemConfig, scenario: Scenario) -> OptimizationProblem:
    prob = scenario.study["problem"].model_copy(deep=True)
    prob.variables = default_variables(cfg)
    return prob
