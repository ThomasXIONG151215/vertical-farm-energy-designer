"""
Design engine — runs the digital-twin building simulation for a project and
produces the hourly electrical load profile plus indoor climate timeseries.

The building ODE is integrated at the project timestep (default 10 min) and
aggregated to hourly load (kW) consumed by the PVBES layer. Device state
(compressor hysteresis, transient lags) is continuous across the whole year.
"""

import logging
import warnings
from typing import List, Optional

import numpy as np
import pandas as pd

from ..physics.psychrometrics import (
    temp_rh_to_ah,
    ah_to_temp_rh,
    latent_heat_vaporization,
)
from ..physics.envelope import Envelope
from ..physics.ode import RoomODESolver
from ..physics.shr import DynamicSHR
from ..devices.hvac import HVACDevice, COPModel, size_hvac
from ..devices.dehumidifier import DEHDevice, size_deh
from ..devices.led import LEDDevice
from ..plants.transpiration import TranspirationModel
from ..plants.van_henten import VanHenten
from ..weather.weather_bridge import fetch_weather
from .result import SimulationResult

__all__ = ["DesignEngine", "run_project", "full_load_warnings"]


# ── P1-7: OPEX transparency ────────────────────────────────────────────
# The bundled presets' default OPEX (labor 30000 + misc 5000 per year) is
# USD-scale and silently dominates LCOE (72-96% of its numerator) whenever
# a project YAML omits the opex section.  When that default is in effect
# AND OPEX exceeds half of the annual cost total, warn once per process:
# a sweep re-evaluates the same defaulted project for every row and would
# otherwise repeat the identical text hundreds of times.
_OPEX_DEFAULT_WARNED = False


def _warn_opex_dominance(project, annual_om: float, pct_of_cost: float) -> None:
    """P1-7: warn when silent default OPEX dominates the annual cost.

    Fires at most once per process, and only when BOTH hold: the project
    YAML had no explicit opex section (``opex_was_defaulted``) and OPEX is
    > 50% of ``annual_capital + annual_om + net_grid_cost``.  The message
    is pure ASCII (GBK-console safe) and worded distinctly from cli.py's
    capital = 0 warning (P0-5).
    """
    global _OPEX_DEFAULT_WARNED
    if _OPEX_DEFAULT_WARNED or not project.opex_was_defaulted or pct_of_cost <= 0.5:
        return
    _OPEX_DEFAULT_WARNED = True
    # warn_explicit (round 25): plain warnings.warn attached a caller
    # source-path trailer (e.g. "engine.py:1400") to every console line.
    # Same treatment as the round-18 legacy-cache notice: attribute to the
    # module-level virtual location so no filesystem path is printed.
    warnings.warn_explicit(
        f"default OPEX in effect: annual_om {annual_om:.2f} "
        f"{project.currency}/yr is {pct_of_cost * 100:.1f}% of the annual "
        f"cost total (labor 30000 + misc 5000 per year are built-in "
        f"USD-scale defaults). To silence this warning, add an explicit "
        f"opex section to your YAML and verify the amounts are in YOUR "
        f"currency.",
        UserWarning,
        "vfed.engine",
        0,
    )


def _limit_removal_by_inventory(
    M_deh_kgs,
    M_hvac_kgs,
    W_z,
    air_mass,
    dt,
    E_trans_kgs=0.0,
    M_inf_kgs=0.0,
    M_perm_kgs=0.0,
    W_setpoint_kgs=None,
):
    """Cap nominal dehumidifier/HVAC moisture removal (kg/s) to what the room
    air can actually yield in this sub-step.

    Physical basis: a dehumidifier cannot remove more water than currently
    exists as vapour in the air.  Removing beyond the inventory (down to
    W_z -> 0) is unphysical and previously had to be silently clamped by the
    ODE floor.  By capping the *flow* here instead, the actual moisture
    removed is reported honestly and the phantom condensation heat can be
    backed out of the heat balance.

    ``E_trans_kgs`` / ``M_inf_kgs`` / ``M_perm_kgs`` are the moisture sources
    arriving DURING the sub-step (P4-1d): transpiration, net infiltration and
    envelope permeance.  They are additional removal capacity, but only the
    NET source is used so a negative (drying) infiltration never inflates the
    cap — this preserves the W_z >= 0 guarantee (when net >= 0 and the cap
    binds, W_z_new lands exactly at 0).  Defaults keep the legacy 5-arg call
    bitwise identical.

    ``W_setpoint_kgs`` (optional): humidity-set-point clamp against
    overshoot.  A real VFD machine modulates down as RH approaches the set
    point, so over one 10-min control step the *average* output never draws
    the air below the set point.  The per-step model would otherwise hold the
    step-start modulation fixed for the whole 600 s and over-shoot (dark
    transition: E_trans collapses but DEH+coil run flat, RH 69 -> 23 % in one
    sub-step).  When set, only the moisture above the set point is available
    to the devices in this step (plus the net source); below the set point
    the room may only be dried passively by the net source, mirroring the
    devices having already turned off.

    Returns (M_deh_actual, M_hvac_actual, scale) where scale = actual/nominal
    (1.0 when unconstrained).  Both devices are scaled by the same factor so
    the ratio between them is preserved.
    """
    removal_nom = M_deh_kgs + M_hvac_kgs
    if removal_nom <= 0.0 or dt <= 0.0:
        return M_deh_kgs, M_hvac_kgs, 1.0
    source = max(0.0, E_trans_kgs + M_inf_kgs + M_perm_kgs)  # kg/s
    if W_setpoint_kgs is not None and W_z <= W_setpoint_kgs:
        inventory = 0.0  # at/below set point: devices must not actively dry
    else:
        inventory = max(0.0, W_z * air_mass) / dt
        if W_setpoint_kgs is not None:
            # only the vapour above the set point may be drawn this step
            inventory = max(0.0, (W_z - W_setpoint_kgs) * air_mass) / dt
    available = inventory + source  # kg/s
    if removal_nom <= available:
        return M_deh_kgs, M_hvac_kgs, 1.0
    scale = available / removal_nom
    return M_deh_kgs * scale, M_hvac_kgs * scale, scale


# ── P0-4: full-load (saturation) diagnostics ───────────────────────────
# Reporting layer only — no ODE / device behaviour is affected.  A setpoint
# the room cannot physically reach (e.g. a dark-period T_dark below the
# natural night balance temperature) shows up as the device riding ~99% of
# rated output hour after hour without ever closing the gap, so counting
# rated-capacity hours turns silent saturation into a visible warning.
_FULL_LOAD_HOURLY_FRAC = 0.99  # substep share of an hour counted as "at rated"
# HVAC: chronic saturation (share of year) or one sustained stretch indicates
# a capacity/setpoint mismatch.  Occasional full-speed hours at design-peak
# weather (a few % of the year, streaks bounded by the diurnal cycle) are
# normal and stay silent.
_FULL_LOAD_HVAC_PCT_WARN = 10.0  # % of year at rated capacity
_FULL_LOAD_HVAC_STREAK_WARN_H = 24.0  # continuous hours at rated capacity
# DEH: the VFD dehumidifier pins at m = 1 during ordinary humid periods (the
# RH proportional band keeps demand positive), so ~20-50% of the year at full
# modulation is normal operation.  Only near-continuous saturation (an
# undersized unit that can never close the RH gap) is diagnostic.
_FULL_LOAD_DEH_PCT_WARN = 60.0  # % of year at rated capacity


def _full_load_stats(full_hours) -> dict:
    """Summarise a boolean hourly "at rated capacity" mask.

    Returns ``{"hours": int, "pct": float, "max_streak_h": int}`` — the rated
    hour count, its share of the simulated year (%), and the longest
    consecutive run (h).
    """
    n = len(full_hours)
    hours = int(np.sum(full_hours))
    streak = best = 0
    for flag in full_hours:
        streak = streak + 1 if flag else 0
        if streak > best:
            best = streak
    return {
        "hours": hours,
        "pct": round(100.0 * hours / n, 2) if n else 0.0,
        "max_streak_h": int(best),
    }


def _monthly_sum(values, months) -> np.ndarray:
    """P1-3a: bucket hourly values into the 12 calendar-month totals.

    ``months`` is the hour-indexed month label array (1..12) already used for
    the engine's monthly accumulators, so the buckets stay consistent with
    monthly_hours / monthly_energy.  Returns an array of 12 sums (0 for a
    month with no hours, e.g. short weather windows).
    """
    v = np.asarray(values, dtype=float)
    out = np.zeros(12)
    for mo in range(1, 13):
        mask = months == mo
        if mask.any():
            out[mo - 1] = float(v[mask].sum())
    return out


