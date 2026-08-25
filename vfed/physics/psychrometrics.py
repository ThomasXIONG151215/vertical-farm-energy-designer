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

# Magnus coefficients, split by phase at the freezing point (P1-1).
_WATER_MAGNUS_A = 17.27
_WATER_MAGNUS_B = 237.3
_WATER_MAGNUS_C = 0.61078
_ICE_MAGNUS_A = 22.587
_ICE_MAGNUS_B = 273.86
_ICE_MAGNUS_C = 0.61121


def _check_temp(temp_c: float) -> None:
    if not (_MAGNUS_T_MIN <= temp_c <= _MAGNUS_T_MAX):
        raise ValueError(
            f"saturation_vapor_pressure valid for "
            f"{_MAGNUS_T_MIN:.0f}..{_MAGNUS_T_MAX:.0f} °C, got {temp_c:.1f} °C"
        )


def saturation_vapor_pressure(temp_c: float) -> float:
    """Saturation vapour pressure (kPa), Magnus formula.

    Switches between the liquid-water and ice formulae at the freezing point:
    - T >= 0 C:  e = 0.61078 * exp(17.27 * T / (T + 237.3))   (water)
    - T <  0 C:  e = 0.61121 * exp(22.587 * T / (T + 273.86)) (ice)
    Using the water formula below 0 C over-estimates e by ~10 % at -10 C and
    ~49 % at -45 C, systematically over-stating winter infiltration humidity
    loads (P1-1).  Ice coefficients (22.587 / 273.86 / 0.61121) per ASHRAE and
    common Magnus references; note e_ice(0) = 0.61121 vs e_water(0) = 0.61078
    (~0.07 % triple-point discontinuity).
    """
    _check_temp(temp_c)
    if temp_c < 0.0:
        a, b, c = _ICE_MAGNUS_A, _ICE_MAGNUS_B, _ICE_MAGNUS_C
    else:
        a, b, c = _WATER_MAGNUS_A, _WATER_MAGNUS_B, _WATER_MAGNUS_C
    return c * math.exp((a * temp_c) / (temp_c + b))


def temp_rh_to_ah(temp_c: float, rh_pct: float, pressure_kpa: float = 101.325) -> float:
    """Convert temperature (C) and RH (%) to absolute humidity (kg/kg)."""
    # Guard: RH outside [0,100] would otherwise produce negative AH or a
    # physically impossible one — clamp to the physical range.
    rh_pct = max(0.0, min(100.0, rh_pct))
    p_sat = saturation_vapor_pressure(temp_c)
    p_vapor = p_sat * rh_pct / 100.0
    # P1-3: denominator must stay strictly positive.  At/above the boiling
    # limit (Magnus water formula reaches P_atm near 99.9 C) W diverges or
    # goes negative — fail fast instead of returning a non-physical value.
    if pressure_kpa - p_vapor <= 0.0:
        raise ValueError(
            f"vapour pressure {p_vapor:.4f} kPa >= station pressure "
            f"{pressure_kpa:.3f} kPa at T={temp_c:.1f} C, RH={rh_pct:.1f}%: "
            f"air at/above its saturation/boiling limit, absolute humidity "
            f"diverges (Magnus valid ~-45..60 C)"
        )
    return 0.622 * p_vapor / (pressure_kpa - p_vapor)


def ah_to_temp_rh(temp_c: float, ah: float, pressure_kpa: float = 101.325) -> float:
    """Convert temperature (C) and absolute humidity (kg/kg) to RH (%)."""
    if ah < 0.0:
        raise ValueError(f"absolute humidity cannot be negative, got {ah:.6f} kg/kg")
    p_sat = saturation_vapor_pressure(temp_c)
    p_vapor = ah * pressure_kpa / (0.622 + ah)
    rh = (p_vapor / p_sat) * 100.0
    return max(0.0, min(100.0, rh))


def temp_rh_to_dewpoint(temp_c: float, rh_pct: float) -> float:
    """Dew point temperature (C) via Magnus inversion.

    Mirrors saturation_vapor_pressure's water/ice switch: first pass uses the
    liquid-water constants; if the resulting T_dp is below 0 C the inversion
    is repeated with the ice constants (22.587 / 273.86) so sub-freezing dew
    points match the ice saturation formula (P1-4).
    """
    if rh_pct <= 0.0:
        raise ValueError(f"RH must be > 0%, got {rh_pct:.2f}")
    if rh_pct >= 100.0:
        return temp_c

    def _invert(a: float, b: float) -> float:
        alpha = ((a * temp_c) / (b + temp_c)) + math.log(rh_pct / 100.0)
        return (b * alpha) / (a - alpha)

    t_dp = _invert(_WATER_MAGNUS_A, _WATER_MAGNUS_B)
    if t_dp < 0.0:
        t_dp = _invert(_ICE_MAGNUS_A, _ICE_MAGNUS_B)
    return t_dp


def temp_rh_to_wetbulb(
    temp_c: float,
    rh_pct: float,
    pressure_kpa: float = 101.325,
    max_iter: int = 50,
    tol: float = 1e-6,
) -> float:
    """Wet-bulb temperature (C) via Newton-Raphson on the psychrometric equation."""
    ah = temp_rh_to_ah(temp_c, rh_pct)
    t_wb = temp_c * math.atan(0.151977 * math.sqrt(rh_pct + 8.313659))
    t_wb += math.atan(temp_c + rh_pct) - math.atan(rh_pct - 1.676331)
    t_wb += 0.00391838 * (rh_pct**1.5) * math.atan(0.023101 * rh_pct) - 4.686035
    for _ in range(max_iter):
        p_sat_wb = saturation_vapor_pressure(t_wb)
        ah_sat_wb = 0.622 * p_sat_wb / (pressure_kpa - p_sat_wb)
        h_fg = 2501.0 - 2.36 * t_wb
        f = ah_sat_wb - (1.006 / h_fg) * (temp_c - t_wb) - ah
        dp_sat = p_sat_wb * (17.27 * 237.3) / ((t_wb + 237.3) ** 2)
        d_ah_sat = 0.622 * pressure_kpa * dp_sat / ((pressure_kpa - p_sat_wb) ** 2)
        d_h_fg = -2.36
        d_f = d_ah_sat + (1.006 / h_fg) + (1.006 * (temp_c - t_wb) * d_h_fg) / (h_fg**2)
        if abs(d_f) < 1e-12:
            break
        t_wb_new = t_wb - f / d_f
        if abs(t_wb_new - t_wb) < tol:
            return t_wb_new
        t_wb = t_wb_new
    else:
        raise RuntimeError(
            f"Wet-bulb iteration did not converge after {max_iter} iterations "
            f"(T={temp_c:.1f}°C, RH={rh_pct:.1f}%)"
        )
    return t_wb


def saturation_humidity(temp_c: float, pressure_kpa: float = 101.325) -> float:
    """Absolute humidity at saturation (kg/kg) for a given temperature."""
    p_sat = saturation_vapor_pressure(temp_c)
    # P1-3: guard the denominator against boiling-point divergence.
    if pressure_kpa - p_sat <= 0.0:
        raise ValueError(
            f"saturation pressure {p_sat:.4f} kPa >= station pressure "
            f"{pressure_kpa:.3f} kPa at T={temp_c:.1f} C: air at/above the "
            f"boiling limit, W_sat diverges (Magnus valid ~-45..60 C)"
        )
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
