"""
Design engine — runs the digital-twin building simulation for a project and
produces the hourly electrical load profile plus indoor climate timeseries.

The building ODE is integrated at the project timestep (default 10 min) and
aggregated to hourly load (kW) consumed by the PVBES layer. Device state
(compressor hysteresis, transient lags) is continuous across the whole year.
"""

import logging
from typing import Dict, Optional

import numpy as np
import pandas as pd

from ..physics.psychrometrics import (
    temp_rh_to_ah, ah_to_temp_rh, compute_vpd, latent_heat_vaporization,
)
from ..physics.envelope import Envelope
from ..physics.ode import RoomODESolver
from ..physics.shr import DynamicSHR
from ..devices.hvac import HVACDevice, COPModel, size_hvac
from ..devices.dehumidifier import DEHDevice, size_deh
from ..devices.led import LEDDevice
from ..devices.compressor import CompressorState
from ..plants.transpiration import TranspirationModel
from ..plants.van_henten import VanHenten
from ..weather.weather_bridge import fetch_weather
from .result import SimulationResult

__all__ = ["DesignEngine", "run_project"]


def _limit_removal_by_inventory(M_deh_kgs, M_hvac_kgs, W_z, air_mass, dt):
    """Cap nominal dehumidifier/HVAC moisture removal (kg/s) to what the room
    air can actually yield in this sub-step.

    Physical basis: a dehumidifier cannot remove more water than currently
    exists as vapour in the air.  Removing beyond the inventory (down to
    W_z -> 0) is unphysical and previously had to be silently clamped by the
    ODE floor.  By capping the *flow* here instead, the actual moisture
    removed is reported honestly and the phantom condensation heat can be
    backed out of the heat balance.

    Returns (M_deh_actual, M_hvac_actual, scale) where scale = actual/nominal
    (1.0 when unconstrained).  Both devices are scaled by the same factor so
    the ratio between them is preserved.
    """
    removal_nom = M_deh_kgs + M_hvac_kgs
    if removal_nom <= 0.0 or dt <= 0.0:
        return M_deh_kgs, M_hvac_kgs, 1.0
    available = max(0.0, W_z * air_mass) / dt  # kg/s
    if removal_nom <= available:
        return M_deh_kgs, M_hvac_kgs, 1.0
    scale = available / removal_nom
    return M_deh_kgs * scale, M_hvac_kgs * scale, scale


