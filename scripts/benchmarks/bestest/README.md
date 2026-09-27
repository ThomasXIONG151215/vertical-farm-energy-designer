# ASHRAE 140 BESTEST Harness (Layer C)

Engineering asset for the R27 Layer-C external validation of the vfed
single-zone ODE building core against ASHRAE Standard 140-2020 test cases
600 / 600FF / 900 / 900FF (Denver Intl AP TMY3 725650).

Outputs the verdict report to `user-gym/benchmarks/layerC_report.md`
(gitignored) — see that report for results, calibration log and attribution.

## Files

| File | Purpose |
|------|---------|
| `bestest_lib.py` | EPW→vfed weather conversion (incl. south-vertical POA synthesis), dual-year concatenation, case configs, reference table (ASHRAE 140-2020 via LBNL modelica-buildings mirror), instrumented run, verdicts |
| `run_bestest.py` | CLI entry: run cases, calibration probes, report generation |
| `USA_CO_Denver.Intl.AP.725650_TMY3.epw` | Denver TMY3 weather (energyplus.net free distribution; same source data as the LBNL BESTEST `.mos`) |

## Usage (from the repo root)

```bash
# full 4-case run + report
python scripts/benchmarks/bestest/run_bestest.py

# calibration probes (no report written)
python scripts/benchmarks/bestest/run_bestest.py --only 600FF --cz 500 600 700
python scripts/benchmarks/bestest/run_bestest.py --only 600 --eta 0.72 0.75 0.78
python scripts/benchmarks/bestest/run_bestest.py --only 900 --ua 70 75 80

# R28: 2R2C wall thermal-mass mode (additive wall_rc_nodes=2, timestep 60 s)
python scripts/benchmarks/bestest/run_bestest.py --rc
python scripts/benchmarks/bestest/run_bestest.py --rc --only 600FF --gim 400 700 900
python scripts/benchmarks/bestest/run_bestest.py --rc --only 900 --eta 0.78 --cmass 3966
```

Each dual-year run simulates 17,520 h at dt=600 s (~1–2 min per case; the
`--rc` mode runs dt=60 s, ~5-10x slower per case).  In `--rc` mode
`U_wall_A` means the direct channel only (roof + window) and the wall path
runs through the mass node (`--cmass` / `--gim` / `--gem` probe flags; the
adopted calibrated set lives in `bestest_lib.INITIAL_RC`, the section-3
derived set in `INITIAL_RC_DERIVED`, reachable again via `--k 1.0`).

## How it works

1. **Weather** — the EPW is parsed to the vfed 7-column contract
   (`temperature_2m`, `relative_humidity_2m`, `wind_speed_10m`,
   `shortwave_radiation`, `direct_radiation`, `diffuse_radiation`,
   `surface_pressure`).  The `shortwave_radiation` column carries
   **south-vertical plane-of-array** irradiance (NOAA solar position +
   isotropic sky, rho_g=0.2) so `Q_solar = eta_solar * A_window * POA`
   matches the BESTEST single south-glazing geometry.  Station pressure is
   included (Denver ~835 hPa) because the engine derives P_atm from it.
2. **Periodic steady state** — two identical years are concatenated; vfed
   always starts at `T_z = T_light`, so year 1 is wash-out and year 2 is
   reported.
3. **Thermal-load capture** — the timeseries only carries electrical energy,
   so `HVACDevice.step` is monkeypatched (and restored) to integrate
   `Q_HVAC_W` (sign: >0 heating, <0 cooling) into hourly buckets.
4. **ODE clamp** — Case 600FF free-float reference peaks (62.4–68.4 °C)
   exceed the production 60 °C clamp, so the harness raises the
   module-level `vfed.physics.ode._DEFAULT_T_MAX` to 90 for the run only.
   The production default and the engine are untouched.
5. **Thermostat** — BESTEST's 20/27 °C window controller is reproduced with
   `photoperiod_hours: 24` (always "light": cooling setpoint `T_light=27`
   year-round) + `T_dark=20` (heating setpoint), resistive heat mode,
   constant COP, zero fan power, `shr_rh_guard=100` (dry-air latent-free).

## Calibration knobs

`C_z` (Wh/K) per case and `eta_solar` are calibrated against the free-float
min/max/mean bands (single-node limitation: see the report attribution for
why the controlled-case annual loads are structurally out of band).

R28 (`--rc`): the identifying constraint is the free-float triple — the
adopted `INITIAL_RC` set passes all six FF metrics.  The controlled-case
annual loads remain out of band and are insensitive to (k, eta, C_z, g_im,
g_em) over a 20+ run scan; attribution (winter solar profile + solar-to-air
absorption) and the full scan table live in
`user-gym/benchmarks/layerC_rc_implementation.md`.  `--k` re-derives the
section-3 conductance set scaled by k for probe restarts.
