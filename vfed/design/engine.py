"""
Design engine — runs the digital-twin building simulation for a project and
produces the hourly electrical load profile plus indoor climate timeseries.

The building ODE is integrated at the project timestep (default 10 min) and
aggregated to hourly load (kW) consumed by the PVBES layer. Device state
(compressor hysteresis, transient lags) is continuous across the whole year.
"""

import logging
import math
import warnings
from typing import List, Optional

import numpy as np
import pandas as pd

from ..physics.psychrometrics import temp_rh_to_ah, latent_heat_vaporization
from ..physics.envelope import Envelope
from ..physics.ode import RoomODESolver
from ..physics.shr import DynamicSHR
from ..devices.hvac import HVACDevice, COPModel, size_hvac
from ..devices.dehumidifier import DEHDevice, size_deh
from ..devices.co2 import CO2Device, ppm_to_mixing_ratio
from ..devices.led import LEDDevice
from ..plants.transpiration import TranspirationModel
from ..plants.van_henten import VanHenten
from ..plants.van_henten_3state import VanHenten3State
from ..weather.series import WeatherSeries
from ..weather.weather_bridge import fetch_weather, to_hourly
from .result import SimulationResult

__all__ = ["DesignEngine", "run_project", "full_load_warnings"]


def _build_growth(p):
    """Build the crop growth model selected by ``p.growth.model``.

    ``van_henten`` (default): 1-state model, constructed with the exact
    same eight parameter arguments as the historical inline calls — the
    609 baseline must stay bit-identical (zero-drift gate).

    ``van_henten_3state``: 3-state Van Henten variant ([X_d, C_buf, LAI],
    BJAAF MATLAB port) with every parameter taken from the nested
    ``growth.three_state`` config block; density (rho_c) and initial LAI
    are passed explicitly, the remaining numeric fields by reflection.
    """
    g = p.growth
    if g.model == "van_henten_3state":
        ts = g.three_state
        overrides = {
            name: getattr(ts, name)
            for name in type(ts).__dataclass_fields__
            if name not in ("initial_lai", "rho_c")
        }
        return VanHenten3State(
            co2_ppm=p.setpoints.co2_ppm,
            rho_c=ts.rho_c,
            initial_lai=ts.initial_lai,
            **overrides,
        )
    return VanHenten(
        co2_ppm=p.setpoints.co2_ppm,
        c_alpha_beta=g.c_alpha_beta,
        c_resp_d=g.c_resp_d,
        c_pl_d=g.c_pl_d,
        c_rad_phot=g.c_rad_phot,
        c_co2_1=g.c_co2_1,
        c_co2_2=g.c_co2_2,
        c_co2_3=g.c_co2_3,
        c_Gamma=g.c_Gamma,
    )


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
    M_erv_kgs=0.0,
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
    cap -- this preserves the W_z >= 0 guarantee (when net >= 0 and the cap
    binds, W_z_new lands exactly at 0).  Defaults keep the legacy 5-arg call
    bitwise identical.  ``M_erv_kgs`` (R34/W3-E) is the net ERV fresh-air
    moisture, joining the same source sum (default 0 = bitwise identical).

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
    source = max(0.0, E_trans_kgs + M_inf_kgs + M_perm_kgs + M_erv_kgs)  # kg/s
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


def _wall_rc_stability_guard(p) -> None:
    """R28: forward-Euler stability guard for the 2R2C wall mass network.

    Closed-form |lambda|max of the 2x2 (T_z, T_m) state matrix (per design
    report layerC_rc_design.md section 2.3; no numpy needed)::

        A = [[-(g_z_ext+g_im)/C_z',  g_im/C_z'        ],
             [ g_im/C_m',           -(g_em+g_im)/C_m' ]]

    with C' = C*3600 (Wh/K -> J/K) and g_z_ext = direct channel U_wall_A +
    infiltration conductance m_dot*cp_air.  Forward Euler is stable for
    dt <= 2/|lambda|max; the engine fails fast when dt exceeds 0.8x of that
    (the 0.8 safety factor absorbs secondary couplings).  Only runs when
    wall_rc_nodes=2 -- the default single-node path never enters here.
    """
    e = p.envelope
    if e.wall_rc_nodes != 2:
        return
    dt = p.space.timestep_s
    c_z_j = e.C_z * 3600.0  # Wh/K -> J/K
    c_m_j = e.C_mass * 3600.0  # Wh/K -> J/K
    m_dot = e.ach * e.V_room * e.rho_air / 3600.0  # kg/s
    # R34/W3-E: an enabled ERV adds its UNRECOVERED (1 - eps_s) share of
    # the ventilation mass flow to the air-node conductance (the recovered
    # share is exchanged inside the core, not with the room air).
    if e.erv_enabled:
        m_dot += (1.0 - e.erv_sensible_eff) * e.erv_flow_m3h * e.rho_air / 3600.0
    g_z_ext = e.U_wall_A + m_dot * e.cp_air  # W/K direct channel + infiltration
    a = (g_z_ext + e.g_im) / c_z_j
    b = (e.g_em + e.g_im) / c_m_j
    tr = a + b  # = -trace(A) > 0
    det = (g_z_ext * e.g_em + g_z_ext * e.g_im + e.g_em * e.g_im) / (c_z_j * c_m_j)
    disc = tr * tr / 4.0 - det
    lam_max = tr / 2.0 + math.sqrt(disc) if disc > 0.0 else tr / 2.0  # |lambda|max, 1/s
    dt_max = 2.0 / lam_max  # s
    if dt > 0.8 * dt_max:
        raise RuntimeError(
            f"2R2C wall mass network unstable at dt={dt:.0f} s: forward-Euler "
            f"stability limit dt_max={dt_max:.0f} s (0.8x margin "
            f"{0.8 * dt_max:.0f} s). Loosen the network: raise C_z "
            f"(>= {e.C_z * dt / (0.8 * dt_max):.0f} Wh/K), C_mass, or lower "
            f"g_im (currently C_z={e.C_z:.0f} Wh/K, C_mass={e.C_mass:.0f} Wh/K, "
            f"g_im={e.g_im:.0f} W/K, g_em={e.g_em:.1f} W/K)."
        )


