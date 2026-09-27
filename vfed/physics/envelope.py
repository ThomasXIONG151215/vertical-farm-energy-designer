"""
Building envelope heat & mass transfer model.

Replaces the sign-based ``Q_infil_base`` in the vendored ``digital_twin`` ODE with
physically consistent mass-flow infiltration (sensible + latent heat) plus an
optional envelope vapour permeance term (latent only). Heat transfer through the
envelope is UA conduction; solar gain is ``eta_solar * A_window * GHI``.

R28 (additive, default off): an optional 2R2C wall thermal-mass network
(``wall_rc_nodes=2``) adds a lumped mass node T_m coupled to the air node
through ``g_im`` (W/K) and to outdoors through ``g_em`` (W/K), storing heat in
``C_mass`` (Wh/K).  With ``wall_rc_nodes=0`` (the default) the legacy
single-node ``Q_wall = U_wall_A * (T_ext - T_z)`` is returned bit-for-bit.
The air-node integrator (``vfed/physics/ode.py``) is untouched: T_m is stepped
explicitly by the envelope itself (``step_mass``), using the substep-start
T_ext/T_z (staggered Euler, same O(dt) order as the air node).
"""

from dataclasses import dataclass
from typing import Optional, Tuple

from .psychrometrics import latent_heat_vaporization

__all__ = ["Envelope"]


