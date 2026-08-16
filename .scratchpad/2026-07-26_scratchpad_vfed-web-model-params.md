## Background and Motivation
The vfed-web UI (index.html) had incomplete parameter coverage for model-switching selectors. When users switched transpiration models or HVAC COP modes, dependent parameters didn't appear/disappear. Additionally, `sled.photoperiod_hours` and `transpiration.photoperiod_hours` existed as independent fields but needed a single source of truth (LED dictates transpiration). The engine had optimization dead code and stale CapitalCostConfig/OpexConfig sections that needed wiring up.

**Status**: Core work done. SECTIONS expanded from 58→100+ fields; all selectors now have dependent visibility; backend fully wired; 150/150 tests pass.

## Key Challenges and Analysis
1. ~~SECTIONS schema in index.html has only 58 of 122 backend fields~~ → RESOLVED: Now 100+ fields across 8 sections
2. ~~transpiration.method selector exists but has ZERO sub-parameter fields~~ → RESOLVED: 11 sub-params added with visibleKey
3. ~~hvac.heat_mode selector exists in preset YAML but not in UI~~ → RESOLVED: Added with dependent fields
4. ~~led.auto_deduce, led.spectrum selectors not in UI~~ → RESOLVED: Added with type support
5. ~~hvac.auto_size, deh.auto_size boolean selectors not in UI~~ → RESOLVED: Added as checkbox/bool type
6. ~~COP table mode has no table editor~~ → RESOLVED: kvlist key-value pair editor added
7. ~~DEHConfig.smer and LEDConfig.spectrum fields not wired to devices~~ → RESOLVED: Backend fully wired
8. ~~CapitalCostConfig and OpexConfig absent from UI~~ → RESOLVED: New Economic section with 24 fields

## High-level Task Breakdown

### Phase 1: Scratchpad + Photoperiod Fix ✅
1. [DONE] Investigate photoperiod_hours flow — traced through engine.py, transpiration.py, led.py
2. [DONE] Make LED.photoperiod_hours the single source of truth — 3 locations changed in engine.py
3. [PENDING] Clean up optimization dead code in engine.py
4. [DONE] Add CapitalCostConfig, OpexConfig, and PV advanced params to UI SECTIONS

### Phase 2: Conditional Visibility Extension ✅
5. [DONE] Extend visible/visibleKey system to support multiple independent selectors via data-visible-key attribute
6. [DONE] Add all transpiration sub-parameters (11 fields) with conditional visibility per method
7. [DONE] Add hvac.heat_mode selector + dependent fields (cop_heat, P_rated_heat_w)
8. [DONE] Add led.auto_deduce toggle + power_w field
9. [DONE] Add led.spectrum select field
10. [DONE] Add hvac.auto_size, deh.auto_size toggles + dependent fields (checkbox/bool type)
11. [DONE] Add COP table editor (kvlist key-value pair UI with add/delete buttons)

### Phase 3: Backend Wiring Fixes ✅
12. [DONE] Wire LEDConfig.spectrum → LEDDevice in engine.py
13. [DONE] Wire DEHConfig.smer → DEHDevice in engine.py
14. [DONE] Add r_a field (float, default 50.0) to TranspirationConfig in project.py
15. [DONE] Add cop_table: dict field to HVACConfig in project.py; wired to COPModel via table=p.hvac.cop_table

### Phase 4: Field Expansion + Presets ✅
16. [DONE] Expand all sections: HVAC 14→24, DEH 7→13, LED 5→8, Growth 10→21, PV 6→8, Battery 6→8, NEW Economic (24), NEW Site (7)
17. [DONE] Update preset YAMLs (609 + lettuce_standard) with transpiration block + hvac.cop_table

### Phase 5: Validation ✅
18. [DONE] All 150 tests pass (pytest)

### Phase 6: Preset Values Audit & UI Bug Fixes ✅
19. [DONE] Audit preset values against Python dataclass defaults — found massive discrepancies (U_wall_A, V_room, C_z, pv labels, deh.eta_ref >1, etc.)
20. [DONE] Fix 609 preset: V_room:5000→200, U_wall_A:0.35→125.3, C_z:1.2M→499.6K, led (ppfd/efficacy/heat_fraction/covered_area), hvac (fan/min_on_off/tau), deh (eta_ref/ah_min/fan/min_on_off), pv (eta_pv/area_to_power/C_pv/eta_inv/degrad), battery (c_energy/c_rate/eta/cycle_life), tariff, interest_rate
21. [DONE] Fix lettuce_standard preset: V_room:3000→200, C_z:800K→500K, U_wall_A:0.3→100, led.heat_fraction, hvac (Q_cool_nom/fan/min_on_off/tau), deh (M_deh_nom/eta_ref/ah_min/deadband/fan/min_on_off), tariff
22. [DONE] Fix SECTIONS labels: pv.area_to_power (Wp/m²→m²/kWp, step:10→0.5), pv.C_pv ($/Wp→$/kWp, step:50→10)
23. [DONE] Fix pv_area_m2: added default:200 in SECTIONS, removed buggy formula from getDefaultFormValues
24. [DONE] Fix first3 sidebar visibility bug: hidden fields (visibleKey) no longer in sidebar — added isFieldVisible() helper
25. [DONE] Remove transpiration.photoperiod_hours from both preset YAMLs
26. [DONE] Set Q_cool_nom:15/M_deh_nom:70 (609) and Q_cool_nom:12/M_deh_nom:60 (lettuce) — replaces confusing "0 kW/0 L/day"
27. [DONE] P_rated_max: kept — advanced users need max electrical caps; tooltips already clear
28. [DONE] 150/150 tests pass after all changes

