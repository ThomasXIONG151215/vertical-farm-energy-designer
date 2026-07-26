"""
HVAC (air conditioner) device model.

A fixed-speed AC maintains the room temperature setpoint via a hysteresis
thermostat. Cooling capacity is ``P_rated * COP(T_ext)``; the DynamicSHR model
splits capacity into sensible (heat removal) and latent (moisture removal) parts
so the air conditioner also acts as a latent sink coupled to the room mass balance.

The device exposes a step interface returning:
    Q_HVAC_W : net heat flux into the room (W, <0 cooling, >0 heating)
    M_hvac_kgs : moisture removal rate (kg/s)
    P_elec_W  : electrical power draw (W)
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, Optional

from ..physics.psychrometrics import temp_rh_to_ah
from ..physics.shr import DynamicSHR
from .compressor import CompressorState
from .lag import FirstOrderLag

__all__ = ["HVACDevice", "COPModel", "size_hvac"]


@dataclass
class COPModel:
    """Outdoor-temperature-dependent cooling COP.

    mode:
        "carnot"   -> eta_II * COP_carnot (second-law efficiency)
        "constant" -> always ``value``
        "linear"   -> value * (1 - k*(T_ext - T_ref))
        "table"    -> piecewise-linear over ``table`` {edge_c: cop}
    """
    mode: str = "carnot"
    value: float = 4.0
    k: float = 0.02
    T_ref: float = 25.0
    table: Dict[float, float] = field(default_factory=dict)
    eta_II: float = 0.35
    delta_T_evap: float = 8.0
    delta_T_cond: float = 15.0

    def __call__(self, T_ext: float, T_indoor: float = None) -> float:
        if self.mode == "carnot":
            Ti = T_indoor if T_indoor is not None else 22.0
            T_evap = Ti - self.delta_T_evap + 273.15
            T_cond = T_ext + self.delta_T_cond + 273.15
            cop_carnot = T_evap / max(T_cond - T_evap, 0.1)
            cop_carnot = min(cop_carnot, 50.0)
            return max(0.5, self.eta_II * cop_carnot)
        if self.mode == "linear":
            return max(1.0, min(10.0, self.value * (1.0 - self.k * (T_ext - self.T_ref))))
        if self.mode == "table":
            edges = sorted(self.table.keys())
            if not edges:
                return self.value
            if T_ext <= edges[0]:
                return self.table[edges[0]]
            if T_ext >= edges[-1]:
                return self.table[edges[-1]]
            for i in range(len(edges) - 1):
                lo, hi = edges[i], edges[i + 1]
                if lo <= T_ext <= hi:
                    c0, c1 = self.table[lo], self.table[hi]
                    t = (T_ext - lo) / (hi - lo)
                    return c0 + t * (c1 - c0)
        return self.value


class HVACDevice:
    """Fixed-speed AC with hysteresis thermostat + SHR-based latent removal."""

    def __init__(
        self,
        P_rated_w: float = 3000.0,
        cop: Optional[COPModel] = None,
        cop_heat: float = 3.0,
        heat_mode: str = "heat_pump",   # "heat_pump" | "resistive"
        P_rated_heat_w: Optional[float] = None,
        deadband_c: float = 1.0,
        min_on_s: float = 180.0,
        min_off_s: float = 180.0,
        fan_power_w: float = 70.0,
        shr: Optional[DynamicSHR] = None,
        tau_q: float = 90.0,
        tau_m: float = 60.0,
        h_fg: float = 2.5e6,
    ):
        self.P_rated = P_rated_w
        self.cop = cop or COPModel()
        self.cop_heat = cop_heat
        self.heat_mode = heat_mode
        self.P_rated_heat = P_rated_heat_w or P_rated_w
        self.h_fg = h_fg
        self.shr = shr or DynamicSHR()
        self.comp = CompressorState(
            deadband=deadband_c, min_on_s=min_on_s, min_off_s=min_off_s,
            fan_power_w=fan_power_w,
        )
        self.lag_q = FirstOrderLag(tau_rise=tau_q, tau_fall=tau_q)
        self.lag_m = FirstOrderLag(tau_rise=tau_m, tau_fall=tau_m)
        self._last_mode: str = "idle"

    def reset(self) -> None:
        self.comp.reset(False)
        self.lag_q.reset(0.0)
        self.lag_m.reset(0.0)

    def step(
        self,
        T_z: float,
        RH_z: float,
        T_ext: float,
        dt: float = 60.0,
        T_setpoint: float = 22.0,
        T_heat_setpoint: float = 18.0,
        is_heating_needed: bool = True,
    ) -> Dict[str, float]:
        """Advance one timestep.

        Returns dict with Q_HVAC_W, M_hvac_kgs, P_elec_W, mode, is_on, SHR, COP.
        """
        # Decide mode via two hysteresis bands.
        if T_z > T_setpoint:
            # Cooling demand: too warm -> demand positive.
            on = self.comp.update(T_z - T_setpoint, dt,
                                  on_threshold=0.0,
                                  off_threshold=-self.comp.deadband)
            mode = "cool"
            self._last_mode = "cool"
        elif is_heating_needed and T_z < T_heat_setpoint:
            on = self.comp.update(T_heat_setpoint - T_z, dt,
                                  on_threshold=0.0,
                                  off_threshold=-self.comp.deadband)
            mode = "heat"
            self._last_mode = "heat"
        else:
            # Within deadband: force compressor off (respects min_on).
            self.comp.update(-1e6, dt)
            on = self.comp.is_on
            mode = "idle"
            if on and self._last_mode != "idle":
                mode = self._last_mode

        Q_target, M_target, P_elec = 0.0, 0.0, 0.0
        cop = self.cop(T_ext, T_z)
        shr = 1.0
        if on and mode == "cool":
            P_elec = self.P_rated + self.comp.fan_power_w
            Q_total = self.P_rated * cop
            shr = self.shr.calc_shr_fallback(T_return=T_z, RH_return=RH_z,
                                              T_setpoint=T_setpoint)
            Q_lat = (1.0 - shr) * Q_total
            Q_target = -(Q_total - self.comp.fan_power_w)
            M_target = Q_lat / self.h_fg
        elif on and mode == "heat":
            P_elec = self.P_rated_heat + self.comp.fan_power_w
            if self.heat_mode == "heat_pump":
                Q_target = self.P_rated_heat * self.cop_heat + self.comp.fan_power_w
            else:
                Q_target = P_elec
            M_target = 0.0

        Q_act = self.lag_q.step(Q_target, dt)
        M_act = self.lag_m.step(M_target, dt)
        return {
            "Q_HVAC_W": Q_act,
            "M_hvac_kgs": M_act,
            "P_elec_W": P_elec if on else 0.0,
            "mode": mode,
            "is_on": bool(on),
            "SHR": shr,
            "COP": cop,
        }


def size_hvac(
    U_wall_A: float,
    A_window: float,
    eta_solar: float,
    ach: float,
    V_room: float,
    rho_air: float,
    cp_air: float,
    led_heat_w: float,
    equipment_power_w: float,
    cop: float,
    T_setpoint: float,
    T_design_ext: float = 35.0,
    GHI_design: float = 800.0,
    shr_design: float = 0.80,
    safety_factor: float = 1.2,
) -> float:
    """Calculate required HVAC P_rated (W) from design cooling load.

    Uses a steady-state heat balance at design outdoor conditions (hottest
    expected temperature + peak solar irradiance) with all internal loads
    running.  The result is the electrical input power needed to maintain
    ``T_setpoint``, not the cooling capacity (which is ``P_rated * COP``).

    The sensible load is divided by the design Sensible Heat Ratio (SHR) so
    that total cooling capacity accounts for both sensible and latent heat
    removal.  In a plant factory with high transpiration SHR can be as low
    as 0.6–0.8; the default of 0.80 provides a reasonable safety margin.
    """
    q_env = U_wall_A * (T_design_ext - T_setpoint)
    q_solar = eta_solar * A_window * GHI_design
    m_dot = ach * V_room * rho_air / 3600.0
    q_inf = m_dot * cp_air * (T_design_ext - T_setpoint)
    q_sens_raw = q_env + q_solar + q_inf + led_heat_w + equipment_power_w
    if q_sens_raw < 0:
        logging.warning(
            "Net sensible load is negative (%.1f W) — clamping to 0 for HVAC sizing. "
            "Check design conditions: T_ext=%.1f, T_setpoint=%.1f, "
            "q_env=%.1f, q_solar=%.1f, q_inf=%.1f, led=%.1f, equip=%.1f",
            q_sens_raw, T_design_ext, T_setpoint,
            q_env, q_solar, q_inf, led_heat_w, equipment_power_w,
        )
    q_sens = max(0.0, q_sens_raw)
    q_total = q_sens / max(shr_design, 0.1)
    return q_total / max(cop, 0.5) * safety_factor
