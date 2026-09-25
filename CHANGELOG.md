# Changelog

All notable changes to VFED are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/); versioning is best-effort
semantic — behaviour changes are called out explicitly under **Changed**.

## [2.1.1] - 2026-09-25

Accuracy-audit release (user13 + whitebox/GHI deep checks, round 21).

### Fixed
- **`payback_period` now recomputable**: sweep column switched from the
  legacy `capital_cost/annual_savings` formula (hidden C_pv=500/kWp +
  c_energy=220/kWh pricing; produced a plausible-but-wrong 6.49 yr on the
  audit case) to `delta_capital / annual_savings` — every row reproduces
  from exported columns to 1e-9. Console prints both gross and net-of-O&M
  payback with explicit labels.
- **Explicit `capital cost: 0.0` is honoured literally** (was silently
  falling back to legacy unit-price estimation, inflating LCOE ~3%); the
  fallback now requires the key/block to be absent (`null` counts as
  absent). Negative costs are rejected.

### Added
- `summary.annual_capital` (capital x CRF), `summary.annual_ghi_kwh_m2`,`
  `battery_charge_kwh` / `battery_recon_grid_kwh` — the battery energy
  balance (+17.6 kWh residual) and apparent RTE overshoot (0.8303 vs 0.8281)
  are now exactly explainable from exports; README documents the
  year-end SOC reconciliation and cycles accounting convention.
- README: ERA5 eastern-China GHI bias (+15-25% vs NASA POWER/CMA) declared
  under Model Scope & Limitations.
- Web worker rebundled with the new capital semantics.

## [2.1.0] - 2026-09-21


Full repair-and-verification cycle driven by 11 simulated cold-start user
audits (personas user1-user12, reports under `user-gym/`), executed in 18
verified ledger rounds (`.scratchpad/2026-09-08_scratchpad_fix-verify-loop.md`).
Every item was independently verified against a frozen physics baseline before
commit.

### Fixed — correctness (was silently wrong)
- **Capital-cost unit fields** (P0-1): `capital` now uses explicit
  `per_kwp` / `per_kwh` / `per_watt` modes; the old misspelled key is
  rejected with an E001 error and a migration hint. (3155c10)
- **No-PV grid cost was silently zero** (P0-2): grid-only designs now price
  electricity via the tariff in both `evaluate` and `sweep`. (93add0f)
- **Lettuce growth calibration** (P0-3R): `growth.c_rad_phot` re-calibrated
  from 1e-8 to 3.5e-9 after the shipped value overpredicted yield 2-4x;
  templates and READMEs carry a calibration warning. (3079495, 9a9fd01)
- **Full-load / reachability diagnostics** (P0-4): HVAC & DEH report
  bidirectional full-speed hours as WARNING; preset 609 `T_dark` corrected
  18 -> 21 C. (896db3b)
- **sweep guardrails** (P0-5): parameter-range validation, single-point
  economic self-evidence, boundary notes. (28e3a71)
- **GBK console mojibake** (P2-1): all runtime warnings/errors are pure
  ASCII (em-dash -> `--`, degree sign -> ` C`). (6ee8ff6)
- **Monthly harvest attribution** (P1-3a/P1-3b): end-of-year standing crop
  no longer folded into any month; reported separately as
  `harvest_final_standing_kg`. (1f6f918, 7aed25f)
- **City weather files** (P1-3b): all 51 pre-downloaded city files
  regenerated on the aligned local calendar year (previous files were a
  UTC-anchored rolling window missing/mislabelling 8 hours); alignment
  guard warns instead of silently using misaligned files. (7aed25f)
- **Web bundle blocked by fail-fast** (round 19): `generateYaml()` emitted
  removed `pv.maintenance` / `battery.maintenance` keys, so every web
  simulation was rejected; keys removed, worker rebundled with current
  engine sources.

### Added
- **DEH `on_off` control mode** + effective/delivered SMER reporting (P1-1,
  50f6774).
- **Investment KPIs** (P1-2, e1ffde2): sweep now exports `npv_25yr`,
  `irr_pct`, `payback_years`, `annual_savings`, `self_consumption`,
  `grid_independence` (+2 auxiliary columns); battery
  `allow_grid_charging` switch (default off).
- **Additive output pipeline** (P1-3a, 1f6f918): monthly CSV gains
  `electricity_cost`, `grid_import_kwh`, `water_m3`, `harvest_fw_kg` (and
  PV-branch `pv_generation_kwh` / `grid_export_kwh` / `battery_net_kwh`);
  summary gains LED/HVAC annual kWh, percentage breakdown and standing-crop
  scalars; `summary.csv` dict cells are now `ast.literal_eval`-safe;
  bilingual CSV column dictionary in the README.
- **Local-calendar time axis** (P1-3b, 7aed25f): timeseries gains ISO8601
  `timestamp` and hourly `price` columns; monthly buckets are true natural
  months (m1 = 744 h).
- **RH compliance KPIs** (P1-4, fe3b2ac): summary
  `rh_exceed_hours/pct`, `rh_p95_pct`, `rh_max_pct`, and configurable
  `rh_disease_risk_threshold` (default 85%) with grey-mould WARNING; plus a
  one-line console `RH compliance = ...` report (round 18).
- **OPEX transparency** (P1-7, 62e5406): summary
  `opex_labor_per_year` / `opex_misc_per_year` / `annual_om_pct_of_cost`;
  a WARNING fires when built-in default OPEX dominates annual cost
  (typical: ~85%).
- **Weather provenance** (P2-2, 15a6b0e): `evaluate` prints
  `Weather source: pre-downloaded city file (...) | cache hit (...) |
  live fetch (...)`; `weather_attrs` also serialized in result JSON and
  displayed in the web UI (round 19).
- **CLI UX** (P2-3, 6f949d7): `vfed --version`; `--tariff {NAME|PATH}`
  override on evaluate/sweep; `Project:` output line shows the YAML
  filename; `design cities` lists lat/lon/timezone; `design tariffs` lists
  currency.
- **Hard limits on all entry points** (round 18, ea17e13): out-of-band
  scalars (e.g. `ppfd_target: 9999`) are rejected by `validate`,
  `evaluate` and `sweep` alike with an E001 naming field, value and band.
- **Tariff currency fail-fast** (round 18, ea17e13): tariff DB regions
  carry `currency`; `--tariff` is rejected (E001) when its currency
  differs from the project currency; `design new --tariff` sets the
  currency automatically.
- **Template placeholder stripping** (round 18, 5ce73dc): `design new`
  templates omit placeholder alias keys (e.g. `M_deh_nom: 0.0`), so the
  documented DIY-alias workflow no longer trips the Ambiguous-alias error.
- **Parameter glossary** (P1-5, bcee81a): per-field comments for all 50
  HVAC/DEH config fields, envelope U-value / C_z estimation guidance, and
  an Output Glossary (removal-limited events, RH clamp, X_d semantics,
  LCOE worked example).
- **Plant parameter glossary + density** (P1-6, d516caf):
  transpiration/growth fields documented; 5 methods enumerated;
  `plants_per_m2` density field with plant_count derivation.
- **Model Scope & Limitations** (P3, 256dad2): bilingual README section
  declaring documented-not-fixed approximations (growth-water decoupling,
  light-period water basis, single weather year, COP winter ceiling,
  thermal/moisture numerics).

### Changed — behaviour (breaking-ish, documented)
- **Direct-set transpiration defaults** (P1-6): unified to the reference
  scenario 1.5 L/m²/day at 25 plants/m² — `daily_water_L` 40 -> 67.5,
  `ml_per_plant_day` 80 -> 60, period lists rescaled accordingly. The
  model-coupled `van_henten` path is unaffected.
- **Weather window** (P1-3b): city-path results shift slightly
  (609 preset annual load 62,452.72 -> 62,444.50 kWh/yr, -0.01%) and
  monthly buckets move to natural months. `example_sweep` economics are
  unaffected (lat/lon cache path).
- **Fail-fast tightening**: capital-mode legacy key, out-of-band hard
  limits, currency-mismatched tariffs and unknown keys (incl. the removed
  web `maintenance` fields) now raise E001 instead of being ignored.
- **`Project:` console line format** (P2-3): `Project: <file>.yaml
  (name: <name>)` — downstream line parsers should adapt.
- **sweep legacy-cache notice** (round 18): deduplicated to one line per
  run, no source paths, includes refetch instructions.
- **City cache side-effect removed** (round 18): hits on pre-downloaded
  city files no longer write lat/lon cache copies.

### Web
- Rebundled worker with the current engine (aligned weather guard, RH
  KPIs, new defaults); water defaults synced; weather-source display bar;
  YAML generator unblocked.

### Verification snapshot
- pytest: 474 passed (305 baseline + 169 added across test_08-test_18).
- Frozen physics baseline (609 preset @ Shanghai 2025, aligned window,
  city path): annual load 62,444.50 kWh/yr, 31.0499 kWh/kg fresh,
  100.55 kg dry / 2,011.10 kg fresh, 10.37 m3 water, grid cost
  6,244.45 USD/yr, LCOE (no capital) 0.6608 USD/kWh.
- `example_sweep` economics bitwise-frozen since P1-2: best
  pv200+batt0+ppfd300, LCOE 0.7697603292315144, capital 23,255.814 USD,
  77.57 kg dry.

## [2.0.0] and earlier
Pre-history; not tracked in this file.
