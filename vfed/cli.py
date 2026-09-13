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
from .design.engine import DesignEngine, full_load_warnings
from .agent.evaluator import agent_evaluate
from .weather.city_db import lookup_city, city_coords, list_cities
from .pvbes.tariff_db import list_regions, lookup_tariff
from .weather.weather_bridge import WeatherFetchError


def _write_results_csv(df, path: str) -> int:
    """Write *df* to *path*; return 0 on success, 1 on write failure."""
    try:
        df.to_csv(path, index=False)
    except OSError as e:  # FileNotFoundError/IsADirectoryError/PermissionError
        print(
            f"[ERROR] cannot write '{path}': {e}. "
            f"Create the parent directory first (e.g. mkdir -p).",
            file=sys.stderr,
        )
        return 1
    print(f"  Enumeration table -> {path}")
    return 0


def _print_unit_price(
    indent: str,
    label: str,
    capital: float,
    rating: float,
    rating_unit: str,
    currency: str,
    extra: str = "",
) -> None:
    """P0-1 self-check line: 'unit cost = capital / rating' so the pricing
    basis can be verified by hand.  Before the P0-1 fix a PV ``rate_per_watt``
    of 3.5 silently meant 3.5/kWp - a 46.5 kWp array priced at 162 instead
    of 162,000; this line makes such a mismatch visible at a glance.
    Skipped silently when the component has no capital or no rating."""
    if capital > 0 and rating > 0:
        print(
            f"{indent}{label:<16s} = {capital:.0f} {currency} / {rating:.1f} {rating_unit}"
            f" = {capital / rating:.2f} {currency}/{rating_unit}{extra}"
        )


def _print_capital_unit_check(project, currency: str) -> None:
    """P0-1: unit-price self-check for every capitalised component
    (evaluate path - *project* has been through ``engine.run``, so the
    auto-sized HVAC/DEH nameplates are current)."""
    from .design.sweep import _derived_led_power, _total_capital

    cap = _total_capital(project, float(project.pv_area_m2), float(project.battery_kwh))
    pv_kwp = float(project.pv_area_m2) / project.pv.area_to_power
    _pv_extra = f" ({cap['PV'] / pv_kwp / 1000:.2f} {currency}/Wp)" if pv_kwp > 0 else ""
    _print_unit_price("  ", "PV unit cost", cap["PV"], pv_kwp, "kWp", currency, extra=_pv_extra)
    _print_unit_price(
        "  ", "Battery unit", cap["Battery"], float(project.battery_kwh), "kWh", currency
    )
    _print_unit_price("  ", "LED unit cost", cap["LED"], _derived_led_power(project), "W", currency)
    _print_unit_price("  ", "HVAC unit cost", cap["HVAC"], project.hvac.P_rated_w, "W", currency)
    _print_unit_price("  ", "DEH unit cost", cap["DEH"], project.deh.P_ref_w, "W", currency)


# P0-5: shared capital = 0 warning — the evaluate path printed it, the sweep
# path did not, so sweep-only users never learned their "LCOE" is OPEX-only.
# Kept word-for-word identical between the two paths; pure ASCII (no em-dash)
# so it survives GBK consoles.
_CAPITAL_ZERO_WARNING = (
    "[WARNING] all capital costs are zero - the LCOE above covers "
    "OPEX only, not the full facility cost. Set capital costs per "
    "component (mode per_watt x rated W for LED/HVAC/DEH, per_kwp x "
    "kWp for PV, per_kwh x kWh for battery) for a meaningful LCOE."
)

# P0-5: best-row keys that are never swept parameters (metrics + currency);
# used by _print_boundary_hints to pick out the swept axes of a sweep row.
# P1-2: + the investment-metric columns (evaluate-parity + incremental).
_SWEEP_METRIC_KEYS = frozenset(
    {
        "currency",
        "lcoe",
        "cost_per_kg_fresh",
        "kwh_per_kg_fresh",
        "annual_load_kwh",
        "biomass_kg",
        "annual_pv_generation",
        "annual_grid_import",
        "annual_grid_export",
        "battery_cycles",
        "peak_power_kwp",
        "capital_total",
        "annual_capital",
        "annual_om",
        "annual_grid_cost",
        "capital_led",
        "capital_hvac",
        "capital_deh",
        "capital_pv",
        "capital_battery",
        "capital_equipment",
        "capital_envelope",
        # P1-2 investment metrics
        "grid_independence_pct",
        "pv_self_consumption_rate",
        "annual_savings",
        "payback_period",
        "delta_capital",
        "delta_annual_savings",
        "npv_25yr",
        "irr_pct",
    }
)


