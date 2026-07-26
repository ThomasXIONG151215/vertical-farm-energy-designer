"""
Room heat & mass balance ODE solver (Euler integration).

Heat balance:
    dT_z/dt = (Q_HVAC + Q_DEH + Q_LED + Q_wall + Q_solar + Q_infil) / (C_z * 3600)

Moisture (absolute humidity) balance:
    dW_z/dt = (E_trans - M_deh - M_hvac + M_infil + M_permeance) / (V_room * rho_air)

Sign convention:
    Q_HVAC < 0 cooling, > 0 heating
    Q_DEH  > 0 dehumidifier condenser heat release
    Q_LED  > 0 LED heat addition
    E_trans > 0 plant transpiration (moisture source, kg/s)
    M_deh, M_hvac > 0 moisture removal (kg/s)
"""

from typing import Tuple

__all__ = ["RoomODESolver"]


class RoomODESolver:
    """Euler room thermal + hygric balance solver."""

    def __init__(
        self,
        C_z: float,            # Equivalent heat capacity (Wh/K)
        V_room: float = 200.0, # Room volume (m^3)
        rho_air: float = 1.2,  # Air density (kg/m^3)
        T_min: float = -20.0,
        T_max: float = 60.0,
        P_atm: float = 101.325,  # Atmospheric pressure (kPa)
    ):
        # The vendored model scaled small C_z by 1000; here C_z is always Wh/K.
        self.C_z = float(C_z)
        self.V_room = float(V_room)
        self.rho_air = float(rho_air)
        self.T_min = T_min
        self.T_max = T_max
        self.P_atm = P_atm

    def step_temperature(self, T_z: float, Q_total_W: float, dt: float = 60.0) -> float:
        """Advance temperature (C) by dt seconds under total heat flux Q_total_W (W)."""
        if self.C_z <= 0:
            raise ValueError("C_z (thermal capacity) must be > 0 Wh/K")
        dT_dt = Q_total_W / (self.C_z * 3600.0)
        T_new = T_z + dT_dt * dt
        if not (-100.0 <= T_new <= 100.0):
            raise RuntimeError(
                f"Temperature diverged to {T_new:.1f}°C — check model inputs "
                f"(Q_total={Q_total_W:.0f}W, T_current={T_z:.1f}°C)")
        return max(self.T_min, min(self.T_max, T_new))

    def step_humidity(self, W_z: float, M_total_kgs: float, T_z: float = None, dt: float = 60.0) -> float:
        """Advance absolute humidity (kg/kg) by dt seconds under net moisture flow (kg/s)."""
        dW = M_total_kgs * dt / (self.V_room * self.rho_air)
        W_new = W_z + dW
        if T_z is not None:
            from .psychrometrics import saturation_vapor_pressure
            P_atm = self.P_atm
            p_sat = saturation_vapor_pressure(T_z)
            W_sat_max = 0.622 * p_sat / (P_atm - p_sat)
            W_new = min(W_new, W_sat_max)
        return max(0.0, W_new)
