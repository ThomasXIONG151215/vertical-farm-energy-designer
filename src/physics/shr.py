"""
Dynamic Sensible Heat Ratio (SHR) model — Bypass-Factor / Apparatus-Dewpoint method.

Used by the HVAC device to split cooling capacity into sensible (Q_sens) and
latent (Q_lat) parts so that moisture removal can be coupled to the room mass
balance. See ``digital_twin.models.shr_model`` for the original derivation.

Physics: air passes through a DX cooling coil at apparatus dewpoint T_adp.
    W_out = BF * W_in + (1-BF) * W_sat(T_adp)
    SHR = q_sens / (q_sens + q_lat),  q_lat = h_fg * max(0, W_in - W_out)
"""

import math
from dataclasses import dataclass
from typing import Optional

from .psychrometrics import (
    saturation_humidity,
    temp_rh_to_ah,
    temp_rh_to_dewpoint,
)

__all__ = ["DynamicSHR"]


@dataclass
class DynamicSHR:
    """Dynamic SHR calculator (BF-ADP coil model)."""

    BF: float = 0.15          # Bypass factor (0.10-0.20 for a 4-row DX coil)
    cp_air: float = 1005.0    # J/(kg.K)
    h_fg: float = 2.5e6       # J/kg latent heat (~22 C)
    # shr_min: real ACs rarely put more than ~55% of capacity into latent
    # removal (SHR floor ~0.45); a lower floor over-dehumidifies.
    shr_min: float = 0.45
    shr_max: float = 1.00
    P_atm: float = 101.325    # kPa

    def calc_shr(self, T_return: float, RH_return: float, T_supply: float) -> float:
        if T_supply >= T_return:
            return 1.0
        W_return = temp_rh_to_ah(T_return, RH_return)
        T_dp = temp_rh_to_dewpoint(T_return, max(0.01, RH_return))
        T_adp = (T_supply - self.BF * T_return) / (1.0 - self.BF)
        if T_adp < 0.0:
            T_adp = 0.0
        # Humidity self-limit (physical, NOT a setpoint control): when the coil
        # surface temperature reaches/exceeds the air dewpoint no condensation
        # occurs -> SHR=1.0, dehumidification stops. This is what keeps a
        # humidity-blind AC from drying the room below the dewpoint equilibrium.
        if T_adp >= T_dp:
            return 1.0
        W_adp_sat = saturation_humidity(T_adp, self.P_atm)
        W_out = self.BF * W_return + (1.0 - self.BF) * W_adp_sat
        dW = max(0.0, W_return - W_out)
        if dW <= 0.0:
            return 1.0
        q_sens = self.cp_air * (T_return - T_supply)
        q_lat = self.h_fg * dW
        if q_sens + q_lat <= 0.0:
            return self.shr_min
        shr = q_sens / (q_sens + q_lat)
        return max(self.shr_min, min(self.shr_max, shr))

    def calc_shr_fallback(self, T_return: float, RH_return: float,
                          T_setpoint: float, T_coil_drop: float = 9.0) -> float:
        """Estimate SHR without measured supply temperature.

        T_coil_drop approximates the supply-air temperature depression
        (T_supply = T_setpoint - T_coil_drop).  Real split/unit ACs run
        supply-air drops of ~8-12 degC depending on fan speed; 9 degC is a
        mid-range value (a too-cold coil removes too much moisture).
        """
        return self.calc_shr(T_return, RH_return, T_setpoint - T_coil_drop)