def full_load_warnings(summary: dict) -> List[str]:
    """P0-4: setpoint-reachability warnings from ``full_load_diagnostics``.

    Pure reporting helper over the summary block produced by
    :meth:`DesignEngine.run` — returns one human-readable message per device
    whose rated-capacity statistics breach the warning criteria:

    * HVAC cooling/heating: >= 10% of the year at rated output, or one
      continuous stretch >= 24 h (a setpoint the room cannot reach saturates
      the unit every control period — the 609 T_dark=18 C failure ran 2,920
      dark hours = 33% of the year at full 3,070 W in 8 h nightly stretches,
      which only the share rule catches).
    * DEH: >= 60% of the year at rated modulation (its VFD pins at full speed
      during ordinary humid periods, so only near-continuous saturation is
      diagnostic).

    Warnings are double-sided for the HVAC (cooling saturation = room too
    warm, heating saturation = room too cold) — the reporting layer never
    changes any physics.
    """
    diag = summary.get("full_load_diagnostics") or {}
    criteria = (
        (
            "hvac_cool",
            "HVAC cooling",
            _FULL_LOAD_HVAC_PCT_WARN,
            _FULL_LOAD_HVAC_STREAK_WARN_H,
            "check T_light/T_dark vs C_z and hvac.P_rated_w",
        ),
        (
            "hvac_heat",
            "HVAC heating",
            _FULL_LOAD_HVAC_PCT_WARN,
            _FULL_LOAD_HVAC_STREAK_WARN_H,
            "check T_dark vs C_z and hvac.P_rated_heat_w",
        ),
        (
            "deh",
            "DEH",
            _FULL_LOAD_DEH_PCT_WARN,
            None,
            "check setpoints.RH vs deh sizing (M_deh_nom/P_ref_w) and C_z",
        ),
    )
    msgs: List[str] = []
    for key, label, pct_warn, streak_warn, hint in criteria:
        d = diag.get(key)
        if not d:
            continue
        fires = d.get("pct", 0.0) >= pct_warn or (
            streak_warn is not None and d.get("max_streak_h", 0) >= streak_warn
        )
        if fires:
            msgs.append(
                f"{label} at rated capacity for {d.get('hours', 0)} h "
                f"({d.get('pct', 0.0):.1f}% of year, longest run "
                f"{d.get('max_streak_h', 0)} h) -- setpoint may be unreachable, {hint}"
            )
    return msgs


def _build_devices(p, P_atm: float = 101.325):
    env = Envelope(
        U_wall_A=p.envelope.U_wall_A,
        A_window=p.envelope.A_window,
        eta_solar=p.envelope.eta_solar,
        ach=p.envelope.ach,
        permeance=p.envelope.permeance,
        rho_air=p.envelope.rho_air,
        cp_air=p.envelope.cp_air,
        V_room=p.envelope.V_room,
    )
    led = LEDDevice(
        power_w=p.led.power_w,
        light_start_hour=p.led.light_start_hour,
        photoperiod_hours=p.led.photoperiod_hours,
        heat_fraction=p.led.heat_fraction,
        auto_deduce=p.led.auto_deduce,
        efficacy=p.led.efficacy,
        ppfd_target=p.led.ppfd_target,
        covered_area=p.led.covered_area,
        spectrum=p.led.spectrum,
    )
    led_heat = led.power_w * p.led.heat_fraction

    cop = COPModel(
        mode=p.hvac.cop_mode,
        value=p.hvac.cop_value,
        k=p.hvac.cop_k,
        T_ref=p.hvac.cop_T_ref,
        eta_II=p.hvac.eta_II,
        delta_T_evap=p.hvac.delta_T_evap,
        delta_T_cond=p.hvac.delta_T_cond,
        table=p.hvac.cop_table,
    )
    cop_design = cop(p.hvac.design_T_ext, p.setpoints.T_light)

    # ── Transpiration model (needed by DEH auto-sizing) ──
    # P1-6: plant_count may come from planting density.  Load-time
    # validation (project.py) guarantees per-plant methods have a usable
    # source: explicit plant_count > 0, or plants_per_m2 in (0, 200], from
    # which the count is derived here as
    # round(plants_per_m2 x covered_area).  plant_count wins when both are
    # given.
    _tcfg = p.transpiration
    plant_count = _tcfg.plant_count
    if (
        _tcfg.method in ("per_plant", "per_plant_per_period")
        and plant_count <= 0
        and _tcfg.plants_per_m2
    ):
        plant_count = max(1, int(round(_tcfg.plants_per_m2 * led.covered_area)))
    transp = TranspirationModel(
        method=_tcfg.method,
        daily_water_L=_tcfg.daily_water_L,
        plant_count=plant_count,
        ml_per_plant_day=_tcfg.ml_per_plant_day,
        period_days=_tcfg.period_days,
        daily_water_L_period=_tcfg.daily_water_L_period,
        ml_per_plant_day_period=_tcfg.ml_per_plant_day_period,
        photoperiod_hours=p.led.photoperiod_hours,
        k_van_henten=_tcfg.k_van_henten,
        stage_factor=_tcfg.stage_factor,
        dark_transpiration_frac=_tcfg.dark_transpiration_frac,
        area_m2=led.covered_area,
    )

    # ── DEH sizing FIRST: HVAC auto-size must include the DEH's net
    # sensible heat rejection (P_comp + fan) in its design-point balance. ──
    T_sp = p.setpoints.T_light
    RH_sp = p.setpoints.RH
    W_z = temp_rh_to_ah(T_sp, RH_sp, pressure_kpa=P_atm)  # P4-7: P_atm aware

    # Design-point transpiration is delegated to the SAME configured
    # TranspirationModel used at runtime (B2 fix): van_henten goes through a
    # cycle pre-run (P3-4 peak sizing), the direct-set methods
    # (daily/per_plant/daily_per_period/per_plant_per_period) through
    # design_rate_kgs() which already returns the peak-stage rate.
    if p.transpiration.method == "van_henten":
        # MAJOR-5 (C1) + P3-4 (MAJOR): the legacy fixed X_d=0.05 "mid-cycle"
        # point is reached on day 3-4 (seedling stage) while the canopy
        # evolves to X_d≈0.45 at harvest — a ~9× DEH capacity gap at peak.
        # A light-weight pre-run evolves the Van Henten biomass over ONE
        # crop cycle at the engine operating point (no capacity constraints,
        # millisecond-scale).
        #
        # P3-4: the design load is the cycle-PEAK light-period transpiration,
        # NOT the cycle mean.  The DEH is a fixed-capacity device that must
        # hold the RH setpoint across the WHOLE cycle, including the harvest
        # stage where X_d — and therefore transpiration — is largest.
        # Mean-based sizing at 609/k_van_henten=4e-4 undersizes the DEH ~2×
        # at peak (3.70 vs 7.55 g/s) and the late-cycle RH setpoint is lost
        # (verified: last-7d RH max 68.8% vs 65.0% when peak-sized).  X_d is
        # monotone over the cycle, so the peak rate equals the harvest-stage
        # design maturity; max-tracking is robust to any growth shape.  The
        # existing size_deh(safety_factor, default 1.2) margin applies on top.
        grow = VanHenten(
            co2_ppm=p.setpoints.co2_ppm,
            c_alpha_beta=p.growth.c_alpha_beta,
            c_resp_d=p.growth.c_resp_d,
            c_pl_d=p.growth.c_pl_d,
            c_rad_phot=p.growth.c_rad_phot,
            c_co2_1=p.growth.c_co2_1,
            c_co2_2=p.growth.c_co2_2,
            c_co2_3=p.growth.c_co2_3,
            c_Gamma=p.growth.c_Gamma,
        )
        xd = p.growth.initial_dry_weight
        # P4-11: use the LED-derived PAR flux so the pre-run growth/DEH
        # sizing matches the runtime light state (identical to ppfd/par_factor
        # under auto_deduce, tracks the configured power otherwise).
        light_wm2 = led.par_wm2
        # P4-8: half-up rounding so the pre-run step count tracks the runtime
        # time-based harvest schedule (both rounded, no banker's tie).
        n_steps = max(144, int(p.setpoints.crop_cycle_days * 144.0 + 0.5))
        m_peak = 0.0
        for s in range(n_steps):
            hour = (s * 600.0 / 3600.0) % 24.0
            is_light_h = led.is_light(hour)
            t_sim = p.setpoints.T_light if is_light_h else p.setpoints.T_dark
            _, xd = grow.step(t_sim, light_wm2 if is_light_h else 0.0, xd, 600.0)
            if is_light_h:
                m_peak = max(m_peak, transp.step(T_sp, RH_sp, True, 3600.0, X_d=xd))
        m_transp = m_peak
    else:
        # daily/per_plant/daily_per_period/per_plant_per_period: pure-algebra
        # direct-set methods — no growth scaling, no T/RH dependence, so the
        # design rate IS the time-invariant light-period rate (no mean-vs-peak
        # distinction).  For the *_per_period methods design_rate_kgs()
        # returns the PEAK stage total (max over stages), so the fixed-
        # capacity DEH holds the RH setpoint across the whole cycle (P3-4
        # peak-sizing logic, applied to staged schedules).
        m_transp = transp.design_rate_kgs()

    P_ref = p.deh.P_ref_w
    if p.deh.M_deh_nom > 0:
        # New mode: nominal dehumidification (L/day) → reference power (W)
        # P_ref = M_deh_nom × 41.67 / SMER
        P_ref = p.deh.M_deh_nom * 41.6667 / max(p.deh.smer, 0.1)
        if p.deh.P_rated_max > 0:
            P_ref = min(P_ref, p.deh.P_rated_max * 1000.0)
    elif p.deh.auto_size:
        W_ext = temp_rh_to_ah(p.hvac.design_T_ext, 80.0, pressure_kpa=P_atm)  # P4-7
        m_dot = p.envelope.ach * p.envelope.V_room * p.envelope.rho_air / 3600.0
        m_inf = m_dot * max(0.0, W_ext - W_z)
        m_perm = p.envelope.permeance * max(0.0, W_ext - W_z)
        moisture_load = max(0.0, m_transp + m_inf + m_perm)
        P_ref = size_deh(moisture_load, p.deh.smer, p.deh.safety_factor)

    deh = DEHDevice(
        P_ref_w=P_ref,
        poly_e=tuple(p.deh.poly_e),
        T_mean=p.deh.T_mean,
        T_std=p.deh.T_std,
        W_mean=p.deh.W_mean,
        W_std=p.deh.W_std,
        deadband_rh=p.deh.deadband_rh,
        min_on_s=p.deh.min_on_s,
        min_off_s=p.deh.min_off_s,
        fan_power_w=p.deh.fan_power_w,
        smer=p.deh.smer,
        tau_q=p.deh.tau_q,
        tau_m=p.deh.tau_m,
        mod_band_rh=p.deh.comp_mod_band_rh,
        control=p.deh.control,
    )
    # DEH net sensible heat rejection at the design point: P_comp + fan only.
    # m_dh*L_v must NOT be added here — the transpiration portion cancels
    # with E_trans*L_v, which the HVAC balance deliberately omits (adding
    # both double-counts).
    deh_net_heat_w = deh._poly_power(T_sp, W_z) + p.deh.fan_power_w
    # P2-2 (MAJOR): the DEH condenser releases M_deh*L_v to the room.  Only
    # the transpiration portion E_trans*L_v cancels against the evaporative
    # sink omitted from the HVAC balance; infiltration/permeance moisture
    # plus the sizing safety factor is NET sensible load the HVAC must
    # reject.  m_transp is the P3-4 cycle-PEAK design value for van_henten
    # (constant design rate otherwise) and M_deh_design is sized at that
    # same point, so the residual below is the design-point condenser excess
    # the HVAC balance needs.  It is computed per project — do not hardcode
    # a "typical" figure (tracks transpiration calibration + sizing mode).
    M_deh_design = P_ref * p.deh.smer / 3.6e6  # design removal capacity, kg/s
    L_v_design = latent_heat_vaporization(T_sp) * 1000.0
    deh_latent_residual_w = max(0.0, M_deh_design - m_transp) * L_v_design
    # Write sizing back to config so CAPEX (sweep._total_capital reads the
    # config's P_ref_w / P_rated_w) reflects the computed equipment.
    if p.deh.M_deh_nom > 0 or p.deh.auto_size:
        p.deh.P_ref_w = P_ref

    P_rated = p.hvac.P_rated_w
    P_rated_heat = p.hvac.P_rated_heat_w
    if p.hvac.Q_cool_nom > 0:
        # New mode: nominal cooling capacity (kW) → rated electrical power (W)
        P_rated = p.hvac.Q_cool_nom * 1000.0 / max(cop_design, 0.5)
        P_rated_heat = p.hvac.P_rated_heat_w if p.hvac.P_rated_heat_w > 0 else P_rated
        if p.hvac.P_rated_max > 0:
            P_rated = min(P_rated, p.hvac.P_rated_max * 1000.0)
    elif p.hvac.auto_size:
        P_rated = size_hvac(
            U_wall_A=p.envelope.U_wall_A,
            A_window=p.envelope.A_window,
            eta_solar=p.envelope.eta_solar,
            ach=p.envelope.ach,
            V_room=p.envelope.V_room,
            rho_air=p.envelope.rho_air,
            cp_air=p.envelope.cp_air,
            led_heat_w=led_heat,
            equipment_power_w=p.equipment_power_w,
            cop=cop_design,
            T_setpoint=p.setpoints.T_light,
            T_design_ext=p.hvac.design_T_ext,
            shr_design=p.hvac.shr_design,
            safety_factor=p.hvac.safety_factor,
            deh_net_heat_w=deh_net_heat_w,
            deh_latent_residual_w=deh_latent_residual_w,
        )
        if P_rated <= 0:
            logging.warning(
                "HVAC auto-size returned P_rated=%.1f W -- net sensible load "
                "clamped to 0. HVAC may be undersized.",
                P_rated,
            )
        P_rated_heat = P_rated
    if p.hvac.Q_cool_nom > 0 or p.hvac.auto_size:
        p.hvac.P_rated_w = P_rated
        p.hvac.P_rated_heat_w = P_rated_heat

    hvac = HVACDevice(
        P_rated_w=P_rated,
        cop=cop,
        cop_heat=p.hvac.cop_heat,
        heat_mode=p.hvac.heat_mode,
        P_rated_heat_w=P_rated_heat,
        deadband_c=p.hvac.deadband_c,
        min_on_s=p.hvac.min_on_s,
        min_off_s=p.hvac.min_off_s,
        fan_power_w=p.hvac.fan_power_w,
        shr=DynamicSHR(BF=p.hvac.shr_BF, P_atm=P_atm, t_coil_drop=p.hvac.t_coil_drop),
        tau_q=p.hvac.tau_q,
        tau_m=p.hvac.tau_m,
        shr_rh_guard=p.hvac.shr_rh_guard,
        rh_guard_band=p.hvac.rh_guard_band,
        coil_condense_max_kgs=p.hvac.coil_condense_max_gps * 1e-3,
        mod_band_c=p.hvac.comp_mod_band_c,
        speed_curve=p.hvac.speed_curve,
    )

    ode = RoomODESolver(
        C_z=p.envelope.C_z, V_room=p.envelope.V_room, rho_air=p.envelope.rho_air, P_atm=P_atm
    )
    return env, hvac, deh, led, transp, ode


