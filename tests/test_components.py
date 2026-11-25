import math

import numpy as np
import pytest

from core.bioreactors import Bioreactor
from core.constrictions import Constriction
from core.scaffolds import Scaffold
from core.splitters import Splitter, SplitterChannel, SplitterPort
from core.throttles import Throttle
from core.tubing import AreaChange, Bend, Fitting, Tube
from core.units import ML_MIN

Q = 2 * ML_MIN


def test_tube_local_losses_added_without_double_counting(water20):
    t0 = Tube(length_m=0.3, inner_diameter_mm=1.6)
    t1 = Tube(length_m=0.3, inner_diameter_mm=1.6, bends=[Bend(count=2, K=0.3)], fittings=[Fitting(count=1, K=0.5)], extra_K=0.2)
    v = Q / (math.pi * 0.0016**2 / 4)
    assert t1.pressure_drop(Q, water20) - t0.pressure_drop(Q, water20) == pytest.approx(1.3 * water20.density * v**2 / 2, rel=1e-9)


def test_tube_area_change_K():
    t = Tube(inner_diameter_mm=1.0, area_changes=[AreaChange(kind="expansion", connected_diameter_mm=2.0)])
    assert t.sum_K(10) == pytest.approx(0.75**2)
    t = Tube(inner_diameter_mm=2.0, area_changes=[AreaChange(kind="contraction", connected_diameter_mm=1.0)])
    assert t.sum_K(10) == pytest.approx(0.5 * 0.75 * 16)


def test_tube_volume_and_wall(water20):
    t = Tube(length_m=1.0, inner_diameter_mm=2.0, outer_diameter_mm=4.0)
    assert t.volume_m3() == pytest.approx(math.pi * 1e-6)
    assert t.wall_thickness() == pytest.approx(1.0)
    d = t.details(Q, water20)
    assert d["residence_time_s"] == pytest.approx(t.volume_m3() / Q)
    assert d["regime"] == "laminar"


def test_tube_reverse_flow_antisymmetric(water20):
    t = Tube(length_m=0.3, inner_diameter_mm=1.6, fittings=[Fitting(K=1)])
    assert t.pressure_drop(-Q, water20) == pytest.approx(-t.pressure_drop(Q, water20))


def test_constriction_diameter_vs_area_reduction():
    D = 2e-3
    cd = Constriction(specification="diameter_reduction", degree_percent=50)
    ca = Constriction(specification="area_reduction", degree_percent=50)
    assert cd.effective_circular_diameter(D) == pytest.approx(1e-3)
    assert cd.remaining_area_fraction(D) == pytest.approx(0.25)
    assert ca.remaining_area_fraction(D) == pytest.approx(0.5)
    ce = Constriction(specification="effective_area", effective_area_mm2=math.pi / 4 * 1.0)
    assert ce.effective_circular_diameter(D) == pytest.approx(1e-3)


def test_constriction_blocked_and_open():
    assert Constriction(mode="blocked").is_blocked()
    assert Constriction(degree_percent=100).is_blocked()
    assert not Constriction(mode="open", degree_percent=100).is_active()
    t = Tube(constrictions=[Constriction(degree_percent=100)])
    assert t.is_closed()


def test_constriction_increases_loss_monotonically(water20):
    dps = []
    for deg in [0, 20, 40, 60, 80, 90]:
        t = Tube(length_m=0.3, inner_diameter_mm=1.6, constrictions=[Constriction(mode="local", degree_percent=deg, length_mm=5)])
        dps.append(t.pressure_drop(Q, water20))
    assert all(np.diff(dps) > 0)


def test_elliptical_compression_perimeter_conserved():
    from core.hydraulics import ellipse_perimeter

    c = Constriction(mode="partial_compression", geometry="elliptical", degree_percent=60)
    a, b = c.ellipse_axes(2e-3)
    assert ellipse_perimeter(a, b) == pytest.approx(math.pi * 2e-3, rel=1e-9)
    assert b == pytest.approx(0.4e-3)
    c2 = Constriction(mode="partial_compression", geometry="elliptical", specification="area_reduction", degree_percent=50)
    assert c2.remaining_area_fraction(2e-3) == pytest.approx(0.5, rel=1e-6)


def test_linear_taper_matches_analytic(water20):
    from core.hydraulics import linear_taper_laminar_resistance

    D, dmin, L = 1.6e-3, 0.8e-3, 0.05
    c = Constriction(mode="continuous", taper="linear", degree_percent=50, length_mm=50, n_slices=400)
    dp = c.loss(0.2 * ML_MIN, water20, __import__("core.hydraulics", fromlist=["x"]).DEFAULT_FRICTION, D)
    assert dp == pytest.approx(linear_taper_laminar_resistance(water20.dynamic_viscosity, L, D, dmin) * 0.2 * ML_MIN, rel=1e-3)


