## Background and Motivation
- This is the FIFTH round of model fixes, continuing from the Round 6 6-way audit that found 19 FAILs and 33 WARNINGs
- 21 fixes already applied across 11 files (Rounds 1-2), 150/150 tests pass
- This round tackles the remaining 8 FAILs + selected actionable WARNINGs

## Key Challenges
- Weather API surface_pressure is needed for psychrometrics accuracy
- engine vs sweep LCOE divergence due to different capital scope and CRF lifetimes
- CLI commands (evaluate) are missing implementation

## High-level Task Breakdown

### Phase 1: HIGH-priority FAIL (5 items)
- [ ] FAIL-7/8: weather API — add surface_pressure, remove wind_speed_10m
- [ ] FAIL-9: timezone calendar-year alignment
- [ ] FAIL-14: engine vs sweep LCOE path divergence
- [ ] FAIL-18/19: engine entry NaN validation

### Phase 2: LOW-priority FAIL (3 items)
- [ ] FAIL-15: vfed evaluate CLI command implementation
- [ ] FAIL-16: strategy mode docstrings
- [ ] FAIL-23: CLI help output alignment

### Phase 3: Actionable WARNINGs
- [ ] h_fg consistency across envelope/shr/hvac
- [ ] gamma 0.066 vs 0.0655 consistency
- [ ] T_adp 0°C freeze comment
- [ ] Other fixable WARNINGs

### Phase 4: Regression
- [ ] pytest 150/150 pass

## Project Status Dashboard
- Phase 1: HIGH FAIL — not started
- Phase 2: LOW FAIL — not started
- Phase 3: WARNINGs — not started
- Phase 4: Regression — not started
- Total tests: 150 pass currently

## Executor Feedback
- All previous rounds passed 150/150 tests
- Starting with fresh code after Round 2 fixes
