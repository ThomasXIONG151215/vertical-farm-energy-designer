"""Report/post-processing layer extracted from ``DesignEngine.run`` (C5 split).

Textual move: one-level dedent only, zero expression changes. Consumes
setup-provided state plus the loop's final scalar states and returns
the :class:`~vfed.design.result.SimulationResult`.
"""

import numpy as np
import logging
import warnings
from .fx import USD_C_ENERGY, USD_C_PV, resolve_unit_price
from .result import SimulationResult
from ..weather.weather_bridge import fetch_weather

# module-level helpers/constants stay in engine.py (frozen surface)
from .engine import (
    _FULL_LOAD_DEH_PCT_WARN,
    _FULL_LOAD_HOURLY_FRAC,
    _FULL_LOAD_HVAC_PCT_WARN,
    _FULL_LOAD_HVAC_STREAK_WARN_H,
    _full_load_stats,
    _monthly_sum,
    _warn_opex_dominance,
)


def build_report(
    *,
    zones=None,
    CO2_z_out,
    E_co2_Wh,
    GHI,
    P_deh,
    P_hvac,
    P_led,
    P_misc,
    RH_ext,
    RH_z_out,
    S_co2_inj_out,
    T_ext,
    T_m_out,
    T_s_out,
    T_sol_air_arr,
    T_wall_out_arr,
    T_z_out,
    X_d,
    X_d_arr,
    X_d_init,
    clamp_stats,
    co2_clamp_stats,
    co2_inj_total_kg,
    co2_on,
    co2_sp_ppm,
    crop_area,
    days,
    deh_comp_kwh,
    deh_full_h,
    deh_perf,
    diffuse,
    direct,
    econ_active_s,
    econ_free_cool_j,
    env,
    erv_fan_j,
    erv_fan_w,
    erv_rec_lat_j,
    erv_rec_sens_j,
    hours,
    hvac,
    hvac_cool_full_h,
    hvac_heat_full_h,
    led,
    load_kw,
    monthly_co2_kg,
    monthly_energy,
    monthly_harvest,
    monthly_hours,
    monthly_rh_sum,
    monthly_t_sum,
    monthly_water_kg,
    months,
    n,
    next_harvest_h,
    p,
    ppfd_out,
    qled_out,
    self,
    total_harvest_kg,
    total_water_kg,
    typical_count,
    typical_load_sum,
    weather,
    weather_attrs,
):
    """Assemble the :class:`SimulationResult` from loop outputs.

    Multi-zone (wave 4, v1 conventions) — when ``zones`` is a non-empty
    payload list of per-zone dicts (from ``DesignEngine._run_multizone``):

    - energy/mass facility columns are the SUM over zones in declared
      order (deterministic);
    - climate-state facility columns (T_z/RH_z/X_d/wall/PPFD) come from
      the FIRST declared zone;
    - hvac/deh full-load flags are the logical OR across zones;
    - ``monthly`` and ``typical_daily`` stay facility-total only (per-zone
      monthly is deferred to a later wave);
    - per-zone prefixed timeseries columns and ``summary["zones"]`` are
      emitted in addition to the existing facility-level keys.

    ``zones=None`` (single-zone path) keeps today's behavior bitwise.
    """
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

    # CO2 M1: injector electricity is folded into the "misc" bucket so

    # energy_breakdown keeps its 4-key structure while the shares still

    # close against annual_energy_kwh (attribution documented here and

    # in the CO2 summary block: the device-level column is E_co2_Wh).

    if co2_on:
        misc_kwh += float(np.sum(E_co2_Wh)) / 1000.0

    # P3-9: ventilation-fan electricity joins the misc bucket so the

    # energy_breakdown shares still close against annual_energy_kwh

    # (erv_fan_j is joules; fan off -> += 0.0, bit-identical).

    if erv_fan_w > 0.0:
        misc_kwh += float(erv_fan_j) / 3.6e6

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

    # R28: 2R2C/2R3C diagnostics (additive, RC on only) -- year-end

    # node temperatures expose the warm-up transient (states start at

    # T_z init).  R28 step 3 adds the surface node for 2R3C.

    if env.rc_enabled:
        summary["wall_rc"] = {"T_m_final_c": round(env.T_m, 3)}

        if env.rc3_enabled:
            summary["wall_rc"]["T_s_final_c"] = round(env.T_s, 3)

    # R28 step 6: FD-wall diagnostics (additive, FD on only).

    if env.fd_enabled:
        summary["wall_fd"] = {
            "n_nodes": int(env._fd.n),
            "T_wall_in_final_c": round(env.T_s, 3),
            "T_wall_out_final_c": round(env.T_wall_out, 3),
            "T_sol_air_final_c": round(env.T_sol_air, 3),
        }

    # R34/W3-E (H7): ERV/HRV heat-recovery self-evidence (enabled runs

    # only -- the default off path adds no key, keeping the test_11

    # exact-set pin intact).  Recovered energy is metered as absolute

    # kWh, sensible and latent split.  P3-9 widens the gate to the

    # economizer and adds fan/free-cooling keys ONLY when the

    # corresponding feature is on, so the legacy erv-on six-key set

    # (test_29 pin) stays exact.

    if env.erv_enabled or env.economizer_enabled:
        _erv_summary = {}

        if env.erv_enabled:
            _erv_summary = {
                "flow_m3h": p.envelope.erv_flow_m3h,
                "sensible_eff": p.envelope.erv_sensible_eff,
                "latent_eff": p.envelope.erv_latent_eff,
                "annual_recovered_sensible_kwh": round(float(erv_rec_sens_j) / 3.6e6, 2),
                "annual_recovered_latent_kwh": round(float(erv_rec_lat_j) / 3.6e6, 2),
            }

        if env.economizer_enabled:
            _erv_summary["economizer_flow_m3h"] = p.envelope.economizer_flow_m3h

            _erv_summary["economizer_delta_t_k"] = p.envelope.economizer_delta_t_k

            _erv_summary["economizer_hours"] = round(econ_active_s / 3600.0, 1)

            _erv_summary["annual_free_cooling_kwh"] = round(float(econ_free_cool_j) / 3.6e6, 2)

        if p.envelope.erv_fan_power_w > 0.0:
            _erv_summary["fan_power_w"] = p.envelope.erv_fan_power_w

            _erv_summary["annual_fan_kwh"] = round(float(erv_fan_j) / 3.6e6, 2)

        summary["erv"] = _erv_summary

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

    # R33: with deh.smer_curve on, the compressor denominator already

    # carries the air-side correction (P = M*3.6e6/SMER_eff in the device

    # step), so effective/delivered are on the SMER_eff basis directly;

    # curve off (default) leaves both ratios bitwise unchanged.

    # R34/W2-C: smer_map=True swaps in the E+ (T, RH) biquadratic maps

    # (capacity AND efficiency); the flag is reported alongside.

    summary["deh_smer"] = {
        "control_mode": p.deh.control,
        "smer_curve": bool(p.deh.smer_curve),
        "smer_map": bool(p.deh.smer_map),
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

    # R34: HVAC additive-upgrade self-evidence (H1a soft cap / H2

    # crankcase / H3 defrost).  Flags + defrost event/energy meters so

    # the switch-on footprint is visible next to the energy breakdown;

    # all-off defaults leave the meters at exactly 0.

    summary["hvac_upgrades"] = {
        "cop_soft_cap": bool(p.hvac.cop_soft_cap),
        "defrost": p.hvac.defrost,
        "defrost_events": int(hvac.defrost_events),
        "defrost_energy_kwh": round(hvac.energy_defrost_j / 3.6e6, 3),
        "crankcase_energy_kwh": round(hvac.energy_crankcase_j / 3.6e6, 3),
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

    # ── CO2 supplement KPIs (additive; co2.enabled only -- the default

    # path adds no key, keeping the test_11 exact-set pin intact) ──

    # Statistics run on the same CO2_z_out array that feeds the ts

    # "CO2_z" column, so recomputing from timeseries.csv reproduces

    # every value.  co2_below_setpoint_hours mirrors rh_exceed_hours

    # (strict inequality on the substep-mean hourly value).

    if co2_on:
        summary["annual_co2_injected_kg"] = round(co2_inj_total_kg, 3)

        summary["co2_mean_ppm"] = round(float(np.mean(CO2_z_out)), 1)

        summary["co2_min_ppm"] = round(float(np.min(CO2_z_out)), 1)

        summary["co2_max_ppm"] = round(float(np.max(CO2_z_out)), 1)

        summary["co2_energy_kwh"] = round(float(np.sum(E_co2_Wh)) / 1000.0, 3)

        summary["co2_below_setpoint_hours"] = int(np.count_nonzero(CO2_z_out < co2_sp_ppm))

        summary["co2_setpoint_ppm"] = co2_sp_ppm

        summary["co2_clamp_stats"] = {
            "floor_clip_events": co2_clamp_stats["floor_clip_events"],
            "floor_clip_co2_kg": round(co2_clamp_stats["floor_clip_co2_kg"], 6),
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

    # ── multi-zone summary (wave 4 Z-report, additive-only path) ────────
    # summary["zones"] is emitted ONLY on the multi-zone path (zones
    # payload non-empty); single-zone output stays bitwise identical.
    # The facility standing-crop value computed above from the aggregated
    # X_d/crop_area inputs is replaced by the exact per-zone sum (the
    # multi-zone engine passes next_harvest_h=0.0, disabling the generic
    # standing block above, so no double count).
    zone_ts = {}
    if zones:
        zsummary = {}
        for z in zones:
            zid = z["zone_id"]
            zp = z["zp"]
            z_rh_set = zp.setpoints.RH
            z_rh_exceed = int(np.count_nonzero(z["RH_z_out"] > z_rh_set))
            z_harvest_kg = z["total_harvest_events_kg"] + z["standing_kg"]
            zdp = z["deh_perf"]
            zmetrics = {
                "annual_load_kwh": round(float(np.sum(z["load_kw"])), 2),
                "annual_harvest_kg": round(z_harvest_kg, 2),
                "annual_harvest_fw_kg": round(z_harvest_kg / zp.growth.dry_matter_fraction, 2),
                "annual_water_m3": round(z["total_water_kg"] / 1000.0, 2),
                "T_z_mean_c": round(float(np.mean(z["T_z_out"])), 2),
                "rh_setpoint_pct": z_rh_set,
                "rh_exceed_hours": z_rh_exceed,
                "rh_p95_pct": round(float(np.percentile(z["RH_z_out"], 95)), 2),
                "rh_max_pct": round(float(np.max(z["RH_z_out"])), 2),
                "deh_utilization": round(zdp["deh_actual_kg"] / zdp["deh_nominal_kg"], 4)
                if zdp["deh_nominal_kg"] > 0
                else 1.0,
                "full_load_diagnostics": {
                    "hvac_cool": _full_load_stats(z["hvac_cool_full_h"]),
                    "hvac_heat": _full_load_stats(z["hvac_heat_full_h"]),
                    "deh": _full_load_stats(z["deh_full_h"]),
                },
                "hvac_P_rated_w": z["hvac_P_rated_w"],
                "hvac_P_rated_heat_w": z["hvac_P_rated_heat_w"],
                "deh_P_ref_w": z["deh_P_ref_w"],
            }
            if z["co2_on"]:
                zmetrics["annual_co2_injected_kg"] = round(z["co2_inj_total_kg"], 3)
            zsummary[zid] = zmetrics
        summary["zones"] = zsummary
        summary["harvest_final_standing_kg"] = round(sum(z["standing_kg"] for z in zones), 4)

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

    # CO2 M1: injected mass per calendar month (kg; closes against

    # summary.annual_co2_injected_kg), co2.enabled only.

    if co2_on:
        monthly["co2_injected_kg"] = monthly_co2_kg.tolist()

    # ── timeseries dict ────────────────────────────────────────────────

    ts = {
        "hour_of_year": list(range(n)),
        "month": months.tolist(),
        "day": days.tolist(),
        "hour_of_day": hours.tolist(),
        "T_z": T_z_out.tolist(),
        "RH_z": RH_z_out.tolist(),
        # R28: 2R2C mass-node temperature (additive column, RC on only;
        # hourly mean of the substep values).
        **({"T_m": T_m_out.tolist()} if (env.rc_enabled or env.fd_enabled) else {}),
        **({"T_s": T_s_out.tolist()} if env.rc3_enabled else {}),
        "T_ext": T_ext.tolist(),
        "RH_ext": RH_ext.tolist(),
        "GHI": GHI.tolist(),
        "load_kw": load_kw.tolist(),
        "E_hvac_Wh": P_hvac.tolist(),
        "E_deh_Wh": P_deh.tolist(),
        "E_led_Wh": P_led.tolist(),
        # P3/B3: light diagnostics (canopy-mean PPFD umol/(m^2*s) and LED
        # heat W, hourly substep means) — emitted ONLY when the spatial
        # light model is active, following the T_m/T_s convention that
        # additive columns must not leak into the default path (the
        # shared zero-drift sha256 oracle stays intact).
        **({"PPFD_mean": ppfd_out, "Q_led_W": qled_out} if led.ppfd_layers else {}),
        "E_misc_Wh": P_misc.tolist(),
        "X_d": X_d_arr.tolist(),
        # CO2 M1: enrichment columns, emitted ONLY when co2.enabled --
        # additive columns must not leak into the default path (the
        # shared zero-drift sha256 oracle stays intact).  CO2_z is the
        # substep-mean indoor concentration (ppm), S_co2_inj_g_h the
        # substep-mean injection rate (g/h), E_co2_Wh the injector
        # electricity per hour.
        **(
            {
                "CO2_z": CO2_z_out.tolist(),
                "S_co2_inj_g_h": S_co2_inj_out.tolist(),
                "E_co2_Wh": E_co2_Wh.tolist(),
            }
            if co2_on
            else {}
        ),
        # P1-3b: ISO8601 local wall-clock timestamp per row (weather index
        # is naive local time on the aligned local calendar year) and the
        # tariff price actually applied to that hour.  Additive columns,
        # appended last (existing consumers index by name).
        "timestamp": weather.index.strftime("%Y-%m-%dT%H:%M:%S").tolist(),
        "price": [p.tariff.hourly_prices[int(h) % 24] for h in hours],
        # R28 step 6: FD-wall diagnostic columns, appended LAST so the
        # existing column order is untouched (FD on only).
        **(
            {
                "T_wall_in": T_s_out.tolist(),
                "T_wall_out": T_wall_out_arr.tolist(),
                "T_sol_air": T_sol_air_arr.tolist(),
            }
            if env.fd_enabled
            else {}
        ),
    }

    # ── multi-zone timeseries (wave 4 Z-report, additive-only path) ────
    # Per-zone columns carry a ``{zone_id}.`` prefix; the unprefixed
    # facility columns above stay untouched (load_kw is the aggregate
    # sum; T_z/RH_z are the first declared zone).  Emitted ONLY on the
    # multi-zone path so the single-zone zero-drift sha256 stays intact.
    if zones:
        for z in zones:
            zid = z["zone_id"]
            zcols = {
                "T_z": z["T_z_out"].tolist(),
                "RH_z": z["RH_z_out"].tolist(),
                "load_kw": z["load_kw"].tolist(),
                "E_hvac_Wh": z["P_hvac"].tolist(),
                "E_deh_Wh": z["P_deh"].tolist(),
                "E_led_Wh": z["P_led"].tolist(),
                "E_misc_Wh": z["P_misc"].tolist(),
                "X_d": z["X_d_arr"].tolist(),
            }
            for col, values in zcols.items():
                ts[f"{zid}.{col}"] = values
            zone_ts[zid] = zcols

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
            # G12 (Wave 1): month labels for the demand-charge peak
            # calculation (read only when the tariff activates it).
            "month": months,
        },
    }

    # ── energy system (optional) ───────────────────────────────────────

    # P4-2 (MAJOR): battery-only and pure-building configurations must also

    # report economics.  Gate on either PV or battery being present so

    # evaluate() matches sweep()'s handling of [0, E_bat] and [0, 0].

    # G1 (Wave 2): pv_arrays replaces the sizing scalars when set.

    if p.pv_area_m2 > 0 or p.battery_kwh > 0 or p.pv_arrays:
        try:
            from ..pvbes.energy_system import EnergySystem

            from ..pvbes.pv import PVSystem

            from ..pvbes.battery import BatterySystem

            from ..pvbes.grid import Tariff

            pv_sys = PVSystem(
                module=p.pv.module,  # G3 (Wave 1): library preset
                eta_pv=p.pv.eta_pv,
                area_to_power=p.pv.area_to_power,
                N_s=p.pv.N_s,
                I_sc_stc=p.pv.I_sc_stc,
                V_oc_stc=p.pv.V_oc_stc,
                I_mp_stc=p.pv.I_mp_stc,
                V_mp_stc=p.pv.V_mp_stc,
                alpha_sc=p.pv.alpha_sc,
                beta_voc=p.pv.beta_voc,
                gamma_pmp=p.pv.gamma_pmp,  # P2-5
                NOCT=p.pv.NOCT,
                eta_inv=p.pv.eta_inv,
                C_pv=resolve_unit_price(p.pv.C_pv, USD_C_PV, p.currency, p.exchange_rate),
                degradation=p.pv.degradation,
                eta_system=p.pv.eta_system,  # P6-7
            )

            bat_sys = BatterySystem(
                c_energy=resolve_unit_price(
                    p.battery.c_energy, USD_C_ENERGY, p.currency, p.exchange_rate
                ),
                c_rate=p.battery.c_rate,
                eta_ch=p.battery.eta_ch,
                eta_dis=p.battery.eta_dis,
                soc_min=p.battery.soc_min,
                soc_max=p.battery.soc_max,
                cycle_life=p.battery.cycle_life,
                soh_eol=p.battery.soh_eol,  # P2-4 capacity fade
                allow_grid_charging=p.battery.allow_grid_charging,  # P1-2 passthrough
                power_kw=p.battery.power_kw,  # G10 (Wave 1): independent PCS cap
                chemistry=p.battery.chemistry,  # G11 (Wave 1): fade model
            )

            tariff = Tariff(
                hourly_prices=p.tariff.hourly_prices,
                export_price=p.tariff.export_price,
                export_limit_kw=p.tariff.export_limit_kw,  # G12
                demand_charge_per_kw=p.tariff.demand_charge_per_kw,  # G12
            )

            es = EnergySystem(
                pv=pv_sys,
                battery=bat_sys,
                tariff=tariff,
                interest_rate=p.interest_rate,
            )

            # ── G1 (Wave 2): multi-array PV ─────────────────────────────

            # When pv_arrays is set the single sizing scalar is replaced

            # by per-orientation arrays.  Each unique (tilt, azimuth)

            # gets its own POA weather series (fetch_weather keys the

            # cache on orientation); each array runs calculate_pv_output

            # at its own area and the series are summed, then injected

            # into dispatch via pv_power_override so the battery/grid

            # logic is byte-identical to the single-array path.  With

            # pv_arrays empty (default) the override stays None and the

            # legacy path below is untouched (golden baseline).

            _pv_area_total = p.pv_area_m2

            _pv_power_override = None

            _pv_array_kwh = []

            if p.pv_arrays:
                _pv_area_total = float(sum(a.area_m2 for a in p.pv_arrays))

                _main_orient = (
                    round(float(p.site.tilt), 6),
                    round(float(p.site.azimuth), 6),
                )

                _orient_weather = {}

                _pv_series = np.zeros(n, dtype=float)

                for a in p.pv_arrays:
                    _key = (round(float(a.tilt), 6), round(float(a.azimuth), 6))

                    if _key not in _orient_weather:
                        if _key == _main_orient:
                            # Same orientation as the site: the main POA

                            # DataFrame already carries these columns.

                            _orient_weather[_key] = weather

                        else:
                            _orient_weather[_key] = fetch_weather(
                                p.site.lat,
                                p.site.lon,
                                p.site.year,
                                tz_hours=p.site.tz_hours,
                                tilt=a.tilt,
                                azimuth=a.azimuth,
                                cache_dir=self.cache_dir,
                                city=p.site.city,
                                provider=getattr(p.site, "weather_provider", "open-meteo"),
                                ghi_scale=getattr(p.site, "ghi_scale", 1.0),
                                albedo=p.site.albedo,
                                transposition=p.site.transposition,
                            )

                    _w = _orient_weather[_key]

                    _arr_weather = {
                        "direct_radiation": np.asarray(_w["direct_radiation"], dtype=float),
                        "diffuse_radiation": np.asarray(_w["diffuse_radiation"], dtype=float),
                        "temperature_2m": np.asarray(_w["temperature_2m"], dtype=float),
                    }

                    if a.module is None or a.module == p.pv.module:
                        _arr_sys = pv_sys

                    else:
                        # Per-array module: the _UNSET sentinel design in

                        # PVSystem resolves the electrical fields from

                        # the module library; explicit kwargs above win.

                        _arr_sys = PVSystem(
                            module=a.module,
                            eta_inv=p.pv.eta_inv,
                            eta_system=p.pv.eta_system,
                            C_pv=resolve_unit_price(
                                p.pv.C_pv, USD_C_PV, p.currency, p.exchange_rate
                            ),
                        )

                    _series_i = _arr_sys.calculate_pv_output(
                        _arr_weather, a.area_m2, year=es.lifetime // 2
                    )

                    _pv_series += _series_i

                    _pv_array_kwh.append(
                        {
                            "name": a.name or f"array_{len(_pv_array_kwh) + 1}",
                            "tilt": float(a.tilt),
                            "azimuth": float(a.azimuth),
                            "area_m2": float(a.area_m2),
                            "module": a.module or p.pv.module,
                            "annual_kwh": round(float(np.sum(_series_i)), 2),
                        }
                    )

                _pv_power_override = _pv_series

            # Single simulation call (calculate_metrics calls

            # simulate_performance internally; call it once directly)

            perf = es.simulate_performance(
                [_pv_area_total, p.battery_kwh],
                _raw["weather"],
                _raw["load"],
                # Mid-life degradation year (see sweep.py: LCOE uses CRF
                # over the lifetime, paired with average PV output).
                year=es.lifetime // 2,
                pv_power_override=_pv_power_override,
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

            # PV+Battery component costs (for legacy fields).  G1: the

            # total array area prices the PV capital; per-module price

            # differentiation stays on the main pv config until G7.

            pv_cost = pv_sys.calculate_costs(_pv_area_total)

            bat_cost = bat_sys.calculate_costs(p.battery_kwh)

            pv_capital = pv_cost.get("capital_cost", 0)

            bat_capital = bat_cost.get("capital_cost", 0)

            # Full-system capital (LED+HVAC+DEH+PV+Battery+Equipment+Envelope)

            from .sweep import _total_capital, _annualized_capital, _compute_lcoe

            cap = _total_capital(p, _pv_area_total, p.battery_kwh)

            annual_cap = _annualized_capital(p, cap)

            annual_om = (
                p.opex.maintenance_pct * cap["total"]
                + p.opex.water_cost_per_m3 * annual_water_m3
                + p.opex.labor_cost_per_year
                + p.opex.misc_opex_per_year
            )

            annual_load = float(np.sum(perf["load"]))

            # Grid cost (months labels ride along for the G12 demand

            # charge; annual_cost ignores them when it is off).

            tcost = tariff.annual_cost(
                perf["grid_import"],
                perf["grid_export"],
                hours,
                months=months,
                dt=1.0,  # T2 (B8-2): hourly arrays, cadence stated at the call
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

            # G1 (Wave 2): per-array generation breakdown (multi-array

            # mode only -- the default key set is unchanged).

            if _pv_array_kwh:
                summary["pv_arrays"] = _pv_array_kwh

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
            export_limit_kw=p.tariff.export_limit_kw,  # G12
            demand_charge_per_kw=p.tariff.demand_charge_per_kw,  # G12
        )

        annual_load = float(np.sum(load_kw))

        # grid_import == load, grid_export == 0 (no PV, no battery)

        tcost = tariff.annual_cost(
            load_kw, np.zeros_like(load_kw), hours, months=months, dt=1.0
        )  # T2 (B8-2): hourly arrays, cadence stated at the call

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

    # Multi-zone (wave 4): the shared project keeps its raw config values
    # (auto-size writebacks land on the per-zone projects only, B8), so
    # facility sizing reads the FIRST declared zone's auto-sized nameplates.
    if zones:
        z0 = zones[0]
        z0p = z0["zp"]
        sizing = {
            "hvac_P_rated_w": z0["hvac_P_rated_w"],
            "hvac_P_rated_heat_w": z0["hvac_P_rated_heat_w"],
            "deh_P_ref_w": z0["deh_P_ref_w"],
            "deh_M_design_kgs": float(z0["deh_P_ref_w"] * z0p.deh.smer / 3.6e6),
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
        zone_ids=[z["zone_id"] for z in zones] if zones else [],
        zone_timeseries=zone_ts,
    )
