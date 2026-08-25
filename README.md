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

Runs the building simulation for a single configuration and reports annual load, biomass, and energy intensity (kWh/kg of fresh biomass). The `609` preset ships with `pv_area_m2=0` / `battery_kwh=0`, so the energy system is disabled here — you will see `Energy system = disabled`. If a project declares `pv` / `battery` (e.g. `example_lcoe_full.yaml`), this step also reports PV generation and grid import/export.

### 4. Parametric Sweep — find the LCOE-optimal PV + battery

The `609` preset declares no sweep ranges, so `vfed sweep my_farm.yaml` would only re-evaluate that single fixed configuration. To demonstrate the core PV-battery sizing, use the shipped example that declares `space.parameter_ranges`:

```bash
# 3 parameters (ppfd_target × pv_area × battery) = 100 configurations, ~1-2 min
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

For an offline quickstart, stick with a built-in city and `--year 2025`. To run an arbitrary site offline, fetch once while online (`vfed evaluate <yaml> --cache weather_cache`), then reuse the cache. Note that `preset 609` keeps `site.city: Shanghai` even when `--lat/--lon` override the coordinates — the city CSV wins whenever its year matches. Set `site.city: null` in the YAML to force the lat/lon (online) path. The example sweep files (`example_sweep.yaml`, `example_lcoe_full.yaml`) use year 2023 with explicit lat/lon, so their first run fetches from Open-Meteo (~1-2 min) and subsequent runs hit the cache.

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

The complete alias table is in `vfed/design/project.py` (`HARDWARE_ALIASES`). Canonical names still work unchanged; a config that sets both spellings to different values is rejected as ambiguous. When you specify a fixed unit, set `auto_size: false` — otherwise the engine overwrites the capacity with its auto-sized value.

### 4. Add real costs before trusting the economics

`vfed evaluate` warns when `capital_total` is 0 — in that case LCOE is operating cost only, not a design-level number. Add capital via `mode: per_watt` rates per component:

```yaml
led:      { capital: { mode: per_watt, rate_per_watt: 1.5 } }
hvac:     { capital: { mode: per_watt, rate_per_watt: 1.0 } }
deh:      { capital: { mode: per_watt, rate_per_watt: 2.0 } }
pv:       { capital: { mode: per_watt, rate_per_watt: 3.5 } }
battery:  { capital: { mode: per_watt, rate_per_watt: 500 } }
```

(`example_lcoe_full.yaml` shows a complete cost model.) Then tune `opex` — especially `labor_cost_per_year` and `misc_opex_per_year`, which dominate small-scale economics.

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

`vfed evaluate` prints more than energy: annual water use, RH clamp events, DEH utilization, and how much moisture the dehumidifier vs the HVAC coil removed. `vfed evaluate ... --export out/` also writes `summary.csv`, `timeseries.csv` (8,760 hourly rows) and `monthly.csv` for your own analysis.

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
│   ├── plants/             # Transpiration (6 methods), Van Henten growth model
│   ├── agent/              # Evaluator (preserves agent-cli error-code contract)
│   └── cli.py              # CLI entry point: vfed
├── research/               # Archived research paper code & data (see below)
├── reference/              # Reference literature
├── weather_cache/          # Cached weather CSVs (auto-generated)
├── pyproject.toml          # Project metadata & dependencies
├── vfed-web/               # Browser visualisation (Pyodide Web Worker)
├── test_project.yaml       # Minimal fixture YAML — tests/ only, not a template
├── test_web_yaml.py        # vfed-web end-to-end contract script — run: python test_web_yaml.py
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
| `vfed evaluate <project.yaml> [--cache dir] [--export dir]` | Run the building simulation for one configuration; `--export` writes `summary.csv` / `timeseries.csv` / `monthly.csv` into `dir` |
| `vfed sweep <project.yaml> [--cache dir] [--out results.csv]` | Enumerate `space.parameter_ranges` (e.g. PV area × battery capacity) into a CSV; evaluate a single fixed configuration if no ranges are declared |

## Configuration

All design parameters live in a single YAML file generated by `vfed design new`. Key sections:

- **site** — latitude, longitude, year, timezone
- **envelope** — U-values, area, solar absorptance, vapour permeance
- **hvac** — rated cooling capacity, COP mode (carnot / constant / linear / table), setpoints
- **deh** — dehumidifier rated capacity, RH setpoints, efficiency model
- **led** — PPFD, efficacy, photoperiod schedule
- **transpiration** — method (van_henten / daily / per_plant / daily_per_period / per_plant_per_period)
- **growth** — Van Henten growth-model parameters
- **pv** — panel efficiency, NOCT, tilt, azimuth
- **battery** — capacity, C-rates, round-trip efficiency, SOC limits
- **tariff** — electricity price:
  - New format: `hourly_prices` (24 values, index = hour 0-23) + `export_price` (recommended).
  - Legacy format (compatible): `peak_price` / `normal_price` / `valley_price` + `peak_hours` / `valley_hours`, expanded to 24 values on load.
  - Reference tariffs: `vfed design tariffs` lists regions; `vfed design new ... --tariff <region>` loads one directly.
- **space** — optional sweep parameter ranges and objective (`lcoe` / `kwh_per_kg_fresh` / `cost_per_kg_fresh`)
- **opex / equipment_capital / envelope_capital / pump_capital** — capital and operating cost inputs
- **currency / exchange_rate** — currency settings for cost reporting

## Interpreting Results

`vfed evaluate` and `vfed sweep` report the same set of economic / energy KPIs. All monetary values are reported in the project's `currency` (default USD); `exchange_rate` is display-only annotation ("1 USD = 7.2 CNY") and **does not convert values**.

### evaluate output (core KPIs)

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
| Battery cycles | `battery_cycles` | full cycles/yr | Annual throughput ÷ (2 × capacity) |
| PV self-consumption | `pv_self_consumed_kwh` / `pv_self_consumption_rate` | kWh/yr / 0-1 | PV directly serving the load / share of generation |
| Battery discharge | `battery_discharge_kwh` | kWh/yr | Annual battery discharge |
| Free energy | `free_energy_kwh` | kWh/yr | PV self-consumed + battery discharge |
| Grid independence | `grid_independence_pct` | % | (1 − grid import ÷ load) × 100; **grid dependency = 100 − this value** |

Additional outputs: `energy_breakdown` (`hvac_pct` / `led_pct` / `deh_pct` / `misc_pct` as fractions, 0.30 = 30%), `monthly` (12-month aggregates), `timeseries` (hourly: `load_kw` / `T_z` / `RH_z` / `E_*_Wh`), `typical_daily` (12 × 24 typical-day loads), `sizing` (auto-sized nameplate values). Only when a project declares `pv` / `battery` does `evaluate` print PV/grid rows; otherwise the energy system is disabled, `grid_import_kwh` equals the annual load and the rest are 0.

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

All `cost*` / `capital*` / `annual_*` monetary columns are in the project's `currency` (see `currency / exchange_rate`).

## Web Visualisation (vfed-web)

`vfed-web/` is a backend-free browser version of VFED: the real VFED Python code runs inside a **Pyodide Web Worker** (`worker.js`), charts are drawn with Chart.js, and weather data is embedded at build time — the browser **never calls Open-Meteo**.

### Run locally

```bash
cd vfed-web
python -m http.server 8000
# open http://localhost:8000
```

Do not double-click `index.html` directly (Web Workers cannot load under `file://`). The first load needs internet (Pyodide + numpy/pandas are fetched from a CDN).

