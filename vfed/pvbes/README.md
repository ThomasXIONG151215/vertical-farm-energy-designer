# PV-Battery-Grid (PVBES) Module

Integrated photovoltaic, battery energy storage, and grid tariff models for energy system simulation and LCOE optimisation.

## Files

| File | Purpose |
|------|---------|
| `pv.py` | Single-diode PV model (SDM) at MPP with NOCT cell-temperature correction |
| `battery.py` | Battery model — Zhao et al. 2024 parametric formulation, SOC tracking, C-rate limits; optional end-of-life capacity fade (`soh_eol`; default off = bit-identical legacy) |
| `grid.py` | Time-of-use electricity tariff — 24-hour price schedule + export price, annual cost & export credit |
| `energy_system.py` | Combined PV-Battery-Grid system — simulate performance, compute LCOE, TLPS, payback; optional frozen `dispatch_policy` hook (causal charge/discharge requests, clamped by the dispatcher) |

## Exports

```python
from vfed.pvbes import PVSystem, BatterySystem, Tariff, EnergySystem
```

## Dependencies

**Leaf module** — no internal `vfed/` imports. Uses only `dataclasses`, `numpy`, `typing`.
