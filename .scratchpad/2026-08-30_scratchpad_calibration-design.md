# Scratchpad — VFED Calibration / Fitting Feature Design (Research + Proposal)

Date: 2026-08-30
Status: DESIGN PROPOSAL ONLY — no code written (per task scope)

## 1. Background and Motivation

User wants to fit UNKNOWN model parameters from their OWN measured data
(indoor T/RH/energy logs) to create a scenario-specific (facility-specific)
model, with some parameters already known. Task was a research + design
proposal; no code changes made.

## 2. Key Findings (current state)

- Active `vfed/` has ZERO fit/calibrate/least_squares/scipy code. Only
  comments describing params as "calibratable"/"calibrated from literature"
  (van_henten.py:38, transpiration.py:87, presets.py:45, project.py:255).
- "calibrate" code only exists in archived `research/` + `reference/`
  (StepSizeCalibrator, CMA/GA/PSO for Van Henten) — not importable (boundary).
- No user-measurement ingestion path anywhere.
- `DesignProject.from_dict` rejects unknown keys → a `fit:` section needs a
  new FitConfig dataclass + `_TOP_KEYS` entry in project.py.
- `DesignEngine.run(project, weather=df)` ALREADY accepts an optional hourly
  weather DataFrame → the key hook for fitting over a measured window.
- Hourly outputs: T_z, RH_z, T_ext, RH_ext, GHI, load_kw, E_hvac_Wh,
  E_deh_Wh, E_led_Wh, E_misc_Wh, X_d (+ monthly/summary KPIs).
- Engine auto-size has side effect (writes nameplates back to project) →
  calibrator must deepcopy + disable auto_size during fit.
- Deps: numpy/pandas/pyyaml/requests only. scipy NOT present.
- sweep.py has `_PARAM_PATH_MAP` registry pattern reusable for fit names.

## 3. High-level Task Breakdown

1. Current-state audit (grep fit/calibrate) — DONE
2. Read config contract / engine / devices / plants — DONE
3. Candidate params × constraining measurements table — DONE
4. Measurable outputs mapping — DONE
5. Design: module / CLI / CSV format / algorithm (scipy optional extra,
   numpy fallback) / fixed-vs-free / validation — DONE
6. Risks & mitigations (identifiability, bang-bang non-smoothness,
   ODE cost, spin-up, auto-size coupling, weather mismatch) — DONE

## 4. Project Status Dashboard

- [x] Current state summary
- [x] Fitting candidates table
- [x] Measurable outputs table
- [x] Proposed CLI + module + data format
- [x] Algorithm choice with fallback
- [x] Example workflow
- [x] Risks and mitigations
- [ ] (future) implement vfed/calibrate/ if user approves

## 5. Executor Feedback / Help Requests

- Proposed design doc delivered in chat. No code written (task scope).
- Awaiting user decision on: scipy optional extra (`[project.optional-
  dependencies] fit`) vs pure-numpy optimizer.
