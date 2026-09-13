"""
Design project configuration.

A ``DesignProject`` is a fully declarative description of a vertical-farm design:
site, envelope, HVAC, dehumidifier, LED, transpiration law, control setpoints
and the PV-Battery-Grid (PVBES) system plus the design search space. It is
serialised to/from YAML for easy creation and versioning.

Strategy Modes (NOT implemented)
--------------------------------
The control-strategy presets (``default`` / ``conservative`` / ``progressive``
/ ``aggressive``) are a planned feature only.  They are **not implemented and
not configurable**: there is no ``strategy:`` config field, ``ScenarioConfig``
does not exist, and any ``strategy`` top-level YAML key is rejected by
``from_dict`` as an unrecognised key.  Do not add or reference a ``strategy:``
field (P5-14).
"""

from dataclasses import dataclass, field, asdict
from typing import List, Optional

import yaml

__all__ = [
    "CapitalCostConfig",
    "CAPITAL_MODES_BY_COMPONENT",
    "validate_capital_config",
    "OpexConfig",
    "SiteConfig",
    "EnvelopeConfig",
    "HVACConfig",
    "DEHConfig",
    "LEDConfig",
    "VanHentenConfig",
    "TranspirationConfig",
    "SetpointConfig",
    "PVConfig",
    "BatteryConfig",
    "TariffConfig",
    "DesignSpace",
    "DesignProject",
    "HARDWARE_ALIASES",
]


# ── S1: hardware spec-sheet vocabulary (datasheet → canonical) ────────
# VFED's canonical HVAC/DEH keys mix units: P_rated_w (W), Q_cool_nom (kW),
# M_deh_nom (L/day), P_ref_w (W), P_rated_max.  A prosumer knows their
# equipment by the numbers on the datasheet (cooling capacity in kW, COP,
# dehumidification capacity in L/day, rated input in W), so ``from_dict``
# accepts these friendly aliases and normalises them onto the canonical key.
# Back-compat is preserved: canonical keys still work unchanged, and a config
# that sets BOTH spellings to different values is rejected as ambiguous.
HARDWARE_ALIASES = {
    "hvac": {
        # datasheet name          canonical VFED key   unit
        "cooling_capacity_kw": "Q_cool_nom",  # nominal cooling capacity, kW
        "cop": "cop_value",  # COP at rated condition
        "power_w": "P_rated_w",  # rated electrical input, W
    },
    "deh": {
        # datasheet name          canonical VFED key   unit
        "capacity_l_per_day": "M_deh_nom",  # dehumidification capacity, L/day
        "power_w": "P_ref_w",  # reference electrical input, W
    },
}


@dataclass
class CapitalCostConfig:
    """Per-component capital cost and depreciation.

    ``mode`` selects how the cost is computed; the pricing basis is part of
    the mode name (P0-1 unit fix: the legacy ``per_watt`` silently multiplied
    kWp for PV and kWh for battery, 1000x / unit-class off its name):
        * ``"direct"``   -- use ``cost`` as-is (absolute, project currency).
        * ``"per_watt"`` -- ``rate_per_watt`` x rated W    (LED / HVAC / DEH).
        * ``"per_kwp"``  -- ``rate_per_kwp``  x rated kWp  (PV only).
        * ``"per_kwh"``  -- ``rate_per_kwh``  x rated kWh  (battery only).
    Valid modes are component-specific (``CAPITAL_MODES_BY_COMPONENT``) and
    enforced at load time and at pricing time; ``per_watt`` on pv/battery is
    rejected with a migration message instead of being silently re-interpreted.
    ``depreciation_years`` controls the CRF term in LCOE.
    """

    mode: str = "direct"
    cost: float = 0.0
    rate_per_watt: float = 1.0  # currency per rated W (LED/HVAC/DEH)
    rate_per_kwp: Optional[float] = None  # currency per rated kWp (PV only)
    rate_per_kwh: Optional[float] = None  # currency per rated kWh (battery only)
    depreciation_years: float = 15.0


# P0-1: pricing basis is part of the mode name.  per_watt multiplies rated W
# (LED/HVAC/DEH); per_kwp multiplies rated kWp (PV only); per_kwh multiplies
# rated kWh (battery only).  A mode that does not match the component's
# pricing basis is rejected (fail-fast) rather than silently mis-multiplied.
CAPITAL_MODES_BY_COMPONENT = {
    "led": {"direct", "per_watt"},
    "hvac": {"direct", "per_watt"},
    "deh": {"direct", "per_watt"},
    "pv": {"direct", "per_kwp"},
    "battery": {"direct", "per_kwh"},
    "equipment": {"direct", "per_watt"},
    "envelope": {"direct", "per_watt"},
    "pump": {"direct", "per_watt"},
}


def validate_capital_config(cfg: CapitalCostConfig, component: str, yaml_path: str = None) -> None:
    """P0-1: capital mode must match the component's pricing basis.

    Raises ``ValueError`` with migration instructions for the legacy
    pv/battery ``per_watt`` spelling (which the pre-P0-1 code silently
    multiplied by kWp / kWh).  Called from ``DesignProject.from_dict`` at
    load time and from ``sweep._resolve_capital`` at pricing time
    (defense in depth for programmatic constructions).
    """
    where = f"{yaml_path}.capital" if yaml_path else f"{component}.capital"
    allowed = CAPITAL_MODES_BY_COMPONENT.get(component)
    if allowed is None:
        raise ValueError(
            f"Unknown capital component '{component}'. "
            f"Known: {sorted(CAPITAL_MODES_BY_COMPONENT)}"
        )
    if cfg.mode not in allowed:
        if component == "pv" and cfg.mode == "per_watt":
            raise ValueError(
                f"{where}: mode 'per_watt' is not valid for PV (P0-1). The "
                f"pre-P0-1 code silently multiplied this rate by kWp -- 1000x "
                f"off the field name (a 46.5 kWp array at 3.5/kWp priced as "
                f"162 instead of 162,000). PV is priced per kWp: use "
                f"mode: per_kwp with rate_per_kwp in currency/kWp "
                f"(3.5 currency/W equals rate_per_kwp: 3500)."
            )
        if component == "battery" and cfg.mode == "per_watt":
            raise ValueError(
                f"{where}: mode 'per_watt' is not valid for battery (P0-1). "
                f"Storage is priced per kWh, not per watt (the pre-P0-1 code "
                f"silently multiplied this rate by kWh). Use mode: per_kwh "
                f"with rate_per_kwh in currency/kWh -- the same number as "
                f"before (rate_per_watt: 500 becomes rate_per_kwh: 500)."
            )
        raise ValueError(
            f"{where}: mode '{cfg.mode}' is not valid for '{component}'. "
            f"Allowed: {sorted(allowed)}. Pricing bases: per_watt = rated W "
            f"(LED/HVAC/DEH), per_kwp = rated kWp (PV), per_kwh = rated kWh "
            f"(battery)."
        )
    if cfg.mode == "per_kwp" and cfg.rate_per_kwp is None:
        raise ValueError(
            f"{where}: mode 'per_kwp' requires rate_per_kwp " f"(currency/kWp) to be set."
        )
    if cfg.mode == "per_kwh" and cfg.rate_per_kwh is None:
        raise ValueError(
            f"{where}: mode 'per_kwh' requires rate_per_kwh " f"(currency/kWh) to be set."
        )


@dataclass
class OpexConfig:
    """Annual operating expenditure for the farm.

    All costs are in the project's currency unit (see ``DesignProject.currency``
    and ``exchange_rate`` for conversion).  Currency-magnitude consistency:
    labor / water / misc OPEX, tariff prices and capital costs must all be
    written in the SAME currency that ``currency`` claims.  The defaults
    below are USD-scale preset figures -- an RMB project that omits this
    section silently inherits USD magnitudes under an RMB label.

    P1-7 transparency: if the YAML omits the whole ``opex`` section, these
    defaults apply SILENTLY (labor 30000 + misc 5000 per year, about 72-96%
    of LCOE's numerator on the bundled presets).  ``DesignProject`` then
    sets ``opex_was_defaulted`` and the engine reports
    ``annual_om_pct_of_cost`` plus a WARNING when OPEX dominates.

    * ``water_cost_per_m3``: water price (irrigation + makeup).
      Default 2.0 currency/m3.
    * ``labor_cost_per_year``: total annual labor cost.
      Default 30000.0 currency/yr -- USD-scale preset; NOT rescaled to your
      currency or farm size.
    * ``maintenance_pct``: annual maintenance as fraction of total CAPEX.
      Default 0.02 (2%/yr).
    * ``misc_opex_per_year``: other operating costs (seeds, nutrients, etc.).
      Default 5000.0 currency/yr -- USD-scale preset.
    """

    water_cost_per_m3: float = 2.0  # currency/m3 irrigation + makeup water
    labor_cost_per_year: float = 30000.0
    #   currency/yr; USD-scale default -- applies silently if the opex
    #   section is omitted (P1-7); verify against YOUR currency.
    maintenance_pct: float = 0.02  # fraction of total CAPEX per year
    misc_opex_per_year: float = 5000.0
    #   currency/yr (seeds, nutrients, ...); USD-scale default -- applies
    #   silently if the opex section is omitted (P1-7).


