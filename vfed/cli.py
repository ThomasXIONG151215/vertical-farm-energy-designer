"""
VFED design simulator CLI (``vfed``).

Commands:
    vfed design new <name> [--preset 609] [--tariff region] [--out path]
    vfed design presets
    vfed design cities
    vfed design tariffs
    vfed validate <project.yaml>
    vfed evaluate <project.yaml> [--cache weather_cache]
    vfed sweep <project.yaml> [--cache weather_cache] [--out results.csv]

The CLI is intentionally dependency-light (argparse) and wraps the parametric
ODE building model + optional PVBES energy system.
"""

import argparse
import sys
from pathlib import Path

from .design.project import DesignProject, TariffConfig
from .design.presets import preset_default, preset_609
from .design.engine import DesignEngine
from .agent.evaluator import agent_evaluate
from .weather.city_db import lookup_city, city_coords, list_cities
from .pvbes.tariff_db import list_regions, lookup_tariff
from .weather.weather_bridge import WeatherFetchError


def _write_results_csv(df, path: str) -> int:
    """Write *df* to *path*; return 0 on success, 1 on write failure."""
    try:
        df.to_csv(path, index=False)
    except OSError as e:  # FileNotFoundError/IsADirectoryError/PermissionError
        print(f"[ERROR] cannot write '{path}': {e}. "
              f"Create the parent directory first (e.g. mkdir -p).",
              file=sys.stderr)
        return 1
    print(f"  Enumeration table -> {path}")
    return 0


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
        coords = city_coords(canonical)
        if coords is not None:
            preset.site.lat, preset.site.lon, preset.site.tz_hours = coords
            print(f"Set '{canonical}' -> lat={preset.site.lat:.3f}, "
                  f"lon={preset.site.lon:.3f}, tz={preset.site.tz_hours:+.1f} h")
        else:
            print(f"[WARN] no pre-downloaded coordinates for '{canonical}'; "
                  f"lat/lon may need manual override.", file=sys.stderr)
    if args.lat is not None:
        preset.site.lat = args.lat
    if args.lon is not None:
        preset.site.lon = args.lon
    if args.year is not None:
        preset.site.year = args.year
    if args.tariff is not None:
        rec = lookup_tariff(args.tariff)
        if rec is None:
            print(f"Tariff region '{args.tariff}' not found. Available:",
                  file=sys.stderr)
            for r in list_regions():
                print(f"  {r['id']:15s}  {r['label']}", file=sys.stderr)
            sys.exit(1)
        preset.tariff = TariffConfig(
            hourly_prices=rec["hourly_prices"], export_price=rec["export_price"])
        print(f"Set tariff '{args.tariff}' ({rec['label']})")
    out = Path(args.out) if args.out else Path(args.name + ".yaml")
    if out.exists():
        print(f"  (overwriting existing file: {out})", file=sys.stderr)
    preset.save(out)
    print(f"Created project '{preset.name}' -> {out}")
    return 0


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


def _cmd_validate(args):
    """Validate a project YAML without running the simulation."""
    if not Path(args.project).is_file():
        print(f"[ERROR E001] project file not found: '{args.project}'. "
              f"Create one with 'vfed design new <name> [--preset 609]'.",
              file=sys.stderr)
        return 1
    try:
        project = DesignProject.load(args.project)
        from .design.sweep import _validate_ranges
        _validate_ranges(project.space.parameter_ranges)
    except Exception as e:
        print(f"[ERROR E001] invalid project config: {e}", file=sys.stderr)
        return 1
    print(f"OK: '{args.project}' is a valid VFED project "
          f"({project.name}, timestep {project.space.timestep_s}s, "
          f"objective {project.space.objective}).")
    return 0


