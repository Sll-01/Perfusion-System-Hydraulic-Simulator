"""Fundamental one-dimensional hydraulic relations (SI units throughout).

Every function in this module is a direct implementation of a textbook relation. The
equations, their derivation and their range of validity are documented in
``documentation/scientific_documentation.md`` (chapter numbers given in brackets).

Conventions
-----------
* ``Q``   volumetric flow rate                [m^3/s]
* ``d``   (hydraulic) diameter                [m]
* ``L``   length                              [m]
* ``rho`` density                             [kg/m^3]
* ``mu``  dynamic viscosity                   [Pa s]
* ``dp``  pressure drop in flow direction     [Pa]

Avoiding double counting
------------------------
Frictional losses of straight tubes are computed **only** with the Darcy-Weisbach
equation. In the laminar regime the Darcy friction factor ``f = 64/Re`` is used, which
makes Darcy-Weisbach algebraically identical to the Hagen-Poiseuille law. Hagen-Poiseuille
is therefore *not* added a second time; :func:`hagen_poiseuille_resistance` exists for
verification, initial guesses and analytical reference cases.
Local (minor) losses ``K * rho v^2 / 2`` describe additional, geometrically localised
dissipation (bends, fittings, area changes) and are added on top of the straight-tube
friction of the *remaining* tube length.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .units import G_STANDARD

# Engineering convention for the regime limits of circular-pipe flow.  The values are
# configurable because the laminar-turbulent transition depends on inlet conditions,
# disturbances and pulsation (see documentation, chapter 3.3).
RE_LAMINAR_LIMIT = 2000.0
RE_TURBULENT_LIMIT = 4000.0


# ---------------------------------------------------------------------------
# Kinematics
# ---------------------------------------------------------------------------
def circle_area(d):
    return np.pi * np.asarray(d, dtype=float) ** 2 / 4.0


def mean_velocity(Q, d):
    """Mean (bulk) velocity v = Q / A for a circular cross-section."""
    return np.asarray(Q, dtype=float) / circle_area(d)


def reynolds_number(rho, v, d, mu):
    """Re = rho * v * d / mu (d = hydraulic diameter)."""
    return rho * np.abs(v) * d / mu


def hydraulic_diameter(area, perimeter):
    """D_h = 4 A / P (exact for circles, an approximation for non-circular ducts)."""
    return 4.0 * area / perimeter


def flow_regime(Re, re_lam=RE_LAMINAR_LIMIT, re_turb=RE_TURBULENT_LIMIT) -> str:
    if Re < re_lam:
        return "laminar"
    if Re <= re_turb:
        return "transitional"
    return "turbulent"


# ---------------------------------------------------------------------------
# Friction factor models (Darcy friction factor f, not Fanning!)
# ---------------------------------------------------------------------------
def friction_factor_laminar(Re):
    """f = 64 / Re (exact for fully developed laminar flow in a circular pipe)."""
    return 64.0 / Re


def friction_factor_swamee_jain(Re, rel_roughness):
    """Explicit approximation of the Colebrook equation (Swamee & Jain, 1976).

    Stated validity: 5e3 <= Re <= 1e8, 1e-6 <= eps/d <= 1e-2.
    """
    Re = np.asarray(Re, dtype=float)
    return 0.25 / np.log10(rel_roughness / 3.7 + 5.74 / Re**0.9) ** 2


def friction_factor_haaland(Re, rel_roughness):
    """Explicit approximation of the Colebrook equation (Haaland, 1983)."""
    Re = np.asarray(Re, dtype=float)
    inv_sqrt = -1.8 * np.log10((rel_roughness / 3.7) ** 1.11 + 6.9 / Re)
    return 1.0 / inv_sqrt**2


def friction_factor_colebrook(Re, rel_roughness, tol=1e-12, max_iter=50):
    """Colebrook-White equation, solved iteratively (fixed point in 1/sqrt(f)).

    1/sqrt(f) = -2 log10( (eps/d)/3.7 + 2.51 / (Re sqrt(f)) )

    The Swamee-Jain approximation serves as starting value. The iteration is a
    contraction for turbulent Reynolds numbers and converges in < 10 iterations.
    """
    Re = np.asarray(Re, dtype=float)
    x = 1.0 / np.sqrt(friction_factor_swamee_jain(Re, rel_roughness))
    for _ in range(max_iter):
        x_new = -2.0 * np.log10(rel_roughness / 3.7 + 2.51 * x / Re)
        if np.all(np.abs(x_new - x) < tol * np.abs(x)):
            x = x_new
            break
        x = x_new
    return 1.0 / x**2


_TURBULENT_MODELS = {
    "colebrook": friction_factor_colebrook,
    "swamee_jain": friction_factor_swamee_jain,
    "haaland": friction_factor_haaland,
}


@dataclass(frozen=True)
class FrictionSettings:
    turbulent_model: str = "colebrook"
    re_laminar: float = RE_LAMINAR_LIMIT
    re_turbulent: float = RE_TURBULENT_LIMIT


DEFAULT_FRICTION = FrictionSettings()


def friction_factor(Re, rel_roughness=0.0, settings: FrictionSettings = DEFAULT_FRICTION):
    """Darcy friction factor for laminar, transitional and turbulent flow (vectorised).

    * Re < Re_lam      : f = 64/Re (analytical, Hagen-Poiseuille)
    * Re > Re_turb     : turbulent correlation (Colebrook by default, empirical)
    * in between       : linear interpolation in Re between f_lam(Re_lam) and
                         f_turb(Re_turb).  This is an engineering bridging assumption
                         that keeps dp(Q) continuous and monotonic for the Newton solver.
                         It is *not* a physical model of intermittent transitional flow.
    """
    Re = np.atleast_1d(np.asarray(Re, dtype=float))
    Re_safe = np.maximum(Re, 1e-12)
    f = np.empty_like(Re_safe)
    lam = Re_safe < settings.re_laminar
    turb = Re_safe > settings.re_turbulent
    trans = ~(lam | turb)
    turb_fn = _TURBULENT_MODELS[settings.turbulent_model]
    f[lam] = friction_factor_laminar(Re_safe[lam])
    if np.any(turb):
        f[turb] = turb_fn(Re_safe[turb], rel_roughness)
    if np.any(trans):
        f_l = friction_factor_laminar(settings.re_laminar)
        f_t = float(turb_fn(np.array([settings.re_turbulent]), rel_roughness)[0])
        w = (Re_safe[trans] - settings.re_laminar) / (settings.re_turbulent - settings.re_laminar)
        f[trans] = (1 - w) * f_l + w * f_t
    return f if f.size > 1 else float(f[0])


def friction_method_label(Re, settings: FrictionSettings = DEFAULT_FRICTION) -> str:
    reg = flow_regime(Re, settings.re_laminar, settings.re_turbulent)
    if reg == "laminar":
        return "Hagen-Poiseuille (f=64/Re, analytical)"
    if reg == "transitional":
        return "Interpolated laminar/turbulent friction factor (bridging assumption)"
    return f"Darcy-Weisbach with {settings.turbulent_model} friction factor (empirical)"


# ---------------------------------------------------------------------------
# Pressure drop relations
# ---------------------------------------------------------------------------
def hagen_poiseuille_resistance(mu, L, d):
    """Laminar hydraulic resistance of a circular tube, R = 128 mu L / (pi d^4) [Pa s/m^3]."""
    return 128.0 * mu * L / (math.pi * d**4)


def darcy_weisbach_dp(f, L, d, rho, v):
    """dp = f (L/d) rho v^2 / 2."""
    return f * (L / d) * rho * v**2 / 2.0


def local_loss_dp(K, rho, v):
    """Minor loss dp = K rho v^2 / 2 (K referenced to the velocity v)."""
    return K * rho * v**2 / 2.0


def dynamic_pressure(rho, v):
    """Bernoulli dynamic pressure rho v^2 / 2."""
    return rho * v**2 / 2.0


def hydrostatic_dp(rho, dz):
    """Hydrostatic pressure difference rho g dz (dz = z_out - z_in)."""
    return rho * G_STANDARD * dz


def wall_shear_stress_from_f(f, rho, v):
    """Mean wall shear stress from the Darcy friction factor, tau_w = f rho v^2 / 8.

    For laminar flow (f = 64/Re) this reduces exactly to tau_w = 8 mu v / d = 32 mu Q /(pi d^3).
    """
    return f * rho * v**2 / 8.0


def wall_shear_stress_poiseuille(mu, Q, d):
    return 32.0 * mu * Q / (math.pi * d**3)


def k_sudden_expansion(d_small, d_large):
    """Borda-Carnot loss coefficient referenced to the upstream (small) velocity.

    K = (1 - A_small/A_large)^2 -- derived from the momentum balance (analytical for
    high Re, turbulent-mixing assumption). For laminar flow it overestimates/underestimates
    the real loss; see documentation.
    """
    if d_large <= d_small:
        return 0.0
    beta = (d_small / d_large) ** 2
    return (1.0 - beta) ** 2


def k_sudden_contraction(d_large, d_small):
    """Approximate sudden-contraction coefficient referenced to the downstream (small)
    velocity, K = 0.5 (1 - A_small/A_large).  Empirical textbook approximation."""
    if d_small >= d_large:
        return 0.0
    beta = (d_small / d_large) ** 2
    return 0.5 * (1.0 - beta)


def two_k_coefficient(K1, K_inf, Re, d):
    """Two-K method (Hooper, 1981): K = K1/Re + K_inf (1 + 1/D_in), D_in = diameter in inches.

    With K1 = 0 this reduces to a constant loss coefficient K_inf (1 + 1/D_in); to obtain a
    *plain* constant K use :func:`local_loss_dp` directly.
    """
    d_in = d / 0.0254
    return K1 / max(Re, 1e-12) + K_inf * (1.0 + 1.0 / d_in)


def orifice_dp(Q, area, rho, cd):
    """Orifice equation from Bernoulli + discharge coefficient: dp = rho Q|Q| / (2 Cd^2 A^2)."""
    return rho * Q * abs(Q) / (2.0 * cd**2 * area**2)


def kv_dp(Q, kv_m3h, rho):
    """Pressure drop from the Kv value (IEC 60534 definition for incompressible liquids).

    Q[m^3/h] = Kv * sqrt( dp[bar] / (rho/1000) )  =>  dp[Pa] = 1e5 (rho/1000) (Q_h/Kv)^2
    """
    q_h = Q * 3600.0
    return 1e5 * (rho / 1000.0) * q_h * abs(q_h) / kv_m3h**2


CV_TO_KV = 0.865  # Kv = 0.865 Cv (US gal/min at 1 psi vs m^3/h at 1 bar)


# ---------------------------------------------------------------------------
# Non-circular / tapered laminar resistances
# ---------------------------------------------------------------------------
def ellipse_laminar_resistance(mu, L, a, b):
    """Exact laminar resistance of an elliptical duct (semi-axes a, b).

    R = 4 mu L (a^2 + b^2) / (pi a^3 b^3)  -- reduces to 128 mu L/(pi d^4) for a = b = d/2.
    """
    return 4.0 * mu * L * (a**2 + b**2) / (math.pi * a**3 * b**3)


def ellipse_perimeter(a, b):
    """Ramanujan's second approximation of the ellipse perimeter (rel. error < 1e-9 for
    moderate eccentricities, < 4e-4 in the degenerate limit)."""
    h = ((a - b) / (a + b)) ** 2
    return math.pi * (a + b) * (1 + 3 * h / (10 + math.sqrt(4 - 3 * h)))


def linear_taper_laminar_resistance(mu, L, d1, d2):
    """Laminar resistance of a linearly tapered circular duct (lubrication approximation).

    R = 128 mu / pi * integral_0^L dx / d(x)^4 = 128 mu L (d1^2 + d1 d2 + d2^2) / (3 pi d1^3 d2^3)
    """
    return 128.0 * mu * L * (d1**2 + d1 * d2 + d2**2) / (3.0 * math.pi * d1**3 * d2**3)


# ---------------------------------------------------------------------------
# Porous media
# ---------------------------------------------------------------------------
def darcy_dp(mu, L, k, area, Q):
    """Darcy's law: dp = mu L Q / (k A)."""
    return mu * L * Q / (k * area)


def forchheimer_dp(mu, rho, L, k, beta, area, Q):
    """Darcy-Forchheimer: dp/L = mu u / k + beta rho u|u|, u = Q/A (superficial velocity)."""
    u = Q / area
    return L * (mu * u / k + beta * rho * u * abs(u))


# ---------------------------------------------------------------------------
# Network helpers (analytical reference)
# ---------------------------------------------------------------------------
def series_resistance(resistances):
    return float(sum(resistances))


def parallel_resistance(resistances):
    inv = [1.0 / r for r in resistances if r != math.inf]
    if not inv:
        return math.inf
    return 1.0 / sum(inv)