@dataclass
class SiteConfig:
    """场地位置与时间基准。全部字段可选——缺省时回退到上海/中国标准时间默认值:

        lat/lon   = (31.2, 121.5)   上海
        tz_hours  = 8.0             UTC+8 (中国标准时间)
        year      = 2025            天气与 PV 衰减计算年份
        tilt      = 20.0°           PV 阵列倾角
        azimuth   = 180.0°          正南方位角
        city      = None            预下载的 Open-Meteo 城市名 (替代 lat/lon)

    P8-15: 默认值在此文档化; 用 ``vfed design new --city <name>`` 可写入
    正确的 lat/lon/tz_hours 三元组。
    """

    lat: float = 31.2
    lon: float = 121.5
    tz_hours: float = 8.0  # UTC+8 (中国标准时间)
    tilt: float = 20.0  # PV 阵列倾角 (°)
    azimuth: float = 180.0  # PV 方位角 (°, 180=正南)
    year: int = 2025  # 天气数据年份
    city: Optional[str] = None  # optional: pre-downloaded city name


@dataclass
class EnvelopeConfig:
    U_wall_A: float = 50.0  # W/K envelope conductance (UA = Σ U_i×A_i over walls/roof/floor)
    #   Estimating UA: pick U per construction (handbook values, W/m²K) and
    #   multiply by its area: 50-100 mm PU/PIR sandwich panel 0.2-0.45,
    #   insulated brick 0.5-1.0, plain brick/concrete 1.5-2.5, single glazing
    #   ~5-6. E.g. a 60 m² envelope in 100 mm PU panel ≈ 15-25 W/K; 50 W/K
    #   ≈ lightly insulated or a larger shell.
    A_window: float = 0.0  # m^2 glazing
    eta_solar: float = 0.15  # solar heat gain coeff
    #   Fraction of incident GHI admitted as heat (SHGC, typical 0.1-0.6);
    #   Q_solar = eta_solar × A_window × GHI.
    ach: float = 0.001  # air changes / hour (infiltration)
    #   Sealed plant factories (positive-pressure, airtight) exchange
    #   N≈0.01-0.02 h⁻¹ (Kozai 2013; WUR WPR-1315); 0.1 is a conservative
    #   leakage upper bound.  The old 0.5 (commercial-building infiltration
    #   level, ASHRAE) was 25-50x too high and dried out the room in winter.
    permeance: float = 0.0  # kg/(s per kg/kg) envelope vapour permeance
    V_room: float = 200.0  # m^3
    rho_air: float = 1.2  # kg/m^3
    cp_air: float = 1005.0  # J/(kg.K)
    C_z: float = 80000.0  # Wh/K equivalent heat capacity (room thermal inertia, ode.py: dT/dt = Q/(C_z·3600))
    #   Estimating: air alone = V_room×rho_air×cp_air/3600 ≈ 67 Wh/K for the
    #   200 m³ default — usually negligible vs the internal mass. Add
    #   Σ(m_i × c_i)/3600 (kg × J/(kg·K) → Wh/K): shelves/racks, concrete slab
    #   and canopy/nutrient water dominate (water ≈ 1.16 kWh/K per m³).
    #   Practical band for a 100-500 m³ PFAL room: 30-200 kWh/K
    #   (P4-5 calibration used 200,000; default 80,000 Wh/K = moderate mass).
    #   注意: 归档数字孪生 499,597 已被判定超物理 (≈430 m³ 水当量), 勿沿用。


@dataclass
class HVACConfig:
    # ── primary sizing (new, industry-standard) ──
    Q_cool_nom: float = 0.0  # nominal cooling capacity (kW); 0 → use P_rated_w or auto_size
    #   Datasheet cooling capacity: P_rated_w = Q_cool_nom×1000/COP(design_T_ext).
    #   Typical 2-10 kW for a grow room.
    P_rated_max: float = 0.0  # max electrical input (kW); 0 → derived from Q_cool_nom/COP_design
    #   Optional cap: derived P_rated_w = min(P_rated_w, P_rated_max×1000). Typical 0.5-5 kW.
    # ── legacy (kept for backward compat) ──
    P_rated_w: float = 3000.0  # rated electrical power (W), used if Q_cool_nom == 0
    #   Rated ELECTRICAL input; cooling capacity = P_rated_w × COP(T_ext). Typical 0.5-10 kW.
    cop_value: float = 4.0  # COP at rated condition (feeds constant/linear/table modes); air-cooled DX 3-6
    cop_mode: str = "carnot"  # carnot | constant | linear | table
    cop_k: float = 0.02  # linear-mode slope (1/K): COP = cop_value×(1−k×(T_ext−cop_T_ref)), clamp [1,10]; typical 0.01-0.04
    cop_T_ref: float = 25.0  # linear-mode reference outdoor temperature (°C)
    cop_table: dict = field(default_factory=dict)  # key = T_ext(°C), value = COP
    #   table mode: piecewise-linear between sorted edges (flat outside), COP floor 0.5;
    #   e.g. {20: 3.0, 35: 2.5}
    cop_heat: float = 3.0  # heating COP at EN 14511 A7/W35 (7°C ext / 20°C int); Carnot-scaled vs T_ext, clamp [1.5, 5]
    heat_mode: str = "heat_pump"  # heat_pump (COP-scaled) | resistive (COP = 1, power ∝ modulation m)
    P_rated_heat_w: float = 3000.0  # rated electrical input in heating mode (W); 0 → falls back to P_rated_w
    deadband_c: float = 1.0  # °C thermostat hysteresis deadband
    #   ON when T_z > T_setpoint, OFF when T_z < T_setpoint − deadband. Typical 0.5-2 °C.
    min_on_s: float = 180.0  # anti-short-cycle min compressor run time (s); typical 120-300
    min_off_s: float = 180.0  # anti-short-cycle min compressor stop time (s); typical 120-300
    fan_power_w: float = 70.0  # indoor fan power (W): counted while compressor runs, fan heat stays in room; typical 40-150
    shr_BF: float = 0.15
    #   Coil bypass factor [0, 1) — BF-ADP SHR model (physics/shr.py):
    #   W_out = BF·W_in + (1−BF)·W_sat(T_adp); higher = less coil contact =
    #   less latent removed by the coil. 0.10-0.20 for a 4-row DX coil.
    t_coil_drop: float = 9.0  # supply-air temperature depression T_supply = T_setpoint - t_coil_drop (real ACs ~8-12°C)
    tau_q: float = 90.0  # first-order lag of heat output (s, coil thermal inertia); typical 30-120
    tau_m: float = 60.0  # first-order lag of moisture removal (s, condensate retention); typical 30-120
    shr_rh_guard: float = 65.0  # % RH; below this the AC stops latent removal (P4-1a)
    #   Humidity-protection guard: SHR → 1.0 (sensible-only) at/below the guard,
    #   blended linearly up to guard + rh_guard_band. Keep near/below setpoints.RH.
    rh_guard_band: float = 3.0  # % RH blend width for the humidity guard
    coil_condense_max_gps: float = (
        0.0  # explicit coil condensate cap (g/s); 0 → auto ~5e-4·P_rated_w (P4-1b)
    )
    #   Airflow-limited condensate bound: auto ≈ 1.5 g/s per 3 kW rated (real DX 1-2 g/s).
    comp_mod_band_c: float = 2.0  # VFD proportional band (°C): m=demand/band, m=1 at ±band
    speed_curve: str = "default"  # compressor part-load curve: default | flat
    #   VFD part-load: COP rises as speed falls (50%→1.33x, 30%→1.54x);
    #   coefficients from Effsys2/KTH Madani + Szreder&Miara 2020 + Fahlén 2012.
    #   "flat" = Maxa i-290 conservative (COP≈const).
    eta_II: float = 0.35  # carnot-mode 2nd-law efficiency (−); typical 0.2-0.5
    delta_T_evap: float = 8.0  # evaporator approach (K): T_evap = T_indoor − ΔT_evap; typical 5-10
    delta_T_cond: float = 15.0  # condenser approach (K): T_cond = T_ext + ΔT_cond; typical 10-20
    auto_size: bool = False  # true = size P_rated_w from the design-day load via size_hvac
    design_T_ext: float = 35.0  # sizing design outdoor temperature (°C); also seeds DEH auto-size (@80% RH outdoor)
    shr_design: float = 0.80  # design SHR for sizing: total capacity = sensible load / shr_design; PFAL 0.6-0.8
    safety_factor: float = 1.2  # sizing margin multiplier on the computed P_rated; typical 1.1-1.3
    capital: CapitalCostConfig = field(default_factory=CapitalCostConfig)


