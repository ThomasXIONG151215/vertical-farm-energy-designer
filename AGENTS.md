# VFED Agent Guidelines

## Project Overview

Vertical Farm Energy Designer (VFED) is a parametric, config-driven design simulator for plant factories. It couples a first-principles ODE building model (no EnergyPlus) to a PV-Battery-Grid energy system for LCOE-optimal solar+storage sizing.

## Repository Layout (two layers)

Full map with layering rules and dependency graph: `docs/architecture.md`.

| Layer | Path | Role |
|-------|------|------|
| Tracked | `vfed/` | Active simulator code (see flat map below) |
| Tracked | `tests/` | Pytest suite — CI-locked, do not move |
| Tracked | `tools/` | Maintenance utilities (`download_weather_db.py` refreshes `data/weather/`) |
| Tracked | `benchmarks/` | Validation benchmarks (BESTEST/ASHRAE 140, BJAAF growth, respiration, UC Davis) |
| Tracked | `examples/` `data/` `docs/` | Example YAMLs · weather/datasets · architecture/reports/references/planning |
| Tracked | `research/` | Archived paper code — frozen |
| Local-only | `gadget/` `user-gym/` `backups/` | Git-ignored machine-local folders — never move (sync layer), never commit |
| Local-only | `weather_cache/` `.scratchpad/` `.workbuddy/` | Runtime cache / agent working files — regeneratable or transient |

## Commands

```bash
# Install
pip install -e .
pip install -e ".[dev]"   # dev/test extras

# Design (options: --preset, --city, --lat/--lon, --year, --tariff, --out)
vfed design new <name> --preset 609 --city Shanghai --year 2025
vfed design presets
vfed design cities
vfed design tariffs

# Validate (schema check without running a simulation)
vfed validate <project.yaml>

# Evaluate / Sweep / Optimize (PVBES sizing via sweep; `vfed optimize` wraps the co-optimization API in `vfed/design/optimize.py` — flat `--grid` keys + inner `--pv`/`--battery` re-dispatch; zones/policies dims are Python-API only)
vfed --version
vfed evaluate <project.yaml> --cache weather_cache [--export out/]
vfed sweep <project.yaml> --cache weather_cache --out results.csv
vfed optimize <project.yaml> --cache weather_cache --grid KEY=SPEC [--pv a1,a2] [--battery b1,b2] [--policy-json JSON]

# Tests
pytest
pytest --cov=vfed
```

## Architecture (flat map)

| Directory | Purpose | Key file |
|-----------|---------|----------|
| `vfed/physics/` | Psychrometrics, envelope, ODE solver, SHR | `engine.py` consumes all |
| `vfed/devices/` | HVAC (Carnot COP default), dehumidifier (auto-size), LED, compressor, lag | Built by `engine.py` |
| `vfed/pvbes/` | PV, battery, grid, energy system | Consumed by `sweep.py` (and `optimize.py`) |
| `vfed/design/` | Project config, engine (+`engine_loop`/`engine_report`), presets, sweep, control protocol (`control.py`), co-optimization API (`optimize.py`) | `engine.py` is the hub |
| `vfed/weather/` | Open-Meteo fetch (NASA-POWER fallback), geocoding | `engine.py` calls `fetch_weather` |
| `vfed/plants/` | Transpiration (5 methods: van_henten model-coupled; daily/per_plant/daily_per_period/per_plant_per_period direct-set), Van Henten growth | `engine.py` steps each hour |
| `vfed/agent/` | Evaluator (agent-cli contract) | Entry point for CLI |
| `vfed/calibration/` | Dataset adapters, identifiability analysis, golden-section fitting | Imports `plants/` only; nothing imports it |
| `tools/` | Maintenance utilities | `download_weather_db.py` refreshes `data/weather/` city CSVs |
| `benchmarks/` | Validation benchmarks | BESTEST, BJAAF growth, respiration, UC Davis |
| `tests/` | Pytest suite | run with `pytest` |

