"""Unit conversion helpers.

All calculations inside :mod:`core` are performed in SI units. Conversions to and from
laboratory units (mL/min, mm, mbar, mmHg, ...) happen exclusively at the boundaries
(user interface, import, export).

The conversion factors are exact definitions (SI brochure / ISO 80000) except where
noted. ``mmHg`` uses the conventional definition 1 mmHg = 133.322387415 Pa.
"""
from __future__ import annotations

import math

# --- base constants -------------------------------------------------------
G_STANDARD = 9.80665  # m/s^2, standard acceleration of gravity (exact by definition)
P_ATM = 101_325.0  # Pa, standard atmosphere (exact by definition)
ZERO_CELSIUS_K = 273.15

# --- conversion factors to SI ---------------------------------------------
_FACTORS: dict[str, dict[str, float]] = {
    "length": {"m": 1.0, "cm": 1e-2, "mm": 1e-3, "um": 1e-6, "µm": 1e-6, "in": 0.0254},
    "area": {"m2": 1.0, "cm2": 1e-4, "mm2": 1e-6, "um2": 1e-12},
    "volume": {"m3": 1.0, "L": 1e-3, "mL": 1e-6, "uL": 1e-9, "µL": 1e-9},
    "flow": {
        "m3/s": 1.0,
        "mL/min": 1e-6 / 60.0,
        "mL/s": 1e-6,
        "uL/min": 1e-9 / 60.0,
        "µL/min": 1e-9 / 60.0,
        "L/min": 1e-3 / 60.0,
        "L/h": 1e-3 / 3600.0,
        "m3/h": 1.0 / 3600.0,
    },
    "pressure": {
        "Pa": 1.0,
        "kPa": 1e3,
        "mbar": 1e2,
        "bar": 1e5,
        "mmHg": 133.322387415,
        "psi": 6894.757293168361,
        "cmH2O": 98.0665,
    },
    "dynamic_viscosity": {"Pa*s": 1.0, "mPa*s": 1e-3, "cP": 1e-3},
    "kinematic_viscosity": {"m2/s": 1.0, "mm2/s": 1e-6, "cSt": 1e-6},
    "density": {"kg/m3": 1.0, "g/cm3": 1e3, "g/mL": 1e3},
    "resistance": {"Pa*s/m3": 1.0, "mbar/(mL/min)": 1e2 / (1e-6 / 60.0), "Pa/(mL/min)": 1.0 / (1e-6 / 60.0)},
    "time": {"s": 1.0, "min": 60.0, "h": 3600.0},
    "velocity": {"m/s": 1.0, "mm/s": 1e-3, "cm/s": 1e-2, "um/s": 1e-6},
    "stress": {"Pa": 1.0, "mPa": 1e-3, "dyn/cm2": 0.1},
    "power": {"W": 1.0, "mW": 1e-3, "uW": 1e-6, "µW": 1e-6},
    "permeability": {"m2": 1.0, "darcy": 9.869233e-13},
}


def _find_dimension(unit: str) -> str:
    for dim, table in _FACTORS.items():
        if unit in table:
            return dim
    raise KeyError(f"Unknown unit '{unit}'")


def convert(value: float, from_unit: str, to_unit: str) -> float:
    """Convert ``value`` from ``from_unit`` to ``to_unit`` (same physical dimension).

    Temperature units (``degC``, ``K``) are handled separately because they are affine.
    """
    if from_unit in ("degC", "K") or to_unit in ("degC", "K"):
        return convert_temperature(value, from_unit, to_unit)
    d1, d2 = _find_dimension(from_unit), _find_dimension(to_unit)
    if d1 != d2:
        raise ValueError(f"Incompatible units: {from_unit} ({d1}) vs {to_unit} ({d2})")
    return value * _FACTORS[d1][from_unit] / _FACTORS[d2][to_unit]


def to_si(value: float, unit: str) -> float:
    if unit in ("degC", "K"):
        return convert_temperature(value, unit, "K")
    return value * _FACTORS[_find_dimension(unit)][unit]


def from_si(value: float, unit: str) -> float:
    if unit in ("degC", "K"):
        return convert_temperature(value, "K", unit)
    return value / _FACTORS[_find_dimension(unit)][unit]


def convert_temperature(value: float, from_unit: str, to_unit: str) -> float:
    if from_unit == to_unit:
        return value
    k = value + ZERO_CELSIUS_K if from_unit == "degC" else value
    if from_unit not in ("degC", "K") or to_unit not in ("degC", "K"):
        raise ValueError("Temperature conversion only between degC and K")
    return k - ZERO_CELSIUS_K if to_unit == "degC" else k


# --- frequently used shortcuts ---------------------------------------------
ML_MIN = _FACTORS["flow"]["mL/min"]  # m^3/s per mL/min
MM = 1e-3
MBAR = 1e2


def mlmin_to_m3s(q_ml_min: float) -> float:
    return q_ml_min * ML_MIN


def m3s_to_mlmin(q_m3s: float) -> float:
    return q_m3s / ML_MIN


def mm_to_m(x_mm: float) -> float:
    return x_mm * MM


def circle_area(diameter_m: float) -> float:
    return math.pi * diameter_m**2 / 4.0
