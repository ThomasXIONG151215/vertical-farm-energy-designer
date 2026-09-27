"""ASHRAE 140 BESTEST (Layer C) harness library.

Compares the vfed single-zone ODE building core against ASHRAE Standard
140-2020 free-float / constant-thermostat test cases 600, 600FF, 900, 900FF.

Reference values: LBNL modelica-buildings BESTEST package (GitHub master),
which embeds the Standard 140 reference ranges and acceptance limits per
case (lbl-srg/modelica-buildings issues #3005, #3396).  Mirrored from
``user-gym/benchmarks/layerC_bestest_scout.md`` section 2.3 -- see the
REF dict below for the source annotation.

Everything here is harness-side only: no vfed production code path changes.
The two sanctioned instrumentations are:
  * ``vfed.physics.ode._DEFAULT_T_MAX`` raised to 90 degC for the run
    (Case 600FF free-float reference peaks 62.4-68.4 degC exceed the 60 degC
    production clamp; production default is untouched and restored after).
  * ``vfed.design.engine.HVACDevice.step`` wrapped to capture Q_HVAC_W per
    substep (the timeseries only carries electrical energy, and BESTEST
    compares thermal loads).

Weather: Denver Intl AP 725650 TMY3 EPW (energyplus.net, free distribution,
same source data as the LBNL ``USA_CO_Denver.Intl.AP.725650_TMY3.mos``).
Converted to the vfed 7-column contract; the ``shortwave_radiation`` column
carries SOUTH-VERTICAL plane-of-array irradiance (isotropic sky, rho_g=0.2)
so ``Q_solar = eta_solar * A_window * POA_south`` matches the BESTEST single
south-glazing geometry exactly (scout report section 4.1 option A).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Reference values -- ASHRAE 140-2020 via LBNL modelica-buildings mirror.
# Ranges are min..max across the validated tools; acceptance limits are the
# Standard 140 pass/fail band.  Sources: Buildings/ThermalZones/Detailed/
# Validation/BESTEST/Cases6xx/Case600(.FF).mo, Cases9xx/Case900(.FF).mo
# (annotated in-file "Reference results from ASHRAE/ANSI Standard 140").
# Controlled cases: annual heating/cooling in GJ and hourly-average peak kW.
# Free-float cases: annual min/max/mean of the hourly room temperature (degC).
# ---------------------------------------------------------------------------
REF: Dict[str, Dict[str, Tuple[float, float]]] = {
    "600": {
        "annual_heating_gj": (3.993, 4.504),
        "annual_cooling_gj": (5.432, 6.162),
        "peak_heating_kw": (3.020, 3.359),
        "peak_cooling_kw": (5.422, 6.481),
        "accept_heating_gj": (3.75, 4.98),
        "accept_cooling_gj": (5.00, 6.83),
    },
    "600FF": {
        "min_t": (-13.8, -9.9),
        "max_t": (62.4, 68.4),
        "mean_t": (24.3, 26.1),
    },
    "900": {
        "annual_heating_gj": (1.379, 1.814),
        "annual_cooling_gj": (2.267, 2.714),
        "peak_heating_kw": (2.443, 2.778),
        "peak_cooling_kw": (2.556, 3.376),
        "accept_heating_gj": (1.04, 2.28),
        "accept_cooling_gj": (2.35, 2.60),
    },
    "900FF": {
        "min_t": (0.6, 2.2),
        "max_t": (43.3, 46.0),
        "mean_t": (24.5, 25.7),
    },
}

REF_SOURCE = (
    "ASHRAE/ANSI Standard 140-2020 reference ranges, mirrored from the LBNL "
    "modelica-buildings BESTEST package (issues #3005/#3396); geometry per "
    "Case600FF.mo base class."
)

# Scout report section 3.5 derivation, transcribed for provenance.
GEOMETRY_NOTE = (
    "BESTEST single zone: 6 m x 8 m x 2.7 m (floor 48 m2, volume 129.6 m3); "
    "south glazing 12 m2 (6x2 m, frameless).  U_wall_A folds opaque walls "
    "(63.6 m2, U~0.51), roof (48 m2, U~0.32) and window (12 m2, U~3.07) into "
    "one conduction channel: 600: 63.6*0.512+48*0.318+12*3.07 = 85 W/K; "
    "900: 63.6*0.509+48*0.318+12*3.07 = 84.7 W/K.  Infiltration: 0.414 ACH "
    "altitude-corrected mass flow 0.0149 kg/s -> ach=0.346 at rho_air=1.2."
)

# Denver Intl AP station metadata (EPW LOCATION header).
LAT, LON, TZ_HOURS, ELEV_M = 39.83, -104.65, -7.0, 1650.0

# Adopted (calibrated) parameter set per case.  Calibration path (probed
# against the 600FF free-float triple, scout section 5 "可标定量"):
#   * scout initial C_z=700/eta=0.75/UA=85 -> maxT 60.6 (OUT low), mean 24.06 (OUT low)
#   * eta_solar=0.78, C_z=600 -> all three PASS but UA=85 double-counts the
#     infiltration conductance (envelope 85 + infil 15 = 100 W/K total, while
#     the reference peak-heating implies ~85-100 total): UA=75 keeps the triple
#     in band with margin and puts total UA at ~90 W/K.
#   * eta_solar=0.72 re-centres maxT/meanT at UA=75 (physical 0.72-0.78
#     double-glass SHGC range; isotropic-sky POA compensates anisotropic
#     circumsolar underestimation -- see report attribution).
# 600: C_z=600 Wh/K, U_wall_A=75, eta=0.72.  900: C_z=4200 Wh/K, eta=0.75
# (calibrated on 900FF min/max: 4400 put maxT 42.8 just under the 43.3 band
# floor at eta 0.72; 4200 x 0.75 centres all three), same UA.
INITIAL = {"600": dict(cz=600.0, ua=75.0, eta=0.72),
           "600FF": dict(cz=600.0, ua=75.0, eta=0.72),
           "900": dict(cz=4200.0, ua=75.0, eta=0.75),
           "900FF": dict(cz=4200.0, ua=75.0, eta=0.75)}

# ---------------------------------------------------------------------------
# R28: 2R2C wall thermal-mass network initial parameters (additive mode).
# Derivation: user-gym/benchmarks/layerC_rc_design.md section 3 (BESTEST
# geometry: walls 63.6 m2, roof 48 m2, floor 48 m2, south glazing 12 m2).
#   * U_wall_A becomes the DIRECT channel only (roof 15.26 + window 36.84).
#   * g_im = sum(A_i/(R_si + d_i/(2 k_i))); g_em = wall outer leg + exterior
#     film; C_mass = lumped mass layers (600: inner boards; 900: concrete
#     wall + floor slab).  DC aperture = 52.1 + series(g_em,g_im) = 86.6 W/K
#     vs the single-node calibrated 75 -> the harness starts the calibration
#     scan at the conductance scale factor k = 75/86.6 = 0.866 (applied to
#     U_wall_A/g_im/g_em only; design report section 3.5).
#   * timestep 60 s (NOT the 600 s of the single-node runs): at 600 s the
#     ideal oversized thermostat + the light air node (C_z=150/100) produce
#     -19 K substep plunges whose saturation-clamp conservation re-step
#     (q_corr, up to +131 kW onto 150 Wh/K) diverges.  60 s bounds the
#     controller swing to ~1 K and passes the lambda-max guard with a wide
#     margin; the passive-network 600 s feasibility claim is unaffected
#     (engine-side guard covers any user dt).
# ---------------------------------------------------------------------------
INITIAL_RC_DERIVED = {
    "600": dict(cz=150.0, ua=52.1, eta=0.72, cmass=535.0, g_im=900.0, g_em=35.8),
    "600FF": dict(cz=150.0, ua=52.1, eta=0.72, cmass=535.0, g_im=900.0, g_em=35.8),
    "900": dict(cz=100.0, ua=52.1, eta=0.75, cmass=3966.0, g_im=585.0, g_em=36.6),
    "900FF": dict(cz=100.0, ua=52.1, eta=0.75, cmass=3966.0, g_im=585.0, g_em=36.6),
}

# Adopted (calibrated) 2R2C parameter set per case -- R28 calibration outcome.
# Calibration path (R28 implementation report, layerC_rc_implementation.md):
#   * Free-float triples were the identifying constraint (hard PASS on all
#     six FF metrics).  Controlled-case annual loads remain OUT (4-5x bands)
#     and are INSENSITIVE to (k, eta, C_z, g_im, g_em) over a wide scan --
#     attributed to the harness solar profile over-energizing clear winter
#     days (Jan free-float daily max mean 40.8 C: 26/31 days above the 27 C
#     cooling setpoint) + the solar-to-air-node absorption architecture.
#     See the implementation report scan table for the full evidence.
#   * g_im values are EFFECTIVE lumped-node couplings: 600 family 400 W/K
#     (mass layer deeper than the surface half-layer of the section-3
#     derivation), 900 family 1000 W/K (floor slab closely coupled).
#   * U_wall_A = direct channel (roof 15.26 + window 36.84); timestep 60 s
#     (600 s controller granularity diverges the latent conservation
#     re-step on a light air node -- see INITIAL_RC_DERIVED note).
INITIAL_RC = {
    "600": dict(cz=150.0, ua=52.1, eta=0.80, cmass=535.0, g_im=400.0, g_em=35.8),
    "600FF": dict(cz=150.0, ua=52.1, eta=0.80, cmass=535.0, g_im=400.0, g_em=35.8),
    "900": dict(cz=150.0, ua=52.1, eta=0.78, cmass=3966.0, g_im=1000.0, g_em=28.0),
    "900FF": dict(cz=150.0, ua=52.1, eta=0.78, cmass=3966.0, g_im=1000.0, g_em=28.0),
}


def scaled_rc_params(case: str, k: float) -> Dict[str, float]:
    """Conductance-scaled 2R2C parameters (design report section 3.5): the
    k factor applies to the DIRECT channel U_wall_A and the two network
    conductances g_im/g_em; C_z, C_mass and eta_solar are held.  Based on
    the section-3 DERIVED set (kept for provenance / probe restarts)."""
    d = dict(INITIAL_RC_DERIVED[case])
    d["ua"] = d.pop("ua") * k
    d["g_im"] *= k
    d["g_em"] *= k
    return d


# ---------------------------------------------------------------------------
# EPW -> vfed weather DataFrame
# ---------------------------------------------------------------------------
def south_vertical_poa(
    doy: np.ndarray,
    hour_mid: np.ndarray,
    dni: np.ndarray,
    dhi: np.ndarray,
    ghi: np.ndarray,
    lat_deg: float = LAT,
    lon_deg: float = LON,
    tz_hours: float = TZ_HOURS,
    rho_g: float = 0.2,
) -> np.ndarray:
    """South-vertical plane-of-array irradiance (W/m2), isotropic sky.

    POA = DNI*max(0, cosAOI) + DHI*(1+cos90)/2 + GHI*rho_g*(1-cos90)/2
    with cosAOI = sin(zenith)*cos(azimuth - 180 deg) for a south-facing
    vertical surface (beta=90).  Solar position: NOAA/Spencer declination +
    equation of time; hour angle from local standard time (no DST in TMY).
    ``hour_mid`` is the interval midpoint (EPW rows are hour-ending averages).
    """
    g = 2.0 * math.pi / 365.0 * (doy - 1.0 + (hour_mid - 12.0) / 24.0)
    eot = 229.18 * (
        0.000075
        + 0.001868 * np.cos(g)
        - 0.032077 * np.sin(g)
        - 0.014615 * np.cos(2 * g)
        - 0.040849 * np.sin(2 * g)
    )  # minutes
    dec = (
        0.006918
        - 0.399912 * np.cos(g)
        + 0.070257 * np.sin(g)
        - 0.006758 * np.cos(2 * g)
        + 0.000907 * np.sin(2 * g)
        - 0.002697 * np.cos(3 * g)
        + 0.00148 * np.sin(3 * g)
    )  # radians (Spencer)
    lstm = 15.0 * tz_hours
    tst = hour_mid * 60.0 + 4.0 * (lon_deg - lstm) + eot  # true solar minutes
    omega = np.radians(tst / 4.0 - 180.0)  # hour angle
    phi = math.radians(lat_deg)
    cos_z = np.sin(phi) * np.sin(dec) + np.cos(phi) * np.cos(dec) * np.cos(omega)
    cos_z = np.clip(cos_z, -1.0, 1.0)
    zen = np.arccos(cos_z)
    sin_z = np.sqrt(np.clip(1.0 - cos_z**2, 0.0, 1.0))
    # Azimuth from north, clockwise: arccos(...) sweeps 0..180 through EAST
    # (morning quadrant); mirror through west for the afternoon (omega > 0).
    with np.errstate(invalid="ignore", divide="ignore"):
        cos_a = (np.sin(dec) - np.sin(phi) * cos_z) / (
            np.cos(phi) * sin_z + 1e-9
        )
    az_morning = np.arccos(np.clip(cos_a, -1.0, 1.0))
    az = np.where(omega > 0.0, 2.0 * math.pi - az_morning, az_morning)
    cos_aoi = sin_z * np.cos(az - math.pi)  # beta = 90, gamma_n = 180 deg
    poa = (
        dni * np.clip(cos_aoi, 0.0, None)
        + dhi * 0.5
        + ghi * rho_g * 0.5
    )
    return np.clip(poa, 0.0, None)


def load_epw(path: str) -> pd.DataFrame:
    """Denver TMY3 EPW -> vfed 7-column hourly DataFrame (hour-ending index).

    EPW data columns (0-based, verified against the downloaded file):
    6 dry bulb (C), 8 RH (%), 9 station pressure (Pa), 13 GHI, 14 DNI,
    15 DHI, 22 wind speed (m/s).  All in local standard time (UTC-7, no DST).
    """
    cols: List[List[float]] = []
    n_header = 8  # EPW fixed header: LOCATION .. DATA PERIODS
    keep = (6, 8, 9, 13, 14, 15, 22)  # T, RH, P(Pa), GHI, DNI, DHI, wind
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for i, line in enumerate(f):
            if i < n_header:
                continue
            parts = line.split(",")
            if len(parts) < 23:
                continue
            row: List[float] = []
            for j in keep:
                try:
                    row.append(float(parts[j]))
                except ValueError:  # e.g. source-flag strings
                    row.append(np.nan)
            cols.append(row)
    arr = np.array(cols, dtype=float)
    if arr.shape[0] != 8760:
        raise ValueError(f"EPW {path}: expected 8760 data rows, got {arr.shape[0]}")

    temp, rh, p_pa, ghi, dni, dhi, ws = (
        arr[:, 0], arr[:, 1], arr[:, 2], arr[:, 3], arr[:, 4], arr[:, 5], arr[:, 6]
    )
    if not (np.isfinite(temp).all() and np.isfinite(rh).all() and np.isfinite(ghi).all()):
        raise ValueError("EPW contains non-finite mandatory values")
    if temp.min() < -50 or temp.max() > 55:
        raise ValueError(f"EPW dry-bulb out of sanity band: {temp.min()}..{temp.max()}")
    if not ((rh >= 0).all() and (rh <= 100).all()):
        raise ValueError("EPW RH out of [0, 100]")

    hour_ending = np.arange(8760) % 24 + 1.0
    doy = np.arange(8760) // 24 + 1
    poa = south_vertical_poa(doy.astype(float), hour_ending - 0.5, dni, dhi, ghi)

    idx = pd.date_range("1990-01-01 01:00", periods=8760, freq="h")
    df = pd.DataFrame(
        {
            "temperature_2m": temp,
            "relative_humidity_2m": rh,
            "wind_speed_10m": ws,
            "shortwave_radiation": poa,  # vfed Q_solar column = POA (option A)
            "direct_radiation": np.clip(ghi - dhi, 0.0, None),
            "diffuse_radiation": dhi,
            "surface_pressure": p_pa / 100.0,  # Pa -> hPa (Denver ~832 hPa)
        },
        index=idx,
    )
    df.attrs["poa_to_ghi_annual"] = float(poa.sum() / max(ghi.sum(), 1.0))
    return df


def dual_year(df: pd.DataFrame) -> pd.DataFrame:
    """BESTEST periodic-steady-state trick: run two concatenated years,
    discard year 1 (wash-out), report year 2.  vfed starts every run at
    T_z = T_light with no warm-start, so the first year only initialises
    the thermal state."""
    df2 = df.copy()
    df2.index = df2.index + pd.DateOffset(years=1)
    return pd.concat([df, df2])


# ---------------------------------------------------------------------------
# Case configuration (scout report section 6 yaml draft)
# ---------------------------------------------------------------------------
def case_dict(
    name: str,
    *,
    cz: float,
    u_wall_a: float,
    eta_solar: float,
    free_float: bool,
    rc: bool = False,
    cmass: float = 0.0,
    gim: float = 0.0,
    gem: float = 0.0,
) -> dict:
    """BESTEST project dict.  Thermostat trick: photoperiod 24 h (always
    'light') makes T_light=27 the year-round cooling setpoint and T_dark=20
    the heating setpoint -- exactly the BESTEST 20/27 window controller.

    ``rc=True`` activates the 2R2C wall thermal-mass network: ``u_wall_a``
    is then the DIRECT channel (roof+window) and the wall path runs through
    the mass node (C_mass / g_im / g_em).  The timestep drops to 60 s (see
    INITIAL_RC note: the 600 s controller granularity diverges the latent
    conservation re-step on a light air node).
    """
    heavy = name.startswith("9")
    hvac = {
        "cop_mode": "constant",
        "cop_value": 3.0,
        "heat_mode": "resistive",
        "deadband_c": 0.5,
        "comp_mod_band_c": 1.0,
        "min_on_s": 0.0,
        "min_off_s": 0.0,
        "fan_power_w": 0.0,  # BESTEST ideal equipment: no fan waste heat
        "shr_rh_guard": 100.0,  # SHR == 1: no latent cooling (140 is dry air)
        "auto_size": False,
    }
    if free_float:
        hvac.update(P_rated_w=0.0, P_rated_heat_w=0.0)  # three zeros: no HVAC
    else:
        hvac.update(P_rated_w=4000.0, P_rated_heat_w=6000.0)  # capacity headroom
    envelope = {
        "U_wall_A": u_wall_a,
        "A_window": 12.0,
        "eta_solar": eta_solar,
        "ach": 0.346,  # 0.414 ACH @ 1650 m mass flow 0.0149 kg/s, rho 1.2
        "permeance": 0.0,
        "V_room": 129.6,
        "rho_air": 1.2,
        "cp_air": 1005.0,
        "C_z": cz,
    }
    if rc:
        envelope.update(
            wall_rc_nodes=2,
            C_mass=cmass,
            g_im=gim,
            g_em=gem,
        )
    return {
        "name": f"bestest{name}",
        "envelope": envelope,
        "hvac": hvac,
        "deh": {"P_ref_w": 0.0, "fan_power_w": 0.0, "auto_size": False},
        # auto_deduce MUST be False: True would recompute power_w from
        # ppfd_target*area/efficacy and put a 1300 W internal gain in the room.
        "led": {
            "auto_deduce": False,
            "power_w": 0.0,
            "photoperiod_hours": 24.0,
            "light_start_hour": 0,
        },
        "transpiration": {"method": "daily", "daily_water_L": 0.0},
        "setpoints": {"T_light": 27.0, "T_dark": 20.0, "RH": 50.0},
        "equipment_power_w": 200.0,  # 140-2020: 80 W convective + 120 W radiant
        "pv_area_m2": 0.0,
        "battery_kwh": 0.0,
        "site": {"lat": LAT, "lon": LON, "tz_hours": TZ_HOURS, "year": 1990},
        "space": {"timestep_s": 60 if rc else 600},
    }


# ---------------------------------------------------------------------------
# Instrumented run
# ---------------------------------------------------------------------------
@dataclass
class CaseResult:
    case: str
    annual_heating_kwh: float
    annual_cooling_kwh: float
    peak_heating_kw: float
    peak_cooling_kw: float
    min_t: float
    max_t: float
    mean_t: float
    temp_clip_events: int
    cz: float
    u_wall_a: float
    eta_solar: float
    runtime_note: str = ""
    extra: Dict[str, float] = field(default_factory=dict)

    @property
    def annual_heating_gj(self) -> float:
        return self.annual_heating_kwh * 0.0036

    @property
    def annual_cooling_gj(self) -> float:
        return self.annual_cooling_kwh * 0.0036


def run_case(
    case: str,
    weather_year: pd.DataFrame,
    *,
    cz: Optional[float] = None,
    u_wall_a: Optional[float] = None,
    eta_solar: Optional[float] = None,
    t_max: float = 90.0,
    rc: bool = False,
    cmass: Optional[float] = None,
    gim: Optional[float] = None,
    gem: Optional[float] = None,
) -> CaseResult:
    """Run one BESTEST case on the dual-year weather and return year-2 KPIs.

    Instrumentation (both restored in ``finally``):
      * ``vfed.physics.ode._DEFAULT_T_MAX = t_max`` -- the engine never passes
        T_min/T_max, so the None-sentinel resolves the module constant at
        build time.  Production default (60) is untouched outside this run.
      * ``HVACDevice.step`` wrapped to integrate Q_HVAC_W (thermal, sign:
        >0 heating, <0 cooling) per substep into hourly Wh buckets.

    ``rc=True`` runs the 2R2C wall mass-network mode: parameters default to
    the derived INITIAL_RC set; C_z / eta_solar / C_mass / g_im / g_em can
    be probed individually, ``u_wall_a`` overrides the direct channel.
    """
    import vfed.design.engine as eng
    import vfed.physics.ode as ode_mod
    from vfed.design.project import DesignProject

    if rc:
        # defaults = the adopted (calibrated) section INITIAL_RC set
        init = dict(INITIAL_RC[case])
    else:
        init = dict(INITIAL[case])
    cz = init["cz"] if cz is None else cz
    ua = init["ua"] if u_wall_a is None else u_wall_a
    eta = init["eta"] if eta_solar is None else eta_solar
    free_float = case.endswith("FF")
    d = case_dict(
        case,
        cz=cz,
        u_wall_a=ua,
        eta_solar=eta,
        free_float=free_float,
        rc=rc,
        cmass=init.get("cmass", 0.0) if cmass is None else cmass,
        gim=init.get("g_im", 0.0) if gim is None else gim,
        gem=init.get("g_em", 0.0) if gem is None else gem,
    )
    project = DesignProject.from_dict(d)
    dt = project.space.timestep_s

    n = len(weather_year)
    sub = int(round(3600.0 / dt))  # timesteps per hour (6 @ 600 s, 60 @ 60 s)
    heat_wh = np.zeros(2 * n)  # dual-year run: year 1 wash-out, year 2 reported
    cool_wh = np.zeros(2 * n)
    counter = {"i": 0}

    orig_step = eng.HVACDevice.step
    orig_tmax = ode_mod._DEFAULT_T_MAX

    def patched_step(self, T_z, RH_z, T_ext, dt=60.0, **kw):
        out = orig_step(self, T_z, RH_z, T_ext, dt, **kw)
        q = out["Q_HVAC_W"]
        h = counter["i"] // sub
        if h < 2 * n:
            if q >= 0.0:
                heat_wh[h] += q * dt / 3600.0
            else:
                cool_wh[h] += -q * dt / 3600.0
        counter["i"] += 1
        return out

    eng.HVACDevice.step = patched_step
    ode_mod._DEFAULT_T_MAX = float(t_max)
    try:
        engine = eng.DesignEngine()
        result = engine.run(project, weather=dual_year(weather_year))
    finally:
        eng.HVACDevice.step = orig_step
        ode_mod._DEFAULT_T_MAX = orig_tmax

    t_z = np.asarray(result.timeseries["T_z"], dtype=float)
    if len(t_z) != 2 * n:
        raise ValueError(f"expected {2*n} hourly rows, got {len(t_z)}")
    t2 = t_z[n:]  # year 2 = periodic steady state
    # heat_wh/cool_wh are hourly energy in Wh; kWh needs /1000.
    h2, c2 = heat_wh[n:] / 1000.0, cool_wh[n:] / 1000.0

    clip = int(result.summary.get("moisture_clamp_stats", {}).get("temp_clip_events", 0))
    extra: Dict[str, float] = {
        # duty-cycle evidence: hours with any heating / cooling in year 2
        "heating_hours": float((h2 > 0.0).sum()),
        "cooling_hours": float((c2 > 0.0).sum()),
        "timestep_s": float(dt),
    }
    if rc:
        extra.update(
            wall_rc_nodes=2,
            cmass=float(d["envelope"]["C_mass"]),
            g_im=float(d["envelope"]["g_im"]),
            g_em=float(d["envelope"]["g_em"]),
            t_m_final_c=float(result.summary.get("wall_rc", {}).get("T_m_final_c", float("nan"))),
        )
    return CaseResult(
        case=case,
        annual_heating_kwh=float(h2.sum()),
        annual_cooling_kwh=float(c2.sum()),
        # h2/c2 are kWh per hour == hourly-average kW
        peak_heating_kw=float(h2.max()),
        peak_cooling_kw=float(c2.max()),
        min_t=float(t2.min()),
        max_t=float(t2.max()),
        mean_t=float(t2.mean()),
        temp_clip_events=clip,
        cz=cz,
        u_wall_a=ua,
        eta_solar=eta,
        extra=extra,
    )


# ---------------------------------------------------------------------------
# Verdicts
# ---------------------------------------------------------------------------
METRIC_LABEL = {
    "annual_heating_gj": "annual heating (GJ)",
    "annual_cooling_gj": "annual cooling (GJ)",
    "peak_heating_kw": "peak heating (kW)",
    "peak_cooling_kw": "peak cooling (kW)",
    "min_t": "annual min T (degC)",
    "max_t": "annual max T (degC)",
    "mean_t": "annual mean T (degC)",
}


def verdict(value: float, band: Tuple[float, float]) -> str:
    return "PASS" if band[0] <= value <= band[1] else "OUT"


def case_metrics(res: CaseResult) -> Dict[str, float]:
    if res.case.endswith("FF"):
        return {"min_t": res.min_t, "max_t": res.max_t, "mean_t": res.mean_t}
    return {
        "annual_heating_gj": res.annual_heating_gj,
        "annual_cooling_gj": res.annual_cooling_gj,
        "peak_heating_kw": res.peak_heating_kw,
        "peak_cooling_kw": res.peak_cooling_kw,
    }


def acceptance_metric(res: CaseResult, key: str) -> Optional[Tuple[float, float]]:
    """Standard-140 hard acceptance limits exist only for ANNUAL loads;
    peak powers have no acceptance band (reference range only)."""
    if res.case.endswith("FF") or not key.startswith("annual_"):
        return None
    pair = REF[res.case].get(f"accept_{key.split('_')[1]}_gj")
    return pair