@dataclass
class DEHConfig:
    # ── primary sizing (new, industry-standard) ──
    M_deh_nom: float = 0.0  # nominal dehumidification (L/day); 0 → use P_ref_w or auto_size
    #   Datasheet capacity: P_ref_w = M_deh_nom×41.67/smer. Typical 10-60 L/day.
    P_rated_max: float = 0.0  # max electrical input (kW); 0 → derived from M_deh_nom/SMER
    #   Optional cap: derived P_ref_w = min(P_ref_w, P_rated_max×1000). Typical 0.2-3 kW.
    # ── legacy (kept for backward compat) ──
    P_ref_w: float = 2233.0  # compressor reference electrical power (W); fan metered separately; typical 0.2-3 kW
    poly_e: tuple = (1.0, 0.02, 0.0, 0.05, 0.0, 0.0)
    #   Power-surface poly (e0..e5): P_comp = P_ref×(e0 + e1·tn + e2·tn² + e3·wn
    #   + e4·wn² + e5·tn·wn), tn = (T_z−T_mean)/T_std, wn = (W_z−W_mean)/W_std,
    #   clamped ≥ 0. Defaults: mildly rising with T and W.
    T_mean: float = 22.0  # °C mean room temp (DEH power poly centre)
    T_std: float = 5.0  # °C std dev (T normalisation scale)
    W_mean: float = 0.012  # kg/kg mean humidity ratio (W normalisation)
    W_std: float = 0.003  # kg/kg std dev
    smer: float = 2.0  # rated SMER (kg water / kWh COMPRESSOR input, fan excluded — P2-5); realistic 1.5-3.0
    control: str = "vfd"
    #   DEH control mode (P1-1): "vfd" = variable-speed modulation inside
    #   comp_mod_band_rh (DOE 87 FR 35286 part-load SMER penalty applies);
    #   "on_off" = bang-bang cycling on the deadband at FULL speed — rated
    #   SMER while running, zero power while off (min_on/min_off kept).
    #   Part-load SMER loss can halve the effective kg/kWh of a VFD machine
    #   (e.g. 1.28 vs rated 2.0) and cost ~56% more DEH electricity than
    #   cycling at full speed — the engine reports effective SMER either way.
    deadband_rh: float = (
        2.0  # % RH hysteresis stop point (was 3.0; narrowed to avoid the pband×deadband idle band)
    )
    comp_mod_band_rh: float = 6.0  # VFD proportional band (% RH): m=(RH_z−sp)/band
    #   VFD dehumidifier: SMER FALLS as speed falls (DOE 87 FR 35286 — opposite
    #   of AC; dew-point approach gets worse at low speed).  SMER(m) curve in
    #   dehumidifier.py; constant-SMER assumption valid only for m≥0.75.
    min_on_s: float = 180.0  # anti-short-cycle min compressor run time (s); typical 120-300
    min_off_s: float = 180.0  # anti-short-cycle min compressor stop time (s); typical 120-300
    fan_power_w: float = 40.0  # fan power (W); metered OUTSIDE smer (P2-5), fan heat stays in room; ≈2% of full load
    tau_q: float = 90.0  # first-order lag of sensible heat output (s, coil thermal inertia); typical 30-120
    tau_m: float = 120.0  # first-order lag of moisture removal (s, retained-condensate inertia); typical 60-180
    auto_size: bool = False  # true = size P_ref_w from the peak design moisture load (transp + infil + permeance)
    safety_factor: float = 1.2  # sizing margin multiplier on the computed P_ref_w; typical 1.1-1.3
    capital: CapitalCostConfig = field(default_factory=CapitalCostConfig)


@dataclass
class LEDConfig:
    power_w: float = 1300.0  # W electrical; EFFECTIVE only when auto_deduce=False (P5-6)
    light_start_hour: int = 6  # hour (0–23) when photoperiod begins
    photoperiod_hours: float = 16.0  # duration of light period (e.g., 12–20)
    heat_fraction: float = 1.0
    # auto-deduce from efficacy when auto_deduce=True (ponytail: avoids manual calc)
    # True → power_w recomputed = ppfd_target*covered_area/efficacy (power_w ignored, P5-6);
    # False → power_w effective (par_wm2 tracks it, P4-11)
    auto_deduce: bool = True
    efficacy: float = 2.5  # µmol/J  (LED photon efficacy)
    ppfd_target: float = 400.0  # µmol/(m²·s)
    covered_area: float = 45.0  # m²
    spectrum: str = "white"  # white | rb_3to1 | rb_4to1 | rb_2to1
    capital: CapitalCostConfig = field(default_factory=CapitalCostConfig)


@dataclass
class VanHentenConfig:
    """Van Henten 2003 one-state carbon-balance plant growth model.

    Reference: Van Henten, E.J. (2003). Sensitivity analysis of an optimal
    control problem in greenhouse climate management. Biosystems Engineering,
    85(3), 355-364.

    All parameters are in SI units.  Semantics reverse-engineered from
    vfed/plants/van_henten.py: gross photosynthesis
    ``phi = f(light) x f(T) x (X_c - Gamma)`` with
    ``f(T) = -c_co2_1*T^2 + c_co2_2*T - c_co2_3`` (must stay > 0, i.e.
    T below ~42 C), net growth ``dX_d = c_alpha_beta*phi - c_resp_d*X_d*Q10(T)``
    and canopy light interception ``1 - exp(-c_pl_d*X_d)``.
    """

    c_alpha_beta: float = 0.544  # (-) assimilate -> dry-matter conversion
    #   efficiency (0-1; literature 0.49-0.6).  Fraction of gross
    #   photosynthesis that ends up as structural dry matter.
    c_resp_d: float = 2.65e-7  # 1/s dark-respiration coefficient at 25 C
    #   (typical 1e-7 - 5e-7).  Applied with a Q10 = 2 van't Hoff response:
    #   rate doubles every +10 C; only active term that can shrink X_d.
    dry_matter_fraction: float = 0.05  # (-) dry -> fresh weight conversion
    #   (leafy vegetables 4-6 % dry matter).  Used only for KPI reporting
    #   (kg fresh = kg dry / fraction); does not feed back into growth.
    c_pl_d: float = 53.0  # m2/kg canopy light extinction per unit dry weight
    #   (typical 40-70).  Enters interception exp(-c_pl_d*X_d): converts
    #   standing dry weight X_d (kg/m2) into effective leaf area.
    c_rad_phot: float = 3.5e-9  # kg/J radiation use efficiency (PAR), lettuce-calibrated
    #   CALIBRATION BASIS (P0-3R, 2026-09-08): recalibrated for PFAL lettuce
    #   to the commercial PFAL yield band 30-60 kg fresh/m2/yr (Kozai et al.
    #   2016): 3.5e-9 anchors the band midpoint (~45 kg/m2/yr at the 609
    #   operating point; engine-verified ~45 kg/m2/yr).  The former 1e-8 kg/J
    #   literature default implied a quantum yield at the C3 theoretical
    #   maximum (no canopy / respiration / whole-cycle discount) and
    #   overpredicted yield 2-4x.  Full derivation and cross-checks:
    #   vfed/plants/van_henten.py; new baseline: user-gym/regression/README.md.
    c_co2_1: float = 5.11e-6  # m/(s*C^2) quadratic temperature-response term
    #   of gross photosynthesis (Van Henten 2003 Table 1; keep defaults).
    c_co2_2: float = 2.3e-4  # m/(s*C) linear temperature-response term
    c_co2_3: float = 6.29e-4  # m/s temperature-response offset; the parabola
    #   -c_co2_1*T^2 + c_co2_2*T - c_co2_3 turns negative above ~42 C and
    #   photosynthesis is clamped to 0 there (van_henten.py guard).
    c_Gamma: float = 5.2e-5  # kg/m3 CO2 compensation point (C3 plants, ~30 ppm
    #   at 25 C; rises with temperature).  Photosynthesis scales with the
    #   CO2 density above this floor: (X_c - c_Gamma).
    initial_dry_weight: float = 0.02  # kg/m2 initial (transplant) dry biomass
    #   real transplant seedlings ~15-80 g/m2,
    #   former 1 g/m2 was an order low (P3-14).  X_d resets to this at every
    #   harvest (sawtooth state).