def _cmd_evaluate(args):
    """Evaluate a single design — building simulation only (no sweep)."""
    import numpy as np
    if not Path(args.project).is_file():
        print(f"[ERROR E001] project file not found: '{args.project}'. "
              f"Create one with 'vfed design new <name> [--preset 609]'.",
              file=sys.stderr)
        return 1
    try:
        project = DesignProject.load(args.project)
    except Exception as e:
        print(f"[ERROR E001] invalid project config: {e}", file=sys.stderr)
        return 1
    engine = DesignEngine(cache_dir=args.cache)
    print(f"Fetching weather for ({project.site.lat:.1f}, {project.site.lon:.1f}) "
          f"year {project.site.year} (cache: '{args.cache}')...", file=sys.stderr)
    try:
        result = engine.run(project)
    except WeatherFetchError as e:
        print(f"[ERROR E003] {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"[ERROR E101] building simulation failed: {e}", file=sys.stderr)
        return 1
    summary = result.summary
    annual_load = result.get("load", np.zeros(1)).sum()
    if annual_load <= 0:
        print("[ERROR E103] load profile is empty or zero "
              "(check LED power / equipment_power_w / setpoints)",
              file=sys.stderr)
        return 1
    print(f"Project: {project.name}")
    print(f"  Annual load      = {annual_load:.0f} kWh/yr")
    print(f"  Biomass (dry)    = {result.get('biomass_kg', 0):.1f} kg")
    print(f"  kWh/kg (dry)     = {result.get('kwh_per_kg', 0):.1f}")
    print(f"  kWh/kg (fresh)   = {result.get('kwh_per_kg_fresh', 0):.1f}")
    # Humidity / moisture-control summary — RH control and water use are
    # first-order concerns for prosumers growing leafy greens.
    water_m3 = summary.get("annual_water_m3")
    if water_m3 is not None:
        print(f"  Annual water     = {water_m3:.2f} m3/yr")
    mc = summary.get("moisture_clamp_stats")
    if mc:
        print(f"  RH clamp events  = {mc.get('sat_clip_events', 0)} saturation / "
              f"{mc.get('floor_clip_events', 0)} floor "
              f"({mc.get('sat_clip_water_kg', 0):.1f}/{mc.get('floor_clip_water_kg', 0):.1f} kg water)")
    dh = summary.get("dehumidifier_performance")
    if dh:
        print(f"  DEH utilization  = {dh.get('deh_utilization', 1.0) * 100:.0f}% "
              f"(removal-limited {dh.get('removal_limited_events', 0)} events, "
              f"{dh.get('removal_limited_water_kg', 0):.1f} kg water)")
        print(f"  Dehumidified     = {dh.get('deh_actual_dehum_kg', 0):.1f} kg (DEH) + "
              f"{dh.get('hvac_actual_dehum_kg', 0):.1f} kg (HVAC coil) per yr")
    if summary.get("lcoe") is not None:
        print(f"  LCOE             = {summary['lcoe']:.4f} {getattr(project, 'currency', 'USD')}/kWh")
    capital_total = summary.get("capital_total")
    if capital_total is not None:
        print(f"  Capital total    = {capital_total:.0f} {getattr(project, 'currency', 'USD')}")
        if capital_total <= 0:
            print(f"  [WARNING] all capital costs are zero — the LCOE above covers "
                  f"OPEX only, not the full facility cost. Set capital.cost / "
                  f"capital.rate_per_watt on each component for a meaningful LCOE.")
    if project.pv_area_m2 <= 0 and project.battery_kwh <= 0:
        print(f"  Energy system    = disabled (pv_area_m2=0, battery_kwh=0)")
    pv_gen = summary.get("pv_generation_kwh", 0)
    if pv_gen > 0:
        print(f"  PV generation    = {pv_gen:.0f} kWh/yr")
        print(f"  Grid import      = {summary.get('grid_import_kwh', 0):.0f} kWh/yr")
        print(f"  Grid export      = {summary.get('grid_export_kwh', 0):.0f} kWh/yr")
    return 0


def _cmd_sweep(args):
    """Run design sweep (single-point if parameter_ranges is empty)."""
    if not Path(args.project).is_file():
        print(f"[ERROR E001] project file not found: '{args.project}'. "
              f"Create one with 'vfed design new <name> [--preset 609]'.",
              file=sys.stderr)
        return 1
    print(f"Loading '{args.project}', fetching weather if needed "
          f"(cache: '{args.cache}')...", file=sys.stderr)
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
        dm = res.get("dry_matter_fraction", 0.05)
        print(f"  kWh/kg (fresh, {dm * 100:.0f}% DM) = {best.get('kwh_per_kg_fresh', 0):.1f}")
        print(f"  Annual load             = {best.get('annual_load_kwh', 0):.0f} kWh/yr")
        print(f"  Biomass (dry)           = {best.get('biomass_kg', 0):.1f} kg")
        if args.out:
            import pandas as pd
            return _write_results_csv(pd.DataFrame([best]), args.out)
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
        return _write_results_csv(results, args.out)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="vfed",
                                description="VFED design simulator")
    # Not required=True: a bare `vfed` prints help and exits 2 (P7-9) instead
    # of leaking the internal `arguments required: cmd` message.
    sub = p.add_subparsers(dest="cmd")

    d = sub.add_parser("design", help="project management")
    dsub = d.add_subparsers(dest="dcmd", required=True)
    dn = dsub.add_parser("new", help="create a new project YAML")
    dn.add_argument("name",
                    help="project name (also the default output filename)")
    dn.add_argument("--preset", choices=["default", "609"], default="default",
                    help="starting preset template (default: default)")
    dn.add_argument("--out", default=None,
                    help="output YAML path (default: '<name>.yaml')")
    dn.add_argument("--city", default=None,
                    help="pre-downloaded city name (use 'design cities' to list)")
    dn.add_argument("--lat", type=float, default=None,
                    help="latitude, overrides preset/city (e.g. --lat 31.23)")
    dn.add_argument("--lon", type=float, default=None,
                    help="longitude, overrides preset/city (e.g. --lon 121.47)")
    dn.add_argument("--year", type=int, default=None,
                    help="weather year (default: 2025)")
    dn.add_argument("--tariff", default=None,
                    help="load a regional TOU tariff (use 'design tariffs' to list)")
    dn.set_defaults(func=_cmd_design_new)
    dp = dsub.add_parser("presets", help="list available presets")
    dp.set_defaults(func=_cmd_design_presets)
    dc = dsub.add_parser("cities", help="list pre-downloaded city weather")
    dc.set_defaults(func=_cmd_cities)

    dc2 = dsub.add_parser("tariffs", help="list electricity tariff regions")
    dc2.set_defaults(func=_cmd_tariffs)

    v = sub.add_parser("validate", help="validate a project YAML without running it")
    v.add_argument("project", help="path to the project YAML file")
    v.set_defaults(func=_cmd_validate)

    e = sub.add_parser("evaluate", help="simulate a single design configuration")
    e.add_argument("project", help="path to the project YAML file")
    e.add_argument("--cache", default="weather_cache",
                   help="weather cache directory (default: weather_cache)")
    e.set_defaults(func=_cmd_evaluate)

    s = sub.add_parser("sweep", help="run a design sweep (single-point if no ranges)")
    s.add_argument("project", help="path to the project YAML file")
    s.add_argument("--cache", default="weather_cache",
                   help="weather cache directory (default: weather_cache)")
    s.add_argument("--out", default=None,
                   help="CSV output file for the enumeration table")
    s.set_defaults(func=_cmd_sweep)

    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "cmd", None):
        # Bare `vfed` (or `vfed --help`) — no subcommand given.
        parser.print_help()
        return 2
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