def _build_devices(p, P_atm: float = 101.325):
    env = Envelope(
        U_wall_A=p.envelope.U_wall_A, A_window=p.envelope.A_window,
        eta_solar=p.envelope.eta_solar, ach=p.envelope.ach,
        permeance=p.envelope.permeance, rho_air=p.envelope.rho_air,
        cp_air=p.envelope.cp_air, V_room=p.envelope.V_room,
    )
    led = LEDDevice(power_w=p.led.power_w,
                    light_start_hour=p.led.light_start_hour,
                    photoperiod_hours=p.led.photoperiod_hours,
                    heat_fraction=p.led.heat_fraction,
                    auto_deduce=p.led.auto_deduce,
                    efficacy=p.led.efficacy,
                    ppfd_target=p.led.ppfd_target,
                    covered_area=p.led.covered_area,
                    spectrum=p.led.spectrum)
    led_heat = led.power_w * p.led.heat_fraction

    cop = COPModel(mode=p.hvac.cop_mode, value=p.hvac.cop_value,
                   k=p.hvac.cop_k, T_ref=p.hvac.cop_T_ref,
                   eta_II=p.hvac.eta_II,
                   delta_T_evap=p.hvac.delta_T_evap,
                   delta_T_cond=p.hvac.delta_T_cond,
                   table=p.hvac.cop_table)
    cop_design = cop(p.hvac.design_T_ext, p.setpoints.T_light)

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
            U_wall_A=p.envelope.U_wall_A, A_window=p.envelope.A_window,
            eta_solar=p.envelope.eta_solar, ach=p.envelope.ach,
            V_room=p.envelope.V_room, rho_air=p.envelope.rho_air,
            cp_air=p.envelope.cp_air, led_heat_w=led_heat,
            equipment_power_w=p.equipment_power_w, cop=cop_design,
            T_setpoint=p.setpoints.T_light,
            T_design_ext=p.hvac.design_T_ext,
            shr_design=p.hvac.shr_design,
            safety_factor=p.hvac.safety_factor,
        )
        if P_rated <= 0:
            logging.warning(
                "HVAC auto-size returned P_rated=%.1f W — net sensible load "
                "clamped to 0. HVAC may be undersized.", P_rated,
            )
        P_rated_heat = P_rated

    hvac = HVACDevice(
        P_rated_w=P_rated, cop=cop, cop_heat=p.hvac.cop_heat,
        heat_mode=p.hvac.heat_mode, P_rated_heat_w=P_rated_heat,
        deadband_c=p.hvac.deadband_c, min_on_s=p.hvac.min_on_s,
        min_off_s=p.hvac.min_off_s, fan_power_w=p.hvac.fan_power_w,
        shr=DynamicSHR(BF=p.hvac.shr_BF, P_atm=P_atm,
                       t_coil_drop=p.hvac.t_coil_drop),
        tau_q=p.hvac.tau_q, tau_m=p.hvac.tau_m,
    )

    transp = TranspirationModel(
        method=p.transpiration.method, E_max_kgs=p.transpiration.E_max_kgs,
        daily_water_L=p.transpiration.daily_water_L,
        plant_count=p.transpiration.plant_count,
        ml_per_plant_day=p.transpiration.ml_per_plant_day,
        photoperiod_hours=p.led.photoperiod_hours,
        k_vpd=p.transpiration.k_vpd,
        k_van_henten=p.transpiration.k_van_henten,
        stage_factor=p.transpiration.stage_factor,
        g_stomata=p.transpiration.g_stomata,
        r_a=p.transpiration.r_a,
        r_n_canopy=p.transpiration.r_n_canopy,
        area_m2=led.covered_area,
    )
    P_ref = p.deh.P_ref_w
    if p.deh.M_deh_nom > 0:
        # New mode: nominal dehumidification (L/day) → reference power (W)
        # P_ref = M_deh_nom × 41.67 / SMER
        P_ref = p.deh.M_deh_nom * 41.6667 / max(p.deh.smer, 0.1)
        if p.deh.P_rated_max > 0:
            P_ref = min(P_ref, p.deh.P_rated_max * 1000.0)
    elif p.deh.auto_size:
        T_sp = p.setpoints.T_light
        RH_sp = p.setpoints.RH
        W_z = temp_rh_to_ah(T_sp, RH_sp)
        W_ext = temp_rh_to_ah(p.hvac.design_T_ext, 80.0)
        # Design-point transpiration is delegated to the SAME configured
        # TranspirationModel used at runtime (B2 fix): constant/daily/
        # per_plant/vpd/stomatal/van_henten are all handled by step().
        # step() is evaluated at light-on with the T_light/RH setpoints;
        # X_d=0.05 is a mid-cycle canopy dry weight (kg/m²) for "van_henten".
        m_transp = transp.step(T_sp, RH_sp, True, 3600.0, X_d=0.05)
        m_dot = p.envelope.ach * p.envelope.V_room * p.envelope.rho_air / 3600.0
        m_inf = m_dot * max(0.0, W_ext - W_z)
        m_perm = p.envelope.permeance * max(0.0, W_ext - W_z)
        moisture_load = max(0.0, m_transp + m_inf + m_perm)
        P_ref = size_deh(moisture_load, p.deh.smer, p.deh.safety_factor)

    deh = DEHDevice(
        P_ref_w=P_ref, poly_e=tuple(p.deh.poly_e),
        T_mean=p.deh.T_mean, T_std=p.deh.T_std, W_mean=p.deh.W_mean,
        W_std=p.deh.W_std,
        deadband_rh=p.deh.deadband_rh, min_on_s=p.deh.min_on_s,
        min_off_s=p.deh.min_off_s, fan_power_w=p.deh.fan_power_w,
        smer=p.deh.smer,
        tau_q=p.deh.tau_q, tau_m=p.deh.tau_m,
    )
    ode = RoomODESolver(C_z=p.envelope.C_z, V_room=p.envelope.V_room,
                        rho_air=p.envelope.rho_air, P_atm=P_atm)
    return env, hvac, deh, led, transp, ode