def _near_endpoint(a: float, b: float) -> bool:
    """Float-tolerant endpoint comparison (np.arange scan grids can carry
    ~1e-12 noise on the last step, so best == range max needs a tolerance)."""
    return abs(a - b) <= 1e-6 * max(1.0, abs(a), abs(b))


def _print_boundary_hints(best, results, indent: str) -> None:
    """P0-5: flag a best design whose swept value sits on a scan-range edge.

    When the optimum equals a range endpoint, the true optimum may lie outside
    the scanned grid (e.g. example_lcoe_full's battery = 40 kWh caps its own
    [0, 40] range).  Report-only hint — the LCOE numbers themselves are never
    altered: example_sweep's pv = 200 m2 edge is a genuine economic optimum
    under market pricing, so the text says "consider widening", not "wrong".
    Range endpoints are read from the enumeration table itself (the Cartesian
    product covers every grid value, so each axis column spans the full
    [min, max] of the scanned range).
    """
    if results is None or getattr(results, "empty", True):
        return
    for key, val in best.items():
        if key in _SWEEP_METRIC_KEYS or key not in results.columns:
            continue
        try:
            bval = float(val)
        except (TypeError, ValueError):
            continue
        col = results[key].astype(float)
        lo, hi = float(col.min()), float(col.max())
        if _near_endpoint(bval, lo):
            endpoint, eval_val = "min", lo
        elif _near_endpoint(bval, hi):
            endpoint, eval_val = "max", hi
        else:
            continue
        if key == "pv_area":
            name, shown = "pv_area", f"{bval:.1f} m2"
        elif key == "battery_kwh":
            name, shown = "battery", f"{bval:.1f} kWh"
        else:
            name, shown = key, f"{bval:g}"
        print(
            f"{indent}[NOTE] optimum at grid boundary - {name} = {shown} is at "
            f"the scan range {endpoint} ({eval_val:g}); "
            f"consider widening the scan range"
        )


# F3: per-section annotations for the generated project YAML.  The data itself
# is always the canonical ``DesignProject.to_dict()`` (schema cannot drift);
# these comments only annotate sections with units / guidance for prosumers.
_YAML_HEADER = (
    "# ============================================================\n"
    "# VFED project configuration\n"
    "# Generated by 'vfed design new'.  All parameters are optional;\n"
    "# edit freely — validation fails fast with clear messages.\n"
    "# Units are annotated per section.  See README.md for the full guide.\n"
    "# ============================================================\n"
)

