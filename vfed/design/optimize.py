"""Design+control co-optimization (O5): candidate evaluation and grid search.

Two public entry points:

* ``evaluate_candidate(base, candidate, ...)`` — apply a declarative
  candidate (flat parameter overrides + ``zones`` delta + ``policy`` /
  ``policies`` specs) to a base ``DesignProject``, run one simulation
  and score it with the same economics formulas as ``sweep_design``
  (LCOE / cost-per-kg-fresh / kWh-per-kg-fresh, imported from
  ``sweep.py`` so the口径 is bit-identical by construction).
* ``optimize(base, grid, ...)`` — Cartesian grid search over candidate
  keys (every grid value is a list; ``zones`` / ``policies`` dims carry
  whole dicts), one ``engine.run`` per building combo in declared key
  order, then an inner PV x battery re-dispatch loop over
  ``EnergySystem.calculate_metrics`` — the same two-phase pattern as
  ``sweep_design``.  Optional ``ProcessPoolExecutor`` parallelism over
  the outer combos with a main-process warm-up run first so the weather
  cache is written before the pool opens.

Candidate schema (v1)::

    {
      "schema": 1,                       # optional, must be 1
      "ppfd_target": 250,                # any PARAM_PATH_MAP key
      "pv_area": 20.0,                   # any PARAM_TOPLEVEL_MAP key
      "zones": {"nursery": {"setpoints": {"T_light": 24}}},
      "policy":  {"type": "setpoint_offset", "params": {...}},   # single-zone
      "policies": {"nursery": {"type": ..., "params": {...}}},   # multi-zone
    }

Unknown keys, unknown policy types and schema versions != 1 fail fast
with the offending key name in the error.
"""

from __future__ import annotations

import itertools
from concurrent.futures import ProcessPoolExecutor
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from .control import CONTROL_FIELDS, build_policy, validate_owns
from .engine import DesignEngine
from .project import (
    PARAM_PATH_MAP,
    PARAM_TOPLEVEL_MAP,
    DesignProject,
)
from .sweep import (
    _VALID_OBJECTIVES,
    _annualized_capital,
    _build_energy_system,
    _compute_cost_per_kg_fresh,
    _compute_lcoe,
    _total_capital,
)

__all__ = ["evaluate_candidate", "optimize"]

# Candidate keys that are not flat parameter overrides.
_CANDIDATE_RESERVED = frozenset({"schema", "zones", "policies", "policy"})
_CANDIDATE_SCHEMA = 1

_FLAT_KEYS = frozenset(PARAM_PATH_MAP) | frozenset(PARAM_TOPLEVEL_MAP)

# Metric columns carried on every optimize row / evaluate metrics dict
# (objective values come from the same sweep helpers, so lcoe /
# cost_per_kg_fresh / kwh_per_kg_fresh are always present for ranking).
_METRIC_KEYS = (
    "lcoe",
    "cost_per_kg_fresh",
    "kwh_per_kg_fresh",
    "capital_total",
    "annual_capital",
    "annual_om",
    "annual_grid_cost",
    "annual_load_kwh",
    "biomass_kg",
    "annual_pv_generation",
    "annual_grid_import",
    "annual_grid_export",
    "battery_cycles",
)


def _check_objective(objective: str) -> None:
    if objective not in _VALID_OBJECTIVES:
        raise ValueError(
            f"Unknown objective '{objective}'. Valid: {sorted(_VALID_OBJECTIVES)}"
        )


def _validate_candidate(candidate: Any) -> None:
    """Fail fast on schema version and unknown top-level candidate keys."""
    if not isinstance(candidate, dict):
        raise ValueError(
            f"candidate must be a mapping, got {type(candidate).__name__}"
        )
    schema = candidate.get("schema", _CANDIDATE_SCHEMA)
    if schema != _CANDIDATE_SCHEMA:
        raise ValueError(
            f"candidate schema version {schema!r} is not supported "
            f"(expected {_CANDIDATE_SCHEMA}); refusing to guess its semantics"
        )
    allowed = _CANDIDATE_RESERVED | _FLAT_KEYS
    unknown = [k for k in candidate if k not in allowed]
    if unknown:
        raise ValueError(
            f"unknown candidate key(s) {sorted(unknown)}; supported flat "
            f"parameter keys: {sorted(_FLAT_KEYS)}, structural keys: "
            f"{sorted(_CANDIDATE_RESERVED)}"
        )