@dataclass
class TranspirationConfig:
    """Crop water-loss (transpiration) configuration — the room's internal
    moisture source.  Five methods in two families; see the ``method`` enum
    below and vfed/plants/transpiration.py for the model.

    Reference water scenario for the direct-set defaults (P1-6): mature
    PFAL lettuce transpires ~1.5 L/m2/day at a dense 25 plants/m2 planting
    (literature band 0.75-2.0 L/m2/day; typical PFAL design figures at the
    Kozai-et-al-2016 Plant-Factory-handbook level).  On the default 45 m2
    canopy this is 1.5 x 45 = 67.5 L/day whole-canopy, or 1500 mL/m2/day
    / 25 plants/m2 = 60 mL/plant/day.
    """

    method: str = "van_henten"
    #   Transpiration method — 5 valid values in 2 families:
    #
    #   Model-coupled (physics-driven, default):
    #     "van_henten" — E = k_van_henten x X_d x VPD x area x light_factor;
    #       biomass X_d comes from the growth model, so water use tracks the
    #       canopy and peaks at harvest.  Consumes: k_van_henten,
    #       stage_factor, dark_transpiration_frac (+ runtime X_d).  All
    #       fields have physical defaults — no missing-field fail-fast.
    #   Direct-set (user states the water use; independent of T/RH):
    #     "daily" — whole-canopy daily total spread over the photoperiod.
    #       Consumes: daily_water_L (default > 0, always usable).
    #     "per_plant" — plant_count x ml_per_plant_day -> daily total.
    #       Consumes: plant_count, ml_per_plant_day (plants_per_m2 may
    #       auto-derive plant_count, see below).  plant_count <= 0 with no
    #       usable plants_per_m2 -> fail-fast at load (E prefix, exit 1)
    #       and again at step time for direct TranspirationModel use.
    #     "daily_per_period" — as "daily" but staged over period_days.
    #       Consumes: period_days + daily_water_L_period (one entry per
    #       stage; shape / positivity / sum == crop_cycle_days validated
    #       at load -> fail-fast).
    #     "per_plant_per_period" — as "per_plant" but staged over
    #       period_days.  Consumes: period_days + ml_per_plant_day_period
    #       + plant_count (or plants_per_m2).  Missing/invalid entries ->
    #       fail-fast at load.
    #   Legacy "constant" / "vpd" / "stomatal" were REMOVED — the whitelist
    #   below fails fast with a migration hint.
    daily_water_L: float = 67.5
    #   L/day whole-canopy water use ("daily" method), typical 20-150.
    #   Anchor: 1.5 L/m2/day (mature lettuce, band 0.75-2.0) x 45 m2 default
    #   canopy = 67.5.  Rescale as daily_water_L = rate * led.covered_area.
    plant_count: int = 0
    #   plants in the room (count), "per_plant" family.  0 = unset: either
    #   plants_per_m2 derives it (see below) or per-plant methods fail fast.
    ml_per_plant_day: float = 60.0
    #   mL water per plant per day ("per_plant" method), typical 20-150 for
    #   leafy greens.  Anchor: 1500 mL/m2/day / 25 plants/m2 = 60 mL, the
    #   same 67.5 L/day scenario as daily_water_L (25 plants/m2 x 45 m2 x
    #   60 mL = 67.5 L/day).
    plants_per_m2: Optional[float] = None
    #   planting density (plants/m2), optional alternative source for
    #   plant_count in the "per_plant" family.  Valid range (0, 200]
    #   (200/m2 ~ mechanical/spacing ceiling for lettuce-style canopies).
    #   Behaviour: per_plant / per_plant_per_period with plant_count == 0
    #   and plants_per_m2 > 0 derive plant_count =
    #   round(plants_per_m2 x led.covered_area) in the engine
    #   (25 plants/m2 x 45 m2 = 1125 plants).  If BOTH plant_count and
    #   plants_per_m2 are given, plant_count wins (no warning).  If neither
    #   is usable the load-time guard fails fast.
    period_days: List[float] = field(default_factory=lambda: [10.0, 10.0, 10.0])
    #   stage widths (days), "*_per_period" methods; sum(period_days) must
    #   equal setpoints.crop_cycle_days (validated below).
    daily_water_L_period: List[float] = field(default_factory=lambda: [22.5, 45.0, 90.0])
    #   daily water per stage (L/day), "daily_per_period"; one entry per
    #   stage.  Anchor ladder 0.5 / 1.0 / 2.0 L/m2/day x 45 m2 = 22.5 / 45 /
    #   90 (seedling -> mature; late stage at the 2.0 L/m2/day band edge).
    #   Stage difference vs the flat "daily" 1.5 L/m2/day anchor is
    #   intentional: early stages use far less, so the ladder's cycle total
    #   (1575 L / 30 d) sits ~22 % below a flat mature-rate cycle (2025 L).
    ml_per_plant_day_period: List[float] = field(default_factory=lambda: [20.0, 40.0, 80.0])
    #   mL water per plant per day per stage, "per_plant_per_period".
    #   Same 0.5 / 1.0 / 2.0 L/m2/day ladder at 25 plants/m2:
    #   rate x 1000 / 25 = 20 / 40 / 80 mL — consistent with
    #   daily_water_L_period (25 plants/m2 x 45 m2 x [20,40,80] mL =
    #   [22.5, 45, 90] L/day).
    k_van_henten: float = 1.0e-4  # biomass-scaled gain (1/(s·kPa)), van_henten method
    #   Calibrated (P3-1, vfed/plants/transpiration.py): 1e-4 gives ~2.4
    #   L/m2/day at harvest; the former 4e-4 was physically impossible.
    #   Typical 0.5e-4 - 5e-4.
    stage_factor: float = 1.0
    #   extra growth-stage multiplier on every method (-, 0-1+); 1.0 = off.
    dark_transpiration_frac: float = 0.15  # night rate / light rate, all methods
    #   Stomata stay partly open at night (Caird et al. 2007: E_night/E_day
    #   5-15%, up to 30%; Kim et al. 2004: lettuce g_night/g_day 11-39%); PFAL
    #   night VPD ≈ day VPD → take 0.10-0.15.  0.0 = zero in the dark (legacy).


@dataclass
class SetpointConfig:
    T_light: float = 22.0  # °C target during photoperiod
    T_dark: float = 18.0  # °C target during dark period
    RH: float = 65.0
    # P1-4: disease-risk band lower edge (% RH). Hours with indoor RH_z
    # >= this value enter summary["rh_disease_risk_hours"] (grey-mould /
    # Botrytis risk band) and emit an ASCII WARNING when the count > 0.
    # Reporting-only threshold — no device behaviour depends on it.
    rh_disease_risk_threshold: float = 85.0
    co2_ppm: float = 800.0  # ambient CO₂ for plant growth model
    crop_cycle_days: float = 30.0  # harvest interval (resets canopy dry weight)