_YAML_SECTION_COMMENTS = {
    "site": (
        "# ------------------------------------------------------------------\n"
        "# site: location & weather\n"
        "#   lat/lon    - degrees (default = Shanghai 31.2, 121.5)\n"
        "#   city       - pre-downloaded weather name ('vfed design cities');\n"
        "#                offline data exists only for 2025 (year is locked)\n"
        "#   tz_hours   - UTC offset (h)\n"
        "#   tilt, azimuth - PV panel mounting (degrees)\n"
        "# ------------------------------------------------------------------\n"
    ),
    "envelope": (
        "# ------------------------------------------------------------------\n"
        "# envelope: grow room\n"
        "#   V_room      - room volume (m3)\n"
        "#   U_wall_A    - envelope conductance (W/K)\n"
        "#   ach         - infiltration air changes per hour\n"
        "#   C_z         - thermal mass (Wh/K)\n"
        "# ------------------------------------------------------------------\n"
    ),
    "hvac": (
        "# ------------------------------------------------------------------\n"
        "# hvac: air conditioning (cooling + dehumidification by coil)\n"
        "#   P_rated_w   - rated electrical power (W)\n"
        "#   auto_size   - true = size capacity from design load\n"
        "#   cop_mode    - carnot | constant | linear | table\n"
        "#   eta_II / delta_T_evap / delta_T_cond - Carnot model parameters\n"
        "#   datasheet aliases: cooling_capacity_kw (-> Q_cool_nom),\n"
        "#                      cop (-> cop_value), power_w (-> P_rated_w)\n"
        "# ------------------------------------------------------------------\n"
    ),
    "deh": (
        "# ------------------------------------------------------------------\n"
        "# deh: dehumidifier (removes moisture from transpiration)\n"
        "#   P_ref_w     - rated electrical power (W)\n"
        "#   smer        - specific moisture extraction (kg water / kWh)\n"
        "#   control     - vfd (variable speed, part-load SMER penalty)\n"
        "#                 | on_off (full-speed cycling, rated SMER)\n"
        "#   auto_size   - true = size capacity from design moisture load\n"
        "#   M_deh_nom   - alternative spec: nominal removal (L/day)\n"
        "#   datasheet aliases: capacity_l_per_day (-> M_deh_nom),\n"
        "#                      power_w (-> P_ref_w)\n"
        "# ------------------------------------------------------------------\n"
    ),
    "led": (
        "# ------------------------------------------------------------------\n"
        "# led: lighting\n"
        "#   auto_deduce - true: power_w = ppfd_target * covered_area / efficacy\n"
        "#   ppfd_target - light intensity (umol/m2/s)\n"
        "#   efficacy    - LED efficiency (umol/J)\n"
        "#   covered_area- lit canopy area (m2) — set to YOUR grow area!\n"
        "#   photoperiod_hours / light_start_hour - light schedule\n"
        "# ------------------------------------------------------------------\n"
    ),
    "transpiration": (
        "# ------------------------------------------------------------------\n"
        "# transpiration: crop water-loss model\n"
        "#   method - van_henten (coupled to growth) | daily | per_plant | ...\n"
        "# ------------------------------------------------------------------\n"
    ),
    "setpoints": (
        "# ------------------------------------------------------------------\n"
        "# setpoints: indoor climate targets\n"
        "#   T_light / T_dark - temperature during light/dark (deg C)\n"
        "#   RH      - relative humidity (%)\n"
        "#   rh_disease_risk_threshold - disease-risk band lower edge (% RH);\n"
        "#             hours at/above it are counted in rh_disease_risk_hours\n"
        "#   co2_ppm - CO2 concentration (ppm)\n"
        "#   crop_cycle_days - days from seeding to harvest\n"
        "# ------------------------------------------------------------------\n"
    ),
    "growth": (
        "# ------------------------------------------------------------------\n"
        "# growth: Van Henten crop-growth parameters (keep defaults)\n"
        "# c_rad_phot is LETTUCE-CALIBRATED (P0-3R): the default 3.5e-9 kg/J\n"
        "#   anchors modelled yield to the commercial PFAL lettuce band\n"
        "#   30-60 kg fresh/m2/yr (mid-band ~45 at 30 d cycles / 400 umol/m2/s\n"
        "#   / 800 ppm CO2). Basis and cross-checks: vfed/plants/van_henten.py.\n"
        "# Residual uncertainty: single-parameter calibration -- validate\n"
        "#   against YOUR facility's harvest records (adjust growth.c_rad_phot)\n"
        "#   before quoting absolute kwh_per_kg_fresh / cost_per_kg_fresh\n"
        "#   against external data. KPIs stay valid for comparing VFED design\n"
        "#   variants against each other.\n"
        "# ------------------------------------------------------------------\n"
    ),
    "pv": (
        "# ------------------------------------------------------------------\n"
        "# pv: solar array\n"
        "#   area_to_power - m2 per kWp (typical 4.3)\n"
        "#   eta_pv / degradation - panel efficiency / annual loss (fraction)\n"
        "#   C_pv - legacy fallback unit price (currency/kWp, default 500,\n"
        "#          market-anchored; used when no pv.capital block is given)\n"
        "#   capital - use mode 'per_kwp' with rate_per_kwp (currency/kWp):\n"
        "#     e.g. rate_per_kwp: 3500 (RMB) = 3.5 RMB/W (China C&I 2025)\n"
        "# ------------------------------------------------------------------\n"
    ),
    "battery": (
        "# ------------------------------------------------------------------\n"
        "# battery: storage\n"
        "#   c_energy - legacy unit price (currency/kWh)\n"
        "#   capital - use mode 'per_kwh' with rate_per_kwh (currency/kWh)\n"
        "#   c_rate, eta_ch/eta_dis, soc_min/soc_max, cycle_life\n"
        "#   allow_grid_charging - true: buy grid power in valley-price hours\n"
        "#       to charge the battery for peak-hour discharge (TOU arbitrage;\n"
        "#       only when peak > valley/(eta_ch*eta_dis)). Default false =\n"
        "#       PV-charging only (legacy dispatch).\n"
        "# ------------------------------------------------------------------\n"
    ),
    "tariff": (
        "# ------------------------------------------------------------------\n"
        "# tariff: grid prices (24 hourly values, project currency/kWh)\n"
        "#   export_price - feed-in / buy-back rate\n"
        "# ------------------------------------------------------------------\n"
    ),
    "space": (
        "# ------------------------------------------------------------------\n"
        "# space: design sweep\n"
        "#   parameter_ranges - {name: [min, max, step]}; empty = single-point\n"
        "#     building: ppfd_target, efficacy, photoperiod_hours, T_light, ...\n"
        "#     energy  : pv_area (or pv_area_m2), battery (or battery_kwh)\n"
        "#   objective - lcoe | kwh_per_kg_fresh | cost_per_kg_fresh\n"
        "# ------------------------------------------------------------------\n"
    ),
    "equipment_power_w": (
        "# ------------------------------------------------------------------\n"
        "# equipment_power_w: constant facility base load (W)\n"
        "# ------------------------------------------------------------------\n"
    ),
    "equipment_capital": (
        "# ------------------------------------------------------------------\n"
        "# capital costs.  mode: direct = total cost;\n"
        "#   per_watt = rate_per_watt x rated W (LED/HVAC/DEH);\n"
        "#   per_kwp  = rate_per_kwp  x rated kWp (PV only);\n"
        "#   per_kwh  = rate_per_kwh  x rated kWh (battery only);\n"
        "# plus cost / depreciation_years as applicable.\n"
        "# NOTE: if ALL capital costs are 0, LCOE covers OPEX only.\n"
        "# ------------------------------------------------------------------\n"
    ),
    "envelope_capital": None,  # same comment already emitted by equipment_capital
    "pump_capital": None,
    "opex": (
        "# ------------------------------------------------------------------\n"
        "# opex: annual operating costs\n"
        "#   labor_cost_per_year / misc_opex_per_year (currency/yr)\n"
        "#   water_cost_per_m3 (currency/m3), maintenance_pct (fraction of capital)\n"
        "# ------------------------------------------------------------------\n"
    ),
    "interest_rate": ("# interest_rate: discount rate (fraction, e.g. 0.06 = 6%)\n"),
    "currency": ("# currency / exchange_rate: monetary units (exchange_rate = currency per USD)\n"),
    "exchange_rate": None,
    "pv_area_m2": (
        "# ------------------------------------------------------------------\n"
        "# energy-system sizing (0 = skip PV/battery)\n"
        "#   pv_area_m2  - PV array area (m2)\n"
        "#   battery_kwh - battery capacity (kWh)\n"
        "# ------------------------------------------------------------------\n"
    ),
    "battery_kwh": None,
}