class DesignEngine:
    def __init__(self, cache_dir: Optional[str] = "weather_cache"):
        self.cache_dir = cache_dir

    def run(self, project, weather: Optional[pd.DataFrame] = None) -> SimulationResult:
        """Run a full-year simulation and return a ``SimulationResult``.

        SIDE EFFECT (P4-9): when auto-sizing is enabled (``deh.auto_size`` or
        ``hvac`` default sizing), this method writes the resulting nameplates
        back onto the caller's ``project`` object (``hvac.P_rated_w`` /
        ``P_rated_heat_w`` and ``deh.P_ref_w``) so that ``sweep._total_capital``
        reads the sized capacities for CAPEX.  The same values are also exposed
        on ``result.sizing`` (``hvac_P_rated_w`` / ``hvac_P_rated_heat_w`` /
        ``deh_P_ref_w`` / ``deh_M_design_kgs``).  Callers needing pure-function
        semantics should pass ``copy.deepcopy(project)``.
        """
        p = project
        if weather is None:
            weather = fetch_weather(
                p.site.lat,
                p.site.lon,
                p.site.year,
                tz_hours=p.site.tz_hours,
                tilt=p.site.tilt,
                azimuth=p.site.azimuth,
                cache_dir=self.cache_dir,
                city=p.site.city,
                # Round 22: weather source + GHI bias correction (additive
                # pass-through; defaults keep the open-meteo path identical).
                provider=getattr(p.site, "weather_provider", "open-meteo"),
                ghi_scale=getattr(p.site, "ghi_scale", 1.0),
            )
        # P2-2: weather provenance (fetch layer tags df.attrs) -- copy it out
        # so the reporting layer can self-evidence the weather source.  The
        # DataFrame itself is never rebuilt here, so the attrs survive; a
        # caller-supplied df without attrs degrades to an empty dict.
        weather_attrs = dict(getattr(weather, "attrs", {}) or {})
        n = len(weather)
        dt = p.space.timestep_s
        sub = max(1, int(round(3600.0 / dt)))
        if abs(sub * dt - 3600.0) > 1.0:
            raise ValueError(
                f"Timestep {dt}s does not evenly divide 3600s "
                f"(sub={sub}, modeled={sub * dt}s/h). "
                f"Choose dt that divides 3600 evenly "
                f"(e.g., 600, 900, 1200, 1800, 3600)."
            )

        T_ext = weather["temperature_2m"].values.astype(float)
        RH_ext = weather["relative_humidity_2m"].values.astype(float)
        GHI = weather["shortwave_radiation"].values.astype(float)
        hours = weather.index.hour.values.astype(float)
        months = weather.index.month.values.astype(int)
        days = weather.index.day.values.astype(int)
        direct = weather["direct_radiation"].values.astype(float)
        diffuse = weather["diffuse_radiation"].values.astype(float)

        # Validate weather input arrays — no NaN/inf allowed
        _weather_arrays = {
            "T_ext": T_ext,
            "RH_ext": RH_ext,
            "GHI": GHI,
            "direct": direct,
            "diffuse": diffuse,
        }
        for name, arr in _weather_arrays.items():
            if not np.isfinite(arr).all():
                idx = np.where(~np.isfinite(arr))[0]
                raise ValueError(
                    f"Weather array '{name}' contains {len(idx)} NaN/inf values "
                    f"at indices {idx[:5].tolist()}..."
                )

        # Surface pressure — Open-Meteo returns hPa, convert to kPa
        surface_pressure = weather.get(
            "surface_pressure",
            pd.Series([1013.25] * n, index=weather.index),
        ).values.astype(float)
        # P4-6 (MINOR): fail-fast on NaN/inf like the other weather arrays
        # (np.nanmean previously swallowed bad station-pressure data silently,
        # letting P_atm=NaN pollute the whole run).
        if not np.isfinite(surface_pressure).all():
            idx = np.where(~np.isfinite(surface_pressure))[0]
            raise ValueError(
                f"Weather array 'surface_pressure' contains {len(idx)} NaN/inf "
                f"values at indices {idx[:5].tolist()}..."
            )
        P_atm = float(np.mean(surface_pressure)) / 10.0  # hPa → kPa

        env, hvac, deh, led, transp, ode = _build_devices(p, P_atm=P_atm)

        # P0-4 full-load observation thresholds (reporting only): the HVAC
        # draws its rated electrical input when the VFD sits at m = 1
        # (cap(1) = eir(1) = 1.0), so a substep is "at rated capacity" when
        # P_elec >= 99% of rated + fan.  The DEH draw varies with T/W
        # conditions, so its modulation coefficient (m >= 0.999) is the
        # full-speed signal instead.
        hvac_cool_full_w = 0.99 * (hvac.P_rated + hvac.comp.fan_power_w)
        hvac_heat_full_w = 0.99 * (hvac.P_rated_heat + hvac.comp.fan_power_w)

        # ── plant growth model ─────────────────────────────────────────────
        grow = VanHenten(
            co2_ppm=p.setpoints.co2_ppm,
            c_alpha_beta=p.growth.c_alpha_beta,
            c_resp_d=p.growth.c_resp_d,
            c_pl_d=p.growth.c_pl_d,
            c_rad_phot=p.growth.c_rad_phot,
            c_co2_1=p.growth.c_co2_1,
            c_co2_2=p.growth.c_co2_2,
            c_co2_3=p.growth.c_co2_3,
            c_Gamma=p.growth.c_Gamma,
        )
        X_d = p.growth.initial_dry_weight
        X_d_init = p.growth.initial_dry_weight  # reset point after each harvest
        crop_area = p.led.covered_area
        # P4-8 (MINOR): time-based harvest on the full crop_cycle_days (fractional
        # days allowed) instead of int(round(...)) banker's rounding, which
        # truncated 30.5 -> 30 and desynced the pre-run from the runtime cycle.
        harvest_hours = max(24.0, p.setpoints.crop_cycle_days * 24.0)
        next_harvest_h = harvest_hours
        total_harvest_kg = 0.0

        T_z = p.setpoints.T_light
        W_z = temp_rh_to_ah(T_z, p.setpoints.RH, pressure_kpa=P_atm)
        RH_z = p.setpoints.RH

        # ── hourly output arrays ───────────────────────────────────────────
        load_kw = np.zeros(n)
        T_z_out = np.zeros(n)
        RH_z_out = np.zeros(n)
        P_hvac = np.zeros(n)
        P_deh = np.zeros(n)
        P_led = np.zeros(n)
        P_misc = np.zeros(n)
        X_d_arr = np.zeros(n)
        # P0-4: hourly "device at rated capacity" flags (reporting layer).
        hvac_cool_full_h = np.zeros(n, dtype=bool)
        hvac_heat_full_h = np.zeros(n, dtype=bool)
        deh_full_h = np.zeros(n, dtype=bool)

        # ── monthly accumulators (12 months) ───────────────────────────────
        monthly_energy = np.zeros((12, 5))  # cols: total,hvac,deh,led,misc
        monthly_harvest = np.zeros(12)
        monthly_t_sum = np.zeros(12)
        monthly_rh_sum = np.zeros(12)
        monthly_hours = np.zeros(12)
        # P1-3a: per-month transpiration water (kg) so monthly.csv can carry
        # water_m3 (= kg / 1000) and close against summary.annual_water_m3.
        monthly_water_kg = np.zeros(12)
        # typical daily: 12 months × 24 hours accumulators
        typical_load_sum = np.zeros((12, 24))
        typical_count = np.zeros((12, 24))

        total_water_kg = 0.0
        # Staged-transpiration cycle clock: hours since the last harvest.
        # The *_per_period methods map cycle_day=cycle_h/24.0 onto their stage
        # tables; cycle_h is reset in lockstep with X_d at every harvest so
        # stage boundaries never drift against the harvest cycle.
        cycle_h = 0.0
        # Moisture clamp accounting (P0-2): how often and how much water the
        # humidity integrator had to clip at the [0, W_sat] bounds.  Exposed in
        # summary["moisture_clamp_stats"] so over-dehumidification is visible.
        clamp_stats = {
            "floor_clip_events": 0,
            "floor_clip_water_kg": 0.0,
            "sat_clip_events": 0,
            "sat_clip_water_kg": 0.0,
            "temp_clip_events": 0,
            "temp_clip_deg_c": 0.0,
        }
        # Dehumidifier/HVAC performance accounting: nominal (full-capacity)
        # vs actual moisture removal.  Nominal removal is capped to the room
        # vapour inventory each sub-step, so `actual` reflects what the device
        # could physically remove and `deh_utilization` reports how much of
        # the nominal capacity is actually being used.
        deh_perf = {
            "deh_nominal_kg": 0.0,
            "deh_actual_kg": 0.0,
            "hvac_nominal_kg": 0.0,
            "hvac_actual_kg": 0.0,
            "removal_limited_events": 0,
            "removal_limited_water_kg": 0.0,
        }
        # P1-1: annual DEH COMPRESSOR energy (kWh, fan excluded) for the
        # effective-SMER report.  Same basis as the rated ``deh.smer`` (P2-5
        # convention), so effective-vs-rated is an apples-to-apples ratio.
        deh_comp_kwh = 0.0
        for h in range(n):
            energy_wh = 0.0
            hvac_wh = 0.0
            deh_wh = 0.0
            led_wh = 0.0
            t_sum, rh_sum = 0.0, 0.0
            # P0-4 full-load observation counters (reporting only, no
            # effect on the ODE or device models below).
            cool_full_s = heat_full_s = deh_full_s = 0
            hour_of_day = int(hours[h])
            month_idx = months[h] - 1  # 0-based
            # P4-10: drive lighting with the fractional hour so
            # photoperiod_hours like 16.5 are not quantized to whole hours.
            is_light_h = led.is_light(hours[h])
            for s in range(sub):
                Q_LED, P_led_s = led.step(hours[h])
                T_sp = p.setpoints.T_light if is_light_h else p.setpoints.T_dark
                hv = hvac.step(
                    T_z, RH_z, T_ext[h], dt, T_setpoint=T_sp, T_heat_setpoint=p.setpoints.T_dark
                )
                dh = deh.step(T_z, RH_z, W_z, dt, deh_setpoint=p.setpoints.RH)
                # P0-4 full-load observation (read-only on device outputs).
                if hv["mode"] == "cool" and hv["P_elec_W"] >= hvac_cool_full_w:
                    cool_full_s += 1
                elif hv["mode"] == "heat" and hv["P_elec_W"] >= hvac_heat_full_w:
                    heat_full_s += 1
                if dh["mod"] >= 0.999:
                    deh_full_s += 1
                # P4-11: runtime PAR from the LED power state (matches the
                # DEH-sizing light_wm2 above).
                light_wm2 = led.par_wm2 if is_light_h else 0.0
                E_trans = transp.step(
                    T_z,
                    RH_z,
                    is_light_h,
                    dt,
                    X_d=X_d,
                    light_wm2=light_wm2,
                    cycle_day=cycle_h / 24.0,
                )
                # Water accounting: condensate (sat_clipped_kg) is assumed to be
                # drained and NOT recovered, so transpiration is the water demand —
                # total_water_kg keeps the full E_trans tally (no sat_clip deduction).
                # P1-3a: the same tally is bucketed per calendar month for
                # monthly.csv's water_m3 column (identical values, no physics).
                total_water_kg += E_trans * dt
                monthly_water_kg[month_idx] += E_trans * dt
                cycle_h += dt / 3600.0
                _, X_d = grow.step(T_z, light_wm2, X_d, dt)
                W_ext = temp_rh_to_ah(T_ext[h], RH_ext[h], pressure_kpa=P_atm)
                Q_wall = env.Q_wall(T_ext[h], T_z)
                Q_solar = env.Q_solar(GHI[h])
                Q_inf, M_inf, Q_lat_inf = env.infiltration(T_ext[h], T_z, W_ext, W_z)
                M_perm = env.envelope_moisture(W_ext, W_z)
                # Transpiration evaporative cooling: water absorbs L_v from
                # the air as it transitions to vapour.  This energy is later
                # released when the DEH condenses the moisture (dh["Q_DH_W"]
                # already includes P_comp + M_deh × L_v).  The two cancel in
                # steady state, leaving only P_comp as net heat from moisture
                # management.
                L_v = latent_heat_vaporization(T_z) * 1000.0  # J/kg
                # Actual moisture removal: cap nominal DEH/HVAC removal to the
                # vapour inventory available this sub-step, so the devices
                # report what they can physically remove and the phantom
                # condensation heat is backed out of the heat balance.
                air_mass = p.envelope.V_room * p.envelope.rho_air
                M_deh_nom = dh["M_deh_kgs"]
                M_hvac_nom = hv["M_hvac_kgs"]
                M_deh_act, M_hvac_act, removal_scale = _limit_removal_by_inventory(
                    M_deh_nom,
                    M_hvac_nom,
                    W_z,
                    air_mass,
                    dt,
                    E_trans_kgs=E_trans,
                    M_inf_kgs=M_inf,
                    M_perm_kgs=M_perm,
                    W_setpoint_kgs=temp_rh_to_ah(T_z, p.setpoints.RH, pressure_kpa=P_atm),
                )
                # Heat-balance correction: dh["Q_DH_W"] carries the nominal
                # M_deh_nom*L_v of condensation heat, but only M_deh_act was
                # actually condensed.  Back out the phantom
                # (1-scale)*M_deh_nom*L_v.  The HVAC latent load needs no
                # correction here: hv["Q_HVAC_W"] holds only the sensible
                # portion, and the latent portion leaves via M_hvac_act in the
                # humidity equation (condensation heat rejected at the outdoor
                # condenser).
                q_removal_corr = -(1.0 - removal_scale) * M_deh_nom * L_v
                # Infiltration latent: M_inf carries L_v*M_inf of latent energy
                # into/out of the room — closed by +Q_lat_inf (P1-2).
                Q_total = (
                    hv["Q_HVAC_W"]
                    + dh["Q_DH_W"]
                    + Q_LED
                    + Q_wall
                    + Q_solar
                    + Q_inf
                    + Q_lat_inf
                    - E_trans * L_v
                    + q_removal_corr
                )
                M_total = E_trans - M_deh_act - M_hvac_act + M_inf + M_perm
                # ── humidity step with conservation accounting ─────────────
                # step_humidity clamps W_z to [0, W_sat].  The clamped water is
                # reported back so the room heat balance stays consistent:
                #   * sat_clip: moisture condensed at the saturation cap releases
                #     L_v of latent heat into the room (add it back);
                #   * floor_clip: moisture "removed" beyond what exists never
                #     condensed — the phantom condenser heat (already in
                #     Q_DEH / Q_HVAC) must be removed from the balance.
                T_z_new, tmeta = ode.step_temperature(T_z, Q_total, dt, return_meta=True)
                W_z_new, wmeta = ode.step_humidity(
                    W_z, M_total, T_z=T_z_new, dt=dt, return_meta=True
                )
                q_corr = (wmeta["sat_clipped_kg"] - wmeta["floor_clipped_kg"]) * L_v
                if q_corr != 0.0:
                    T_z_new, tmeta = ode.step_temperature(
                        T_z, Q_total + q_corr, dt, return_meta=True
                    )
                if tmeta["clipped_deg_c"] != 0.0:
                    clamp_stats["temp_clip_events"] += 1
                    clamp_stats["temp_clip_deg_c"] += tmeta["clipped_deg_c"]
                T_z = T_z_new
                W_z = W_z_new
                RH_z = ah_to_temp_rh(T_z, W_z, pressure_kpa=P_atm)
                if wmeta["floor_clipped_kg"] > 0.0:
                    clamp_stats["floor_clip_events"] += 1
                    clamp_stats["floor_clip_water_kg"] += wmeta["floor_clipped_kg"]
                if wmeta["sat_clipped_kg"] > 0.0:
                    clamp_stats["sat_clip_events"] += 1
                    clamp_stats["sat_clip_water_kg"] += wmeta["sat_clipped_kg"]
                # Dehumidifier performance bookkeeping: nominal vs actual
                # moisture removal (kg) and how often the inventory cap bound.
                deh_perf["deh_nominal_kg"] += M_deh_nom * dt
                deh_perf["deh_actual_kg"] += M_deh_act * dt
                deh_perf["hvac_nominal_kg"] += M_hvac_nom * dt
                deh_perf["hvac_actual_kg"] += M_hvac_act * dt
                # P1-1: compressor input = P_elec - fan exactly while running
                # (P_elec = P_comp + fan, device contract); zero when off.
                if dh["is_on"]:
                    deh_comp_kwh += (dh["P_elec_W"] - deh.fan_power_w) * dt / 3.6e6
                if removal_scale < 1.0:
                    deh_perf["removal_limited_events"] += 1
                    deh_perf["removal_limited_water_kg"] += (
                        (1.0 - removal_scale) * (M_deh_nom + M_hvac_nom) * dt
                    )
                P_tot = hv["P_elec_W"] + dh["P_elec_W"] + P_led_s + p.equipment_power_w
                energy_wh += P_tot * dt / 3600.0
                hvac_wh += hv["P_elec_W"] * dt / 3600.0
                deh_wh += dh["P_elec_W"] * dt / 3600.0
                led_wh += P_led_s * dt / 3600.0
                t_sum += T_z
                rh_sum += RH_z
                if not (np.isfinite(T_z) and np.isfinite(W_z)):
                    raise RuntimeError(
                        f"NaN/inf state at hour {h}, sub-step {s}: " f"T_z={T_z}, W_z={W_z}"
                    )
            # An hour counts as "at rated capacity" when >= 99% of its
            # substeps ran at full output (a full hour at rated = rated W
            # + fan, matching the E_hvac >= 0.99x(P_rated+fan) audit).
            hvac_cool_full_h[h] = cool_full_s >= sub * _FULL_LOAD_HOURLY_FRAC
            hvac_heat_full_h[h] = heat_full_s >= sub * _FULL_LOAD_HOURLY_FRAC
            deh_full_h[h] = deh_full_s >= sub * _FULL_LOAD_HOURLY_FRAC
            load_kw[h] = energy_wh / 1000.0
            T_z_out[h] = t_sum / sub
            RH_z_out[h] = rh_sum / sub
            P_hvac[h] = hvac_wh
            P_deh[h] = deh_wh
            P_led[h] = led_wh
            P_misc[h] = p.equipment_power_w  # W × 1h = Wh
            X_d_arr[h] = X_d

            # ── monthly accumulation ──
            monthly_energy[month_idx, 0] += load_kw[h]
            monthly_energy[month_idx, 1] += hvac_wh / 1000.0
            monthly_energy[month_idx, 2] += deh_wh / 1000.0
            monthly_energy[month_idx, 3] += led_wh / 1000.0
            monthly_energy[month_idx, 4] += p.equipment_power_w / 1000.0
            monthly_t_sum[month_idx] += T_z_out[h]
            monthly_rh_sum[month_idx] += RH_z_out[h]
            monthly_hours[month_idx] += 1
            # typical daily accumulator
            typical_load_sum[month_idx, hour_of_day] += load_kw[h]
            typical_count[month_idx, hour_of_day] += 1

            # ── harvest cycle (time-based, P4-8: fractional crop_cycle_days) ──
            if (h + 1) >= next_harvest_h:
                harvested = (X_d - X_d_init) * crop_area
                monthly_harvest[month_idx] += max(harvested, 0.0)
                total_harvest_kg += max(harvested, 0.0)
                X_d = X_d_init
                cycle_h = 0.0  # stage clock resets with X_d (staged methods)
                next_harvest_h += harvest_hours

        if n not in (8760, 8784):
            logging.warning(
                "weather data has %d hours (expected 8760 or leap 8784); "
                "annual totals may be scaled incorrectly",
                n,
            )
        # final partial cycle (skip if the last harvest already landed on the
        # final hour)
        # P1-3a: the end-of-year standing crop is no longer folded into the
        # last row's label month (it inflated that month's harvest by up to
        # ~15% under the rotating window, and still landed in December under
        # an aligned window).  It keeps counting toward the ANNUAL totals
        # (annual_harvest_kg unchanged) and is reported separately as
        # summary["harvest_final_standing_kg"] — monthly.harvest_kg is now
        # the pure harvest-event sum (annual − standing).
        harvest_final_standing_kg = 0.0
        if next_harvest_h > n:
            harvested = (X_d - X_d_init) * crop_area
            total_harvest_kg += max(harvested, 0.0)
            harvest_final_standing_kg = max(harvested, 0.0)

        annual_water_m3 = total_water_kg / 1000.0

        # ── monthly averages ───────────────────────────────────────────────
        monthly_hours_safe = np.maximum(monthly_hours, 1)
        monthly_avg_T = monthly_t_sum / monthly_hours_safe
        monthly_avg_RH = monthly_rh_sum / monthly_hours_safe
        months_1_12 = list(range(1, 13))

        # ── typical daily load (12 × 24) ───────────────────────────────────
        typical_count_safe = np.maximum(typical_count, 1)
        typical_load = (typical_load_sum / typical_count_safe).tolist()

        # ── climate summary ────────────────────────────────────────────────
        climate_monthly_T = []
        climate_monthly_RH = []
        climate_monthly_GHI = []
        for mo in range(1, 13):
            mask = months == mo
            climate_monthly_T.append(float(np.mean(T_ext[mask])) if mask.any() else 0.0)
            climate_monthly_RH.append(float(np.mean(RH_ext[mask])) if mask.any() else 0.0)
            climate_monthly_GHI.append(float(np.sum(GHI[mask]) / 1000.0) if mask.any() else 0.0)

        climate_summary = {
            "city": p.site.city or f"{p.site.lat:.1f}N,{p.site.lon:.1f}E",
            "lat": p.site.lat,
            "lon": p.site.lon,
            "year": p.site.year,
            "annual_avg_temp_c": float(np.mean(T_ext)),
            "annual_avg_rh_pct": float(np.mean(RH_ext)),
            "annual_ghi_kwh_m2": float(np.sum(GHI) / 1000.0),
            "monthly": {
                "month": months_1_12,
                "avg_temp_c": climate_monthly_T,
                "avg_rh_pct": climate_monthly_RH,
                "ghi_kwh_m2": climate_monthly_GHI,
            },
        }

        # ── summary KPIs ───────────────────────────────────────────────────
        total_kwh = float(np.sum(load_kw))
        dry_fraction = p.growth.dry_matter_fraction
        annual_harvest_fw_kg = total_harvest_kg / dry_fraction
        kwh_per_kg_fresh = total_kwh / max(annual_harvest_fw_kg, 1e-6)

        # ── energy breakdown ───────────────────────────────────────────────
        hvac_kwh = float(np.sum(P_hvac)) / 1000.0
        deh_kwh = float(np.sum(P_deh)) / 1000.0
        led_kwh = float(np.sum(P_led)) / 1000.0
        misc_kwh = p.equipment_power_w * n / 1000.0
        denom = max(total_kwh, 1e-6)
        energy_breakdown = {
            "hvac_pct": round(hvac_kwh / denom, 4),
            "deh_pct": round(deh_kwh / denom, 4),
            "led_pct": round(led_kwh / denom, 4),
            "misc_pct": round(misc_kwh / denom, 4),
        }

        summary = {
            "annual_harvest_kg": round(total_harvest_kg, 2),
            "annual_harvest_fw_kg": round(annual_harvest_fw_kg, 2),
            "annual_energy_kwh": round(total_kwh, 2),
            "specific_energy_kwh_per_kg": round(kwh_per_kg_fresh, 4),
            "harvest_per_month_avg_kg": round(float(np.mean(monthly_harvest)), 2),
            "dry_matter_fraction": dry_fraction,
            "annual_water_m3": round(annual_water_m3, 2),
            # Round 21 F3: annual GHI insolation (kWh/m²/yr) as a summary
            # scalar.  Same value as climate.annual_ghi_kwh_m2 (hourly
            # shortwave_radiation summed over the aligned window ÷ 1000),
            # flattened here so it actually reaches summary.csv.
            "annual_ghi_kwh_m2": round(float(np.sum(GHI) / 1000.0), 2),
            # P1-3a: annual LED / HVAC totals (previously only derivable by
            # summing the hourly timeseries) and the energy_breakdown shares
            # flattened into summary scalars so they reach summary.csv.
            "annual_led_kwh": round(led_kwh, 2),
            "annual_hvac_kwh": round(hvac_kwh, 2),
            "hvac_pct": energy_breakdown["hvac_pct"],
            "deh_pct": energy_breakdown["deh_pct"],
            "led_pct": energy_breakdown["led_pct"],
            "misc_pct": energy_breakdown["misc_pct"],
            # P1-3a: year-end standing crop, excluded from every monthly
            # bucket (see the harvest block above).  Included in
            # annual_harvest_kg / annual_harvest_fw_kg as before.
            "harvest_final_standing_kg": round(harvest_final_standing_kg, 4),
            "moisture_clamp_stats": {
                "floor_clip_events": clamp_stats["floor_clip_events"],
                "floor_clip_water_kg": round(clamp_stats["floor_clip_water_kg"], 3),
                "sat_clip_events": clamp_stats["sat_clip_events"],
                "sat_clip_water_kg": round(clamp_stats["sat_clip_water_kg"], 3),
            },
            "temperature_clamp_stats": {
                "clip_events": clamp_stats["temp_clip_events"],
                "clipped_deg_c": round(clamp_stats["temp_clip_deg_c"], 3),
            },
            "dehumidifier_performance": {
                "deh_nominal_dehum_kg": round(deh_perf["deh_nominal_kg"], 1),
                "deh_actual_dehum_kg": round(deh_perf["deh_actual_kg"], 1),
                "hvac_nominal_dehum_kg": round(deh_perf["hvac_nominal_kg"], 1),
                "hvac_actual_dehum_kg": round(deh_perf["hvac_actual_kg"], 1),
                "removal_limited_events": deh_perf["removal_limited_events"],
                "removal_limited_water_kg": round(deh_perf["removal_limited_water_kg"], 3),
                "deh_utilization": round(deh_perf["deh_actual_kg"] / deh_perf["deh_nominal_kg"], 4)
                if deh_perf["deh_nominal_kg"] > 0
                else 1.0,
            },
        }

        # P1-1: DEH effective-SMER report — the control strategy's efficiency
        # footprint made visible.  Two ratios on the same COMPRESSOR-input
        # denominator as the rated ``deh.smer`` (P2-5), so both are directly
        # comparable to the nameplate:
        #   * ``effective_smer_kg_per_kwh`` (primary, the user3 1.28-vs-2.0
        #     figure): annual NOMINAL device condensate / annual compressor
        #     energy.  Isolates the device-level control penalty — the DOE
        #     part-load SMER curve for vfd (smer_speed_mod(m) < 1 at low m),
        #     exactly 1.0 for on_off (m = 1 while running -> rated).
        #   * ``delivered_smer_kg_per_kwh``: annual ACTUAL (inventory-capped)
        #     condensate / annual compressor energy.  Adds the room-vapour
        #     inventory clamp on top, i.e. the whole-system efficiency
        #     including water the machine was paid to remove but could not.
        # ``None`` when the DEH never ran (undefined ratio, not a silent zero).
        summary["deh_smer"] = {
            "control_mode": p.deh.control,
            "effective_smer_kg_per_kwh": round(deh_perf["deh_nominal_kg"] / deh_comp_kwh, 3)
            if deh_comp_kwh > 0.0
            else None,
            "delivered_smer_kg_per_kwh": round(deh_perf["deh_actual_kg"] / deh_comp_kwh, 3)
            if deh_comp_kwh > 0.0
            else None,
            "rated_smer_kg_per_kwh": p.deh.smer,
            "deh_comp_energy_kwh": round(deh_comp_kwh, 2),
            "deh_total_energy_kwh": round(deh_kwh, 2),  # incl. fan
        }

        # P0-4: rated-capacity (full-load) diagnostics — how often each
        # device saturated.  A setpoint the room cannot reach keeps the
        # device pinned at rated output without ever closing the gap; the
        # CLI surfaces breaches via full_load_warnings().  Reporting only.
        summary["full_load_diagnostics"] = {
            "hvac_cool": _full_load_stats(hvac_cool_full_h),
            "hvac_heat": _full_load_stats(hvac_heat_full_h),
            "deh": _full_load_stats(deh_full_h),
            "criteria": {
                "hvac_pct_warn": _FULL_LOAD_HVAC_PCT_WARN,
                "hvac_streak_warn_h": _FULL_LOAD_HVAC_STREAK_WARN_H,
                "deh_pct_warn": _FULL_LOAD_DEH_PCT_WARN,
                "hourly_substep_frac": _FULL_LOAD_HOURLY_FRAC,
            },
        }

        # ── P1-4: RH compliance / disease-risk KPIs (additive, reporting
        # only) ── How well the RH setpoint was actually held, and how long
        # the room sat in the grey-mould (Botrytis) disease-risk band — the
        # control-deviation story the device-terse output (removal-limited /
        # utilization) could not tell.  All statistics run on the same
        # RH_z_out array that feeds the ts "RH_z" column, so recomputing
        # from timeseries.csv reproduces every value.  No physics touched.
        rh_set = p.setpoints.RH
        thr = p.setpoints.rh_disease_risk_threshold
        rh_exceed_hours = int(np.count_nonzero(RH_z_out > rh_set))
        rh_disease_risk_hours = int(np.count_nonzero(RH_z_out >= thr))
        summary["rh_setpoint_pct"] = rh_set
        summary["rh_exceed_hours"] = rh_exceed_hours
        summary["rh_exceed_pct"] = round(rh_exceed_hours / n, 4)
        summary["rh_p95_pct"] = round(float(np.percentile(RH_z_out, 95)), 2)
        summary["rh_max_pct"] = round(float(np.max(RH_z_out)), 2)
        summary["rh_disease_risk_hours"] = rh_disease_risk_hours
        if rh_disease_risk_hours > 0:
            warnings.warn(
                f"RH disease risk: {rh_disease_risk_hours} h/yr at or above "
                f"{thr:.1f}% RH (grey-mould risk band; RH setpoint "
                f"{rh_set:.1f}%, p95 {summary['rh_p95_pct']:.2f}%, max "
                f"{summary['rh_max_pct']:.2f}%) -- check dehumidifier "
                f"sizing/setpoints.RH",
                UserWarning,
                stacklevel=2,
            )

        # ── monthly dict ───────────────────────────────────────────────────
        # P1-3a: flat-key columns (water_m3 / harvest_fw_kg here; grid / cost
        # / PV-dispatch columns are attached by the economics branches below,
        # where the tariff and the EnergySystem perf arrays live).  Flat keys
        # keep save_monthly_csv's `__`-flattening style consistent.
        monthly = {
            "month": months_1_12,
            "energy_kwh": {
                "total": monthly_energy[:, 0].tolist(),
                "hvac": monthly_energy[:, 1].tolist(),
                "deh": monthly_energy[:, 2].tolist(),
                "led": monthly_energy[:, 3].tolist(),
                "misc": monthly_energy[:, 4].tolist(),
            },
            "harvest_kg": monthly_harvest.tolist(),
            # fresh-weight conversion of the monthly harvest events
            "harvest_fw_kg": (monthly_harvest / dry_fraction).tolist(),
            # transpiration water, m³ (= kg / 1000)
            "water_m3": (monthly_water_kg / 1000.0).tolist(),
            # P1-4: hours per month with indoor RH above the setpoint
            # (strict >); the 12 values sum to summary.rh_exceed_hours.
            "rh_exceed_hours": [
                int(v) for v in _monthly_sum((RH_z_out > rh_set).astype(float), months).tolist()
            ],
            "avg_T_z": monthly_avg_T.tolist(),
            "avg_RH_z": monthly_avg_RH.tolist(),
        }

        # ── timeseries dict ────────────────────────────────────────────────
        ts = {
            "hour_of_year": list(range(n)),
            "month": months.tolist(),
            "day": days.tolist(),
            "hour_of_day": hours.tolist(),
            "T_z": T_z_out.tolist(),
            "RH_z": RH_z_out.tolist(),
            "T_ext": T_ext.tolist(),
            "RH_ext": RH_ext.tolist(),
            "GHI": GHI.tolist(),
            "load_kw": load_kw.tolist(),
            "E_hvac_Wh": P_hvac.tolist(),
            "E_deh_Wh": P_deh.tolist(),
            "E_led_Wh": P_led.tolist(),
            "E_misc_Wh": P_misc.tolist(),
            "X_d": X_d_arr.tolist(),
            # P1-3b: ISO8601 local wall-clock timestamp per row (weather index
            # is naive local time on the aligned local calendar year) and the
            # tariff price actually applied to that hour.  Additive columns,
            # appended last (existing consumers index by name).
            "timestamp": weather.index.strftime("%Y-%m-%dT%H:%M:%S").tolist(),
            "price": [p.tariff.hourly_prices[int(h) % 24] for h in hours],
        }

        # ── typical daily ──────────────────────────────────────────────────
        typical_daily = {
            "months": months_1_12,
            "hours": list(range(24)),
            "load_kw": typical_load,
        }

        # ── keep raw arrays for sweep reuse ────────────────────────────────
        _raw = {
            "load": load_kw,
            "weather": {
                "direct_radiation": direct,
                "diffuse_radiation": diffuse,
                "temperature_2m": T_ext,
                "hour": hours,
                "shortwave_radiation": GHI,
            },
        }

        # ── energy system (optional) ───────────────────────────────────────
        # P4-2 (MAJOR): battery-only and pure-building configurations must also
        # report economics.  Gate on either PV or battery being present so
        # evaluate() matches sweep()'s handling of [0, E_bat] and [0, 0].
        if p.pv_area_m2 > 0 or p.battery_kwh > 0:
            try:
                from ..pvbes.energy_system import EnergySystem
                from ..pvbes.pv import PVSystem
                from ..pvbes.battery import BatterySystem
                from ..pvbes.grid import Tariff

                pv_sys = PVSystem(
                    eta_pv=p.pv.eta_pv,
                    area_to_power=p.pv.area_to_power,
                    N_s=p.pv.N_s,
                    I_sc_stc=p.pv.I_sc_stc,
                    V_oc_stc=p.pv.V_oc_stc,
                    I_mp_stc=p.pv.I_mp_stc,
                    V_mp_stc=p.pv.V_mp_stc,
                    alpha_sc=p.pv.alpha_sc,
                    beta_voc=p.pv.beta_voc,
                    NOCT=p.pv.NOCT,
                    eta_inv=p.pv.eta_inv,
                    C_pv=p.pv.C_pv,
                    degradation=p.pv.degradation,
                    eta_system=p.pv.eta_system,  # P6-7
                )
                bat_sys = BatterySystem(
                    c_energy=p.battery.c_energy,
                    c_rate=p.battery.c_rate,
                    eta_ch=p.battery.eta_ch,
                    eta_dis=p.battery.eta_dis,
                    soc_min=p.battery.soc_min,
                    soc_max=p.battery.soc_max,
                    cycle_life=p.battery.cycle_life,
                    allow_grid_charging=p.battery.allow_grid_charging,  # P1-2 passthrough
                )
                tariff = Tariff(
                    hourly_prices=p.tariff.hourly_prices,
                    export_price=p.tariff.export_price,
                )
                es = EnergySystem(
                    pv=pv_sys,
                    battery=bat_sys,
                    tariff=tariff,
                    interest_rate=p.interest_rate,
                )

                # Single simulation call (calculate_metrics calls
                # simulate_performance internally; call it once directly)
                perf = es.simulate_performance(
                    [p.pv_area_m2, p.battery_kwh],
                    _raw["weather"],
                    _raw["load"],
                    # Mid-life degradation year (see sweep.py: LCOE uses CRF
                    # over the lifetime, paired with average PV output).
                    year=es.lifetime // 2,
                )

                # ── P1-3a: monthly PV-dispatch columns (additive) ──────────
                # The EnergySystem perf arrays were previously consumed and
                # discarded after the summary scalars; now they also feed
                # monthly.csv so the PV/battery schedule is auditable month
                # by month.  electricity_cost is the hourly NET bill
                # (import × price − export × feed-in), matching the annual
                # net_grid_cost definition, so the 12 monthly values close
                # against summary.annual_grid_cost_net.
                _price_arr = tariff.price_array(hours)
                _cost_hourly = (
                    np.asarray(perf["grid_import"], dtype=float) * _price_arr
                    - np.asarray(perf["grid_export"], dtype=float) * tariff.export_price
                )
                monthly["grid_import_kwh"] = _monthly_sum(perf["grid_import"], months).tolist()
                monthly["electricity_cost"] = _monthly_sum(_cost_hourly, months).tolist()
                monthly["pv_generation_kwh"] = _monthly_sum(perf["pv_power"], months).tolist()
                monthly["grid_export_kwh"] = _monthly_sum(perf["grid_export"], months).tolist()
                monthly["battery_net_kwh"] = _monthly_sum(
                    np.asarray(perf["battery_discharge"], dtype=float)
                    - np.asarray(perf["battery_charge"], dtype=float),
                    months,
                ).tolist()

                # ── Cost breakdown (full-system capital, aligned with sweep.py) ──
                # PV+Battery component costs (for legacy fields)
                pv_cost = pv_sys.calculate_costs(p.pv_area_m2)
                bat_cost = bat_sys.calculate_costs(p.battery_kwh)
                pv_capital = pv_cost.get("capital_cost", 0)
                bat_capital = bat_cost.get("capital_cost", 0)

                # Full-system capital (LED+HVAC+DEH+PV+Battery+Equipment+Envelope)
                from .sweep import _total_capital, _annualized_capital, _compute_lcoe

                cap = _total_capital(p, p.pv_area_m2, p.battery_kwh)
                annual_cap = _annualized_capital(p, cap)
                annual_om = (
                    p.opex.maintenance_pct * cap["total"]
                    + p.opex.water_cost_per_m3 * annual_water_m3
                    + p.opex.labor_cost_per_year
                    + p.opex.misc_opex_per_year
                )
                annual_load = float(np.sum(perf["load"]))

                # Grid cost
                tcost = tariff.annual_cost(
                    perf["grid_import"],
                    perf["grid_export"],
                    hours,
                )
                net_grid_cost = tcost["net_grid_cost"]
                total_electricity_cost = net_grid_cost

                # LCOE using per-component CRF (aligned with sweep.py)
                lcoe = _compute_lcoe(annual_cap, annual_om, net_grid_cost, annual_load)
                capital_cost = cap["total"]

                # ── PV self-consumption & grid independence stats ──
                try:  # P4-4: non-critical detail stats may degrade gracefully
                    pv_power = perf["pv_power"]
                    bat_discharge = perf["battery_discharge"]
                    load_arr = perf["load"]
                    pv_to_load = np.minimum(pv_power, load_arr)
                    pv_self_consumed = float(np.sum(pv_to_load))
                    pv_total_gen = float(np.sum(pv_power))
                    bat_total_discharge = float(np.sum(bat_discharge))
                    grid_total_import = float(np.sum(perf["grid_import"]))
                    load_total = float(np.sum(load_arr))
                    self_consumption_rate = pv_self_consumed / max(pv_total_gen, 1e-6)
                    grid_independence = 1.0 - grid_total_import / max(load_total, 1e-6)
                    free_energy_kwh = pv_self_consumed + bat_total_discharge

                    summary["pv_generation_kwh"] = round(float(pv_total_gen), 2)
                    summary["grid_import_kwh"] = round(float(grid_total_import), 2)
                    summary["grid_export_kwh"] = round(float(np.sum(perf["grid_export"])), 2)
                    summary["battery_cycles"] = round(float(perf["battery_cycles"]), 2)
                    summary["pv_self_consumed_kwh"] = round(pv_self_consumed, 2)
                    summary["pv_self_consumption_rate"] = round(float(self_consumption_rate), 4)
                    summary["battery_discharge_kwh"] = round(bat_total_discharge, 2)
                    # Round 21 F4: battery bookkeeping (additive).  Charge is
                    # the TERMINAL-side annual throughput (sum of the hourly
                    # battery_charge array, which already contains the P4-18
                    # year-end reconciliation top-up), so the round-trip and
                    # annual-balance identities close from summary.csv alone.
                    bat_total_charge = float(np.sum(perf["battery_charge"]))
                    summary["battery_charge_kwh"] = round(bat_total_charge, 2)
                    summary["battery_recon_grid_kwh"] = round(
                        float(perf.get("battery_recon_grid_kwh", 0.0)), 2
                    )
                    summary["free_energy_kwh"] = round(free_energy_kwh, 2)
                    summary["grid_independence_pct"] = round(float(grid_independence) * 100, 1)
                except Exception as e2:
                    summary["energy_system_detail_status"] = f"failed: {e2}"
                    logging.warning(f"PVBES detail stats failed (degraded): {e2}")

                summary["total_electricity_cost"] = round(float(total_electricity_cost), 2)
                summary["lcoe"] = round(float(lcoe), 4)
                summary["specific_cost_per_kg"] = round(
                    (annual_cap + annual_om + net_grid_cost) / max(annual_harvest_fw_kg, 1e-6),
                    4,
                )
                summary["capital_total"] = round(float(capital_cost), 2)
                # Round 21 F3: the annualised capital was already computed
                # (CRF per component depreciation life, same value folded
                # into lcoe / specific_cost_per_kg) but never exported —
                # README promised the column.  Additive summary key.
                summary["annual_capital"] = round(float(annual_cap), 2)
                summary["annual_om"] = round(float(annual_om), 2)
                summary["annual_grid_cost_net"] = round(float(net_grid_cost), 2)
                # ── P1-7: OPEX transparency scalars (additive, summary only;
                # no numeric result is touched) ──
                summary["opex_labor_per_year"] = round(float(p.opex.labor_cost_per_year), 2)
                summary["opex_misc_per_year"] = round(float(p.opex.misc_opex_per_year), 2)
                _om_denom = annual_cap + annual_om + net_grid_cost
                summary["annual_om_pct_of_cost"] = (
                    round(float(annual_om / _om_denom), 4) if _om_denom > 0 else 0.0
                )
                _warn_opex_dominance(p, annual_om, summary["annual_om_pct_of_cost"])
            except Exception as e:
                # P4-4 (MAJOR): the core economics (lcoe/capital/om/grid) must
                # NOT vanish silently — re-raise so the CLI/agent layer maps it
                # to E101 (fail fast, aligned with sweep).  Non-critical detail
                # stats below degrade into energy_system_detail_status instead.
                summary["energy_system_status"] = f"failed: {e}"
                logging.warning(f"Energy system simulation failed: {e}")
                raise RuntimeError(f"Energy system evaluation failed: {e}") from e
        else:
            # P0-2 (MAJOR): grid-only economics (no PV, no battery) — the full
            # building load is served from the grid, so it is priced at the
            # project tariff exactly like sweep.py's [0, 0] row (EnergySystem
            # with zero PV/battery yields grid_import == load, grid_export == 0).
            # Previously this path silently recorded annual_grid_cost_net = 0
            # while grid_import_kwh still reported the full load, and LCOE
            # excluded electricity cost entirely — inconsistent with both the
            # enabled path and sweep.
            from ..pvbes.grid import Tariff
            from .sweep import _total_capital, _annualized_capital, _compute_lcoe

            tariff = Tariff(
                hourly_prices=p.tariff.hourly_prices,
                export_price=p.tariff.export_price,
            )
            annual_load = float(np.sum(load_kw))
            # grid_import == load, grid_export == 0 (no PV, no battery)
            tcost = tariff.annual_cost(load_kw, np.zeros_like(load_kw), hours)
            net_grid_cost = tcost["net_grid_cost"]

            # ── P1-3a: monthly grid / cost columns (additive) ──────────────
            # Same pricing basis as the annual figures above (P0-2): the full
            # building load is the grid import and is priced at the project
            # tariff hour by hour, so the 12 monthly electricity_cost values
            # close against annual_grid_cost_net.  There is no disabled-tariff
            # mode: a project without an explicit tariff section gets the
            # TariffConfig defaults (see README column dictionary).
            _price_arr = tariff.price_array(hours)
            _cost_hourly = load_kw * _price_arr  # export == 0 in this branch
            monthly["grid_import_kwh"] = monthly_energy[:, 0].tolist()
            monthly["electricity_cost"] = _monthly_sum(_cost_hourly, months).tolist()

            cap = _total_capital(p, 0.0, 0.0)
            annual_cap = _annualized_capital(p, cap)
            annual_om = (
                p.opex.maintenance_pct * cap["total"]
                + p.opex.water_cost_per_m3 * annual_water_m3
                + p.opex.labor_cost_per_year
                + p.opex.misc_opex_per_year
            )
            lcoe = _compute_lcoe(annual_cap, annual_om, net_grid_cost, annual_load)
            summary["total_electricity_cost"] = round(float(net_grid_cost), 2)
            summary["lcoe"] = round(float(lcoe), 4)
            summary["specific_cost_per_kg"] = round(
                (annual_cap + annual_om + net_grid_cost) / max(annual_harvest_fw_kg, 1e-6),
                4,
            )
            summary["capital_total"] = round(float(cap["total"]), 2)
            # Round 21 F3: same annualised-capital export as the PV branch
            # (identical _annualized_capital call); zero capital → 0.
            summary["annual_capital"] = round(float(annual_cap), 2)
            summary["annual_om"] = round(float(annual_om), 2)
            summary["annual_grid_cost_net"] = round(float(net_grid_cost), 2)
            # ── P1-7: OPEX transparency scalars (additive, summary only;
            # no numeric result is touched) ──
            summary["opex_labor_per_year"] = round(float(p.opex.labor_cost_per_year), 2)
            summary["opex_misc_per_year"] = round(float(p.opex.misc_opex_per_year), 2)
            _om_denom = annual_cap + annual_om + net_grid_cost
            summary["annual_om_pct_of_cost"] = (
                round(float(annual_om / _om_denom), 4) if _om_denom > 0 else 0.0
            )
            _warn_opex_dominance(p, annual_om, summary["annual_om_pct_of_cost"])
            summary["pv_generation_kwh"] = 0.0
            summary["grid_import_kwh"] = round(annual_load, 2)
            summary["grid_export_kwh"] = 0.0
            summary["battery_cycles"] = 0.0
            summary["pv_self_consumed_kwh"] = 0.0
            summary["pv_self_consumption_rate"] = 0.0
            summary["battery_discharge_kwh"] = 0.0
            # Round 21 F4: no battery → zero bookkeeping (same convention as
            # the other battery_* keys above).
            summary["battery_charge_kwh"] = 0.0
            summary["battery_recon_grid_kwh"] = 0.0
            summary["free_energy_kwh"] = 0.0
            summary["grid_independence_pct"] = 0.0

        # P4-9: expose the auto-sized nameplates (written back to the project
        # above) so non-side-effect consumers can read them from the result.
        sizing = {
            "hvac_P_rated_w": float(p.hvac.P_rated_w),
            "hvac_P_rated_heat_w": float(p.hvac.P_rated_heat_w),
            "deh_P_ref_w": float(p.deh.P_ref_w),
            "deh_M_design_kgs": float(p.deh.P_ref_w * p.deh.smer / 3.6e6),
        }

        return SimulationResult(
            project_name=p.name,
            currency=p.currency,
            exchange_rate=p.exchange_rate,
            summary=summary,
            climate=climate_summary,
            timeseries=ts,
            monthly=monthly,
            energy_breakdown=energy_breakdown,
            typical_daily=typical_daily,
            _raw=_raw,
            sizing=sizing,
            weather_attrs=weather_attrs,
        )


def run_project(project, weather=None):
    return DesignEngine().run(project, weather)