def _wall_rc3_stability_guard(p) -> None:
    """R28 step 3: forward-Euler stability guard for the 2R3C wall network.

    Closed-form |lambda|max of the 3x3 (T_z, T_s, T_m) state matrix; no
    numpy needed.  A is a positive diagonal D^{-1} times a symmetric
    negative-definite conductance matrix L (A ~ D^{-1/2} L D^{-1/2}), so all
    three eigenvalues are real and <= 0; they follow from the characteristic
    cubic via the trigonometric (Cardano) closed form::

        A = [[-(g_z_ext+g_sa)/Cz',  g_sa/Cz',               0          ],
             [  g_sa/Cs',          -(g_sa+g_sm)/Cs',         g_sm/Cs'   ],
             [  0,                  g_sm/Cm',               -(g_em+g_sm)/Cm']]

    with C' = C*3600 (Wh/K -> J/K) and g_z_ext = direct channel U_wall_A +
    infiltration conductance m_dot*cp_air.  Forward Euler is stable for
    dt <= 2/|lambda|max; fail fast at 0.8x.  Only runs when
    wall_rc_nodes=3 -- every other mode returns immediately.
    """
    e = p.envelope
    if e.wall_rc_nodes != 3:
        return
    dt = p.space.timestep_s
    c_z_j = e.C_z * 3600.0  # Wh/K -> J/K
    c_s_j = e.C_surface * 3600.0
    c_m_j = e.C_mass * 3600.0
    m_dot = e.ach * e.V_room * e.rho_air / 3600.0  # kg/s
    # R34/W3-E: same unrecovered-ERV conductance term as the 2R2C guard.
    if e.erv_enabled:
        m_dot += (1.0 - e.erv_sensible_eff) * e.erv_flow_m3h * e.rho_air / 3600.0
    g_z_ext = e.U_wall_A + m_dot * e.cp_air  # W/K direct channel + infiltration
    a11 = -(g_z_ext + e.g_sa) / c_z_j
    a22 = -(e.g_sa + e.g_sm) / c_s_j
    a33 = -(e.g_em + e.g_sm) / c_m_j
    a12 = e.g_sa / c_z_j
    a21 = e.g_sa / c_s_j
    a23 = e.g_sm / c_s_j
    a32 = e.g_sm / c_m_j
    # Characteristic cubic lam^3 + c2*lam^2 + c1*lam + c0 = 0 with
    # c2 = -trace, c1 = sum of principal 2x2 minors, c0 = -det.
    c2 = -(a11 + a22 + a33)
    c1 = (
        (a22 * a33 - a23 * a32)  # minor without row/col 1
        + a11 * a33  # minor without row/col 2 (off-diag pair is zero)
        + (a11 * a22 - a12 * a21)  # minor without row/col 3
    )
    c0 = -(a11 * (a22 * a33 - a23 * a32) - a12 * a21 * a33)
    # Depressed cubic t = lam - c2/3:  t^3 + pp*t + qq = 0.
    pp = c1 - c2 * c2 / 3.0
    qq = 2.0 * c2**3 / 27.0 - c2 * c1 / 3.0 + c0
    disc = -4.0 * pp**3 - 27.0 * qq**2  # >= 0 for three real roots
    if disc >= 0.0:
        # Trigonometric form: lam_k = m*cos(theta - 2*pi*k/3) - c2/3.
        m = 2.0 * math.sqrt(-pp / 3.0)
        arg = 3.0 * qq / (pp * m)
        theta = math.acos(arg if arg > -1.0 else -1.0) / 3.0
        lam_max = 0.0
        for k in range(3):
            lam = m * math.cos(theta - 2.0 * math.pi * k / 3.0) - c2 / 3.0
            lam_max = max(lam_max, abs(lam))
    else:
        # Numerically slipped past the (theoretically guaranteed) three-real-
        # roots region: fall back to the conservative Gershgorin upper bound
        # of |lambda| for the similar symmetric matrix -- stricter guard,
        # never unsafe.
        lam_max = max(
            abs(a11) + a12,
            abs(a22) + a21 + a23,
            abs(a33) + a32,
        )
    dt_max = 2.0 / lam_max  # s
    if dt > 0.8 * dt_max:
        raise RuntimeError(
            f"2R3C wall network unstable at dt={dt:.0f} s: forward-Euler "
            f"stability limit dt_max={dt_max:.0f} s (0.8x margin "
            f"{0.8 * dt_max:.0f} s). Loosen the network: raise C_z, "
            f"C_surface or C_mass, or lower g_sa/g_sm (currently "
            f"C_z={e.C_z:.0f} Wh/K, C_surface={e.C_surface:.0f} Wh/K, "
            f"C_mass={e.C_mass:.0f} Wh/K, g_sa={e.g_sa:.0f} W/K, "
            f"g_sm={e.g_sm:.0f} W/K, g_em={e.g_em:.1f} W/K)."
        )