def _commented_project_yaml(project) -> str:
    """Render *project* as commented YAML for prosumer-friendly editing.

    The YAML data is the canonical ``project.to_dict()`` (schema always in
    sync); comments are inserted only at top-level section boundaries.
    """
    import io
    import yaml

    buf = io.StringIO()
    yaml.safe_dump(project.to_dict(), buf, sort_keys=False, allow_unicode=True)
    lines = buf.getvalue().splitlines()
    out = [_YAML_HEADER.rstrip("\n")]
    emitted = set()
    for line in lines:
        key = line.split(":", 1)[0] if line and line[0] != " " and ":" in line else None
        if key in _YAML_SECTION_COMMENTS and key not in emitted:
            cmt = _YAML_SECTION_COMMENTS[key]
            if cmt is not None:
                out.append(cmt.rstrip("\n"))
            emitted.add(key)
        out.append(line)
    return "\n".join(out) + "\n"


def _cmd_design_new(args):
    preset = preset_609() if args.preset == "609" else preset_default()
    preset.name = args.name
    preset.site.year = args.year if args.year is not None else 2025
    if args.city is not None:
        canonical = lookup_city(args.city)
        if canonical is None:
            print(f"City '{args.city}' not found. Available cities:", file=sys.stderr)
            for c in list_cities():
                print(f"  {c['name']}", file=sys.stderr)
            sys.exit(1)
        preset.site.city = canonical
        coords = city_coords(canonical)
        if coords is not None:
            preset.site.lat, preset.site.lon, preset.site.tz_hours = coords
            print(
                f"Set '{canonical}' -> lat={preset.site.lat:.3f}, "
                f"lon={preset.site.lon:.3f}, tz={preset.site.tz_hours:+.1f} h"
            )
        else:
            print(
                f"[WARN] no pre-downloaded coordinates for '{canonical}'; "
                f"lat/lon may need manual override.",
                file=sys.stderr,
            )
    latlon_given = args.lat is not None or args.lon is not None
    if latlon_given:
        # CRITICAL-1 fix: preset_default/preset_609 hard-code site.city
        # ("Shanghai") so the bundled offline weather file is used on first
        # run.  fetch_weather() gives the city file priority over lat/lon, so
        # leaving city in place silently simulates the preset's city for ANY
        # user-supplied coordinates.  An explicit --lat/--lon must therefore
        # clear city (and conflict with --city).
        if args.city is not None:
            print(
                "[ERROR] --city cannot be combined with --lat/--lon; "
                "use a single location source.",
                file=sys.stderr,
            )
            sys.exit(1)
        if preset.site.city is not None:
            print(
                f"[WARN] clearing preset city='{preset.site.city}'; "
                "weather will follow the given lat/lon instead. "
                "Remember tz_hours still uses the preset value "
                f"({preset.site.tz_hours:+.1f} h) unless edited.",
                file=sys.stderr,
            )
            preset.site.city = None
    if args.lat is not None:
        preset.site.lat = args.lat
    if args.lon is not None:
        preset.site.lon = args.lon
    if args.year is not None:
        preset.site.year = args.year
    if args.tariff is not None:
        rec = lookup_tariff(args.tariff)
        if rec is None:
            print(f"Tariff region '{args.tariff}' not found. Available:", file=sys.stderr)
            for r in list_regions():
                print(f"  {r['id']:15s}  {r['label']}", file=sys.stderr)
            sys.exit(1)
        preset.tariff = TariffConfig(
            hourly_prices=rec["hourly_prices"], export_price=rec["export_price"]
        )
        print(f"Set tariff '{args.tariff}' ({rec['label']})")
    out = Path(args.out) if args.out else Path(args.name + ".yaml")
    if out.exists():
        print(f"  (overwriting existing file: {out})", file=sys.stderr)
    with open(out, "w", encoding="utf-8") as f:
        f.write(_commented_project_yaml(preset))
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
        print(
            f"[ERROR E001] project file not found: '{args.project}'. "
            f"Create one with 'vfed design new <name> [--preset 609]'.",
            file=sys.stderr,
        )
        return 1
    try:
        project = DesignProject.load(args.project)
        from .design.sweep import _validate_ranges

        _validate_ranges(project.space.parameter_ranges)
    except Exception as e:
        print(f"[ERROR E001] invalid project config: {e}", file=sys.stderr)
        return 1
    print(
        f"OK: '{args.project}' is a valid VFED project "
        f"({project.name}, timestep {project.space.timestep_s}s, "
        f"objective {project.space.objective})."
    )
    return 0


