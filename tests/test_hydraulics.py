import math

import numpy as np
import pytest

from core import hydraulics as h
from core.fluids import FluidConfig, evaluate_fluid, water_density, water_viscosity
from core.units import convert, from_si, mlmin_to_m3s, m3s_to_mlmin, to_si


def test_unit_roundtrip():
    for u in ["mL/min", "uL/min", "L/h", "m3/h"]:
        assert from_si(to_si(3.7, u), u) == pytest.approx(3.7)
    assert convert(1, "bar", "mbar") == pytest.approx(1000)
    assert convert(37, "degC", "K") == pytest.approx(310.15)
    assert convert(1, "cP", "Pa*s") == pytest.approx(1e-3)
    assert m3s_to_mlmin(mlmin_to_m3s(2.5)) == pytest.approx(2.5)
    with pytest.raises(ValueError):
        convert(1, "mL/min", "Pa")


def test_laminar_darcy_equals_hagen_poiseuille():
    mu, rho, d, L, Q = 1e-3, 1000.0, 1e-3, 0.5, 1e-8
    v = Q / (math.pi * d**2 / 4)
    Re = rho * v * d / mu
    dp_dw = h.darcy_weisbach_dp(h.friction_factor(Re), L, d, rho, v)
    assert dp_dw == pytest.approx(h.hagen_poiseuille_resistance(mu, L, d) * Q, rel=1e-12)


def test_friction_factor_continuity_at_regime_limits():
    for Re in (2000.0, 4000.0):
        lo, hi = h.friction_factor(Re * (1 - 1e-9), 1e-3), h.friction_factor(Re * (1 + 1e-9), 1e-3)
        assert lo == pytest.approx(hi, rel=1e-6)


def test_friction_models_agree():
    Re = np.array([1e4, 1e5, 1e6])
    fc = h.friction_factor_colebrook(Re, 1e-4)
    assert np.allclose(h.friction_factor_swamee_jain(Re, 1e-4), fc, rtol=0.02)
    assert np.allclose(h.friction_factor_haaland(Re, 1e-4), fc, rtol=0.02)


def test_regime():
    assert h.flow_regime(100) == "laminar"
    assert h.flow_regime(3000) == "transitional"
    assert h.flow_regime(1e5) == "turbulent"


def test_borda_carnot_and_contraction():
    assert h.k_sudden_expansion(1.0, 2.0) == pytest.approx((1 - 0.25) ** 2)
    assert h.k_sudden_expansion(2.0, 1.0) == 0.0
    assert h.k_sudden_contraction(2.0, 1.0) == pytest.approx(0.5 * 0.75)


def test_series_parallel_helpers():
    assert h.series_resistance([1, 2, 3]) == 6
    assert h.parallel_resistance([2, 2]) == pytest.approx(1)
    assert h.parallel_resistance([math.inf, 4]) == pytest.approx(4)


def test_forchheimer_reduces_to_darcy():
    assert h.forchheimer_dp(1e-3, 1000, 0.003, 1e-10, 0.0, 5e-5, 1e-8) == pytest.approx(h.darcy_dp(1e-3, 0.003, 1e-10, 5e-5, 1e-8))


def test_kv_definition():
    # Kv = 1 m3/h -> 1 m3/h water at 1 bar
    assert h.kv_dp(1 / 3600, 1.0, 1000.0) == pytest.approx(1e5)


def test_orifice():
    assert h.orifice_dp(1e-6, 1e-6, 1000, 1.0) == pytest.approx(500.0)


def test_water_properties_monotonic():
    t = np.linspace(5, 60, 12)
    mu = [water_viscosity(x) for x in t]
    assert all(np.diff(mu) < 0)
    assert water_density(4.0) == pytest.approx(999.97, abs=0.01)


@pytest.mark.parametrize("ft", ["water", "saline", "culture_medium", "custom"])
def test_fluid_presets(ft):
    f = evaluate_fluid(FluidConfig(fluid_type=ft, temperature_c=37))
    assert 980 < f.density < 1020
    assert 3e-4 < f.dynamic_viscosity < 2e-3
    assert f.kinematic_viscosity == pytest.approx(f.dynamic_viscosity / f.density)


def test_fluid_overrides_and_warnings():
    f = evaluate_fluid(FluidConfig(fluid_type="water", temperature_c=37, dynamic_viscosity_override=0.9e-3, density_override=1005))
    assert f.dynamic_viscosity == 0.9e-3 and f.density == 1005
    f = evaluate_fluid(FluidConfig(fluid_type="water", temperature_c=37, kinematic_viscosity_override=1e-6, density_override=1000))
    assert f.dynamic_viscosity == pytest.approx(1e-3)
    f = evaluate_fluid(FluidConfig(fluid_type="water", temperature_c=50))
    assert any("outside validity" in w for w in f.warnings)
    f = evaluate_fluid(FluidConfig(fluid_type="culture_medium"))
    assert any("ASSUMPTION" in w for w in f.warnings)
