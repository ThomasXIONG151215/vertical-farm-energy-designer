"""
Design project configuration.

A ``DesignProject`` is a fully declarative description of a vertical-farm design:
site, envelope, HVAC, dehumidifier, LED, transpiration law, control setpoints
and the PV-Battery-Grid (PVBES) system plus the design search space. It is
serialised to/from YAML for easy creation and versioning.
"""

from dataclasses import dataclass, field, asdict
from typing import Optional

import yaml

__all__ = [
    "CapitalCostConfig",
    "SiteConfig", "EnvelopeConfig", "HVACConfig", "DEHConfig", "LEDConfig",
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
class SiteConfig:
    lat: float = 31.2
    lon: float = 121.5
    tz_hours: float = 8.0
    tilt: float = 20.0
    azimuth: float = 180.0
    year: int = 2023


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
    P_rated_w: float = 3000.0
    cop_value: float = 4.0
    cop_mode: str = "constant"   # constant | linear | table
    cop_k: float = 0.02
    cop_T_ref: float = 25.0
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
    capital: CapitalCostConfig = field(default_factory=CapitalCostConfig)


@dataclass
class DEHConfig:
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
    # Specific Moisture Extraction Rate (kg water / kWh electricity) — realistic
    # refrigeration dehumidifiers achieve 1.5–3.0 kg/kWh. Replaces the ASHRAE
    # bypass-factor eta (which gave SMER≈0.1, 10–30× too low).
    smer: float = 2.0
    deadband_rh: float = 3.0
    min_on_s: float = 180.0
    min_off_s: float = 180.0
    fan_power_w: float = 40.0
    tau_q: float = 90.0
    tau_m: float = 120.0
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
    capital: CapitalCostConfig = field(default_factory=CapitalCostConfig)


@dataclass
class TranspirationConfig:
    method: str = "vpd"          # constant | vpd | stomatal | van_henten
    # Rates are PER m²; the model multiplies by canopy area at runtime.
    E_max_kgs: float = 1.0e-4    # peak transpiration (kg/s per m²), constant method
    k_vpd: float = 1.0e-4        # VPD gain (kg/s per m² per kPa), vpd/van_henten
    stage_factor: float = 1.0
    g_stomata: float = 1.0e-3


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
    alpha_sc: float = 0.045
    beta_voc: float = -0.25
    NOCT: float = 45.0
    eta_inv: float = 0.97
    C_pv: float = 110.0
    degradation: float = 0.004
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
    pv: PVConfig = field(default_factory=PVConfig)
    battery: BatteryConfig = field(default_factory=BatteryConfig)
    tariff: TariffConfig = field(default_factory=TariffConfig)
    space: DesignSpace = field(default_factory=DesignSpace)
    equipment_power_w: float = 0.0   # constant facility electrical base load (W)
    equipment_capital: CapitalCostConfig = field(default_factory=CapitalCostConfig)
    envelope_capital: CapitalCostConfig = field(default_factory=CapitalCostConfig)
    interest_rate: float = 0.06          # annual discount rate (fraction)
    currency: str = "USD"                # monetary unit for all costs
    exchange_rate: float = 1.0           # conversion factor to USD (7.2 for RMB)

    # ---- (de)serialisation ---------------------------------------------
    def to_dict(self) -> dict:
        return asdict(self)

    def save(self, path) -> None:
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(self.to_dict(), f, sort_keys=False, allow_unicode=True)

    @classmethod
    def from_dict(cls, d: dict) -> "DesignProject":
        # Build sub-dataclasses, ignoring unknown keys defensively.
        def sub(target, data, *, has_nested_capital: bool = False):
            known = {f.name for f in getattr(target, '__dataclass_fields__').values()}
            filtered = {k: data[k] for k in data if k in known}
            if has_nested_capital:
                cap_data = data.get("capital", {})
                if isinstance(cap_data, dict) and cap_data:
                    c_fields = {f.name for f in CapitalCostConfig.__dataclass_fields__.values()}
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

        return cls(
            name=d.get("name", "unnamed"),
            site=SiteConfig(**sub(SiteConfig, d.get("site", {}))),
            envelope=EnvelopeConfig(**sub(EnvelopeConfig, d.get("envelope", {}))),
            hvac=HVACConfig(**sub(HVACConfig, d.get("hvac", {}),
                                 has_nested_capital=True)),
            deh=DEHConfig(**sub(DEHConfig, d.get("deh", {}),
                                has_nested_capital=True)),
            led=LEDConfig(**sub(LEDConfig, d.get("led", {}),
                               has_nested_capital=True)),
            transpiration=TranspirationConfig(**sub(TranspirationConfig, d.get("transpiration", {}))),
            setpoints=SetpointConfig(**sub(SetpointConfig, d.get("setpoints", {}))),
            pv=PVConfig(**sub(PVConfig, d.get("pv", {}),
                              has_nested_capital=True)),
            battery=BatteryConfig(**sub(BatteryConfig, d.get("battery", {}),
                                        has_nested_capital=True)),
            tariff=_tariff(d.get("tariff", {})),
            space=DesignSpace(**sub(DesignSpace, d.get("space", {}))),
            equipment_power_w=d.get("equipment_power_w", 0.0),
            equipment_capital=CapitalCostConfig(**sub(CapitalCostConfig, d.get("equipment_capital", {}))),
            envelope_capital=CapitalCostConfig(**sub(CapitalCostConfig, d.get("envelope_capital", {}))),
            interest_rate=d.get("interest_rate", 0.06),
            currency=d.get("currency", "USD"),
            exchange_rate=d.get("exchange_rate", 1.0),
        )

    @classmethod
    def load(cls, path) -> "DesignProject":
        with open(path, "r", encoding="utf-8") as f:
            return cls.from_dict(yaml.safe_load(f))
