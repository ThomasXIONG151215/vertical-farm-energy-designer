"""
VFED design simulator CLI (``vfed``).

Commands:
    vfed design new <name> [--preset 609] [--out path]
    vfed design presets
    vfed optimize <project.yaml> [--cache weather_cache]
    vfed evaluate <project.yaml> --pv-area N --battery M
    vfed sweep <project.yaml> [--out results.csv]

The CLI is intentionally dependency-light (argparse) and wraps the parametric
ODE building model + PVBES energy system.
"""

import argparse
import sys
from pathlib import Path

from .design.project import DesignProject
from .design.presets import preset_default, preset_609
from .design.engine import DesignEngine
from .design.sweep import sweep_design
from .agent.evaluator import agent_evaluate
from .pvbes import PVSystem, BatterySystem, Tariff, EnergySystem
from .weather.geocode import geocode_city


def _cmd_design_new(args):
    preset = preset_609() if args.preset == "609" else preset_default()
    preset.name = args.name
    if args.city is not None:
        try:
            lat, lon = geocode_city(args.city)
            preset.site.lat = lat
            preset.site.lon = lon
            print(f"Geocoded '{args.city}' -> lat={lat:.3f}, lon={lon:.3f}")
        except Exception as e:
            print(f"[WARN] Geocoding failed: {e}. Using preset defaults.", file=sys.stderr)
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


def _cmd_optimize(args):
    res = agent_evaluate(args.project, cache_dir=args.cache, tlps_max=args.tlps_max)
    if not res["success"]:
        print(f"[ERROR {res.get('error_code','?')}] {res['message']}", file=sys.stderr)
        return 1
    best = res["best"]
    m = best["metrics"]
    print(f"Project: {res['project']}")
    print(f"Optimal design: PV={best['pv_area_m2']:.1f} m^2, "
          f"Battery={best['battery_kwh']:.1f} kWh")
    print(f"  LCOE      = {m['lcoe']:.4f} $/kWh")
    print(f"  TLPS      = {m['tlps']:.2f} %")
    print(f"  Capital   = {m['capital_cost']:.0f} $")
    print(f"  Annual sav= {m['annual_savings']:.0f} $/yr")
    print(f"  Payback   = {m['payback_period']:.1f} yr")
    print(f"  PV gen    = {m['annual_pv_generation']:.0f} kWh/yr")
    print(f"  Load      = {res['annual_load_kwh']:.0f} kWh/yr")
    print(f"  Biomass   = {res.get('biomass_kg', 0):.1f} kg (dry)")
    print(f"  kWh/kg    = {res.get('kwh_per_kg_fresh', 0):.1f} (fresh, ~5% DM)")
    if args.out:
        res["results"].to_csv(args.out, index=False)
        print(f"Enumeration table -> {args.out}")
    return 0


def _cmd_evaluate(args):
    project = DesignProject.load(args.project)
    engine = DesignEngine(cache_dir=args.cache)
    sim = engine.run(project)
    load = sim["load"]
    es = EnergySystem(
        pv=PVSystem(C_pv=project.pv.C_pv, area_to_power=project.pv.area_to_power,
                    eta_pv=project.pv.eta_pv, eta_inv=project.pv.eta_inv,
                    NOCT=project.pv.NOCT, N_s=project.pv.N_s,
                    I_sc_stc=project.pv.I_sc_stc, V_oc_stc=project.pv.V_oc_stc,
                    I_mp_stc=project.pv.I_mp_stc, alpha_sc=project.pv.alpha_sc,
                    beta_voc=project.pv.beta_voc),
        battery=BatterySystem(c_energy=project.battery.c_energy,
                              c_rate=project.battery.c_rate,
                              eta_ch=project.battery.eta_ch,
                              eta_dis=project.battery.eta_dis,
                              soc_min=project.battery.soc_min,
                              soc_max=project.battery.soc_max,
                              maintenance=project.battery.maintenance),
        tariff=Tariff(peak_price=project.tariff.peak_price,
                      normal_price=project.tariff.normal_price,
                      valley_price=project.tariff.valley_price,
                      export_price=project.tariff.export_price,
                      peak_hours=list(project.tariff.peak_hours),
                      valley_hours=list(project.tariff.valley_hours)),
    )
    m = es.calculate_metrics([args.pv_area, args.battery], sim["weather"], load)
    for k, v in m.items():
        print(f"  {k:22s} = {v}")
    print(f"  Annual load           = {sim['annual_load_kwh']:.0f} kWh/yr")
    print(f"  Biomass (dry)         = {sim.get('biomass_kg', 0):.1f} kg")
    print(f"  kWh/kg (dry)          = {sim.get('kwh_per_kg', 0):.1f}")
    print(f"  kWh/kg (fresh, ~5%DM) = {sim.get('kwh_per_kg_fresh', 0):.1f}")
    return 0


def _cmd_sweep(args):
    project = DesignProject.load(args.project)
    engine = DesignEngine(cache_dir=args.cache)
    sim = engine.run(project)
    sweep = sweep_design(project, sim["load"], sim["weather"], tlps_max=args.tlps_max)
    out = Path(args.out)
    sweep["results"].to_csv(out, index=False)
    best = sweep["best"]
    if best:
        print(f"Best: PV={best['pv_area_m2']:.1f} m^2, "
              f"Battery={best['battery_kwh']:.1f} kWh, "
              f"LCOE={best['metrics']['lcoe']:.4f} $/kWh")
    print(f"  Annual load = {sim['annual_load_kwh']:.0f} kWh/yr")
    print(f"  Biomass     = {sim.get('biomass_kg', 0):.1f} kg (dry)")
    print(f"  kWh/kg      = {sim.get('kwh_per_kg_fresh', 0):.1f} (fresh, ~5% DM)")
    print(f"Enumeration table ({len(sweep['results'])} configs) -> {out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="vfed", description="VFED design simulator")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("design", help="project management")
    dsub = d.add_subparsers(dest="dcmd", required=True)
    dn = dsub.add_parser("new", help="create a new project YAML")
    dn.add_argument("name")
    dn.add_argument("--preset", choices=["default", "609"], default="default")
    dn.add_argument("--out", default="project.yaml")
    dn.add_argument("--city", default=None, help="resolve lat/lon via Open-Meteo geocoding")
    dn.add_argument("--lat", type=float, default=None)
    dn.add_argument("--lon", type=float, default=None)
    dn.add_argument("--year", type=int, default=None)
    dn.set_defaults(func=_cmd_design_new)
    dp = dsub.add_parser("presets", help="list presets")
    dp.set_defaults(func=_cmd_design_presets)

    o = sub.add_parser("optimize", help="optimize PVBES design")
    o.add_argument("project")
    o.add_argument("--cache", default="weather_cache")
    o.add_argument("--tlps-max", dest="tlps_max", type=float, default=100.0)
    o.add_argument("--out", default=None)
    o.set_defaults(func=_cmd_optimize)

    e = sub.add_parser("evaluate", help="evaluate a single config")
    e.add_argument("project")
    e.add_argument("--pv-area", type=float, required=True)
    e.add_argument("--battery", type=float, required=True)
    e.add_argument("--cache", default="weather_cache")
    e.set_defaults(func=_cmd_evaluate)

    s = sub.add_parser("sweep", help="enumerate design space")
    s.add_argument("project")
    s.add_argument("--cache", default="weather_cache")
    s.add_argument("--tlps-max", dest="tlps_max", type=float, default=100.0)
    s.add_argument("--out", default="sweep_results.csv")
    s.set_defaults(func=_cmd_sweep)
    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
