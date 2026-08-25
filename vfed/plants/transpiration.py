"""
Plant transpiration model — the room's internal moisture source.

Five methods in two families:

  Model-calculated (driven by physics / growth state):
    method = "van_henten"  — E = k_van_henten × X_d × VPD × area × light_factor.
                             The dry-weight state X_d comes from the Van Henten
                             growth model, so transpiration grows with the
                             canopy and peaks at harvest.

  Direct-set (user specifies the water consumption):
    method = "daily"                 — daily water total (L/day for the whole
                                       canopy), spread evenly over the
                                       photoperiod hours.
    method = "per_plant"             — plant_count × mL/plant/day → daily
                                       total, spread over photoperiod hours.
    method = "daily_per_period"      — as "daily" but the daily total is
                                       staged over period_days (seedling →
                                       mature canopy), default three stages
                                       [d0, d1, d2).
    method = "per_plant_per_period"  — as "per_plant" but mL/plant/day is
                                       staged over period_days.

Light modulates stomatal aperture: the dark-period transpiration stays at
``dark_transpiration_frac`` (default 0.15) of the light-period rate — stomata
do not close fully at night (Caird et al. 2007, Plant Physiol. 143:4-10:
E_night/E_day ≈ 5-15 %, up to 30 %; Kim et al. 2004, Ann. Botany 94:691-697:
lettuce g_night/g_day ≈ 11-39 %).  In a plant factory the night VPD is not
suppressed as it is in the field, so the upper end of the range applies
(E_night/E_day ≈ 0.10-0.15).  The growth-stage scale factor ``stage_factor``
is a common multiplier applied to every method.

Direct-set methods do NOT depend on T/RH — the user states the water need
directly.  Period-staged methods additionally need ``cycle_day`` (days since
the last harvest) to select the current stage; the project validator
guarantees sum(period_days) == setpoints.crop_cycle_days, so stage
boundaries and harvest resets stay aligned.

The model-calculated method evaluates leaf-to-air VPD with the ROOM-AIR VPD
(T_leaf ≈ T_air first-order approximation).  Under light a well-ventilated
canopy runs 0.5-2 °C warmer than the air, so true leaf VPD is higher and
the model slightly UNDERestimates transpiration (few %).  No numeric
compensation is applied.
"""

from dataclasses import dataclass, field
from typing import List, Optional

from ..physics.psychrometrics import compute_vpd

__all__ = ["TranspirationModel"]

VALID_METHODS = (
    "van_henten",
    "daily",
    "per_plant",
    "daily_per_period",
    "per_plant_per_period",
)

# Removed methods → migration hint shown in validation errors.
_LEGACY_METHOD_HINTS = {
    "vpd": "van_henten",
    "stomatal": "van_henten",
    "constant": "daily",
}


