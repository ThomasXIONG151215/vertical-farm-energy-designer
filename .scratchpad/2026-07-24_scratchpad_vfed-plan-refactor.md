# 2026-07-24 — VFED Plan Refactor

> Scratchpad for reorganising the VFED project plans with clear separation of concerns.

---

## 1. Background and Motivation

The VFED project had accumulated two sprawling, chaotic planning documents that mixed simulation/model concerns with UI/webapp concerns in an unstructured way. There was no clear boundary between "what the simulation engine computes" and "what the webapp renders", making it difficult to reason about dependencies, implementation order, and ownership.

The user asked to refactor these into two cleanly separated plans:

| Plan File | Scope | Length |
|-----------|-------|--------|
| `vfed-models-plan.md` | All simulation, computation, data infrastructure | 228 lines |
| `vfed-web-gran-plan.md` | All UI, layout, interaction, frontend rendering | 331 lines |

Both plans now cross-reference each other explicitly with "不在本Plan范围的内容" (out of scope) sections at the end of each.

---

## 2. Key Decisions

### 2.1 Separation Boundary

**vfed-models-plan.md** now covers ONLY simulation/model computation changes:
- M1–M11 phases: HVAC/DEH settings-oriented refactor, LED spectrum model, spatial layout, weather/electricity databases, AI strategy models, economic model, water/pump model
- All Python code changes in `src/`
- No UI concerns whatsoever

**vfed-web-gran-plan.md** now covers ONLY UI/webapp layer:
- W1–W7 phases: real-time preview, URL sharing, parameter optimisation, LED spectrum UI, cost analysis, 3D container visualisation, custom spatial design
- All changes in `vfed-web/`
- Computation stays Pyodide browser-side

### 2.2 Phase Ordering

The web phase order was adjusted to be more logical:
```
W1 (real-time preview) → W2 (URL sharing) → W4 (parameter optimization)
                                               ├── W3 (LED spectrum UI, depends on M1)
                                               └── W5 (cost analysis, depends on M10)
W1 → W6 (3D container, depends on M6+M7+M8+M9) → W7 (custom spatial design)
```

Key change: **parameter optimization (W4) moved before LED spectrum UI (W3)** — the sweep/optimisation mode is higher priority than the LED spectrum customisation feature.

### 2.3 Dependency Mapping

Model ↔ Web phase dependencies are now explicit:
- M2+M3 (HVAC/DEH refactor) → W1 (real-time preview) — highest priority
- M4+M5 (weather/electricity DBs) → W1+W5
- M1 (LED spectrum) → W3
- M6+M7+M8+M9 (spatial + pump) → W6
- M10 (cost model) → W5
- M11 (AI strategies) → future web phase

### 2.4 Architecture Preserved

- Pyodide Worker + bundler (`bundle.py`) stays — all Python executed browser-side
- No backend/server introduced
- No user registration

---

## 3. Gap Analysis Summary

Completed gap analysis between existing `src/` models and desired features:

| Category | Existing | Missing |
|----------|----------|---------|
| HVAC | Fixed COP/rated power | Auto-size from T_setpoint + load |
| DEH | Fixed polynomial coefficients | Auto-size from RH_setpoint + moisture load |
| LED | Fixed efficacy (µmol/J) | Spectrum → real PPF/W calculation |
| Weather | Manual lat/lon fetch | City search + pre-downloaded DB |
| Tariff | Manual 24h array | Regional tariff database |
| Spatial | None | Container layout, rack arrangement, equipment placement |
| Water/Pump | None | Pump power model |
| Cost | Basic CAPEX + LCOE | Full CAPEX+OPEX → $/kg, payback period |
| AI Strategies | None | Dynamic PPFD, temperature, power scheduling |

---

## 4. File Manifests

### Modified Files