### Built-in presets and the simulation path

- **Built-in presets** `BUILTIN_PRESETS`: `609` (Fengxian Lettuce PFAL), `lettuce_standard` (Lettuce — Standard PFAL).
- **Simulation path**: form → `generateYaml()` → `postMessage({type:'simulate', projectYaml})` → Pyodide in the Worker runs the vfed simulation → results post back → charts render.
- **Rebundling**: after changing `vfed/` Python code or updating `weather_cache/`, re-run `python bundle.py` in `vfed-web/` to embed the sources and weather cache into `worker.js`.

## Troubleshooting

The first line of defence is `vfed validate <project.yaml>`: it checks the YAML, `timestep_s`, `space.objective`, and sweep parameter ranges without running a simulation.

### Error codes

| Code | Meaning | Common triggers | Fix |
|---|---|---|---|
| **E001** | Config error | Missing file, broken/unknown/out-of-range YAML; illegal `parameter_ranges` (unknown name, non-`[min,max,step]` triple, non-integer step, out of hard limits) | Regenerate with `vfed design new <name> --preset 609`; locate with `vfed validate <yaml>` |
| **E003** | Weather fetch failed | No network, no cache, missing `requests` package | See "Weather offline" below |
| **E101** | Simulation failed | Engine / energy-system exception (illegal timestep, NaN weather, energy-system error) | Read the full stderr; `vfed validate`; check `timestep_s` and weather data integrity |
| **E103** | Zero load | Annual load ≤ 0 | Check LED power (with `auto_deduce`: `ppfd_target` × `covered_area` ÷ `efficacy`), `equipment_power_w`, `setpoints` |

### Common problems

1. **`timestep_s` must divide 3600 s.** Rule: `sub=max(1,round(3600/dt))` and `|sub·dt−3600|≤1`. Valid values: 600, 900, 1200, 1800, 3600. `vfed validate` and `vfed evaluate` both reject non-divisors.

2. **Sweep ranges outside `HARD_LIMITS`.** Scan ranges `[min,max,step]` must lie within:

   | Parameter | Hard limit | Parameter | Hard limit |
   |---|---|---|---|
   | `ppfd_target` | 50–500 µmol/m²/s | `T_dark` | 10–28 °C |
   | `efficacy` | 1.5–4.0 µmol/J | `RH` | 40–90 % |
   | `photoperiod_hours` | 0–24 h/day | `co2_ppm` | 300–2000 ppm |
   | `light_start_hour` | 0–23 h | `crop_cycle_days` | 15–60 days |
   | `T_light` | 15–30 °C | `pv_area` | 0–1000 m² |
   | | | `battery` | 0–500 kWh |

   and `(max−min)/step` must be an integer.

3. **Weather offline (E003) — three fixes:**
   - Retry online: re-run on a networked machine; the fetch writes `weather_cache/` for later offline reuse.
   - Cache / prefetch: run `vfed evaluate <yaml> --cache weather_cache` once online; legacy cache files are reused automatically (warning printed, not fatal).
   - Offline CSV: place a cache CSV in `weather_cache/` manually (filename includes lat/lon/year; the tilt-aware key also includes tilt/azimuth/tz). In the browser build, weather is embedded via `bundle.py`.

4. **E103 zero load:** usually LED power derives to 0 (`auto_deduce` with `ppfd_target` / `covered_area` / `efficacy` missing) or `equipment_power_w=0`. Run `vfed validate` and check those fields.

5. **LCOE semantics:** `lcoe` is the facility full cost per kWh of load — when comparing projects, note that each project may use a different `currency`.

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
