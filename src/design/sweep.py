"""
Design sweeper — enumerates user-defined parameter ranges (building + PVBES)
via a generic Cartesian product and returns the full enumeration table ranked
by LCOE ($/kWh total system cost).

Includes full-system capital costs (LED, HVAC, DEH, PV, battery, equipment,
envelope) with per-component depreciation.  Objective: min(LCOE).
"""

import itertools
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from ..pvbes.pv import PVSystem
from ..pvbes.battery import BatterySystem
from ..pvbes.grid import Tariff
from ..pvbes.energy_system import EnergySystem
from .project import CapitalCostConfig, DesignProject
from .engine import DesignEngine

__all__ = ["sweep_design"]

# ---------------------------------------------------------------------------
# Hard limits — ranges outside these bounds raise an error.
# ---------------------------------------------------------------------------
HARD_LIMITS: Dict[str, tuple] = {
    "ppfd_target":        (50, 500),
    "efficacy":           (1.5, 4.0),
    "photoperiod_hours":  (0, 24),
    "light_start_hour":   (0, 23),
    "T_light":            (15, 30),
    "T_dark":             (10, 28),
    "RH":                 (40, 90),
    "co2_ppm":            (300, 2000),
    "crop_cycle_days":    (15, 60),
    "pv_area":            (0, 1000),
    "battery":            (0, 500),
}

# ---------------------------------------------------------------------------
# Mapping: parameter_ranges key → (project_dict_section, field_name)
# ---------------------------------------------------------------------------
_PARAM_PATH_MAP: Dict[str, tuple] = {
    "ppfd_target":       ("led", "ppfd_target"),
    "efficacy":          ("led", "efficacy"),
    "light_start_hour":  ("led", "light_start_hour"),
    "photoperiod_hours": ("led", "photoperiod_hours"),
    "T_light":           ("setpoints", "T_light"),
    "T_dark":            ("setpoints", "T_dark"),
    "RH":                ("setpoints", "RH"),
    "co2_ppm":           ("setpoints", "co2_ppm"),
    "crop_cycle_days":   ("setpoints", "crop_cycle_days"),
}

# params handled by EnergySystem (not project overrides)
_PVBES_PARAMS = {"pv_area", "battery"}

# valid values for DesignSpace.objective
_VALID_OBJECTIVES = {"lcoe", "kwh_per_kg_fresh", "cost_per_kg_fresh"}


# ---------------------------------------------------------------------------
# Capital cost resolution
# ---------------------------------------------------------------------------
def _derived_led_power(project: DesignProject) -> float:
    """LED electrical power (W) as actually run (auto-deduced or direct)."""
    if project.led.auto_deduce:
        return (project.led.ppfd_target * project.led.covered_area
                / max(project.led.efficacy, 0.1))
    return project.led.power_w


def _resolve_capital(cfg: CapitalCostConfig, rated_value: float,
                     legacy_fallback: float = 0.0) -> float:
    """Resolve a single component's capital cost.

    Args:
        cfg: CapitalCostConfig from the project.
        rated_value: rated value (W for LED/HVAC/DEH; Wp for PV; kWh for battery).
        legacy_fallback: cost from old config field (C_pv, c_energy) if capital is default.

    Returns:
        capital cost in project currency.
    """
    if cfg.mode == "per_watt":
        return cfg.rate_per_watt * rated_value
    if cfg.mode == "direct" and cfg.cost > 0:
        return cfg.cost
    return legacy_fallback


