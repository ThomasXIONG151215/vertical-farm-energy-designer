"""
Design project configuration.

A ``DesignProject`` is a fully declarative description of a vertical-farm design:
site, envelope, HVAC, dehumidifier, LED, transpiration law, control setpoints
and the PV-Battery-Grid (PVBES) system plus the design search space. It is
serialised to/from YAML for easy creation and versioning.

Strategy Modes (planned)
------------------------
Four predefined control strategy presets govern how the HVAC/DEH/LED devices
coordinate during simulation:

* ``default``      — basic thermostat + dehumidifier, standard photoperiod
* ``conservative`` — wider deadband, higher dehum setpoint, longer min cycle times
* ``progressive``  — tighter deadband, lower dehum setpoint, shorter min cycles
* ``aggressive``   — minimum deadband, aggressive dehum, shortest min cycles

These modes are applied via ``ScenarioConfig`` and **must not** be extended
beyond these four. Scenario logic is isolated from energy-optimisation code
and the data layer. Actual implementation is pending.
"""

from dataclasses import dataclass, field, asdict
from typing import Optional

import yaml

__all__ = [
    "CapitalCostConfig", "OpexConfig",
    "SiteConfig", "EnvelopeConfig", "HVACConfig", "DEHConfig", "LEDConfig",
    "VanHentenConfig",
    "TranspirationConfig", "SetpointConfig", "PVConfig", "BatteryConfig",
    "TariffConfig", "DesignSpace", "DesignProject",
]


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
    lat: float = 31.2
    lon: float = 121.5
    tz_hours: float = 8.0
    tilt: float = 20.0
    azimuth: float = 180.0
    year: int = 2025
    city: Optional[str] = None      # optional: pre-downloaded city name


@dataclass
class EnvelopeConfig:
    U_wall_A: float = 50.0       # W/K envelope conductance
    A_window: float = 0.0        # m^2 glazing
    eta_solar: float = 0.15      # solar heat gain coeff
    ach: float = 0.5             # air changes / hour (infiltration)
    permeance: float = 0.0       # kg/(s per kg/kg) envelope vapour permeance
    V_room: float = 200.0        # m^3
    rho_air: float = 1.2         # kg/m^3
    cp_air: float = 1005.0       # J/(kg.K)
    C_z: float = 80000.0         # Wh/K equivalent heat capacity


@dataclass
class HVACConfig:
    # ── primary sizing (new, industry-standard) ──
    Q_cool_nom: float = 0.0        # nominal cooling capacity (kW); 0 → use P_rated_w or auto_size
    P_rated_max: float = 0.0       # max electrical input (kW); 0 → derived from Q_cool_nom/COP_design
    # ── legacy (kept for backward compat) ──
    P_rated_w: float = 3000.0       # rated electrical power (W), used if Q_cool_nom == 0
    cop_value: float = 4.0
    cop_mode: str = "carnot"   # carnot | constant | linear | table
    cop_k: float = 0.02
    cop_T_ref: float = 25.0
    cop_table: dict = field(default_factory=dict)  # key = T_ext(°C), value = COP
    cop_heat: float = 3.0
    heat_mode: str = "heat_pump"
    P_rated_heat_w: float = 3000.0
    deadband_c: float = 1.0
    min_on_s: float = 180.0
    min_off_s: float = 180.0
    fan_power_w: float = 70.0
    shr_BF: float = 0.15
    tau_q: float = 90.0
    tau_m: float = 60.0
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
    M_deh_nom: float = 0.0         # nominal dehumidification (L/day); 0 → use P_ref_w or auto_size
    P_rated_max: float = 0.0       # max electrical input (kW); 0 → derived from M_deh_nom/SMER
    # ── legacy (kept for backward compat) ──
    P_ref_w: float = 2233.0
    poly_e: tuple = (1.0, 0.02, 0.0, 0.05, 0.0, 0.0)
    T_mean: float = 22.0
    T_std: float = 5.0
    W_mean: float = 0.012
    W_std: float = 0.003
    eta_ref: float = 0.11
    eta_max: float = 0.15
    ah_min: float = 0.0054
    ah_ref: float = 0.0099
    smer: float = 2.0
    deadband_rh: float = 3.0
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
    power_w: float = 1300.0
    light_start_hour: int = 6       # hour (0–23) when photoperiod begins
    photoperiod_hours: float = 16.0 # duration of light period (e.g., 12–20)
    heat_fraction: float = 1.0
    # auto-deduce from efficacy when auto_deduce=True (ponytail: avoids manual calc)
    auto_deduce: bool = True
    efficacy: float = 2.5       # µmol/J  (LED photon efficacy)
    ppfd_target: float = 400.0  # µmol/(m²·s)
    covered_area: float = 45.0  # m²
    spectrum: str = "white"      # white | rb_3to1 | rb_4to1 | rb_2to1
    capital: CapitalCostConfig = field(default_factory=CapitalCostConfig)