def _check_authority_conflicts(flat_keys, zones_delta, policy_specs) -> None:
    """Raise when a candidate/sweep key fights a policy's declared ``owns``.

    Wave 6 authority rule: a policy that owns a control field voids the
    runtime authority of the config keys listed in
    ``CONTROL_FIELDS[field].voids_params``. A candidate that overrides one
    of those flat keys (or a ``zones`` delta that lands on the same field)
    would be silently ignored at runtime, so it is refused up front.

    A policy spec may carry ``"schedule_echo": true`` to declare that the
    config value stays meaningful (the policy merely echoes the schedule);
    such specs skip the conflict check entirely.
    """
    specs = [
        spec
        for spec in policy_specs
        if isinstance(spec, dict) and not spec.get("schedule_echo")
    ]
    voided = {}  # param name -> owning field (first owner wins for message)
    for spec in specs:
        policy = build_policy(spec)
        owns = validate_owns(
            getattr(policy, "owns", None), f"policy spec {spec!r}"
        )
        for fname in owns:
            for param in CONTROL_FIELDS[fname].voids_params:
                voided.setdefault(param, fname)
    for key in flat_keys:
        if key in voided:
            raise ValueError(
                f"candidate key '{key}' is voided by policy field "
                f"'{voided[key]}' (owned control authority); the policy "
                "would silently override it at runtime; remove the key "
                "from the candidate, or opt out with "
                "'\"schedule_echo\": true' in the policy spec"
            )
    if zones_delta:
        rev = {v: k for k, v in PARAM_PATH_MAP.items()}
        for zid, sections in zones_delta.items():
            for section, fields in (sections or {}).items():
                for field in (fields or {}):
                    flat = rev.get((section, field))
                    if flat is not None and flat in voided:
                        raise ValueError(
                            f"zones[{zid}].{section}.{field} maps to config "
                            f"key '{flat}', voided by policy field "
                            f"'{voided[flat]}'; the policy would silently "
                            "override it at runtime; remove the override "
                            "or opt out with "
                            "'\"schedule_echo\": true' in the policy spec"
                        )


def _project_from_candidate(base: DesignProject, candidate: dict) -> DesignProject:
    """Clone *base* with the candidate applied, re-validated by from_dict.

    Flat keys write through ``PARAM_PATH_MAP`` / ``PARAM_TOPLEVEL_MAP``
    (same mechanism as ``sweep._override_project``); the ``zones`` delta
    deep-merges per zone/section onto any existing zones so ``from_dict``
    re-runs the full zone contract validation on the merged project.
    """
    d = base.to_dict()
    for key, value in candidate.items():
        if key in _CANDIDATE_RESERVED:
            continue
        if key in PARAM_TOPLEVEL_MAP:
            d[PARAM_TOPLEVEL_MAP[key]] = value
        else:
            section, field = PARAM_PATH_MAP[key]
            if not isinstance(d.get(section), dict):
                d[section] = {}
            d[section][field] = value
    if "zones" in candidate:
        zones_delta = candidate["zones"]
        if not isinstance(zones_delta, dict) or not zones_delta:
            raise ValueError(
                "candidate 'zones' must be a non-empty mapping "
                "zone_id -> {section: {field: value}}"
            )
        merged = d.get("zones") or {}
        for zid, sections in zones_delta.items():
            if not isinstance(sections, dict):
                raise ValueError(
                    f"candidate zones.{zid} must be a mapping of "
                    f"section -> {{field: value}}, got {type(sections).__name__}"
                )
            zsec = dict(merged.get(zid) or {})
            for sec, fields in sections.items():
                if not isinstance(fields, dict):
                    raise ValueError(
                        f"candidate zones.{zid}.{sec} must be a mapping of "
                        f"field -> value, got {type(fields).__name__}"
                    )
                zsec[sec] = {**(zsec.get(sec) or {}), **fields}
            merged[zid] = zsec
        d["zones"] = merged
    return DesignProject.from_dict(d)


def _policy_seat_from_candidate(candidate: dict) -> Tuple[Optional[Any], Optional[dict]]:
    """Build the (policy, policies) seat for engine.run from the candidate.

    Unknown policy types fail fast via ``build_policy`` with the type
    name in the error.  Seat/zone arity mismatches (``policy`` on a
    multi-zone project, ``policies`` key set != zone ids) are rejected
    by ``DesignEngine.run`` itself.
    """
    multi = candidate.get("policies")
    single = candidate.get("policy")
    if multi is not None and single is not None:
        raise ValueError(
            "candidate cannot carry both 'policies' and 'policy' -- use "
            "'policies' for multi-zone projects, 'policy' for single-zone"
        )
    if single is not None:
        return build_policy(single), None
    if multi is not None:
        if not isinstance(multi, dict) or not multi:
            raise ValueError(
                "candidate 'policies' must be a non-empty mapping "
                "zone_id -> {'type': str, 'params': dict}"
            )
        return None, {zid: build_policy(spec) for zid, spec in multi.items()}
    return None, None