def _cmd_evaluate(args):
    """Evaluate a single design — building simulation only (no sweep)."""
    import numpy as np

    if not Path(args.project).is_file():
        print(
            f"[ERROR E001] project file not found: '{args.project}'. "
            f"Create one with 'vfed design new <name> [--preset 609]'.",
            file=sys.stderr,
        )
        return 1
    try:
        project = DesignProject.load(args.project)
    except Exception as e:
        print(f"[ERROR E001] invalid project config: {e}", file=sys.stderr)
        return 1
    engine = DesignEngine(cache_dir=args.cache)
    print(
        f"Fetching weather for ({project.site.lat:.1f}, {project.site.lon:.1f}) "
        f"year {project.site.year} (cache: '{args.cache}')...",
        file=sys.stderr,
    )
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
        print(
            "[ERROR E103] load profile is empty or zero "
            "(check LED power / equipment_power_w / setpoints)",
            file=sys.stderr,
        )
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
        print(
            f"  RH clamp events  = {mc.get('sat_clip_events', 0)} saturation / "
            f"{mc.get('floor_clip_events', 0)} floor "
            f"({mc.get('sat_clip_water_kg', 0):.1f}/{mc.get('floor_clip_water_kg', 0):.1f} kg water)"
        )
    dh = summary.get("dehumidifier_performance")
    if dh:
        print(
            f"  DEH utilization  = {dh.get('deh_utilization', 1.0) * 100:.0f}% "
            f"(removal-limited {dh.get('removal_limited_events', 0)} events, "
            f"{dh.get('removal_limited_water_kg', 0):.1f} kg water)"
        )
        print(
            f"  Dehumidified     = {dh.get('deh_actual_dehum_kg', 0):.1f} kg (DEH) + "
            f"{dh.get('hvac_actual_dehum_kg', 0):.1f} kg (HVAC coil) per yr"
        )
    # P1-1: effective-SMER self-evidence — how much of the rated kg/kWh the
    # chosen control strategy actually delivers (VFD part-load penalty vs
    # full-speed cycling).  Skipped when the DEH never ran.
    sm = summary.get("deh_smer")
    if sm and sm.get("effective_smer_kg_per_kwh") is not None:
        print(
            f"  DEH eff. SMER    = {sm['effective_smer_kg_per_kwh']:.2f} kg/kWh "
            f"(rated {sm.get('rated_smer_kg_per_kwh', 0.0):.2f}, "
            f"mode {sm.get('control_mode', 'vfd')})"
        )
    # P0-4: full-load diagnostics — a device pinned at rated output hour
    # after hour usually means a setpoint the room cannot physically reach
    # (same reporting style as the capital = 0 warning below).
    for _warn in full_load_warnings(summary):
        print(f"  [WARNING] {_warn}")
    if summary.get("lcoe") is not None:
        print(
            f"  LCOE             = {summary['lcoe']:.4f} {getattr(project, 'currency', 'USD')}/kWh"
        )
    capital_total = summary.get("capital_total")
    if capital_total is not None:
        print(f"  Capital total    = {capital_total:.0f} {getattr(project, 'currency', 'USD')}")
        if capital_total <= 0:
            # P0-5: text lives in _CAPITAL_ZERO_WARNING so sweep prints the
            # identical caveat (word-for-word parity between the two paths).
            print(f"  {_CAPITAL_ZERO_WARNING}")
        else:
            # P0-1: unit-price self-check lines (capital / rating per component)
            _print_capital_unit_check(project, getattr(project, "currency", "USD"))
    if project.pv_area_m2 <= 0 and project.battery_kwh <= 0:
        print("  Energy system    = disabled (pv_area_m2=0, battery_kwh=0)")
        # P0-2: self-evidence that electricity IS priced when the energy
        # system is disabled (full load = grid import, cost = load x tariff).
        grid_cost = summary.get("annual_grid_cost_net")
        if grid_cost is not None:
            currency = getattr(project, "currency", "USD")
            print(
                f"  Grid cost (no PV/battery) = {grid_cost:.2f} {currency}/yr "
                f"@ tariff (grid_import_kwh x hourly_prices)"
            )
    pv_gen = summary.get("pv_generation_kwh", 0)
    if pv_gen > 0:
        print(f"  PV generation    = {pv_gen:.0f} kWh/yr")
        print(f"  Grid import      = {summary.get('grid_import_kwh', 0):.0f} kWh/yr")
        print(f"  Grid export      = {summary.get('grid_export_kwh', 0):.0f} kWh/yr")
    if args.export:
        export_dir = Path(args.export)
        export_dir.mkdir(parents=True, exist_ok=True)
        result.save_summary_csv(str(export_dir / "summary.csv"))
        result.save_timeseries_csv(str(export_dir / "timeseries.csv"))
        result.save_monthly_csv(str(export_dir / "monthly.csv"))
        print(f"  Exported        -> {export_dir}/ (summary.csv, timeseries.csv, monthly.csv)")
    return 0


