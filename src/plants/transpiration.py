"""
Plant transpiration model — the room's internal moisture source.

Two families of methods:

  Model-calculated:
    method = "vpd"         — E = k_vpd × VPD × area × light_factor
    method = "stomatal"    — Penman-Monteith-style light + VPD + temperature
    method = "van_henten"  — E = k_vpd × X_d × VPD × area × light_factor

  Direct-set (user specifies water consumption):
    method = "constant"    — fixed instantaneous rate E_max (kg/s per m²)
    method = "daily"       — daily water total (L/day for whole canopy),
                             spread evenly over the photoperiod hours.
    method = "per_plant"   — number of plants × mL/plant/day → daily
                             total, spread over photoperiod hours.

Light modulates stomatal aperture (transpiration ~0 in the dark for most
methods). A growth-stage scale factor lets the same device represent
seedlings vs. mature canopy.
"""

from dataclasses import dataclass
from typing import Optional

from ..physics.psychrometrics import compute_vpd, saturation_vapor_pressure

__all__ = ["TranspirationModel"]


@dataclass
class TranspirationModel:
    method: str = "vpd"        # "constant" | "daily" | "per_plant" | "vpd" | "stomatal" | "van_henten"
    E_max_kgs: float = 1.0e-4   # peak transpiration (kg/s per m²), constant method
    daily_water_L: float = 40.0 # daily water for whole canopy (L/day), "daily" method
    plant_count: int = 0        # number of plants, "per_plant" method
    ml_per_plant_day: float = 80.0  # mL water per plant per day, "per_plant" method
    photoperiod_hours: float = 16.0  # light hours per day
    k_vpd: float = 2.0e-5       # VPD gain (kg/s per m² per kPa), vpd method
    k_van_henten: float = 4.0e-4 # biomass-scaled gain (1/(s·kPa)), van_henten method
    stage_factor: float = 1.0   # growth-stage scale (0-1+)
    g_stomata: float = 1.0e-3   # stomatal conductance proxy (m/s) for "stomatal"
    r_a: float = 50.0            # aerodynamic resistance (s/m) for "stomatal"
    r_n_canopy: float = 250.0   # net canopy radiation (W/m²) for "stomatal"
    area_m2: float = 45.0       # canopy area (rates are per m²)
    cp_air: float = 1005.0
    h_fg: float = 2.5e6         # J/kg

    def step(
        self,
        T_z: float,
        RH_z: float,
        is_light: bool,
        dt: float = 60.0,
        X_d: Optional[float] = None,   # kg/m²  (needed by "van_henten")
    ) -> float:
        """Return transpiration rate E_trans (kg/s) for the whole canopy."""
        light_factor = 1.0 if is_light else 0.0
        area = self.area_m2
        if self.method == "constant":
            return self.E_max_kgs * area * self.stage_factor * light_factor
        if self.method == "daily":
            pph = max(self.photoperiod_hours, 0.1)
            return self.daily_water_L * self.stage_factor / (pph * 3600.0) * light_factor
        if self.method == "per_plant":
            pph = max(self.photoperiod_hours, 0.1)
            daily_L = self.plant_count * self.ml_per_plant_day / 1000.0
            return daily_L * self.stage_factor / (pph * 3600.0) * light_factor
        if self.method == "vpd":
            vpd = compute_vpd(T_z, RH_z)
            return self.k_vpd * max(0.0, vpd) * area * self.stage_factor * light_factor
        if self.method == "van_henten":
            _xd = X_d if X_d is not None else 0.01
            vpd = compute_vpd(T_z, RH_z)
            return self.k_van_henten * max(_xd, 0.0) * max(0.0, vpd) * area * light_factor * self.stage_factor
        if self.method == "stomatal":
            if light_factor <= 0.0:
                return 0.0
            vpd = compute_vpd(T_z, RH_z)
            e_sat = saturation_vapor_pressure(T_z)
            delta = 4098.0 * e_sat / ((T_z + 237.3) ** 2)
            gamma = 0.0655                   # psychrometric constant (kPa/K) at 20°C
            r_s = 1.0 / max(1e-9, self.g_stomata)
            r_a = max(1.0, self.r_a)
            rho_cp = self.rho_cp()  # volumetric heat capacity, J/(m³·K) ≡ Pa/K
            R_n = self.r_n_canopy * light_factor  # net canopy radiation (W/m²)
            # Penman–Monteith: λE = (Δ·R_n + ρ·c_p·VPD/r_a) / (Δ + γ(1 + r_s/r_a))
            # Δ (kPa/K), γ (kPa/K) and VPD (kPa) must share ONE pressure unit.
            # With all three in kPa the ratio is invariant — the kPa and Pa
            # representations give identical λE (verified numerically) — so no
            # kPa→Pa factor is applied.  Only a *mixed* VPD(Pa) with Δ, γ in
            # kPa would overstate the aerodynamic term by 1000×.
            numerator = delta * R_n + rho_cp * max(0.0, vpd) / r_a
            denominator = delta + gamma * (1.0 + r_s / r_a)
            lambda_E = numerator / denominator
            E_rate = lambda_E / self.h_fg
            return E_rate * area * self.stage_factor
        return 0.0

    def rho_cp(self) -> float:
        return 1.2 * self.cp_air
