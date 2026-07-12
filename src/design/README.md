# Design Module

Design orchestration — YAML project configuration, simulation engine, validated presets, and parametric sweep.

## Files

| File | Purpose |
|------|---------|
| `project.py` | Declarative design-project config (site, envelope, HVAC, DEH, LED, transpiration, PV, battery, tariff) serialised to/from YAML |
| `engine.py` | Core design engine — runs full digital-twin ODE simulation, produces hourly load profile + indoor climate timeseries |
| `presets.py` | Pre-built presets: `preset_default()` and `preset_609()` (Fengxian lettuce PFAL) |
| `sweep.py` | Design-space sweeper — enumerates PV area × battery capacity grid, returns LCOE-optimal design |

## Hub Module

`engine.py` imports from all other `src/` modules: `physics/`, `devices/`, `plants/`, `weather/`.

## Usage

```python
from src.design.project import DesignProject
from src.design.engine import DesignEngine, run_project
from src.design.presets import preset_609
from src.design.sweep import sweep_design
```
