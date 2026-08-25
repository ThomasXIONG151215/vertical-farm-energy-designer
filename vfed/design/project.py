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

    ``mode`` selects how the cost is computed:
        * ``"direct"`` – use ``cost`` as-is (absolute, same units as project currency).
        * ``"per_watt"`` – multiply ``rate_per_watt`` by the component's rated power
          (W for LED/HVAC/DEH, Wp for PV; for battery the unit is kWh).
    ``depreciation_years`` controls the CRF term in LCOE.
    """

    mode: str = "direct"
    cost: float = 0.0
    rate_per_watt: float = 1.0
    depreciation_years: float = 15.0


@dataclass
class OpexConfig:
    """Annual operating expenditure for the farm.

    All costs are in the project's currency unit (see ``DesignProject.currency``
    and ``exchange_rate`` for conversion).

    * ``water_cost_per_m3``: water price (irrigation + makeup).
    * ``labor_cost_per_year``: total annual labor cost.
    * ``maintenance_pct``: annual maintenance as fraction of total CAPEX.
    * ``misc_opex_per_year``: other operating costs (seeds, nutrients, etc.).
    """

    water_cost_per_m3: float = 2.0
    labor_cost_per_year: float = 30000.0
    maintenance_pct: float = 0.02
    misc_opex_per_year: float = 5000.0


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
    U_wall_A: float = 50.0  # W/K envelope conductance
    A_window: float = 0.0  # m^2 glazing
    eta_solar: float = 0.15  # solar heat gain coeff
    ach: float = 0.001  # air changes / hour (infiltration)
    #   Sealed plant factories (positive-pressure, airtight) exchange
    #   N≈0.01-0.02 h⁻¹ (Kozai 2013; WUR WPR-1315); 0.1 is a conservative
    #   leakage upper bound.  The old 0.5 (commercial-building infiltration
    #   level, ASHRAE) was 25-50x too high and dried out the room in winter.
    permeance: float = 0.0  # kg/(s per kg/kg) envelope vapour permeance
    V_room: float = 200.0  # m^3
    rho_air: float = 1.2  # kg/m^3
    cp_air: float = 1005.0  # J/(kg.K)
    C_z: float = 80000.0  # Wh/K equivalent heat capacity
    # 默认 = 房间空气主导 200 m³×1.2×1005/3600 ≈ 67 kWh/K,
    # 结构/货架/冠层水另加 ~30-130 kWh/K (P4-5 校准用 200,000)。
    # 注意: 归档数字孪生 499,597 已被判定超物理 (≈430 m³ 水当量),
    # 勿沿用。


@dataclass
class HVACConfig:
    # ── primary sizing (new, industry-standard) ──
    Q_cool_nom: float = 0.0  # nominal cooling capacity (kW); 0 → use P_rated_w or auto_size
    P_rated_max: float = 0.0  # max electrical input (kW); 0 → derived from Q_cool_nom/COP_design
    # ── legacy (kept for backward compat) ──
    P_rated_w: float = 3000.0  # rated electrical power (W), used if Q_cool_nom == 0
    cop_value: float = 4.0
    cop_mode: str = "carnot"  # carnot | constant | linear | table
    cop_k: float = 0.02
    cop_T_ref: float = 25.0
    cop_table: dict = field(default_factory=dict)  # key = T_ext(°C), value = COP
    cop_heat: float = 3.0
    heat_mode: str = "heat_pump"
    P_rated_heat_w: float = 3000.0
    deadband_c: float = 1.0  # °C thermostat hysteresis deadband
    min_on_s: float = 180.0
    min_off_s: float = 180.0
    fan_power_w: float = 70.0
    shr_BF: float = 0.15
    t_coil_drop: float = 9.0  # supply-air temperature depression T_supply = T_setpoint - t_coil_drop (real ACs ~8-12°C)
    tau_q: float = 90.0
    tau_m: float = 60.0
    shr_rh_guard: float = 65.0  # % RH; below this the AC stops latent removal (P4-1a)
    rh_guard_band: float = 3.0  # % RH blend width for the humidity guard
    coil_condense_max_gps: float = (
        0.0  # explicit coil condensate cap (g/s); 0 → auto ~5e-4·P_rated_w (P4-1b)
    )
    comp_mod_band_c: float = 2.0  # VFD proportional band (°C): m=demand/band, m=1 at ±band
    speed_curve: str = "default"  # compressor part-load curve: default | flat
    #   VFD part-load: COP rises as speed falls (50%→1.33x, 30%→1.54x);
    #   coefficients from Effsys2/KTH Madani + Szreder&Miara 2020 + Fahlén 2012.
    #   "flat" = Maxa i-290 conservative (COP≈const).
    eta_II: float = 0.35
    delta_T_evap: float = 8.0
    delta_T_cond: float = 15.0
    auto_size: bool = False
    design_T_ext: float = 35.0
    shr_design: float = 0.80
    safety_factor: float = 1.2
    capital: CapitalCostConfig = field(default_factory=CapitalCostConfig)


@dataclass
class DEHConfig:
    # ── primary sizing (new, industry-standard) ──
    M_deh_nom: float = 0.0  # nominal dehumidification (L/day); 0 → use P_ref_w or auto_size
    P_rated_max: float = 0.0  # max electrical input (kW); 0 → derived from M_deh_nom/SMER
    # ── legacy (kept for backward compat) ──
    P_ref_w: float = 2233.0
    poly_e: tuple = (1.0, 0.02, 0.0, 0.05, 0.0, 0.0)
    T_mean: float = 22.0  # °C mean room temp (DEH power poly centre)
    T_std: float = 5.0  # °C std dev (T normalisation scale)
    W_mean: float = 0.012  # kg/kg mean humidity ratio (W normalisation)
    W_std: float = 0.003  # kg/kg std dev
    smer: float = 2.0
    deadband_rh: float = (
        2.0  # % RH hysteresis stop point (was 3.0; narrowed to avoid the pband×deadband idle band)
    )
    comp_mod_band_rh: float = 6.0  # VFD proportional band (% RH): m=(RH_z−sp)/band
    #   VFD dehumidifier: SMER FALLS as speed falls (DOE 87 FR 35286 — opposite
    #   of AC; dew-point approach gets worse at low speed).  SMER(m) curve in
    #   dehumidifier.py; constant-SMER assumption valid only for m≥0.75.
    min_on_s: float = 180.0
    min_off_s: float = 180.0
    fan_power_w: float = 40.0
    tau_q: float = 90.0
    tau_m: float = 120.0
    auto_size: bool = False
    safety_factor: float = 1.2
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

    All parameters are in SI units.
    """

    c_alpha_beta: float = 0.544  # conversion efficiency (dimensionless)
    c_resp_d: float = 2.65e-7  # dark respiration at 25°C (s⁻¹)
    dry_matter_fraction: float = 0.05  # dry→fresh weight conversion (−)
    c_pl_d: float = 53.0  # light extinction per LAI (m²/kg)
    c_rad_phot: float = 1e-8  # radiation use efficiency (kg/J)
    #   CALIBRATION BASIS (C-fix, 2026-08-16): this is the Van Henten 2003
    #   tomato literature default, NOT recalibrated for 609 lettuce.  The
    #   reference calibration band (reference/van-henten/PSO_Win.py) is
    #   25-100 W/m² PAR (nominal 70); the engine feeds ppfd_target/par_factor
    #   = 87.5 W/m² (LED PAR), which falls inside that band.  Model yields
    #   ~109 kg fresh/m²/yr vs 30-60 for real PFAL lettuce (~2x high) — growth
    #   is calibrated to the greenhouse reference, not to 609 field data.
    c_co2_1: float = 5.11e-6  # CO₂ assimilation coef (m/(s·°C²))
    c_co2_2: float = 2.3e-4  # CO₂ assimilation coef (m/(s·°C))
    c_co2_3: float = 6.29e-4  # CO₂ assimilation coef (m/s)
    c_Gamma: float = 5.2e-5  # CO₂ compensation point (kg/m³)
    initial_dry_weight: float = 0.02  # initial dry biomass (kg/m²); real
    # transplant seedlings ~15-80 g/m²,
    # former 1 g/m² was an order low (P3-14)


