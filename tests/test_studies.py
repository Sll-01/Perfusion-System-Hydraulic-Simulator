import numpy as np
import pytest

from core.optimization import OptimizationProblem, default_variables, optimize_system
from core.sensitivity import ParameterSpec, expand_path, local_sensitivity, monte_carlo, sweep_1d, sweep_grid, latin_hypercube_study, tube_tolerance_study
from core.system import default_system
from scenarios import SCENARIO_BY_KEY


def _clean_single_tube():
    c = SCENARIO_BY_KEY["01_single_tube"].build()
    for t in (c.suction_tube, c.pump_outlet_tube, c.return_tube):
        t.inner_diameter_mm = 20.0
    return c


def test_wildcard_expansion(cfg):
    assert len(expand_path(cfg, "reactor_paths.*.throttle.opening_percent")) == 4


def test_sweep_1d_diameter_monotonic():
    df = sweep_1d(_clean_single_tube(), ParameterSpec(path="single_line.test_tube.inner_diameter_mm", low=1.0, high=3.0, n=9))
    assert (np.diff(df.pump_dp_pa) < 0).all()
    assert (df.converged == 1).all()


def test_local_sensitivity_laminar_exponents():
    c = _clean_single_tube()
    s = local_sensitivity(c, ["single_line.test_tube.inner_diameter_mm", "single_line.test_tube.length_m"], ["pump_dp_pa"])
    e = dict(zip(s.parameter, s.elasticity))
    assert e["single_line.test_tube.inner_diameter_mm"] == pytest.approx(-4.0, rel=0.01)
    assert e["single_line.test_tube.length_m"] == pytest.approx(1.0, rel=0.01)


def test_grid_and_lhs(cfg):
    df = sweep_grid(cfg, [ParameterSpec(path="bypass.throttle.opening_percent", low=20, high=100, n=3),
                          ParameterSpec(path="pump.flow_rate_ml_min", low=2, high=6, n=3)])
    assert len(df) == 9 and (df.converged == 1).all()
    df = latin_hypercube_study(cfg, [ParameterSpec(path="bypass.throttle.opening_percent", low=20, high=100),
                                     ParameterSpec(path="fluid.temperature_c", low=20, high=40)], 8)
    assert len(df) == 8


def test_monte_carlo_reproducible(cfg):
    a, sa = tube_tolerance_study(cfg, 0.05, 20, seed=3)
    b, sb = tube_tolerance_study(cfg, 0.05, 20, seed=3)
    assert np.allclose(a.cv_percent, b.cv_percent)
    assert sa.loc["cv_percent", "mean"] > 0
    # mass conservation in every sample (no bypass target): sum of paths = total
    q = a[[f"Q_reactor_{k}_ml_min" for k in range(1, 5)]].sum(axis=1) + a.Q_bypass_ml_min
    assert np.allclose(q, a.Q_total_ml_min, rtol=1e-9)


def test_temperature_study_viscosity(cfg):
    df = sweep_1d(cfg, ParameterSpec(path="fluid.temperature_c", low=20, high=40, n=5))
    assert (np.diff(df.pump_dp_pa) < 0).all()  # lower viscosity at higher T -> lower pressure (mode A)


def test_optimization_homogeneous():
    c = SCENARIO_BY_KEY["14_optimize_throttles"].build()
    prob = OptimizationProblem(objective="homogeneous", bypass_target_ml_min=1.0, variables=default_variables(c))
    res, c_opt = optimize_system(c, prob)
    assert res.success and res.feasible
    assert res.metrics["cv_percent"] < 0.5
    assert res.outputs["Q_bypass_ml_min"] == pytest.approx(1.0, rel=0.02)


def test_optimization_individual_targets_feasible():
    c = default_system(bypass=False)
    prob = OptimizationProblem(objective="individual_targets", reactor_targets_ml_min=[1.0, 1.0, 1.5, 1.5],
                               variables=default_variables(c, min_opening=2.0))
    res, _ = optimize_system(c, prob)
    assert res.feasible
    assert res.metrics["rmse_vs_target_ml_min"] < 0.01


def test_optimization_infeasible_explained():
    c = default_system(bypass=False)
    prob = OptimizationProblem(objective="individual_targets", reactor_targets_ml_min=[3, 3, 3, 3],
                               variables=default_variables(c), max_iterations=10)
    res, _ = optimize_system(c, prob)
    assert not res.feasible
    assert any("Mass conservation" in e for e in res.explanations)
    prob = OptimizationProblem(objective="homogeneous", max_pump_pressure_pa=10.0, variables=default_variables(c), max_iterations=5)
    res, _ = optimize_system(c, prob)
    assert not res.feasible
    assert any("Even with all throttles" in e for e in res.explanations)


def test_optimization_min_pressure_opens_throttles(cfg):
    prob = OptimizationProblem(objective="min_pump_pressure", variables=default_variables(cfg))
    res, _ = optimize_system(cfg, prob)
    assert all(v > 95 for v in res.x.values())