class DesignEngine:
    def __init__(self, cache_dir: Optional[str] = "weather_cache"):
        self.cache_dir = cache_dir

    def run(self, project, weather: Optional[pd.DataFrame] = None) -> SimulationResult:
        p = project
        if weather is None:
            weather = fetch_weather(
                p.site.lat, p.site.lon, p.site.year, tz_hours=p.site.tz_hours,
                tilt=p.site.tilt, azimuth=p.site.azimuth, cache_dir=self.cache_dir,
                city=p.site.city,
            )
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
            "T_ext": T_ext, "RH_ext": RH_ext, "GHI": GHI,
            "direct": direct, "diffuse": diffuse,
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
            "surface_pressure", pd.Series([1013.25] * n, index=weather.index),
        ).values.astype(float)
        P_atm = float(np.nanmean(surface_pressure)) / 10.0  # hPa → kPa

        env, hvac, deh, led, transp, ode = _build_devices(p, P_atm=P_atm)

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
        harvest_days = max(1, int(round(p.setpoints.crop_cycle_days)))
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

        # ── monthly accumulators (12 months) ───────────────────────────────
        monthly_energy = np.zeros((12, 5))  # cols: total,hvac,deh,led,misc
        monthly_harvest = np.zeros(12)
        monthly_t_sum = np.zeros(12)
        monthly_rh_sum = np.zeros(12)
        monthly_hours = np.zeros(12)
        # typical daily: 12 months × 24 hours accumulators
        typical_load_sum = np.zeros((12, 24))
        typical_count = np.zeros((12, 24))

        total_water_kg = 0.0
        # Moisture clamp accounting (P0-2): how often and how much water the
        # humidity integrator had to clip at the [0, W_sat] bounds.  Exposed in
        # summary["moisture_clamp_stats"] so over-dehumidification is visible.
        clamp_stats = {
            "floor_clip_events": 0,
            "floor_clip_water_kg": 0.0,
            "sat_clip_events": 0,
            "sat_clip_water_kg": 0.0,
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
        for h in range(n):
            energy_wh = 0.0
            hvac_wh = 0.0
            deh_wh = 0.0
            led_wh = 0.0
            t_sum, rh_sum = 0.0, 0.0
            hour_of_day = int(hours[h])
            month_idx = months[h] - 1  # 0-based
            is_light_h = led.is_light(hour_of_day)
            for s in range(sub):
                Q_LED, P_led_s = led.step(hour_of_day)
                T_sp = p.setpoints.T_light if is_light_h else p.setpoints.T_dark
                hv = hvac.step(T_z, RH_z, T_ext[h], dt,
                               T_setpoint=T_sp,
                               T_heat_setpoint=p.setpoints.T_dark)
                dh = deh.step(T_z, RH_z, W_z, dt, deh_setpoint=p.setpoints.RH)
                light_wm2 = (p.led.ppfd_target / led.par_factor
                             if is_light_h else 0.0)
                E_trans = transp.step(T_z, RH_z, is_light_h, dt, X_d=X_d,
                                      light_wm2=light_wm2)
                # Water accounting: condensate (sat_clipped_kg) is assumed to be
                # drained and NOT recovered, so transpiration is the water demand —
                # total_water_kg keeps the full E_trans tally (no sat_clip deduction).
                total_water_kg += E_trans * dt
                _, X_d = grow.step(T_z, light_wm2, X_d, dt)
                W_ext = temp_rh_to_ah(T_ext[h], RH_ext[h], pressure_kpa=P_atm)
                Q_wall = env.Q_wall(T_ext[h], T_z)
                Q_solar = env.Q_solar(GHI[h])
                Q_inf, M_inf = env.infiltration(T_ext[h], T_z, W_ext, W_z)
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
                    M_deh_nom, M_hvac_nom, W_z, air_mass, dt)
                # Heat-balance correction: the capped moisture would have
                # released L_v into the room via the DEH condenser (+), or been
                # carried out of the room as latent heat by the HVAC (−).  Back
                # both out proportionally to the capped removal.
                q_removal_corr = (1.0 - removal_scale) * (
                    M_hvac_nom - M_deh_nom) * L_v
                Q_total = (hv["Q_HVAC_W"] + dh["Q_DH_W"] + Q_LED +
                           Q_wall + Q_solar + Q_inf - E_trans * L_v
                           + q_removal_corr)
                M_total = (E_trans - M_deh_act - M_hvac_act
                           + M_inf + M_perm)
                # ── humidity step with conservation accounting ─────────────
                # step_humidity clamps W_z to [0, W_sat].  The clamped water is
                # reported back so the room heat balance stays consistent:
                #   * sat_clip: moisture condensed at the saturation cap releases
                #     L_v of latent heat into the room (add it back);
                #   * floor_clip: moisture "removed" beyond what exists never
                #     condensed — the phantom condenser heat (already in
                #     Q_DEH / Q_HVAC) must be removed from the balance.
                T_z_new = ode.step_temperature(T_z, Q_total, dt)
                W_z_new, wmeta = ode.step_humidity(
                    W_z, M_total, T_z=T_z_new, dt=dt, return_meta=True)
                q_corr = (wmeta["sat_clipped_kg"] - wmeta["floor_clipped_kg"]) * L_v
                if q_corr != 0.0:
                    T_z_new = ode.step_temperature(T_z, Q_total + q_corr, dt)
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
                if removal_scale < 1.0:
                    deh_perf["removal_limited_events"] += 1
                    deh_perf["removal_limited_water_kg"] += (
                        (1.0 - removal_scale) * (M_deh_nom + M_hvac_nom) * dt)
                P_tot = (hv["P_elec_W"] + dh["P_elec_W"] + P_led_s +
                         p.equipment_power_w)
                energy_wh += P_tot * dt / 3600.0
                hvac_wh += hv["P_elec_W"] * dt / 3600.0
                deh_wh += dh["P_elec_W"] * dt / 3600.0
                led_wh += P_led_s * dt / 3600.0
                t_sum += T_z
                rh_sum += RH_z
                if not (np.isfinite(T_z) and np.isfinite(W_z)):
                    raise RuntimeError(
                        f"NaN/inf state at hour {h}, sub-step {s}: "
                        f"T_z={T_z}, W_z={W_z}"
                    )
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

            # ── harvest cycle ──
            if (h + 1) % 24 == 0:
                day = (h + 1) // 24
                if day % harvest_days == 0:
                    harvested = (X_d - X_d_init) * crop_area
                    monthly_harvest[month_idx] += max(harvested, 0.0)
                    total_harvest_kg += max(harvested, 0.0)
                    X_d = X_d_init

        if n not in (8760, 8784):
            logging.warning(
                "weather data has %d hours (expected 8760 or leap 8784); "
                "annual totals may be scaled incorrectly", n
            )
        # final partial cycle (skip if already harvested on last day)
        _last_day = n // 24
        _last_day_harvested = (_last_day % harvest_days == 0) and (n % 24 == 0)
        if not _last_day_harvested:
            harvested = (X_d - X_d_init) * crop_area
            total_harvest_kg += max(harvested, 0.0)
            monthly_harvest[months[-1] - 1] += max(harvested, 0.0)

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
            "lat": p.site.lat, "lon": p.site.lon, "year": p.site.year,
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
            "moisture_clamp_stats": {
                "floor_clip_events": clamp_stats["floor_clip_events"],
                "floor_clip_water_kg": round(clamp_stats["floor_clip_water_kg"], 3),
                "sat_clip_events": clamp_stats["sat_clip_events"],
                "sat_clip_water_kg": round(clamp_stats["sat_clip_water_kg"], 3),
            },
            "dehumidifier_performance": {
                "deh_nominal_dehum_kg": round(deh_perf["deh_nominal_kg"], 1),
                "deh_actual_dehum_kg": round(deh_perf["deh_actual_kg"], 1),
                "hvac_nominal_dehum_kg": round(deh_perf["hvac_nominal_kg"], 1),
                "hvac_actual_dehum_kg": round(deh_perf["hvac_actual_kg"], 1),
                "removal_limited_events": deh_perf["removal_limited_events"],
                "removal_limited_water_kg": round(
                    deh_perf["removal_limited_water_kg"], 3),
                "deh_utilization": round(
                    deh_perf["deh_actual_kg"] / deh_perf["deh_nominal_kg"], 4)
                    if deh_perf["deh_nominal_kg"] > 0 else 1.0,
            },
        }

        # ── monthly dict ───────────────────────────────────────────────────
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
        if p.pv_area_m2 > 0:
            try:
                from ..pvbes.energy_system import EnergySystem
                from ..pvbes.pv import PVSystem
                from ..pvbes.battery import BatterySystem
                from ..pvbes.grid import Tariff

                pv_sys = PVSystem(
                    eta_pv=p.pv.eta_pv, area_to_power=p.pv.area_to_power,
                    N_s=p.pv.N_s, I_sc_stc=p.pv.I_sc_stc,
                    V_oc_stc=p.pv.V_oc_stc, I_mp_stc=p.pv.I_mp_stc,
                    V_mp_stc=p.pv.V_mp_stc, alpha_sc=p.pv.alpha_sc,
                    beta_voc=p.pv.beta_voc, NOCT=p.pv.NOCT,
                    eta_inv=p.pv.eta_inv,
                )
                bat_sys = BatterySystem(
                    c_energy=p.battery.c_energy, c_rate=p.battery.c_rate,
                    eta_ch=p.battery.eta_ch, eta_dis=p.battery.eta_dis,
                    soc_min=p.battery.soc_min, soc_max=p.battery.soc_max,
                    cycle_life=p.battery.cycle_life,
                    maintenance=p.battery.maintenance,
                )
                tariff = Tariff(
                    hourly_prices=p.tariff.hourly_prices,
                    export_price=p.tariff.export_price,
                )
                es = EnergySystem(
                    pv=pv_sys, battery=bat_sys, tariff=tariff,
                    interest_rate=p.interest_rate,
                )

                # Single simulation call (calculate_metrics calls
                # simulate_performance internally; call it once directly)
                perf = es.simulate_performance(
                    [p.pv_area_m2, p.battery_kwh],
                    _raw["weather"],
                    _raw["load"],
                )

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
                annual_om = (p.opex.maintenance_pct * cap["total"]
                             + p.opex.water_cost_per_m3 * annual_water_m3
                             + p.opex.labor_cost_per_year
                             + p.opex.misc_opex_per_year)
                annual_load = float(np.sum(perf["load"]))

                # Grid cost
                tcost = tariff.annual_cost(
                    perf["grid_import"], perf["grid_export"], hours,
                )
                net_grid_cost = tcost["net_grid_cost"]
                total_electricity_cost = net_grid_cost

                # LCOE using per-component CRF (aligned with sweep.py)
                lcoe = _compute_lcoe(annual_cap, annual_om, net_grid_cost, annual_load)
                capital_cost = cap["total"]

                # ── PV self-consumption & grid independence stats ──
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

                summary["total_electricity_cost"] = round(float(total_electricity_cost), 2)
                summary["lcoe"] = round(float(lcoe), 4)
                summary["pv_generation_kwh"] = round(float(pv_total_gen), 2)
                summary["grid_import_kwh"] = round(float(grid_total_import), 2)
                summary["grid_export_kwh"] = round(float(np.sum(perf["grid_export"])), 2)
                summary["battery_cycles"] = round(float(perf["battery_cycles"]), 2)
                summary["pv_self_consumed_kwh"] = round(pv_self_consumed, 2)
                summary["pv_self_consumption_rate"] = round(float(self_consumption_rate), 4)
                summary["battery_discharge_kwh"] = round(bat_total_discharge, 2)
                summary["free_energy_kwh"] = round(free_energy_kwh, 2)
                summary["grid_independence_pct"] = round(float(grid_independence) * 100, 1)
                summary["specific_cost_per_kg"] = round(
                    (annual_cap + annual_om + net_grid_cost) / max(annual_harvest_fw_kg, 1e-6), 4,
                )
                summary["capital_total"] = round(float(capital_cost), 2)
                summary["annual_om"] = round(float(annual_om), 2)
                summary["annual_grid_cost_net"] = round(float(net_grid_cost), 2)
            except Exception as e:
                summary["energy_system_status"] = f"failed: {e}"
                logging.warning(f"Energy system simulation failed: {e}")

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
        )


def run_project(project, weather=None):
    return DesignEngine().run(project, weather)
