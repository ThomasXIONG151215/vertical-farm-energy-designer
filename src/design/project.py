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
    "SiteConfig", "EnvelopeConfig", "HVACConfig", "DEHConfig", "LEDConfig",
    "TranspirationConfig", "SetpointConfig", "PVConfig", "BatteryConfig",
    "TariffConfig", "DesignSpace", "DesignProject",
]


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


@dataclass
class LEDConfig:
    power_w: float = 1300.0
    start_hour: int = 6
    end_hour: int = 22
    heat_fraction: float = 1.0
    # auto-deduce from efficacy when auto_deduce=True (ponytail: avoids manual calc)
    auto_deduce: bool = True
    efficacy: float = 2.5       # µmol/J  (LED photon efficacy)
    ppfd_target: float = 400.0  # µmol/(m²·s)
    covered_area: float = 45.0  # m²


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
    T_cool: float = 22.0
    T_heat: float = 18.0
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


@dataclass
class TariffConfig:
    peak_price: float = 0.096
    normal_price: float = 0.096
    valley_price: float = 0.096
    export_price: float = 0.05
    peak_hours: list = field(default_factory=lambda: [10, 11, 12, 13, 14, 18, 19, 20, 21])
    valley_hours: list = field(default_factory=lambda: [0, 1, 2, 3, 4, 5, 23])


@dataclass
class DesignSpace:
    pv_area_range: tuple = (0.0, 200.0)
    pv_area_step: float = 10.0
    battery_range: tuple = (0.0, 100.0)
    battery_step: float = 5.0
    timestep_s: float = 600.0


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

    # ---- (de)serialisation ---------------------------------------------
    def to_dict(self) -> dict:
        return asdict(self)

    def save(self, path) -> None:
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(self.to_dict(), f, sort_keys=False, allow_unicode=True)

    @classmethod
    def from_dict(cls, d: dict) -> "DesignProject":
        # Build sub-dataclasses, ignoring unknown keys defensively.
        def sub(target, data):
            known = {f.name for f in getattr(target, '__dataclass_fields__').values()}
            return {k: data[k] for k in data if k in known}
        return cls(
            name=d.get("name", "unnamed"),
            site=SiteConfig(**sub(SiteConfig, d.get("site", {}))),
            envelope=EnvelopeConfig(**sub(EnvelopeConfig, d.get("envelope", {}))),
            hvac=HVACConfig(**sub(HVACConfig, d.get("hvac", {}))),
            deh=DEHConfig(**sub(DEHConfig, d.get("deh", {}))),
            led=LEDConfig(**sub(LEDConfig, d.get("led", {}))),
            transpiration=TranspirationConfig(**sub(TranspirationConfig, d.get("transpiration", {}))),
            setpoints=SetpointConfig(**sub(SetpointConfig, d.get("setpoints", {}))),
            pv=PVConfig(**sub(PVConfig, d.get("pv", {}))),
            battery=BatteryConfig(**sub(BatteryConfig, d.get("battery", {}))),
            tariff=TariffConfig(**sub(TariffConfig, d.get("tariff", {}))),
            space=DesignSpace(**sub(DesignSpace, d.get("space", {}))),
            equipment_power_w=d.get("equipment_power_w", 0.0),
        )

    @classmethod
    def load(cls, path) -> "DesignProject":
        with open(path, "r", encoding="utf-8") as f:
            return cls.from_dict(yaml.safe_load(f))
