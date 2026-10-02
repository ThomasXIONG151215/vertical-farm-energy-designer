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

from ..physics.psychrometrics import latent_heat_vaporization, saturation_humidity
from ..physics.shr import DynamicSHR
from .compressor import CompressorState
from .lag import FirstOrderLag

__all__ = ["HVACDevice", "COPModel", "size_hvac"]


# P2-1 (MAJOR): real-unit bounds for the Carnot cooling COP (ASHRAE Handbook —
# HVAC Systems and Equipment; air-cooled DX cooling COP ~3-6).  The old
# 0.1 K denominator floor + flat 50 cap returned COP up to 17.5 when the
# refrigerant lift collapsed (T_ext <= T_z), ~3.5x the real 4-5 of a
# mild-weather unit.
_COP_MIN_LIFT_C = 5.0  # minimum physical compressor lift (K)
_COP_COOL_MAX = 4.5  # final cooling COP ceiling

# R34/H1a: COP soft ceiling (cop_soft_cap=True) -- replaces the flat 4.5
# ceiling, which pinned ~25% of the 609 cooling hours at the cap (B3
# conservative at mild lift, B7 optimistic on the annual weighted COP: the
# two-sided "constant-cap" distortion).  Calibration anchors:
#   * GB 21455-2019 IPLV(C) four-point weights 0.023/0.415/0.461/0.101 at
#     100/75/50/25% load (low lift = mild-weather part load, so the
#     low-lift ceiling is the IPLV 25-50% region of the curve).
#   * Knee at lift = 21 K = the A25/A27 (EN 14511-3 mild, 25 C outdoor /
#     27 C indoor) lift with the default coil approaches (8 + 15 K, T_z -
#     T_ext = 2 K).  Below the knee the ceiling is FLAT at 5.25: mid of the
#     real-fleet 5-6 mild-weather EER band (B-layer B3 evidence) and inside
#     the 5.0-5.5 acceptance band.  The DELIVERED COP at A25/A27 is the
#     un-pinned Carnot 4.87 (the B-layer already judges that in-band); the
#     5.25 ceiling itself holds the 5.0-5.5 band for lower-approach presets
#     (e.g. delta_T_cond = 12 -> Carnot 5.68 -> capped 5.25).
#   * Slope 0.16/K above the knee converges the ceiling to 3.65 at the
#     A35/A27 lift (31 K), the 3.5-4 hot-lift convergence band; at A35/A27
#     the Carnot term (3.30, B1 PASS) still binds, so the rating EER holds.
#   * Weighted check with the defaults + VFD part-load boost: the GB-weight
#     IPLV of the curve is 4.18 (tests/test_27, report in
#     user-gym/benchmarks/hvac_upgrades_report.md); the flat region is the
#     only lever that touches deep-mild hours, and its level is set so the
#     609 annual weighted COP stays inside the 3.0-4.0 band.
_COP_SOFTCAP_KNEE_K = 21.0  # lift (K) where the ceiling starts to slope
_COP_SOFTCAP_FLAT = 5.25  # mild-lift (<= knee) ceiling
_COP_SOFTCAP_SLOPE = 0.16  # 1/K; (5.25 - 3.65) / (31 - 21)


def _soft_cap_cool(lift_c: float) -> float:
    """R34/H1a lift-dependent cooling-COP ceiling (see module constants)."""
    return _COP_SOFTCAP_FLAT - _COP_SOFTCAP_SLOPE * max(lift_c - _COP_SOFTCAP_KNEE_K, 0.0)


# R34/H3: defrost constants -- DOE-2.1E / EnergyPlus Engineering Reference
# ("Frost Adjustment Factors / Defrost Operation"), the public lineage the
# model is built on.  Air-to-air heat-pump heating only.
_DEFROST_MODES = ("off", "timed", "on_demand")
_DEFROST_COIL_A = 0.82  # T_coil [C] = 0.82*T_db_o - 8.589 (outdoor coil
_DEFROST_COIL_B = 8.589  #  frost-point correlation, DOE-2.1E)
_DEFROST_DW_MIN = 1e-6  # kg/kg floor of the frost-potential difference
_DEFROST_OD_K = 0.01446  # on-demand t_frac = 1/(1 + K/d_omega)
_DEFROST_OD_CAP = 0.875  # on-demand capacity  multiplier = CAP*(1 - t_frac)
_DEFROST_OD_POW = 0.954  # on-demand power     multiplier = POW*(1 - t_frac)
_DEFROST_LOAD_A = 0.01  # reverse-cycle load coefficient
_DEFROST_LOAD_TREF_C = 7.222  # C, load vanishes above this outdoor temp
_DEFROST_LOAD_QREF = 1.01667  # rated-capacity normalisation divisor

