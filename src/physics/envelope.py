"""
Building envelope heat & mass transfer model.

Replaces the sign-based ``Q_infil_base`` in the vendored ``digital_twin`` ODE with
physically consistent mass-flow infiltration (sensible + latent heat) plus an
optional envelope vapour permeance term (latent only). Heat transfer through the
envelope is UA conduction; solar gain is ``eta_solar * A_window * GHI``.
"""

from typing import Tuple
import math

from .psychrometrics import temp_rh_to_ah

__all__ = ["Envelope"]


class Envelope:
    """Envelope thermal + hygric model.

    Parameters
    ----------
    U_wall_A : float
        Overall envelope conductance UA (W/K).
    A_window : float
        Effective window / glazed area (m^2).
    eta_solar : float
        Solar heat gain coefficient (fraction of incident irradiance admitted as heat).
    ach : float
        Air changes per hour from infiltration / leakage (1/h). Drives the mass-flow
        sensible + latent exchange with outdoor air.
    permeance : float
        Envelope vapour permeance coefficient (kg/(s·(kg/kg))) — passive moisture
        migration through the envelope driven by the indoor/outdoor AH gradient.
        Set to 0 to disable.
    rho_air : float
        Air density (kg/m^3).
    cp_air : float
        Specific heat of air (J/(kg·K)).
    """

    def __init__(
        self,
        U_wall_A: float = 50.0,
        A_window: float = 0.0,
        eta_solar: float = 0.15,
        ach: float = 0.5,
        permeance: float = 0.0,
        rho_air: float = 1.2,
        cp_air: float = 1005.0,
        V_room: float = 200.0,
    ):
        self.U_wall_A = U_wall_A
        self.A_window = A_window
        self.eta_solar = eta_solar
        self.ach = ach
        self.permeance = permeance
        self.rho_air = rho_air
        self.cp_air = cp_air
        self.V_room = V_room

    # -- Heat transfer -----------------------------------------------------
    def Q_wall(self, T_ext: float, T_z: float) -> float:
        """Conductive envelope heat flow (W). + = into room."""
        return self.U_wall_A * (T_ext - T_z)

    def Q_solar(self, solar_radiation_wm2: float) -> float:
        """Solar heat gain through glazing (W)."""
        return self.eta_solar * self.A_window * solar_radiation_wm2

    # -- Infiltration (sensible + latent) ---------------------------------
    def infiltration(self, T_ext: float, T_z: float,
                     W_ext: float, W_z: float) -> Tuple[float, float]:
        """Mass-flow infiltration.

        Returns
        -------
        (Q_infil_W, M_infil_kgs) : (float, float)
            Sensible heat flow (W, + into room) and latent moisture flow
            (kg/s, + into room).
        """
        if self.ach <= 0.0:
            return 0.0, 0.0
        m_dot = self.ach * self.V_room * self.rho_air / 3600.0  # kg/s
        Q_sens = m_dot * self.cp_air * (T_ext - T_z)             # W
        M_lat = m_dot * (W_ext - W_z)                            # kg/s
        return Q_sens, M_lat

    def envelope_moisture(self, W_ext: float, W_z: float) -> float:
        """Passive moisture migration through envelope (kg/s, + into room)."""
        return self.permeance * (W_ext - W_z)
