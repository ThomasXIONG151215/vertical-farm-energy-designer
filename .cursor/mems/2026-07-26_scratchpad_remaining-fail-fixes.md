## Background and Motivation
- This is the FIFTH round of model fixes, continuing from the Round 6 6-way audit that found 19 FAILs and 33 WARNINGs
- 21 fixes already applied across 11 files (Rounds 1-2), 150/150 tests pass
- This round tackles the remaining 8 FAILs + selected actionable WARNINGs

## Key Challenges
- Weather API surface_pressure is needed for psychrometrics accuracy
- engine vs sweep LCOE divergence due to different capital scope and CRF lifetimes
- CLI commands (evaluate) are missing implementation

## High-level Task Breakdown

### Phase 1: HIGH-priority FAIL (5 items) — COMPLETED ✅
- [x] FAIL-7/8: weather API — add surface_pressure, remove wind_speed_10m
- [x] FAIL-9: timezone calendar-year alignment
- [x] FAIL-14: engine vs sweep LCOE path divergence (engine now uses full-system capital via sweep.py)
- [x] FAIL-18/19: engine entry NaN validation on weather input arrays

### Phase 2: LOW-priority FAIL (3 items) — COMPLETED ✅
- [x] FAIL-15: vfed evaluate CLI command implementation
- [x] FAIL-16: strategy mode docstrings added to project.py module docstring
- [x] FAIL-23: CLI help output alignment (evaluate subcommand registered)

### Phase 3: Actionable WARNINGs — COMPLETED ✅
- [x] h_fg: engine.py already uses temperature-dependent latent_heat_vaporization()
- [x] gamma: 0.066 → 0.0655 (standard psychrometric constant at 20°C)
- [x] T_adp 0°C freeze: verified with existing comments — no changes needed

### Phase 4: Regression — COMPLETED ✅
- [x] pytest 150/150 pass (74.80s)

## Project Status Dashboard
- Phase 1: HIGH FAIL — **COMPLETED** ✅
- Phase 2: LOW FAIL — **COMPLETED** ✅
- Phase 3: WARNINGs — **COMPLETED** ✅
- Phase 4: Regression — **COMPLETED** ✅
- Total tests: **150/150 pass** (74.80s)

## File Changes Summary
| File | Change |
|------|--------|
| `src/weather/weather_bridge.py` | +surface_pressure, -wind_speed_10m |
| `src/physics/ode.py` | +P_atm parameter in __init__ and step_humidity |
| `src/design/engine.py` | +P_atm threading, +NaN validation, +full-system LCOE via sweep imports |
| `src/cli.py` | +vfed evaluate subcommand |
| `src/design/project.py` | +strategy mode docstring |
| `src/plants/transpiration.py` | gamma 0.066 → 0.0655 |

## Executor Feedback
- All 150 tests pass (74.80s)
- engine.py → sweep.py import is lazy (inside run()) to avoid circular dependency
- Strategy modes are documented but not yet implemented (pending feature)
- Weather API now provides surface_pressure (hPa) which is averaged and converted to kPa for psychrometrics
- Round 5 of model fixes complete — all Phase 1-4 items resolved