def _total_capital(project: DesignProject, pv_area: float,
                   battery_kwh: float) -> Dict[str, float]:
    """Compute per-component capital breakdown, including legacy fallbacks."""
    led_w = _derived_led_power(project)
    # PV peak kWp = pv_area (m²) / area_to_power (m²/kWp)
    pv_kwp = pv_area / project.pv.area_to_power

    breakdown = {
        "LED":       _resolve_capital(project.led.capital, led_w),
        "HVAC":      _resolve_capital(project.hvac.capital, project.hvac.P_rated_w),
        "DEH":       _resolve_capital(project.deh.capital, project.deh.P_ref_w),
        "PV":        _resolve_capital(project.pv.capital, pv_kwp,
                                      legacy_fallback=project.pv.C_pv * pv_kwp),
        "Battery":   _resolve_capital(project.battery.capital, battery_kwh,
                                      legacy_fallback=project.battery.c_energy * battery_kwh),
        "Equipment": _resolve_capital(project.equipment_capital, 0),
        "Envelope":  _resolve_capital(project.envelope_capital, 0),
    }
    breakdown["total"] = sum(breakdown.values())
    return breakdown


def _crf(i: float, n: float) -> float:
    """Capital Recovery Factor.  Handles i=0 (division-safe)."""
    n = max(n, 1.0)
    if abs(i) < 1e-12:
        return 1.0 / n
    return i * (1 + i) ** n / ((1 + i) ** n - 1)


def _annualized_capital(project: DesignProject,
                        capital_breakdown: Dict[str, float]) -> float:
    """CRF-weighted annualised capital using per-component depreciation years."""
    dep_map = {
        "LED":       project.led.capital.depreciation_years,
        "HVAC":      project.hvac.capital.depreciation_years,
        "DEH":       project.deh.capital.depreciation_years,
        "PV":        project.pv.capital.depreciation_years,
        "Battery":   project.battery.capital.depreciation_years,
        "Equipment": project.equipment_capital.depreciation_years,
        "Envelope":  project.envelope_capital.depreciation_years,
    }
    i = project.interest_rate
    total = 0.0
    for comp, dep in dep_map.items():
        total += _crf(i, dep) * capital_breakdown[comp]
    return total


def _compute_lcoe(annual_capital: float, annual_om: float,
                  net_grid_cost: float, annual_energy: float) -> float:
    """LCOE using per-component CRF (not EnergySystem's single-lifetime CRF)."""
    if annual_energy <= 0:
        return float("inf")
    return (annual_capital + annual_om + net_grid_cost) / annual_energy


def _compute_cost_per_kg_fresh(annual_capital: float, annual_om: float,
                                net_grid_cost: float, biomass_kg: float,
                                dry_matter_fraction: float = 0.05) -> float:
    """$/kg fresh-mass cost."""
    fresh_kg = biomass_kg / dry_matter_fraction
    if fresh_kg <= 0:
        return float("inf")
    return (annual_capital + annual_om + net_grid_cost) / fresh_kg


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------
def _build_energy_system(project: DesignProject) -> EnergySystem:
    """Re-use project PV / battery / tariff defaults for EnergySystem."""
    pv = PVSystem(
        eta_pv=project.pv.eta_pv, area_to_power=project.pv.area_to_power,
        N_s=project.pv.N_s, I_sc_stc=project.pv.I_sc_stc,
        V_oc_stc=project.pv.V_oc_stc, I_mp_stc=project.pv.I_mp_stc,
        V_mp_stc=project.pv.V_mp_stc, alpha_sc=project.pv.alpha_sc,
        beta_voc=project.pv.beta_voc, NOCT=project.pv.NOCT,
        eta_inv=project.pv.eta_inv, C_pv=project.pv.C_pv,
        degradation=project.pv.degradation,
    )
    battery = BatterySystem(
        c_energy=project.battery.c_energy, c_rate=project.battery.c_rate,
        eta_ch=project.battery.eta_ch, eta_dis=project.battery.eta_dis,
        soc_min=project.battery.soc_min, soc_max=project.battery.soc_max,
        cycle_life=project.battery.cycle_life,
        maintenance=project.battery.maintenance,
    )
    tariff = Tariff(
        hourly_prices=list(project.tariff.hourly_prices),
        export_price=project.tariff.export_price,
    )
    return EnergySystem(pv=pv, battery=battery, tariff=tariff)


