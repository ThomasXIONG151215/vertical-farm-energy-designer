"""
Wet-air thermodynamics utility library (psychrometrics).

Pure functions for psychrometric calculations used by the VFED design simulator.
All temperatures in Celsius, RH in percent (0-100), absolute humidity in kg/kg.

References:
- Magnus formula for saturation vapour pressure.
- ASHRAE Fundamentals, Chapter 1 (Psychrometrics).

This is a clean, configuration-free re-implementation of the vendored
``digital_twin.core.thermodynamics`` module, intended for design-time use
(no requirement on the 609 ML/TableStore stack).
"""

import math
from typing import Tuple

__all__ = [
    "saturation_vapor_pressure",
    "temp_rh_to_ah",
    "ah_to_temp_rh",
    "temp_rh_to_dewpoint",
    "temp_rh_to_wetbulb",
    "enthalpy",
    "latent_heat_vaporization",
    "compute_vpd",
    "saturation_humidity",
]


# Magnus formula is empirically valid roughly over -45..+60 °C; the guard
# below is deliberately wider so real-world weather and the room temperature
# clamp ([-20, 60] in ode.py) always pass, while absurd direct calls that
# would make the formula diverge (division by zero at T=-237.3 °C, overflow
# below that, or non-physical saturation pressure far above boiling) fail fast.
_MAGNUS_T_MIN = -100.0
_MAGNUS_T_MAX = 100.0


def _check_temp(temp_c: float) -> None:
    if not (_MAGNUS_T_MIN <= temp_c <= _MAGNUS_T_MAX):
        raise ValueError(
            f"saturation_vapor_pressure valid for "
            f"{_MAGNUS_T_MIN:.0f}..{_MAGNUS_T_MAX:.0f} °C, got {temp_c:.1f} °C"
        )


def saturation_vapor_pressure(temp_c: float) -> float:
    """Saturation vapour pressure over water (Magnus), kPa."""
    _check_temp(temp_c)
    return 0.61078 * math.exp((17.27 * temp_c) / (temp_c + 237.3))


def temp_rh_to_ah(temp_c: float, rh_pct: float,
                  pressure_kpa: float = 101.325) -> float:
    """Convert temperature (C) and RH (%) to absolute humidity (kg/kg)."""
    # Guard: RH outside [0,100] would otherwise produce negative AH or a
    # physically impossible one — clamp to the physical range.
    rh_pct = max(0.0, min(100.0, rh_pct))
    p_sat = saturation_vapor_pressure(temp_c)
    p_vapor = p_sat * rh_pct / 100.0
    return 0.622 * p_vapor / (pressure_kpa - p_vapor)


def ah_to_temp_rh(temp_c: float, ah: float,
                  pressure_kpa: float = 101.325) -> float:
    """Convert temperature (C) and absolute humidity (kg/kg) to RH (%)."""
    if ah < 0.0:
        raise ValueError(
            f"absolute humidity cannot be negative, got {ah:.6f} kg/kg")
    p_sat = saturation_vapor_pressure(temp_c)
    p_vapor = ah * pressure_kpa / (0.622 + ah)
    rh = (p_vapor / p_sat) * 100.0
    return max(0.0, min(100.0, rh))


def temp_rh_to_dewpoint(temp_c: float, rh_pct: float) -> float:
    """Dew point temperature (C) via Magnus inversion."""
    a, b = 17.27, 237.3
    if rh_pct <= 0.0:
        raise ValueError(f"RH must be > 0%, got {rh_pct:.2f}")
    if rh_pct >= 100.0:
        return temp_c
    alpha = ((a * temp_c) / (b + temp_c)) + math.log(rh_pct / 100.0)
    return (b * alpha) / (a - alpha)


def temp_rh_to_wetbulb(temp_c: float, rh_pct: float,
                       pressure_kpa: float = 101.325,
                       max_iter: int = 50, tol: float = 1e-6) -> float:
    """Wet-bulb temperature (C) via Newton-Raphson on the psychrometric equation."""
    ah = temp_rh_to_ah(temp_c, rh_pct)
    t_wb = temp_c * math.atan(0.151977 * math.sqrt(rh_pct + 8.313659))
    t_wb += math.atan(temp_c + rh_pct) - math.atan(rh_pct - 1.676331)
    t_wb += 0.00391838 * (rh_pct ** 1.5) * math.atan(0.023101 * rh_pct) - 4.686035
    for _ in range(max_iter):
        p_sat_wb = saturation_vapor_pressure(t_wb)
        ah_sat_wb = 0.622 * p_sat_wb / (pressure_kpa - p_sat_wb)
        h_fg = 2501.0 - 2.36 * t_wb
        f = ah_sat_wb - (1.006 / h_fg) * (temp_c - t_wb) - ah
        dp_sat = p_sat_wb * (17.27 * 237.3) / ((t_wb + 237.3) ** 2)
        d_ah_sat = 0.622 * pressure_kpa * dp_sat / ((pressure_kpa - p_sat_wb) ** 2)
        d_h_fg = -2.36
        d_f = d_ah_sat + (1.006 / h_fg) + (1.006 * (temp_c - t_wb) * d_h_fg) / (h_fg ** 2)
        if abs(d_f) < 1e-12:
            break
        t_wb_new = t_wb - f / d_f
        if abs(t_wb_new - t_wb) < tol:
            return t_wb_new
        t_wb = t_wb_new
    else:
        raise RuntimeError(
            f"Wet-bulb iteration did not converge after {max_iter} iterations "
            f"(T={temp_c:.1f}°C, RH={rh_pct:.1f}%)")
    return t_wb


def saturation_humidity(temp_c: float, pressure_kpa: float = 101.325) -> float:
    """Absolute humidity at saturation (kg/kg) for a given temperature."""
    p_sat = saturation_vapor_pressure(temp_c)
    return 0.622 * p_sat / (pressure_kpa - p_sat)


def enthalpy(temp_c: float, ah: float) -> float:
    """Specific enthalpy of moist air (kJ/kg dry air)."""
    return 1.006 * temp_c + ah * (2501.0 + 1.86 * temp_c)


def latent_heat_vaporization(temp_c: float) -> float:
    """Latent heat of vaporisation of water (kJ/kg) at temperature."""
    return 2501.0 - 2.36 * temp_c


def compute_vpd(temp_c: float, rh_pct: float) -> float:
    """Vapour pressure deficit (kPa)."""
    p_sat = saturation_vapor_pressure(temp_c)
    return p_sat * (1.0 - rh_pct / 100.0)
