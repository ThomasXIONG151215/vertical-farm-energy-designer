"""
Plant transpiration model — the room's internal moisture source.

Transpiration is fully configurable for design studies:

  method = "constant" : fixed rate E_max (kg/s) whenever lights are on.
  method = "vpd"      : E = k_vpd * max(0, VPD) * light_factor  (kg/s)
  method = "stomatal" : Penman-Monteith-style light + VPD + temperature drive.
  method = "van_henten": E = k_vpd * X_d * max(0, VPD) * light_factor

where X_d is the current canopy dry-weight (kg/m²), supplied by the Van Henten
growth model running in the same ODE loop.

Light modulates stomatal aperture (transpiration ~0 in the dark). A growth-stage
scale factor lets the same device represent seedlings vs. mature canopy.
"""

from dataclasses import dataclass
from typing import Optional

from ..physics.psychrometrics import compute_vpd

__all__ = ["TranspirationModel"]


@dataclass
class TranspirationModel:
    method: str = "vpd"        # "constant" | "vpd" | "stomatal" | "van_henten"
    E_max_kgs: float = 1.0e-4   # peak transpiration (kg/s per m²), constant method
    k_vpd: float = 1.0e-4       # VPD gain (kg/s per m² per kPa), vpd/van_henten
    stage_factor: float = 1.0   # growth-stage scale (0-1+)
    g_stomata: float = 1.0e-3   # stomatal conductance proxy (m/s) for "stomatal"
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
        if self.method == "vpd":
            vpd = compute_vpd(T_z, RH_z)
            return self.k_vpd * max(0.0, vpd) * area * self.stage_factor * light_factor
        if self.method == "van_henten":
            _xd = X_d or 0.01               # fallback if growth model not coupled
            vpd = compute_vpd(T_z, RH_z)
            return self.k_vpd * _xd * max(0.0, vpd) * area * light_factor
        if self.method == "stomatal":
            vpd = compute_vpd(T_z, RH_z)
            # Light + VPD driven latent flux (simplified PM).
            radiative = self.E_max_kgs * area * light_factor
            vpd_term = self.g_stomata * vpd * self.h_fg
            aerodyn = 1.0 / max(1e-3, self.g_stomata)
            E = (radiative + (self.rho_cp() * vpd_term) / aerodyn)
            return E * self.stage_factor
        return 0.0

    def rho_cp(self) -> float:
        return 1.2 * self.cp_air
