# Changelog

All notable changes to VFED are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/); versioning is best-effort
semantic — behaviour changes are called out explicitly under **Changed**.

## [Unreleased]

### Added

- **DEH identified setpoint-modulation map (commissioning mode).**
  `DEHDevice` accepts `setpoint_modulation` (a measured `lookup` on the
  humidity setpoint, optional `lookup_dark` for the dark photoperiod, and
  `rh_err_coef` linear feedback) plus `floor_w` (minimum electrical power
  while commanded on). `step()` gains an `is_light` keyword selecting the
  dark table. With a map installed the device drops the generic
  proportional-band/DOE part-load curves: power is linear in the map value
  (`P = P_ref·poly(T,W)·S_DH`) and moisture removal uses a **constant
  effective SMER** (`M = smer·P/3.6e6`) — `smer` in this mode is a
  commissioning value absorbing envelope/infiltration/HVAC-latent residual,
  not a rated SMER. `tau_q`/`tau_m` accept scalar or `(rise, fall)` tuples
  for asymmetric transient lags. Stock behaviour without a map is
  unchanged. `DEHConfig`/`DesignEngine` forward the new fields, and the
  new **`609_identified` preset** ships the Fengxian-identified numbers
  (twin JSONs, 2026-09-22): P_ref 1554.3 W, 6-term poly, dual 9-point
  lookups with rh_err feedback 0.009808, effective SMER 0.25, zero fan
  power (net metering). `preset_609()` itself stays on the stock DEH so
  published baselines remain reproducible. Validated head-to-head against
  the reference implementation (P/M identical to 0.000 W on an 84-cell
  grid; holdout one-step P_deh MAE 389 W vs 507 W for the prior
  calibrated local model).

### Changed

- **609 preset baseline migration (R34/W3-D, counterpart alignment).**
  `preset_609` now explicitly pins `deh.smer: 3.5` and `hvac.eta_II: 0.33`
  (wave 1-A sensitivity scan, user-gym/benchmarks/route3_sensitivity_scan.md,
  migration candidate D1):
  - `deh.smer` 2.0 → 3.5 — rated SMER of a GB/T 19411 whole-facility
    dehumidifier class (clears the B8 −47% conservatism vs the ENERGY STAR
    IEF band).
  - `hvac.eta_II` 0.35 → 0.33 — annual demand-weighted COP 3.99 → 3.85,
    mid-band of the GB 21455 SCOP 3.0–4.0 comparison window (clears the B7
    optimism flag). `delta_T_cond` stays 15 K.
  - This is a **pure device re-calibration**, not a model-structure change:
    `smer_curve` / `smer_map` / `cop_soft_cap` / `defrost` / crankcase all
    remain default off. The reported **delivered SMER caliber switch
    (0.77 → 1.03 kg/kWh)** is the direct arithmetic consequence of
    re-rating smer 2.0 → 3.5 on the same delivered moisture and compressor
    energy — no dispatch or physics-path change is involved.
  - New authoritative 609 @ Shanghai 2025 baseline: annual 61582.59 kWh
    (−1.38%), specific 30.6261 kWh/kg, harvest 100.54 kg, water 10.76 m³,
    grid cost 6158.26, LCOE 0.6687, O&M 35021.51, GHI 1569.54 kWh/m²;
    HVAC 10259.65 kWh, DEH total 9274.94 kWh (compressor 8924.59);
    RH exceed 61.3% (5368 h), RH max 68.16%. Shanghai KPI pins
    (tests 09/10/11/15) migrated and the shared 48 h zero-drift sha256
    oracle (tests 23–28) re-captured.

- **Currency conversion engine (round 26).** VFED now distinguishes
  *explicit* from *default* prices everywhere:
  - A price written in the project YAML is a **literal in the project
    currency and is never converted** (unchanged principle, now enforced
    without exceptions).
  - A price left out (`null` counts as omitted) selects the built-in
    **USD-baseline default**, automatically converted into the project
    currency with `exchange_rate` (project-currency units per 1 USD,
    user-set for reproducibility). USD projects and `exchange_rate: 1.0`
    keep bitwise-identical numbers. Previously the omitted defaults applied
    at USD magnitude under ANY currency label (e.g. an RMB project silently
    got USD-magnitude opex/tariff).
  - Converted defaults: `tariff.hourly_prices` (0.10/kWh) and
    `tariff.export_price` (0.05/kWh), `opex.labor_cost_per_year` (30000/yr),
    `opex.misc_opex_per_year` (5000/yr), `opex.water_cost_per_m3` (2.0/m3),
    `pv.C_pv` (500/kWp), `battery.c_energy` (220/kWh) and
    `*.capital.rate_per_watt` (1.0/W — now behind the same `None` sentinel
    as `capital.cost`). `maintenance_pct` (a fraction) is never converted.
  - `opex_was_defaulted` now means "at least one default OPEX price is in
    effect" (a partially explicit `opex` section keeps the flag), so the
    P1-7 OPEX-dominance warning fires exactly when a default is used.
    A partially explicit section roundtrips losslessly (explicit values are
    preserved through `to_dict`/`from_dict`, including sweep overrides).
  - Presets are built through `from_dict`, so `preset_609()` /
    `preset_default()` now report `opex_was_defaulted = True` (they do use
    the default OPEX); numbers are unchanged.

### Added

- **ERV/HRV mechanical fresh air with heat recovery (R34/W3-E, H7).** New
  additive envelope fields `erv_enabled` (default `false`, bit-identical
  baselines) / `erv_flow_m3h` / `erv_sensible_eff` [0, 0.95] (default 0.7)
  / `erv_latent_eff` [0, 0.95] (default 0 = sensible-only HRV, >0 =
  enthalpy ERV). Fixed-effectiveness model (ASHRAE HVAC Systems and
  Equipment Ch. 26): the un-recovered share `(1-eps)` of the fresh-air
  sensible/latent load superposes on the room balances on top of `ach`
  infiltration; recovered energy is metered in the `erv` summary block
  (sensible/latent kWh split) and a one-line `vfed evaluate` self-evidence.
  Fail-fast: enabled without flow, flow without enabled, effectiveness out
  of band. The 609 preset does not enable ERV.
- `vfed design fx` — prints the built-in FX reference snapshot (CNY/USD/EUR
  and more, per 1 USD, snapshot date annotated, reference values only).
- `vfed evaluate` prints a `USD equivalent` line for the headline LCOE when
  `exchange_rate != 1` (project currency is the reporting currency; the
  extra line keeps cross-site comparisons honest).

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
