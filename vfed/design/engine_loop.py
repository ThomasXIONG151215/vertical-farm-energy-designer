"""Hourly timestep loop extracted from ``DesignEngine.run`` (C5 split).

Textual move: one-level dedent only, zero expression changes - the
zero-drift sha256 oracle gates any accidental FP reordering. All state
enters as keyword-only arguments under their original local names;
buffers and accumulator arrays/lists mutate in place; final scalar
states come back in :class:`LoopState`.
"""

from dataclasses import dataclass
import numpy as np
from ..devices.co2 import DM_TO_CO2, mixing_ratio_to_ppm
from ..physics.psychrometrics import ah_to_temp_rh, latent_heat_vaporization, temp_rh_to_ah
from ..plants.van_henten_3state import VanHenten3State

# module-level helpers/constants stay in engine.py (frozen surface)
from .engine import _FULL_LOAD_HOURLY_FRAC, _limit_removal_by_inventory


@dataclass
class LoopState:
    """Final scalar states handed to the report layer."""

    X_d: float
    co2_inj_total_kg: float
    deh_comp_kwh: float
    econ_active_s: float
    econ_free_cool_j: float
    erv_fan_j: float
    erv_rec_lat_j: float
    erv_rec_sens_j: float
    next_harvest_h: float
    total_harvest_kg: float
    total_water_kg: float


