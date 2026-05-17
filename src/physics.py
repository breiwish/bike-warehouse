"""Martin et al. 1998 cycling power model.

P_total = (P_roll + P_aero + P_grav + P_KE) / (1 - drivetrain_loss)
  P_roll = Crr * m * g * cos(theta) * v
  P_aero = 0.5 * rho * CdA * v^3        (zero wind assumption; extend later)
  P_grav = m * g * sin(theta) * v
  P_KE   = m * v * dv/dt
"""
from __future__ import annotations

import math

import numpy as np

from . import config as C


def air_density(temp_c: float | None, altitude_m: float | None) -> float:
    """Crude ISA correction. Falls back to 1.225 kg/m^3."""
    if temp_c is None and altitude_m is None:
        return C.RHO
    T = (temp_c if temp_c is not None else 15.0) + 273.15
    h = altitude_m if altitude_m is not None else 0.0
    # Barometric
    p0 = 101325.0
    L = 0.0065
    T0 = 288.15
    p = p0 * (1 - L * h / T0) ** 5.2561 if h < 11000 else p0 * 0.2234
    R = 287.058
    return p / (R * T)


def grade_to_theta(grade_pct: float) -> float:
    return math.atan(grade_pct / 100.0)


def estimate_watts(speed_ms: np.ndarray,
                   grade_pct: np.ndarray,
                   altitude_m: np.ndarray | None = None,
                   temp_c: float | None = None,
                   mass_kg: float | None = None,
                   cda: float | None = None,
                   crr: float | None = None,
                   dt_s: float = 1.0) -> np.ndarray:
    """Return per-sample estimated watts. Coasting / braking clamped to 0."""
    m = mass_kg if mass_kg is not None else C.RIDER_KG + C.BIKE_KG
    cda = cda if cda is not None else C.CDA
    crr = crr if crr is not None else C.CRR
    g = C.G

    v = np.asarray(speed_ms, dtype=float)
    grade = np.asarray(grade_pct, dtype=float)
    theta = np.arctan(grade / 100.0)

    if altitude_m is not None:
        alt = float(np.nanmean(altitude_m))
    else:
        alt = 0.0
    rho = air_density(temp_c, alt)

    p_roll = crr * m * g * np.cos(theta) * v
    p_aero = 0.5 * rho * cda * v ** 3
    p_grav = m * g * np.sin(theta) * v
    dv = np.gradient(v, dt_s)
    p_ke = m * v * dv

    p = (p_roll + p_aero + p_grav + p_ke) / (1.0 - C.DRIVETRAIN_LOSS)
    return np.clip(p, 0.0, None)


def normalized_power(watts: np.ndarray, dt_s: float = 1.0) -> float:
    """Coggan NP: 4th-root of mean of (30s rolling avg)^4."""
    if len(watts) < 30:
        return float(np.nan)
    window = int(30 / dt_s)
    kernel = np.ones(window) / window
    rolled = np.convolve(watts, kernel, mode="valid")
    return float((np.mean(rolled ** 4)) ** 0.25)


def vam(altitude_m: np.ndarray, dt_s: float = 1.0) -> float:
    """Vertical ascent meters per hour."""
    gain = np.diff(altitude_m)
    gain = gain[gain > 0].sum()
    hours = len(altitude_m) * dt_s / 3600.0
    return float(gain / hours) if hours > 0 else 0.0