@dataclass
class VanHentenConfig:
    """Van Henten 2003 one-state carbon-balance plant growth model.

    Reference: Van Henten, E.J. (2003). Sensitivity analysis of an optimal
    control problem in greenhouse climate management. Biosystems Engineering,
    85(3), 355-364.

    All parameters are in SI units.
    """
    c_alpha_beta: float = 0.544        # conversion efficiency (dimensionless)
    c_resp_d: float = 2.65e-7          # dark respiration at 25°C (s⁻¹)
    dry_matter_fraction: float = 0.05  # dry→fresh weight conversion (−)
    c_pl_d: float = 53.0               # light extinction per LAI (m²/kg)
    c_rad_phot: float = 1e-8           # radiation use efficiency (kg/J)
    c_co2_1: float = 5.11e-6           # CO₂ assimilation coef (m/(s·°C²))
    c_co2_2: float = 2.3e-4            # CO₂ assimilation coef (m/(s·°C))
    c_co2_3: float = 6.29e-4           # CO₂ assimilation coef (m/s)
    c_Gamma: float = 5.2e-5            # CO₂ compensation point (kg/m³)
    initial_dry_weight: float = 0.001   # initial dry biomass (kg/m²)


@dataclass
class TranspirationConfig:
    method: str = "vpd"          # constant | daily | per_plant | vpd | stomatal | van_henten
    E_max_kgs: float = 1.0e-4    # peak transpiration (kg/s per m²), constant method
    daily_water_L: float = 40.0  # daily water for whole canopy (L/day), "daily" method
    plant_count: int = 0         # number of plants, "per_plant" method
    ml_per_plant_day: float = 80.0  # mL water per plant per day, "per_plant" method
    photoperiod_hours: float = 16.0  # light hours per day
    k_vpd: float = 2.0e-5        # VPD gain (kg/s per m² per kPa), vpd method
    k_van_henten: float = 4.0e-4 # biomass-scaled gain (m²/(s·kPa)), van_henten method
    stage_factor: float = 1.0
    g_stomata: float = 1.0e-3
    r_a: float = 50.0            # aerodynamic resistance (s/m) for "stomatal"
    r_n_canopy: float = 250.0    # net canopy radiation (W/m²) for "stomatal"


@dataclass
class SetpointConfig:
    T_light: float = 22.0        # °C target during photoperiod
    T_dark: float = 18.0         # °C target during dark period
    RH: float = 65.0
    co2_ppm: float = 800.0    # ambient CO₂ for plant growth model
    crop_cycle_days: float = 30.0  # harvest interval (resets canopy dry weight)


@dataclass
class PVConfig:
    eta_pv: float = 0.233
    area_to_power: float = 4.3
    N_s: int = 156
    I_sc_stc: float = 13.98
    V_oc_stc: float = 57.34
    I_mp_stc: float = 13.33
    V_mp_stc: float = 46.0
    alpha_sc: float = 0.00045
    beta_voc: float = -0.25
    NOCT: float = 45.0
    eta_inv: float = 0.97
    C_pv: float = 110.0
    degradation: float = 0.004
    maintenance: float = 0.005
    capital: CapitalCostConfig = field(default_factory=CapitalCostConfig)