def _wall_fd_stability_guard(p) -> None:
    """R28 step 6: FD-wall runtime guard.

    The 1-D FD wall is advanced with a FULLY IMPLICIT (backward-Euler)
    solve -- unconditionally stable for any dt, so there is no lambda-max
    band to enforce.  What can still go wrong at build time is a
    non-positive timestep (division by zero in the C/dt terms) or a
    degenerate discretisation; both are rejected here (and, for the config
    surface, in ``DesignProject.from_dict`` / ``Envelope.__init__``).
    """
    e = p.envelope
    if e.wall_fd_nodes == 0:
        return
    dt = p.space.timestep_s
    if not (dt > 0.0):
        raise RuntimeError(
            f"FD wall requires timestep_s > 0 (got {dt!r}); the implicit "
            "solve is unconditionally stable but needs a positive dt."
        )
    if not (10 <= int(e.wall_fd_nodes) <= 100):
        raise RuntimeError(f"wall_fd_nodes must be in [10, 100] (got {e.wall_fd_nodes!r}).")


def _resolve_control_steps(dt: float, period_s) -> int:
    """T2 (nested-time v2): control cadence in integer substeps.

    ``period_s`` None resolves to the physics timestep (k = 1, legacy
    behaviour).  The period must be an integer multiple of dt and at
    least dt; otherwise raise (fail fast, mirroring the dt|3600 gate) —
    a non-integer k would make an ``N % k`` tick test silently never
    fire (B2: float-modulo trap).
    """
    period = float(dt) if period_s is None else float(period_s)
    k = period / float(dt)
    ki = int(round(k))
    if ki < 1 or abs(k - ki) > 1e-9:
        raise ValueError(
            f"control.period_s={period_s} must be an integer multiple of "
            f"space.timestep_s={dt}s (and >= dt); got k={k}. Choose "
            f"period_s = k * timestep_s."
        )
    return ki


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
        # R28 additive: defaults (0/0/0/0) keep the legacy single-node path
        # bit-for-bit; wall_rc_nodes=2 activates the 2R2C wall mass network,
        # wall_rc_nodes=3 the 2R3C wall network (R28 step 3).
        wall_rc_nodes=p.envelope.wall_rc_nodes,
        C_mass=p.envelope.C_mass,
        g_im=p.envelope.g_im,
        g_em=p.envelope.g_em,
        # R28 step 3 additive: 2R3C surface node + solar split (defaults 0
        # keep every existing path bit-for-bit).
        C_surface=p.envelope.C_surface,
        g_sa=p.envelope.g_sa,
        g_sm=p.envelope.g_sm,
        solar_mass_fraction=p.envelope.solar_mass_fraction,
        # R28 step 6 additive: 1-D FD wall continuum (defaults keep every
        # existing path bit-for-bit).
        wall_fd_nodes=p.envelope.wall_fd_nodes,
        wall_layers=p.envelope.wall_layers,
        wall_area_m2=p.envelope.wall_area_m2,
        h_ext_wm2=p.envelope.h_ext_wm2,
        wall_solar_abs=p.envelope.wall_solar_abs,
        h_int_c_wm2=p.envelope.h_int_c_wm2,
        # R34/W3-E (H7) additive: ERV/HRV mechanical fresh air with heat
        # recovery (default off = no mechanical ventilation channel,
        # bit-for-bit the legacy path).
        erv_enabled=p.envelope.erv_enabled,
        erv_flow_m3h=p.envelope.erv_flow_m3h,
        erv_sensible_eff=p.envelope.erv_sensible_eff,
        erv_latent_eff=p.envelope.erv_latent_eff,
        # P3-9: dry-bulb economizer + fan power (defaults off/0 keep the
        # legacy path bit-for-bit).
        economizer_enabled=p.envelope.economizer_enabled,
        economizer_flow_m3h=p.envelope.economizer_flow_m3h,
        economizer_delta_t_k=p.envelope.economizer_delta_t_k,
        erv_fan_power_w=p.envelope.erv_fan_power_w,
    )
    # R28: closed-form Euler stability guard (only active when RC is on).
    _wall_rc_stability_guard(p)
    # R28 step 3: 3-node closed-form guard (only active at wall_rc_nodes=3).
    _wall_rc3_stability_guard(p)
    # R28 step 6: FD-wall guard (dt > 0; implicit solve is unconditionally
    # stable).  Only active when wall_fd_nodes > 0.
    _wall_fd_stability_guard(p)
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
        ppfd_layers=p.led.ppfd_layers,  # P3/A1: spatial per-layer PPFD (None = uniform)
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
        # R34/H1a: lift-dependent COP soft ceiling (default off = flat cap,
        # bit-identical legacy path).
        cop_soft_cap=p.hvac.cop_soft_cap,
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
        light_ref_wm2=led.par_wm2,  # P3/A4: design PAR — runtime light factor
        # scales as clamp(light_wm2/par_wm2, 0, 1); with uniform legacy light
        # light_wm2 == led.par_wm2 exactly, so the factor is 1.0 bit-identical.
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
        grow = _build_growth(p)
        xd = p.growth.initial_dry_weight
        # P4-11: use the LED-derived PAR flux so the pre-run growth/DEH
        # sizing matches the runtime light state (identical to ppfd/par_factor
        # under auto_deduce, tracks the configured power otherwise).
        # P3/A3: with ppfd_layers set, canopy_par_wm2 is the layer-mean PAR —
        # the DEH-sizing pre-run sees the same (lower) crop light as runtime.
        light_wm2 = led.canopy_par_wm2
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
        # R34/W3-E: mechanical fresh air adds its un-recovered (1 - eps_l)
        # share of the outdoor moisture surplus to the design moisture load
        # (an HRV with eps_l=0 takes the full fresh-air moisture).
        m_erv = 0.0
        if p.envelope.erv_enabled:
            m_erv = (
                (1.0 - p.envelope.erv_latent_eff)
                * p.envelope.erv_flow_m3h
                * p.envelope.rho_air
                / 3600.0
                * max(0.0, W_ext - W_z)
            )
        moisture_load = max(0.0, m_transp + m_inf + m_perm + m_erv)
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
        smer_curve=p.deh.smer_curve,
        smer_map=p.deh.smer_map,
        tau_q=p.deh.tau_q,
        tau_m=p.deh.tau_m,
        mod_band_rh=p.deh.comp_mod_band_rh,
        control=p.deh.control,
        setpoint_modulation=p.deh.setpoint_modulation,
        floor_w=p.deh.floor_w,
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
    # R28: with the 2R2C wall mass network active, U_wall_A is the DIRECT
    # channel only; the steady-state design-load conductance closes through
    # the mass node as UA_dc = U_wall_A + g_em*g_im/(g_em+g_im) (series
    # g_em/g_im legs), so auto-sizing keeps the same DC aperture as the
    # legacy single-node semantics.  R28 step 3: 2R3C closes through the
    # series g_sa/g_sm/g_em chain.  Default path (RC off): unchanged.
    _ua_env = p.envelope.U_wall_A
    if p.envelope.wall_rc_nodes == 2:
        _ua_env += (p.envelope.g_em * p.envelope.g_im) / (p.envelope.g_em + p.envelope.g_im)
    elif p.envelope.wall_rc_nodes == 3:
        if p.envelope.g_em > 0.0:
            _ua_env += 1.0 / (
                1.0 / p.envelope.g_sa + 1.0 / p.envelope.g_sm + 1.0 / p.envelope.g_em
            )  # g_em = 0 (pure internal mass): no DC path, adds nothing
    elif p.envelope.wall_fd_nodes > 0:
        # R28 step 6: the FD wall's DC aperture is the series
        # exterior-film -> layer stack -> interior-convective-film path
        # (the radiative share feeds the internal mass node, not the air).
        _layers = p.envelope.wall_layers
        _r_lay = (
            sum(lay[0] / lay[1] for lay in _layers) / p.envelope.wall_area_m2
        )  # K/W through the full stack
        _ua_env += 1.0 / (
            1.0 / (p.envelope.h_ext_wm2 * p.envelope.wall_area_m2)
            + _r_lay
            + 1.0 / (p.envelope.h_int_c_wm2 * p.envelope.wall_area_m2)
        )
    if p.hvac.Q_cool_nom > 0:
        # New mode: nominal cooling capacity (kW) → rated electrical power (W)
        P_rated = p.hvac.Q_cool_nom * 1000.0 / max(cop_design, 0.5)
        P_rated_heat = p.hvac.P_rated_heat_w if p.hvac.P_rated_heat_w > 0 else P_rated
        if p.hvac.P_rated_max > 0:
            P_rated = min(P_rated, p.hvac.P_rated_max * 1000.0)
    elif p.hvac.auto_size:
        # R34/W3-E: the ERV's un-recovered ventilation sensible load is
        # added as an equivalent infiltration ach at the design point
        # ((1 - eps_s) * flow / V_room has the same m_dot*cp*(dT) effect).
        _ach_sizing = p.envelope.ach
        if p.envelope.erv_enabled:
            _ach_sizing += (
                (1.0 - p.envelope.erv_sensible_eff) * p.envelope.erv_flow_m3h / p.envelope.V_room
            )
        P_rated = size_hvac(
            U_wall_A=_ua_env,
            A_window=p.envelope.A_window,
            eta_solar=p.envelope.eta_solar,
            ach=_ach_sizing,
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
        # R34/H2 + H3: crankcase heater + defrost (both default-off / zero,
        # bit-identical to the pre-R34 device path).
        crankcase_heat_w=p.hvac.crankcase_heat_w,
        defrost=p.hvac.defrost,
        defrost_threshold_c=p.hvac.defrost_threshold_c,
        defrost_interval_min=p.hvac.defrost_interval_min,
        defrost_duration_min=p.hvac.defrost_duration_min,
    )

    ode = RoomODESolver(
        C_z=p.envelope.C_z, V_room=p.envelope.V_room, rho_air=p.envelope.rho_air, P_atm=P_atm
    )
    # ── CO2 enrichment injector (additive, CO2 supplement M1) ──
    # Constructed ONLY when the project enables the CO2 balance; the
    # default None keeps every legacy caller's path untouched (zero drift:
    # the disabled path builds no device and runs no new float op).
    co2_dev = None
    if p.co2.enabled:
        co2_dev = CO2Device(
            capacity_g_per_h=p.co2.capacity_g_per_h,
            band_ppm=p.co2.band_ppm,
            control=p.co2.control,
            inject_in_dark=p.co2.inject_in_dark,
            min_on_s=p.co2.min_on_s,
            min_off_s=p.co2.min_off_s,
            power_w=p.co2.power_w,
            tau_s=p.co2.tau_s,
        )
    return env, hvac, deh, led, transp, ode, co2_dev