## Review Standard

`REVIEW.md` is the simulation-architecture review checklist (heat & mass transfer + energy dispatch). Consult it when reviewing changes to `vfed/physics/`, `vfed/devices/`, `vfed/plants/`, or `vfed/pvbes/`.

## Constraints

- **All parameters live in YAML** — `vfed/design/project.py` is the config contract. New fields must be added there and in `presets.py`.
- **No EnergyPlus dependency** — pure Python ODE solver (`vfed/physics/ode.py`).
- **Python >= 3.8** — core deps: `numpy`, `pandas`, `pyyaml`, `requests`.
- **`vfed/design/engine.py` is the hub** — it imports from every other module. `run()` orchestrates `engine_loop.py` (hourly timestep loop) and `engine_report.py` (report + PVBES quick-eval); they lazy-import back from `engine.py`, so no import cycle. Changes to physics/devices/plants/weather may affect all three.
- **Control protocol & zones are additive and default-off** — `vfed/design/control.py` is a stdlib-only leaf (AST-gated by `tests/test_40_control_protocol.py`); YAML carries only `control.period_s` (integer multiple of `timestep_s`, 60–3600 s, default `None` = physics timestep) and the top-level `zones` mapping (zone id → override delta; non-empty zones run one full-year simulation per zone; zones are not sweepable in v1). Policies are attached in Python via `build_policy({"type", "params"})`. With no policy and empty zones, behaviour is bit-identical to legacy.
- **Strategy/scenario modes are NOT implemented** — the 4 strategy modes (`default` / `conservative` / `progressive` / `aggressive`) exist only as a *planned* feature documented in the `vfed/design/project.py` docstring. Do not add or reference a `strategy:` config field.
- **HVAC COP mode is 4** — `carnot` (default: η_II × T_evap/(T_cond-T_evap)), `constant`, `linear`, `table`. Carnot depends on both indoor and outdoor temperature.
- **Transpiration method is 5** — 1 model-coupled (`van_henten`) + 4 direct-set (`daily`, `per_plant`, `daily_per_period`, `per_plant_per_period`).

## Boundaries

### Always do
- Update `vfed/design/project.py` when adding/rename a config field
- Run `pytest` before committing
- Use `DesignProject` dataclasses for config (not raw dicts)

### Ask first
- Adding new dependencies — keep the dep footprint small
- Changing `engine.py` interface — it affects agent/evaluator
- Modifying weather_bridge.py — API responses may change

### Never do
- Commit `.env` or API keys
- Hardcode weather data — always use `fetch_weather` or cache
- Import from `research/` into `vfed/` — research is archived, vfed is the active codebase
- Move `gadget/` or other large root folders on this machine — the G: volume is managed by a
  bidirectional cloud-sync layer (FeRp reparse tags; Syncthing/Baidu sync suspected). Local moves
  are reverted from peer state within minutes (verified by repeated tests). `gadget/` stays at
  repo root; it is git-ignored and harmless there.
- Modify `research/` code — it is preserved for reproducibility only.
  Exception (2026-10-23 cleanup, user-approved): byte-identical cross-city duplicate files
  (442 files) were removed; the original layout is recorded in
  `research/xiong-pvbes-photoperiod-2026/MANIFEST_DEDUP.csv` (deleted_path → kept_path).
  Regeneratable EnergyPlus outputs (html/csv/png under test_case|results|load_analysis|output)
  were deleted locally; they are git-ignored and reproducible from the kept .idf + .epw inputs.

## File Conventions

- Config dataclasses: `vfed/design/project.py`
- Presets: `vfed/design/presets.py`
- CLI entry: `vfed/cli.py`
- Tests: `tests/`
- Example projects: `examples/`
- Architecture map: `docs/architecture.md`
- Session plans: `docs/planning/`
- Validation data (PV/BES datasheets, measured curves): `docs/references/`
- Cached weather: `weather_cache/` (git-ignored, regeneratable)
