"""
Pump device model for irrigation / cooling water circulation.

Calculates pump electrical power from flow rate, total head, pump efficiency,
and motor efficiency.  The pump runs when the LED is on (photoperiod coupling)
in the default configuration.
"""

from dataclasses import dataclass

__all__ = ["PumpDevice"]


@dataclass
class PumpDevice:
    """Simple constant-flow pump with fixed head and efficiency.

    Power is computed from the hydraulic power equation:

        P_hydraulic [W] = rho * g * flow_rate [m³/s] * head [m]
        P_elec   [W] = P_hydraulic / (eta_pump * eta_motor)

    Typical values for a PFAL recirculating irrigation pump:
        flow_rate   ≈ 0.5–2.0 L/s   (1.8–7.2 m³/h)
        head        ≈ 5–15 m
        eta_pump    ≈ 0.55–0.75
        eta_motor   ≈ 0.85–0.95
    """

    flow_rate_Ls: float = 1.0  # L/s (water flow)
    head_m: float = 10.0  # m (total dynamic head)
    eta_pump: float = 0.65  # hydraulic efficiency
    eta_motor: float = 0.90  # motor/drive efficiency
    rho: float = 1000.0  # kg/m³ (water density)
    g: float = 9.81  # m/s²

    def power_w(self) -> float:
        """Return steady-state electrical power draw (W)."""
        q = self.flow_rate_Ls / 1000.0  # L/s → m³/s
        p_hyd = self.rho * self.g * q * self.head_m
        eta = max(self.eta_pump * self.eta_motor, 0.1)
        return p_hyd / eta

    def step(self, is_light: bool, dt: float = 60.0) -> dict:
        """Return ``{Q_pump_W, P_elec_W, flow_rate_m3s}`` for one timestep."""
        on = is_light  # pump runs with the photoperiod
        p_elec = self.power_w() if on else 0.0
        return {
            "Q_pump_W": p_elec,  # all electrical power → heat to room
            "P_elec_W": p_elec,
            "flow_rate_m3s": self.flow_rate_Ls / 1000.0 if on else 0.0,
        }
