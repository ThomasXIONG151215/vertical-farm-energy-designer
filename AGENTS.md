# VFED Agent Guidelines

## Project Overview

Vertical Farm Energy Designer (VFED) is a parametric, config-driven design simulator for plant factories. It couples a first-principles ODE building model (no EnergyPlus) to a PV-Battery-Grid energy system for LCOE-optimal solar+storage sizing.

## Commands

```bash
# Install
pip install -e .
pip install -e ".[dev]"   # dev/test extras

# Design
vfed design new <name> --preset 609 --lat N --lon N --year YYYY
vfed design presets
vfed design cities
vfed design tariffs

# Evaluate / Sweep (there is no separate `optimize` command — PVBES sizing is done via sweep)
vfed evaluate <project.yaml> --cache weather_cache
vfed sweep <project.yaml> --cache weather_cache --out results.csv

# Tests
pytest
pytest --cov=src
```

## Architecture (flat map)

| Directory | Purpose | Key file |
|-----------|---------|----------|
| `src/physics/` | Psychrometrics, envelope, ODE solver, SHR | `engine.py` consumes all |
| `src/devices/` | HVAC (Carnot COP default), dehumidifier (auto-size), LED, compressor, lag | Built by `engine.py` |
| `src/pvbes/` | PV, battery, grid, energy system | Consumed by `sweep.py` |
| `src/design/` | Project config, engine, presets, sweep | `engine.py` is the hub |
| `src/weather/` | Open-Meteo fetch, geocoding | `engine.py` calls `fetch_weather` |
| `src/plants/` | Transpiration (6 methods: vpd/stomatal/van_henten/constant/daily/per_plant), Van Henten growth | `engine.py` steps each hour |
| `src/agent/` | Evaluator (agent-cli contract) | Entry point for CLI |

## Constraints

- **All parameters live in YAML** — `src/design/project.py` is the config contract. New fields must be added there and in `presets.py`.
- **No EnergyPlus dependency** — pure Python ODE solver (`src/physics/ode.py`).
- **Python >= 3.8** — core deps: `numpy`, `pandas`, `pyyaml`, `requests`.
- **`src/design/engine.py` is the hub** — it imports from every other module. Changes to physics/devices/plants/weather may affect it.
- **Strategy/scenario modes are NOT implemented** — the 4 strategy modes (`default` / `conservative` / `progressive` / `aggressive`) exist only as a *planned* feature documented in the `src/design/project.py` docstring. Do not add or reference a `strategy:` config field.
- **HVAC COP mode is 4** — `carnot` (default: η_II × T_evap/(T_cond-T_evap)), `constant`, `linear`, `table`. Carnot depends on both indoor and outdoor temperature.
- **Transpiration method is 6** — 3 model-calculated (`vpd`, `stomatal`, `van_henten`) + 3 direct-set (`constant`, `daily`, `per_plant`).

## Boundaries

### Always do
- Update `src/design/project.py` when adding/rename a config field
- Run `pytest` before committing
- Use `DesignProject` dataclasses for config (not raw dicts)

### Ask first
- Adding new dependencies — keep the dep footprint small
- Changing `engine.py` interface — it affects agent/evaluator
- Modifying weather_bridge.py — API responses may change

### Never do
- Commit `.env` or API keys
- Hardcode weather data — always use `fetch_weather` or cache
- Import from `research/` into `src/` — research is archived, src is the active codebase
- Modify `research/` code — it is preserved for reproducibility only

## File Conventions

- Config dataclasses: `src/design/project.py`
- Presets: `src/design/presets.py`
- CLI entry: `src/cli.py`
- Tests: `tests/`
- Cached weather: `weather_cache/` (git-ignored, regeneratable)
