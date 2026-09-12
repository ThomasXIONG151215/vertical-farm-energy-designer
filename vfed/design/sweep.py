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
from .project import (
    CAPITAL_MODES_BY_COMPONENT,
    CapitalCostConfig,
    DesignProject,
    validate_capital_config,
)
from .engine import DesignEngine

__all__ = ["sweep_design"]

# ---------------------------------------------------------------------------
# Hard limits — ranges outside these bounds raise an error.
# ---------------------------------------------------------------------------
HARD_LIMITS: Dict[str, tuple] = {
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

# ---------------------------------------------------------------------------
# Mapping: parameter_ranges key → (project_dict_section, field_name)
# ---------------------------------------------------------------------------
_PARAM_PATH_MAP: Dict[str, tuple] = {
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

# params handled by EnergySystem (not project overrides)
_PVBES_PARAMS = {"pv_area", "battery"}

# F7: accept the top-level config field names (pv_area_m2 / battery_kwh) as
# aliases for the sweep parameter names (pv_area / battery), so users can use
# one consistent vocabulary in space.parameter_ranges.
_RANGE_ALIASES = {
    "pv_area_m2": "pv_area",
    "battery_kwh": "battery",
}

# valid values for DesignSpace.objective
_VALID_OBJECTIVES = {"lcoe", "kwh_per_kg_fresh", "cost_per_kg_fresh"}

# valid values for CapitalCostConfig.mode, per component (P0-1 / P5-11).
# The mode name carries the pricing basis: per_watt = rated W (LED/HVAC/DEH),
# per_kwp = rated kWp (PV), per_kwh = rated kWh (battery).  The pre-P0-1
# 'per_watt' silently multiplied kWp for PV and kWh for battery (1000x /
# unit-class off the field name) -- those spellings now fail fast.
_VALID_CAPITAL_MODES = set().union(*CAPITAL_MODES_BY_COMPONENT.values())


# ---------------------------------------------------------------------------
# Capital cost resolution
# ---------------------------------------------------------------------------
def _derived_led_power(project: DesignProject) -> float:
    """LED electrical power (W) as actually run (auto-deduced or direct)."""
    if project.led.auto_deduce:
        return project.led.ppfd_target * project.led.covered_area / max(project.led.efficacy, 0.1)
    return project.led.power_w


def _resolve_capital(
    cfg: CapitalCostConfig,
    rated_value: float,
    legacy_fallback: float = 0.0,
    component: str = "equipment",
) -> float:
    """Resolve a single component's capital cost.

    Args:
        cfg: CapitalCostConfig from the project.
        rated_value: rated value in the component's pricing basis
            (W for LED/HVAC/DEH; kWp for PV; kWh for battery).
        legacy_fallback: cost from old config field (C_pv, c_energy) if capital
            resolves to nothing (mode 'direct' with cost <= 0).
        component: component key (led/hvac/deh/pv/battery/equipment/envelope/
            pump).  The mode must match the component's pricing basis
            (``CAPITAL_MODES_BY_COMPONENT``, P0-1) -- 'per_watt' on pv/battery
            is rejected with a migration message instead of being silently
            multiplied by kWp / kWh as before.

    Returns:
        capital cost in project currency.
    """
    # P0-1: defense in depth -- from_dict validates at load time; this catches
    # programmatically constructed DesignProjects with a stale spelling.
    validate_capital_config(cfg, component)
    if cfg.mode == "per_watt":
        return cfg.rate_per_watt * rated_value
    if cfg.mode == "per_kwp":
        return cfg.rate_per_kwp * rated_value
    if cfg.mode == "per_kwh":
        return cfg.rate_per_kwh * rated_value
    # mode == "direct"
    if cfg.cost > 0:
        return cfg.cost
    return legacy_fallback


def _total_capital(project: DesignProject, pv_area: float, battery_kwh: float) -> Dict[str, float]:
    """Compute per-component capital breakdown, including legacy fallbacks.

    P0-1: PV is priced per kWp (``pv.capital`` mode ``per_kwp`` or the legacy
    ``C_pv`` fallback), battery per kWh (mode ``per_kwh`` or ``c_energy``
    fallback), electrical equipment per rated W (mode ``per_watt``).
    """
    led_w = _derived_led_power(project)
    # PV peak kWp = pv_area (m²) / area_to_power (m²/kWp)
    pv_kwp = pv_area / project.pv.area_to_power

    breakdown = {
        "LED": _resolve_capital(project.led.capital, led_w, component="led"),
        "HVAC": _resolve_capital(project.hvac.capital, project.hvac.P_rated_w, component="hvac"),
        "DEH": _resolve_capital(project.deh.capital, project.deh.P_ref_w, component="deh"),
        "PV": _resolve_capital(
            project.pv.capital,
            pv_kwp,
            legacy_fallback=project.pv.C_pv * pv_kwp,
            component="pv",
        ),
        "Battery": _resolve_capital(
            project.battery.capital,
            battery_kwh,
            legacy_fallback=project.battery.c_energy * battery_kwh,
            component="battery",
        ),
        "Equipment": _resolve_capital(project.equipment_capital, 0, component="equipment"),
        "Envelope": _resolve_capital(project.envelope_capital, 0, component="envelope"),
        "Pump": _resolve_capital(
            project.pump_capital, 0, component="pump"
        ),  # P5-1: pump capital was never counted
    }
    breakdown["total"] = sum(breakdown.values())
    return breakdown


def _crf(i: float, n: float) -> float:
    """Capital Recovery Factor.  Handles i=0 (division-safe)."""
    n = max(n, 1.0)
    if abs(i) < 1e-12:
        return 1.0 / n
    return i * (1 + i) ** n / ((1 + i) ** n - 1)


def _annualized_capital(
    project: DesignProject,
    capital_breakdown: Dict[str, float],
    battery_life_years: Optional[float] = None,
) -> float:
    """CRF-weighted annualised capital using per-component depreciation years.

    P6-4 (group-C coordination): ``battery_life_years`` (from
    ``EnergySystem.calculate_metrics``, P4-15) caps the battery depreciation
    horizon at the cycle-life-derived wear-out when it is shorter than the
    configured depreciation years.  ``None`` (callers that have not measured a
    life yet — e.g. engine.py) falls back to the configured depreciation
    years, so this is backward compatible and numerically identical for
    presets whose battery life exceeds the depreciation horizon.
    """
    battery_dep = project.battery.capital.depreciation_years
    if battery_life_years is not None:
        battery_dep = min(battery_dep, battery_life_years)
    dep_map = {
        "LED": project.led.capital.depreciation_years,
        "HVAC": project.hvac.capital.depreciation_years,
        "DEH": project.deh.capital.depreciation_years,
        "PV": project.pv.capital.depreciation_years,
        "Battery": battery_dep,
        "Equipment": project.equipment_capital.depreciation_years,
        "Envelope": project.envelope_capital.depreciation_years,
        "Pump": project.pump_capital.depreciation_years,  # P5-1: same CRF / own depreciation
    }
    i = project.interest_rate
    total = 0.0
    for comp, dep in dep_map.items():
        total += _crf(i, dep) * capital_breakdown[comp]
    return total


def _compute_lcoe(
    annual_capital: float, annual_om: float, net_grid_cost: float, annual_energy: float
) -> float:
    """Levelised facility cost per kWh of building load.

    (annualised capital + OPEX + net grid purchase) / annual building load,
    with per-component CRF depreciation (not EnergySystem's single-lifetime
    CRF).  It is a *facility full cost per kWh*, not a classical generation
    LCOE; the ``lcoe`` column name is kept so existing CSV consumers are not
    broken (P6-3).
    """
    if annual_energy <= 0:
        return float("inf")
    return (annual_capital + annual_om + net_grid_cost) / annual_energy


def _compute_cost_per_kg_fresh(
    annual_capital: float,
    annual_om: float,
    net_grid_cost: float,
    biomass_kg: float,
    dry_matter_fraction: float = 0.05,
) -> float:
    """$/kg fresh-mass cost."""
    fresh_kg = biomass_kg / dry_matter_fraction
    if fresh_kg <= 0:
        return float("inf")
    return (annual_capital + annual_om + net_grid_cost) / fresh_kg


# ---------------------------------------------------------------------------
# P1-2: incremental investment economics (vs the no-PV / no-battery baseline)
#
# Scope & assumptions (also printed by the CLI next to the best row):
#   * Baseline  : the identical building served entirely from the grid
#                 (pv_area=0, battery=0), priced at the project tariff.
#   * ΔCapital  : PV + battery capital of the config (all other components
#                 are identical to the baseline, so they cancel).
#   * ΔSavings  : baseline grid bill - (config net grid bill + O&M on the
#                 delta capital).  NOTE: the legacy ``annual_savings``
#                 exported from ``EnergySystem.calculate_metrics`` ignores
#                 O&M; the incremental metrics below subtract
#                 ``opex.maintenance_pct x ΔCapital`` — that is the
#                 corrected, auditable口径.
#   * Horizon   : 25 years (= EnergySystem.lifetime).
#   * Prices    : constant tariff, constant PV output (the simulation's
#                 mid-life degradation year — the same year the LCOE pairs
#                 with), constant savings each year.
#   * Battery   : replaced at its cycle-life year
#                 (life = cycle_life / annual cycles) for the battery
#                 capital, discounted — n_extra = ceil(25/life) - 1 units,
#                 the same replacement count as EnergySystem's P4-15 logic.
#   * Discount  : project.interest_rate.
#   * IRR       : hand-rolled bisection on NPV(r) = 0 — no new dependency
#                 (numpy_financial is banned).  NaN (not 0) when no root
#                 exists: ΔSavings <= 0, ΔCapital <= 0, or the bracket
#                 fails (fail-fast, no silent zero).
# ---------------------------------------------------------------------------
def _annuity_factor(r: float, years: float) -> float:
    """Present value of 1 currency/yr over *years* years at rate *r* (r > -1)."""
    if abs(r) < 1e-12:
        return float(years)
    return (1.0 - (1.0 + r) ** (-years)) / r


def _battery_replacement_pv(
    battery_capital: float, battery_life_years: Optional[float], years: float, r: float
) -> float:
    """PV of the battery replacements due within the analysis horizon.

    Replacement count matches ``EnergySystem.calculate_metrics`` (P4-15):
    ``n_extra = ceil(years / life_years) - 1`` units bought at years
    ``k * life_years`` (k = 1..n_extra), each discounted at (1+r)^(-k*life).
    Zero when the battery outlives the horizon, never cycles, or is absent.
    """
    if battery_capital <= 0.0 or battery_life_years is None:
        return 0.0
    life = float(battery_life_years)
    if not np.isfinite(life) or life <= 0.0 or life >= years:
        return 0.0
    n_extra = int(np.ceil(years / life)) - 1
    if n_extra <= 0:
        return 0.0
    return battery_capital * sum((1.0 + r) ** (-(k * life)) for k in range(1, n_extra + 1))


def _incremental_npv(
    delta_capital: float,
    delta_savings: float,
    interest_rate: float,
    years: float,
    replacement_pv: float,
) -> float:
    """Closed-form NPV of the incremental cash flows.

    NPV = -ΔCapital + Σ_{t=1..years} ΔSavings/(1+i)^t - replacements.
    NaN when the discount rate is degenerate (i <= -1) or savings are
    non-finite — NaN means "undefined", never a silent 0.
    """
    if not np.isfinite(delta_savings) or interest_rate <= -1.0:
        return float("nan")
    return -delta_capital + delta_savings * _annuity_factor(interest_rate, years) - replacement_pv


def _incremental_irr(
    delta_capital: float,
    delta_savings: float,
    years: float,
    battery_capital: float,
    battery_life_years: Optional[float],
) -> float:
    """Internal rate of return of the incremental cash flows (bisection).

    Solves NPV(r) = 0 for r in (-0.99, 1e9).  With a mid-life replacement
    the stream is not strictly conventional; bisection returns the root
    bracketed between -0.99 and the first sign change from above.  Returns
    NaN when no root exists (ΔSavings <= 0 — the stream never pays back —
    ΔCapital <= 0, or bracket failure).  Hand-rolled: no numpy_financial.
    """
    if delta_capital <= 0.0 or not np.isfinite(delta_savings) or delta_savings <= 0.0:
        return float("nan")

    def npv_at(r: float) -> float:
        return (
            -delta_capital
            + delta_savings * _annuity_factor(r, years)
            - _battery_replacement_pv(battery_capital, battery_life_years, years, r)
        )

    lo, hi = -0.99, 0.1
    if npv_at(lo) <= 0.0:
        return float("nan")
    while npv_at(hi) > 0.0:
        hi *= 10.0
        if hi > 1e9:
            return float("nan")  # unbracketable (NPV -> -ΔCapital < 0 eventually)
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if npv_at(mid) > 0.0:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------
def _build_energy_system(project: DesignProject) -> EnergySystem:
    """Re-use project PV / battery / tariff defaults for EnergySystem."""
    pv = PVSystem(
        eta_pv=project.pv.eta_pv,
        area_to_power=project.pv.area_to_power,
        N_s=project.pv.N_s,
        I_sc_stc=project.pv.I_sc_stc,
        V_oc_stc=project.pv.V_oc_stc,
        I_mp_stc=project.pv.I_mp_stc,
        V_mp_stc=project.pv.V_mp_stc,
        alpha_sc=project.pv.alpha_sc,
        beta_voc=project.pv.beta_voc,
        NOCT=project.pv.NOCT,
        eta_inv=project.pv.eta_inv,
        C_pv=project.pv.C_pv,
        degradation=project.pv.degradation,
        eta_system=project.pv.eta_system,  # P6-7
    )
    battery = BatterySystem(
        c_energy=project.battery.c_energy,
        c_rate=project.battery.c_rate,
        eta_ch=project.battery.eta_ch,
        eta_dis=project.battery.eta_dis,
        soc_min=project.battery.soc_min,
        soc_max=project.battery.soc_max,
        cycle_life=project.battery.cycle_life,
        allow_grid_charging=project.battery.allow_grid_charging,  # P1-2
    )
    tariff = Tariff(
        hourly_prices=list(project.tariff.hourly_prices),
        export_price=project.tariff.export_price,
    )
    return EnergySystem(pv=pv, battery=battery, tariff=tariff)


def _validate_ranges(ranges: dict) -> None:
    """Raise ValueError if any range is ill-formed or exceeds HARD_LIMITS.

    P5-10: shape checks (dict, [min,max,step] triples, integer step count)
    run FIRST so a malformed range fails here with the parameter name, not
    later as an opaque unpack error.
    """
    if not isinstance(ranges, dict):
        raise ValueError(
            f"parameter_ranges must be a dict of {{name: [min, max, step]}}, "
            f"got {type(ranges).__name__}"
        )
    for name, rng in ranges.items():
        if not isinstance(rng, (list, tuple)) or len(rng) != 3:
            raise ValueError(
                f"parameter_ranges['{name}'] must be a [min, max, step] " f"triple, got {rng!r}"
            )
        lo, hi, step = rng
        if name not in HARD_LIMITS:
            raise ValueError(
                f"Unknown parameter '{name}' in parameter_ranges. "
                f"Known: {sorted(HARD_LIMITS.keys())}"
            )
        hard_lo, hard_hi = HARD_LIMITS[name]
        if lo < hard_lo or hi > hard_hi:
            raise ValueError(
                f"'{name}' range [{lo}, {hi}] exceeds hard limits " f"[{hard_lo}, {hard_hi}]"
            )
        if step <= 0 or hi <= lo:
            raise ValueError(f"Invalid range for '{name}': [{lo}, {hi}, {step}]")
        n_steps = (hi - lo) / step
        if not np.isclose(n_steps, round(n_steps), rtol=1e-9, atol=1e-9):
            raise ValueError(
                f"'{name}' range [{lo}, {hi}, {step}] has a non-integer "
                f"step count: (max-min)/step = {n_steps:.6g}"
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
def sweep_design(project: DesignProject, cache_dir: str = "weather_cache") -> Dict:
    """Enumerate parameter_ranges → build sim per building combo → PVBES eval.

    Returns
    -------
    dict with keys ``results`` (DataFrame, None when no ranges) and ``best``
    (dict or sim result for single-point).  Objective is taken from
    ``project.space.objective`` (default ``"lcoe"``).
    """
    ranges = dict(project.space.parameter_ranges)
    # F7: normalize top-level config name aliases (pv_area_m2 / battery_kwh)
    # to the sweep parameter names (pv_area / battery) before validation.
    for alias, canonical in _RANGE_ALIASES.items():
        if alias in ranges:
            if canonical in ranges:
                raise ValueError(
                    f"parameter_ranges contains both '{alias}' and "
                    f"'{canonical}' — specify only one."
                )
            ranges[canonical] = ranges.pop(alias)
    objective = getattr(project.space, "objective", "lcoe")
    if objective not in _VALID_OBJECTIVES:
        raise ValueError(f"Unknown objective '{objective}'. " f"Valid: {sorted(_VALID_OBJECTIVES)}")

    # ── single-point evaluation ──────────────────────────────────────────
    if not ranges:
        engine = DesignEngine(cache_dir=cache_dir)
        sim = engine.run(project)
        s = sim.summary
        # P6-9: pass through the engine-computed economics so the single-point
        # best dict carries the same keys as a multi-point sweep row (LCOE /
        # capital / grid / PV indicators).  Column names match the sweep rows.
        best = {
            "currency": project.currency,
            "kwh_per_kg_fresh": sim["kwh_per_kg_fresh"],
            "annual_load_kwh": sim["annual_load_kwh"],
            "biomass_kg": sim["biomass_kg"],
            "lcoe": s.get("lcoe"),
            "cost_per_kg_fresh": s.get("specific_cost_per_kg"),
            "capital_total": s.get("capital_total"),
            "annual_om": s.get("annual_om"),
            "annual_grid_cost": s.get("annual_grid_cost_net", 0.0),
            "annual_pv_generation": s.get("pv_generation_kwh", 0.0),
            "annual_grid_import": s.get("grid_import_kwh", 0.0),
            "annual_grid_export": s.get("grid_export_kwh", 0.0),
            "battery_cycles": s.get("battery_cycles", 0.0),
        }
        # P1-2: evaluate-parity + investment columns on the single-point row
        # (user7 audit: sweep CSV and evaluate summary.csv must not diverge).
        best["grid_independence_pct"] = s.get("grid_independence_pct", 0.0)
        best["pv_self_consumption_rate"] = s.get("pv_self_consumption_rate", 0.0)
        _load = np.asarray(sim["load"], dtype=float)
        _hours = np.asarray(sim["weather"]["hour"], dtype=int)
        _es = _build_energy_system(project)
        # Legacy scope (EnergySystem.calculate_metrics): bill savings vs the
        # all-grid baseline; payback = legacy PV+battery capital / savings.
        # NOTE: engine's summary annual_grid_cost_net is rounded to 2 dp, so
        # for an enabled system the legacy savings carry that (±0.005)
        # rounding; when the config IS the baseline (pv=0 & battery=0) the
        # savings are exactly zero by construction.
        _baseline = float(np.sum(_load * _es.tariff.price_array(_hours)))
        _grid_only = float(project.pv_area_m2) <= 0.0 and float(project.battery_kwh) <= 0.0
        _sav = 0.0 if _grid_only else _baseline - s.get("annual_grid_cost_net", 0.0)
        _leg_cap = (
            _es.pv.calculate_costs(float(project.pv_area_m2))["capital_cost"]
            + _es.battery.calculate_costs(float(project.battery_kwh))["capital_cost"]
        )
        best["annual_savings"] = _sav
        best["payback_period"] = (_leg_cap / _sav) if _sav > 0 else float("inf")
        # P1-2 incremental economics vs the no-PV/no-battery baseline (see
        # the assumptions block above _annuity_factor).
        _cap0 = _total_capital(project, float(project.pv_area_m2), float(project.battery_kwh))
        _dcap = _cap0["PV"] + _cap0["Battery"]
        _dsav = (
            0.0
            if _grid_only
            else _baseline
            - (s.get("annual_grid_cost_net", 0.0) + project.opex.maintenance_pct * _dcap)
        )
        _cycles = s.get("battery_cycles", 0.0)
        _life = (
            project.battery.cycle_life / _cycles if _cycles > 0.0 else None
        )  # None -> no replacement (matches EnergySystem's no-cycling case)
        _repl = _battery_replacement_pv(
            _cap0["Battery"], _life, float(_es.lifetime), project.interest_rate
        )
        best["delta_capital"] = _dcap
        best["delta_annual_savings"] = _dsav
        best["npv_25yr"] = _incremental_npv(
            _dcap, _dsav, project.interest_rate, float(_es.lifetime), _repl
        )
        best["irr_pct"] = (
            _incremental_irr(_dcap, _dsav, float(_es.lifetime), _cap0["Battery"], _life) * 100.0
        )
        return {"results": None, "best": best}

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
            np.arange(ranges[n][0], ranges[n][1] + 1e-9, ranges[n][2]) for n in building_names
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

        # P1-2: baseline grid bill for the incremental investment metrics —
        # the same building served entirely from the grid (pv=0, battery=0),
        # priced at the project tariff.  Constant per building combo (the
        # sweep only overrides building/PVBES sizing, never the tariff).
        _load_arr = np.asarray(sim["load"], dtype=float)
        _hours_arr = np.asarray(sim["weather"]["hour"], dtype=int)
        _tariff = Tariff(
            hourly_prices=list(project.tariff.hourly_prices),
            export_price=project.tariff.export_price,
        )
        baseline_grid_cost = _tariff.annual_cost(_load_arr, np.zeros_like(_load_arr), _hours_arr)[
            "net_grid_cost"
        ]

        if pvb_names:
            for A_pv in pv_areas:
                for E_bat in bats:
                    m = es.calculate_metrics(
                        [A_pv, E_bat],
                        sim["weather"],
                        sim["load"],
                        # Mid-life degradation year: LCOE uses CRF over the
                        # lifetime, so pair it with the average (mid-life)
                        # PV output rather than pristine first-year output.
                        year=es.lifetime // 2,
                    )
                    cap = _total_capital(p, A_pv, E_bat)
                    annual_cap = _annualized_capital(p, cap, m.get("battery_life_years"))
                    annual_water_m3 = float(sim.summary.get("annual_water_m3", 0.0))
                    annual_om = (
                        p.opex.maintenance_pct * cap["total"]
                        + p.opex.water_cost_per_m3 * annual_water_m3
                        + p.opex.labor_cost_per_year
                        + p.opex.misc_opex_per_year
                    )
                    net_grid = m["annual_grid_cost"]
                    lcoe = _compute_lcoe(annual_cap, annual_om, net_grid, annual_load)
                    cost_kg = _compute_cost_per_kg_fresh(
                        annual_cap, annual_om, net_grid, biomass_kg, p.growth.dry_matter_fraction
                    )

                    # P1-2 ②: incremental economics vs the no-PV/no-battery
                    # baseline (assumptions: see the block above
                    # _annuity_factor — 25-yr horizon, constant tariff and
                    # mid-life PV output, battery replaced at its cycle-life
                    # year, discount = interest_rate, O&M on delta capital).
                    delta_capital = cap["PV"] + cap["Battery"]
                    delta_savings = baseline_grid_cost - (
                        net_grid + p.opex.maintenance_pct * delta_capital
                    )
                    _life = m.get("battery_life_years")
                    _repl = _battery_replacement_pv(
                        cap["Battery"], _life, float(es.lifetime), p.interest_rate
                    )

                    row = {
                        **base,
                        "currency": p.currency,
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
                        # P1-2 ①: evaluate-parity columns (same names /
                        # rounding as engine.py's summary.csv so user scripts
                        # stop hitting KeyError across the two tables).
                        "grid_independence_pct": round(
                            (1.0 - m["annual_grid_import"] / max(annual_load, 1e-6)) * 100.0, 1
                        ),
                        "pv_self_consumption_rate": round(float(m["pv_self_consumption_rate"]), 4),
                        # Legacy EnergySystem scope: bill savings vs the
                        # all-grid baseline (excludes O&M); payback uses the
                        # legacy PV+battery unit pricing (C_pv / c_energy).
                        "annual_savings": m["annual_savings"],
                        "payback_period": m["payback_period"],
                        # P1-2 ②: incremental (corrected) investment metrics.
                        "delta_capital": delta_capital,
                        "delta_annual_savings": delta_savings,
                        "npv_25yr": _incremental_npv(
                            delta_capital,
                            delta_savings,
                            p.interest_rate,
                            float(es.lifetime),
                            _repl,
                        ),
                        "irr_pct": _incremental_irr(
                            delta_capital, delta_savings, float(es.lifetime), cap["Battery"], _life
                        )
                        * 100.0,
                    }
                    rows.append(row)
                    if best is None or row[objective] < best[objective]:
                        best = row
        else:
            # P6-2: building-only sweep — evaluate the project's FIXED
            # pv_area_m2 / battery_kwh instead of silently assuming grid-only
            # (was _total_capital(p, 0, 0) + net_grid=0.0).  Aligns the
            # multi-point row with the single-point engine path (which runs
            # the energy system at the fixed sizes).  P0-2: when no PV/battery
            # is configured, the full load is still grid import and is priced
            # at the project tariff — identical to the pvb-path's [0, 0] row
            # and to engine's grid-only economics.
            A_pv = float(p.pv_area_m2)
            E_bat = float(p.battery_kwh)
            if A_pv > 0.0 or E_bat > 0.0:
                if es is None:
                    es = _build_energy_system(project)
                m = es.calculate_metrics(
                    [A_pv, E_bat],
                    sim["weather"],
                    sim["load"],
                    year=es.lifetime // 2,
                )
                net_grid = m["annual_grid_cost"]
            else:
                m = None
                tariff = Tariff(
                    hourly_prices=list(project.tariff.hourly_prices),
                    export_price=project.tariff.export_price,
                )
                net_grid = tariff.annual_cost(
                    sim["load"],
                    np.zeros_like(sim["load"]),
                    np.asarray(sim["weather"]["hour"], dtype=int),
                )["net_grid_cost"]
            cap = _total_capital(p, A_pv, E_bat)
            annual_cap = _annualized_capital(p, cap, (m or {}).get("battery_life_years"))
            annual_water_m3 = float(sim.summary.get("annual_water_m3", 0.0))
            annual_om = (
                p.opex.maintenance_pct * cap["total"]
                + p.opex.water_cost_per_m3 * annual_water_m3
                + p.opex.labor_cost_per_year
                + p.opex.misc_opex_per_year
            )
            lcoe = _compute_lcoe(annual_cap, annual_om, net_grid, annual_load)
            cost_kg = _compute_cost_per_kg_fresh(
                annual_cap, annual_om, net_grid, biomass_kg, p.growth.dry_matter_fraction
            )

            # P1-2 ②: incremental economics.  When m is None the config IS
            # the baseline (pv=0 & battery=0): zero delta -> NPV 0.0, IRR
            # NaN (undefined), exactly the grid-only semantics of engine.py.
            _life = (m or {}).get("battery_life_years")
            _years = float(es.lifetime) if es is not None else 25.0
            delta_capital = cap["PV"] + cap["Battery"]
            delta_savings = baseline_grid_cost - (net_grid + p.opex.maintenance_pct * delta_capital)
            _repl = _battery_replacement_pv(cap["Battery"], _life, _years, p.interest_rate)

            row = {
                **base,
                "currency": p.currency,
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
                # P1-2 ①: evaluate-parity columns (0/inf when the config is
                # the grid-only baseline, matching engine.py's summary).
                "grid_independence_pct": (
                    round((1.0 - m["annual_grid_import"] / max(annual_load, 1e-6)) * 100.0, 1)
                    if m is not None
                    else 0.0
                ),
                "pv_self_consumption_rate": (
                    round(float(m["pv_self_consumption_rate"]), 4) if m is not None else 0.0
                ),
                "annual_savings": m["annual_savings"] if m is not None else 0.0,
                "payback_period": m["payback_period"] if m is not None else float("inf"),
                "delta_capital": delta_capital,
                "delta_annual_savings": delta_savings,
                "npv_25yr": _incremental_npv(
                    delta_capital, delta_savings, p.interest_rate, _years, _repl
                ),
                "irr_pct": _incremental_irr(
                    delta_capital, delta_savings, _years, cap["Battery"], _life
                )
                * 100.0,
            }
            if m is not None:
                row.update(
                    {
                        "annual_pv_generation": m["annual_pv_generation"],
                        "annual_grid_import": m["annual_grid_import"],
                        "annual_grid_export": m["annual_grid_export"],
                        "battery_cycles": m["battery_cycles"],
                    }
                )
            rows.append(row)
            if best is None or row[objective] < best[objective]:
                best = row

    results = pd.DataFrame(rows) if rows else pd.DataFrame()
    if not results.empty and objective in results.columns:
        results = results.sort_values(objective)
    return {"results": results, "best": best, "objective": objective}
