# Scratchpad: Currency, OPEX & Cost Calculation Fixes

**Date**: 2026-07-26
**Project**: VFED (垂直农业能源设计器)
**Related Scratchpad**: 2026-07-26_scratchpad_vfed-web-model-params.md (UI infrastructure + preset values audit)
**Status**: ✅ Complete
**Created by**: create agent

---

## Background and Motivation

Earlier today, we completed major UI infrastructure work (SECTIONS from 58→135+ fields, visibilityKey system, 5 backend wiring bugs, preset values audit). Now moving to fix three core simulation integrity issues:

1. **Currency system is completely non-functional** — `currency` (USD/CNY/EUR/JPY) and `exchange_rate` are pure pass-through annotations with zero computational effect. All 14+ cost displays in the web UI hardcode `$`. `SimulationResult` doesn't carry currency metadata.

2. **OPEX costs are entirely orphaned** — `OpexConfig` fields (water, labor, misc, maintenance_pct) are defined in config but NEVER read by any LCOE or cost computation. Only `CAPEX_total × 0.01` is used as OM, massively understating total cost (by ~$35k+/yr).

3. **Weather data uses API/cache instead of local files** — 51 pre-downloaded city CSVs exist at `data/weather/` for 2025, but presets don't set `city`, causing fallback to Open-Meteo API. Also `site.year` is in SECTIONS but always should be 2025.

Root cause: 4-bug investigation earlier today found that `engine.py`/`sweep.py` create cost metrics without any awareness of project's currency or OPEX, and `SimulationResult` carries no currency metadata.

---

## Key Challenges

- Currency requires coordinated backend (result.py, engine.py, cli.py) + frontend (14+ hardcoded `$` replacements) changes
- OPEX integration requires tracking actual water consumption from transpiration model (not a flat number)
- Local weather CSVs are only activated when `site.city` is set; currently presets use bare lat/lon
- All cost values should stay RAW FLOATS in project currency; `exchange_rate` is for USD comparison display only

---

## High-level Task Breakdown

### Phase 1: Weather Data — Switch to Local CSVs
- Remove `site.year` from SECTIONS
- Add `city` to preset YAMLs (609→Shanghai, lettuce_standard→Tokyo)
- Update Python presets
- Remove `getCachedWeather()` dead code in index.html

### Phase 2: Currency Backend
- Add `currency` + `exchange_rate` to `SimulationResult`
- Pass through from engine to result
- Fix CLI hardcoded `"$/kg"` labels

### Phase 3: Currency Frontend
- Dynamic `CURRENCY_SYMBOL` mapping
- Replace all hardcoded `$` in display, labels, and mock data
- Currency change triggers re-render

### Phase 4: OPEX Scene Bar
- New "OPEX" scene-group with Water/Labor/Misc fields
- Add to SCENE_KEYS

### Phase 5: OPEX → LCOE Integration
- Track annual water consumption from transpiration
- Fix `annual_om` to include all OPEX components
- Fix `specific_cost_per_kg` to include total cost (not grid-only)
- Sync sweep.py changes

---

## Project Status Dashboard

| Phase | Task | Status | Files Changed |
|-------|------|--------|---------------|
| 1 | Weather data switch | ✅ Complete | `web/static/vfed-3d/index.html`, `data/presets/609.yaml`, `data/presets/lettuce_standard.yaml`, `src/design/presets.py`, `data/weather/` (51 CSVs) |
| 2 | Currency backend | ✅ Complete | `src/design/result.py`, `src/design/engine.py`, `src/cli.py` |
| 3 | Currency frontend | ✅ Complete | `web/static/vfed-3d/index.html` (CURRENCY_SYMBOL, getCurSymbol, updateCurrencyLabels, onSinglePointComplete) |
| 4 | OPEX scene bar | ✅ Complete | `web/static/vfed-3d/index.html` (OPEX scene-group, 3 SCENE_KEYS) |
| 5 | OPEX → LCOE integration | ✅ Complete | `src/design/engine.py`, `src/pvbes/sweep.py` (150/150 tests pass) |

---

## Executor Feedback or Help Requests

(All 5 phases completed — see dashboard above.)

All phases completed in commit `1a985cb`. Key outcomes:

- **Currency**: Full end-to-end flow — `SimulationResult` carries `currency` + `exchange_rate`, engine passes them through, CLI uses dynamic symbol, frontend has `CURRENCY_SYMBOL` mapping with auto-update on currency change.
- **OPEX**: Water/Labor/Misc fields now wired through engine → summary → `specific_cost_per_kg`. `annual_om` includes `maintenance_pct*CAPEX + water + labor + misc`. Water tracked from actual transpiration model output.
- **Weather**: 51 local city CSVs at `data/weather/` now used via `city` parameter instead of live API. `site.year` removed from SECTIONS.
- **Tests**: 150/150 pass after all changes.
- **Files touched across all phases**: `index.html`, `presets.py`, `engine.py`, `result.py`, `cli.py`, `sweep.py`, preset YAMLs, 51 weather CSVs.