@dataclass
class PVConfig:
    eta_pv: float = 0.233  # 组件 STC 效率 (−, 无量纲); 仅信息性, MPP 功率由 I_mp×V_mp 计算
    area_to_power: float = 4.3  # 单位容量所需组件面积 (m²/kWp); A_pv/area_to_power = 峰值功率 (kWp)
    N_s: int = 156  # 组件串联电池片数 (−)
    I_sc_stc: float = 13.98  # STC 短路电流 (A)
    V_oc_stc: float = 57.34  # STC 开路电压 (V)
    I_mp_stc: float = 12.66  # STC 最大功率点电流 (A)
    V_mp_stc: float = 45.85  # STC 最大功率点电压 (V); P_module_STC = V_mp×I_mp ≈ 580.5 W
    alpha_sc: float = 0.00045  # 短路电流温度系数 (/K, 相对值 ≈0.045 %/K)——非 A/K
    beta_voc: float = -0.0025  # 开路电压温度系数 (/K, 相对值 ≈-0.25 %/K)——非 V/K
    NOCT: float = 45.0  # 标称工作电池温度 (°C)
    eta_inv: float = 0.97  # 逆变器效率 (−)
    eta_system: float = 0.95  # 系统综合折减 (积灰/直流线损/失配, −); P6-7
    C_pv: float = 500.0  # 光伏系统单价 (项目货币/kWp)——是单价不是容量!
    #   P0-1: 旧默认 110 低于市场 4-8 倍, 已提到市场区间: 中国工商业分布式
    #   2025 组件+安装 ≈ 3-3.5 RMB/W ≈ 3000-3500 RMB/kWp ≈ 420-490 USD/kWp
    #   (按 7.2 汇率), 取整 500 (USD 锚定; 其他货币项目请显式覆盖)。
    #   仅作 capital 块缺省时的 legacy 回退计价 (sweep._total_capital)。
    degradation: float = 0.004  # 年衰减率 (1/年, 0.4 %/年)
    capital: CapitalCostConfig = field(default_factory=CapitalCostConfig)


@dataclass
class BatteryConfig:
    c_energy: float = 220.0  # 电池储能单价 (项目货币/kWh)——注意: 这是"单价"不是容量!
    # 容量见顶层 battery_kwh (kWh)
    c_rate: float = 1.0  # 最大充放电倍率 C-rate (1/h)
    eta_ch: float = 0.91  # 充电效率 (−)
    eta_dis: float = 0.91  # 放电效率 (−)
    soc_min: float = 0.10  # 最小荷电状态 SOC (−, 0~1)
    soc_max: float = 0.90  # 最大荷电状态 SOC (−, 0~1)
    cycle_life: int = 4000  # 循环寿命 (全充放电循环次数至寿命终了, −); 寿命年折算见 P4-15
    allow_grid_charging: bool = False  # 允许电网充电 (P1-2, −)
    #   true  = 谷价时段 (电价==表内最小值) 从电网买电充电池, 用于峰时放电
    #           置换高价电 (TOU 套利; 仅当峰价 > 谷价/(η_ch·η_dis) 往返盈亏
    #           平衡点时启用, 平价电价为空操作)。
    #   false = 现行为 (仅 PV 余电充电), 调度路径逐位不变。
    capital: CapitalCostConfig = field(default_factory=CapitalCostConfig)


@dataclass
class TariffConfig:
    """Hourly electricity price table (24 values, index = hour-of-day).

    All prices are in the project's currency (see ``DesignProject.currency``).
    ``export_price`` is the feed-in tariff (grid buy-back rate).
    """

    hourly_prices: list = field(default_factory=lambda: [0.10] * 24)
    export_price: float = 0.05


@dataclass
class DesignSpace:
    # dict[param_name, [min, max, step]]
    # Parameters NOT listed here use their fixed value from the project.
    # Example: {"ppfd_target": [100, 300, 25], "pv_area": [0, 200, 10]}
    # key 名 = vfed/design/sweep.py 注册表 (HARD_LIMITS/_PARAM_PATH_MAP) 的合法键:
    # 建筑参数 (ppfd_target/efficacy/photoperiod_hours/T_light/T_dark/RH/co2_ppm/
    # crop_cycle_days) + PVBES 键 'pv_area' (m²) / 'battery' (kWh) —— 注意顶层
    # 固定装机字段是 pv_area_m2/battery_kwh, 两者是独立概念 (P8-6)。
    # 自 F7 起, PVBES 键也接受顶层字段名别名: 'pv_area_m2' ≡ 'pv_area',
    # 'battery_kwh' ≡ 'battery' (同一物理参数不可同时写两种拼写)。
    parameter_ranges: dict = field(default_factory=dict)
    timestep_s: float = 600.0
    objective: str = (
        "lcoe"  # optimization target: "lcoe" | "kwh_per_kg_fresh" | "cost_per_kg_fresh"
    )


