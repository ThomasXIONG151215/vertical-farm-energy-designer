# 2026-08-24 Scratchpad — Prosumer Usability Fixes

## 1. Background and Motivation

Follow-up to the prosumer usability review of VFED (see `2026-08-24_scratchpad_review_diy.md`).
The review ran a first-time-prosumer walkthrough (install → `design new` → `validate` → `evaluate` → interpret) and
produced 10 blocker-level usability findings (Always Flag) + style observations. This scratchpad records ALL findings
permanently and plans the fix work.

**Decision (user, m0032):**
- **FIX NOW** — issues **1, 2, 3, 4, 6, 7, 9** of the Always Flag list.
- **RECORD ONLY (untouched for now)** — issues **5, 8, 10**; their existence must be "unforgettable" (tracked here so they are never lost).
- **STYLE fixes** — hardware naming, preset crop label, README.
- **CONSTRAINT** — weather year is **locked to 2025**; do NOT implement any year-change flexibility for weather reference for the moment.
- Order of work: **easy fixes first**, then medium, then style/docs.

## 2. Key Challenges and Analysis

Review headline: VFED is a solid *engineering* tool that a prosumer **cannot use on their own today**.
All 10 blockers are onboarding/presentation/UX issues, not physics issues. The underlying model and result data are rich —
the problems are: (a) the default path is broken offline, (b) output economics are silently meaningless, (c) the YAML
contract and CLI output are engineer-facing, and (d) the web bundle disagrees with the CLI engine (trust issue, deferred).

Key files touched by fixes: `vfed/cli.py`, `vfed/design/project.py`, `vfed/design/presets.py`, `vfed/design/sweep.py`,
`vfed/design/result.py` (already has save_* methods), `vfed-web/index.html` (label text only), `README.md`.

Smoke-test evidence (temp dir, offline env):
- `design new diy_test` → 228-line uncommented YAML; `evaluate` → E003 (city=null).
- `design new diy609 --preset 609` + `evaluate` → SUCCESS offline, but `LCOE = 0.5284 USD/kWh` from opex only (capital all zero) → misleading.
- LED auto-deduce: `400 µmol × 45 m² / 2.5 µmol/J = 7200 W` derived silently.
- `design presets` → hardcoded 2 presets; web label says "Fengxian **Strawberry**" while CLI says "Fengxian **lettuce**".

## 3. High-level Task Breakdown

### A. Fix list (Always Flag 1,2,3,4,6,7,9)

