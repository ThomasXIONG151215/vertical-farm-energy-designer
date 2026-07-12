# VFED Agent Guidelines

## Project Overview

Vertical Farm Energy Designer (VFED) is a parametric, config-driven design simulator for plant factories. It couples a first-principles ODE building model (no EnergyPlus) to a PV-Battery-Grid energy system for LCOE-optimal solar+storage sizing.

## Commands

```bash
# Install
pip install -e .
pip install -e ".[all]"

# Design
vfed design new <name> --preset 609 --lat N --lon N --year YYYY
vfed design presets

# Optimise / Evaluate / Sweep
vfed optimize <project.yaml> --cache weather_cache --out results.csv
vfed evaluate <project.yaml> --pv-area N --battery M
vfed sweep <project.yaml> --out sweep_results.csv

# Tests
pytest
pytest --cov=src
```

## Architecture (flat map)

| Directory | Purpose | Key file |
|-----------|---------|----------|
| `src/physics/` | Psychrometrics, envelope, ODE solver, SHR | `engine.py` consumes all |
| `src/devices/` | HVAC, dehumidifier, LED, compressor, lag | Built by `engine.py` |
| `src/pvbes/` | PV, battery, grid, energy system | Consumed by `sweep.py` |
| `src/design/` | Project config, engine, presets, sweep | `engine.py` is the hub |
| `src/weather/` | Open-Meteo fetch, geocoding | `engine.py` calls `fetch_weather` |
| `src/plants/` | Transpiration, Van Henten growth | `engine.py` steps each hour |
| `src/agent/` | Evaluator (agent-cli contract) | Entry point for CLI |

## Constraints

- **All parameters live in YAML** — `src/design/project.py` is the config contract. New fields must be added there and in `presets.py`.
- **No EnergyPlus dependency** — pure Python ODE solver (`src/physics/ode.py`).
- **Python >= 3.8** — core deps: `numpy`, `pandas`, `pyyaml`, `requests`.
- **`src/design/engine.py` is the hub** — it imports from every other module. Changes to physics/devices/plants/weather may affect it.
- **Strategy modes are exactly 4** — `default` / `conservative` / `progressive` / `aggressive`. No fifth.
- **Scenario/routine logic stays isolated** from energy-optimisation code and from the data layer.

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
