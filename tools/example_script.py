"""Example: use the calculation library without the user interface.

    python tools/example_script.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.optimization import OptimizationProblem, default_variables, optimize_system  # noqa: E402
from core.sensitivity import ParameterSpec, sweep_1d, tube_tolerance_study  # noqa: E402
from core.simulation import run_simulation  # noqa: E402
from core.system import default_system  # noqa: E402

cfg = default_system(n_reactors=4, bypass=True)          # EXAMPLE parameters
cfg.pump.flow_rate_ml_min = 4.0
cfg.reactor_paths[2].reactor.scaffold.permeability_m2 = 2e-11

res = run_simulation(cfg)
print("converged:", res.ok, "| pump dp [Pa]:", round(res.pump["dp"], 2))
print(res.reactors[["reactor", "Q_ml_min", "dp_pa", "shear_stress_estimate_pa"]])
for w in res.warnings:
    print(w.level.upper(), w.message)

study = sweep_1d(cfg, ParameterSpec(path="bypass.throttle.opening_percent", low=5, high=100, n=10))
print(study[["bypass.throttle.opening_percent", "Q_bypass_ml_min", "cv_percent"]])

mc, summary = tube_tolerance_study(cfg, tolerance_mm=0.05, n_samples=100, seed=1)
print(summary.loc[["cv_percent", "Q_reactor_1_ml_min"]])

prob = OptimizationProblem(objective="homogeneous", bypass_target_ml_min=0.5, variables=default_variables(cfg))
opt, cfg_opt = optimize_system(cfg, prob)
print("feasible:", opt.feasible, opt.metrics, opt.x)