# P4-1 (BLOCKING): humidity-protection guard + physical coil condensation bound.
#   (a) Below the guard RH the coil stops condensing (SHR->1.0) — temperature-only
#       control, matching real plant-factory 'humidity blind zone' HVAC; keeps a
#       humidity-blind AC from over-dehumidifying the room below the DEH band.
#   (b) Condensate rate is capped by the coil's airflow-limited capacity
#       (~1.5 g/s per 3 kW rated electrical, real DX condensate 1-2 g/s), so a
#       capacity/SHR split can never drain the room vapour inventory in one step.
_SHR_RH_GUARD = 55.0  # % RH; below this the AC stops latent removal
_SHR_RH_GUARD_BAND = 3.0  # % RH blend width over which the guard engages
_COIL_CONDENSE_K = 5.0e-7  # kg/s condensate per W rated electrical
# (5e-7 * 3000 W = 1.5 g/s, matching the ~1.5 g/s
# per 3 kW spec above; P4-1b fix: was 5e-4 -> 1.5 kg/s)

# P2-3 (MINOR): air-source heat pump heating COP bounds and rating condition.
# EN 14511 A7/W35 rating point (7 degC outdoor / 20 degC indoor) is the
# condition at which ``cop_heat`` is defined.
_HEAT_REF_OUTDOOR_C = 7.0
_HEAT_REF_INDOOR_C = 20.0
_HEAT_COP_MIN = 1.5
_HEAT_COP_MAX = 5.0

