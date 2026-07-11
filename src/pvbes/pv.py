"""
PV system model — single-diode model (SDM) at maximum-power-point.

Parametric re-implementation of the reused ``src/system.py:PVSystem`` (drop-in
for the design simulator): no numba/cuda dependency. All cell parameters are
configurable; defaults match the Jinko 78 HL4-BDV reference module.

PV power (kW) per timestep is computed from the plane-of-array irradiance
(direct + diffuse) and cell temperature (NOCT model).
"""

from dataclasses import dataclass
from typing import Dict

import numpy as np

__all__ = ["PVSystem"]


@dataclass
class PVSystem:
    eta_pv: float = 0.233          # module efficiency
    area_to_power: float = 4.3     # m^2 of module per kWp
    N_s: int = 156                 # cells in series
    I_sc_stc: float = 13.98        # A
    V_oc_stc: float = 57.34        # V
    I_mp_stc: float = 13.33        # A
    V_mp_stc: float = 46.0         # V (derived)
    alpha_sc: float = 0.045        # A/K
    beta_voc: float = -0.25        # V/K
    beta: float = -0.0029          # power temp coeff (1/K)
    NOCT: float = 45.0             # C
    T_stc: float = 25.0            # C
    eta_inv: float = 0.97          # inverter efficiency
    C_pv: float = 110.0            # $/kWp
    degradation: float = 0.004     # per year

    def cell_temperature(self, G: np.ndarray, T_amb: np.ndarray) -> np.ndarray:
        """Nominal-Operating-Cell-Temperature model."""
        G = np.asarray(G, dtype=float)
        T_amb = np.asarray(T_amb, dtype=float)
        return T_amb + (self.NOCT - 20.0) * G / 800.0

    def _sd_mpp(self, G: np.ndarray, T_cell: np.ndarray) -> np.ndarray:
        """Approximate SDM maximum-power-point power per module (W)."""
        G = np.asarray(G, dtype=float)
        T_cell = np.asarray(T_cell, dtype=float)
        I_ph = self.I_sc_stc * (1 + self.alpha_sc * (T_cell - self.T_stc)) * (G / 1000.0)
        V_oc = self.V_oc_stc + self.beta_voc * (T_cell - self.T_stc)
        I_mp = self.I_mp_stc * (1 + self.alpha_sc * (T_cell - self.T_stc)) * (G / 1000.0)
        I_mp = np.clip(I_mp, 0.0, None)
        k_v = np.clip(0.86 - 0.0005 * (G - 1000.0), 0.6, 0.9)
        V_mp = V_oc * k_v
        return I_mp * V_mp

    def calculate_pv_output(self, weather: Dict[str, np.ndarray],
                            A_pv: float) -> np.ndarray:
        """Hourly PV AC output (kW).

        weather keys: 'direct_radiation', 'diffuse_radiation', 'temperature_2m'.
        Plane-of-array irradiance = direct + diffuse (see weather_bridge.add_poa).
        """
        G = np.asarray(weather["direct_radiation"], dtype=float) + \
            np.asarray(weather["diffuse_radiation"], dtype=float)
        T_amb = np.asarray(weather["temperature_2m"], dtype=float)
        G = np.clip(G, 0.0, None)
        T_cell = self.cell_temperature(G, T_amb)
        P_module_w = self._sd_mpp(G, T_cell)
        n_modules = A_pv / self.area_to_power
        P_ac_w = P_module_w * n_modules * self.eta_inv
        P_ac_w = np.where(G <= 0.0, 0.0, P_ac_w)
        return P_ac_w / 1000.0

    def calculate_costs(self, A_pv: float) -> Dict[str, float]:
        peak_power_kwp = A_pv / self.area_to_power
        capital = peak_power_kwp * self.C_pv
        return {
            "peak_power_kwp": peak_power_kwp,
            "capital_cost": capital,
        }