def _cmd_sweep(args):
    """Run design sweep (single-point if parameter_ranges is empty)."""
    if not Path(args.project).is_file():
        print(
            f"[ERROR E001] project file not found: '{args.project}'. "
            f"Create one with 'vfed design new <name> [--preset 609]'.",
            file=sys.stderr,
        )
        return 1
    print(
        f"Loading '{args.project}', fetching weather if needed " f"(cache: '{args.cache}')...",
        file=sys.stderr,
    )
    res = agent_evaluate(args.project, cache_dir=args.cache)
    if not res["success"]:
        print(f"[ERROR {res.get('error_code', '?')}] {res['message']}", file=sys.stderr)
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
        # P0-5: surface the economics that used to be CSV-only on this path —
        # LCOE, annual OPEX and the capital = 0 caveat (same wording as the
        # evaluate branch).  Single-point users previously got none of them.
        lcoe = best.get("lcoe")
        if lcoe is not None:
            print(f"  LCOE                    = {lcoe:.4f} {currency}/kWh")
        annual_om = best.get("annual_om")
        if annual_om is not None:
            print(f"  annual_om               = {annual_om:.0f} {currency}/yr")
        capital_total = best.get("capital_total")
        if capital_total is not None:
            print(f"  Capital total           = {capital_total:.0f} {currency}")
            if capital_total <= 0:
                print(f"  {_CAPITAL_ZERO_WARNING}")
        # P0-1: PV / battery unit-price self-check.  PV area and battery kWh
        # are config-fixed (not swept here), so a re-loaded project gives the
        # same ratings the sweep priced against.
        _sp = DesignProject.load(args.project)
        from .design.sweep import _total_capital as _tc

        _sp_cap = _tc(_sp, float(_sp.pv_area_m2), float(_sp.battery_kwh))
        _sp_kwp = float(_sp.pv_area_m2) / _sp.pv.area_to_power
        _sp_extra = f" ({_sp_cap['PV'] / _sp_kwp / 1000:.2f} {currency}/Wp)" if _sp_kwp > 0 else ""
        _print_unit_price(
            "  ", "PV unit cost", _sp_cap["PV"], _sp_kwp, "kWp", currency, extra=_sp_extra
        )
        _print_unit_price(
            "  ", "Battery unit", _sp_cap["Battery"], float(_sp.battery_kwh), "kWh", currency
        )
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
        # P0-1: PV / battery unit-price self-check for the best design.  The
        # row carries capital_pv / pv_area / capital_battery / battery_kwh;
        # area_to_power comes from the project config (not a sweepable param).
        _bp = DesignProject.load(args.project)
        _bp_kwp = float(best.get("pv_area", 0.0)) / _bp.pv.area_to_power
        _bp_cap_pv = float(best.get("capital_pv", 0.0))
        _bp_extra = f" ({_bp_cap_pv / _bp_kwp / 1000:.2f} {currency}/Wp)" if _bp_kwp > 0 else ""
        _print_unit_price(
            "    ", "PV unit cost", _bp_cap_pv, _bp_kwp, "kWp", currency, extra=_bp_extra
        )
        _print_unit_price(
            "    ",
            "Battery unit",
            float(best.get("capital_battery", 0.0)),
            float(best.get("battery_kwh", 0.0)),
            "kWh",
            currency,
        )
    else:
        # P0-5: the same capital = 0 caveat the evaluate path prints — a
        # sweep-only user previously never saw it and could mistake an
        # OPEX-only "LCOE" for a full facility cost.
        print(f"    {_CAPITAL_ZERO_WARNING}")

    # swept parameter values
    for key, val in best.items():
        if key in (
            "lcoe",
            "cost_per_kg_fresh",
            "kwh_per_kg_fresh",
            "annual_load_kwh",
            "biomass_kg",
            "annual_pv_generation",
            "annual_grid_import",
            "annual_grid_export",
            "battery_cycles",
            "peak_power_kwp",
            "capital_total",
            "annual_capital",
            "annual_om",
            "annual_grid_cost",
            "capital_led",
            "capital_hvac",
            "capital_deh",
            "capital_pv",
            "capital_battery",
            "capital_equipment",
            "capital_envelope",
            # P1-2 investment metrics (printed in the block above)
            "grid_independence_pct",
            "pv_self_consumption_rate",
            "annual_savings",
            "payback_period",
            "delta_capital",
            "delta_annual_savings",
            "npv_25yr",
            "irr_pct",
        ):
            continue
        elif key == "pv_area":
            print(f"    pv_area                 = {val:.1f} m2")
        elif key == "battery_kwh":
            print(f"    battery                 = {val:.1f} kWh")
        else:
            print(f"    {key:24s} = {val}")

    # P1-2: investment metrics on the best row.
    # * annual_savings / payback_period — legacy EnergySystem scope (bill
    #   savings vs the all-grid baseline; legacy PV+battery unit pricing).
    # * delta_* / npv_25yr / irr_pct — incremental (corrected) economics vs
    #   the no-PV/no-battery baseline; assumptions printed below.
    import math

    _sav = best.get("annual_savings")
    _pb = best.get("payback_period")
    if _sav is not None:
        print(f"    annual_savings          = {_sav:.0f} {currency}/yr (legacy bill-savings scope)")
    if _pb is not None:
        _pb_s = "inf" if math.isinf(_pb) else f"{_pb:.1f}"
        print(f"    payback_period          = {_pb_s} yr (legacy scope)")
    _dc = best.get("delta_capital")
    _ds = best.get("delta_annual_savings")
    _npv = best.get("npv_25yr")
    _irr = best.get("irr_pct")
    if _dc is not None:
        print(
            "    [NOTE] npv/irr vs no-PV/battery baseline: 25-yr horizon, "
            "constant tariff, mid-life PV output, battery replaced at its "
            "cycle-life year, discount = interest_rate"
        )
        print(f"    delta_capital           = {_dc:.0f} {currency} (PV + battery capital)")
        print(
            f"    delta_annual_savings    = {_ds:.0f} {currency}/yr "
            "(baseline grid bill - net grid bill - O&M on delta capital)"
        )
        if _ds is not None and _ds > 0:
            print(f"    payback (incremental)   = {_dc / _ds:.1f} yr")
        else:
            print("    payback (incremental)   = inf (delta_annual_savings <= 0)")
        if _npv is not None and _npv == _npv:  # NaN-safe (NaN != NaN)
            print(f"    npv_25yr                = {_npv:.0f} {currency}")
        else:
            print("    npv_25yr                = n/a (undefined incremental cash flow)")
        if _irr is not None and _irr == _irr:
            print(f"    irr_pct                 = {_irr:.1f} %")
        else:
            print(
                "    irr_pct                 = n/a (no IRR: incremental cash flow never pays back)"
            )

    # P0-5: a best design pinned at a scan-range edge usually means the true
    # optimum lies outside the scanned grid (example_lcoe_full: battery = 40
    # kWh caps its own [0, 40] range).  Report-only; never alters results.
    _print_boundary_hints(best, results, "    ")

    print(f"    annual_load_kwh         = {best.get('annual_load_kwh', 0):.0f} kWh/yr")
    print(f"    biomass_kg (dry)        = {best.get('biomass_kg', 0):.1f} kg")
    print(f"    annual_capital          = {best.get('annual_capital', 0):.0f} {currency}/yr")
    # P0-5: annual OPEX is 72-96% of LCOE's numerator — print it next to the
    # annualised capital so the best row is self-evidencing (was CSV-only).
    print(f"    annual_om               = {best.get('annual_om', 0):.0f} {currency}/yr")
    print(f"    annual_grid_cost        = {best.get('annual_grid_cost', 0):.0f} {currency}/yr")
    if "annual_pv_generation" in best:
        print(f"    annual_pv_generation    = {best.get('annual_pv_generation', 0):.0f} kWh/yr")
    if "annual_grid_import" in best:
        print(f"    annual_grid_import      = {best.get('annual_grid_import', 0):.0f} kWh/yr")

    if args.out:
        return _write_results_csv(results, args.out)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="vfed", description="VFED design simulator")
    # Not required=True: a bare `vfed` prints help and exits 2 (P7-9) instead
    # of leaking the internal `arguments required: cmd` message.
    sub = p.add_subparsers(dest="cmd")

    d = sub.add_parser("design", help="project management")
    dsub = d.add_subparsers(dest="dcmd", required=True)
    dn = dsub.add_parser("new", help="create a new project YAML")
    dn.add_argument("name", help="project name (also the default output filename)")
    dn.add_argument(
        "--preset",
        choices=["default", "609"],
        default="default",
        help="starting preset template (default: default)",
    )
    dn.add_argument("--out", default=None, help="output YAML path (default: '<name>.yaml')")
    dn.add_argument(
        "--city", default=None, help="pre-downloaded city name (use 'design cities' to list)"
    )
    dn.add_argument(
        "--lat", type=float, default=None, help="latitude, overrides preset/city (e.g. --lat 31.23)"
    )
    dn.add_argument(
        "--lon",
        type=float,
        default=None,
        help="longitude, overrides preset/city (e.g. --lon 121.47)",
    )
    dn.add_argument("--year", type=int, default=None, help="weather year (default: 2025)")
    dn.add_argument(
        "--tariff", default=None, help="load a regional TOU tariff (use 'design tariffs' to list)"
    )
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
    e.add_argument(
        "--cache", default="weather_cache", help="weather cache directory (default: weather_cache)"
    )
    e.add_argument(
        "--export",
        default=None,
        help="directory to write summary.csv / timeseries.csv / "
        "monthly.csv (created if missing)",
    )
    e.set_defaults(func=_cmd_evaluate)

    s = sub.add_parser("sweep", help="run a design sweep (single-point if no ranges)")
    s.add_argument("project", help="path to the project YAML file")
    s.add_argument(
        "--cache", default="weather_cache", help="weather cache directory (default: weather_cache)"
    )
    s.add_argument("--out", default=None, help="CSV output file for the enumeration table")
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
