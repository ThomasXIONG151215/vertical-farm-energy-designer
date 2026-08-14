"""
VFED design simulator CLI (``vfed``).

Commands:
    vfed design new <name> [--preset 609] [--out path]
    vfed design presets
    vfed sweep <project.yaml> [--out results.csv]

The CLI is intentionally dependency-light (argparse) and wraps the parametric
ODE building model + optional PVBES energy system.
"""

import argparse
import sys
from pathlib import Path

from .design.project import DesignProject
from .design.presets import preset_default, preset_609
from .design.engine import DesignEngine
from .design.sweep import sweep_design
from .agent.evaluator import agent_evaluate
from .weather.geocode import geocode_city
from .weather.city_db import lookup_city, list_cities
from .pvbes.tariff_db import lookup_tariff, list_regions


def _currency_label(project: DesignProject) -> str:
    cur = getattr(project, 'currency', 'USD')
    rate = getattr(project, 'exchange_rate', 1.0)
    if cur == "USD" or rate == 1.0:
        return cur
    return f"{cur} (1 USD = {rate:.1f} {cur})"


def _cmd_design_new(args):
    preset = preset_609() if args.preset == "609" else preset_default()
    preset.name = args.name
    preset.site.year = args.year if args.year is not None else 2025
    if args.city is not None:
        canonical = lookup_city(args.city)
        if canonical is None:
            print(f"City '{args.city}' not found. Available cities:",
                  file=sys.stderr)
            for c in list_cities():
                print(f"  {c['name']}", file=sys.stderr)
            sys.exit(1)
        preset.site.city = canonical
        try:
            lat, lon = geocode_city(canonical)
            preset.site.lat = lat
            preset.site.lon = lon
            print(f"Geocoded '{canonical}' -> lat={lat:.3f}, lon={lon:.3f}")
        except Exception as e:
            print(f"[WARN] Geocoding failed: {e}. lat/lon may need manual override.",
                  file=sys.stderr)
    if args.lat is not None:
        preset.site.lat = args.lat
    if args.lon is not None:
        preset.site.lon = args.lon
    if args.year is not None:
        preset.site.year = args.year
    out = Path(args.out)
    preset.save(out)
    print(f"Created project '{preset.name}' -> {out}")


def _cmd_design_presets(args):
    print("Available presets: default, 609 (Fengxian lettuce PFAL)")


def _cmd_cities(args):
    print("Available cities for pre-downloaded weather (2025):")
    for c in list_cities():
        print(f"  {c['name']}")


def _cmd_tariffs(args):
    print("Available electricity tariff regions:")
    for r in list_regions():
        print(f"  {r['id']:15s}  {r['label']}")


def _cmd_evaluate(args):
    """Evaluate a single design — building simulation only (no sweep)."""
    import numpy as np
    try:
        project = DesignProject.load(args.project)
    except Exception as e:
        print(f"[ERROR E001] invalid project config: {e}", file=sys.stderr)
        return 1
    engine = DesignEngine(cache_dir=args.cache)
    try:
        result = engine.run(project)
    except Exception as e:
        print(f"[ERROR E101] building simulation failed: {e}", file=sys.stderr)
        return 1
    summary = result.summary
    annual_load = result.get("load", np.zeros(1)).sum()
    print(f"Project: {project.name}")
    print(f"  Annual load      = {annual_load:.0f} kWh/yr")
    print(f"  Biomass (dry)    = {result.get('biomass_kg', 0):.1f} kg")
    print(f"  kWh/kg (dry)     = {result.get('kwh_per_kg', 0):.1f}")
    print(f"  kWh/kg (fresh)   = {result.get('kwh_per_kg_fresh', 0):.1f}")
    if summary.get("lcoe"):
        print(f"  LCOE             = {summary['lcoe']:.4f} {getattr(project, 'currency', 'USD')}/kWh")
    pv_gen = summary.get("pv_generation_kwh", 0)
    if pv_gen > 0:
        print(f"  PV generation    = {pv_gen:.0f} kWh/yr")
        print(f"  Grid import      = {summary.get('grid_import_kwh', 0):.0f} kWh/yr")
        print(f"  Grid export      = {summary.get('grid_export_kwh', 0):.0f} kWh/yr")
    return 0