| File | Lines | Description |
|------|-------|-------------|
| `vfed-models-plan.md` | 228 | Simulation & computation plan: baseline inventory, gap analysis (M1–M11), implementation phases, dependency diagram |
| `vfed-web-gran-plan.md` | 331 | UI/WebApp plan: baseline inventory, core architecture diagram, W1–W7 phases with wireframes, dependency diagram, cross-cutting UX features |
| `src/devices/hvac.py` | +60 | M-Carnot: COPModel mode default `carnot`; `__call__` accepts `T_indoor`; `size_hvac()` design cooling load → P_rated |
| `src/devices/dehumidifier.py` | +30 | M3: `size_deh()` moisture load → P_ref via SMER |
| `src/plants/transpiration.py` | +40 | M-Transp: k_vpd=2e-5; added `daily` and `per_plant` direct-set methods |
| `src/design/project.py` | +30 | M2+M3+M-Carnot+M-Transp: HVACConfig auto_size/eta_II/delta_T; DEHConfig auto_size; TranspirationConfig daily_water_L/plant_count/ml_per_plant_day |
| `src/design/engine.py` | +20 | M2+M3+M-Carnot: HVAC auto-size with Carnot COP; DEH auto-size; 6 transpiration methods handled |
| `vfed-web/worker.js` | +140 | W1: Added `runSinglePoint()` — new `simulate` message handler runs `DesignEngine.run()` via Pyodide, computes monthly/seasonal/composition/climate aggregations, returns compact JSON |
| `vfed-web/index.html` | +300 | W1+UI: Single Point mode tab with real-time preview; Carnot COP dropdown; conditional field visibility (updateFieldVisibility); `renderField` supports `type:'select'` |
| `vfed-web/index.html` | +80 | W2: Share button (🔗) in header; `encodeState()`/`decodeState()`/`updateShareURL()`/`copyShareLink()` functions; URL state auto-updates on param change and mode switch; init checks `?state=` query param and restores if present; state format `{v:1, yaml, sweeps, mode, objective}` → JSON → btoa → encodeURIComponent |
| `tests/test_devices.py` | +110 | 18 HVAC/DEH unit tests (Carnot COP, size_hvac, size_deh) |
| `tests/test_transpiration.py` | +140 | 23 transpiration unit tests (6 methods, edge cases, equivalence) |
| `tests/test_04_config.py` | +80 | +8 config tests (Carnot round-trip, auto_size, daily/per_plant YAML) |
| `tests/test_05_regression.py` | +70 | +6 regression tests (Carnot COP, auto_size, VPD, daily) |
| `vfed-web/test_comprehensive.js` | +200 | 12 Playwright tests (URL state, field visibility, chart rendering) |
| `vfed-web/worker.template.js` | +140 | W1: Added `runSinglePoint()` + `simulate` handler to template for `bundle.py` rebuilds |

### Sections in vfed-models-plan.md
```
0. Baseline — Already Implemented (32-row inventory table)
1. Gap Analysis — Missing Models (11 items, M1–M11)
2. Model Implementation Phases
   - Phase M-HIGH: M2 (HVAC refactor), M3 (DEH refactor)
   - Phase M-MID: M4 (weather DB), M5 (tariff DB)
   - Phase M-LOW: M1 (LED spectrum), M6+M7+M8 (spatial), M9 (water/pump), M10 (cost), M11 (AI strategies)
3. Dependency Diagram (ASCII graph)
4. Out of Scope → vfed-web-gran-plan.md
```

### Sections in vfed-web-gran-plan.md
```
0. Baseline — Existing Web App (inventory table)
1. Core UI Architecture (ASCII wireframe)
2. Implementation Phases
   - W1: Real-time preview (structured forms + auto-recalc)
   - W2: URL sharing (base64 state encoding)
   - W4: Parameter optimisation mode (scatter plots, sweep)
   - W3: LED spectrum UI (spectrum presets + drag curve)
   - W5: Full cost analysis ($/kg, waterfall chart)
   - W6: 3D container visualisation (Three.js)
   - W7: Custom spatial design (drag-and-drop, multi-room)
3. Cross-Cutting UX Features (i18n, no-registration)
4. Phase Dependency Diagram
5. Out of Scope → vfed-models-plan.md
```

---

## 5. Project Status Dashboard

