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

from ..physics.psychrometrics import latent_heat_vaporization, temp_rh_to_ah
from ..physics.shr import DynamicSHR
from .compressor import CompressorState
from .lag import FirstOrderLag

__all__ = ["HVACDevice", "COPModel", "size_hvac"]


# P2-1 (MAJOR): real-unit bounds for the Carnot cooling COP (ASHRAE Handbook —
# HVAC Systems and Equipment; air-cooled DX cooling COP ~3-6).  The old
# 0.1 K denominator floor + flat 50 cap returned COP up to 17.5 when the
# refrigerant lift collapsed (T_ext <= T_z), ~3.5x the real 4-5 of a
# mild-weather unit.
_COP_MIN_LIFT_C = 5.0    # minimum physical compressor lift (K)
_COP_COOL_MAX = 4.5      # final cooling COP ceiling

# P4-1 (BLOCKING): humidity-protection guard + physical coil condensation bound.
#   (a) Below the guard RH the coil stops condensing (SHR->1.0) — temperature-only
#       control, matching real plant-factory 'humidity blind zone' HVAC; keeps a
#       humidity-blind AC from over-dehumidifying the room below the DEH band.
#   (b) Condensate rate is capped by the coil's airflow-limited capacity
#       (~1.5 g/s per 3 kW rated electrical, real DX condensate 1-2 g/s), so a
#       capacity/SHR split can never drain the room vapour inventory in one step.
_SHR_RH_GUARD = 55.0            # % RH; below this the AC stops latent removal
_SHR_RH_GUARD_BAND = 3.0        # % RH blend width over which the guard engages
_COIL_CONDENSE_K = 5.0e-7       # kg/s condensate per W rated electrical
                                # (5e-7 * 3000 W = 1.5 g/s, matching the ~1.5 g/s
                                # per 3 kW spec above; P4-1b fix: was 5e-4 -> 1.5 kg/s)