def run_hourly_loop(
    *,
    CO2_z_out,
    E_co2_Wh,
    GHI,
    P_atm,
    P_deh,
    P_hvac,
    P_led,
    P_misc,
    RH_ext,
    RH_z,
    RH_z_out,
    S_co2_inj_out,
    T_ext,
    T_m_out,
    T_s_out,
    T_sol_air_arr,
    T_wall_out_arr,
    T_z,
    T_z_out,
    W_z,
    X_d,
    X_d_arr,
    X_d_init,
    air_mass_co2,
    c_out,
    c_z,
    clamp_stats,
    co2_clamp_stats,
    co2_dev,
    co2_gamma,
    co2_inj_total_kg,
    co2_on,
    co2_sp_ppm,
    crop_area,
    cycle_h,
    deh,
    deh_comp_kwh,
    deh_full_h,
    deh_perf,
    dt,
    econ_active_s,
    econ_dt_k,
    econ_flow,
    econ_free_cool_j,
    econ_on,
    env,
    erv_fan_j,
    erv_fan_ref_flow,
    erv_fan_w,
    erv_on,
    erv_rec_lat_j,
    erv_rec_sens_j,
    grow,
    harvest_hours,
    hours,
    hvac,
    hvac_cool_full_h,
    hvac_cool_full_w,
    hvac_heat_full_h,
    hvac_heat_full_w,
    led,
    load_kw,
    m_dot_ach_co2,
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
    ode,
    p,
    ppfd_out,
    qled_out,
    sub,
    total_harvest_kg,
    total_water_kg,
    transp,
    typical_count,
    typical_load_sum,
) -> LoopState:
    for h in range(n):
        energy_wh = 0.0

        hvac_wh = 0.0

        deh_wh = 0.0

        led_wh = 0.0

        ppfd_sum = 0.0  # P3/B3

        qled_sum = 0.0  # P3/B3

        co2_ppm_sum = 0.0  # CO2 M1: substep accumulators (co2_on only)

        co2_inj_sum = 0.0

        co2_wh = 0.0

        P_co2_s = 0.0

        erv_fan_wh = 0.0  # P3-9: hourly ventilation-fan Wh (misc bucket)

        t_sum, rh_sum = 0.0, 0.0

        tm_sum = 0.0  # R28: mass-node substep accumulator (RC on only)

        ts_sum = 0.0  # R28 step 3: surface-node substep accumulator (rc3 only)

        twi_sum = 0.0  # R28 step 6: FD exterior-cell accumulator

        tos_sum = 0.0  # R28 step 6: sol-air boundary accumulator

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

            # R34/H3: outdoor humidity ratio, hoisted above the HVAC

            # step (pure function of weather + P_atm, so the hoist is

            # value-identical) for the on_demand defrost factors.

            W_ext = temp_rh_to_ah(T_ext[h], RH_ext[h], pressure_kpa=P_atm)

            hv = hvac.step(
                T_z,
                RH_z,
                T_ext[h],
                dt,
                T_setpoint=T_sp,
                T_heat_setpoint=p.setpoints.T_dark,
                W_ext=W_ext,
            )

            dh = deh.step(T_z, RH_z, W_z, dt, deh_setpoint=p.setpoints.RH, is_light=is_light_h)

            # P0-4 full-load observation (read-only on device outputs).

            if hv["mode"] == "cool" and hv["P_elec_W"] >= hvac_cool_full_w:
                cool_full_s += 1

            elif hv["mode"] == "heat" and hv["P_elec_W"] >= hvac_heat_full_w:
                heat_full_s += 1

            if dh["mod"] >= 0.999:
                deh_full_s += 1

            # P4-11: runtime PAR from the LED power state (matches the

            # DEH-sizing light_wm2 above).

            # P3/A3: canopy_par_wm2 = layer-mean PAR when ppfd_layers is

            # set (spatial light distribution reaches growth/transpiration),

            # else the legacy power-derived par_wm2 (bit-identical).

            light_wm2 = led.canopy_par_wm2 if is_light_h else 0.0

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

            # 3-state only: the rhs needs air humidity for stomatal

            # resistance and SLA; keep the live room RH on the model.

            # (1-state ignores RH; attribute is a no-op there.)

            if isinstance(grow, VanHenten3State):
                grow.rh_pct = RH_z

            # ── CO2 mass balance (additive; CO2 supplement M1) ─────

            # Sources/sinks at the FIXED setpoint concentration (M1 --

            # the dynamic growth feedback is M2): injector (lagged

            # device flux), crop photosynthesis sink phi*A_canopy and

            # respiration source resp*DM_TO_CO2*A_canopy (phi/resp via

            # the read-only grow.fluxes at the step-start state, the

            # same values grow.step integrates below), plus the ach

            # infiltration exchange m_dot*(c_out - c_z).  Photosynthesis

            # is capped at the CO2 inventory above Γ available this

            # sub-step (+ concurrent sources) so the sink can never

            # draw c_z below the compensation point in one Euler step

            # (mirror of _limit_removal_by_inventory); step_co2's Γ

            # floor then reports any residual clamp, never silently.

            if co2_on:
                phi_c, resp_c = grow.fluxes(T_z, light_wm2, X_d)

                inj = co2_dev.step(mixing_ratio_to_ppm(c_z), dt, co2_sp_ppm, is_light_h)

                S_inj_co2 = inj["S_inj_kgs"]

                S_resp_co2 = resp_c * DM_TO_CO2 * crop_area

                S_phot_co2 = phi_c * crop_area

                S_inf_co2 = m_dot_ach_co2 * (c_out - c_z)

                co2_sources = S_inj_co2 + S_resp_co2 + max(S_inf_co2, 0.0)

                uptake_cap = (c_z - co2_gamma) * air_mass_co2 / dt + co2_sources

                if S_phot_co2 > uptake_cap:
                    S_phot_co2 = max(uptake_cap, 0.0)

                S_co2_total = S_inj_co2 + S_resp_co2 - S_phot_co2 + S_inf_co2

                c_z, cmeta = ode.step_co2(c_z, S_co2_total, dt, c_floor=co2_gamma, return_meta=True)

                if cmeta["floor_clipped_kg"] > 0.0:
                    co2_clamp_stats["floor_clip_events"] += 1

                    co2_clamp_stats["floor_clip_co2_kg"] += cmeta["floor_clipped_kg"]

                P_co2_s = inj["P_elec_W"]

                co2_ppm_sum += mixing_ratio_to_ppm(c_z)

                co2_inj_sum += S_inj_co2

                co2_wh += P_co2_s * dt / 3600.0

                co2_inj_total_kg += S_inj_co2 * dt

                monthly_co2_kg[month_idx] += S_inj_co2 * dt

            _, X_d = grow.step(T_z, light_wm2, X_d, dt)

            # R34/H3: W_ext now computed above the HVAC step (hoisted,

            # value-identical); the ODE branch below reuses it.

            # R28: the ONLY branch point of the wall mass network.  With

            # RC off the legacy single-node calls below are byte-identical

            # to pre-R28 builds (zero drift by construction).

            if env.fd_enabled:
                # R28 step 6: FD wall -- solar split lands the f_m share

                # on the inner-surface control volume (LBNL

                # SolarRadiationExchange rule), I_ext drives the sol-air

                # exterior boundary; fully implicit solve inside.

                f_m = env.solar_mass_fraction

                q_sol_full = env.eta_solar * env.A_window * GHI[h]

                T_rc = env.step_mass(
                    T_ext[h],
                    T_z,
                    dt,
                    Q_source_w=f_m * q_sol_full if f_m > 0.0 else 0.0,
                    I_ext_wm2=GHI[h],
                )

                Q_solar = (1.0 - f_m) * q_sol_full

                Q_wall = env.Q_wall(T_ext[h], T_z, T_rc)

                tm_sum += env.T_m

                ts_sum += env.T_s

                twi_sum += env.T_wall_out

                tos_sum += env.T_sol_air

            elif env.rc_enabled:
                # Staggered Euler: step the RC nodes from the SUBSTEP-START

                # T_ext/T_z, then let Q_wall discharge them into the air

                # balance (same O(dt) ordering as the air node).  The

                # q_corr re-integration below only re-steps T_z -- the RC

                # nodes are NOT re-stepped (no double counting).

                f_m = env.solar_mass_fraction

                if f_m > 0.0:
                    # R28 step 3 solar split: full window gain computed

                    # once (same (eta*A)*I evaluation order as Q_solar);

                    # the f_m share enters the RC network as a source

                    # (mass node for 2R2C, surface node for 2R3C -- LBNL

                    # SolarRadiationExchange puts transmitted solar on

                    # the construction surfaces), the (1-f_m) remainder

                    # goes to the air node via Q_solar below.  f_m = 0

                    # skips the branch entirely: bit-for-bit the pre-

                    # step-3 rc path.

                    q_sol_full = env.eta_solar * env.A_window * GHI[h]

                    T_rc = env.step_mass(T_ext[h], T_z, dt, Q_source_w=f_m * q_sol_full)

                    Q_solar = (1.0 - f_m) * q_sol_full

                else:
                    T_rc = env.step_mass(T_ext[h], T_z, dt)

                    Q_solar = env.Q_solar(GHI[h])

                tm_sum += env.T_m

                if env.rc3_enabled:
                    ts_sum += env.T_s

                Q_wall = env.Q_wall(T_ext[h], T_z, T_rc)

            else:
                Q_wall = env.Q_wall(T_ext[h], T_z)

                Q_solar = env.Q_solar(GHI[h])

            Q_inf, M_inf, Q_lat_inf = env.infiltration(T_ext[h], T_z, W_ext, W_z)

            M_perm = env.envelope_moisture(W_ext, W_z)

            # R34/W3-E (H7): mechanical fresh air through an ERV/HRV

            # core -- an INDEPENDENT channel superposed on the ach

            # infiltration above (guarded branch: disabled path touches

            # no float, bit-for-bit identical to pre-W3-E builds).

            # P3-9: when the dry-bulb economizer criterion holds during

            # cooling demand (T_ext <= T_z - delta), the core is

            # BYPASSED and full fresh air at economizer_flow_m3h

            # provides free cooling instead (bypassing a core while

            # recovering makes no sense).  Fan power runs with the

            # active airflow and is metered for the electric total.

            Q_erv = M_erv = Q_lat_erv = 0.0

            P_erv_fan_s = 0.0

            econ_active = econ_on and hv["mode"] == "cool" and T_ext[h] <= T_z - econ_dt_k

            if econ_active:
                Q_erv, M_erv, Q_lat_erv = env.economizer_ventilation(
                    T_ext[h], T_z, W_ext, W_z, econ_flow
                )

                if Q_erv < 0.0:
                    econ_free_cool_j += -Q_erv * dt

                econ_active_s += dt

                if erv_fan_w > 0.0 and erv_fan_ref_flow > 0.0:
                    P_erv_fan_s = erv_fan_w * (econ_flow / erv_fan_ref_flow)

            elif erv_on:
                (
                    Q_erv,
                    M_erv,
                    Q_lat_erv,
                    _q_rec_s,
                    _q_rec_l,
                ) = env.mechanical_ventilation(T_ext[h], T_z, W_ext, W_z)

                erv_rec_sens_j += abs(_q_rec_s) * dt

                erv_rec_lat_j += abs(_q_rec_l) * dt

                if erv_fan_w > 0.0 and env.erv_flow_m3h > 0.0:
                    P_erv_fan_s = erv_fan_w

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
                M_erv_kgs=M_erv,
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

            # R34/W3-E: superpose the ERV net fresh-air loads on both

            # balances (guarded add -- the disabled path leaves the two

            # sums above bit-for-bit untouched).  P3-9 extends the

            # branch to the economizer path and dissolves the fan

            # power as heat inside the envelope (supply + exhaust fans

            # both sit in the room boundary; conservative).

            if erv_on or econ_active:
                Q_total += Q_erv + Q_lat_erv

                M_total += M_erv

                if P_erv_fan_s > 0.0:
                    Q_total += P_erv_fan_s

            # ── humidity step with conservation accounting ─────────────

            # step_humidity clamps W_z to [0, W_sat].  The clamped water is

            # reported back so the room heat balance stays consistent:

            #   * sat_clip: moisture condensed at the saturation cap releases

            #     L_v of latent heat into the room (add it back);

            #   * floor_clip: moisture "removed" beyond what exists never

            #     condensed — the phantom condenser heat (already in

            #     Q_DEH / Q_HVAC) must be removed from the balance.

            T_z_new, tmeta = ode.step_temperature(T_z, Q_total, dt, return_meta=True)

            W_z_new, wmeta = ode.step_humidity(W_z, M_total, T_z=T_z_new, dt=dt, return_meta=True)

            q_corr = (wmeta["sat_clipped_kg"] - wmeta["floor_clipped_kg"]) * L_v

            if q_corr != 0.0:
                T_z_new, tmeta = ode.step_temperature(T_z, Q_total + q_corr, dt, return_meta=True)

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

            # CO2 M1: injector electricity joins the building total

            # (guarded add -- the disabled path's P_tot is untouched).

            if co2_on:
                P_tot += P_co2_s

            # P3-9: ventilation fan electricity joins the building

            # total (guarded add -- 0 W default leaves P_tot untouched;

            # the heat side is already in Q_total above).

            if P_erv_fan_s > 0.0:
                P_tot += P_erv_fan_s

                erv_fan_j += P_erv_fan_s * dt

                erv_fan_wh += P_erv_fan_s * dt / 3600.0

            energy_wh += P_tot * dt / 3600.0

            hvac_wh += hv["P_elec_W"] * dt / 3600.0

            deh_wh += dh["P_elec_W"] * dt / 3600.0

            led_wh += P_led_s * dt / 3600.0

            ppfd_sum += light_wm2 * led.par_factor  # P3/B3: W/m² → µmol/(m²·s)

            qled_sum += Q_LED  # P3/B3: instantaneous LED heat (W)

            t_sum += T_z

            rh_sum += RH_z

            if not (np.isfinite(T_z) and np.isfinite(W_z)):
                raise RuntimeError(
                    f"NaN/inf state at hour {h}, sub-step {s}: " f"T_z={T_z}, W_z={W_z}"
                )

            if co2_on and not np.isfinite(c_z):
                raise RuntimeError(
                    f"NaN/inf CO2 state at hour {h}, sub-step {s}: "
                    f"c_z={c_z} (check co2.capacity_g_per_h / growth params)"
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

        if env.rc_enabled or env.fd_enabled:
            T_m_out[h] = tm_sum / sub

            if env.rc3_enabled or env.fd_enabled:
                T_s_out[h] = ts_sum / sub

            if env.fd_enabled:
                T_wall_out_arr[h] = twi_sum / sub

                T_sol_air_arr[h] = tos_sum / sub

        P_hvac[h] = hvac_wh

        P_deh[h] = deh_wh

        P_led[h] = led_wh

        # P3/B3: hourly substep-mean canopy PPFD (µmol/(m²·s); 0 in the

        # dark) and LED heat to the room (W) — additive output columns.

        ppfd_out.append(ppfd_sum / sub)

        qled_out.append(qled_sum / sub)

        P_misc[h] = p.equipment_power_w  # W × 1h = Wh

        X_d_arr[h] = X_d

        # CO2 M1: hourly output columns (substep means; E in Wh).

        if co2_on:
            CO2_z_out[h] = co2_ppm_sum / sub

            S_co2_inj_out[h] = co2_inj_sum / sub * 3.6e6  # kg/s -> g/h

            E_co2_Wh[h] = co2_wh

        # ── monthly accumulation ──

        monthly_energy[month_idx, 0] += load_kw[h]

        monthly_energy[month_idx, 1] += hvac_wh / 1000.0

        monthly_energy[month_idx, 2] += deh_wh / 1000.0

        monthly_energy[month_idx, 3] += led_wh / 1000.0

        monthly_energy[month_idx, 4] += p.equipment_power_w / 1000.0

        # CO2 M1: injector electricity folded into the "misc" bucket

        # (energy_breakdown keeps its 4-key structure; documented

        # attribution) so the monthly components close against the

        # monthly total.

        if co2_on:
            monthly_energy[month_idx, 4] += co2_wh / 1000.0

        # P3-9: ventilation-fan electricity folded into the "misc"

        # bucket the same way, so the monthly components close

        # against the monthly total (fan off -> += 0.0, bit-identical).

        if erv_fan_w > 0.0:
            monthly_energy[month_idx, 4] += erv_fan_wh / 1000.0

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

            # Reset the internal states (C_buf, LAI) alongside X_d so a

            # new cycle starts from the seedling state.  No-op on the

            # 1-state model (no internal states).

            grow.reset(X_d_init)

            cycle_h = 0.0  # stage clock resets with X_d (staged methods)

            next_harvest_h += harvest_hours

    return LoopState(
        X_d=X_d,
        co2_inj_total_kg=co2_inj_total_kg,
        deh_comp_kwh=deh_comp_kwh,
        econ_active_s=econ_active_s,
        econ_free_cool_j=econ_free_cool_j,
        erv_fan_j=erv_fan_j,
        erv_rec_lat_j=erv_rec_lat_j,
        erv_rec_sens_j=erv_rec_sens_j,
        next_harvest_h=next_harvest_h,
        total_harvest_kg=total_harvest_kg,
        total_water_kg=total_water_kg,
    )
