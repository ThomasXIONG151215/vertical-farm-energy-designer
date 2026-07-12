# PV-Battery-Grid (PVBES) Module

Integrated photovoltaic, battery energy storage, and grid tariff models for energy system simulation and LCOE optimisation.

## Files

| File | Purpose |
|------|---------|
| `pv.py` | Single-diode PV model (SDM) at MPP with NOCT cell-temperature correction |
| `battery.py` | Battery model — Zhao et al. 2024 parametric formulation, SOC tracking, C-rate limits |
| `grid.py` | Time-of-use electricity tariff — peak/normal/valley pricing, annual cost & export credit |
| `energy_system.py` | Combined PV-Battery-Grid system — simulate performance, compute LCOE, TLPS, payback |

## Exports

```python
from src.pvbes import PVSystem, BatterySystem, Tariff, EnergySystem
```

## Dependencies

**Leaf module** — no internal `src/` imports. Uses only `dataclasses`, `numpy`, `typing`.