# P2-3 (MINOR): air-source heat pump heating COP bounds and rating condition.
# EN 14511 A7/W35 rating point (7 degC outdoor / 20 degC indoor) is the
# condition at which ``cop_heat`` is defined.
_HEAT_REF_OUTDOOR_C = 7.0
_HEAT_REF_INDOOR_C = 20.0
_HEAT_COP_MIN = 1.5
_HEAT_COP_MAX = 5.0


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
            # P2-1 (MAJOR): the old 0.1 K denominator floor + flat 50 cap on
            # cop_carnot returned up to 17.5 when T_ext <= T_z (refrigerant
            # lift collapses) — ~3.5x the real 4-5 of a mild-weather unit.
            # A physical minimum compressor lift (~5 K, real split systems
            # never run below it) replaces the denominator hack, and the 50
            # cap is dropped in favour of a ceiling on the *final* COP, which
            # keeps the model inside real-unit bounds (air-cooled DX cooling
            # COP ~3-6, ASHRAE Handbook HVAC Systems & Equipment).
            lift = max(T_cond - T_evap, _COP_MIN_LIFT_C)
            return max(0.5, min(self.eta_II * T_evap / lift, _COP_COOL_MAX))
        if self.mode == "linear":
            return max(1.0, min(10.0, self.value * (1.0 - self.k * (T_ext - self.T_ref))))
        if self.mode == "table":
            edges = sorted(self.table.keys())
            if not edges:
                return max(0.5, self.value)
            if T_ext <= edges[0]:
                return max(0.5, self.table[edges[0]])
            if T_ext >= edges[-1]:
                return max(0.5, self.table[edges[-1]])
            for i in range(len(edges) - 1):
                lo, hi = edges[i], edges[i + 1]
                if lo <= T_ext <= hi:
                    c0, c1 = self.table[lo], self.table[hi]
                    t = (T_ext - lo) / (hi - lo)
                    return max(0.5, c0 + t * (c1 - c0))
        # unknown mode / constant: floor the COP so a bad value can never flip
        # the cooling cycle into a heater (see config-side guards in project.py)
        return max(0.5, self.value)


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
        shr_rh_guard: float = _SHR_RH_GUARD,
        rh_guard_band: float = _SHR_RH_GUARD_BAND,
        coil_condense_max_kgs: float = 0.0,   # 0 -> auto from P_rated (P4-1b)
    ):
        self.P_rated = P_rated_w
        self.cop = cop or COPModel()
        self.cop_heat = max(0.5, cop_heat)
        self.heat_mode = heat_mode
        self.P_rated_heat = P_rated_heat_w or P_rated_w
        self.shr = shr or DynamicSHR()
        self.shr_rh_guard = shr_rh_guard
        self.rh_guard_band = max(rh_guard_band, 1e-6)
        self.m_coil_max_kgs = (coil_condense_max_kgs if coil_condense_max_kgs > 0.0
                               else _COIL_CONDENSE_K * self.P_rated)
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

    def _cop_heat_at(self, T_ext: float, T_z: float) -> float:
        """Outdoor-temperature-dependent heating COP (heat_pump mode only).

        P2-3 (MINOR): the old flat ``cop_heat`` ignored T_ext; real air-source
        heat pumps degrade sharply in the cold (COP ~1.8-2.0 at T_ext=-10 C,
        ~3-3.5 at 5 C, ~4-5 at 15 C).  The rating-point ``cop_heat`` (defined
        at the EN 14511 A7/W35 condition, 7 C outdoor / 20 C indoor) is scaled
        by the ratio of the Carnot heating COP at the current vs rating
        condition.  Coil-approach terms reuse the cooling model's
        delta_T_evap (indoor coil, heating condenser) / delta_T_cond (outdoor
        coil, heating evaporator) so no new configuration is introduced.
        """
        dT_evap = self.cop.delta_T_evap
        dT_cond = self.cop.delta_T_cond
        T_cond = T_z + dT_evap + 273.15            # indoor coil (condenser)
        T_evap = T_ext - dT_cond + 273.15          # outdoor coil (evaporator)
        lift = max(T_cond - T_evap, _COP_MIN_LIFT_C)
        cop_carnot = T_cond / lift
        T_cond_ref = _HEAT_REF_INDOOR_C + dT_evap + 273.15
        T_evap_ref = _HEAT_REF_OUTDOOR_C - dT_cond + 273.15
        lift_ref = max(T_cond_ref - T_evap_ref, _COP_MIN_LIFT_C)
        cop_carnot_ref = T_cond_ref / lift_ref
        return max(_HEAT_COP_MIN,
                   min(self.cop_heat * cop_carnot / cop_carnot_ref,
                       _HEAT_COP_MAX))

    def _apply_rh_guard(self, shr: float, RH_z: float) -> float:
        """Humidity-protection guard (P4-1a): below ``shr_rh_guard`` % RH the
        coil stops condensing (SHR -> 1.0), blended over ``rh_guard_band``.

        A control action, not a coil-physics change — a temperature-only AC
        must not actively dry the room in the DEH 'humidity blind zone'.  When
        the guard lifts SHR to 1.0 all capacity shifts to sensible cooling,
        identical to the existing T_adp >= T_dp self-limiting behaviour in
        DynamicSHR (both mean "stop latent removal, keep sensible removal").
        """
        g = self.shr_rh_guard
        if RH_z >= g + self.rh_guard_band:
            return shr
        if RH_z <= g:
            return 1.0
        w = (RH_z - g) / self.rh_guard_band
        return 1.0 + (shr - 1.0) * w

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
            # P2-7 (MINOR, documented simplification): the indoor fan is tied
            # to the compressor — fan power and fan heat are counted only
            # while the compressor runs.  Real units often keep the fan on
            # briefly after compressor stop (~70 W, <1% of rated draw); the
            # simplification is retained for low cost and minimal energy
            # impact.
            P_elec = self.P_rated + self.comp.fan_power_w
            Q_total = self.P_rated * cop
            shr = self.shr.calc_shr_fallback(T_return=T_z, RH_return=RH_z,
                                              T_setpoint=T_setpoint)
            # P4-1 (BLOCKING): humidity-protection guard (below the guard RH
            # the coil stops condensing, so a humidity-blind AC cannot over-
            # dry the room) + physical coil condensate-rate bound (capped by
            # the coil's airflow-limited capacity, ~1.5 g/s per 3 kW rated,
            # independent of the COP-scaled Q_total).  Together these stop the
            # single-step vapour-inventory drain that collapsed winter/night
            # RH to ~2% (see P4-1 in scratchpad).
            shr = self._apply_rh_guard(shr, RH_z)
            Q_lat = (1.0 - shr) * Q_total
            # Only the sensible portion cools the air in the T-equation.  The
            # latent portion is removed as moisture (M_target -> W-equation),
            # and its condensation heat is rejected at the outdoor condenser
            # (T_cond = T_ext).  Counting Q_lat in Q_target as well would
            # double-count the latent removal in the room enthalpy balance.
            Q_target = -(shr * Q_total - self.comp.fan_power_w)
            # MINOR-7 (D): latent heat evaluated at the coil supply-air
            # temperature (T_setpoint - t_coil_drop, same convention as the
            # DynamicSHR fallback) so M_target shares one L_v source with the
            # room enthalpy balance.
            T_supply = T_setpoint - self.shr.t_coil_drop
            M_target = min(Q_lat / (latent_heat_vaporization(T_supply) * 1000.0),
                           self.m_coil_max_kgs)
        elif on and mode == "heat":
            P_elec = self.P_rated_heat + self.comp.fan_power_w
            if self.heat_mode == "heat_pump":
                # P2-3: heating COP degrades with outdoor temperature instead
                # of the old flat cop_heat (see _cop_heat_at).
                Q_target = (self.P_rated_heat * self._cop_heat_at(T_ext, T_z)
                            + self.comp.fan_power_w)
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
    deh_net_heat_w: float = 0.0,
    deh_latent_residual_w: float = 0.0,
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

    ``deh_net_heat_w`` is the dehumidifier's net sensible heat rejection at
    the design point (P_comp + fan only).

    ``deh_latent_residual_w`` is the DEH condenser latent heat that does NOT
    cancel against transpiration (P2-2, MAJOR).  The DEH is sized for
    m_transp + m_inf + m_perm (infiltration + envelope permeance + safety
    factor); only the transpiration portion E_trans*L_v cancels against the
    evaporative sink already omitted from this balance.  The residual
    (M_deh_design - E_trans_design)*L_v is a genuine net sensible load the
    HVAC must reject — its magnitude varies per project (transpiration
    calibration + sizing mode), so the engine computes and passes it.  Must
    be supplied by the caller (engine); defaults to 0 for backward
    compatibility.
    """
    q_env = U_wall_A * (T_design_ext - T_setpoint)
    q_solar = eta_solar * A_window * GHI_design
    m_dot = ach * V_room * rho_air / 3600.0
    q_inf = m_dot * cp_air * (T_design_ext - T_setpoint)
    q_sens_raw = (q_env + q_solar + q_inf + led_heat_w
                  + equipment_power_w + deh_net_heat_w
                  + deh_latent_residual_w)
    if q_sens_raw < 0:
        logging.warning(
            "Net sensible load is negative (%.1f W) — clamping to 0 for HVAC sizing. "
            "Check design conditions: T_ext=%.1f, T_setpoint=%.1f, "
            "q_env=%.1f, q_solar=%.1f, q_inf=%.1f, led=%.1f, equip=%.1f, "
            "deh=%.1f, deh_lat=%.1f",
            q_sens_raw, T_design_ext, T_setpoint,
            q_env, q_solar, q_inf, led_heat_w, equipment_power_w,
            deh_net_heat_w, deh_latent_residual_w,
        )
    q_sens = max(0.0, q_sens_raw)
    q_total = q_sens / max(shr_design, 0.1)
    return q_total / max(cop, 0.5) * safety_factor