@dataclass
class BatteryConfig:
    c_energy: float = 220.0
    c_rate: float = 1.0
    eta_ch: float = 0.91
    eta_dis: float = 0.91
    soc_min: float = 0.10
    soc_max: float = 0.90
    cycle_life: int = 4000
    maintenance: float = 0.01
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
    parameter_ranges: dict = field(default_factory=dict)
    timestep_s: float = 600.0
    objective: str = "lcoe"   # optimization target: "lcoe" | "kwh_per_kg_fresh" | "cost_per_kg_fresh"


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
    equipment_power_w: float = 0.0   # constant facility electrical base load (W)
    equipment_capital: CapitalCostConfig = field(default_factory=CapitalCostConfig)
    envelope_capital: CapitalCostConfig = field(default_factory=CapitalCostConfig)
    pump_capital: CapitalCostConfig = field(default_factory=CapitalCostConfig)
    opex: OpexConfig = field(default_factory=OpexConfig)
    interest_rate: float = 0.06          # annual discount rate (fraction)
    currency: str = "USD"                # monetary unit for all costs
    exchange_rate: float = 1.0           # conversion factor to USD (7.2 for RMB)

    # ── sizing decisions (energy system) ──
    pv_area_m2: float = 0.0             # PV array area (m²); 0 = skip energy system
    battery_kwh: float = 0.0            # battery energy capacity (kWh); 0 = no battery

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
            "name", "site", "envelope", "hvac", "deh", "led",
            "transpiration", "setpoints", "pv", "battery", "tariff", "space",
            "growth",
            "equipment_power_w", "equipment_capital", "envelope_capital",
            "pump_capital", "opex",
            "interest_rate", "currency", "exchange_rate",
            "pv_area_m2", "battery_kwh",
        }
        unknown_top = set(d.keys()) - _TOP_KEYS
        if unknown_top:
            raise ValueError(
                f"Unrecognised top-level YAML keys: {sorted(unknown_top)}. "
                f"Valid keys: {sorted(_TOP_KEYS)}"
            )

        def sub(target, data, *, has_nested_capital: bool = False):
            known = {f.name for f in getattr(target, '__dataclass_fields__').values()}
            # 'capital' is a valid nested field handled separately
            unknown = set(data.keys()) - known - ({"capital"} if has_nested_capital else set())
            if unknown:
                raise ValueError(
                    f"Unrecognised keys in '{target.__name__}': "
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
                            f"Unrecognised keys in 'capital': {sorted(cap_unknown)}. "
                            f"Valid keys: {sorted(c_fields)}"
                        )
                    filtered["capital"] = CapitalCostConfig(
                        **{k: cap_data[k] for k in cap_data if k in c_fields}
                    )
            return filtered

        def _tariff(d: dict) -> TariffConfig:
            # backward compat: old peak/normal/valley → hourly_prices
            if "hourly_prices" in d:
                return TariffConfig(**sub(TariffConfig, d))
            if "peak_price" in d:
                hp = [d.get("normal_price", 0.10)] * 24
                for h in d.get("peak_hours", []):
                    hp[min(int(h), 23)] = d.get("peak_price", 0.12)
                for h in d.get("valley_hours", []):
                    hp[min(int(h), 23)] = d.get("valley_price", 0.06)
                return TariffConfig(
                    hourly_prices=hp,
                    export_price=d.get("export_price", 0.05),
                )
            return TariffConfig(**sub(TariffConfig, d))

        def _require_nonnegative(fields, data, cfg_name):
            """Reject negative config values (a negative moisture gain/removal
            coefficient would silently flip the humidity source into a sink)."""
            for f in fields:
                v = data.get(f)
                if v is not None and v < 0:
                    raise ValueError(
                        f"{cfg_name}.{f} must be >= 0, got {v}")

        # ── humidity-related sub-configs (validated, then applied) ──
        transp_cfg = sub(TranspirationConfig, d.get("transpiration", {}))
        deh_cfg = sub(DEHConfig, d.get("deh", {}), has_nested_capital=True)
        sp_cfg = sub(SetpointConfig, d.get("setpoints", {}))
        _require_nonnegative(
            ["E_max_kgs", "daily_water_L", "plant_count", "ml_per_plant_day",
             "k_vpd", "k_van_henten", "stage_factor", "g_stomata",
             "r_a", "r_n_canopy"],
            transp_cfg, "transpiration",
        )
        _require_nonnegative(
            ["smer", "M_deh_nom", "P_ref_w", "P_rated_max"],
            deh_cfg, "deh",
        )
        rh_sp = sp_cfg.get("RH")
        if rh_sp is not None and not (0.0 <= rh_sp <= 100.0):
            raise ValueError(
                f"setpoints.RH must be in [0,100] %, got {rh_sp}")

        return cls(
            name=d.get("name", "unnamed"),
            site=SiteConfig(**sub(SiteConfig, d.get("site", {}))),
            envelope=EnvelopeConfig(**sub(EnvelopeConfig, d.get("envelope", {}))),
            hvac=HVACConfig(**sub(HVACConfig, d.get("hvac", {}),
                                 has_nested_capital=True)),
            deh=DEHConfig(**deh_cfg),
            led=LEDConfig(**sub(LEDConfig, d.get("led", {}),
                               has_nested_capital=True)),
            transpiration=TranspirationConfig(**transp_cfg),
            setpoints=SetpointConfig(**sp_cfg),
            growth=VanHentenConfig(**sub(VanHentenConfig, d.get("growth", {}))),
            pv=PVConfig(**sub(PVConfig, d.get("pv", {}),
                              has_nested_capital=True)),
            battery=BatteryConfig(**sub(BatteryConfig, d.get("battery", {}),
                                        has_nested_capital=True)),
            tariff=_tariff(d.get("tariff", {})),
            space=DesignSpace(**sub(DesignSpace, d.get("space", {}))),
            equipment_power_w=d.get("equipment_power_w", 0.0),
            equipment_capital=CapitalCostConfig(**sub(CapitalCostConfig, d.get("equipment_capital", {}))),
            envelope_capital=CapitalCostConfig(**sub(CapitalCostConfig, d.get("envelope_capital", {}))),
            pump_capital=CapitalCostConfig(**sub(CapitalCostConfig, d.get("pump_capital", {}))),
            opex=OpexConfig(**sub(OpexConfig, d.get("opex", {}))),
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