# Variable-speed (inverter) compressor part-load curves (second-round
# research; see scratchpad section 2.7).  COP RISES as speed drops (50% load
# -> ~1.33x, 30% -> ~1.54x) because the reduced refrigerant lift dominates
# over drive losses down to ~20% speed.  Sources: Effsys2/KTH Madani,
# Szreder & Miara 2020 (Sustainability 12:10521), Fahlen 2012 (REHVA J.).
# m = modulation coefficient (speed ratio) in [0.2, 1]; both curves are
# normalised to 1.0 at m = 1.0.
_CAP_SPEED_A, _CAP_SPEED_B, _CAP_SPEED_C = 0.167, 0.991, -0.158
_EIR_SPEED_A, _EIR_SPEED_B, _EIR_SPEED_C = 0.488, 0.553, -0.041
# Conservative flat alternative (Maxa i-290 air-to-water same-T measurements):
# part-load efficiency ~flat, slight dip at deep part load.
_EIR_FLAT_A, _EIR_FLAT_B, _EIR_FLAT_C = 1.1332, -0.410, 0.280
_SPEED_M_MIN = 0.2  # lowest continuous speed (turndown, oil-return bound)


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
    cop_soft_cap: bool = False
    #   R34/H1a: true = replace the flat 4.5 cooling-COP ceiling with the
    #   lift-dependent soft ceiling ``_soft_cap_cool`` (GB 21455-2019
    #   IPLV-calibrated, see module constants).  Carnot mode only; False
    #   (default) keeps the legacy flat cap bit-for-bit.

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
            if self.cop_soft_cap:
                # R34/H1a: lift-dependent ceiling (5.25 flat below lift 21 K,
                # -0.16/K beyond) replaces the flat 4.5 pin.  The A35/A27
                # Carnot (3.30) still binds at the rating point.
                return max(0.5, min(self.eta_II * T_evap / lift, _soft_cap_cool(lift)))
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
        heat_mode: str = "heat_pump",  # "heat_pump" | "resistive"
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
        coil_condense_max_kgs: float = 0.0,  # 0 -> auto from P_rated (P4-1b)
        mod_band_c: float = 2.0,  # VFD proportional band (degC)
        speed_curve: str = "default",  # "default" | "flat" (conservative)
        crankcase_heat_w: float = 0.0,
        #   R34/H2: crankcase-heater power (W, typical 30-80).  Runs ONLY
        #   while the compressor is OFF (winter off-cycle protection): a
        #   constant parasitic draw counted in HVAC electricity AND as a
        #   room heat gain.  0.0 (default) = no heater, bit-identical.
        defrost: str = "off",
        #   R34/H3: heat-pump defrost model.  "off" (default) = no frost
        #   derating, bit-identical.  Active only for heat_mode="heat_pump"
        #   in heating mode with T_ext < defrost_threshold_c:
        #     "timed"     - discrete reverse-cycle events: every
        #                  defrost_interval_min of frost-condition heating,
        #                  a defrost_duration_min event stops the heat
        #                  delivery (COP x 0), draws the DOE-2.1E
        #                  reverse-cycle load from the room and burns the
        #                  rated electrical draw.  Annualised multiplier =
        #                  duration/interval.
        #     "on_demand" - DOE-2.1E continuous frost-adjustment factors
        #                  (T_coil = 0.82*T_ext - 8.589; d_omega vs the
        #                  coil frost point; capacity x 0.875*(1-t_frac),
        #                  power x 0.954*(1-t_frac), reverse-cycle load
        #                  averaged over the heating operation).
        defrost_threshold_c: float = 4.0,
        #   Outdoor temperature below which frost conditions are assumed
        #   (DOE-2.1E timed threshold; typical 4-7 C).
        defrost_interval_min: float = 90.0,  # timed cycle interval (min)
        defrost_duration_min: float = 5.0,  # timed defrost duration (min)
    ):
        if defrost not in _DEFROST_MODES:
            raise ValueError(
                f"defrost must be one of {'|'.join(_DEFROST_MODES)}, got {defrost!r}"
            )
        if defrost != "off":
            if heat_mode != "heat_pump":
                raise ValueError(
                    f"defrost='{defrost}' models heat-pump coil frost but "
                    f"heat_mode={heat_mode!r}; set heat_mode='heat_pump' or "
                    f"defrost='off'."
                )
            if defrost_interval_min <= 0.0 or defrost_duration_min <= 0.0:
                raise ValueError(
                    f"defrost_interval_min ({defrost_interval_min}) and "
                    f"defrost_duration_min ({defrost_duration_min}) must be > 0 min."
                )
            if defrost_duration_min >= defrost_interval_min:
                raise ValueError(
                    f"defrost_duration_min ({defrost_duration_min}) must be < "
                    f"defrost_interval_min ({defrost_interval_min}) or the unit "
                    f"never leaves defrost."
                )
        self.P_rated = P_rated_w
        self.cop = cop or COPModel()
        self.cop_heat = max(0.5, cop_heat)
        self.heat_mode = heat_mode
        self.P_rated_heat = P_rated_heat_w or P_rated_w
        self.shr = shr or DynamicSHR()
        self.shr_rh_guard = shr_rh_guard
        self.rh_guard_band = max(rh_guard_band, 1e-6)
        self.m_coil_max_kgs = (
            coil_condense_max_kgs
            if coil_condense_max_kgs > 0.0
            else _COIL_CONDENSE_K * self.P_rated
        )
        self.mod_band_c = mod_band_c
        self.speed_curve = speed_curve
        self.crankcase_heat_w = max(0.0, crankcase_heat_w)
        self.defrost = defrost
        self.defrost_threshold_c = defrost_threshold_c
        self._defrost_interval_s = defrost_interval_min * 60.0
        self._defrost_duration_s = defrost_duration_min * 60.0
        # R34/H3 defrost state (timed event scheduler + energy metering).
        self._t_frost_run_s = 0.0  # heating seconds under the threshold
        self._defrost_remaining_s = 0.0  # >0 while inside a timed event
        self.defrost_events = 0
        self.energy_defrost_j = 0.0  # J attributed to defrost operation
        self.energy_crankcase_j = 0.0  # J of crankcase-heater draw
        self.comp = CompressorState(
            deadband=deadband_c,
            min_on_s=min_on_s,
            min_off_s=min_off_s,
            fan_power_w=fan_power_w,
            proportional_band=mod_band_c,
            m_min=_SPEED_M_MIN,
        )
        self.lag_q = FirstOrderLag(tau_rise=tau_q, tau_fall=tau_q)
        self.lag_m = FirstOrderLag(tau_rise=tau_m, tau_fall=tau_m)
        self._last_mode: str = "idle"

    def _cap_speed_mod(self, m: float) -> float:
        """Capacity modifier vs speed ratio (variable-speed compressor)."""
        m = min(max(m, _SPEED_M_MIN), 1.0)
        return _CAP_SPEED_A + _CAP_SPEED_B * m + _CAP_SPEED_C * m * m

    def _eir_speed_mod(self, m: float) -> float:
        """EIR modifier vs speed ratio.  EIR = 1/COP, so a value < 1 means
        part-load COP is BETTER than full-load (inverter units)."""
        m = min(max(m, _SPEED_M_MIN), 1.0)
        if self.speed_curve == "flat":
            return _EIR_FLAT_A + _EIR_FLAT_B * m + _EIR_FLAT_C * m * m
        return _EIR_SPEED_A + _EIR_SPEED_B * m + _EIR_SPEED_C * m * m

    def reset(self) -> None:
        self.comp.reset(False)
        self.lag_q.reset(0.0)
        self.lag_m.reset(0.0)
        # R34/H3: defrost scheduler + meters restart clean (device-level
        # semantics only; the engine builds a fresh device per run).
        self._t_frost_run_s = 0.0
        self._defrost_remaining_s = 0.0
        self.defrost_events = 0
        self.energy_defrost_j = 0.0
        self.energy_crankcase_j = 0.0

    def _reverse_cycle_load_w(self, T_ext: float, t_frac: float) -> float:
        """DOE-2.1E reverse-cycle defrost load (W, heat drawn FROM the room).

        Q_defrost = 0.01 * t_frac * (7.222 - T_db,o) * (Q_rated / 1.01667)
        with Q_rated the rated HEATING delivery (P_rated_heat * cop_heat at
        the A7/W35 rating point, W).  During a timed defrost event the
        instantaneous rate applies (t_frac = 1); on_demand uses the
        time-averaged t_frac over the heating operation.
        """
        Q_rated_heat = self.P_rated_heat * max(self.cop_heat, 0.5)
        return max(
            0.0,
            _DEFROST_LOAD_A
            * t_frac
            * (_DEFROST_LOAD_TREF_C - T_ext)
            * (Q_rated_heat / _DEFROST_LOAD_QREF),
        )

    def _defrost_heat_step(
        self, T_ext: float, W_ext: Optional[float], dt: float, Q_machine: float,
        P_machine: float,
    ):
        """R34/H3: one heat-pump heating substep under frost conditions.

        Called only when ``defrost != "off"``, the mode is "heat" and
        ``T_ext < defrost_threshold_c``.  Returns the final
        ``(Q_target, P_elec, defrost_frac)``; the fan terms are added here
        because a timed event stops the indoor fan with the delivery.
        """
        fan = self.comp.fan_power_w
        if self.defrost == "timed":
            if self._defrost_remaining_s > 0.0:
                # Inside an event: heating COP x 0 over the event share of
                # the substep (the reversed indoor coil DRAWS heat from the
                # room at the DOE-2.1E instantaneous rate) while the
                # compressor burns its rated draw; the fan is off with the
                # delivery.  A duration shorter than dt (5 min event vs a
                # 10-min substep) is blended by time fraction so the event
                # ENERGY stays exact at coarse timesteps.
                duty_df = min(self._defrost_remaining_s, dt) / dt
                self._defrost_remaining_s -= dt
                self.energy_defrost_j += duty_df * self.P_rated_heat * dt
                if self._defrost_remaining_s <= 0.0:
                    self._defrost_remaining_s = 0.0
                    self._t_frost_run_s = 0.0
                return (
                    (1.0 - duty_df) * (Q_machine + fan)
                    - duty_df * self._reverse_cycle_load_w(T_ext, 1.0),
                    (1.0 - duty_df) * (P_machine + fan) + duty_df * self.P_rated_heat,
                    duty_df,
                )
            self._t_frost_run_s += dt
            if self._t_frost_run_s >= self._defrost_interval_s:
                self._defrost_remaining_s = self._defrost_duration_s
                self.defrost_events += 1
            return (Q_machine + fan, P_machine + fan, 0.0)
        # on_demand: DOE-2.1E continuous frost-adjustment factors.  No frost
        # potential (outdoor air drier than the coil frost point) leaves the
        # step untouched -- demand defrost never fires on dry coils.
        if W_ext is None:
            raise ValueError(
                "defrost='on_demand' needs the outdoor humidity ratio W_ext "
                "(kg/kg) each step (frost severity is humidity-driven); the "
                "engine passes it -- direct device callers must too."
            )
        T_coil = _DEFROST_COIL_A * T_ext - _DEFROST_COIL_B
        w_sat_coil = saturation_humidity(T_coil)
        if W_ext <= w_sat_coil:
            return (Q_machine + fan, P_machine + fan, 0.0)
        d_omega = max(_DEFROST_DW_MIN, W_ext - w_sat_coil)
        t_frac = 1.0 / (1.0 + _DEFROST_OD_K / d_omega)
        cap_mult = max(0.0, _DEFROST_OD_CAP * (1.0 - t_frac))
        pow_mult = max(0.0, _DEFROST_OD_POW * (1.0 - t_frac))
        # Defrost-attributable share of the draw: the multiplier's cut of
        # the machine power (reporting only; the balance uses P_elec).
        if pow_mult < 1.0:
            self.energy_defrost_j += P_machine * (1.0 - pow_mult) * dt
        return (
            Q_machine * cap_mult + fan - self._reverse_cycle_load_w(T_ext, t_frac),
            P_machine * pow_mult + fan,
            t_frac,
        )

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
        T_cond = T_z + dT_evap + 273.15  # indoor coil (condenser)
        T_evap = T_ext - dT_cond + 273.15  # outdoor coil (evaporator)
        lift = max(T_cond - T_evap, _COP_MIN_LIFT_C)
        cop_carnot = T_cond / lift
        T_cond_ref = _HEAT_REF_INDOOR_C + dT_evap + 273.15
        T_evap_ref = _HEAT_REF_OUTDOOR_C - dT_cond + 273.15
        lift_ref = max(T_cond_ref - T_evap_ref, _COP_MIN_LIFT_C)
        cop_carnot_ref = T_cond_ref / lift_ref
        return max(_HEAT_COP_MIN, min(self.cop_heat * cop_carnot / cop_carnot_ref, _HEAT_COP_MAX))

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
        W_ext: Optional[float] = None,
        #   R34/H3: outdoor humidity ratio (kg/kg); consumed by the
        #   on_demand defrost factors only (ignored on the default path).
    ) -> Dict[str, float]:
        """Advance one timestep.

        Returns dict with Q_HVAC_W, M_hvac_kgs, P_elec_W, mode, is_on, SHR,
        COP plus the R34 additive keys defrosting / defrost_frac.
        """
        # Decide mode via two hysteresis bands.  The compressor returns a
        # modulation coefficient m in [0,1] (VFD): 0 = OFF, m_min..1 = speed
        # ratio.  m=1 only when the deviation reaches the proportional band.
        if T_z > T_setpoint:
            # Cooling demand: too warm -> demand positive.
            mod = self.comp.update(
                T_z - T_setpoint, dt, on_threshold=0.0, off_threshold=-self.comp.deadband
            )
            mode = "cool"
            self._last_mode = "cool"
        elif is_heating_needed and T_z < T_heat_setpoint:
            mod = self.comp.update(
                T_heat_setpoint - T_z, dt, on_threshold=0.0, off_threshold=-self.comp.deadband
            )
            mode = "heat"
            self._last_mode = "heat"
        else:
            # Within deadband: force compressor off (respects min_on).
            mod = self.comp.update(-1e6, dt)
            mode = "idle"
            if self.comp.is_on and self._last_mode != "idle":
                mode = self._last_mode

        Q_target, M_target, P_elec = 0.0, 0.0, 0.0
        cop = self.cop(T_ext, T_z)
        shr = 1.0
        defrost_frac = 0.0  # R34/H3 reporting state (0.0 on every legacy path)
        if mod > 0.0 and mode == "cool":
            # P2-7 (MINOR, documented simplification): the indoor fan is tied
            # to the compressor — fan power and fan heat are counted only
            # while the compressor runs.  Real units often keep the fan on
            # briefly after compressor stop (~70 W, <1% of rated draw); the
            # simplification is retained for low cost and minimal energy
            # impact.
            cap = self._cap_speed_mod(mod)
            eir = self._eir_speed_mod(mod)
            Q_total = self.P_rated * cop * cap
            P_elec = self.P_rated * cap * eir + self.comp.fan_power_w
            shr = self.shr.calc_shr_fallback(T_return=T_z, RH_return=RH_z, T_setpoint=T_setpoint)
            # P4-1 (BLOCKING): humidity-protection guard (below the guard RH
            # the coil stops condensing, so a humidity-blind AC cannot over-
            # dry the room) + physical coil condensate-rate bound (capped by
            # the coil's airflow-limited capacity, ~1.5 g/s per 3 kW rated,
            # independent of the COP-scaled Q_total).  Together these stop the
            # single-step vapour-inventory drain that collapsed winter/night
            # RH to ~2% (see P4-1 in scratchpad).  Q_total already scales
            # with the VFD modulation m, so the coil condensate rate scales
            # down automatically at part load — the night-time switch-off
            # overshoot (m~0.5 -> half condensate) is resolved by modulation.
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
            M_target = min(
                Q_lat / (latent_heat_vaporization(T_supply) * 1000.0), self.m_coil_max_kgs
            )
        elif mod > 0.0 and mode == "heat":
            if self.heat_mode == "heat_pump":
                cap = self._cap_speed_mod(mod)
                eir = self._eir_speed_mod(mod)
                # Machine terms are split from the fan so the defrost branch
                # can scale/replace them; with defrost off (or above the
                # frost threshold) the re-assembly below evaluates the SAME
                # float operations as the legacy single expression
                # (bit-for-bit zero drift).
                Q_machine = self.P_rated_heat * self._cop_heat_at(T_ext, T_z) * cap
                P_machine = self.P_rated_heat * cap * eir
                # P2-3: heating COP degrades with outdoor temperature instead
                # of the old flat cop_heat (see _cop_heat_at).  R34/H3: frost
                # derating engages only for heat-pump heating below the
                # threshold and only when the switch is on.
                if self.defrost == "off" or T_ext >= self.defrost_threshold_c:
                    Q_target = Q_machine + self.comp.fan_power_w
                    P_elec = P_machine + self.comp.fan_power_w
                else:
                    Q_target, P_elec, defrost_frac = self._defrost_heat_step(
                        T_ext, W_ext, dt, Q_machine, P_machine
                    )
            else:
                # Resistive: no compressor COP curve — power follows the VFD
                # modulation m linearly, COP = 1.
                P_elec = self.P_rated_heat * mod + self.comp.fan_power_w
                Q_target = P_elec
            M_target = 0.0

        # R34/H2: crankcase heater runs while the compressor is OFF — a
        # constant parasitic draw counted in HVAC electricity AND as a room
        # heat gain (resistive heat, no coil lag).  Guarded so the default
        # 0 W path never perturbs a float (bitwise zero drift).
        q_crank = 0.0
        if self.crankcase_heat_w > 0.0 and mod <= 0.0:
            q_crank = self.crankcase_heat_w
            self.energy_crankcase_j += q_crank * dt

        Q_act = self.lag_q.step(Q_target, dt)
        M_act = self.lag_m.step(M_target, dt)
        if q_crank != 0.0:
            Q_act = Q_act + q_crank
        P_out = P_elec if mod > 0.0 else 0.0
        if q_crank != 0.0:
            P_out = P_out + q_crank
        return {
            "Q_HVAC_W": Q_act,
            "M_hvac_kgs": M_act,
            "P_elec_W": P_out,
            "mode": mode,
            "is_on": bool(mod > 0.0),
            "mod": mod,
            "SHR": shr,
            "COP": cop,
            # R34/H3 additive reporting keys: live defrost state (1.0 inside
            # a timed event, the DOE-2.1E t_frac under on_demand, else 0.0).
            "defrosting": defrost_frac > 0.0,
            "defrost_frac": defrost_frac,
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
    q_sens_raw = (
        q_env
        + q_solar
        + q_inf
        + led_heat_w
        + equipment_power_w
        + deh_net_heat_w
        + deh_latent_residual_w
    )
    if q_sens_raw < 0:
        logging.warning(
            "Net sensible load is negative (%.1f W) -- clamping to 0 for HVAC sizing. "
            "Check design conditions: T_ext=%.1f, T_setpoint=%.1f, "
            "q_env=%.1f, q_solar=%.1f, q_inf=%.1f, led=%.1f, equip=%.1f, "
            "deh=%.1f, deh_lat=%.1f",
            q_sens_raw,
            T_design_ext,
            T_setpoint,
            q_env,
            q_solar,
            q_inf,
            led_heat_w,
            equipment_power_w,
            deh_net_heat_w,
            deh_latent_residual_w,
        )
    q_sens = max(0.0, q_sens_raw)
    q_total = q_sens / max(shr_design, 0.1)
    return q_total / max(cop, 0.5) * safety_factor
