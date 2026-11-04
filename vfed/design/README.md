# Design Module

Design orchestration — YAML project configuration, simulation engine, validated presets, and parametric sweep. `engine.py` is the hub of the whole simulator: every hourly timestep passes through it.

## Files

| File | Purpose |
|------|---------|
| `project.py` | Declarative design-project config (site, envelope, HVAC, DEH, LED, transpiration, growth, PV, battery, tariff, space, opex, capital, currency) serialised to/from YAML. **This is the config contract** — new fields must be added here and in `presets.py`. |
| `engine.py` | Core design engine — runs the full digital-twin ODE simulation (8,760 hourly steps), produces hourly load profile + indoor climate timeseries as `SimulationResult` |
| `presets.py` | Pre-built presets: `preset_default()` and `preset_609()` (Fengxian lettuce PFAL) |
| `sweep.py` | Design-space sweeper — enumerates `space.parameter_ranges` (e.g. PV area × battery capacity), dispatches each configuration through the PVBES energy system, returns the design minimising the configured objective (default LCOE) |
| `fx.py` | Currency conversion (energy/PV unit prices, exchange rates) |
| `result.py` | `SimulationResult` container returned by the engine and consumed by sweep/agent/CLI |

## Hub Module

`engine.py` imports from every domain package:

- `physics/` — psychrometrics, `Envelope`, `RoomODESolver`, `DynamicSHR`
- `devices/` — `HVACDevice`, `DEHDevice`, `LEDDevice`, `CO2Device`
- `plants/` — `TranspirationModel`, `VanHenten`, `VanHenten3State`
- `weather/` — `fetch_weather`

`sweep.py` then imports `engine.py` **and** `pvbes/` (pv, battery, grid, energy_system) — it is the only design file that touches the energy system. Consumers of the engine: `sweep.py`, `agent/evaluator.py`, `cli.py`. Nothing else in `vfed/` imports `design/`.

Layering rules and the full dependency graph: repo-root `docs/architecture.md`.

## Usage

```python
from vfed.design.project import DesignProject
from vfed.design.engine import DesignEngine, run_project
from vfed.design.presets import preset_609
from vfed.design.sweep import sweep_design
```

## Notes

- `project.py` (~2,600 lines) and `engine.py` (~2,200 lines) are the two largest files in the repo — change them with care and run the full test suite afterwards.
- A planned split (interface-preserving) will move the hourly loop out of `engine.py`; the public surface (`DesignEngine`, `run_project`, `full_load_warnings`, `SimulationResult` import paths) stays frozen. See `docs/planning/2026-11-03_repo-reorg-plan.md`.