@dataclass
class _WallRC:
    """2R2C wall thermal-mass network state (R28).

    Topology (g in W/K, C in Wh/K)::

                g_em                    g_im
      T_ext --/\\/\\/-- T_m --/\\/\\/-- T_z     (+ infiltration direct to T_z)
                   |                 |
                 C_mass             C_z

    The mass node carries NO source terms: it charges/discharges purely
    through the g_em (outdoor) and g_im (air) conductances -- the daytime
    store / night-time release "regenerative buffer" is the g_im channel.
    """

    C_mass: float  # Wh/K lumped mass-layer capacity
    g_im: float  # W/K mass node -> air node (inner film + half-layer conduction)
    g_em: float  # W/K mass node -> outdoors (outer half-layer + exterior film); 0 = pure internal mass
    T_m: float = 20.0  # degC mass-node temperature state (engine resets to T_z init)


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
    wall_rc_nodes : int
        R28 additive switch: 0 (default) = legacy single-node envelope
        (``Q_wall = U_wall_A*(T_ext-T_z)``, bit-for-bit unchanged); 2 = enable
        the 2R2C wall thermal-mass network (T_z air node + T_m mass node).
    C_mass : float
        Lumped mass-node heat capacity (Wh/K); required > 0 when
        ``wall_rc_nodes=2``.  ``Σ A_i·d_i·ρ_i·c_i / 3600`` over the mass layers
        (includes pure internal mass with no outdoor path, e.g. a floor slab
        on insulation).
    g_im : float
        Mass node -> air node conductance (W/K) when ``wall_rc_nodes=2``;
        required > 0.  Inner surface film (R_si ≈ 0.125 m²K/W) + inner half
        of the mass layer, areas in parallel: ``Σ A_i / (R_si + d_i/(2 k_i))``.
    g_em : float
        Mass node -> outdoor conductance (W/K) when ``wall_rc_nodes=2``;
        required >= 0 (0 for pure internal mass).  Outer half of the mass
        layer + remaining layers + exterior film: ``Σ A_i / R_i,ext``.
        With RC on, ``U_wall_A`` means the DIRECT channel only (window +
        lightweight surfaces that bypass the mass node); the steady-state
        design conductance is ``UA_dc = U_wall_A + g_em·g_im/(g_em+g_im)``.
    """

    def __init__(
        self,
        U_wall_A: float = 50.0,
        A_window: float = 0.0,
        eta_solar: float = 0.15,
        ach: float = 0.001,
        permeance: float = 0.0,
        rho_air: float = 1.2,
        cp_air: float = 1005.0,
        V_room: float = 200.0,
        wall_rc_nodes: int = 0,
        C_mass: float = 0.0,
        g_im: float = 0.0,
        g_em: float = 0.0,
    ):
        self.U_wall_A = U_wall_A
        self.A_window = A_window
        self.eta_solar = eta_solar
        self.ach = ach
        self.permeance = permeance
        self.rho_air = rho_air
        self.cp_air = cp_air
        self.V_room = V_room
        # R28: additive 2R2C wall mass network (None = legacy single node).
        if wall_rc_nodes not in (0, 2):
            raise ValueError(
                f"wall_rc_nodes must be 0 (single node, legacy) or 2 (2R2C wall "
                f"mass network), got {wall_rc_nodes!r}"
            )
        if wall_rc_nodes == 2:
            if C_mass <= 0.0:
                raise ValueError("wall_rc_nodes=2 requires C_mass > 0 Wh/K")
            if g_im <= 0.0:
                raise ValueError("wall_rc_nodes=2 requires g_im > 0 W/K")
            if g_em < 0.0:
                raise ValueError("wall_rc_nodes=2 requires g_em >= 0 W/K")
            self._rc = _WallRC(C_mass=C_mass, g_im=g_im, g_em=g_em)
        else:
            self._rc = None  # default: legacy path, zero behavioural drift

    @property
    def rc_enabled(self) -> bool:
        """True when the 2R2C wall mass network is active (wall_rc_nodes=2)."""
        return self._rc is not None

    def reset(self, T_init: float) -> None:
        """Reset the mass-node state to ``T_init`` (degC); engine calls this
        once at run start with the air-node initial temperature so both
        states start consistent."""
        if self._rc is None:
            return
        self._rc.T_m = float(T_init)

    @property
    def T_m(self) -> Optional[float]:
        """Current mass-node temperature (degC), or None when RC is off."""
        return None if self._rc is None else self._rc.T_m

    def step_mass(self, T_ext: float, T_z: float, dt: float) -> float:
        """Advance the mass node one explicit Euler step (dt seconds).

        Uses the SUBSTEP-START T_ext/T_z (staggered with the air-node
        integrator, same O(dt) ordering error); the engine calls this before
        the air-node heat balance so Q_wall sees the freshly stepped T_m.
        Only a +-100 degC divergence guard applies (no clamp: the mass node
        is a slow, large-inertia state and clamping it would mask physics).
        """
        if self._rc is None:
            raise RuntimeError("step_mass called with wall mass network disabled")
        rc = self._rc
        # C_mass is Wh/K -> J/K via x3600; g in W/K, dt in s -> energy in J.
        q_net = rc.g_em * (T_ext - rc.T_m) + rc.g_im * (T_z - rc.T_m)  # W
        T_new = rc.T_m + q_net * dt / (rc.C_mass * 3600.0)
        if not (-100.0 <= T_new <= 100.0):
            raise RuntimeError(
                f"Mass-node temperature diverged to {T_new:.1f} C -- check "
                f"wall_rc stability (C_mass={rc.C_mass:.1f} Wh/K, g_im="
                f"{rc.g_im:.1f} W/K, g_em={rc.g_em:.1f} W/K, dt={dt:.0f} s, "
                f"T_m={rc.T_m:.1f} C)"
            )
        rc.T_m = T_new
        return T_new

    # -- Heat transfer -----------------------------------------------------
    def Q_wall(self, T_ext: float, T_z: float, T_m: Optional[float] = None) -> float:
        """Conductive envelope heat flow (W). + = into room.

        Legacy path (``T_m`` is None or RC off): ``U_wall_A * (T_ext - T_z)``
        -- the historical single-node expression, unchanged.  RC path
        (``wall_rc_nodes=2``): direct channel (window + lightweight surfaces)
        plus the mass-node discharge into the air ``g_im * (T_m - T_z)``; the
        outdoor leg g_em enters only through the T_m dynamics.
        """
        if self._rc is None or T_m is None:
            return self.U_wall_A * (T_ext - T_z)
        return self.U_wall_A * (T_ext - T_z) + self._rc.g_im * (T_m - T_z)

    def Q_solar(self, solar_radiation_wm2: float) -> float:
        """Solar heat gain through glazing (W)."""
        return self.eta_solar * self.A_window * solar_radiation_wm2

    # -- Infiltration (sensible + latent) ---------------------------------
    def infiltration(
        self, T_ext: float, T_z: float, W_ext: float, W_z: float
    ) -> Tuple[float, float, float]:
        """Mass-flow infiltration with explicit sensible + latent energy.

        Returns
        -------
        (Q_sens_W, M_lat_kgs, Q_lat_W) : (float, float, float)
            Sensible heat flow (W, + into room), latent moisture flow
            (kg/s, + into room) and the latent heat carried by that
            moisture (W, + into room).  Q_lat = M_lat * L_v(T_z); together
            Q_sens_W + Q_lat_W form the complete enthalpy flux of the
            infiltrating air.  Callers MUST include Q_lat_W in the room
            heat balance or energy conservation is violated.
        """
        if self.ach <= 0.0:
            return 0.0, 0.0, 0.0
        m_dot = self.ach * self.V_room * self.rho_air / 3600.0  # kg/s
        Q_sens = m_dot * self.cp_air * (T_ext - T_z)  # W
        M_lat = m_dot * (W_ext - W_z)  # kg/s
        Q_lat = M_lat * latent_heat_vaporization(T_z) * 1000.0  # W  (kJ/kg -> J/kg)
        return Q_sens, M_lat, Q_lat

    def envelope_moisture(self, W_ext: float, W_z: float) -> float:
        """Passive moisture migration through envelope (kg/s, + into room)."""
        return self.permeance * (W_ext - W_z)
