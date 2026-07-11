"""
Design engine — runs the digital-twin building simulation for a project and
produces the hourly electrical load profile plus indoor climate timeseries.

The building ODE is integrated at the project timestep (default 10 min) and
aggregated to hourly load (kW) consumed by the PVBES layer. Device state
(compressor hysteresis, transient lags) is continuous across the whole year.
"""

from typing import Dict, Optional

import numpy as np
import pandas as pd

from ..physics.psychrometrics import temp_rh_to_ah, ah_to_temp_rh
from ..physics.envelope import Envelope
from ..physics.ode import RoomODESolver
from ..physics.shr import DynamicSHR
from ..devices.hvac import HVACDevice, COPModel
from ..devices.dehumidifier import DEHDevice, EnthalpyEfficiency
from ..devices.led import LEDDevice
from ..devices.compressor import CompressorState
from ..plants.transpiration import TranspirationModel
from ..plants.van_henten import VanHenten
from ..weather.weather_bridge import fetch_weather

__all__ = ["DesignEngine", "run_project"]


def _build_devices(p):
    env = Envelope(
        U_wall_A=p.envelope.U_wall_A, A_window=p.envelope.A_window,
        eta_solar=p.envelope.eta_solar, ach=p.envelope.ach,
        permeance=p.envelope.permeance, rho_air=p.envelope.rho_air,
        cp_air=p.envelope.cp_air, V_room=p.envelope.V_room,
    )
    cop = COPModel(mode=p.hvac.cop_mode, value=p.hvac.cop_value,
                   k=p.hvac.cop_k, T_ref=p.hvac.cop_T_ref)
    hvac = HVACDevice(
        P_rated_w=p.hvac.P_rated_w, cop=cop, cop_heat=p.hvac.cop_heat,
        heat_mode=p.hvac.heat_mode, P_rated_heat_w=p.hvac.P_rated_heat_w,
        deadband_c=p.hvac.deadband_c, min_on_s=p.hvac.min_on_s,
        min_off_s=p.hvac.min_off_s, fan_power_w=p.hvac.fan_power_w,
        shr=DynamicSHR(BF=p.hvac.shr_BF),
        tau_q=p.hvac.tau_q, tau_m=p.hvac.tau_m,
    )
    deh = DEHDevice(
        P_ref_w=p.deh.P_ref_w, poly_e=tuple(p.deh.poly_e),
        T_mean=p.deh.T_mean, T_std=p.deh.T_std, W_mean=p.deh.W_mean,
        W_std=p.deh.W_std,
        efficiency=EnthalpyEfficiency(
            eta_ref=p.deh.eta_ref, eta_max=p.deh.eta_max,
            ah_min=p.deh.ah_min, ah_ref=p.deh.ah_ref),
        deadband_rh=p.deh.deadband_rh, min_on_s=p.deh.min_on_s,
        min_off_s=p.deh.min_off_s, fan_power_w=p.deh.fan_power_w,
        tau_q=p.deh.tau_q, tau_m=p.deh.tau_m,
    )
    led = LEDDevice(power_w=p.led.power_w, start_hour=p.led.start_hour,
                    end_hour=p.led.end_hour, heat_fraction=p.led.heat_fraction)
    transp = TranspirationModel(
        method=p.transpiration.method, E_max_kgs=p.transpiration.E_max_kgs,
        k_vpd=p.transpiration.k_vpd, stage_factor=p.transpiration.stage_factor,
        g_stomata=p.transpiration.g_stomata, area_m2=p.led.covered_area,
    )
    ode = RoomODESolver(C_z=p.envelope.C_z, V_room=p.envelope.V_room,
                        rho_air=p.envelope.rho_air)
    return env, hvac, deh, led, transp, ode