@dataclass
class TranspirationConfig:
    method: str = "van_henten"
    #   van_henten | daily | per_plant | daily_per_period | per_plant_per_period
    #   Legacy methods (constant / vpd / stomatal) were REMOVED — the method
    #   whitelist below fails fast with a migration hint.
    daily_water_L: float = 40.0  # daily water for whole canopy (L/day), "daily" method
    plant_count: int = 0  # number of plants, "per_plant" family
    ml_per_plant_day: float = 80.0  # mL water per plant per day, "per_plant" method
    period_days: List[float] = field(default_factory=lambda: [10.0, 10.0, 10.0])
    #   stage widths (days), "*_per_period" methods; sum(period_days) must
    #   equal setpoints.crop_cycle_days (validated below).
    daily_water_L_period: List[float] = field(default_factory=lambda: [30.0, 45.0, 60.0])
    #   daily water per stage (L/day), "daily_per_period"; one entry per stage.
    ml_per_plant_day_period: List[float] = field(default_factory=lambda: [10.0, 30.0, 50.0])
    #   mL water per plant per day per stage, "per_plant_per_period".
    k_van_henten: float = 1.0e-4  # biomass-scaled gain (1/(s·kPa)), van_henten method
    stage_factor: float = 1.0
    dark_transpiration_frac: float = 0.15  # night rate / light rate, all methods
    #   Stomata stay partly open at night (Caird et al. 2007: E_night/E_day
    #   5-15%, up to 30%; Kim et al. 2004: lettuce g_night/g_day 11-39%); PFAL
    #   night VPD ≈ day VPD → take 0.10-0.15.  0.0 = zero in the dark (legacy).