@dataclass
class DesignProject:
    name: str = "unnamed"
    site: SiteConfig = field(default_factory=SiteConfig)
    envelope: EnvelopeConfig = field(default_factory=EnvelopeConfig)
    hvac: HVACConfig = field(default_factory=HVACConfig)
    deh: DEHConfig = field(default_factory=DEHConfig)
    led: LEDConfig = field(default_factory=LEDConfig)
    transpiration: TranspirationConfig = field(default_factory=TranspirationConfig)
    setpoints: SetpointConfig = field(default_factory=SetpointConfig)
    growth: VanHentenConfig = field(default_factory=VanHentenConfig)
    pv: PVConfig = field(default_factory=PVConfig)
    battery: BatteryConfig = field(default_factory=BatteryConfig)
    tariff: TariffConfig = field(default_factory=TariffConfig)
    space: DesignSpace = field(default_factory=DesignSpace)
    equipment_power_w: float = 0.0  # constant facility electrical base load (W)
    equipment_capital: CapitalCostConfig = field(default_factory=CapitalCostConfig)
    envelope_capital: CapitalCostConfig = field(default_factory=CapitalCostConfig)
    pump_capital: CapitalCostConfig = field(default_factory=CapitalCostConfig)
    # P5-1: irrigation/cooling-water circulation pump capital cost.
    # unit = project currency (direct) or rate_per_watt × rated W (per_watt;
    # no project-level pump rated power exists, so per_watt resolves to 0).
    # Aggregated in sweep._total_capital under "Pump".
    opex: OpexConfig = field(default_factory=OpexConfig)
    # P1-7: internal provenance flag -- True when the source dict/YAML had
    # no explicit 'opex' section, so the built-in USD-scale defaults (labor
    # 30000 + misc 5000 per year) are silently in effect.  Set only by
    # ``from_dict``; never emitted by ``to_dict`` (a user YAML that spells
    # it out is rejected).  Consumed by the engine's OPEX-dominance warning.
    opex_was_defaulted: bool = False
    interest_rate: float = 0.06  # annual discount rate (fraction)
    currency: str = "USD"  # monetary unit for all costs
    exchange_rate: float = 1.0  # conversion factor to USD (7.2 for RMB)

    # ── sizing decisions (energy system) ──
    pv_area_m2: float = 0.0  # PV array area (m²); 0 = skip energy system
    battery_kwh: float = 0.0  # 电池能量容量 (kWh); 0 = 无电池。单价见 battery.c_energy (项目货币/kWh)

    # ---- (de)serialisation ---------------------------------------------
    def to_dict(self) -> dict:
        # P1-7: ``opex_was_defaulted`` is runtime provenance, not schema --
        # strip it so serialized projects never carry an internal key (and
        # ``from_dict``'s internal-key rejection cannot fire on a
        # roundtrip).  When the opex section was defaulted, ``opex`` is
        # omitted as well so ``from_dict`` re-derives the flag (absent
        # section -> True) and the roundtrip stays lossless.
        d = asdict(self)
        d.pop("opex_was_defaulted", None)
        if self.opex_was_defaulted:
            d.pop("opex", None)
        return d

    def save(self, path) -> None:
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(self.to_dict(), f, sort_keys=False, allow_unicode=True)

    @classmethod
    def from_dict(cls, d: dict) -> "DesignProject":
        # P1-7: 'opex_was_defaulted' is an internal flag that from_dict sets
        # itself (raw dict has no 'opex' key).  It is never a user config
        # key -- reject it with a dedicated message instead of the generic
        # unknown-key error so the fix is obvious.
        if "opex_was_defaulted" in d:
            raise ValueError(
                "'opex_was_defaulted' is an internal VFED field, not a user "
                "config key: it is set automatically when the YAML has no "
                "explicit 'opex' section. Remove it from the YAML; to take "
                "control of OPEX, write an explicit 'opex' section instead."
            )
        # Build sub-dataclasses; raise on unrecognised keys.
        _TOP_KEYS = {
            "name",
            "site",
            "envelope",
            "hvac",
            "deh",
            "led",
            "transpiration",
            "setpoints",
            "pv",
            "battery",
            "tariff",
            "space",
            "growth",
            "equipment_power_w",
            "equipment_capital",
            "envelope_capital",
            "pump_capital",
            "opex",
            "interest_rate",
            "currency",
            "exchange_rate",
            "pv_area_m2",
            "battery_kwh",
        }
        unknown_top = set(d.keys()) - _TOP_KEYS
        if unknown_top:
            raise ValueError(
                f"Unrecognised top-level YAML keys: {sorted(unknown_top)}. "
                f"Valid keys: {sorted(_TOP_KEYS)}"
            )

        def sub(target, data, *, yaml_path: str, has_nested_capital: bool = False):
            """Filter ``data`` to the dataclass fields of ``target``, rejecting
            unknown keys.  ``yaml_path`` is the config path (e.g. "hvac") used
            in error messages so users see their YAML key, not the Python class
            name (P8-8)."""
            known = {f.name for f in getattr(target, "__dataclass_fields__").values()}
            # 'capital' is a valid nested field handled separately
            unknown = set(data.keys()) - known - ({"capital"} if has_nested_capital else set())
            if unknown:
                raise ValueError(
                    f"Unrecognised keys in '{yaml_path}': "
                    f"{sorted(unknown)}. Valid keys: {sorted(known)}"
                )
            filtered = {k: data[k] for k in data if k in known}
            if has_nested_capital:
                cap_data = data.get("capital", {})
                if isinstance(cap_data, dict) and cap_data:
                    c_fields = {f.name for f in CapitalCostConfig.__dataclass_fields__.values()}
                    cap_unknown = set(cap_data.keys()) - c_fields
                    if cap_unknown:
                        raise ValueError(
                            f"Unrecognised keys in '{yaml_path}.capital': "
                            f"{sorted(cap_unknown)}. "
                            f"Valid keys: {sorted(c_fields)}"
                        )
                    filtered["capital"] = CapitalCostConfig(
                        **{k: cap_data[k] for k in cap_data if k in c_fields}
                    )
            return filtered

        def _check_capital(cfg_dict, component):
            """P0-1: validate a section's nested ``capital`` block against the
            component's pricing basis (fail-fast at load time)."""
            cap = cfg_dict.get("capital")
            if cap is not None:
                validate_capital_config(cap, component, yaml_path=component)

        def _tariff(d: dict) -> TariffConfig:
            # backward compat: old peak/normal/valley → hourly_prices
            if "hourly_prices" in d:
                _hp = d["hourly_prices"]
                if not isinstance(_hp, list) or len(_hp) != 24:
                    raise ValueError(
                        f"tariff.hourly_prices must be exactly 24 values "
                        f"(index = hour-of-day), got "
                        f"{len(_hp) if isinstance(_hp, list) else type(_hp).__name__}"
                    )
                if not all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in _hp):
                    raise ValueError(
                        "tariff.hourly_prices must contain 24 numbers "
                        "(index = hour-of-day, in the project currency), got "
                        f"{_hp!r}"
                    )
                return TariffConfig(**sub(TariffConfig, d, yaml_path="tariff"))
            if "peak_price" in d:
                _legacy_keys = {
                    "peak_price",
                    "normal_price",
                    "valley_price",
                    "peak_hours",
                    "valley_hours",
                    "export_price",
                }
                _unknown = set(d.keys()) - _legacy_keys
                if _unknown:
                    raise ValueError(
                        f"Unrecognised legacy tariff keys in 'tariff': "
                        f"{sorted(_unknown)}. "
                        f"Valid legacy keys: {sorted(_legacy_keys)}; or use the "
                        f"new-style 'hourly_prices' (24 values)."
                    )
                _require_number(
                    ["peak_price", "normal_price", "valley_price", "export_price"], d, "tariff"
                )
                hp = [d.get("normal_price", 0.10)] * 24
                for h in d.get("peak_hours", []):
                    hp[min(int(h), 23)] = d.get("peak_price", 0.12)
                for h in d.get("valley_hours", []):
                    hp[min(int(h), 23)] = d.get("valley_price", 0.06)
                return TariffConfig(
                    hourly_prices=hp,
                    export_price=d.get("export_price", 0.05),
                )
            return TariffConfig(**sub(TariffConfig, d, yaml_path="tariff"))

        def _require_nonnegative(fields, data, cfg_name):
            """Reject negative config values (a negative moisture gain/removal
            coefficient would silently flip the humidity source into a sink)."""
            for f in fields:
                v = data.get(f)
                if v is None:
                    continue
                if isinstance(v, bool) or not isinstance(v, (int, float)):
                    raise ValueError(
                        f"{cfg_name}.{f} must be a number, " f"got {type(v).__name__}: {v!r}"
                    )
                if v < 0:
                    raise ValueError(f"{cfg_name}.{f} must be >= 0, got {v}")

        def _require_number(fields, data, cfg_name):
            """Reject non-numeric config values at load time (fail-fast,
            P8-5).  Strings like "600" or "six" previously loaded fine and
            only exploded deep inside the engine/sweep."""
            for f in fields:
                v = data.get(f)
                if v is None:
                    continue
                if isinstance(v, bool) or not isinstance(v, (int, float)):
                    raise ValueError(
                        f"{cfg_name}.{f} must be a number, " f"got {type(v).__name__}: {v!r}"
                    )

        def _normalize_aliases(data, *, section: str, yaml_path: str) -> dict:
            """Map datasheet-style hardware names onto the canonical VFED
            config key (S1).  ``HARDWARE_ALIASES`` defines the vocabulary per
            section; canonical keys still work unchanged (back-compat).  A
            config that specifies BOTH an alias and its canonical key with
            different values is ambiguous and rejected."""
            data = data or {}
            aliases = HARDWARE_ALIASES.get(section, {})
            if not aliases:
                return dict(data)
            out = dict(data)
            for alias, canon in aliases.items():
                if alias not in out:
                    continue
                if canon in out:
                    if out[canon] != out[alias]:
                        raise ValueError(
                            f"Ambiguous '{yaml_path}' config: both '{alias}' "
                            f"and '{canon}' are given with different values "
                            f"({out[alias]!r} vs {out[canon]!r}). "
                            f"Set only one of them."
                        )
                    del out[alias]  # equal values: drop the alias
                    continue
                out[canon] = out.pop(alias)
            return out

        # ── humidity-related sub-configs (validated, then applied) ──
        transp_cfg = sub(TranspirationConfig, d.get("transpiration", {}), yaml_path="transpiration")
        deh_cfg = sub(
            DEHConfig,
            _normalize_aliases(d.get("deh", {}), section="deh", yaml_path="deh"),
            yaml_path="deh",
            has_nested_capital=True,
        )
        _check_capital(deh_cfg, "deh")  # P0-1
        sp_cfg = sub(SetpointConfig, d.get("setpoints", {}), yaml_path="setpoints")
        _require_number(
            [
                "T_light",
                "T_dark",
                "RH",
                "rh_disease_risk_threshold",
                "co2_ppm",
                "crop_cycle_days",
            ],
            sp_cfg,
            "setpoints",
        )
        _require_nonnegative(
            [
                "daily_water_L",
                "plant_count",
                "ml_per_plant_day",
                "k_van_henten",
                "stage_factor",
                "dark_transpiration_frac",
            ],
            transp_cfg,
            "transpiration",
        )
        # P1-6: optional planting density — if set it must be a sane number.
        # Band (0, 200] plants/m2: ~200/m2 is the mechanical/spacing ceiling
        # for lettuce-style canopies; a denser figure is almost surely a
        # unit mistake (e.g. plants per tray).
        _ppm2 = transp_cfg.get("plants_per_m2")
        if _ppm2 is not None:
            if isinstance(_ppm2, bool) or not isinstance(_ppm2, (int, float)):
                raise ValueError(
                    f"transpiration.plants_per_m2 must be a number "
                    f"(plants/m2), got {type(_ppm2).__name__}: {_ppm2!r}"
                )
            if not (0.0 < _ppm2 <= 200.0):
                raise ValueError(
                    f"transpiration.plants_per_m2 must be in (0, 200] "
                    f"plants/m2, got {_ppm2}"
                )
        _require_nonnegative(
            ["smer", "M_deh_nom", "P_ref_w", "P_rated_max", "comp_mod_band_rh"],
            deh_cfg,
            "deh",
        )
        # P1-1: deh.control whitelist — an unknown mode must fail fast instead
        # of silently falling back to the VFD path (no silent fallbacks).
        _deh_control = deh_cfg.get("control")
        if _deh_control is not None and _deh_control not in ("vfd", "on_off"):
            raise ValueError(
                f"deh.control must be one of vfd|on_off, got {_deh_control!r}. "
                f"'vfd' modulates speed inside deh.comp_mod_band_rh (DOE part-load "
                f"SMER penalty); 'on_off' cycles at full speed on deh.deadband_rh "
                f"(rated SMER while running)."
            )
        rh_sp = sp_cfg.get("RH")
        if rh_sp is not None and not (0.0 <= rh_sp <= 100.0):
            raise ValueError(f"setpoints.RH must be in [0,100] %, got {rh_sp}")
        # P1-4: disease-risk threshold must be a sane % RH (0 excluded -- an
        # always-true threshold would turn every hour into a risk hour).
        _rh_thr = sp_cfg.get("rh_disease_risk_threshold")
        if _rh_thr is not None and not (0.0 < _rh_thr <= 100.0):
            raise ValueError(
                f"setpoints.rh_disease_risk_threshold must be in (0, 100] %, "
                f"got {_rh_thr}"
            )

        # ── PV temperature-coefficient dimension guards ──
        # alpha_sc / beta_voc are RELATIVE coefficients (/K). A value of 0.045
        # (previously shipped in the example YAMLs) is 100x the physical
        # 0.00045 and inflates annual yield ~1.7x; an absolute -0.25 V/K is
        # ~1.75x the datasheet-consistent relative value. Reject out-of-band
        # values at load time (fail-fast).
        pv_cfg = sub(PVConfig, d.get("pv", {}), yaml_path="pv", has_nested_capital=True)
        _check_capital(pv_cfg, "pv")  # P0-1: reject per_watt on PV at load
        _pv_alpha = pv_cfg.get("alpha_sc")
        if _pv_alpha is not None and not (0.0 < _pv_alpha < 0.01):
            raise ValueError(f"pv.alpha_sc must be in (0, 0.01) /K (relative), got {_pv_alpha}")
        _pv_beta = pv_cfg.get("beta_voc")
        if _pv_beta is not None and not (-0.1 < _pv_beta < 0.0):
            raise ValueError(f"pv.beta_voc must be in (-0.1, 0) /K (relative), got {_pv_beta}")

        # ── HVAC COP / coil guards (fail-fast) ──
        # A negative COP silently flips the cooling cycle into a heater+humidifier
        # (Q_total<0 → Q_target>0, M_target<0); an unknown cop_mode falls through
        # to `return self.value`; shr_BF=1.0 divides by zero in the BF-ADP coil
        # model. Reject all of these at load time.
        hvac_cfg = sub(
            HVACConfig,
            _normalize_aliases(d.get("hvac", {}), section="hvac", yaml_path="hvac"),
            yaml_path="hvac",
            has_nested_capital=True,
        )
        _check_capital(hvac_cfg, "hvac")  # P0-1
        _require_nonnegative(
            [
                "cop_value",
                "cop_heat",
                "eta_II",
                "delta_T_evap",
                "delta_T_cond",
                "P_rated_w",
                "P_rated_heat_w",
                "Q_cool_nom",
                "P_rated_max",
                "safety_factor",
                "comp_mod_band_c",
            ],
            hvac_cfg,
            "hvac",
        )
        _speed_curve = hvac_cfg.get("speed_curve")
        if _speed_curve is not None and _speed_curve not in ("default", "flat"):
            raise ValueError(
                f"hvac.speed_curve must be one of " f"default|flat, got {_speed_curve}"
            )
        _cop_mode = hvac_cfg.get("cop_mode")
        if _cop_mode is not None and _cop_mode not in ("carnot", "constant", "linear", "table"):
            raise ValueError(
                f"hvac.cop_mode must be one of " f"carnot|constant|linear|table, got {_cop_mode}"
            )
        _cop_table = hvac_cfg.get("cop_table") or {}
        if not isinstance(_cop_table, dict):
            raise ValueError(
                f"hvac.cop_table must be a {{T_ext_degC: COP}} mapping "
                f"(dict), got {type(_cop_table).__name__}: {_cop_table!r}. "
                f"Example: cop_table: {{20: 3.0, 35: 2.5}}"
            )
        for _k, _v in _cop_table.items():
            if _v < 0:
                raise ValueError(f"hvac.cop_table[{_k}] must be >= 0, got {_v}")
        _heat_mode = hvac_cfg.get("heat_mode")
        if _heat_mode is not None and _heat_mode not in ("heat_pump", "resistive"):
            raise ValueError(
                f"hvac.heat_mode must be one of " f"heat_pump|resistive, got {_heat_mode}"
            )
        _shr_bf = hvac_cfg.get("shr_BF")
        if _shr_bf is not None and not (0.0 <= _shr_bf < 1.0):
            raise ValueError(f"hvac.shr_BF must be in [0, 1), got {_shr_bf}")

        # ── transpiration.method whitelist (P5-5) ──
        # An unknown method silently returns zero transpiration — the room
        # loses its moisture source, the DEH never runs and the latent load
        # is wrong end-to-end.  Align with the cop_mode guard above.
        _method = transp_cfg.get("method")
        if _method is not None and _method not in (
            "van_henten",
            "daily",
            "per_plant",
            "daily_per_period",
            "per_plant_per_period",
        ):
            if _method in ("constant", "vpd", "stomatal"):
                raise ValueError(
                    f"transpiration.method='{_method}' was removed. "
                    f"Migrate to 'van_henten' (model-calculated, default) "
                    f"or one of daily|per_plant|daily_per_period|"
                    f"per_plant_per_period (direct-set)."
                )
            raise ValueError(
                f"transpiration.method must be one of "
                f"van_henten|daily|per_plant|daily_per_period|"
                f"per_plant_per_period, got {_method}"
            )

        # ── period-staged guards: list shape, positivity, harvest alignment.
        # sub() does not merge dataclass defaults, so fall back to
        # TranspirationConfig() defaults for fields the YAML omits.
        if _method in ("daily_per_period", "per_plant_per_period"):
            _t_dflt = TranspirationConfig()
            _pd = transp_cfg.get("period_days")
            if _pd is None:
                _pd = _t_dflt.period_days
            _need = (
                "daily_water_L_period"
                if _method == "daily_per_period"
                else "ml_per_plant_day_period"
            )
            _req = transp_cfg.get(_need)
            if _req is None:
                _req = getattr(_t_dflt, _need)
            if not isinstance(_pd, list) or not _pd:
                raise ValueError(
                    f"transpiration.period_days must be a non-empty list "
                    f"of stage widths (days), got {_pd!r}"
                )
            if not isinstance(_req, list) or not _req:
                raise ValueError(
                    f"transpiration.{_need} must be a non-empty list of "
                    f"daily water totals (one per stage), got {_req!r}"
                )
            if len(_pd) != len(_req):
                raise ValueError(
                    f"transpiration.{_need} has {len(_req)} entries but "
                    f"transpiration.period_days has {len(_pd)} -- one water "
                    f"total per stage is required."
                )
            if any(isinstance(x, bool) or not isinstance(x, (int, float)) or x <= 0 for x in _pd):
                raise ValueError(
                    f"transpiration.period_days must contain positive "
                    f"numbers (days per stage), got {_pd!r}"
                )
            if any(isinstance(x, bool) or not isinstance(x, (int, float)) or x <= 0 for x in _req):
                raise ValueError(
                    f"transpiration.{_need} must contain positive numbers "
                    f"(water per stage), got {_req!r}"
                )
            _sum_pd = float(sum(_pd))
            _cycle = sp_cfg.get("crop_cycle_days")
            if _cycle is not None and abs(_sum_pd - _cycle) > 1e-9:
                raise ValueError(
                    f"transpiration.period_days sums to {_sum_pd} days but "
                    f"setpoints.crop_cycle_days is {_cycle} -- they must "
                    f"match so stage boundaries stay aligned with the "
                    f"harvest cycle."
                )

        # P1-6: per-plant methods need a usable plant count.  Sources, in
        # order: explicit plant_count > 0, else plants_per_m2 x
        # led.covered_area (derived by the engine at build time), else fail
        # fast here.
        if _method in ("per_plant", "per_plant_per_period"):
            _pc = transp_cfg.get("plant_count")
            if _pc is None:
                _pc = TranspirationConfig().plant_count
            _pc_ok = _pc is not None and _pc > 0
            _ppm2_ok = _ppm2 is not None and _ppm2 > 0
            if not _pc_ok and not _ppm2_ok:
                raise ValueError(
                    f"transpiration.method='{_method}' requires a plant "
                    f"count: set transpiration.plant_count > 0 (got {_pc}) "
                    f"or transpiration.plants_per_m2 in (0, 200] plants/m2 "
                    f"(the engine then derives plant_count = "
                    f"round(plants_per_m2 * led.covered_area))"
                )

        # ── LED guards (P5-6 / P5-7) ──
        led_cfg = sub(LEDConfig, d.get("led", {}), yaml_path="led", has_nested_capital=True)
        _check_capital(led_cfg, "led")  # P0-1
        _require_number(
            [
                "power_w",
                "light_start_hour",
                "photoperiod_hours",
                "heat_fraction",
                "efficacy",
                "ppfd_target",
                "covered_area",
            ],
            led_cfg,
            "led",
        )
        if led_cfg.get("auto_deduce", True) and led_cfg.get("power_w") not in (None, 1300.0):
            import warnings as _w

            _w.warn(
                "led.auto_deduce=True ignores led.power_w (recomputed as "
                "ppfd_target*covered_area/efficacy). Set led.auto_deduce=False "
                "to make led.power_w effective.",
                UserWarning,
                stacklevel=2,
            )
        _spectrum = led_cfg.get("spectrum")
        if _spectrum is not None and _spectrum not in ("white", "rb_3to1", "rb_4to1", "rb_2to1"):
            raise ValueError(
                f"led.spectrum must be one of " f"white|rb_3to1|rb_4to1|rb_2to1, got {_spectrum}"
            )

        # ── design space: objective whitelist + range structure + timestep ──
        space_cfg = sub(DesignSpace, d.get("space", {}), yaml_path="space")
        _objective = space_cfg.get("objective")
        if _objective is not None and _objective not in (
            "lcoe",
            "kwh_per_kg_fresh",
            "cost_per_kg_fresh",
        ):
            raise ValueError(
                f"space.objective must be one of "
                f"lcoe|kwh_per_kg_fresh|cost_per_kg_fresh, got {_objective}"
            )
        _pr = space_cfg.get("parameter_ranges") or {}
        if not isinstance(_pr, dict):
            raise ValueError(
                f"space.parameter_ranges must be a dict of "
                f"{{name: [min, max, step]}}, got {type(_pr).__name__}"
            )
        for _name, _rng in _pr.items():
            if not isinstance(_rng, (list, tuple)) or len(_rng) != 3:
                raise ValueError(
                    f"space.parameter_ranges['{_name}'] must be a "
                    f"[min, max, step] triple, got {_rng!r}"
                )
            for _i, _v in enumerate(_rng):
                if isinstance(_v, bool) or not isinstance(_v, (int, float)):
                    raise ValueError(
                        f"space.parameter_ranges['{_name}'][{_i}] must be " f"numeric, got {_v!r}"
                    )
        _require_number(["timestep_s"], space_cfg, "space")
        _ts = space_cfg.get("timestep_s")
        if _ts is not None:
            if _ts <= 0:
                raise ValueError(f"space.timestep_s must be > 0, got {_ts}")
            _sub = max(1, int(round(3600.0 / _ts)))  # mirror engine.py:304
            if abs(_sub * _ts - 3600.0) > 1.0:  # mirror engine.py:305
                raise ValueError(
                    f"space.timestep_s={_ts}s does not evenly divide 3600s "
                    f"(modeled {_sub * _ts}s per hour). Choose a divisor of "
                    f"3600 (e.g., 600, 900, 1200, 1800, 3600)."
                )

        # ── top-level numeric guards (P8-5) ──
        _require_number(
            ["equipment_power_w", "interest_rate", "exchange_rate", "pv_area_m2", "battery_kwh"],
            d,
            "project",
        )

        # ── soft guards: silently-wrong climate / currency (P8-13/P8-14) ──
        import warnings as _w

        _site_d = d.get("site", {}) or {}
        if ("lat" not in _site_d or "lon" not in _site_d) and not _site_d.get("city"):
            _w.warn(
                "site.lat/site.lon missing -- falling back to Shanghai "
                "defaults (31.2, 121.5). Set them (or site.city) to avoid "
                "a silently wrong climate.",
                UserWarning,
                stacklevel=2,
            )
        if "name" not in d:
            _w.warn(
                "project 'name' missing -- using 'unnamed'. Set name to "
                "identify this design in outputs.",
                UserWarning,
                stacklevel=2,
            )
        _cur = d.get("currency", "USD")
        _fx = d.get("exchange_rate", 1.0)
        if _cur and _cur != "USD" and _fx == 1.0:
            _w.warn(
                f"currency='{_cur}' with exchange_rate=1.0 treats all costs "
                f"as 1:1 to USD -- set exchange_rate (e.g. 7.2 for RMB) or "
                f"keep currency='USD'.",
                UserWarning,
                stacklevel=2,
            )

        site_cfg = sub(SiteConfig, d.get("site", {}), yaml_path="site")
        _require_number(["lat", "lon", "tz_hours", "tilt", "azimuth", "year"], site_cfg, "site")

        # P0-1: battery + top-level capital blocks -- validate the pricing
        # basis before constructing the project (fail-fast, YAML paths).
        battery_cfg = sub(
            BatteryConfig, d.get("battery", {}), yaml_path="battery", has_nested_capital=True
        )
        _check_capital(battery_cfg, "battery")
        # P1-2: allow_grid_charging must be a real boolean (YAML true/false).
        # Strings like "true" or the numbers 0/1 previously would coerce or
        # crash deep inside dispatch — reject at load time instead.
        _agc = battery_cfg.get("allow_grid_charging")
        if _agc is not None and not isinstance(_agc, bool):
            raise ValueError(
                f"battery.allow_grid_charging must be a boolean (true/false), "
                f"got {type(_agc).__name__}: {_agc!r}"
            )
        _equipment_cap = CapitalCostConfig(
            **sub(CapitalCostConfig, d.get("equipment_capital", {}), yaml_path="equipment_capital")
        )
        validate_capital_config(_equipment_cap, "equipment", yaml_path="equipment_capital")
        _envelope_cap = CapitalCostConfig(
            **sub(CapitalCostConfig, d.get("envelope_capital", {}), yaml_path="envelope_capital")
        )
        validate_capital_config(_envelope_cap, "envelope", yaml_path="envelope_capital")
        _pump_cap = CapitalCostConfig(
            **sub(CapitalCostConfig, d.get("pump_capital", {}), yaml_path="pump_capital")
        )
        validate_capital_config(_pump_cap, "pump", yaml_path="pump_capital")

        # P1-7: flag = the opex section was not spelled out, so the built-in
        # defaults (labor 30000 + misc 5000 per year, USD-scale) are in
        # effect.  Pure provenance -- never touches any numeric result.
        _opex_was_defaulted = "opex" not in d

        return cls(
            name=d.get("name", "unnamed"),
            site=SiteConfig(**site_cfg),
            envelope=EnvelopeConfig(
                **sub(EnvelopeConfig, d.get("envelope", {}), yaml_path="envelope")
            ),
            hvac=HVACConfig(**hvac_cfg),
            deh=DEHConfig(**deh_cfg),
            led=LEDConfig(**led_cfg),
            transpiration=TranspirationConfig(**transp_cfg),
            setpoints=SetpointConfig(**sp_cfg),
            growth=VanHentenConfig(**sub(VanHentenConfig, d.get("growth", {}), yaml_path="growth")),
            pv=PVConfig(**pv_cfg),
            battery=BatteryConfig(**battery_cfg),
            tariff=_tariff(d.get("tariff", {})),
            space=DesignSpace(**space_cfg),
            equipment_power_w=d.get("equipment_power_w", 0.0),
            equipment_capital=_equipment_cap,
            envelope_capital=_envelope_cap,
            pump_capital=_pump_cap,
            opex=OpexConfig(**sub(OpexConfig, d.get("opex", {}), yaml_path="opex")),
            opex_was_defaulted=_opex_was_defaulted,
            interest_rate=d.get("interest_rate", 0.06),
            currency=d.get("currency", "USD"),
            exchange_rate=d.get("exchange_rate", 1.0),
            pv_area_m2=d.get("pv_area_m2", 0.0),
            battery_kwh=d.get("battery_kwh", 0.0),
        )

    @classmethod
    def load(cls, path) -> "DesignProject":
        with open(path, "r", encoding="utf-8") as f:
            return cls.from_dict(yaml.safe_load(f))
