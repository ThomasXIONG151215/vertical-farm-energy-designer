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
from typing import Dict, List, Optional, Tuple

import yaml

from .fx import (
    USD_C_ENERGY,
    USD_C_PV,
    USD_EXPORT,
    USD_LABOR,
    USD_MISC,
    USD_RATE_PER_WATT,
    USD_TARIFF,
    USD_WATER,
    usd_base_to_project,
)

__all__ = [
    "CapitalCostConfig",
    "CAPITAL_MODES_BY_COMPONENT",
    "validate_capital_config",
    "WEATHER_PROVIDERS",
    "GHI_SCALE_LIMITS",
    "validate_weather_provider",
    "validate_ghi_scale",
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
    "HARD_LIMITS",
    "PARAM_PATH_MAP",
    "PARAM_TOPLEVEL_MAP",
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


# ---------------------------------------------------------------------------
# Hard limits — values outside these bounds raise a config error (E001).
# Migrated here from sweep.py (user12 fix, T1): the table used to guard ONLY
# sweep parameter_ranges, so a single-point evaluate with e.g.
# led.ppfd_target: 9999 sailed through and produced an absurd result.
# ``DesignProject.from_dict`` now enforces the same bands on every scalar
# config field, so validate / evaluate / sweep all fail fast at load time.
# ---------------------------------------------------------------------------
HARD_LIMITS: Dict[str, Tuple[float, float]] = {
    "ppfd_target": (50, 500),
    "efficacy": (1.5, 4.0),
    "photoperiod_hours": (0, 24),
    "light_start_hour": (0, 23),
    "T_light": (15, 30),
    "T_dark": (10, 28),
    "RH": (40, 90),
    "co2_ppm": (300, 2000),
    "crop_cycle_days": (15, 60),
    "pv_area": (0, 1000),
    "battery": (0, 500),
}

# Mapping: hard-limit name -> (project_dict_section, field_name) for the
# building-side parameters.  Consumed by from_dict's scalar guard and by
# sweep._override_project.
PARAM_PATH_MAP: Dict[str, Tuple[str, str]] = {
    "ppfd_target": ("led", "ppfd_target"),
    "efficacy": ("led", "efficacy"),
    "light_start_hour": ("led", "light_start_hour"),
    "photoperiod_hours": ("led", "photoperiod_hours"),
    "T_light": ("setpoints", "T_light"),
    "T_dark": ("setpoints", "T_dark"),
    "RH": ("setpoints", "RH"),
    "co2_ppm": ("setpoints", "co2_ppm"),
    "crop_cycle_days": ("setpoints", "crop_cycle_days"),
}

# PVBES sizing keys (pv_area / battery) have no nested section: their YAML
# home is the top-level sizing fields pv_area_m2 / battery_kwh (same physical
# quantity, different key name -- see DesignSpace's comment, P8-6/F7).  The
# from_dict guard uses this map so no HARD_LIMITS entry is silently skipped.
PARAM_TOPLEVEL_MAP: Dict[str, str] = {
    "pv_area": "pv_area_m2",
    "battery": "battery_kwh",
}


# ---------------------------------------------------------------------------
# Round 22: weather provider enum + GHI bias-correction band.  Enforced by
# ``DesignProject.from_dict`` (E001 at load time) and reused verbatim by the
# CLI ``--provider`` / ``--ghi-scale`` overrides and agent_evaluate's
# additive kwargs, so every entry point applies the SAME rule.
# ---------------------------------------------------------------------------
WEATHER_PROVIDERS: Tuple[str, ...] = ("open-meteo", "nasa-power")
GHI_SCALE_LIMITS = (0.5, 1.5)  # (lo, hi]; <= 0.5 is almost surely a unit/source error


def validate_weather_provider(value, where: str = "site.weather_provider") -> str:
    """Round 22: provider whitelist — an unknown source must fail fast
    instead of silently falling back to Open-Meteo (no silent fallbacks)."""
    if value not in WEATHER_PROVIDERS:
        raise ValueError(
            f"{where} must be one of {'|'.join(WEATHER_PROVIDERS)}, got "
            f"{value!r}. 'open-meteo' (ERA5 archive) is the default; "
            f"'nasa-power' fetches NASA POWER hourly (MERRA-2/CERES)."
        )
    return value


def validate_ghi_scale(value, where: str = "site.ghi_scale") -> float:
    """Round 22: GHI bias-correction band (0.5, 1.5] (E001 at load time)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(
            f"{where} must be a number (GHI multiplier), got "
            f"{type(value).__name__}: {value!r}"
        )
    lo, hi = GHI_SCALE_LIMITS
    if not (lo < float(value) <= hi):
        raise ValueError(
            f"{where} must be in ({lo}, {hi}], got {value}. The multiplier "
            f"scales shortwave_radiation (and the POA field) at the weather "
            f"exit; a factor of {lo} or less is almost surely a unit or "
            f"source mistake, not a bias correction."
        )
    return float(value)


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

    F2 (round 21): ``cost`` defaults to ``None`` — the "unspecified" sentinel.
    ``None`` (capital block absent, or the block present but the ``cost`` key
    omitted / null) selects the legacy fallback pricing (``pv.C_pv`` per kWp,
    ``battery.c_energy`` per kWh; 0 for components without a legacy price).
    An explicit ``cost: 0.0`` is a literal zero-cost component and never
    falls back; negative values are rejected at load time.

    R26 (currency engine): ``rate_per_watt`` uses the same sentinel pattern.
    ``None`` (key omitted / null) means the built-in USD-baseline default
    (1.0 currency/W), which ``from_dict`` materializes into the project
    currency via ``exchange_rate``; an explicit value is a literal in the
    project currency and is never converted.
    """

    mode: str = "direct"
    cost: Optional[float] = None
    rate_per_watt: Optional[float] = None  # None -> USD baseline 1.0 x exchange_rate
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
    # F2 (round 21): cost=None means "unspecified" (legacy fallback) and is
    # exempt from the negativity check; an explicit negative cost is a config
    # error, not something to silently fall back from.
    if cfg.cost is not None and cfg.cost < 0:
        raise ValueError(
            f"{where}: cost must be >= 0, got {cfg.cost}. Omit 'cost' (or the "
            f"whole capital block) for legacy fallback pricing, or write an "
            f"explicit cost: 0.0 for a zero-cost component."
        )


@dataclass
class OpexConfig:
    """Annual operating expenditure for the farm.

    All costs are in the project's currency unit (see ``DesignProject.currency``
    and ``exchange_rate``).  Currency-magnitude consistency: labor / water /
    misc OPEX, tariff prices and capital costs must all be written in the
    SAME currency that ``currency`` claims.

    R26 (currency engine): the three price fields below are USD-baseline
    defaults behind the ``None`` sentinel (same pattern as
    ``CapitalCostConfig.cost``, F2).  Omitting a field (or writing ``null``)
    selects the built-in USD-baseline default, which ``from_dict``
    materializes into the project currency via ``exchange_rate``; writing an
    explicit value means "this many units of MY currency" and is never
    converted.  ``maintenance_pct`` is a capital fraction (unitless) -- not
    part of the currency engine.

    P1-7 transparency: when the YAML omits the whole ``opex`` section (or any
    of the three price fields), ``DesignProject`` sets ``opex_was_defaulted``
    and the engine reports ``annual_om_pct_of_cost`` plus a WARNING when OPEX
    dominates.

    * ``water_cost_per_m3``: water price (irrigation + makeup).
      Default (USD baseline) 2.0 currency/m3.
    * ``labor_cost_per_year``: total annual labor cost.
      Default (USD baseline) 30000.0 currency/yr; NOT rescaled to farm size.
    * ``maintenance_pct``: annual maintenance as fraction of total CAPEX.
      Default 0.02 (2%/yr).
    * ``misc_opex_per_year``: other operating costs (seeds, nutrients, etc.).
      Default (USD baseline) 5000.0 currency/yr.
    """

    water_cost_per_m3: Optional[float] = None  # None -> USD baseline 2.0 x exchange_rate
    labor_cost_per_year: Optional[float] = None
    #   None -> USD baseline 30000/yr x exchange_rate; applies silently if
    #   unspecified (P1-7); verify against YOUR currency.
    maintenance_pct: float = 0.02  # fraction of total CAPEX per year
    misc_opex_per_year: Optional[float] = None
    #   None -> USD baseline 5000/yr x exchange_rate; applies silently if
    #   unspecified (P1-7).


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

    Round 22 (weather source, 新增，均有默认值——缺省即原行为，零漂移):

        weather_provider = "open-meteo"  逐时天气源枚举
            "open-meteo"  ERA5 archive (默认，历来的唯一来源)
            "nasa-power"  NASA POWER hourly (MERRA-2/CERES)；GHI 气候态略优，
                          T2M/WS10M 略差 (见 README "Weather Data")。非默认
                          provider 的缓存/城市文件名自动加 ``_power`` 后缀，
                          两源永不混用。
        ghi_scale = 1.0  GHI 订正乘子，区间 (0.5, 1.5]。在 weather df 出口
            统一乘 shortwave_radiation 及其派生的 POA 场 (POA/PV/年度 GHI
            同比例生效)；缓存文件存的是未乘订正的原始值，改系数不换缓存。
            例: 把 ERA5 年 GHI 1570 kWh/m2/yr 对齐到当地气候态 1370 时，
            ghi_scale ≈ 1370/1570 = 0.873。
    """

    lat: float = 31.2
    lon: float = 121.5
    tz_hours: float = 8.0  # UTC+8 (中国标准时间)
    tilt: float = 20.0  # PV 阵列倾角 (°)
    azimuth: float = 180.0  # PV 方位角 (°, 180=正南)
    year: int = 2025  # 天气数据年份
    city: Optional[str] = None  # optional: pre-downloaded city name
    weather_provider: str = "open-meteo"
    #   hourly weather source (round 22); see the class docstring above.
    ghi_scale: float = 1.0
    #   GHI bias-correction multiplier, band (0.5, 1.5]; see the class
    #   docstring above — the cache always stores unscaled values.


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
    # ── R28: 2R2C wall thermal-mass network (additive, default off) ──
    wall_rc_nodes: int = 0
    #   0 (default) = legacy single-node envelope: Q_wall = U_wall_A×(T_ext−T_z),
    #   behaviour identical to pre-R28 builds.  2 = enable the 2R2C network
    #   (air node T_z + lumped mass node T_m; g_im couples T_m→T_z, g_em
    #   couples T_m→outdoors).  3 = enable the 2R3C network (adds a surface
    #   node T_s between T_m and T_z: C_surface capacity, g_sa couples
    #   T_s→T_z, g_sm couples T_s→T_m) -- the topology the LBNL BESTEST
    #   reference uses to route window solar through a construction surface.
    #   The engine fails fast at build time if the configured timestep
    #   violates the forward-Euler stability band of the resulting 2×2 / 3×3
    #   system (λmax guards in engine._build_devices).
    C_mass: float = 0.0  # Wh/K lumped mass-layer capacity (wall_rc_nodes=2 only)
    #   Estimating: Σ A_i·d_i·ρ_i·c_i / 3600 over the mass layers (wall/roof/
    #   floor slabs), including pure internal mass with no outdoor path (e.g.
    #   a floor slab on insulation).  Concrete slab: A·d·1400·1000/3600 ≈
    #   0.389×A·d(m) Wh/K; timber board ≈ 0.22×A·d Wh/K.
    g_im: float = 0.0  # W/K mass node -> air node conductance (wall_rc_nodes=2 only)
    #   Inner surface film + inner half of the mass layer, surfaces in
    #   parallel: Σ A_i / (R_si + d_i/(2·k_i)) with R_si ≈ 0.125 m²K/W.
    g_em: float = 0.0  # W/K mass node -> outdoor conductance (wall_rc_nodes=2 only)
    #   Outer half of the mass layer + remaining layers + exterior film:
    #   Σ A_i / R_i,ext.  0 is valid (pure internal mass).  With RC on,
    #   U_wall_A means the DIRECT channel only (window + lightweight surfaces
    #   bypassing the mass node); steady-state design conductance closes as
    #   UA_dc = U_wall_A + g_em·g_im/(g_em+g_im) (hvac auto-size uses this).
    # ── R28 step 3: 2R3C wall network (wall_rc_nodes=3) + solar split ──
    C_surface: float = 0.0  # Wh/K surface-node capacity (wall_rc_nodes=3 only)
    #   Lumped capacity of the solar-receiving inner surfaces (floor slab +
    #   inner boards): Σ A_i·d_i·ρ_i·c_i / 3600.  BESTEST-600 floor (25 mm oak
    #   over insulation): 48·0.025·650·1200/3600 ≈ 260 Wh/K.
    g_sa: float = 0.0  # W/K surface node -> air node conductance (wall_rc_nodes=3 only)
    #   Inner surface film over the solar-receiving areas, in parallel:
    #   Σ A_i / R_si with R_si ≈ 0.125 m²K/W (48 m² floor ≈ 384 W/K).
    g_sm: float = 0.0  # W/K surface node -> mass node conductance (wall_rc_nodes=3 only)
    #   Conduction from the surface into the inner half of the mass layer:
    #   Σ A_i / (d_i/(2·k_i)).  Small for insulated light construction.
    solar_mass_fraction: float = 0.0
    #   Fraction of the window solar gain fed INTO the RC network as a heat
    #   source (mass node for wall_rc_nodes=2, surface node for =3 -- the LBNL
    #   SolarRadiationExchange rule puts all transmitted solar on the
    #   construction surfaces, i.e. 1.0); the remainder goes to the air node
    #   exactly as before.  0.0 (default) = legacy single-point air injection,
    #   bit-for-bit identical to pre-step-3 builds.  Requires wall_rc_nodes>0
    #   (no mass node to absorb it otherwise); valid range [0, 1].
    # ── R28 step 6: 1-D finite-difference wall (wall_fd_nodes > 0) ──
    wall_fd_nodes: int = 0
    #   0 (default) = FD wall OFF (legacy / RC paths untouched, zero drift).
    #   10..100 = number of FD nodes discretising the wall_layers stack
    #   (cell-centered control volumes; nodes distributed per layer
    #   proportional to sqrt(R_i·C_i), min 1 per layer).  Mutually exclusive
    #   with wall_rc_nodes > 0.  Implicit (backward-Euler) solve: stable for
    #   any dt; the engine still fails fast on dt <= 0.
    wall_layers: List[Tuple[float, float, float, float]] = field(default_factory=list)
    #   Wall layer stack, EXTERIOR -> INTERIOR, each (thickness_m, k_W_mK,
    #   rho_kg_m3, c_J_kgK).  Required non-empty when wall_fd_nodes > 0.
    #   Example (ASHRAE 140 Case 600 wall, 63.6 m2): [(0.009, 0.14, 530, 900),
    #   (0.066, 0.04, 12, 840), (0.012, 0.16, 950, 840)] -> R=1.789 m2K/W,
    #   areal capacity 14.53 kJ/m2K.
    wall_area_m2: float = 0.0
    #   Conductive area of the FD wall (m2); required > 0 when wall_fd_nodes>0.
    h_ext_wm2: float = 0.0
    #   Exterior surface film coefficient (W/m2K); required > 0 when
    #   wall_fd_nodes > 0 (ASHRAE 140: R_o = 0.04 m2K/W -> h_o = 25.0).
    wall_solar_abs: float = 0.0
    #   Exterior solar absorptance [0, 1] driving the sol-air boundary
    #   T_sol-air = T_ext + wall_solar_abs * I_ext / h_ext_wm2 (long-wave sky
    #   term not modelled).  0.0 (default) disables the sol-air channel
    #   (boundary = T_ext).
    h_int_c_wm2: float = 0.0
    #   Interior CONVECTIVE film coefficient (W/m2K) coupling the wall inner
    #   surface to the zone air; required > 0 when wall_fd_nodes > 0
    #   (g_c = h_int_c_wm2 * wall_area_m2).  The radiative share to the
    #   internal mass runs through g_sm (LBNL BESTEST: h_c = 3.0 fixed,
    #   h_r ~ 5.3 -> total 8.29 = 1/R_si per ASHRAE 140).
    # ── R34/W3-E (H7): mechanical fresh air + ERV/HRV heat recovery ──
    erv_enabled: bool = False
    #   true = a mechanical ventilation stream of erv_flow_m3h m3/h runs
    #   through a heat-recovery core, IN ADDITION to the ach infiltration
    #   (both channels superpose; the ERV flow does not replace leakage).
    #   false (default) = no mechanical ventilation, bit-for-bit legacy.
    erv_flow_m3h: float = 0.0
    #   Mechanical fresh-air volume flow (m3/h); required > 0 when
    #   erv_enabled (fail-fast otherwise).  Typical PFAL fresh air
    #   0.5-2 room volumes/h (100-400 m3/h on a 200 m3 room).
    erv_sensible_eff: float = 0.7
    #   Sensible (dry-bulb) recovery effectiveness [0, 0.95].  Fixed-
    #   effectiveness model per ASHRAE Handbook HVAC Systems and Equipment
    #   Ch. 26; certified cores rate 0.5-0.85 (AHRI 1060 / EN 13141).
    #   Net fresh-air sensible load = (1 - eps_s)*m_v*cp*(T_ext - T_z).
    erv_latent_eff: float = 0.0
    #   Latent (moisture) recovery effectiveness [0, 0.95].  0 (default) =
    #   sensible-only HRV (plate exchanger); > 0 = enthalpy ERV (membrane /
    #   enthalpy wheel, typically 0.45-0.75) that also recovers moisture:
    #   net fresh-air latent load = (1 - eps_l)*m_v*(W_ext - W_z)*h_fg.


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
    cop_soft_cap: bool = False
    #   R34/H1a: cooling-COP soft ceiling (carnot mode only).  true =
    #   COP_cool = min(carnot_cop, 5.25 - 0.16*max(lift-21, 0)), lift =
    #   T_cond - T_evap (K), replacing the flat 4.5 ceiling that pinned
    #   ~25% of 609 cooling hours (B3 conservative at mild lift / B7
    #   optimistic annual weighted COP).  Calibrated on the GB 21455-2019
    #   IPLV(C) four-point weights (0.023/0.415/0.461/0.101 at
    #   100/75/50/25%): flat 5.25 ceiling below the A25/A27 lift (21 K)
    #   inside the 5.0-5.5 mild band, converging 0.16/K to 3.65 at the
    #   A35/A27 lift (31 K; Carnot 3.30 still binds there).  false
    #   (default) = flat 4.5 cap, bit-identical to every pre-R34 baseline.
    crankcase_heat_w: float = 0.0
    #   R34/H2: crankcase-heater power (W, typical 30-80).  Drawn only
    #   while the compressor is OFF (winter off-cycle protection) and
    #   counted BOTH in HVAC electricity and as a room heat gain.
    #   0.0 (default) = no heater, bit-identical.
    defrost: str = "off"  # R34/H3: off | timed | on_demand
    #   Heat-pump defrost (heat_mode=heat_pump, heating mode, T_ext below
    #   defrost_threshold_c only; 609 Shanghai heating hours = 0 so the
    #   default path never fires).  "timed" = discrete reverse-cycle events
    #   every defrost_interval_min of frost-condition heating for
    #   defrost_duration_min: heat delivery stops (COP x 0), the DOE-2.1E
    #   reverse-cycle load is drawn from the room, compressor at rated
    #   draw; annualised multiplier = duration/interval.  "on_demand" =
    #   DOE-2.1E continuous frost factors: T_coil = 0.82*T_ext - 8.589,
    #   d_omega = max(1e-6, W_out - W_sat(T_coil)), t_frac =
    #   1/(1+0.01446/d_omega), capacity x 0.875*(1-t_frac), power x
    #   0.954*(1-t_frac), averaged reverse-cycle load
    #   0.01*t_frac*(7.222-T_ext)*(Q_rated/1.01667).
    defrost_threshold_c: float = 4.0  # outdoor temp below which frost applies (°C); DOE-2.1E timed threshold
    defrost_interval_min: float = 90.0  # timed defrost cycle interval (min); typical 60-120
    defrost_duration_min: float = 5.0  # timed defrost event duration (min); typical 3-10
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
    smer_curve: bool = False
    #   R33/B10: operating-condition SMER correction.  true = each step applies
    #   SMER_eff = smer × clamp(0.25 + 0.75×(W_z/W_nom)^0.7, 0.25, 1.0), with
    #   W_z = room humidity ratio and W_nom anchored at the DOE 10 CFR 430
    #   Appendix X1 dehumidifier test condition (26.7 °C / 60 % RH, ≈0.01318
    #   kg/kg, computed via vfed/physics/psychrometrics.py).  Moisture
    #   capacity is unchanged; the compressor power for the same condensate
    #   rises as 1/SMER_eff (dry-air rooms: 15 °C/40 % RH → factor ≈0.59 ≈
    #   1.7× power vs the constant-SMER assumption).  Applies to BOTH control
    #   modes (vfd stacks with the DOE part-load speed curve; on_off gets the
    #   air factor at full speed).  false (default) = constant rated SMER,
    #   bit-identical to the pre-R33 baselines.
    smer_map: bool = False
    #   R34/W2-C (D1, layerB top-1 upgrade): EnergyPlus
    #   ZoneHVAC:Dehumidifier:DX isomorphic operating-condition map.  true =
    #   two normalized biquadratic curves of the inlet air state (T_z, RH_z),
    #   coefficients = the E+ reference curves (v9.5.0
    #   SingleFamilyHouse_HP_Slab_Dehumidification.idf, NREL fit to the DOE
    #   10 CFR 430 Appendix X1 test matrix), both exactly 1.0 at the rating
    #   point 26.7 °C / 60 % RH, inputs clamped to the E+ curve domain
    #   [21, 32.22] °C × [40, 80] % RH:
    #     capacity  M = M_nom × WR(T_z, RH_z)   (capacity also derated)
    #     SMER_eff  = smer × EF(T_z, RH_z)      (vfd: × part-load speed mod)
    #     P_comp    = M × 3.6e6 / SMER_eff      (same P2-5 compressor basis)
    #   Corner behaviour: 15 °C/40 % RH → wr 0.349 / ef 0.617 (SMER_eff =
    #   0.617×rated, inside the B10 fix band); 21 °C/68 % RH → ef 1.124
    #   (wetter-than-rated air may beat the rating: anchor, not cap, per E+).
    #   Mutually exclusive with smer_curve (same DOE dry-air physics, two
    #   functional forms).  false (default) = bit-identical to the pre-R34
    #   baselines.
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
    C_pv: Optional[float] = None  # 光伏系统单价 (USD 基准缺省 500/kWp)——是单价不是容量!
    #   P0-1: 旧默认 110 低于市场 4-8 倍, 已提到市场区间: 中国工商业分布式
    #   2025 组件+安装 ≈ 3-3.5 RMB/W ≈ 3000-3500 RMB/kWp ≈ 420-490 USD/kWp
    #   (按 7.2 汇率), 取整 500 (USD 锚定)。
    #   R26 哨兵: None (缺省/null) = USD 基准 500/kWp × exchange_rate 自动
    #   换算 (from_dict 物化); 显式值 = 项目货币字面值, 绝不换算。
    #   仅作 capital 块缺省时的 legacy 回退计价 (sweep._total_capital)。
    degradation: float = 0.004  # 年衰减率 (1/年, 0.4 %/年)
    capital: CapitalCostConfig = field(default_factory=CapitalCostConfig)


@dataclass
class BatteryConfig:
    c_energy: Optional[float] = None  # 电池储能单价 (USD 基准缺省 220/kWh)——这是"单价"不是容量!
    #   R26 哨兵: None (缺省/null) = USD 基准 220/kWh × exchange_rate 自动
    #   换算 (from_dict 物化); 显式值 = 项目货币字面值, 绝不换算。
    #   容量见顶层 battery_kwh (kWh)
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

    R26 (currency engine): both fields are USD-baseline defaults behind the
    ``None`` sentinel (same pattern as ``CapitalCostConfig.cost``, F2).
    Omitting a field (or writing ``null``) selects the built-in USD-baseline
    default (flat 0.10/kWh, export 0.05/kWh), which ``from_dict``
    materializes into the project currency via ``exchange_rate``; an
    explicit value is a literal in the project currency and is never
    converted.  The 24-length / numeric validation applies to explicit
    lists only (there is nothing to validate on the sentinel).
    """

    hourly_prices: Optional[List[float]] = None  # None -> USD baseline [0.10]*24 x exchange_rate
    export_price: Optional[float] = None  # None -> USD baseline 0.05 x exchange_rate


@dataclass
class DesignSpace:
    # dict[param_name, [min, max, step]]
    # Parameters NOT listed here use their fixed value from the project.
    # Example: {"ppfd_target": [100, 300, 25], "pv_area": [0, 200, 10]}
    # key 名 = 本模块 HARD_LIMITS/PARAM_PATH_MAP 注册表的合法键
    # (sweep.py 自本模块 import; user12 T1 迁移后单一事实源在此):
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
    # P1-7: internal provenance flag -- True when at least one of the three
    # USD-baseline default prices (labor / misc / water) is in effect, i.e.
    # the source dict/YAML had no 'opex' section or left one of them
    # unspecified.  Set only by ``from_dict``; never emitted by ``to_dict``
    # (a user YAML that spells it out is rejected).  Consumed by the engine's
    # OPEX-dominance warning.
    opex_was_defaulted: bool = False
    # R26: internal provenance -- which opex fields the source YAML spelled
    # out with a non-null value.  ``to_dict`` emits exactly these keys (a
    # defaulted field re-derives from its USD-baseline default on reload);
    # an empty tuple drops the whole section.  Set only by ``from_dict``;
    # never emitted / rejected as a user key like ``opex_was_defaulted``.
    opex_explicit_keys: Tuple[str, ...] = ()
    interest_rate: float = 0.06  # annual discount rate (fraction)
    currency: str = "USD"  # monetary unit for all costs
    exchange_rate: float = 1.0  # project-currency units per 1 USD (7.2 = CNY)
    #   R26: scales the built-in USD-baseline DEFAULT prices (tariff 0.10,
    #   export 0.05, PV 500/kWp, battery 220/kWh, opex labor/misc/water,
    #   rate_per_watt 1.0) into the project currency.  Values written
    #   explicitly in the YAML are never converted.  User-set for
    #   reproducibility (offline); 'vfed design fx' shows a reference
    #   snapshot.

    # ── sizing decisions (energy system) ──
    pv_area_m2: float = 0.0  # PV array area (m²); 0 = skip energy system
    battery_kwh: float = 0.0  # 电池能量容量 (kWh); 0 = 无电池。单价见 battery.c_energy (项目货币/kWh)

    # ---- (de)serialisation ---------------------------------------------
    def to_dict(self) -> dict:
        # P1-7: ``opex_was_defaulted`` is runtime provenance, not schema --
        # strip it so serialized projects never carry an internal key (and
        # ``from_dict``'s internal-key rejection cannot fire on a
        # roundtrip).
        d = asdict(self)
        d.pop("opex_was_defaulted", None)
        # R26: ``opex_explicit_keys`` is internal in the same way.  The opex
        # section is emitted as EXACTLY the keys the source YAML spelled out
        # (a defaulted field re-derives from its USD-baseline default on
        # reload, keeping the roundtrip lossless even for a partially
        # explicit section); with nothing spelled out the whole section is
        # dropped so ``from_dict`` re-derives the defaulted flag.
        d.pop("opex_explicit_keys", None)
        _opex = d.get("opex")
        if isinstance(_opex, dict):
            _keep = set(self.opex_explicit_keys)
            for _k in list(_opex):
                if _k not in _keep:
                    _opex.pop(_k, None)
            if not _opex:
                d.pop("opex", None)
        # F2 (round 21): a None capital cost means "unspecified -> legacy
        # fallback".  Serializing it as ``cost: null`` would roundtrip as the
        # same None, but omitting the key keeps templates clean and makes the
        # serialized YAML say exactly what from_dict re-derives (roundtrip
        # stays lossless either way; explicit 0.0 / positive values are kept).
        # R26: the same omission rule now covers every None sentinel that
        # from_dict would re-materialize (rate_per_watt, tariff prices).
        for _sec in ("hvac", "deh", "led", "pv", "battery"):
            _cap = d.get(_sec, {}).get("capital")
            if isinstance(_cap, dict):
                if _cap.get("cost") is None:
                    _cap.pop("cost", None)
                if _cap.get("rate_per_watt") is None:
                    _cap.pop("rate_per_watt", None)
        for _key in ("equipment_capital", "envelope_capital", "pump_capital"):
            _cap = d.get(_key)
            if isinstance(_cap, dict):
                if _cap.get("cost") is None:
                    _cap.pop("cost", None)
                if _cap.get("rate_per_watt") is None:
                    _cap.pop("rate_per_watt", None)
        # R26: sentinel legacy unit prices -- omitted key == USD baseline
        # (re-materialized on reload); explicit values are kept verbatim.
        if d.get("pv", {}).get("C_pv") is None:
            d.get("pv", {}).pop("C_pv", None)
        if d.get("battery", {}).get("c_energy") is None:
            d.get("battery", {}).pop("c_energy", None)
        _tar = d.get("tariff")
        if isinstance(_tar, dict):
            if _tar.get("hourly_prices") is None:
                _tar.pop("hourly_prices", None)
            if _tar.get("export_price") is None:
                _tar.pop("export_price", None)
            if not _tar:
                d.pop("tariff", None)
        return d

    def save(self, path) -> None:
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(self.to_dict(), f, sort_keys=False, allow_unicode=True)

    @classmethod
    def from_dict(cls, d: dict) -> "DesignProject":
        # P1-7: 'opex_was_defaulted' is an internal flag that from_dict sets
        # itself (raw dict has no 'opex' key).  R26 adds the sibling
        # 'opex_explicit_keys' provenance.  Neither is ever a user config
        # key -- reject with a dedicated message instead of the generic
        # unknown-key error so the fix is obvious.
        for _internal in ("opex_was_defaulted", "opex_explicit_keys"):
            if _internal in d:
                raise ValueError(
                    f"'{_internal}' is an internal VFED field, not a user "
                    f"config key: it is derived automatically from the YAML. "
                    f"Remove it; to take control of OPEX, write an explicit "
                    f"'opex' section instead."
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
            # R26: an explicit ``hourly_prices: null`` is the unspecified
            # sentinel (same rule as capital ``cost: null``, F2) -- only an
            # actual list is shape-validated here; the sentinel is
            # materialized from the USD baseline after construction.
            if "hourly_prices" in d and d["hourly_prices"] is not None:
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
                        # user12 T4: name the most common cause -- an old
                        # 'vfed design new' template wrote placeholder
                        # canonical keys (e.g. M_deh_nom: 0.0) next to the
                        # datasheet key the user added from the tutorial.
                        raise ValueError(
                            f"Ambiguous '{yaml_path}' config: both '{alias}' "
                            f"and '{canon}' are given with different values "
                            f"({out[alias]!r} vs {out[canon]!r}). "
                            f"Set only one of them. Common cause: templates "
                            f"generated by older 'vfed design new' versions "
                            f"kept a placeholder '{canon}' line (e.g. its "
                            f"class default) next to the '{alias}' you added "
                            f"-- delete the placeholder line or make both "
                            f"values equal (current templates omit "
                            f"placeholders, so you can just add keys)."
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
        # R33/B10: smer_curve is a boolean switch — YAML strings like "true"
        # or the numbers 0/1 previously would coerce or mislead; reject at
        # load time (same pattern as battery.allow_grid_charging).
        _smer_curve = deh_cfg.get("smer_curve")
        if _smer_curve is not None and not isinstance(_smer_curve, bool):
            raise ValueError(
                f"deh.smer_curve must be a boolean (true/false), got "
                f"{type(_smer_curve).__name__}: {_smer_curve!r}. true applies the "
                f"DOE rating-point SMER correction (SMER_eff = smer * clamp(0.25 + "
                f"0.75*(W_z/W_nom)^0.7, 0.25, 1.0), W_nom at 26.7 C / 60 % RH)."
            )
        # R34/W2-C: smer_map is a boolean switch (same pattern) and is
        # MUTUALLY EXCLUSIVE with smer_curve -- both are air-side SMER
        # corrections anchored at the same DOE rating point; enabling both
        # would double-count the dry-air penalty.
        _smer_map = deh_cfg.get("smer_map")
        if _smer_map is not None and not isinstance(_smer_map, bool):
            raise ValueError(
                f"deh.smer_map must be a boolean (true/false), got "
                f"{type(_smer_map).__name__}: {_smer_map!r}. true applies the "
                f"EnergyPlus Dehumidifier:DX (T, RH) biquadratic maps "
                f"(M = M_nom*WR(T,RH), SMER_eff = smer*EF(T,RH), both 1.0 at "
                f"26.7 C / 60 % RH)."
            )
        if _smer_map is True and _smer_curve is True:
            raise ValueError(
                f"deh.smer_map and deh.smer_curve are mutually exclusive "
                f"(both are DOE rating-point air-side SMER corrections; "
                f"enabling both would double-count the dry-air penalty). "
                f"Enable exactly one -- smer_map is the EnergyPlus "
                f"Dehumidifier:DX (T, RH) biquadratic upgrade."
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
        # R34/H1a: cop_soft_cap is a boolean switch -- YAML strings like
        # "true" or the numbers 0/1 must not coerce (same pattern as
        # deh.smer_curve, battery.allow_grid_charging).
        _cop_soft_cap = hvac_cfg.get("cop_soft_cap")
        if _cop_soft_cap is not None and not isinstance(_cop_soft_cap, bool):
            raise ValueError(
                f"hvac.cop_soft_cap must be a boolean (true/false), got "
                f"{type(_cop_soft_cap).__name__}: {_cop_soft_cap!r}. true "
                f"applies the lift-dependent cooling-COP ceiling "
                f"min(carnot, 5.25 - 0.16*max(lift-21, 0)) (GB 21455-2019 "
                f"IPLV-calibrated, carnot mode only)."
            )
        # R34/H2: crankcase heater must be a sane wattage (real units
        # 30-80 W; a value beyond ~1 kW is a unit typo, not a heater).
        _crankcase = hvac_cfg.get("crankcase_heat_w")
        if _crankcase is not None and (
            isinstance(_crankcase, bool) or not isinstance(_crankcase, (int, float))
        ):
            raise ValueError(
                f"hvac.crankcase_heat_w must be a number (W), got "
                f"{type(_crankcase).__name__}: {_crankcase!r}"
            )
        if _crankcase is not None and not (0.0 <= float(_crankcase) <= 1000.0):
            raise ValueError(
                f"hvac.crankcase_heat_w must be in [0, 1000] W (typical "
                f"30-80 W crankcase heaters), got {_crankcase}"
            )
        # R34/H3: defrost enum + parameter guards.  An unknown mode must
        # fail fast (no silent fallback), defrost on a resistive unit is a
        # config contradiction (no outdoor coil to frost), and
        # duration >= interval would trap the unit in permanent defrost.
        _defrost = hvac_cfg.get("defrost")
        if _defrost is not None and _defrost not in ("off", "timed", "on_demand"):
            raise ValueError(
                f"hvac.defrost must be one of off|timed|on_demand, got "
                f"{_defrost!r}. 'timed' = discrete reverse-cycle events "
                f"(defrost_interval_min/defrost_duration_min); 'on_demand' "
                f"= DOE-2.1E continuous frost factors; 'off' (default) = "
                f"no frost derating."
            )
        _heat_mode_cfg = hvac_cfg.get("heat_mode") or HVACConfig.heat_mode
        if _defrost not in (None, "off") and _heat_mode_cfg != "heat_pump":
            raise ValueError(
                f"hvac.defrost='{_defrost}' models heat-pump coil frost but "
                f"hvac.heat_mode='{_heat_mode_cfg}'; set heat_mode=heat_pump "
                f"or defrost=off."
            )
        _df_thr = hvac_cfg.get("defrost_threshold_c")
        if _df_thr is not None and (
            isinstance(_df_thr, bool) or not isinstance(_df_thr, (int, float))
        ):
            raise ValueError(
                f"hvac.defrost_threshold_c must be a number (degC), got "
                f"{type(_df_thr).__name__}: {_df_thr!r}"
            )
        if _df_thr is not None and not (-30.0 <= float(_df_thr) <= 10.0):
            raise ValueError(
                f"hvac.defrost_threshold_c must be in [-30, 10] degC (frost "
                f"physics; DOE-2.1E timed threshold 4), got {_df_thr}"
            )
        _df_int = hvac_cfg.get("defrost_interval_min")
        _df_dur = hvac_cfg.get("defrost_duration_min")
        for _fname, _fval in (
            ("defrost_interval_min", _df_int),
            ("defrost_duration_min", _df_dur),
        ):
            if _fval is not None and (
                isinstance(_fval, bool) or not isinstance(_fval, (int, float))
            ):
                raise ValueError(
                    f"hvac.{_fname} must be a number (min), got "
                    f"{type(_fval).__name__}: {_fval!r}"
                )
        if _df_int is not None and float(_df_int) <= 0.0:
            raise ValueError(
                f"hvac.defrost_interval_min must be > 0 min, got {_df_int}"
            )
        if _df_dur is not None and float(_df_dur) <= 0.0:
            raise ValueError(
                f"hvac.defrost_duration_min must be > 0 min, got {_df_dur}"
            )
        _df_int_eff = float(_df_int) if _df_int is not None else HVACConfig.defrost_interval_min
        _df_dur_eff = float(_df_dur) if _df_dur is not None else HVACConfig.defrost_duration_min
        if _df_dur_eff >= _df_int_eff:
            raise ValueError(
                f"hvac.defrost_duration_min ({_df_dur_eff}) must be < "
                f"hvac.defrost_interval_min ({_df_int_eff}) or the unit "
                f"never leaves defrost."
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
        # Round 22: weather provider enum + GHI bias-correction band (E001
        # at load time; the defaults themselves are always valid).
        validate_weather_provider(site_cfg.get("weather_provider", "open-meteo"))
        validate_ghi_scale(site_cfg.get("ghi_scale", 1.0))

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

        # ── hard limits: scalar fields (E001, unified with sweep's range
        # guard).  Enforced here so EVERY entry point that loads a project
        # (validate / evaluate / sweep) rejects out-of-band values before any
        # simulation -- e.g. led.ppfd_target: 9999 used to run to completion
        # on the single-point path and produce a meaningless result.  Bands
        # come from HARD_LIMITS (same table sweep ranges are checked against);
        # missing keys and non-numeric values stay the business of the
        # section-specific type guards above.
        def _hard_limit_guard(param, yaml_path, value):
            lo, hi = HARD_LIMITS[param]
            if lo <= value <= hi:
                return
            raise ValueError(
                f"{yaml_path} = {value} is outside the hard limit "
                f"[{lo}, {hi}] -- clamp it to the valid band."
            )

        for _param, (_section, _field) in PARAM_PATH_MAP.items():
            _sec_data = d.get(_section)
            if not isinstance(_sec_data, dict) or _field not in _sec_data:
                continue
            _val = _sec_data[_field]
            if isinstance(_val, bool) or not isinstance(_val, (int, float)):
                continue  # type errors are reported by the guards above
            _hard_limit_guard(_param, f"{_section}.{_field}", _val)
        for _param, _field in PARAM_TOPLEVEL_MAP.items():
            if _field not in d:
                continue
            _val = d[_field]
            if isinstance(_val, bool) or not isinstance(_val, (int, float)):
                continue
            _hard_limit_guard(_param, _field, _val)

        # P1-7: flag = at least one of the three USD-baseline default prices
        # (labor / misc / water) is in effect -- the opex section was absent
        # OR one of them was left unspecified (R26 sentinel semantics:
        # "warn when a default was used").  Pure provenance -- never touches
        # any numeric result.  The sibling tuple records which fields the
        # YAML DID spell out, so to_dict can roundtrip a partially explicit
        # section without losing the explicit values.
        _opex_sub = sub(OpexConfig, d.get("opex", {}), yaml_path="opex")
        _opex_explicit_keys = tuple(k for k, v in _opex_sub.items() if v is not None)
        _opex_was_defaulted = ("opex" not in d) or any(
            _opex_sub.get(k) is None
            for k in ("labor_cost_per_year", "misc_opex_per_year", "water_cost_per_m3")
        )

        # ── R28: 2R2C wall mass network switch -- fail-fast config checks
        # (E001 style).  Physics-level re-validation also lives in
        # Envelope.__init__; this block gives the YAML-facing error messages. ──
        _env_cfg = EnvelopeConfig(
            **sub(EnvelopeConfig, d.get("envelope", {}), yaml_path="envelope")
        )
        if _env_cfg.wall_rc_nodes not in (0, 2, 3):
            raise ValueError(
                f"envelope.wall_rc_nodes = {_env_cfg.wall_rc_nodes!r} is invalid -- "
                f"use 0 (single node, legacy default), 2 (2R2C wall mass network) "
                f"or 3 (2R3C wall network with surface node)."
            )
        if not (0.0 <= _env_cfg.solar_mass_fraction <= 1.0):
            raise ValueError(
                "envelope.solar_mass_fraction must be within [0, 1] "
                f"(got {_env_cfg.solar_mass_fraction})."
            )
        if _env_cfg.solar_mass_fraction > 0.0 and (
            _env_cfg.wall_rc_nodes == 0 and _env_cfg.wall_fd_nodes == 0
        ):
            raise ValueError(
                "envelope.solar_mass_fraction > 0 requires wall_rc_nodes=2, 3 "
                "or wall_fd_nodes > 0 "
                "-- with the legacy single-node envelope there is no mass/surface "
                "node to absorb the solar source (got "
                f"solar_mass_fraction={_env_cfg.solar_mass_fraction})."
            )
        if _env_cfg.wall_rc_nodes == 2:
            if _env_cfg.C_mass <= 0.0:
                raise ValueError(
                    "envelope.C_mass must be > 0 Wh/K when wall_rc_nodes=2 "
                    f"(got {_env_cfg.C_mass})."
                )
            if _env_cfg.g_im <= 0.0:
                raise ValueError(
                    "envelope.g_im must be > 0 W/K when wall_rc_nodes=2 "
                    f"(got {_env_cfg.g_im})."
                )
            if _env_cfg.g_em < 0.0:
                raise ValueError(
                    "envelope.g_em must be >= 0 W/K when wall_rc_nodes=2 "
                    f"(got {_env_cfg.g_em}; 0 = pure internal mass)."
                )
        if _env_cfg.wall_rc_nodes == 3:
            if _env_cfg.C_mass <= 0.0:
                raise ValueError(
                    "envelope.C_mass must be > 0 Wh/K when wall_rc_nodes=3 "
                    f"(got {_env_cfg.C_mass})."
                )
            if _env_cfg.g_em < 0.0:
                raise ValueError(
                    "envelope.g_em must be >= 0 W/K when wall_rc_nodes=3 "
                    f"(got {_env_cfg.g_em}; 0 = pure internal mass)."
                )
            if _env_cfg.C_surface <= 0.0:
                raise ValueError(
                    "envelope.C_surface must be > 0 Wh/K when wall_rc_nodes=3 "
                    f"(got {_env_cfg.C_surface})."
                )
            if _env_cfg.g_sa <= 0.0:
                raise ValueError(
                    "envelope.g_sa must be > 0 W/K when wall_rc_nodes=3 "
                    f"(got {_env_cfg.g_sa})."
                )
            if _env_cfg.g_sm <= 0.0:
                raise ValueError(
                    "envelope.g_sm must be > 0 W/K when wall_rc_nodes=3 "
                    f"(got {_env_cfg.g_sm})."
                )

        # ── R28 step 6: 1-D finite-difference wall -- fail-fast config
        # checks (E001 style).  Physics-level re-validation also lives in
        # Envelope.__init__; this block gives the YAML-facing messages. ──
        if _env_cfg.wall_fd_nodes != 0 and _env_cfg.wall_rc_nodes != 0:
            raise ValueError(
                "envelope.wall_fd_nodes and envelope.wall_rc_nodes are "
                "mutually exclusive wall models -- set one of them to 0 "
                f"(got wall_fd_nodes={_env_cfg.wall_fd_nodes}, "
                f"wall_rc_nodes={_env_cfg.wall_rc_nodes})."
            )
        if _env_cfg.wall_fd_nodes != 0:
            _fd = _env_cfg.wall_fd_nodes
            if isinstance(_fd, bool) or not isinstance(_fd, int) or not (10 <= _fd <= 100):
                raise ValueError(
                    "envelope.wall_fd_nodes must be an int in [10, 100] when "
                    f"enabled (got {_fd!r}); 0 disables the FD wall."
                )
            _layers = _env_cfg.wall_layers
            if not isinstance(_layers, (list, tuple)) or len(_layers) == 0:
                raise ValueError(
                    "envelope.wall_layers must be a non-empty list of "
                    "(thickness_m, k_W_mK, rho_kg_m3, c_J_kgK) tuples when "
                    f"wall_fd_nodes > 0 (got {_layers!r})."
                )
            if len(_layers) > _fd:
                raise ValueError(
                    "envelope.wall_fd_nodes must be >= the number of wall "
                    f"layers (got {_fd} nodes for {len(_layers)} layers)."
                )
            for li, lay in enumerate(_layers):
                if not isinstance(lay, (list, tuple)) or len(lay) != 4:
                    raise ValueError(
                        f"envelope.wall_layers[{li}] must be "
                        f"(thickness_m, k, rho, c), got {lay!r}."
                    )
                d_i, k_i, rho_i, c_i = (float(v) for v in lay)
                for name, v in (
                    ("thickness_m", d_i),
                    ("k_W_mK", k_i),
                    ("rho_kg_m3", rho_i),
                    ("c_J_kgK", c_i),
                ):
                    if not (v > 0.0):
                        raise ValueError(
                            f"envelope.wall_layers[{li}].{name} must be > 0 "
                            f"(got {v})."
                        )
            if not (_env_cfg.wall_area_m2 > 0.0):
                raise ValueError(
                    "envelope.wall_area_m2 must be > 0 m2 when "
                    f"wall_fd_nodes > 0 (got {_env_cfg.wall_area_m2})."
                )
            if not (_env_cfg.h_ext_wm2 > 0.0):
                raise ValueError(
                    "envelope.h_ext_wm2 must be > 0 W/m2K when "
                    f"wall_fd_nodes > 0 (got {_env_cfg.h_ext_wm2})."
                )
            if not (_env_cfg.h_int_c_wm2 > 0.0):
                raise ValueError(
                    "envelope.h_int_c_wm2 must be > 0 W/m2K when "
                    f"wall_fd_nodes > 0 (got {_env_cfg.h_int_c_wm2})."
                )
            if not (0.0 <= _env_cfg.wall_solar_abs <= 1.0):
                raise ValueError(
                    "envelope.wall_solar_abs must be within [0, 1] "
                    f"(got {_env_cfg.wall_solar_abs})."
                )
            if _env_cfg.C_mass <= 0.0:
                raise ValueError(
                    "envelope.C_mass must be > 0 Wh/K when wall_fd_nodes > 0 "
                    f"(the FD inner surface radiates to the internal mass "
                    f"node; got {_env_cfg.C_mass})."
                )
            if _env_cfg.g_sm <= 0.0:
                raise ValueError(
                    "envelope.g_sm must be > 0 W/K when wall_fd_nodes > 0 "
                    f"(surface <-> internal-mass coupling; got "
                    f"{_env_cfg.g_sm})."
                )
            for _name, _v in (
                ("g_em", _env_cfg.g_em),
                ("g_im", _env_cfg.g_im),
                ("C_surface", _env_cfg.C_surface),
                ("g_sa", _env_cfg.g_sa),
            ):
                if _v != 0.0:
                    raise ValueError(
                        f"envelope.{_name} must be 0 when wall_fd_nodes > 0 "
                        f"(the FD wall replaces the RC network; got {_v})."
                    )
        elif (
            _env_cfg.wall_layers
            or _env_cfg.wall_area_m2 != 0.0
            or _env_cfg.h_ext_wm2 != 0.0
            or _env_cfg.wall_solar_abs != 0.0
            or _env_cfg.h_int_c_wm2 != 0.0
        ):
            raise ValueError(
                "envelope.wall_layers / wall_area_m2 / h_ext_wm2 / "
                "wall_solar_abs / h_int_c_wm2 require wall_fd_nodes > 0 -- "
                "they would otherwise be silently ignored "
                f"(wall_fd_nodes={_env_cfg.wall_fd_nodes})."
            )

        # ── R34/W3-E (H7): ERV/HRV mechanical fresh-air guards ──
        # Same rules as the Envelope constructor (defence in depth): boolean
        # switch, flow>0 iff enabled (an enabled ERV with no flow is a config
        # error; a positive flow with the switch off would be silently
        # ignored), effectiveness bands [0, 0.95].
        _erv_enabled = _env_cfg.erv_enabled
        if not isinstance(_erv_enabled, bool):
            raise ValueError(
                f"envelope.erv_enabled must be a boolean (true/false), got "
                f"{type(_erv_enabled).__name__}: {_erv_enabled!r}. true turns "
                f"on the mechanical fresh-air channel with ERV/HRV heat "
                f"recovery (erv_flow_m3h + erv_sensible_eff/erv_latent_eff)."
            )
        _erv_flow = _env_cfg.erv_flow_m3h
        if isinstance(_erv_flow, bool) or not isinstance(_erv_flow, (int, float)):
            raise ValueError(
                f"envelope.erv_flow_m3h must be a number (m3/h), got "
                f"{type(_erv_flow).__name__}: {_erv_flow!r}"
            )
        if float(_erv_flow) < 0.0:
            raise ValueError(
                f"envelope.erv_flow_m3h must be >= 0 m3/h, got {_erv_flow}"
            )
        for _eff_name in ("erv_sensible_eff", "erv_latent_eff"):
            _eff_val = getattr(_env_cfg, _eff_name)
            if isinstance(_eff_val, bool) or not isinstance(_eff_val, (int, float)):
                raise ValueError(
                    f"envelope.{_eff_name} must be a number (recovery "
                    f"effectiveness), got {type(_eff_val).__name__}: {_eff_val!r}"
                )
            if not (0.0 <= float(_eff_val) <= 0.95):
                raise ValueError(
                    f"envelope.{_eff_name} must be within [0, 0.95] "
                    f"(certified core band 0.5-0.85 sensible / 0.45-0.75 "
                    f"enthalpy), got {_eff_val}"
                )
        if _erv_enabled and not (float(_erv_flow) > 0.0):
            raise ValueError(
                f"envelope.erv_enabled=true requires erv_flow_m3h > 0 m3/h "
                f"(got {_erv_flow}); an enabled ERV with no flow is a config "
                f"error, not a zero-flow machine."
            )
        if not _erv_enabled and float(_erv_flow) > 0.0:
            raise ValueError(
                f"envelope.erv_flow_m3h > 0 ({_erv_flow}) requires "
                f"envelope.erv_enabled=true -- otherwise the mechanical "
                f"fresh air is silently ignored. See also envelope.ach for "
                f"uncontrolled infiltration (no heat recovery)."
            )

        project = cls(
            name=d.get("name", "unnamed"),
            site=SiteConfig(**site_cfg),
            envelope=_env_cfg,
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
            opex=OpexConfig(**_opex_sub),
            opex_was_defaulted=_opex_was_defaulted,
            opex_explicit_keys=_opex_explicit_keys,
            interest_rate=d.get("interest_rate", 0.06),
            currency=d.get("currency", "USD"),
            exchange_rate=d.get("exchange_rate", 1.0),
            pv_area_m2=d.get("pv_area_m2", 0.0),
            battery_kwh=d.get("battery_kwh", 0.0),
        )

        # ── R26 currency engine: materialize USD-baseline default prices ──
        # Every None sentinel (omitted key / explicit null) becomes the
        # built-in USD-baseline default converted into the project currency
        # (fx.usd_base_to_project).  Explicit values are NEVER touched:
        # they are already literals in the project currency.  USD projects
        # (or exchange_rate == 1.0) get the raw constants back, so the
        # bundled baselines stay bitwise identical.
        _cur = d.get("currency", "USD") or "USD"
        _fx = d.get("exchange_rate", 1.0)
        if project.tariff.hourly_prices is None:
            project.tariff.hourly_prices = [usd_base_to_project(USD_TARIFF, _cur, _fx)] * 24
        if project.tariff.export_price is None:
            project.tariff.export_price = usd_base_to_project(USD_EXPORT, _cur, _fx)
        for _fname, _base in (
            ("labor_cost_per_year", USD_LABOR),
            ("misc_opex_per_year", USD_MISC),
            ("water_cost_per_m3", USD_WATER),
        ):
            if getattr(project.opex, _fname) is None:
                setattr(project.opex, _fname, usd_base_to_project(_base, _cur, _fx))
        # Legacy unit prices (pv.C_pv / battery.c_energy): same sentinel rule.
        if project.pv.C_pv is None:
            project.pv.C_pv = usd_base_to_project(USD_C_PV, _cur, _fx)
        if project.battery.c_energy is None:
            project.battery.c_energy = usd_base_to_project(USD_C_ENERGY, _cur, _fx)
        for _cap in (
            project.led.capital,
            project.hvac.capital,
            project.deh.capital,
            project.pv.capital,
            project.battery.capital,
            project.equipment_capital,
            project.envelope_capital,
            project.pump_capital,
        ):
            if _cap.rate_per_watt is None:
                _cap.rate_per_watt = usd_base_to_project(USD_RATE_PER_WATT, _cur, _fx)
        return project

    @classmethod
    def load(cls, path) -> "DesignProject":
        with open(path, "r", encoding="utf-8") as f:
            return cls.from_dict(yaml.safe_load(f))