| ID | Task | Status | Notes |
|----|------|--------|-------|
| Plan-1 | Separate models vs web concerns | ✅ Complete | Clear boundary: models=src/ Python, web=vfed-web/ JS+HTML |
| Plan-2 | Gap analysis (existing vs desired) | ✅ Complete | 11 missing models identified across 3 priority tiers |
| Plan-3 | Phase ordering (W3↔W4 swap) | ✅ Complete | Parameter optimisation (W4) now precedes LED spectrum (W3) |
| Plan-4 | Dependency mapping | ✅ Complete | Each web phase explicitly mapped to required model phase |
| Plan-5 | Cross-reference sections | ✅ Complete | Each plan references the other with "out of scope" section |
| M2 | HVAC settings-oriented refactor | ✅ Complete | `size_hvac()` computes design cooling load → P_rated; `auto_size: bool` in HVACConfig. Engine builds LED first, then auto-sizes HVAC if auto_size=True. |
| M3 | DEH settings-oriented refactor | ✅ Complete | `size_deh()` computes moisture load → P_ref via SMER; `auto_size: bool` in DEHConfig. Engine calculates moisture from transpiration+infiltration+permeance at design conditions. |
| M1 | LED spectrum → real PPF/W | ⬜ Not started | Phase M-LOW. Prerequisite for W3 (LED spectrum UI). |
| M-Carnot | Carnot COP model (new default) | ✅ Complete | COP = η_II × T_evap/(T_cond-T_evap). Literature: Madonna & Bazzocchi (2013), EnergyPlus. Typical: η_II=0.35, ΔT_evap=8K, ΔT_cond=15K. Updated: hvac.py, project.py, engine.py, index.html. |
| M-Transp | Transpiration model expansion | ✅ Complete | 6 methods: 3 model-calculated (vpd/stomatal/van_henten) + 3 direct-set (constant/daily/per_plant). k_vpd lowered to 2e-5 per literature. Regression bounds updated (annual load 25→22 MWh). |
| W1 | Real-time preview webapp | ✅ Complete | Single Point mode: `simulate` handler in worker.js, 2×2 chart grid in index.html. |
| W2 | Unified URL sharing | ✅ Complete | `encodeState()` → JSON→btoa→`?state=`, `decodeState()` restores form+sweeps+mode, share button |
| T-Devices | HVAC/DEH unit tests | ✅ Complete | 18 tests: Carnot COP modes, size_hvac, size_deh, table interpolation |
| T-Transp | Transpiration unit tests | ✅ Complete | 23 tests: 6 methods, equivalence, zero-dark, stage_factor |
| T-Config | Config validation tests | ✅ Complete | +8 tests: Carnot round-trip, auto_size defaults, daily/per_plant YAML |
| T-Regress | Regression checkpoints | ✅ Complete | +6 tests: Carnot COP, auto_size HVAC+DEH, VPD, daily transpiration |
| T-Web | Playwright web tests | ✅ Complete | 12 tests: URL encode/decode, form visibility, chart rendering |
| Tests | Total test suite | ✅ Complete | 129 Python + 12 Web = 141 tests, all pass |
| W3 | LED spectrum UI | ⬜ Not started | Depends on M1 (LED spectrum model). |
| W4 | Parameter sweep UI | ⬜ Not started | Scatter plots, sweep controls, objective selection. |
| W5 | Full cost analysis | ⬜ Not started | $/kg breakdown, waterfall chart. |
| W6 | 3D container visualisation | ⬜ Not started | Three.js, depends on spatial models. |
| W7 | Custom spatial design | ⬜ Not started | Drag-and-drop, multi-room layout. |

---

## 6. Executor Feedback or Help Requests

- Both plan files are complete and ready for implementation review.
- **2026-07-24 — Complete: Model-layer + W1+W2 + Full Test Suite**:
  - HVAC/DEH auto-size (M2+M3): `size_hvac()` / `size_deh()` compute design loads, backward compatible.
  - Carnot COP model (new default): η_II × T_evap/(T_cond-T_evap), 4 modes (carnot/constant/linear/table).
  - 6 transpiration methods: 3 model-calculated + 3 direct-set, k_vpd=2e-5.
  - W1 (real-time preview): Single Point mode, debounced auto-sim, 2×2 chart grid.
  - W2 (URL sharing): base64-encoded state in `?state=`, full form+sweeps+mode restore.
  - Bug fix: `worker.template.js` missing `runSinglePoint` — `bundle.py` rebuilds broke W1 Web UI. Added full function to template.
  - **Tests: 141 pass** (129 Python + 12 Playwright). 6 new test files. All layers covered.
- Next: W4 (parameter sweep/optimisation UI) per plan order.
