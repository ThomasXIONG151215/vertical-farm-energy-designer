# Archive: xiong-pvbes-photoperiod-2026

This folder contains the **original Vertical Farm Energy Designer (VFED)** simulation
codebase, preserved as a reference/comparison baseline before the project was
re-organized around a parametric, digital-twin-based design simulator.

## What this is

The original VFED pipeline:

1. `weather_processor.py` — fetch weather (Open-Meteo) and convert to EPW.
2. `create_load_profiles.py` — build/edit an EnergyPlus IDF and run it via **eppy**
   to produce `annual_energy_schedule_<start>_<end>.csv` (hourly building load, kWh).
3. `main.py` — consume the load CSVs + weather, run `SystemOptimizer`
   (brute-force enumeration of PV area × battery capacity) over `src/system.py`
   (PV single-diode + battery + grid/LCOE model). No EnergyPlus inside the optimizer.
4. `analyze_results.py` — plot results.

The EnergyPlus building model lives in `idfs/`, `idd/`, `weather/`, `test_case/`.
Validation data: `results/validate_ep/NOE.csv`.

## Known limitations (documented 2026-07)

- The "genetic algorithm" described in README/AGENTS.md is actually **brute-force
  enumeration** (`src/optimizer.py`).
- `src/eso_to_csv.py` referenced in AGENTS.md does **not exist**; ESO parsing is
  inlined in `src/cli.py::idf_extract_loads`.
- `requirements.txt` referenced by docs does not exist (only `pyproject.toml`).
- Two parallel, un-wired load-generation paths exist: `create_load_profiles.py`
  (eppy + meter CSV) vs `src/idf_builder.py` + `vfed idf` CLI (programmatic IDF + ESO).

## How to run (baseline)

```bash
pip install -e .            # installs the original `vfed` CLI (src.cli)
python main.py --mode optimize --city shanghai
```

This archive is **frozen**. New development happens in the repository root
(`src/` parametric design simulator). Use this folder to regression-check the new
ODE-based load generator against the original EnergyPlus-based loads.
