import math

import numpy as np
import pytest

from core.elements import LinearResistor
from core.network import HydraulicNetwork
from core.pumps import CurvePoint, PumpConfig
from core.simulation import run_simulation
from core.solver import SolverError, solve_network
from core.system import build_network, default_system, set_reactor_count
from core.units import ML_MIN


def _assert_mass_balance(res, rtol=1e-9):
    q = res.solver.edge_flows
    Qp = q["pump"]
    paths = sum(q[f"reactor_{k+1}"] for k in range(res.config.n_reactors))
    if res.config.bypass.enabled:
        paths += q["bypass_throttle"]
    assert Qp == pytest.approx(paths, rel=rtol, abs=1e-18)
    assert res.solver.max_mass_residual < 1e-9 * res.solver.q_scale


def test_default_system_converges_and_mass_balance(cfg):
    res = run_simulation(cfg)
    assert res.ok
    _assert_mass_balance(res)
    assert res.solver.max_pressure_residual < 1e-5


def test_symmetric_distribution(cfg):
    res = run_simulation(cfg)
    q = res.reactor_flows()
    assert np.max(np.abs(q - q.mean())) / q.mean() < 1e-10


def test_asymmetric_distribution_follows_resistance(cfg):
    cfg.reactor_paths[2].tube_to_reactor.length_m *= 3
    res = run_simulation(cfg)
    q = res.reactor_flows()
    assert q[2] < q[0]
    assert q[0] == pytest.approx(q[1], rel=1e-10) and q[0] == pytest.approx(q[3], rel=1e-10)
    _assert_mass_balance(res)


def test_increasing_path_resistance_redistributes_flow(cfg):
    res0 = run_simulation(cfg)
    cfg.reactor_paths[0].reactor.scaffold.permeability_m2 *= 0.01
    res1 = run_simulation(cfg)
    assert res1.reactor_flows()[0] < res0.reactor_flows()[0]
    assert all(res1.reactor_flows()[1:] > res0.reactor_flows()[1:])
    assert res1.bypass["Q"] > res0.bypass["Q"]
    assert res1.pump["dp"] > res0.pump["dp"]  # mode A: higher system resistance -> higher pressure


def test_pressure_drop_non_negative_in_flow_direction(cfg):
    res = run_simulation(cfg)
    passive = res.edges[(res.edges.kind != "pump") & (~res.edges.closed)]
    sgn = np.sign(passive.Q_m3s) * passive.dp_pa
    assert (sgn >= -1e-9).all()


def test_blocked_reactor_zero_flow(cfg):
    cfg.reactor_paths[1].reactor.state = "blocked"
    res = run_simulation(cfg)
    assert res.ok
    assert res.solver.edge_flows["reactor_2"] == 0.0
    _assert_mass_balance(res)


def test_closed_throttle_zero_flow(cfg):
    cfg.reactor_paths[0].throttle.opening_percent = 0.0
    res = run_simulation(cfg)
    assert res.ok
    assert abs(res.solver.edge_flows["reactor_1"]) < 1e-20
    assert res.solver.edge_flows["throttle_1"] == 0.0
    # the dead-end reactor section takes the collector pressure (no flow -> no pressure drop)
    p = res.solver.node_pressures
    assert p["rx1_in"] == pytest.approx(p["S2"], abs=1e-6)


def test_isolated_section_reported(cfg):
    cfg.reactor_paths[0].throttle.opening_percent = 0.0
    cfg.reactor_paths[0].reactor.state = "blocked"
    res = run_simulation(cfg)
    assert res.ok
    assert "thr1_out" in res.solver.isolated_nodes
    assert math.isnan(res.solver.node_pressures["thr1_out"])


def test_bypass_disabled_vs_enabled(cfg):
    on = run_simulation(cfg)
    cfg2 = cfg.model_copy(deep=True)
    cfg2.bypass.enabled = False
    off = run_simulation(cfg2)
    assert "bypass_throttle" not in off.solver.edge_flows
    assert off.reactor_flows().sum() == pytest.approx(cfg.pump.flow_rate_ml_min * ML_MIN, rel=1e-10)
    assert on.reactor_flows().sum() < off.reactor_flows().sum()
    assert off.pump["dp"] > on.pump["dp"]  # additional parallel path lowers the system resistance
    _assert_mass_balance(on)
    _assert_mass_balance(off)


def test_bypass_tee_variant(cfg):
    cfg.bypass.integration = "tee_pieces"
    res = run_simulation(cfg)
    assert res.ok
    _assert_mass_balance(res)
    assert res.bypass["Q"] > 0


def test_bypass_opening_monotonic(cfg):
    fr = []
    for op in [10, 30, 60, 100]:
        cfg.bypass.throttle.opening_percent = op
        fr.append(run_simulation(cfg).bypass["fraction"])
    assert all(np.diff(fr) > 0)


def test_throttle_half_open_is_not_half_flow(cfg):
    cfg.bypass.enabled = False
    q_full = run_simulation(cfg).reactor_flows()[0]
    cfg.reactor_paths[0].throttle.opening_percent = 50
    q_half = run_simulation(cfg).reactor_flows()[0]
    assert q_half < q_full
    assert abs(q_half / q_full - 0.5) > 0.05


@pytest.mark.parametrize("mode", ["A_constant_flow", "B_constant_pressure", "C_pump_curve", "D_displacement"])
def test_pump_modes(cfg, mode):
    cfg.pump.mode = mode
    res = run_simulation(cfg)
    assert res.ok
    _assert_mass_balance(res)
    assert res.pump["Q"] > 0 and res.pump["dp"] > 0
    assert res.pump["P_hyd"] == pytest.approx(res.pump["Q"] * res.pump["dp"])