def _cmd_sweep(args):
    """Run design sweep (single-point if parameter_ranges is empty)."""
    res = agent_evaluate(args.project, cache_dir=args.cache)
    if not res["success"]:
        print(f"[ERROR {res.get('error_code','?')}] {res['message']}",
              file=sys.stderr)
        return 1

    project = res.get("project", "unnamed")
    currency = res.get("currency", "USD")
    exchange_rate = res.get("exchange_rate", 1.0)
    cur_label = currency
    if currency != "USD" and abs(exchange_rate - 1.0) > 1e-6:
        cur_label = f"{currency} (1 USD = {exchange_rate:.1f} {currency})"

    print(f"Project: {project}  |  Currency: {cur_label}")

    best = res["best"]
    if best is None:
        print("  No results produced.")
        return 1

    results = res["results"]
    if results is None:
        # single-point evaluation (no parameter_ranges in project)
        print(f"  kWh/kg (fresh, ~5% DM) = {best.get('kwh_per_kg_fresh', 0):.1f}")
        print(f"  Annual load             = {best.get('annual_load_kwh', 0):.0f} kWh/yr")
        print(f"  Biomass (dry)           = {best.get('biomass_kg', 0):.1f} kg")
        return 0

    # full sweep — user-defined objective
    objective = res.get("objective", "lcoe")
    obj_labels = {
        "lcoe": "LCOE",
        "kwh_per_kg_fresh": "kWh/kg (fresh)",
        "cost_per_kg_fresh": "Cost/kg (fresh)",
    }
    obj_label = obj_labels.get(objective, objective)
    n_configs = len(results)
    print(f"  Configs enumerated = {n_configs}")
    print(f"\n  Best design (min {obj_label}):")

    lcoe = best.get("lcoe", float("inf"))
    cpk = best.get("cost_per_kg_fresh", float("inf"))
    print(f"    LCOE                    = {lcoe:.4f} {currency}/kWh")
    print(f"    Cost/kg (fresh)        = {cpk:.4f} {currency}/kg")
    print(f"    kWh/kg (fresh)          = {best.get('kwh_per_kg_fresh', 0):.1f}")

    # capital breakdown
    ct = best.get("capital_total", 0)
    if ct > 0:
        print(f"    Total capital           = {ct:.0f} {currency}")

    # swept parameter values
    for key, val in best.items():
        if key in ("lcoe", "cost_per_kg_fresh", "kwh_per_kg_fresh",
                   "annual_load_kwh", "biomass_kg",
                   "annual_pv_generation", "annual_grid_import",
                   "annual_grid_export", "battery_cycles", "peak_power_kwp",
                   "capital_total", "annual_capital", "annual_om",
                   "annual_grid_cost",
                   "capital_led", "capital_hvac", "capital_deh",
                   "capital_pv", "capital_battery",
                   "capital_equipment", "capital_envelope"):
            continue
        elif key == "pv_area":
            print(f"    pv_area                 = {val:.1f} m2")
        elif key == "battery_kwh":
            print(f"    battery                 = {val:.1f} kWh")
        else:
            print(f"    {key:24s} = {val}")

    print(f"    annual_load_kwh         = {best.get('annual_load_kwh', 0):.0f} kWh/yr")
    print(f"    biomass_kg (dry)        = {best.get('biomass_kg', 0):.1f} kg")
    print(f"    annual_capital          = {best.get('annual_capital', 0):.0f} {currency}/yr")
    print(f"    annual_grid_cost        = {best.get('annual_grid_cost', 0):.0f} {currency}/yr")
    if "annual_pv_generation" in best:
        print(f"    annual_pv_generation    = {best.get('annual_pv_generation', 0):.0f} kWh/yr")
    if "annual_grid_import" in best:
        print(f"    annual_grid_import      = {best.get('annual_grid_import', 0):.0f} kWh/yr")

    if args.out:
        results.to_csv(args.out, index=False)
        print(f"  Enumeration table -> {args.out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="vfed",
                                description="VFED design simulator")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("design", help="project management")
    dsub = d.add_subparsers(dest="dcmd", required=True)
    dn = dsub.add_parser("new", help="create a new project YAML")
    dn.add_argument("name")
    dn.add_argument("--preset", choices=["default", "609"], default="default")
    dn.add_argument("--out", default="project.yaml")
    dn.add_argument("--city", default=None,
                    help="pre-downloaded city name (use 'design cities' to list)")
    dn.add_argument("--lat", type=float, default=None)
    dn.add_argument("--lon", type=float, default=None)
    dn.add_argument("--year", type=int, default=None)
    dn.set_defaults(func=_cmd_design_new)
    dp = dsub.add_parser("presets", help="list presets")
    dp.set_defaults(func=_cmd_design_presets)
    dc = dsub.add_parser("cities", help="list available cities for weather")
    dc.set_defaults(func=_cmd_cities)

    dc2 = dsub.add_parser("tariffs", help="list available electricity tariff regions")
    dc2.set_defaults(func=_cmd_tariffs)

    e = sub.add_parser("evaluate", help="evaluate a single design configuration")
    e.add_argument("project")
    e.add_argument("--cache", default="weather_cache")
    e.set_defaults(func=_cmd_evaluate)

    s = sub.add_parser("sweep", help="run design sweep")
    s.add_argument("project")
    s.add_argument("--cache", default="weather_cache")
    s.add_argument("--out", default=None,
                   help="CSV output file for enumeration table")
    s.set_defaults(func=_cmd_sweep)

    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