def test_kink_model_calibratable(water20):
    t0 = Tube(length_m=0.3)
    t1 = Tube(length_m=0.3, constrictions=[Constriction(mode="kink", degree_percent=0, length_mm=2, kink_K=5)])
    v = Q / t0.area
    assert t1.pressure_drop(Q, water20) - t0.pressure_drop(Q, water20) == pytest.approx(5 * water20.density * v**2 / 2, rel=1e-6)


@pytest.mark.parametrize("ch", ["linear", "equal_percentage", "quick_opening", "table"])
def test_throttle_characteristics(ch):
    th = Throttle(characteristic=ch, opening_table=[(0, 0), (50, 0.2), (100, 1)])
    caps = []
    for op in [10, 30, 50, 70, 100]:
        th.opening_percent = op
        caps.append(th.relative_capacity())
    assert all(np.diff(caps) > 0)
    assert caps[-1] == pytest.approx(1.0)
    th.opening_percent = 0
    assert th.is_closed()


@pytest.mark.parametrize("model", ["resistance", "orifice_diameter", "orifice_area", "k_value", "kv"])
def test_throttle_models_monotonic_in_opening(model, water20):
    th = Throttle(model=model, kv_max=0.01, max_area_mm2=0.8)
    dps = []
    for op in [20, 40, 60, 80, 100]:
        th.opening_percent = op
        dps.append(th.pressure_drop(Q, water20))
    assert all(np.diff(dps) < 0)


def test_throttle_cv_conversion(water20):
    a = Throttle(model="kv", kv_max=0.865)
    b = Throttle(model="kv", cv_max=1.0)
    assert a.pressure_drop(Q, water20) == pytest.approx(b.pressure_drop(Q, water20))


def test_throttle_dp_curve_reproduces_measurements(water20):
    pts = [(100, q, 10 * q + 3 * q**2) for q in (0.5, 1, 2, 4)]
    th = Throttle(model="dp_curve", dp_curve_points=pts, opening_percent=100)
    for _, q, dp in pts:
        assert th.pressure_drop(q * ML_MIN, water20) == pytest.approx(dp, rel=1e-6)


def test_throttle_calibration_factor(water20):
    a, b = Throttle(), Throttle(calibration_factor=2.0)
    assert b.pressure_drop(Q, water20) == pytest.approx(2 * a.pressure_drop(Q, water20))


def test_scaffold_quantities(water20):
    s = Scaffold(diameter_mm=8, height_mm=3, porosity=0.8, permeability_m2=1e-10)
    d = s.details(Q, water20)
    A = math.pi * 0.008**2 / 4
    assert d["superficial_velocity"] == pytest.approx(Q / A)
    assert d["pore_velocity_estimate"] == pytest.approx(Q / A / 0.8)
    u = Q / A
    assert d["shear_stress_pore_model"] == pytest.approx(math.sqrt(2) * water20.dynamic_viscosity * u / math.sqrt(1e-10 * 0.8))
    s2 = s.model_copy(update={"use_forchheimer": True})
    assert s2.loss(Q, water20) > s.loss(Q, water20)


def test_reactor_states(water20):
    r = Bioreactor()
    base = r.pressure_drop(Q, water20)
    assert Bioreactor(state="reduced_permeability", permeability_factor=0.1).pressure_drop(Q, water20) > base
    assert Bioreactor(state="partially_blocked", blocked_fraction=0.5).pressure_drop(Q, water20) > base
    assert Bioreactor(state="empty").pressure_drop(Q, water20) < base
    assert Bioreactor(state="no_scaffold").pressure_drop(Q, water20) < base
    assert Bioreactor(state="blocked").is_closed()
    ex = Bioreactor(experimental_resistance=1e9)
    assert ex.pressure_drop(Q, water20) == pytest.approx(1e9 * Q)
    assert r.volume_m3() < Bioreactor(state="empty").volume_m3()


def test_reactor_scaffold_dp_reported(water20):
    r = Bioreactor()
    d = r.details(Q, water20)
    assert d["dp_scaffold"] == pytest.approx(r.scaffold.loss(Q, water20))
    assert d["dp_total"] > d["dp_scaffold"]


def test_splitter_modes(water20):
    sp = Splitter(mode="ideal")
    assert sp.channel(0).pressure_drop(Q, water20) == 0.0
    sp = Splitter(mode="individual_resistances", branch_ports=[SplitterPort(resistance=1e9), SplitterPort(resistance=2e9)])
    assert sp.channel(1).pressure_drop(Q, water20) == pytest.approx(2e9 * Q)
    sp = Splitter(mode="symmetric", branch_ports=[SplitterPort(K=0.5), SplitterPort(K=5)])
    assert sp.channel(1).pressure_drop(Q, water20) == pytest.approx(sp.channel(0).pressure_drop(Q, water20))
    sp.ensure_ports(6)
    assert len(sp.branch_ports) == 6
