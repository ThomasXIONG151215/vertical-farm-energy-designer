# Design Module

Design orchestration — YAML project configuration, simulation engine, validated presets, and parametric sweep. `engine.py` is the hub of the whole simulator: every hourly timestep passes through it. Since the C5 split (2026-11-04), `run()` orchestrates `engine_loop.py` (hourly loop) and `engine_report.py` (report layer). Waves 1–5 (2026-11) added the control protocol (`control.py`, stdlib-only) and the co-optimization API (`optimize.py`).

## Files

| File | Purpose |
|------|---------|
| `project.py` | Declarative design-project config (site, envelope, HVAC, DEH, LED, transpiration, growth, PV, battery, tariff, space, opex, capital, currency) serialised to/from YAML. **This is the config contract** — new fields must be added here and in `presets.py`. |
| `engine.py` | Core design engine — runs the full digital-twin ODE simulation (8,760 hourly steps), produces hourly load profile + indoor climate timeseries as `SimulationResult` |
| `engine_loop.py` | Hourly timestep loop extracted from `engine.py` `run()` — heat/moisture ODE substeps + device dispatch (`run_hourly_loop`) |
| `engine_report.py` | Report layer extracted from `run()` post-processing — timeseries/summary/climate dicts + PVBES quick-eval (`build_report`) |
| `presets.py` | Pre-built presets: `preset_default()` and `preset_609()` (Fengxian lettuce PFAL) |
| `sweep.py` | Design-space sweeper — enumerates `space.parameter_ranges` (e.g. PV area × battery capacity), dispatches each configuration through the PVBES energy system, returns the design minimising the configured objective (default LCOE) |
| `control.py` | Control protocol — `ZoneAction`/`Observation`/`PolicyContext`, `BuildingPolicy` protocol (`reset`/`plan_daily`/`step`), per-field merge (step action > daily plan > none = bit-identical legacy), `POLICY_REGISTRY` with built-in `setpoint_offset`. Pure leaf: stdlib only, no `vfed/` imports (AST-enforced) |
| `optimize.py` | Co-optimization API — `evaluate_candidate` (apply a schema-v1 candidate dict to a base project, run one simulation, score with the sweep economics helpers) and `optimize` (Cartesian grid search: one engine run per building combo, then inner PV × battery re-dispatch). Python API only — no CLI command |
| `fx.py` | Currency conversion (energy/PV unit prices, exchange rates) |
| `result.py` | `SimulationResult` container returned by the engine and consumed by sweep/agent/CLI |

## Hub Module

`engine.py` imports from every domain package:

- `physics/` — psychrometrics, `Envelope`, `RoomODESolver`, `DynamicSHR`
- `devices/` — `HVACDevice`, `DEHDevice`, `LEDDevice`, `CO2Device`
- `plants/` — `TranspirationModel`, `VanHenten`, `VanHenten3State`
- `weather/` — `fetch_weather`

`sweep.py` then imports `engine.py` **and** `pvbes/` (pv, battery, grid, energy_system); `optimize.py` reuses the energy-system builder and economics helpers from `sweep.py`. `control.py` imports nothing from `vfed/` (stdlib only). Consumers of the engine: `sweep.py`, `optimize.py`, `agent/evaluator.py`, `cli.py`. Nothing else in `vfed/` imports `design/`.

Layering rules and the full dependency graph: repo-root `docs/architecture.md`.

## Usage

```python
from vfed.design.project import DesignProject
from vfed.design.engine import DesignEngine, run_project
from vfed.design.presets import preset_609
from vfed.design.sweep import sweep_design
from vfed.design.control import build_policy
from vfed.design.optimize import evaluate_candidate, optimize
```

## Notes

- `project.py` (~2,800 lines) and the engine trio (`engine.py` ~1,900 + `engine_loop.py` ~850 + `engine_report.py` ~950) are the largest files in the repo — change them with care and run the full test suite afterwards. `control.py` (301 lines) and `optimize.py` (426 lines) are newer and smaller; `control.py` must stay stdlib-only.
- The C5 split (2026-11-04) moved the hourly loop to `engine_loop.py` and the report layer to `engine_report.py`; the public surface (`DesignEngine`, `run_project`, `full_load_warnings`, `SimulationResult` import paths) stays frozen. See `docs/planning/2026-11-03_repo-reorg-plan.md`.
