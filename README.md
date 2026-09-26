# Vertical Farm Energy Designer (VFED)

> [中文版](./README_zh.md) | English

> An open-source design simulator for **Plant Factories with Artificial Lighting (PFALs)** — couples a first-principles building energy model to a PV-Battery-Grid (PVBES) system for minimum-LCOE solar+storage sizing.

[![GitHub stars](https://img.shields.io/github/stars/ThomasXIONG151215/vertical-farm-energy-designer?style=social)](https://github.com/ThomasXIONG151215/vertical-farm-energy-designer/stargazers)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Python 3.8+](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://www.python.org/)

## Background

Plant Factories with Artificial Lighting (PFALs) — fully enclosed, multi-layer growing facilities that replace sunlight with LEDs — are among the most energy-intensive agricultural systems, consuming **200–500 kWh/m²/year** for lighting, HVAC, and dehumidification combined. Grid electricity dominates operating costs, often exceeding 30% of total production expense.

Integrating rooftop photovoltaics (PV) with battery energy storage (BES) can dramatically reduce grid dependency and operating costs. But the optimal PV array size and battery capacity depend on a complex interplay of factors: geographic location, local climate, building envelope, crop photoperiod schedule, and time-of-use electricity tariff. There is no universal rule of thumb — each facility needs a site-specific design.

**VFED** solves this problem. It simulates a PFAL's hourly energy balance using first-principles physics (wet-air thermodynamics, envelope heat transfer, ODE-based room model), then sweeps PV area × battery capacity to find the design that minimises the **Levelised Cost of Energy (LCOE)**.

> 📄 This tool accompanies the paper:
> **Xiong, T., Cai, W., Hu, Y., Song, M., Qian, T., & Bao, H. (2026).** *Photovoltaic-battery integration strategy in plant factories with artificial lighting.* Energy and Buildings, 361, 117462.
> [DOI: 10.1016/j.enbuild.2026.117462](https://doi.org/10.1016/j.enbuild.2026.117462)

The `research/xiong-pvbes-photoperiod-2026/` directory contains the archived code and experimental data from the published paper. The current active codebase (`vfed/`) replaces the EnergyPlus-based load generator with a pure-Python first-principles ODE solver and adds a parametric design sweep — see [research/xiong-pvbes-photoperiod-2026/](research/xiong-pvbes-photoperiod-2026/) for details.

## How VFED Works

| Challenge | VFED Approach |
|-----------|---------------|
| PFAL loads depend on climate, envelope, and lighting schedule | First-principles ODE solver — room heat & moisture balance, no EnergyPlus dependency |
| PV output varies with location, tilt, and weather | Single-diode PV model with Open-Meteo hourly weather data |
| Battery sizing is a trade-off between cost and self-sufficiency | Parametric sweep over (PV area × battery capacity) → LCOE-optimal design |
| Electricity tariff structure affects economics | Time-of-use tariff model (24-hour price schedule + export price) |
| Plant transpiration adds latent load | 5 transpiration methods — 1 model-coupled (Van Henten) and 4 direct-set (daily / per_plant / daily_per_period / per_plant_per_period) |

## Quick Start

### Install

```bash
git clone https://github.com/ThomasXIONG151215/vertical-farm-energy-designer.git
cd vertical-farm-energy-designer
pip install -e .
# or with dev/test dependencies:
pip install -e ".[dev]"
```

### 1. Create a Design

```bash
vfed design new my_farm --preset 609 --city Shanghai --year 2025
```

Creates `my_farm.yaml` from the Fengxian lettuce preset. The default output name is `<name>.yaml` — use `--out path.yaml` to change it. `--city` fills in latitude/longitude/timezone from the built-in city table (list with `vfed design cities`) and lets the whole quickstart run **fully offline** from the pre-downloaded `data/weather/Shanghai_2025.csv`. For an arbitrary site use `--lat <deg> --lon <deg> [--year YYYY]` instead; the first run then needs a network connection (see "Weather Data" below). `--year` defaults to 2025. A prosumer (no `--preset`)? The default preset is a small ~10 m² room that also runs fully offline — see the *DIY / Prosumer Guide* below.

### 2. Validate the Configuration

```bash
vfed validate my_farm.yaml
```

Checks the YAML against the project schema without running the simulation.

### 3. Evaluate a Configuration

```bash
vfed evaluate my_farm.yaml --cache weather_cache
```

Runs the building simulation for a single configuration and reports annual load, biomass, and energy intensity (kWh/kg of fresh biomass). The `609` preset ships with `pv_area_m2=0` / `battery_kwh=0`, so the energy system is disabled here — you will see `Energy system = disabled`. If a project declares `pv` / `battery` (e.g. `example_lcoe_full.yaml`), this step also reports PV generation and grid import/export. A single full-year run (8,760 hourly steps) takes ~10 s on a typical laptop (machine-dependent).

### 4. Parametric Sweep — find the LCOE-optimal PV + battery

The `609` preset declares no sweep ranges, so `vfed sweep my_farm.yaml` would only re-evaluate that single fixed configuration. To demonstrate the core PV-battery sizing, use the shipped example that declares `space.parameter_ranges`:

```bash
# 3 parameters (ppfd_target × pv_area × battery) = 100 configurations, ~6 s (typical laptop)
vfed sweep example_sweep.yaml --cache weather_cache --out results.csv
```

`--out results.csv` writes the full enumeration table to CSV (one row per configuration). The console prints the best design that minimises the configured objective — `lcoe` (default), `kwh_per_kg_fresh`, or `cost_per_kg_fresh` — including the optimal `pv_area` and `battery` sizes. A longer 225-configuration demo with full capital costs is `example_lcoe_full.yaml`. There is no separate `optimize` command; sizing is done via `sweep`.

### 5. Visualise in the Browser

`vfed-web/` is a browser frontend that runs the same engine via Pyodide. To try it locally:

```bash
cd vfed-web
npm run build   # optional: rebundle worker.js from the vfed/ sources (needs python)
npm start       # serves http://localhost:8000/
```

Open http://localhost:8000/ and configure a design in the browser, or paste a generated YAML into the editor. Deploy to Cloudflare Pages with `npm run deploy`.

### Weather Data — network, cache, offline

Weather is fetched hourly from Open-Meteo by lat/lon/year on first use and cached as CSV under `weather_cache/` (point `evaluate` / `sweep` at a different directory with `--cache <dir>`). Sources, in priority order:

1. **Pre-downloaded city CSV** — `data/weather/{City}_{year}.csv`, available for all 51 built-in cities for **2025** (see `vfed design cities`). No network required; used automatically when the project's `site.city` and year match.
2. **`weather_cache/`** — previously fetched results, reused keyed by lat/lon/year/tilt/azimuth/timezone.
3. **Open-Meteo live** — for any other (lat, lon, year) combination. Requires internet; on failure the CLI aborts with `[ERROR E003]`. To stay offline, use a cached year or pass `--cache`.

For an offline quickstart, stick with a built-in city and `--year 2025`. To run an arbitrary site offline, fetch once while online (`vfed evaluate <yaml> --cache weather_cache`), then reuse the cache. Explicit coordinates take priority over a bundled city: `vfed design new --lat <deg> --lon <deg>` clears the preset's `site.city` (a `[WARN] clearing preset city ...` line is printed at creation) because the lat/lon cache key and the city CSV describe two different sites — keeping the city would silently simulate the wrong climate. The generated YAML then uses the coordinates as the weather cache key (`weather_<lat>_<lon>_<year>_*.csv`) and for the live Open-Meteo fetch on first run (`tz_hours` stays at the preset value unless you edit it). Conversely, if you hand-edit `lat`/`lon` in a YAML that still carries `site.city`, the city CSV keeps winning whenever its year matches — set `site.city: null` to force the lat/lon path. The example sweep files (`example_sweep.yaml`, `example_lcoe_full.yaml`) use year 2023 with explicit lat/lon, so their first run fetches from Open-Meteo (a few seconds, network-dependent) and subsequent runs hit the cache.

#### Weather providers & GHI bias correction (round 22)

`site.weather_provider` selects the hourly weather source and `site.ghi_scale` (band (0.5, 1.5]) multiplies the GHI — and the POA field derived from it — as a mean-bias correction, so POA, PV generation and annual GHI all shift by exactly the same factor. Defaults (`open-meteo`, `1.0`) reproduce every earlier baseline bit-for-bit. Both can be overridden per run without editing the YAML (`evaluate` and `sweep`):

```bash
vfed evaluate my_farm.yaml --provider nasa-power              # one-off source switch
vfed evaluate my_farm.yaml --provider nasa-power --ghi-scale 0.9
```

The two sources never mix on disk: NASA POWER caches carry a `_power` suffix (`weather_..._z8.000_power.csv`) and a POWER city file would be named `{City}_{year}_power.csv`. The scale is applied at the weather-data exit, so the cache itself always stores unscaled provider values — changing `ghi_scale` never invalidates a cache.

**Which source for what?** Independent validation studies do not crown a single winner:

| Variable | Open-Meteo (ERA5) | NASA POWER (MERRA-2/CERES) |
|---|---|---|
| GHI, annual total | high bias in East China (Shanghai 2025: ~1570 kWh/m²/yr vs ~1370 CMA climatology) | closer climatology (measured 1524.3) |
| GHI, hourly diurnal cycle | smallest overestimation (Wang & Wang 2025) | broader hourly spread |
| T2M | slightly better (RMSE 2.04 vs 2.66 K; Huang 2023) | slightly worse |
| RH2M | comparable | comparable |
| WS10M | clearly better (Mi & Liu 2025) | weakest variable (NRMSE ≥ 20%) |

Recommended use: keep `open-meteo` as the coupled-simulation default (best hourly T/RH/WS); use `--provider nasa-power` as an independent GHI cross-check; and use `ghi_scale` to align whichever source you run with your local GHI climatology — e.g. Shanghai 2025 ERA5 1570 → CMA ~1370 gives `ghi_scale: 0.873`.

NASA POWER practical notes: (1) hourly `ALLSKY_SFC_SW_DWN` is reported in Wh/m² per hour — numerically equal to the mean W/m² over the hour and used as-is (no ×3600); (2) VFED always requests `time-standard=UTC` (POWER's default LST would silently shift the day); (3) the `-999` fill value fails fast (any variable, any row). Radiation parameters lag real time by ~3–4 months (meteorology ~2 days); the API is keyless with no quota.

References: Wang & Wang 2025 (hourly GHI validation, ERA5 vs POWER); Huang 2023 (ERA5 vs POWER near-surface temperature); Mi & Liu 2025 (reanalysis wind-speed intercomparison).

## DIY / Prosumer Guide

VFED is a research tool, but the **default preset** is now a usable starting point for a small grow room: a ~10 m² lit canopy in a 40 m³ room, with `auto_size` HVAC and dehumidifier, located in Shanghai with bundled 2025 weather — the whole flow below works **fully offline**.

### 1. Offline quick start

```bash
vfed design new my_farm              # default preset: 10 m² room, Shanghai 2025
vfed evaluate my_farm.yaml --cache weather_cache
```

No `--preset` and no `--city` needed: the default preset sets `site.city: Shanghai`, so the pre-downloaded `data/weather/Shanghai_2025.csv` is used automatically. The generated YAML is fully commented (units + guidance on every section).

### 2. Scale it to your grow room

Open `my_farm.yaml` and edit the numbers to match your facility:

| Your hardware | Edit |
|---|---|
| Lit canopy area | `led.covered_area` (m²) |
| Room size / insulation | `envelope.V_room` (m³), `envelope.U_wall_A` (W/K) |
| Lights | `led.ppfd_target`, `led.efficacy`, `led.photoperiod_hours` |
| Climate targets | `setpoints.T_light` / `setpoints.T_dark` / `setpoints.RH` |
| Crop cycle | `growth.crop_cycle_days`, `transpiration.method` |

`hvac.auto_size: true` and `deh.auto_size: true` derive equipment capacity from your design load automatically — keep them on unless you have a specific unit in mind.

### 3. Enter your actual hardware (datasheet vocabulary)

VFED accepts the numbers printed on a real datasheet. Instead of the internal names (`Q_cool_nom` in kW, `P_rated_w` / `P_ref_w` in W, `M_deh_nom` in L/day) you can write:

```yaml
hvac:
  auto_size: false
  cooling_capacity_kw: 3.5     # datasheet cooling capacity (kW) → Q_cool_nom
  cop: 3.2                     # datasheet COP → cop_value
  power_w: 1200                # rated electrical input (W) → P_rated_w
deh:
  capacity_l_per_day: 12       # datasheet dehumidification (L/day) → M_deh_nom
  power_w: 260                 # rated electrical input (W) → P_ref_w
  smer: 2.0                    # specific moisture extraction (kg water/kWh)
```

Templates generated by `vfed design new` omit canonical sizing keys that sit at their class defaults (placeholders such as `M_deh_nom: 0.0` or `cop_value: 4.0` are not written), so **adding a datasheet key just works** — there is no placeholder line to delete first, and the key you add is the single source for that quantity. The complete alias table is in `vfed/design/project.py` (`HARDWARE_ALIASES`). Canonical names still work unchanged; setting both spellings to the same value collapses to one, while different values are rejected as ambiguous — the error names the usual cause (an older template's placeholder left next to the added alias) and tells you to delete one of the two. When you specify a fixed unit, set `auto_size: false` — otherwise the engine overwrites the capacity with its auto-sized value.

### 4. Add real costs before trusting the economics

`vfed evaluate` warns when `capital_total` is 0 — in that case LCOE is operating cost only, not a design-level number. Add capital per component; **the pricing basis is part of the mode name** (LED / HVAC / DEH are priced per rated watt, PV per kWp, battery per kWh):

```yaml
led:      { capital: { mode: per_watt, rate_per_watt: 1.5 } }    # currency per rated W
hvac:     { capital: { mode: per_watt, rate_per_watt: 1.0 } }    # currency per rated W
deh:      { capital: { mode: per_watt, rate_per_watt: 2.0 } }    # currency per rated W
pv:       { capital: { mode: per_kwp,  rate_per_kwp: 3500 } }    # currency per kWp (= 3.5 currency/W)
battery:  { capital: { mode: per_kwh,  rate_per_kwh: 500 } }     # currency per kWh
```

A `per_watt` mode on `pv` or `battery` is rejected at load time with a migration message: before the P0-1 fix that spelling silently multiplied **kWp** for PV (1000x off the field name — a 46.5 kWp array at "3.5/W" priced out at 162 instead of 162,000) and **kWh** for battery. When a component has no `capital:` block — or the block omits its `cost` key (`cost: null`) — legacy fallback pricing applies (`pv.C_pv` per kWp, default 500 = market-anchored; `battery.c_energy` per kWh). An **explicit `cost: 0.0`** in a `direct` block is a *literal zero-cost component* (round 21, F2): it never falls back, so a project whose capital blocks are all explicit zeros reports `capital_total = 0` and an OPEX-only LCOE — exactly what the template NOTE promises. Negative `cost` values are rejected at load time.

Both `evaluate` and `sweep` print a unit-price self-check line per capitalised component (e.g. `PV unit cost = 162792 RMB / 46.5 kWp = 3500.00 RMB/kWp (3.50 RMB/Wp)`) so the pricing basis can be verified by hand. (`example_lcoe_full.yaml` shows a complete cost model.) Then tune `opex` — especially `labor_cost_per_year` and `misc_opex_per_year`, which dominate small-scale economics.

### 5. Size PV + battery for your site

```yaml
space:
  parameter_ranges:
    pv_area: [0, 50, 10]      # m²
    battery: [0, 20, 5]       # kWh
```

```bash
vfed sweep my_farm.yaml --cache weather_cache --out results.csv
```

`results.csv` is sorted by the objective (LCOE by default); the first row is the best PV × battery combination. The same aliases work in sweep ranges (`pv_area_m2` / `battery_kwh` are accepted). Offline at a different site? Pick one of the 51 built-in cities (`vfed design cities`) and set `site.city` — 2025 weather is bundled for all of them.

### Humidity and moisture results

`vfed evaluate` prints more than energy: annual water use, RH clamp events, DEH utilization, and how much moisture the dehumidifier vs the HVAC coil removed (see the **Output Glossary** under *Interpreting Results* for what these mean). `vfed evaluate ... --export out/` also writes `summary.csv`, `timeseries.csv` (8,760 hourly rows) and `monthly.csv` for your own analysis.

## Architecture

```
┌─────────────┐     ┌──────────────────────────────────────────────┐
│   Weather   │────▶│              Design Engine                   │
│  (Open-Meteo)│     │  (vfed/design/engine.py — ODE integration)   │
└─────────────┘     │                                              │
                    │  ┌──────────┐ ┌──────────┐ ┌──────────────┐ │
                    │  │ Physics  │ │ Devices  │ │   Plants     │ │
                    │  │ psychro- │ │ HVAC     │ │ transpiration│ │
                    │  │ metrics, │ │ dehumid. │ │ Van Henten   │ │
                    │  │ envelope,│ │ LED      │ │              │ │
                    │  │ ODE, SHR │ │ compressor│ │              │ │
                    │  └──────────┘ └──────────┘ └──────────────┘ │
                    └──────────────────┬───────────────────────────┘
                                       │ hourly load profile
                    ┌──────────────────▼───────────────────────────┐
                    │         PVBES Sweep & Optimisation           │
                    │  (vfed/design/sweep.py + vfed/pvbes/)         │
                    │  PVSystem → BatterySystem → Tariff → LCOE   │
                    └──────────────────┬───────────────────────────┘
                                       │
                              LCOE-optimal design
```

## Repository Layout

```
vertical-farm-energy-designer/
├── vfed/                    # Core simulator code
│   ├── physics/            # Psychrometrics, envelope, ODE solver, SHR (sensible heat ratio)
│   ├── devices/            # HVAC, dehumidifier, LED, compressor, lag
│   ├── pvbes/              # PV (single-diode), battery (Zhao 2024), grid (TOU), energy system
│   ├── design/             # Project config (YAML), engine, presets, sweep
│   ├── weather/            # Open-Meteo bridge, Erbs GHI split, POA, geocoding
│   ├── plants/             # Transpiration (5 methods: 1 model-coupled van_henten + 4 direct-set), Van Henten growth model
│   ├── agent/              # Evaluator (preserves agent-cli error-code contract)
│   └── cli.py              # CLI entry point: vfed
├── research/               # Archived research paper code & data (see below)
├── reference/              # Reference literature
├── data/weather/           # Pre-downloaded city weather CSVs (51 cities × 2025)
├── scripts/                # Utility scripts (download_weather_db.py refreshes data/weather/; test_web_yaml.py checks the web YAML contract)
├── tests/                  # Pytest suite (incl. test_project.yaml minimal fixture)
├── weather_cache/          # Cached weather CSVs (auto-generated)
├── pyproject.toml          # Project metadata & dependencies
├── vfed-web/               # Browser visualisation (Pyodide Web Worker)
└── README.md
```

## Research Papers & Data

The `research/xiong-pvbes-photoperiod-2026/` directory contains the archived code and experimental data from the published paper. This code is preserved for reproducibility but is no longer the active codebase — the current simulator lives in `vfed/`.

| Subfolder | Description |
|-----------|-------------|
| `research/xiong-pvbes-photoperiod-2026/` | Original PV-BES optimiser (EnergyPlus-based load generation). Contains the CLI, optimizer, battery model, weather processor, and validation data used in the published results. |

Each subfolder under `research/` has its own `README.md` with detailed documentation.

## CLI Reference

| Command | Description |
|---------|-------------|
| `vfed design new <name>` | Create a project YAML from a preset (default output `<name>.yaml`; options `--preset 609`, `--city`, `--lat`, `--lon`, `--year`, `--tariff`, `--out`) |
| `vfed design presets` | List available presets |
| `vfed design cities` | List built-in cities (pre-downloaded 2025 weather) |
| `vfed design tariffs` | List built-in tariff regions |
| `vfed validate <project.yaml>` | Validate a project YAML without running the simulation |
| `vfed evaluate <project.yaml> [--cache dir] [--export dir] [--tariff region]` | Run the building simulation for one configuration; `--export` writes `summary.csv` / `timeseries.csv` / `monthly.csv` into `dir` |
| `vfed sweep <project.yaml> [--cache dir] [--out results.csv] [--tariff region]` | Enumerate `space.parameter_ranges` (e.g. PV area × battery capacity) into a CSV; evaluate a single fixed configuration if no ranges are declared |

## Configuration

All design parameters live in a single YAML file generated by `vfed design new`. Key sections:

- **site** — latitude, longitude, year, timezone
- **envelope** — U-values, area, solar absorptance, vapour permeance
- **hvac** — rated cooling capacity, COP mode (carnot / constant / linear / table), setpoints
- **deh** — dehumidifier rated capacity, RH setpoints, efficiency model
- **led** — PPFD, efficacy, photoperiod schedule
- **transpiration** — method (van_henten / daily / per_plant / daily_per_period / per_plant_per_period).
  The direct-set defaults share one reference scenario: mature lettuce ≈ **1.5 L/m²/day at 25 plants/m²** (literature band 0.75-2.0 L/m²/day), i.e. **67.5 L/day** on the default 45 m² canopy or **60 mL/plant/day**; the staged defaults use a 0.5/1.0/2.0 L/m²/day seedling→mature ladder. Rescale to your canopy with `daily_water_L = rate × led.covered_area`.
  New: `transpiration.plants_per_m2` (planting density, plants/m², 0-200) — for the per-plant methods it auto-derives `plant_count = round(plants_per_m2 × led.covered_area)` when `plant_count` is 0 (25 plants/m² × 45 m² = 1125 plants), so you can think in density instead of counting plants.
- **growth** — Van Henten growth-model parameters (`c_rad_phot` lettuce-calibrated to the commercial PFAL yield band 30-60 kg fresh/m²/yr; see the yield note under [Interpreting Results](#interpreting-results)).
  All coefficients are SI and feed the one-state carbon balance in `vfed/plants/van_henten.py`: `c_alpha_beta` (assimilate→dry-matter conversion, -), `c_resp_d` (dark respiration, 1/s, Q10 = 2), `c_pl_d` (light extinction, m²/kg), `c_co2_1/2/3` + `c_Gamma` (photosynthesis temperature response and CO₂ compensation point, kg/m³), `initial_dry_weight` (transplant start biomass, kg/m² — `X_d` resets here at every harvest). Keep defaults unless calibrating against your own harvest records.
- **pv** — panel efficiency, NOCT, tilt, azimuth
- **battery** — capacity, C-rates, round-trip efficiency, SOC limits
- **tariff** — electricity price:
  - New format: `hourly_prices` (24 values, index = hour 0-23) + `export_price` (recommended).
  - Legacy format (compatible): `peak_price` / `normal_price` / `valley_price` + `peak_hours` / `valley_hours`, expanded to 24 values on load.
  - Reference tariffs: `vfed design tariffs` lists regions; `vfed design new ... --tariff <region>` loads one directly.
- **space** — optional sweep parameter ranges and objective (`lcoe` / `kwh_per_kg_fresh` / `cost_per_kg_fresh`)
- **opex / equipment_capital / envelope_capital / pump_capital** — capital and operating cost inputs (capital modes: `per_watt` × rated W, `per_kwp` × kWp for PV, `per_kwh` × kWh for battery; see section 4)
- **currency / exchange_rate** — currency settings for cost reporting

## Model Scope & Limitations

VFED's physics and crop models are deliberately simple where the underlying evidence is thin. The bounds below are quantified so results can be read with the right level of trust; see the yield-model calibration note (Lettuce-calibrated `growth.c_rad_phot`, 30-60 kg fresh/m²/yr sanity band) and the Output Glossary under [Interpreting Results](#interpreting-results).

### Crop & growth model

Van Henten biomass responds to light and temperature only — there is no water-stress coupling: a 2.7x change in irrigation moves annual yield by only ~±0.5%. The direct-set transpiration methods likewise carry no stress feedback into the growth model. The photometric response is mildly superlinear with no long-photoperiod penalty, whereas real crops decline beyond 17-18 h of light (marginal returns, tipburn). Annual yield decreases monotonically with `crop_cycle_days` and is sensitive to growth-rate calibration — recalibrate `growth.c_rad_phot` against your own harvest records before quoting absolute numbers (see the 30-60 kg fresh/m²/yr sanity-band warning and the Lettuce-Calibrated note under [Interpreting Results](#interpreting-results)).

### Water parameters

`daily_water_L` / `ml_per_plant_day` (and the `_per_period` variants) represent **photoperiod** water, not 24-h totals: the model keeps transpiring at night, which adds ~7.5% on top of the labelled daily amount. Treat the parameter value as a photoperiod quantity and expect the simulated 24-h total to exceed it by that margin.

### Weather & PV (single year)

The simulation uses a single weather year (default 2025) — there is no inter-annual variability. PV output likewise reflects a lifespan-median year: no degradation and no year-to-year spread.

### Weather data (ERA5) known bias

Weather comes from the Open-Meteo archive API, whose ERA5 reanalysis is known to **overestimate surface solar irradiance over eastern China by ~+15-25%** (Atmosphere 2026: PBIAS 57.4% at daily scale, ME +124 W/m² vs 160 CMA stations; cloud and aerosol extinction are under-represented). For Shanghai 2025 the bundled data yields GHI ≈ 1570 kWh/m²/yr vs NASA POWER 1367 and CMA ground-truth 1250-1300. PV generation and specific yield inherit this bias proportionally (the implied performance ratio stays normal at 0.78-0.87), so treat absolute PV/electricity-saving numbers as optimistic when sourced from ERA5. Check your own annual figure via `summary.annual_ghi_kwh_m2`; a data-source switch or bias-correction option is planned.

### HVAC COP winter ceiling

Heating COP is capped at 4.5 by a hard limit, not by physics — uncapped Carnot values can exceed 17 in winter. The parameter pair (η_II = 0.35, ΔT_cond = 15 K) is not uniquely identifiable: several pairs reproduce the same COP, so treat the cap as an engineering envelope rather than a calibrated physical result.

### Thermal / moisture numerics

The temperature ODE carries an enthalpy-flow term, treated as part of the standard load calculation; its effect is negligible at realistic air-change rates. The humidity integrator uses moist-air mass where dry-air mass is the standard convention (~1-2% effect).

These bounds are documented, not accepted as fixed — future versions may tighten them.

## Interpreting Results

`vfed evaluate` and `vfed sweep` report the same set of economic / energy KPIs. All monetary values are reported in the project's `currency` (default USD); `exchange_rate` is display-only annotation ("1 USD = 7.2 CNY") and **does not convert values**.

> **Yield-model calibration — read before quoting absolute KPIs.** The Van Henten growth coefficient `c_rad_phot` is calibrated for PFAL lettuce (P0-3R): the default `3.5e-9 kg/J` anchors the 609 preset to the mid-band (~45 kg fresh/m²/yr) of the commercial PFAL lettuce range **30-60 kg fresh/m²/yr** (30-day cycles, 400 µmol/m²/s, 800 ppm CO₂), replacing the former literature default that overpredicted yield 2-4x. The derivation and cross-checks (quantum-yield ceiling, per-cycle fresh mass, whole-cycle light-use efficiency) are documented in `vfed/plants/van_henten.py`. Residual uncertainty: this is a **single-parameter calibration** — validate against your facility's harvest records (adjust `growth.c_rad_phot`) before comparing `kwh_per_kg_fresh` / `cost_per_kg_fresh` with external facility data; the KPIs remain valid for comparing VFED design variants against each other.

> **Default OPEX & currency magnitude (P1-7).** If a project YAML omits the `opex` section, USD-scale defaults apply silently: `labor_cost_per_year = 30000` + `misc_opex_per_year = 5000` (currency/yr) — on the bundled presets that is 72-96% of LCOE's numerator. The engine therefore always reports `opex_labor_per_year` / `opex_misc_per_year` / `annual_om_pct_of_cost` (= `annual_om` ÷ (annualised capital + `annual_om` + net grid cost)) in the summary, `vfed evaluate` prints the OPEX share line, and a WARNING fires (at most once per run) when the section was defaulted **and** OPEX exceeds 50% of the annual cost total. Keep magnitudes consistent: write `opex` amounts, `tariff.hourly_prices` and all capital rates in the SAME currency as `currency` — the built-in OPEX defaults are USD-scale presets, so an RMB project that omits them gets USD-magnitude numbers under an RMB label.

### evaluate output (core KPIs)

> **Weather source self-evidence (P2-2).** The first line under `Project:` states which weather dataset actually fed the run: `Weather source  : pre-downloaded city file (Shanghai_2025.csv)`, `cache hit (weather_<lat>_<lon>_<year>_...csv)` or `live fetch (api.open-meteo.com)`. Since P1-3b the bundled city file and the lat/lon cache are two different provenances — check this line before comparing runs. It is console-only and pure ASCII: sweep output never repeats it (a 100-row sweep must not flood), and exported CSV / JSON stay unchanged.

| KPI | summary key / CLI label | Unit | Definition |
|---|---|---|---|
| Annual load | `annual_energy_kwh` / Annual load | kWh/yr | Total building electricity (LED + HVAC + DEH + misc) |
| Harvest (dry) | `annual_harvest_kg` / Biomass (dry) | kg dry/yr | Van Henten annual dry-mass harvest |
| Harvest (fresh) | `annual_harvest_fw_kg` | kg fresh/yr | dry mass ÷ `dry_matter_fraction` |
| Energy intensity | `specific_energy_kwh_per_kg` / kWh/kg (fresh) | kWh/kg fresh | Electricity per kg of fresh crop |
| Dry-matter fraction | `dry_matter_fraction` | — | dry→fresh conversion factor (default 0.05) |
| Water use | `annual_water_m3` | m³/yr | Annual transpiration water |
| Levelised cost | `lcoe` | currency/kWh | (annualised capital + O&M + net grid cost) ÷ annual load. **Note: "facility full cost per kWh of load", not a classic generation LCOE** (column kept for compatibility) |
| Cost per kg | `specific_cost_per_kg` / Cost/kg (fresh) | currency/kg fresh | Full cost ÷ fresh harvest |
| Total capital | `capital_total` | currency | Installed capital (LED+HVAC+DEH+PV+battery+equipment+envelope) |
| Annualised capital | `annual_capital` | currency/yr | CRF annualisation per component depreciation life |
| Annual O&M | `annual_om` | currency/yr | Maintenance (fraction of capital) + water + labour + misc |
| Net grid cost | `annual_grid_cost_net` | currency/yr | Purchase − export revenue |
| PV generation | `pv_generation_kwh` | kWh/yr | Annual PV output |
| Grid import | `grid_import_kwh` | kWh/yr | Annual grid purchases |
| Grid export | `grid_export_kwh` | kWh/yr | Annual grid sales |
| Battery cycles | `battery_cycles` | full cycles/yr | Storage-side throughput ÷ (2 × capacity): (`battery_charge_kwh` × η_ch + `battery_discharge_kwh` ÷ η_dis) ÷ (2 × `battery_kwh`). Terminal-side throughput gives a value higher by 1 − 2η/(1+η²) ≈ 0.44% at η=0.91 (see battery bookkeeping below) |
| PV self-consumption | `pv_self_consumed_kwh` / `pv_self_consumption_rate` | kWh/yr / 0-1 | PV directly serving the load / share of generation |
| Battery discharge | `battery_discharge_kwh` | kWh/yr | Annual battery discharge |
| Battery charge | `battery_charge_kwh` | kWh/yr | Annual battery charge (terminal side, **includes** the year-end reconciliation top-up `battery_recon_grid_kwh`) |
| Battery reconciliation | `battery_recon_grid_kwh` | kWh/yr | Year-end SOC reconciliation energy crossing the grid interface (signed: + grid top-up counted in `grid_import_kwh`, − dump counted in `grid_export_kwh`; see battery bookkeeping below) |
| Annual GHI | `annual_ghi_kwh_m2` | kWh/m²/yr | Annual global horizontal irradiation (hourly `GHI` summed over the aligned year ÷ 1000; same value as `climate.annual_ghi_kwh_m2`) |
| Free energy | `free_energy_kwh` | kWh/yr | PV self-consumed + battery discharge |
| Grid independence | `grid_independence_pct` | % | (1 − grid import ÷ load) × 100; **grid dependency = 100 − this value** |

Additional outputs: `energy_breakdown` (`hvac_pct` / `led_pct` / `deh_pct` / `misc_pct` as fractions, 0.30 = 30%), `monthly` (12-month aggregates), `timeseries` (hourly: `load_kw` / `T_z` / `RH_z` / `E_*_Wh`), `typical_daily` (12 × 24 typical-day loads), `sizing` (auto-sized nameplate values). Only when a project declares `pv` / `battery` does `evaluate` print PV/grid rows. If the energy system is disabled (`pv_area_m2=0` and `battery_kwh=0`), `grid_import_kwh` equals the annual load and electricity is still priced as `grid_import_kwh × tariff` — `annual_grid_cost_net`, `total_electricity_cost`, `lcoe` and `specific_cost_per_kg` include it, matching the sweep path's `(0, 0)` row — while the PV/battery columns (`pv_generation_kwh`, `grid_export_kwh`, `battery_*`, `grid_independence_pct`, …) are 0. See **CSV Column Dictionary** below for the per-column semantics of the three exported CSVs.

### sweep output (results.csv columns)

`vfed sweep --out results.csv` sorts rows by the objective ascending (first row = best); a single-point project (empty `parameter_ranges`) writes a one-row CSV. The column set depends on whether PV/BES is configured or swept.

| Column | Unit | Meaning |
|---|---|---|
| (swept parameter columns) | per parameter | Swept building axes: `ppfd_target` / `efficacy` / `photoperiod_hours` / `light_start_hour` / `T_light` / `T_dark` / `RH` / `co2_ppm` / `crop_cycle_days` |
| `currency` | — | Currency code used for all monetary columns (e.g. USD, CNY) |
| `pv_area` | m² | PV area (sweep axis or fixed value) |
| `battery_kwh` | kWh | Battery capacity (sweep axis or fixed value) |
| `lcoe` | currency/kWh | Objective 1 (default) |
| `cost_per_kg_fresh` | currency/kg fresh | Objective 2 |
| `kwh_per_kg_fresh` | kWh/kg fresh | Objective 3 |
| `capital_total` / `capital_led` / `capital_hvac` / `capital_deh` / `capital_pv` / `capital_battery` / `capital_equipment` / `capital_envelope` | currency | Capital breakdown (pump capital is included in the total but not split out) |
| `annual_capital` | currency/yr | CRF-annualised capital |
| `annual_om` | currency/yr | Annual O&M |
| `annual_grid_cost` | currency/yr | Net grid purchase cost |
| `annual_load_kwh` | kWh/yr | Annual load |
| `biomass_kg` | kg dry/yr | Annual dry-mass harvest |
| `annual_pv_generation` | kWh/yr | Annual PV output |
| `annual_grid_import` | kWh/yr | Annual grid purchases |
| `annual_grid_export` | kWh/yr | Annual grid sales |
| `battery_cycles` | full cycles/yr | Battery cycles |
| `grid_independence_pct` | % | (1 − grid import ÷ load) × 100 |
| `pv_self_consumption_rate` | 0-1 | PV directly serving the load ÷ generation |
| `annual_savings` | currency/yr | Baseline grid bill (all-grid, same load) − net grid bill; **excludes O&M** |
| `payback_period` | yr | **Round 21 (F1) definition change**: (PV+battery capital of the row − the same at pv=0/battery=0) ÷ `annual_savings`. Recomputable from the CSV as `delta_capital ÷ annual_savings` (size-proportional pricing). Before round 21 the numerator used the legacy hidden unit prices `pv.C_pv` + `battery.c_energy`, a value derivable from no other column |
| `delta_capital` | currency | PV + battery capital (all other components cancel vs the no-PV/no-battery baseline) |
| `delta_annual_savings` | currency/yr | `annual_savings` − O&M on `delta_capital` |
| `npv_25yr` | currency | 25-yr NPV of the incremental cash flow (battery replacement discounted at its cycle-life year) |
| `irr_pct` | % | IRR of the same stream (NaN = never pays back) |

All `cost*` / `capital*` / `annual_*` monetary columns are in the project's `currency` (see `currency / exchange_rate`).

### CSV Column Dictionary

`vfed evaluate --export <dir>` writes `summary.csv`, `timeseries.csv` and `monthly.csv`. **Mass semantics: every harvest column is DRY matter (kg DM) unless suffixed `_fw` (fresh weight).** Dict-valued summary cells are Python-literal dicts (parse with `ast.literal_eval`); they never contain numpy reprs.

**RH compliance / disease risk (P1-4):** summary reports how well the RH setpoint was actually held. `rh_setpoint_pct` is the target (`setpoints.RH`); `rh_exceed_hours` / `rh_exceed_pct` count hours with indoor RH **above** the setpoint (strict `>`; `rh_exceed_pct` is a 0-1 fraction of the year); `rh_p95_pct` / `rh_max_pct` give the distribution tail; `rh_disease_risk_hours` counts hours **at or above** `setpoints.rh_disease_risk_threshold` (default 85 % RH — the lower edge of the grey-mould/Botrytis risk band, configurable in the project yaml). All figures derive from the same hourly `RH_z` series exported to timeseries.csv, so they are recomputable from the CSV; a positive risk-hour count emits a pure-ASCII `WARNING`.

summary.csv (single row — scalar KPIs):

| Column | Unit | Meaning / basis |
|---|---|---|
| `annual_energy_kwh` | kWh/yr | Total building electricity (LED + HVAC + DEH + misc) |
| `annual_led_kwh` / `annual_hvac_kwh` | kWh/yr | Annual LED / HVAC electricity (same values as summing the hourly `E_led_Wh` / `E_hvac_Wh`) |
| `hvac_pct` / `deh_pct` / `led_pct` / `misc_pct` | fraction (0-1) | Share of annual energy per device (flattened `energy_breakdown`; 0.30 = 30%) |
| `annual_harvest_kg` | kg DM/yr | Annual dry-matter harvest — **includes** the year-end standing crop |
| `annual_harvest_fw_kg` | kg fresh/yr | `annual_harvest_kg` ÷ `dry_matter_fraction` |
| `harvest_final_standing_kg` | kg DM | Biomass standing in the room at year end (last unfinished cycle). Counted in `annual_harvest_kg` but **in no monthly bucket** — `monthly.harvest_kg` sums to `annual_harvest_kg` − this value |
| `harvest_per_month_avg_kg` | kg DM/yr÷12 | Mean monthly harvest-event mass (events only, standing excluded) |
| `specific_energy_kwh_per_kg` | kWh/kg **fresh** | `annual_energy_kwh` ÷ `annual_harvest_fw_kg` — fresh-weight basis, no `_fw` suffix (kept for compatibility) |
| `specific_cost_per_kg` | currency/kg fresh | (annualised capital + O&M + net grid cost) ÷ fresh harvest |
| `dry_matter_fraction` | — | dry→fresh conversion (default 0.05) |
| `annual_water_m3` | m³/yr | Annual transpiration water |
| `lcoe` | currency/kWh | (annualised capital + O&M + net grid cost) ÷ annual load — facility full cost per kWh, not a generation LCOE |
| `capital_total` / `annual_capital` / `annual_om` | currency, currency/yr, currency/yr | Installed capital / CRF-annualised capital (per component depreciation life; the value folded into `lcoe`) / annual O&M |
| `total_electricity_cost` = `annual_grid_cost_net` | currency/yr | Net grid bill: Σ(`grid_import` × hourly price) − Σ(`grid_export` × `export_price`). Always priced — there is no disabled-tariff mode; a yaml without a `tariff` section uses the defaults (0.10/kWh flat, 0.05 feed-in) |
| `grid_import_kwh` / `grid_export_kwh` / `pv_generation_kwh` | kWh/yr | Grid purchases / sales / PV output (0 on a grid-only run, where import = load) |
| `battery_cycles` / `battery_discharge_kwh` / `battery_charge_kwh` / `battery_recon_grid_kwh` / `pv_self_consumed_kwh` / `pv_self_consumption_rate` / `free_energy_kwh` / `grid_independence_pct` | mixed | Battery throughput & bookkeeping KPIs (see **Battery bookkeeping** below), PV self-consumption, grid independence (see KPI table above) |
| `annual_ghi_kwh_m2` | kWh/m²/yr | Annual GHI insolation of the simulation window (round 21): `Σ GHI ÷ 1000` over the aligned local calendar year — makes the solar resource auditable from summary.csv itself |
| `moisture_clamp_stats` / `temperature_clamp_stats` | dict | Humidity-integrator clip events (saturation cap / zero floor) and temperature clip events |
| `dehumidifier_performance` | dict | Nominal vs actual (inventory-capped) moisture removal; `removal_limited_*` |
| `deh_smer` | dict | Effective / delivered / rated SMER (kg/kWh, compressor input, fan excluded); `deh_comp_energy_kwh` excludes the fan, `deh_total_energy_kwh` includes it |
| `full_load_diagnostics` | dict | Hours/pct/longest streak at rated capacity per device + warning criteria |
| `rh_setpoint_pct` / `rh_exceed_hours` / `rh_exceed_pct` | % / h / fraction (0-1) | RH target and control deviation: hours with indoor RH **above** the setpoint (strict `>`), and their share of the year (see RH compliance note above) |
| `rh_p95_pct` / `rh_max_pct` / `rh_disease_risk_hours` | % / % / h | Indoor-RH 95th percentile and maximum; hours **at or above** `setpoints.rh_disease_risk_threshold` (grey-mould risk band, default 85 % RH, yaml-configurable) |

timeseries.csv (8760 hourly rows):

**Time axis (P1-3b):** the simulation window is the **local calendar year** — hour 0 = local Jan 1 00:00, and monthly buckets are natural months (Jan = 744 h in 2025). The `timestamp` column is ISO8601 **local wall clock** (naive, no UTC offset). The ingestion guard checks every pre-downloaded city file for this alignment (first row = `{year}-01-01 00:00`, 8760/8784 rows, strictly monotonic); a non-conforming file is still used **as-is** — never interpolated — after a grep-able ASCII `WARNING` naming the file and its actual first timestamp. Legacy rotated-window files (first row local 01-01 08:00, tail wrapped into next Jan 1) carry a misleading `+00:00` tag on what are actually local wall-clock values; on load the tag is stripped and the rotated window is reported by the guard (its local Jan 1 00:00-07:00 hours do not exist in the file, so Jan mixes 8 h of next-year Jan 1, ~+0.6% of annual energy). Regenerate such files from Open-Meteo for an aligned window.

| Column | Unit | Meaning |
|---|---|---|
| `hour_of_year` | 0-8759 | Simulation step index |
| `timestamp` | ISO8601 (local wall clock) | `YYYY-MM-DDTHH:MM:SS` per hour, 8760 strictly monotonic unique stamps from `{year}-01-01T00:00:00` |
| `price` | currency/kWh | Tariff price applied to that hour (`tariff.hourly_prices[hour_of_day]`) — makes every `electricity_cost` cell recomputable from the CSV |
| `month` / `day` / `hour_of_day` | — | Labels taken from the weather file (aligned local natural year; see time-axis note above) |
| `T_z` / `RH_z` | °C / % | Indoor air temperature / relative humidity |
| `T_ext` / `RH_ext` | °C / % | Outdoor air temperature / relative humidity |
| `GHI` | W/m² | Global horizontal irradiance |
| `load_kw` | kW | Building electric demand (1-h steps: kW = kWh/h) |
| `E_hvac_Wh` / `E_deh_Wh` / `E_led_Wh` / `E_misc_Wh` | Wh | Hourly electricity per device (misc = `equipment_power_w`) |
| `X_d` | kg DM/m² | Standing dry-biomass density: **sawtooth state variable, reset to `growth.initial_dry_weight` at each harvest, NOT cumulative** |

monthly.csv (12 rows, `month` 1-12 without a year — each bucket is one natural calendar month of the weather year, see the time-axis note above):

| Column | Unit | Meaning / basis |
|---|---|---|
| `energy_kwh__total` / `__hvac` / `__deh` / `__led` / `__misc` | kWh | Monthly electricity per device (sums = annual) |
| `avg_T_z` / `avg_RH_z` | °C / % | Monthly mean indoor conditions |
| `harvest_kg` | kg DM | **Harvest events only** (dry). Sum = `annual_harvest_kg` − `harvest_final_standing_kg` |
| `harvest_fw_kg` | kg fresh | Fresh-weight conversion: `harvest_kg` ÷ `dry_matter_fraction` |
| `water_m3` | m³ | Monthly transpiration water (sums = `annual_water_m3`) |
| `rh_exceed_hours` | h | Monthly hours with indoor RH above the setpoint (12-month sum = `summary.rh_exceed_hours`) |
| `grid_import_kwh` | kWh | Monthly grid purchases (= `energy_kwh__total` on a grid-only run) |
| `electricity_cost` | currency | Monthly net bill: Σ(`grid_import` × hourly tariff price) − Σ(`grid_export` × `export_price`); the 12 values close against `annual_grid_cost_net` (diff < 0.01). Always priced (see tariff note above) |
| `pv_generation_kwh` / `grid_export_kwh` / `battery_net_kwh` | kWh | Only when PV or battery is enabled: monthly PV output / grid sales / net battery energy (discharge − charge) |

### Battery bookkeeping: year-end SOC reconciliation & throughput identities

The battery dispatch starts the year at `soc0` (default 0.5) but is not guaranteed to end there, so the annual energy balance needs one reconciliation entry to close exactly. Three rules make every exported battery number auditable from `summary.csv` alone:

1. **Year-end SOC reconciliation (P4-18).** At the last timestep the SOC is restored to the periodic boundary (`soc0` clamped to [soc_min, soc_max]). If the year ends below the target (e.g. the battery was drawn down to `soc_min`), the deficit `capacity × (soc0 − soc_end)` is topped up **from the grid**: the terminal-side energy `capacity × (soc0 − soc_end) ÷ η_ch` is added to the last hour of both `grid_import` and `battery_charge` — it enters **import, not load**. If the year ends above the target, the surplus is dumped and enters `grid_export` / `battery_discharge` instead. The signed quantity is exported as `battery_recon_grid_kwh` (+ = import, − = export).
   - The annual balance therefore closes **with** the charge term: `pv_generation + grid_import + battery_discharge = load + battery_charge + grid_export` (exact).
   - The charge-free check `grid_import + battery_discharge + pv_self_consumed − load` that some audits use carries a residual of exactly `battery_recon_grid_kwh` — that is the reconciliation top-up, not lost energy.
2. **`battery_cycles` counts storage-side throughput.** `(charge × η_ch + discharge ÷ η_dis) ÷ (2 × capacity)` — both legs converted to energy crossing the cell. If you instead divide terminal-side throughput `(charge + discharge) ÷ (2 × capacity)`, you get a value higher by `1 − 2η/(1+η²)` ≈ **0.443%** at the default η_ch = η_dis = 0.91 — a definitional difference, not an error.
3. **Measured round-trip efficiency identity.** `battery_discharge_kwh ÷ battery_charge_kwh = η_ch × η_dis` (= 0.8281 at the defaults) exactly, because `battery_charge_kwh` already includes the reconciliation top-up. If you derive the charge denominator from the PV columns only (`pv_generation − pv_self_consumed − grid_export`), you must add `battery_recon_grid_kwh` to recover the full denominator — omitting it is what makes a measured RTE look like 0.8303 instead of 0.8281.

On a grid-only run (or `battery_kwh = 0`) all three battery bookkeeping keys are 0.

### Output Glossary (warnings & special outputs)

Plain-language semantics for the summary keys users most often ask about:

- **removal-limited events** — `dehumidifier_performance.removal_limited_events` / `removal_limited_water_kg`. Sub-steps where the DEH / HVAC coil was commanded to condense more vapour than the room actually contained. Each sub-step the engine caps nominal moisture removal to the available room vapour inventory, so the event count tallies the capped sub-steps and `removal_limited_water_kg` is the water that could not be removed (nominal − actual). A large count means the dehumidification capacity exceeds what the room can supply — check the DEH sizing / RH setpoint rather than extrapolating from nameplate capacity.

- **RH clamp** — `moisture_clamp_stats`. The humidity integrator clamps the room's absolute humidity to the physical bounds [0, W_sat(T)] every sub-step:
  - `sat_clip_events` / `sat_clip_water_kg` — moisture condensed at the saturation cap (RH would otherwise exceed 100 %); the latent heat of this water is added back to the room balance.
  - `floor_clip_events` / `floor_clip_water_kg` — moisture "removed" past the zero floor (devices tried to dry the room below 0 kg/kg — phantom condensation); the corresponding phantom condenser heat is backed out of the heat balance.
  
  Occasional events are benign numerical bookkeeping; large water totals mean the moisture balance is being forced past its physical limits (undersized DEH, mis-set setpoints).

- **X_d** — the timeseries.csv `X_d` column: standing in-canopy dry-biomass density (kg DM/m²). It is a **sawtooth state variable**: it grows over each crop cycle and resets to `growth.initial_dry_weight` at every harvest — it is NOT a cumulative production counter. Annual production is `annual_harvest_kg`.

- **LCOE** — `lcoe` is the facility full cost per kWh of load: `(annual_capital + annual_om + annual_grid_cost_net) ÷ annual_load_kwh`. Toy example (any currency): `capital_total` 12,000 depreciated over 10 yr at 6 % interest → CRF ≈ 0.136 → `annual_capital` ≈ 1,630; `annual_om` = 600; `annual_grid_cost_net` = 1,770 → total 4,000/yr; annual load 10,000 kWh → **lcoe = 0.40 currency/kWh**.

## Web Visualisation (vfed-web)

`vfed-web/` is a backend-free browser version of VFED: the real VFED Python code runs inside a **Pyodide Web Worker** (`worker.js`), charts are drawn with Chart.js, and weather data is embedded at build time — the browser **never calls Open-Meteo**.

### Run locally

```bash
cd vfed-web
npm start        # serves http://localhost:8000/ (= python -m http.server 8000)
# open http://localhost:8000
```

Do not double-click `index.html` directly (Web Workers cannot load under `file://`). The first load needs internet (Pyodide + numpy/pandas are fetched from a CDN).

### Built-in presets and the simulation path

- **Built-in presets** `BUILTIN_PRESETS`: `609` (Fengxian Lettuce PFAL), `lettuce_standard` (Lettuce — Standard PFAL).
- **Simulation path**: form → `generateYaml()` → `postMessage({type:'simulate', projectYaml})` → Pyodide in the Worker runs the vfed simulation → results post back → charts render.
- **Weather provenance**: each single-point result displays `Weather source: <source> (<detail>)` from `weather_attrs` (天气来源溯源), hidden when absent.
- **Rebundling**: after changing `vfed/` Python code or updating `weather_cache/`, re-run `python bundle.py` in `vfed-web/` to embed the sources and weather cache into `worker.js`.

## Troubleshooting

The first line of defence is `vfed validate <project.yaml>`: it checks the YAML, `timestep_s`, `space.objective`, and sweep parameter ranges without running a simulation. The same config checks — including the hard limits below — run at load time in **every** entry point (`validate`, `evaluate`, `sweep`), so an out-of-band value fails fast with `[ERROR E001]` before any simulation.

### Error codes

| Code | Meaning | Common triggers | Fix |
|---|---|---|---|
| **E001** | Config error | Missing file, broken/unknown/out-of-range YAML; scalar field outside `HARD_LIMITS`; currency-mismatched `--tariff` region; illegal `parameter_ranges` (unknown name, non-`[min,max,step]` triple, non-integer step, out of hard limits) as reported by `validate` — the `sweep` entry surfaces range violations as **E101** | Regenerate with `vfed design new <name> --preset 609`; locate with `vfed validate <yaml>` |
| **E003** | Weather fetch failed | No network, no cache, missing `requests` package | See "Weather offline" below |
| **E101** | Simulation failed | Engine / energy-system exception (illegal timestep, NaN weather, energy-system error); `parameter_ranges` violations reached via `sweep` (`validate` reports the same violation as E001) | Read the full stderr; `vfed validate`; check `timestep_s` and weather data integrity |
| **E103** | Zero load | Annual load ≤ 0 | Check LED power (with `auto_deduce`: `ppfd_target` × `covered_area` ÷ `efficacy`), `equipment_power_w`, `setpoints` |

### Common problems

1. **`timestep_s` must divide 3600 s.** Rule: `sub=max(1,round(3600/dt))` and `|sub·dt−3600|≤1`. Valid values: 600, 900, 1200, 1800, 3600. `vfed validate` and `vfed evaluate` both reject non-divisors.

2. **Values outside `HARD_LIMITS` (config load fails with E001).** The hard-limit table lives in `vfed/design/project.py` and is enforced **uniformly at all three entry points** (`validate` / `evaluate` / `sweep`): every scalar config field listed below is checked when the YAML loads, and sweep ranges `[min,max,step]` must additionally lie inside the band with an integer `(max−min)/step`. A violation prints the field path, the offending value and the valid band — e.g. `led.ppfd_target: 9999` is rejected before any simulation instead of producing a meaningless result:

   | Parameter | Hard limit | Parameter | Hard limit |
   |---|---|---|---|
   | `ppfd_target` | 50–500 µmol/m²/s | `T_dark` | 10–28 °C |
   | `efficacy` | 1.5–4.0 µmol/J | `RH` | 40–90 % |
   | `photoperiod_hours` | 0–24 h/day | `co2_ppm` | 300–2000 ppm |
   | `light_start_hour` | 0–23 h | `crop_cycle_days` | 15–60 days |
   | `T_light` | 15–30 °C | `pv_area` (`pv_area_m2`) | 0–1000 m² |
   | | | `battery` (`battery_kwh`) | 0–500 kWh |

   The table keys are the `space.parameter_ranges` names; the scalar YAML fields they map to are `led.*` / `setpoints.*` / the top-level `pv_area_m2` / `battery_kwh`.

3. **Weather offline (E003) — three fixes:**
   - Retry online: re-run on a networked machine; the fetch writes `weather_cache/` for later offline reuse.
   - Cache / prefetch: run `vfed evaluate <yaml> --cache weather_cache` once online; legacy cache files are reused automatically (see item 7 for the one-line notice).
   - Offline CSV: place a cache CSV in `weather_cache/` manually (filename includes lat/lon/year; the tilt-aware key also includes tilt/azimuth/tz). In the browser build, weather is embedded via `bundle.py`.

4. **E103 zero load:** usually LED power derives to 0 (`auto_deduce` with `ppfd_target` / `covered_area` / `efficacy` missing) or `equipment_power_w=0`. Run `vfed validate` and check those fields.

5. **LCOE semantics:** `lcoe` is the facility full cost per kWh of load — when comparing projects, note that each project may use a different `currency`.

6. **Tariff currency mismatch (E001).** Every tariff-db region carries its currency (`vfed design tariffs` lists it). `vfed evaluate/sweep --tariff <REGION>` fails fast when the region's currency differs from the project's `currency` — e.g. feeding RMB-priced `Beijing` into a `currency: USD` project previously mislabelled LCOE by ~7x. Fix either side yourself: edit the project YAML `currency:` (then re-check `opex`/capital prices and `exchange_rate` against your currency — VFED never converts or rewrites them), or pick a region priced in the project's currency. A user-supplied `--tariff` YAML file is always assumed to be in the project's own currency. `vfed design new --tariff <REGION>` sets the new project's `currency` to the region's automatically (echoed at creation).

7. **Legacy weather cache notice (one line per run).** A cache CSV written before the tilt-aware cache key existed (`weather_<lat>_<lon>_<year>.csv` — no tilt/azimuth/timezone in the filename) does not encode the panel geometry, so `poa_radiation` is recomputed from GHI on load and the run prints one ASCII notice naming the file. This is expected behaviour, not an error: the simulation always uses the geometry your project asks for. To silence it permanently, delete the named file (e.g. `weather_cache/weather_31.230_121.470_2025.csv`) and re-run once online — the refetch writes a geometry-aware cache. A sweep prints the notice exactly once for the whole run, never per row.

## Contributing

1. Fork the repository
2. Create a branch: `git checkout -b feature/my-feature`
3. Make changes and add tests
4. Run tests: `pytest`
5. Submit a pull request

## License

This project is licensed under the MIT License — see [LICENSE](LICENSE) for details.

## Citation

If you use VFED in your research, please cite:

**Paper:**
```bibtex
@article{xiong2026photovoltaic,
  title={Photovoltaic-battery integration strategy in plant factories with artificial lighting},
  author={Xiong, Tianzheng and Cai, Wenxin and Hu, Yue and Song, Mingxuan and Qian, Tao and Bao, Huashan},
  journal={Energy and Buildings},
  volume={361},
  pages={117462},
  year={2026},
  publisher={Elsevier},
  doi={10.1016/j.enbuild.2026.117462}
}
```

**Software:**
```bibtex
@software{vertical-farm-energy-designer,
  title = {Vertical Farm Energy Designer (VFED)},
  author = {Thomas XIONG},
  url = {https://github.com/ThomasXIONG151215/vertical-farm-energy-designer},
  year = {2024}
}
```

## Support

- **Issues**: https://github.com/ThomasXIONG151215/vertical-farm-energy-designer/issues
- **Discussions**: https://github.com/ThomasXIONG151215/vertical-farm-energy-designer/discussions