def test_mode_b_reproduces_mode_a(cfg):
    a = run_simulation(cfg)
    cfg.pump.mode = "B_constant_pressure"
    cfg.pump.pressure_difference_pa = a.pump["dp"]
    b = run_simulation(cfg)
    assert b.pump["Q"] == pytest.approx(a.pump["Q"], rel=1e-7)
    assert np.allclose(a.reactor_flows(), b.reactor_flows(), rtol=1e-7)


def test_mode_c_operating_point_on_curve(cfg):
    cfg.pump.mode = "C_pump_curve"
    res = run_simulation(cfg)
    h, _ = cfg.pump.curve_head(res.pump["Q"])
    assert res.pump["dp"] == pytest.approx(h, rel=1e-8)


def test_mode_d_theoretical_flow_and_slip(cfg):
    cfg.pump.mode = "D_displacement"
    cfg.pump.volumetric_efficiency = 1.0
    res = run_simulation(cfg)
    assert res.pump["Q"] == pytest.approx(cfg.pump.theoretical_flow(), rel=1e-9)
    cfg.pump.slip_coefficient_ml_min_per_kpa = 1.0
    res2 = run_simulation(cfg)
    assert res2.pump["Q"] < res.pump["Q"]


def test_impossible_configuration_detected(cfg):
    cfg.bypass.enabled = False
    for p in cfg.reactor_paths:
        p.throttle.opening_percent = 0
    res = run_simulation(cfg)
    assert not res.ok
    assert any("impossible" in w.message for w in res.warnings if w.level == "error")
    cfg.pump.mode = "B_constant_pressure"
    res = run_simulation(cfg)
    assert res.ok and res.pump["Q"] == 0.0


def test_excess_pressure_warning(cfg):
    cfg.pump.flow_rate_ml_min = 500
    res = run_simulation(cfg)
    assert any(w.level == "error" and "exceeds" in w.message for w in res.warnings)


def test_turbulent_regime_converges(cfg):
    cfg.pump.flow_rate_ml_min = 400
    cfg.pump.max_pressure_pa = 1e8
    res = run_simulation(cfg)
    assert res.ok
    assert (res.edges.regime == "turbulent").any()
    _assert_mass_balance(res)


def test_variable_reactor_count():
    for n in (1, 2, 6, 8):
        c = default_system()
        set_reactor_count(c, n)
        res = run_simulation(c)
        assert res.ok and len(res.reactor_flows()) == n
        _assert_mass_balance(res)


def test_reverse_flow_possible_with_two_pumps(water20):
    net = HydraulicNetwork()
    net.add_node("R", fixed_pressure=0)
    net.add_node("a")
    net.add_node("b")
    net.add_edge("p1", "R", "a", PumpConfig(mode="B_constant_pressure", pressure_difference_pa=1000), "pump")
    net.add_edge("p2", "R", "b", PumpConfig(mode="B_constant_pressure", pressure_difference_pa=3000), "pump")
    net.add_edge("x", "a", "b", LinearResistor(resistance=1e9), "resistor")
    net.add_edge("ra", "a", "R", LinearResistor(resistance=1e9), "resistor")
    net.add_edge("rb", "b", "R", LinearResistor(resistance=1e9), "resistor")
    s = solve_network(net, water20)
    assert s.converged and s.edge_flows["x"] == pytest.approx(-2000 / 1e9)


def test_network_without_reference_raises(water20):
    net = HydraulicNetwork()
    net.add_node("a")
    net.add_node("b")
    net.add_edge("r", "a", "b", LinearResistor(), "resistor")
    with pytest.raises(SolverError):
        solve_network(net, water20)


def test_network_validation_errors():
    net = HydraulicNetwork()
    net.add_node("a")
    with pytest.raises(ValueError):
        net.add_node("a")
    with pytest.raises(ValueError):
        net.add_edge("e", "a", "zz", LinearResistor())
    with pytest.raises(ValueError):
        net.add_edge("e", "a", "a", LinearResistor())


def test_single_line_layout(cfg):
    cfg.layout = "single_line"
    cfg.single_line.include_reactor = True
    cfg.single_line.include_throttle = True
    res = run_simulation(cfg)
    assert res.ok and res.reactor_flows()[0] == pytest.approx(cfg.pump.flow_rate_ml_min * ML_MIN)


def test_system_volume_positive(cfg):
    res = run_simulation(cfg)
    assert res.volumes["circuit_total"] > 0
    assert res.volumes["total_medium"] == pytest.approx(res.volumes["circuit_total"] + cfg.reservoir.fill_volume_ml * 1e-6)


def test_hydrostatic_cancels_in_closed_loop(cfg):
    base = run_simulation(cfg)
    cfg.pump_outlet_tube.elevation_change_mm = 300
    cfg.return_tube.elevation_change_mm = -300
    res = run_simulation(cfg)
    assert res.pump["dp"] == pytest.approx(base.pump["dp"], rel=1e-9)
    assert res.solver.node_pressures["S1"] < base.solver.node_pressures["S1"]


def test_warm_start_same_result(cfg):
    a = run_simulation(cfg)
    b = run_simulation(cfg, initial=a.solver)
    assert np.allclose(a.reactor_flows(), b.reactor_flows(), rtol=1e-10)