@dataclass
class SetpointConfig:
    T_light: float = 22.0  # °C target during photoperiod
    T_dark: float = 18.0  # °C target during dark period
    RH: float = 65.0
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
    C_pv: float = 110.0  # 光伏组件单价 (项目货币/kWp = 0.11 货币/Wp)——是单价不是容量!
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
    interest_rate: float = 0.06  # annual discount rate (fraction)
    currency: str = "USD"  # monetary unit for all costs
    exchange_rate: float = 1.0  # conversion factor to USD (7.2 for RMB)

    # ── sizing decisions (energy system) ──
    pv_area_m2: float = 0.0  # PV array area (m²); 0 = skip energy system
    battery_kwh: float = 0.0  # 电池能量容量 (kWh); 0 = 无电池。单价见 battery.c_energy (项目货币/kWh)

    # ---- (de)serialisation ---------------------------------------------
    def to_dict(self) -> dict:
        return asdict(self)

    def save(self, path) -> None:
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(self.to_dict(), f, sort_keys=False, allow_unicode=True)

    @classmethod
    def from_dict(cls, d: dict) -> "DesignProject":
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
        sp_cfg = sub(SetpointConfig, d.get("setpoints", {}), yaml_path="setpoints")
        _require_number(
            ["T_light", "T_dark", "RH", "co2_ppm", "crop_cycle_days"], sp_cfg, "setpoints"
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
        _require_nonnegative(
            ["smer", "M_deh_nom", "P_ref_w", "P_rated_max", "comp_mod_band_rh"],
            deh_cfg,
            "deh",
        )
        rh_sp = sp_cfg.get("RH")
        if rh_sp is not None and not (0.0 <= rh_sp <= 100.0):
            raise ValueError(f"setpoints.RH must be in [0,100] %, got {rh_sp}")

        # ── PV temperature-coefficient dimension guards ──
        # alpha_sc / beta_voc are RELATIVE coefficients (/K). A value of 0.045
        # (previously shipped in the example YAMLs) is 100x the physical
        # 0.00045 and inflates annual yield ~1.7x; an absolute -0.25 V/K is
        # ~1.75x the datasheet-consistent relative value. Reject out-of-band
        # values at load time (fail-fast).
        pv_cfg = sub(PVConfig, d.get("pv", {}), yaml_path="pv", has_nested_capital=True)
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
                    f"transpiration.period_days has {len(_pd)} — one water "
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
                    f"setpoints.crop_cycle_days is {_cycle} — they must "
                    f"match so stage boundaries stay aligned with the "
                    f"harvest cycle."
                )
            if _method == "per_plant_per_period":
                _pc = transp_cfg.get("plant_count")
                if _pc is None:
                    _pc = _t_dflt.plant_count
                if _pc is not None and _pc <= 0:
                    raise ValueError(
                        f"transpiration.method='per_plant_per_period' "
                        f"requires transpiration.plant_count > 0, "
                        f"got {_pc}"
                    )
        if _method == "per_plant":
            _pc = transp_cfg.get("plant_count")
            if _pc is None:
                _pc = TranspirationConfig().plant_count
            if _pc is not None and _pc <= 0:
                raise ValueError(
                    f"transpiration.method='per_plant' requires "
                    f"transpiration.plant_count > 0, got {_pc}"
                )

        # ── LED guards (P5-6 / P5-7) ──
        led_cfg = sub(LEDConfig, d.get("led", {}), yaml_path="led", has_nested_capital=True)
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
                "site.lat/site.lon missing — falling back to Shanghai "
                "defaults (31.2, 121.5). Set them (or site.city) to avoid "
                "a silently wrong climate.",
                UserWarning,
                stacklevel=2,
            )
        if "name" not in d:
            _w.warn(
                "project 'name' missing — using 'unnamed'. Set name to "
                "identify this design in outputs.",
                UserWarning,
                stacklevel=2,
            )
        _cur = d.get("currency", "USD")
        _fx = d.get("exchange_rate", 1.0)
        if _cur and _cur != "USD" and _fx == 1.0:
            _w.warn(
                f"currency='{_cur}' with exchange_rate=1.0 treats all costs "
                f"as 1:1 to USD — set exchange_rate (e.g. 7.2 for RMB) or "
                f"keep currency='USD'.",
                UserWarning,
                stacklevel=2,
            )

        site_cfg = sub(SiteConfig, d.get("site", {}), yaml_path="site")
        _require_number(["lat", "lon", "tz_hours", "tilt", "azimuth", "year"], site_cfg, "site")

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
            battery=BatteryConfig(
                **sub(
                    BatteryConfig,
                    d.get("battery", {}),
                    yaml_path="battery",
                    has_nested_capital=True,
                )
            ),
            tariff=_tariff(d.get("tariff", {})),
            space=DesignSpace(**space_cfg),
            equipment_power_w=d.get("equipment_power_w", 0.0),
            equipment_capital=CapitalCostConfig(
                **sub(
                    CapitalCostConfig, d.get("equipment_capital", {}), yaml_path="equipment_capital"
                )
            ),
            envelope_capital=CapitalCostConfig(
                **sub(
                    CapitalCostConfig, d.get("envelope_capital", {}), yaml_path="envelope_capital"
                )
            ),
            pump_capital=CapitalCostConfig(
                **sub(CapitalCostConfig, d.get("pump_capital", {}), yaml_path="pump_capital")
            ),
            opex=OpexConfig(**sub(OpexConfig, d.get("opex", {}), yaml_path="opex")),
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