class DesignEngine:
    def __init__(self, cache_dir: Optional[str] = "weather_cache"):
        self.cache_dir = cache_dir

    def run(self, project, weather: Optional[pd.DataFrame] = None) -> Dict:
        p = project
        if weather is None:
            weather = fetch_weather(
                p.site.lat, p.site.lon, p.site.year, tz_hours=p.site.tz_hours,
                tilt=p.site.tilt, azimuth=p.site.azimuth, cache_dir=self.cache_dir,
            )
        n = len(weather)
        dt = p.space.timestep_s
        sub = max(1, int(round(3600.0 / dt)))

        T_ext = weather["temperature_2m"].values.astype(float)
        RH_ext = weather["relative_humidity_2m"].values.astype(float)
        GHI = weather["shortwave_radiation"].values.astype(float)
        hours = weather.index.hour.values.astype(float)
        direct = weather["direct_radiation"].values.astype(float)
        diffuse = weather["diffuse_radiation"].values.astype(float)

        env, hvac, deh, led, transp, ode = _build_devices(p)

        # ── plant growth model ─────────────────────────────────────────────
        grow = VanHenten(co2_ppm=p.setpoints.co2_ppm)
        X_d = 0.001  # initial dry weight (kg/m²)
        X_d_init = 0.001  # reset point after each harvest
        crop_area = p.led.covered_area
        harvest_days = max(1, int(round(p.setpoints.crop_cycle_days)))
        total_harvest_kg = 0.0  # cumulative harvested dry matter (kg)

        T_z = p.setpoints.T_cool
        W_z = temp_rh_to_ah(T_z, p.setpoints.RH)
        RH_z = p.setpoints.RH

        load_kw = np.zeros(n)
        T_out = np.zeros(n)
        RH_out = np.zeros(n)
        P_hvac = np.zeros(n)
        P_deh = np.zeros(n)
        P_led = np.zeros(n)

        for h in range(n):
            energy_wh = 0.0
            t_sum, rh_sum = 0.0, 0.0
            hour_of_day = hours[h]
            is_light_h = led.is_light(hour_of_day)
            for s in range(sub):
                Q_LED, P_led_s = led.step(hour_of_day)
                hv = hvac.step(T_z, RH_z, T_ext[h], dt,
                               T_setpoint=p.setpoints.T_cool,
                               T_heat_setpoint=p.setpoints.T_heat)
                dh = deh.step(T_z, RH_z, W_z, dt, deh_setpoint=p.setpoints.RH)
                E_trans = transp.step(T_z, RH_z, is_light_h, dt, X_d=X_d)
                # plant growth (van Henten carbon balance)
                light_wm2 = (p.led.ppfd_target / max(p.led.efficacy, 0.1) / 4.57
                             if is_light_h else 0.0)
                _, X_d = grow.step(T_z, light_wm2, X_d, dt)
                W_ext = temp_rh_to_ah(T_ext[h], RH_ext[h])
                Q_wall = env.Q_wall(T_ext[h], T_z)
                Q_solar = env.Q_solar(GHI[h])
                Q_inf, M_inf = env.infiltration(T_ext[h], T_z, W_ext, W_z)
                M_perm = env.envelope_moisture(W_ext, W_z)
                Q_total = (hv["Q_HVAC_W"] + dh["Q_DH_W"] + Q_LED +
                           Q_wall + Q_solar + Q_inf)
                M_total = (E_trans - dh["M_deh_kgs"] - hv["M_hvac_kgs"]
                           + M_inf + M_perm)
                T_z = ode.step_temperature(T_z, Q_total, dt)
                W_z = ode.step_humidity(W_z, M_total, dt)
                RH_z = ah_to_temp_rh(T_z, W_z)
                P_tot = (hv["P_elec_W"] + dh["P_elec_W"] + P_led_s +
                         p.equipment_power_w)
                energy_wh += P_tot * dt / 3600.0
                t_sum += T_z
                rh_sum += RH_z
            load_kw[h] = energy_wh / 1000.0  # kWh over the hour
            T_out[h] = t_sum / sub
            RH_out[h] = rh_sum / sub
            P_hvac[h] = hv["P_elec_W"]
            P_deh[h] = dh["P_elec_W"]
            P_led[h] = P_led_s
            # ── harvest cycle ──
            if (h + 1) % 24 == 0:
                day = (h + 1) // 24
                if day % harvest_days == 0:
                    harvested = (X_d - X_d_init) * crop_area
                    total_harvest_kg += max(harvested, 0.0)
                    X_d = X_d_init  # reset canopy for next cycle

        # final partial cycle
        harvested = (X_d - X_d_init) * crop_area
        total_harvest_kg += max(harvested, 0.0)

        timeseries = pd.DataFrame({
            "hour_of_year": np.arange(n),
            "hour_of_day": hours,
            "T_z": T_out,
            "RH_z": RH_out,
            "load_kw": load_kw,
            "P_hvac_W": P_hvac,
            "P_deh_W": P_deh,
            "P_led_W": P_led,
        })
        total_kwh = float(np.sum(load_kw)) + p.equipment_power_w * n / 1000.0
        biomass_kg = total_harvest_kg
        kwh_per_kg = total_kwh / max(biomass_kg, 1e-6)   # per kg dry matter
        dry_fraction = 0.05                              # ~5% DM for lettuce
        kwh_per_kg_fresh = kwh_per_kg * dry_fraction

        weather_dict = {
            "direct_radiation": direct,
            "diffuse_radiation": diffuse,
            "temperature_2m": T_ext,
            "hour": hours,
            "shortwave_radiation": GHI,
        }
        return {
            "load": load_kw,
            "weather": weather_dict,
            "timeseries": timeseries,
            "annual_load_kwh": total_kwh,
            "biomass_kg": biomass_kg,
            "kwh_per_kg": kwh_per_kg,
            "kwh_per_kg_fresh": kwh_per_kg_fresh,
        }


def run_project(project, weather=None):
    return DesignEngine().run(project, weather)
