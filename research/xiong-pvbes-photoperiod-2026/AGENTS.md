# VFED — Archived Research Agent Guidelines

> **Note:** This directory contains archived research code from the original PV-BES photoperiod optimisation papers. The current active codebase lives in `src/` at the repository root, using a pure-Python ODE solver instead of EnergyPlus.

## Project Overview

This is the original OpenCROPS (now VFED) research code — an EnergyPlus-based load generator coupled with a genetic-algorithm PV-Battery optimiser. Preserved for reproducibility of published results.

## Commands

```bash
# Install (legacy)
pip install -e .

# CLI (legacy — use `vfed` from root for current code)
python main.py optimize --cities shanghai harbin
python main.py evaluate --pv-area 200 --battery-capacity 100 --city shanghai
python main.py calibrate --city shanghai
python main.py analyze --results-file all_optimization_results.csv

# EnergyPlus (if installed)
"/c/EnergyPlusV23-1-0/energyplus.exe" \
  -i "/c/EnergyPlusV23-1-0/IDD_Version23_1_0.idd" \
  -w weather/shanghai_2024.epw \
  -d output test.idf
```

## Architecture

```
research/xiong-pvbes-photoperiod-2026/
├── main.py                # Legacy CLI entry point
├── src/
│   ├── cli.py             # Typer CLI interface
│   ├── system.py          # Energy system simulation
│   ├── optimizer.py       # Genetic algorithm optimisation
│   ├── battery.py         # Battery power flow
│   ├── calibrator.py      # Step size calibration
│   └── models/            # Extensible model base classes
├── weather/               # EPW weather files
├── idfs/                  # IDF templates
├── data/                  # Experimental data (CC BY 4.0)
├── tests/                 # Test suite
└── results/               # Validation data
```

## Key Differences from Current VFED (`src/`)

| Aspect | This directory (archived) | Current `src/` |
|--------|--------------------------|-----------------|
| Load generation | EnergyPlus IDF simulation | Pure Python ODE solver |
| Optimiser | Genetic algorithm (DEAP) | Parametric sweep + LCOE |
| Weather | EPW files | Open-Meteo API + cache |
| Entry point | `python main.py` | `vfed` CLI |

## Don't Modify

This directory is archived. Do not add features, refactor, or fix bugs here. If you find an issue in the logic, port the fix to `src/` instead.

## Validation Data

- `results/validate_ep/NOE.csv` — 16-day validation (2023/8/21–9/6, 384 hourly records)
- `data/raw/BW_data.csv` — multi-year PFAL energy monitoring (CC BY 4.0)