@dataclass
class TranspirationModel:
    method: str = "van_henten"  # see module docstring / VALID_METHODS
    daily_water_L: float = 40.0  # daily water for whole canopy (L/day), "daily"
    plant_count: int = 0  # number of plants, "per_plant" family
    ml_per_plant_day: float = 80.0  # mL water per plant per day, "per_plant"
    period_days: List[float] = field(
        default_factory=lambda: [10.0, 10.0, 10.0]
    )  # stage widths (days)
    daily_water_L_period: List[float] = field(
        default_factory=lambda: [30.0, 45.0, 60.0]
    )  # L/day per stage
    ml_per_plant_day_period: List[float] = field(
        default_factory=lambda: [10.0, 30.0, 50.0]
    )  # mL/plant/day per stage
    photoperiod_hours: float = 16.0  # light hours per day
    k_van_henten: float = 1.0e-4  # biomass-scaled gain (1/(s·kPa)), van_henten
    #   P3-1 (calibrated 4e-4 -> 1e-4): 4e-4 gave harvest λE≈616 W/m²
    #   (14.5 L/m²/day) — ~7x the available LED PAR (87.5 W/m²), physically
    #   impossible.  1e-4 is calibrated to the ACTUAL 30-day-cycle harvest
    #   X_d≈0.45 (87.5 W/m² PAR), giving harvest λE≈102 W/m² (2.4 L/m²/day)
    #   — the same physical level as the former vpd method (113 W/m²).
    #   Cycle-mean light-period λE≈50 W/m² is what the DEH auto-size consumes.
    stage_factor: float = 1.0  # growth-stage scale (0-1+), all methods
    area_m2: float = 45.0  # canopy area (rates are per m²)
    dark_transpiration_frac: float = 0.15  # night rate as a fraction of the
    #   light-period rate (all methods).  Physical basis: Caird et al. 2007
    #   (E_night/E_day 5-15%, up to 30%) × plant-factory night VPD ≈ day VPD
    #   → take 0.10-0.15.  0.0 restores the old "zero in the dark" behaviour.

    def step(
        self,
        T_z: float,
        RH_z: float,
        is_light: bool,
        dt: float = 60.0,
        X_d: Optional[float] = None,  # kg/m²  (needed by "van_henten")
        light_wm2: Optional[float] = None,  # kept for a uniform call signature
        cycle_day: Optional[float] = None,  # days since harvest, needed by
        # "*_per_period" methods
    ) -> float:
        """Return transpiration rate E_trans (kg/s) for the whole canopy.

        ``dt`` is accepted for API compatibility but is NOT used: the return
        value is an INSTANTANEOUS rate (kg/s), not an integrated amount.  Do
        not multiply it by dt again when accumulating water — that would
        double-count the time integration.
        """
        light_factor = 1.0 if is_light else self.dark_transpiration_frac
        area = self.area_m2
        if self.method == "van_henten":
            # Fallback only on direct TranspirationModel use — the engine
            # always passes X_d.  Aligned with VanHentenConfig.
            # initial_dry_weight (P3-13).
            _xd = X_d if X_d is not None else 0.02
            vpd = compute_vpd(T_z, RH_z)
            return (
                self.k_van_henten
                * max(_xd, 0.0)
                * max(0.0, vpd)
                * area
                * light_factor
                * self.stage_factor
            )
        if self.method == "daily":
            pph = max(self.photoperiod_hours, 0.1)
            return self.daily_water_L * self.stage_factor / (pph * 3600.0) * light_factor
        if self.method == "per_plant":
            # Dark period: no transpiration only when dark_transpiration_frac
            # is explicitly 0; then no config check is needed (P3-5).
            if light_factor <= 0.0:
                return 0.0
            self._require_plant_count()
            pph = max(self.photoperiod_hours, 0.1)
            daily_L = self.plant_count * self.ml_per_plant_day / 1000.0
            return daily_L * self.stage_factor / (pph * 3600.0) * light_factor
        if self.method in ("daily_per_period", "per_plant_per_period"):
            # Dark period: same early-return as per_plant when the dark
            # fraction is explicitly 0; stage/cycle-day checks only when the
            # night transpiration is active.
            if light_factor <= 0.0:
                return 0.0
            if cycle_day is None:
                raise ValueError(
                    f"transpiration.method='{self.method}' requires cycle_day "
                    f"(days since the last harvest) to select the current "
                    f"stage.  The engine passes it automatically; direct "
                    f"TranspirationModel use must pass cycle_day=... ."
                )
            idx = self._stage_index(cycle_day)
            if self.method == "daily_per_period":
                daily_L = self.daily_water_L_period[idx]
            else:
                self._require_plant_count()
                daily_L = self.plant_count * self.ml_per_plant_day_period[idx] / 1000.0
            pph = max(self.photoperiod_hours, 0.1)
            return daily_L * self.stage_factor / (pph * 3600.0) * light_factor
        raise ValueError(self._unknown_method_message())

    def design_rate_kgs(self) -> float:
        """Instantaneous light-period transpiration rate (kg/s, whole canopy)
        used to size the DEH.

        Direct-set methods are time-invariant under constant light and do not
        depend on T/RH, so the design rate equals the PEAK-stage rate: sizing
        to the maximum stage keeps the DEH (a fixed-capacity device) able to
        hold the RH setpoint through the whole crop cycle — the same
        peak-sizing logic as the van_henten pre-run (P3-4).  The stage_factor
        multiplier is applied; the DEH safety_factor applies on top (engine).
        """
        pph = max(self.photoperiod_hours, 0.1)
        if self.method == "daily":
            daily_L = self.daily_water_L
        elif self.method == "per_plant":
            self._require_plant_count()
            daily_L = self.plant_count * self.ml_per_plant_day / 1000.0
        elif self.method == "daily_per_period":
            if not self.daily_water_L_period:
                raise ValueError(
                    "transpiration.daily_water_L_period must not be empty "
                    "for the daily_per_period method"
                )
            daily_L = max(self.daily_water_L_period)
        elif self.method == "per_plant_per_period":
            self._require_plant_count()
            if not self.ml_per_plant_day_period:
                raise ValueError(
                    "transpiration.ml_per_plant_day_period must not be empty "
                    "for the per_plant_per_period method"
                )
            daily_L = self.plant_count * max(self.ml_per_plant_day_period) / 1000.0
        elif self.method == "van_henten":
            raise ValueError(
                "design_rate_kgs() is not defined for the 'van_henten' method "
                "— its biomass evolves over the crop cycle, so the engine "
                "sizes the DEH with a cycle pre-run peak instead (P3-4)."
            )
        else:
            raise ValueError(self._unknown_method_message())
        return daily_L * self.stage_factor / (pph * 3600.0)

    def _stage_index(self, cycle_day: float) -> int:
        """Map days-since-harvest to the direct-set stage index.

        Stage boundaries are left-closed, right-open:
            stage 0: [0, period_days[0])
            stage 1: [period_days[0], period_days[0] + period_days[1])
            ...
        cycle_day >= sum(period_days) maps to the LAST stage — the project
        validator enforces sum(period_days) == crop_cycle_days, so in engine
        use the index is always < len(period_days).
        """
        if cycle_day < 0.0:
            raise ValueError(f"cycle_day must be >= 0, got {cycle_day}")
        if not self.period_days:
            raise ValueError(
                "transpiration.period_days must not be empty for " "period-staged methods"
            )
        acc = 0.0
        for i, d in enumerate(self.period_days):
            acc += max(0.0, d)
            if cycle_day < acc:
                return i
        return len(self.period_days) - 1

    def _require_plant_count(self) -> None:
        # P3-5 (fail-fast): plant_count<=0 previously returned a silent
        # zero transpiration — the room humidity collapses, the DEH never
        # runs, no warning is raised.  Reject the invalid config.
        if self.plant_count <= 0:
            raise ValueError(
                f"transpiration.method='{self.method}' requires "
                f"transpiration.plant_count > 0, got {self.plant_count}. "
                f"Set transpiration.plant_count in the project YAML "
                f"(and optionally transpiration.ml_per_plant_day)."
            )

    def _unknown_method_message(self) -> str:
        msg = (
            f"transpiration.method='{self.method}' is not a valid method. "
            f"Valid methods: {'|'.join(VALID_METHODS)}."
        )
        hint = _LEGACY_METHOD_HINTS.get(self.method)
        if hint:
            msg += f"  '{self.method}' was removed — migrate to " f"'{hint}'."
        return msg