class DesignEngine:
    def __init__(self, cache_dir: Optional[str] = "weather_cache"):
        self.cache_dir = cache_dir

    def run(self, project, weather: Optional[pd.DataFrame] = None, policy=None) -> SimulationResult:
        """Run a full-year simulation and return a ``SimulationResult``.

        ``policy`` (C1 control protocol) optionally attaches a
        ``BuildingPolicy`` to the building loop; ``None`` (the default)
        keeps the config-driven path bit-identical.  When a policy is
        attached, ``p.control.period_s`` sets the control tick cadence
        and the policy's ``step`` is called every tick, with
        ``plan_daily`` at each day boundary.

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
                # G2 (Wave 1): POA transposition inputs (defaults keep the
                # legacy isotropic / albedo=0.2 bitstream).
                albedo=p.site.albedo,
                transposition=p.site.transposition,
            )
        # P2-2: weather provenance (fetch layer tags df.attrs) -- copy it out
        # so the reporting layer can self-evidence the weather source.  The
        # DataFrame itself is never rebuilt here, so the attrs survive; a
        # caller-supplied df without attrs degrades to an empty dict.
        weather_attrs = dict(getattr(weather, "attrs", {}) or {})
        # T3 (nested-time v2): dual view.  ``weather_hourly`` is the report/
        # PVBES/sweep view (hourly aggregates; hourly input hits the
        # identity fast path and stays bit-identical incl. dtype/attrs).
        # ``weather_series`` is the building loop's native-resolution ZOH
        # lookup built from the raw frame (T1 wiring, upgraded in T3).
        weather_hourly = to_hourly(weather)
        weather_series = WeatherSeries.from_dataframe(weather)
        n = len(weather_hourly)
        dt = p.space.timestep_s
        sub = max(1, int(round(3600.0 / dt)))
        if abs(sub * dt - 3600.0) > 1.0:
            raise ValueError(
                f"Timestep {dt}s does not evenly divide 3600s "
                f"(sub={sub}, modeled={sub * dt}s/h). "
                f"Choose dt that divides 3600 evenly "
                f"(e.g., 600, 900, 1200, 1800, 3600)."
            )

        # T2 (nested-time v2): fail-fast cadence check — control.period_s
        # must be an integer multiple of dt (k substeps per tick).  C1
        # captures the resolved tick length and passes it to the loop.
        control_steps = _resolve_control_steps(dt, p.control.period_s)

        T_ext = weather_hourly["temperature_2m"].values.astype(float)
        RH_ext = weather_hourly["relative_humidity_2m"].values.astype(float)
        GHI = weather_hourly["shortwave_radiation"].values.astype(float)
        hours = weather_hourly.index.hour.values.astype(float)
        months = weather_hourly.index.month.values.astype(int)
        days = weather_hourly.index.day.values.astype(int)
        direct = weather_hourly["direct_radiation"].values.astype(float)
        diffuse = weather_hourly["diffuse_radiation"].values.astype(float)

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
        surface_pressure = weather_hourly.get(
            "surface_pressure",
            pd.Series([1013.25] * n, index=weather_hourly.index),
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

        env, hvac, deh, led, transp, ode, co2_dev = _build_devices(p, P_atm=P_atm)

        # P0-4 full-load observation thresholds (reporting only): the HVAC
        # draws its rated electrical input when the VFD sits at m = 1
        # (cap(1) = eir(1) = 1.0), so a substep is "at rated capacity" when
        # P_elec >= 99% of rated + fan.  The DEH draw varies with T/W
        # conditions, so its modulation coefficient (m >= 0.999) is the
        # full-speed signal instead.
        hvac_cool_full_w = 0.99 * (hvac.P_rated + hvac.comp.fan_power_w)
        hvac_heat_full_w = 0.99 * (hvac.P_rated_heat + hvac.comp.fan_power_w)

        # ── plant growth model ─────────────────────────────────────────────
        # Selected by p.growth.model: "van_henten" (1-state, default/609
        # zero-drift) or "van_henten_3state" (3-state, LAI/C_buf states).
        grow = _build_growth(p)
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
        # ── CO2 concentration state (additive; CO2 supplement M1) ──────
        # Zero drift: every float below sits behind the co2_on guard; the
        # disabled default path initialises nothing and never reads these.
        co2_on = p.co2.enabled
        co2_sp_ppm = p.co2.setpoint_ppm if p.co2.setpoint_ppm is not None else p.setpoints.co2_ppm
        if co2_on:
            # Initial concentration at the setpoint (avoids a start-up
            # transient -- same convention as T_z init at T_light), unless
            # the user pins co2_initial_ppm.
            c_z = ppm_to_mixing_ratio(
                p.co2.co2_initial_ppm if p.co2.co2_initial_ppm is not None else co2_sp_ppm
            )
            c_out = ppm_to_mixing_ratio(p.envelope.outdoor_co2_ppm)
            # Gamma (growth CO2 compensation point, kg/m3) in mixing-ratio
            # form (kg/kg): divide by the configured room air density.
            co2_gamma = p.growth.c_Gamma / p.envelope.rho_air
            # ach infiltration mass flow (envelope.py:812 same expression);
            # the ERV fresh-air CO2 channel is an M3 deliverable.
            m_dot_ach_co2 = p.envelope.ach * p.envelope.V_room * p.envelope.rho_air / 3600.0
            air_mass_co2 = p.envelope.V_room * p.envelope.rho_air
        # R28: 2R2C wall mass node starts consistent with the air node
        # (T_m init == T_z init; same warm-up caveat as the air node).
        # R28 step 3: 2R3C surface node T_s likewise.  R28 step 6: FD-wall
        # continuum + mass node likewise.
        if env.rc_enabled or env.fd_enabled:
            env.reset(T_z)
            T_m_out = np.zeros(n)
            if env.rc3_enabled or env.fd_enabled:
                T_s_out = np.zeros(n)
            if env.fd_enabled:
                T_wall_out_arr = np.zeros(n)  # exterior cell (diagnostic)
                T_sol_air_arr = np.zeros(n)  # sol-air boundary (diagnostic)

        # ── hourly output arrays ───────────────────────────────────────────
        load_kw = np.zeros(n)
        T_z_out = np.zeros(n)
        RH_z_out = np.zeros(n)
        P_hvac = np.zeros(n)
        P_deh = np.zeros(n)
        P_led = np.zeros(n)
        P_misc = np.zeros(n)
        X_d_arr = np.zeros(n)
        # CO2 supplement (M1): additive output columns + accumulators,
        # allocated ONLY when enabled (T_m/T_s convention: additive columns
        # must not leak into the default path).
        if co2_on:
            CO2_z_out = np.zeros(n)  # ppm, substep mean
            S_co2_inj_out = np.zeros(n)  # g/h, substep mean
            E_co2_Wh = np.zeros(n)  # injector electricity, Wh per hour
            monthly_co2_kg = np.zeros(12)
            co2_inj_total_kg = 0.0
            # Γ-floor clamp accounting (ode.step_co2 return_meta): a clamp
            # is never silently dropped (P0-2 "钳位不静默").
            co2_clamp_stats = {
                "floor_clip_events": 0,
                "floor_clip_co2_kg": 0.0,
            }
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
        # P3/B3: hourly light-diagnostic accumulators (canopy-mean PPFD and
        # LED heat released to the room), plain lists appended once per hour —
        # additive timeseries columns, no physics impact.
        ppfd_out: List[float] = []
        qled_out: List[float] = []
        # R34/W3-E (H7): ERV recovered-energy meters (J, absolute values;
        # sensible and latent split).  Zero on the default off path.
        erv_rec_sens_j = 0.0
        erv_rec_lat_j = 0.0
        erv_on = env.erv_enabled
        # P3-9: dry-bulb economizer + ERV fan power meters.  Zero on both
        # default-off paths (guarded adds below touch no float otherwise).
        econ_on = env.economizer_enabled
        econ_flow = env.economizer_flow_m3h
        econ_dt_k = env.economizer_delta_t_k
        erv_fan_w = env.erv_fan_power_w
        # Reference flow for the fan-power linear scaling (EC motor,
        # first order): the flow the nameplate W refers to.
        erv_fan_ref_flow = env.erv_flow_m3h if erv_on else econ_flow
        econ_free_cool_j = 0.0
        econ_active_s = 0.0
        erv_fan_j = 0.0
        # C5 split (interface-preserving): the hourly loop lives in
        # .engine_loop and the report layer in .engine_report. Lazy
        # imports here break the cycle: both import helpers/constants
        # from this module at top level, which is fully loaded by the
        # time run() is first called.
        from .engine_loop import ZoneState, run_hourly_loop
        from .engine_report import build_report

        # Conditionally-created setup buffers (e.g. `if co2_on:`)
        # are guarded by the same conditions in loop/report, so a
        # None placeholder is never read - mirrors pre-split behavior.
        if "CO2_z_out" not in locals():
            CO2_z_out = None
        if "E_co2_Wh" not in locals():
            E_co2_Wh = None
        if "S_co2_inj_out" not in locals():
            S_co2_inj_out = None
        if "T_m_out" not in locals():
            T_m_out = None
        if "T_s_out" not in locals():
            T_s_out = None
        if "T_sol_air_arr" not in locals():
            T_sol_air_arr = None
        if "T_wall_out_arr" not in locals():
            T_wall_out_arr = None
        if "air_mass_co2" not in locals():
            air_mass_co2 = None
        if "c_out" not in locals():
            c_out = None
        if "c_z" not in locals():
            c_z = None
        if "co2_clamp_stats" not in locals():
            co2_clamp_stats = None
        if "co2_gamma" not in locals():
            co2_gamma = None
        if "co2_inj_total_kg" not in locals():
            co2_inj_total_kg = None
        if "m_dot_ach_co2" not in locals():
            m_dot_ach_co2 = None
        if "monthly_co2_kg" not in locals():
            monthly_co2_kg = None

        # ZoneState packaging (multi-zone step 1): pure move.  The 72
        # per-zone arguments are bundled into one ZoneState; the shared
        # building context stays as plain keyword arguments.  The loop
        # mutates buffers in place, so build_report keeps reading these
        # same locals afterwards - mirrors pre-packaging behavior.
        zone_state = ZoneState(
            RH_z=RH_z,
            T_z=T_z,
            W_z=W_z,
            X_d=X_d,
            c_z=c_z,
            cycle_h=cycle_h,
            next_harvest_h=next_harvest_h,
            X_d_init=X_d_init,
            crop_area=crop_area,
            harvest_hours=harvest_hours,
            co2_on=co2_on,
            co2_sp_ppm=co2_sp_ppm,
            co2_gamma=co2_gamma,
            air_mass_co2=air_mass_co2,
            m_dot_ach_co2=m_dot_ach_co2,
            hvac_cool_full_w=hvac_cool_full_w,
            hvac_heat_full_w=hvac_heat_full_w,
            econ_on=econ_on,
            econ_dt_k=econ_dt_k,
            econ_flow=econ_flow,
            erv_on=erv_on,
            erv_fan_w=erv_fan_w,
            erv_fan_ref_flow=erv_fan_ref_flow,
            env=env,
            hvac=hvac,
            deh=deh,
            led=led,
            transp=transp,
            grow=grow,
            ode=ode,
            co2_dev=co2_dev,
            load_kw=load_kw,
            T_z_out=T_z_out,
            RH_z_out=RH_z_out,
            P_hvac=P_hvac,
            P_deh=P_deh,
            P_led=P_led,
            P_misc=P_misc,
            X_d_arr=X_d_arr,
            ppfd_out=ppfd_out,
            qled_out=qled_out,
            T_m_out=T_m_out,
            T_s_out=T_s_out,
            T_wall_out_arr=T_wall_out_arr,
            T_sol_air_arr=T_sol_air_arr,
            CO2_z_out=CO2_z_out,
            S_co2_inj_out=S_co2_inj_out,
            E_co2_Wh=E_co2_Wh,
            hvac_cool_full_h=hvac_cool_full_h,
            hvac_heat_full_h=hvac_heat_full_h,
            deh_full_h=deh_full_h,
            monthly_energy=monthly_energy,
            monthly_harvest=monthly_harvest,
            monthly_t_sum=monthly_t_sum,
            monthly_rh_sum=monthly_rh_sum,
            monthly_hours=monthly_hours,
            monthly_water_kg=monthly_water_kg,
            monthly_co2_kg=monthly_co2_kg,
            typical_load_sum=typical_load_sum,
            typical_count=typical_count,
            clamp_stats=clamp_stats,
            co2_clamp_stats=co2_clamp_stats,
            deh_perf=deh_perf,
            total_water_kg=total_water_kg,
            total_harvest_kg=total_harvest_kg,
            co2_inj_total_kg=co2_inj_total_kg,
            deh_comp_kwh=deh_comp_kwh,
            econ_active_s=econ_active_s,
            econ_free_cool_j=econ_free_cool_j,
            erv_fan_j=erv_fan_j,
            erv_rec_lat_j=erv_rec_lat_j,
            erv_rec_sens_j=erv_rec_sens_j,
        )
        loop = run_hourly_loop(
            zone_state=zone_state,
            P_atm=P_atm,
            c_out=c_out,
            dt=dt,
            hours=hours,
            months=months,
            n=n,
            p=p,
            sub=sub,
            weather_series=weather_series,
            policy=policy,
            control_steps=control_steps,
        )
        return build_report(
            CO2_z_out=CO2_z_out,
            E_co2_Wh=E_co2_Wh,
            GHI=GHI,
            P_deh=P_deh,
            P_hvac=P_hvac,
            P_led=P_led,
            P_misc=P_misc,
            RH_ext=RH_ext,
            RH_z_out=RH_z_out,
            S_co2_inj_out=S_co2_inj_out,
            T_ext=T_ext,
            T_m_out=T_m_out,
            T_s_out=T_s_out,
            T_sol_air_arr=T_sol_air_arr,
            T_wall_out_arr=T_wall_out_arr,
            T_z_out=T_z_out,
            X_d_arr=X_d_arr,
            X_d_init=X_d_init,
            clamp_stats=clamp_stats,
            co2_clamp_stats=co2_clamp_stats,
            co2_on=co2_on,
            co2_sp_ppm=co2_sp_ppm,
            crop_area=crop_area,
            days=days,
            deh_full_h=deh_full_h,
            deh_perf=deh_perf,
            diffuse=diffuse,
            direct=direct,
            env=env,
            erv_fan_w=erv_fan_w,
            hours=hours,
            hvac=hvac,
            hvac_cool_full_h=hvac_cool_full_h,
            hvac_heat_full_h=hvac_heat_full_h,
            led=led,
            load_kw=load_kw,
            monthly_co2_kg=monthly_co2_kg,
            monthly_energy=monthly_energy,
            monthly_harvest=monthly_harvest,
            monthly_hours=monthly_hours,
            monthly_rh_sum=monthly_rh_sum,
            monthly_t_sum=monthly_t_sum,
            monthly_water_kg=monthly_water_kg,
            months=months,
            n=n,
            p=p,
            ppfd_out=ppfd_out,
            qled_out=qled_out,
            self=self,
            typical_count=typical_count,
            typical_load_sum=typical_load_sum,
            weather=weather_hourly,
            weather_attrs=weather_attrs,
            X_d=loop.X_d,
            co2_inj_total_kg=loop.co2_inj_total_kg,
            deh_comp_kwh=loop.deh_comp_kwh,
            econ_active_s=loop.econ_active_s,
            econ_free_cool_j=loop.econ_free_cool_j,
            erv_fan_j=loop.erv_fan_j,
            erv_rec_lat_j=loop.erv_rec_lat_j,
            erv_rec_sens_j=loop.erv_rec_sens_j,
            next_harvest_h=loop.next_harvest_h,
            total_harvest_kg=loop.total_harvest_kg,
            total_water_kg=loop.total_water_kg,
        )


def run_project(project, weather=None):
    return DesignEngine().run(project, weather)