def _economics(
    p: DesignProject,
    sim,
    pv_area: float,
    battery_kwh: float,
    es=None,
) -> Dict[str, float]:
    """Score one (project, sim, pv, battery) point with sweep.py's formulas.

    Same call shapes and helpers as ``sweep_design``'s inner loop:
    ``EnergySystem.calculate_metrics`` re-dispatch at the mid-life year,
    ``_total_capital`` / ``_annualized_capital`` for CAPEX, and the
    imported ``_compute_lcoe`` / ``_compute_cost_per_kg_fresh`` for the
    objective values.
    """
    if es is None:
        es = _build_energy_system(p)
    m = es.calculate_metrics(
        [pv_area, battery_kwh],
        sim["weather"],
        sim["load"],
        dt=1.0,
        year=es.lifetime // 2,
    )
    cap = _total_capital(p, pv_area, battery_kwh)
    annual_cap = _annualized_capital(p, cap, m.get("battery_life_years"))
    annual_water_m3 = float(sim.summary.get("annual_water_m3", 0.0))
    annual_om = (
        p.opex.maintenance_pct * cap["total"]
        + p.opex.water_cost_per_m3 * annual_water_m3
        + p.opex.labor_cost_per_year
        + p.opex.misc_opex_per_year
    )
    net_grid = m["annual_grid_cost"]
    annual_load = sim["annual_load_kwh"]
    biomass_kg = sim["biomass_kg"]
    lcoe = _compute_lcoe(annual_cap, annual_om, net_grid, annual_load)
    cost_kg = _compute_cost_per_kg_fresh(
        annual_cap, annual_om, net_grid, biomass_kg, p.growth.dry_matter_fraction
    )
    return {
        "lcoe": lcoe,
        "cost_per_kg_fresh": cost_kg,
        "kwh_per_kg_fresh": sim["kwh_per_kg_fresh"],
        "capital_total": cap["total"],
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


def _run_combo(
    base: DesignProject,
    candidate: dict,
    cache_dir,
    weather,
    pv_values: List[float],
    bat_values: List[float],
) -> List[dict]:
    """One building combo: one engine.run + inner PV x battery re-dispatch.

    Returns the row dicts (outer param cols + currency + sizing +
    ``_METRIC_KEYS``) in inner-loop order.
    """
    _validate_candidate(candidate)
    p = _project_from_candidate(base, candidate)
    policy, policies = _policy_seat_from_candidate(candidate)
    sim = DesignEngine(cache_dir=cache_dir).run(
        p, weather=weather, policy=policy, policies=policies
    )
    es = _build_energy_system(p)
    base_cols = {k: v for k, v in candidate.items() if k != "schema"}
    rows: List[dict] = []
    for a_pv in pv_values:
        for e_bat in bat_values:
            metrics = _economics(p, sim, a_pv, e_bat, es=es)
            rows.append(
                {
                    **base_cols,
                    "currency": p.currency,
                    "pv_area": a_pv,
                    "battery_kwh": e_bat,
                    **{k: metrics[k] for k in _METRIC_KEYS},
                }
            )
    return rows


def _optimize_worker(args) -> List[dict]:
    """Pool worker: pickle-safe payload (plain dicts / None / DataFrames)."""
    project_dict, candidate, cache_dir, pv_values, bat_values, weather = args
    base = DesignProject.from_dict(project_dict)
    return _run_combo(base, candidate, cache_dir, weather, pv_values, bat_values)


def evaluate_candidate(
    base: DesignProject,
    candidate: dict,
    cache_dir=None,
    weather=None,
    objective: str = "lcoe",
) -> Dict[str, Any]:
    """Evaluate one candidate against *base* and score it.

    Returns ``{"objective": float, "metrics": {...}, "result": SimulationResult}``
    where ``metrics`` carries ``_METRIC_KEYS`` evaluated at the project's
    fixed ``pv_area_m2`` / ``battery_kwh`` sizing (same formulas as
    ``sweep_design``).  ``weather`` passes straight through to
    ``DesignEngine.run``; production callers leave it ``None`` and let
    the engine fetch from ``cache_dir``.
    """
    _check_objective(objective)
    _validate_candidate(candidate)
    specs: List[dict] = []
    if isinstance(candidate.get("policy"), dict):
        specs.append(candidate["policy"])
    if isinstance(candidate.get("policies"), dict):
        specs.extend(
            s for s in candidate["policies"].values() if isinstance(s, dict)
        )
    _check_authority_conflicts(
        [k for k in candidate if k not in _CANDIDATE_RESERVED],
        candidate.get("zones"),
        specs,
    )
    p = _project_from_candidate(base, candidate)
    policy, policies = _policy_seat_from_candidate(candidate)
    sim = DesignEngine(cache_dir=cache_dir).run(
        p, weather=weather, policy=policy, policies=policies
    )
    metrics = _economics(p, sim, float(p.pv_area_m2), float(p.battery_kwh))
    return {"objective": metrics[objective], "metrics": metrics, "result": sim}


def optimize(
    base: DesignProject,
    grid: dict,
    cache_dir=None,
    weather=None,
    objective: str = "lcoe",
    pv_grid=None,
    battery_grid=None,
    n_workers: int = 1,
) -> Dict[str, Any]:
    """Grid-search candidates; two-phase eval like ``sweep_design``.

    Every ``grid`` value is a LIST of values (for ``zones`` / ``policies``
    dims: a list of whole dicts).  Combos enumerate the grid keys in
    DECLARED key order (deterministic); each combo runs the engine once,
    then the inner loop re-dispatches PV x battery through
    ``EnergySystem.calculate_metrics``.

    Returns ``{"results": DataFrame (sorted by objective ascending, stable
    tie-break = combo order), "best": dict, "objective": str}``.

    Wave 6: grid-level flat keys are checked against every declared policy
    spec's ``owns`` up front (``_check_authority_conflicts``).  v1
    simplification: combo-level ``zones`` deltas versus policy specs are
    NOT re-checked here per combo — those conflicts follow
    ``evaluate_candidate`` semantics (raise) and can be opted out of with
    ``"schedule_echo": true`` on the spec.
    """
    _check_objective(objective)
    if not isinstance(grid, dict):
        raise ValueError(
            f"grid must be a dict of name -> list of values, "
            f"got {type(grid).__name__}"
        )
    for name, values in grid.items():
        if not isinstance(values, (list, tuple)):
            raise ValueError(
                f"grid['{name}'] must be a list of values, got "
                f"{type(values).__name__}"
            )
    grid_specs: List[Any] = list(grid.get("policy", []) or [])
    for seat in grid.get("policies", []) or []:
        # policies dim: list of whole {zone_id: spec} dicts
        if isinstance(seat, dict):
            grid_specs.extend(s for s in seat.values() if isinstance(s, dict))
    _check_authority_conflicts(
        [k for k in grid if k not in _CANDIDATE_RESERVED], None, grid_specs
    )
    pv_values: List[float] = [0.0] if pv_grid is None else list(pv_grid)
    bat_values: List[float] = [0.0] if battery_grid is None else list(battery_grid)

    names = list(grid.keys())  # declared key order (dict is ordered)
    combos: List[dict] = [
        dict(zip(names, values))
        for values in itertools.product(*(grid[n] for n in names))
    ]
    if not combos:  # empty product on an empty grid -> one base combo
        combos = [{}]

    chunks: List[List[dict]]
    if n_workers > 1:
        # Warm-up: run combo #1 in the main process FIRST so any weather
        # fetch writes the cache before the pool opens (workers would
        # otherwise race on the same cache file).  The warm-up result is
        # kept, so combo #1 is not computed twice.
        chunks = [
            _run_combo(base, combos[0], cache_dir, weather, pv_values, bat_values)
        ]
        rest = combos[1:]
        if rest:
            project_dict = base.to_dict()
            payload = [
                (project_dict, c, cache_dir, pv_values, bat_values, weather)
                for c in rest
            ]
            with ProcessPoolExecutor(max_workers=n_workers) as ex:
                chunks.extend(list(ex.map(_optimize_worker, payload)))
    else:
        chunks = [
            _run_combo(base, c, cache_dir, weather, pv_values, bat_values)
            for c in combos
        ]

    rows = [row for chunk in chunks for row in chunk]
    results = pd.DataFrame(rows) if rows else pd.DataFrame()
    if not results.empty and objective in results.columns:
        # stable kind: equal-objective rows keep combo order, so two
        # identical optimize() calls return an identical row order.
        results = results.sort_values(objective, kind="stable")
    best = results.iloc[0].to_dict() if not results.empty else None
    return {"results": results, "best": best, "objective": objective}