| # | Issue (review #) | Where | Proposed fix |
|---|---|---|---|
| F1 | Default preset offline E003 (#1) | `presets.py:14` `preset_default()`, `project.py:87` (city=None) | Set `city="Shanghai"` in `preset_default()` so bundled `data/weather/Shanghai_2025.csv` is used. Year stays 2025 (locked). Verify no weather-fetch on first `evaluate`. |
| F2 | Misleading LCOE, zero capital (#2) | `cli.py:162` `_cmd_evaluate` | Print a warning when total capital ≈ 0 (all `capital.cost=0.0`) or when opex still at defaults (labor 30000 / misc 5000), and surface `capital_total` in output so LCOE semantics are transparent. |
| F3 | Uncommented, unit-less generated YAML (#3) | `cli.py` `_cmd_design_new` (YAML emit) | Emit commented YAML with units + inline guidance for every section (site/envelope/hvac/deh/led/setpoints/capital/opex/pvbes). Keep strict schema identical — comments only. |
| F4 | 609-dimensioned hardware defaults, auto_size off (#4) | `project.py:117,145,155,158,175` | Make the DIY base sensible: `preset_default()` → small-scale envelope + `auto_size=True` for HVAC/DEH; `preset_609()` explicitly `auto_size=False` to preserve current behavior. Update tests. |
| F5 | CLI hides humidity/moisture results (#6) | `cli.py:157-164` `_cmd_evaluate` | Print `dehumidifier_performance` (`deh_utilization`, `removal_limited_events`), `annual_water_m3`, RH clamp stats — already computed in `engine.py` summary, just not surfaced. |
| F6 | No CLI export of result data (#7) | `cli.py` `_cmd_evaluate` + `result.py` | Add export flag (e.g. `--export` / `--out-dir`) on `vfed evaluate` calling `result.save_summary_csv / save_timeseries_csv / save_monthly_csv`. |
| F7 | Sweep parameter-name trap (#9) | `sweep.py` `_PARAM_PATH_MAP` | Accept `pv_area_m2` / `battery_kwh` as aliases for `pv_area` / `battery` in `space.parameter_ranges` (normalize internally); document mapping. |

### B. Style fixes

| # | Item | Where | Proposed fix |
|---|---|---|---|
| S1 | Hardware naming inconsistency (`P_rated_w` vs `P_ref_w` vs `Q_cool_nom` kW vs `M_deh_nom` L/day vs `P_rated_max`) | `project.py` + web | Establish one vocabulary with units; add alias support or a documented unit/naming map. Caution: `from_dict` strictly rejects unknown keys — add aliases only via explicit normalization, keep back-compat. |
| S2 | Preset crop label mismatch ("Fengxian Strawberry" web vs "Fengxian lettuce" CLI) | `vfed-web/index.html:814,2353` | Change label text to "Fengxian lettuce PFAL" (matches `presets.py` / `cli.py:90`). Source text only; bundle rebuild deferred with R3. |
| S3 | README research-oriented, no DIY onboarding | `README.md` | Add DIY/prosumer section: 10 m² factory tutorial, hardware-spec-to-YAML walkthrough, offline quick start that works with default preset. |

### C. Record-only (untouched now — existence must stay unforgettable)

| # | Issue (review #) | Where | Status / future |
|---|---|---|---|
| R1 | LED auto_deduce surprise — silent 7.2 kW derivation (#5) | `project.py:187-192` | Deferred. Behavior kept. Future: surface derivation in output + YAML comment; consider warning when covered_area ≫ plausible home scale. |
| R2 | Only 2 presets, no small/home-scale (#8) | `presets.py`, `cli.py:90` | Deferred (scratchpad D1). Future: add small/home/modular preset. |
| R3 | vfed-web diverges from CLI engine — stale bundle (ach 0.5, C_z 500000.0, area_to_power 190, "Fengxian Strawberry", pre-humidity-fix engine) (#10) | `vfed-web/index.html:2351-2360`, worker.js | Deferred. Engine must NOT be touched now. Only S2 (label text) allowed. Future: rebundle via `python bundle.py` after engine sync; fix unphysical preset values (ach→0.001, C_z→200000, area_to_power→4.3). |

### D. Constraints

- **C1 (weather year)**: year locked to 2025 for weather reference. No year-change support for now. All fixes must not add it.
- **C2 (web engine)**: vfed-web engine untouched; only the crop-label text change (S2) is in scope.
- **C3**: `from_dict` strict validation — any new field/alias must be added there first (project.py is the config contract).
- **C4**: `pytest` before commit; smoke-test the CLI flow offline (temp dir, `--cache weather_cache`).

### E. Execution order (easy → hard)

1. **Phase 1 — easy, low-risk**: F1 (preset_default city), F5 (humidity prints), F2 (capital-zero warning), S2 (web label text).
2. **Phase 2 — medium**: F7 (sweep aliases), F6 (export flag), F3 (commented YAML writer), F4 (preset/auto_size semantics + tests).
3. **Phase 3 — style/docs**: S1 (hardware naming map), S3 (README DIY onboarding).
4. **Never dropped**: R1, R2, R3 remain recorded; revisit after phases 1–3.

## 4. Project Status Dashboard

| Task | Status | Notes |
|---|---|---|
| F1 preset_default city="Shanghai" (offline E003) | pending | Easy; must verify first-run evaluate works offline |
| F2 capital-zero LCOE warning | pending | Easy; print warning + capital_total |
| F5 CLI humidity/moisture output | pending | Easy; data already in summary |
| S2 web crop label text fix | pending | Easy; source text only, no rebundle |
| F7 sweep pv_area_m2/battery_kwh aliases | pending | Medium; validation + docs |
| F6 `vfed evaluate --export` (CSV save) | pending | Medium; uses existing result.save_* |
| F3 commented unit-annotated YAML emit | pending | Medium; comments only, schema identical |
| F4 preset_default small-scale + auto_size=True | pending | Medium; needs test updates, 609 unaffected |
| S1 hardware naming map / aliases | pending | Style; careful with strict validation |
| S3 README DIY onboarding (10 m² tutorial) | pending | Docs |
| R1 LED auto_deduce surprise | recorded — deferred | Do not implement now |
| R2 small/home-scale presets | recorded — deferred | Do not implement now |
| R3 vfed-web engine divergence | recorded — deferred | Engine untouched; only S2 allowed |

## 5. Executor Feedback or Help Requests

- Environment is **offline** (Open-Meteo unreachable, proxy error). All offline verification must use bundled `data/weather/*_2025.csv` via `--city Shanghai` (or F1 fix) + `--cache weather_cache`.
- Smoke-test scratch dir: `C:\Users\ADMINI~1\AppData\Local\Temp\opencode` (diy_test.yaml, diy609.yaml already generated).
- Reference materials: full review report is in the session context (10 Always Flag findings with file:line evidence); REVIEW.md update was NOT confirmed by user and is parked.