def _validate_ranges(ranges: dict) -> None:
    """Raise ValueError if any range exceeds HARD_LIMITS or is ill-formed."""
    for name, (lo, hi, step) in ranges.items():
        if name not in HARD_LIMITS:
            raise ValueError(
                f"Unknown parameter '{name}' in parameter_ranges. "
                f"Known: {sorted(HARD_LIMITS.keys())}"
            )
        hard_lo, hard_hi = HARD_LIMITS[name]
        if lo < hard_lo or hi > hard_hi:
            raise ValueError(
                f"'{name}' range [{lo}, {hi}] exceeds hard limits "
                f"[{hard_lo}, {hard_hi}]"
            )
        if step <= 0 or hi <= lo:
            raise ValueError(
                f"Invalid range for '{name}': [{lo}, {hi}, {step}]"
            )


def _override_project(project: DesignProject, overrides: dict) -> DesignProject:
    """Clone *project*, apply overrides (key→value), and re-construct.

    Re-construction via ``DesignProject.from_dict`` triggers ``LEDDevice.__post_init__``
    so that ``ppfd_target`` / ``efficacy`` / ``covered_area`` changes auto-recalculate
    the LED electrical power.
    """
    d = project.to_dict()
    for key, value in overrides.items():
        section, field = _PARAM_PATH_MAP[key]
        d[section][field] = value
    return DesignProject.from_dict(d)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def sweep_design(project: DesignProject,
                 cache_dir: str = "weather_cache") -> Dict:
    """Enumerate parameter_ranges → build sim per building combo → PVBES eval.

    Returns
    -------
    dict with keys ``results`` (DataFrame, None when no ranges) and ``best``
    (dict or sim result for single-point).  Objective is taken from
    ``project.space.objective`` (default ``"lcoe"``).
    """
    ranges = project.space.parameter_ranges
    objective = getattr(project.space, "objective", "lcoe")
    if objective not in _VALID_OBJECTIVES:
        raise ValueError(
            f"Unknown objective '{objective}'. "
            f"Valid: {sorted(_VALID_OBJECTIVES)}"
        )

    # ── single-point evaluation ──────────────────────────────────────────
    if not ranges:
        engine = DesignEngine(cache_dir=cache_dir)
        sim = engine.run(project)
        return {"results": None, "best": {
            "kwh_per_kg_fresh": sim["kwh_per_kg_fresh"],
            "annual_load_kwh": sim["annual_load_kwh"],
            "biomass_kg": sim["biomass_kg"],
        }}

    _validate_ranges(ranges)

    # ── split building vs PVBES params ────────────────────────────────────
    building_names = [k for k in ranges if k not in _PVBES_PARAMS]
    pvb_names = [k for k in ranges if k in _PVBES_PARAMS]

    # ── PV / battery grids ────────────────────────────────────────────────
    pv_areas = [0.0]
    bats = [0.0]
    if "pv_area" in ranges:
        r = ranges["pv_area"]
        pv_areas = list(np.arange(r[0], r[1] + 1e-9, r[2]))
    if "battery" in ranges:
        r = ranges["battery"]
        bats = list(np.arange(r[0], r[1] + 1e-9, r[2]))

    # ── building combos ───────────────────────────────────────────────────
    if building_names:
        building_arrays = [
            np.arange(ranges[n][0], ranges[n][1] + 1e-9, ranges[n][2])
            for n in building_names
        ]
        building_combos = list(itertools.product(*building_arrays))
    else:
        building_combos = [()]

    # ── setup ─────────────────────────────────────────────────────────────
    engine = DesignEngine(cache_dir=cache_dir)
    es = _build_energy_system(project) if pvb_names else None

    rows: List[dict] = []
    best: Optional[dict] = None

    for b_combo in building_combos:
        overrides = dict(zip(building_names, b_combo)) if building_names else {}
        p = _override_project(project, overrides) if overrides else project

        sim = engine.run(p)
        kwh_fresh = sim["kwh_per_kg_fresh"]
        annual_load = sim["annual_load_kwh"]
        biomass_kg = sim["biomass_kg"]
        base = dict(zip(building_names, b_combo)) if building_names else {}

        if pvb_names:
            for A_pv in pv_areas:
                for E_bat in bats:
                    m = es.calculate_metrics(
                        [A_pv, E_bat], sim["weather"], sim["load"],
                        # Mid-life degradation year: LCOE uses CRF over the
                        # lifetime, so pair it with the average (mid-life)
                        # PV output rather than pristine first-year output.
                        year=es.lifetime // 2,
                    )
                    cap = _total_capital(p, A_pv, E_bat)
                    annual_cap = _annualized_capital(p, cap)
                    annual_water_m3 = float(sim.summary.get("annual_water_m3", 0.0))
                    annual_om = (p.opex.maintenance_pct * cap["total"]
                                 + p.opex.water_cost_per_m3 * annual_water_m3
                                 + p.opex.labor_cost_per_year
                                 + p.opex.misc_opex_per_year)
                    net_grid = m["annual_grid_cost"]
                    lcoe = _compute_lcoe(annual_cap, annual_om, net_grid, annual_load)
                    cost_kg = _compute_cost_per_kg_fresh(
                        annual_cap, annual_om, net_grid, biomass_kg,
                        p.growth.dry_matter_fraction)

                    row = {
                        **base,
                        "pv_area": A_pv,
                        "battery_kwh": E_bat,
                        "lcoe": lcoe,
                        "cost_per_kg_fresh": cost_kg,
                        "kwh_per_kg_fresh": kwh_fresh,
                        "capital_total": cap["total"],
                        "capital_led": cap["LED"],
                        "capital_hvac": cap["HVAC"],
                        "capital_deh": cap["DEH"],
                        "capital_pv": cap["PV"],
                        "capital_battery": cap["Battery"],
                        "capital_equipment": cap["Equipment"],
                        "capital_envelope": cap["Envelope"],
                        "annual_capital": annual_cap,
                        "annual_om": annual_om,
                        "annual_grid_cost": net_grid,
                        "annual_load_kwh": annual_load,
                        "biomass_kg": biomass_kg,
                        "annual_pv_generation": m["annual_pv_generation"],
                        "annual_grid_import": m["annual_grid_import"],
                        "annual_grid_export": m["annual_grid_export"],
                        "battery_cycles": m["battery_cycles"],
                    }
                    rows.append(row)
                    if best is None or row[objective] < best[objective]:
                        best = row
        else:
            cap = _total_capital(p, 0, 0)
            annual_cap = _annualized_capital(p, cap)
            annual_water_m3 = float(sim.summary.get("annual_water_m3", 0.0))
            annual_om = (p.opex.maintenance_pct * cap["total"]
                         + p.opex.water_cost_per_m3 * annual_water_m3
                         + p.opex.labor_cost_per_year
                         + p.opex.misc_opex_per_year)
            lcoe = _compute_lcoe(annual_cap, annual_om, 0.0, annual_load)
            cost_kg = _compute_cost_per_kg_fresh(
                annual_cap, annual_om, 0.0, biomass_kg,
                p.growth.dry_matter_fraction)

            row = {
                **base,
                "lcoe": lcoe,
                "cost_per_kg_fresh": cost_kg,
                "kwh_per_kg_fresh": kwh_fresh,
                "capital_total": cap["total"],
                "annual_capital": annual_cap,
                "annual_om": annual_om,
                "annual_grid_cost": 0.0,
                "annual_load_kwh": annual_load,
                "biomass_kg": biomass_kg,
            }
            rows.append(row)
            if best is None or row[objective] < best[objective]:
                best = row

    results = pd.DataFrame(rows) if rows else pd.DataFrame()
    if not results.empty and objective in results.columns:
        results = results.sort_values(objective)
    return {"results": results, "best": best, "objective": objective}