## Project Status Dashboard

| Task | Status | Notes |
|------|--------|-------|
| Photoperiod investigation | DONE | Traced flow through engine.py, transpiration.py, led.py |
| Single-source photoperiod | DONE | 3 locations changed: `p.transpiration.photoperiod_hours` → `p.led.photoperiod_hours` |
| Engine dead code cleanup | PENDING | Remove optimization code remnants |
| CapitalCost/Opex/PV params | DONE | New Economic section (24 fields) + PV maintenance/NOCT |
| visibleKey system extension | DONE | `data-visible-key` attribute, multi-selector support |
| Transpiration sub-params | DONE | 11 fields with conditional visibility per method (vpd/stomatal/van_henten) |
| hvac.heat_mode + deps | DONE | Selector + cop_heat, P_rated_heat_w |
| led.auto_deduce + power_w | DONE | Checkbox toggle + power_w field |
| led.spectrum field | DONE | Select field in LED section, wired to LEDDevice |
| auto_size toggles | DONE | HVAC and DEH auto-sizing params (checkbox/bool type) |
| COP table editor | DONE | kvlist key-value pair UI with add/delete |
| Backend wiring: spectrum | DONE | `spectrum=p.led.spectrum` in LEDDevice constructor |
| Backend wiring: smer | DONE | `smer=p.deh.smer` in DEHDevice constructor |
| Backend wiring: r_a | DONE | `r_a: float = 50.0` added to TranspirationConfig |
| Backend wiring: cop_table | DONE | `cop_table: dict = field(default_factory=dict)` in HVACConfig |
| Static fields expansion | DONE | HVAC 14→24, DEH 7→13, LED 5→8, Growth 10→21, PV 6→8, Battery 6→8 |
| Economic section (new) | DONE | 24 fields: CapitalCostConfig × 5 components + OpexConfig |
| Site section (new) | DONE | 7 fields: tilt, azimuth, year, rho_air, cp_air, initial_dry_weight, dry_matter_fraction |
| Preset YAML updates | DONE | 609 + lettuce_standard: transpiration block + hvac.cop_table |
| CSS for kvlist/checkbox | DONE | .kvlist, .kvrow, .kvdel, .kvadd styles; checkbox rendering |
| Preset values audit | DONE | Compared JS presets vs Python defaults; fixed 609 + lettuce_standard |
| 609 preset fix | DONE | V_room, U_wall_A, C_z, eta_solar, led, hvac, deh, pv, battery, tariff values |
| lettuce_standard preset fix | DONE | V_room, C_z, U_wall_A, hvac, deh, battery, tariff values |
| SECTIONS label fixes | DONE | pv.area_to_power m²/kWp, pv.C_pv $/kWp; steps corrected |
| pv_area_m2 default | DONE | default:200; removed buggy formula (0.233×4.3×0.5=0.5m²) |
| first3 visibility bug | DONE | isFieldVisible() filter; hidden fields no longer in sidebar |
| transpiration.photoperiod_hours | DONE | Removed from both presets (LED is source of truth) |
| Q_cool_nom / M_deh_nom | DONE | Replaced "0 kW/0 L/day" with reasonable values per scenario |
| P_rated_max decision | DONE | Kept; 0=unlimited, tooltip explains derivation |
| Tests | DONE | 150/150 pass |

## Executor Feedback or Help Requests
- **2026-07-26 (Phase 6)**: Preset values audit + UI bugs fixed. Key deliverables:
  - Both preset YAMLs now match Python dataclass defaults (V_room 200, U_wall_A ~100-125, LED heat_fraction 1.0, etc.)
  - Fixed egregious bugs: deh.eta_ref=1.2 (>1 efficiency), pv area_to_power labeled as Wp/m² but valued at 180, pv.C_pv labeled $/Wp but valued at $800
  - SECTIONS label/step corrections: area_to_power now m²/kWp, C_pv now $/kWp
  - first3 sidebar now respects visibility rules (isFieldVisible filter)
  - Removed transpiration.photoperiod_hours from preset YAMLs
  - Q_cool_nom/M_deh_nom now show reasonable defaults (not "0")
  - P_rated_max fields kept (too]tip explains "0=auto-derive")
  - **Remaining**: Engine optimization dead code cleanup (Phase 1, task 3)
