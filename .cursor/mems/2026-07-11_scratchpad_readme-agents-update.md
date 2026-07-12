# Scratchpad: Update README.md and AGENTS.md Files Across VFED

## 1. Background and Motivation

The vertical-farm-energy-designer (VFED) project has **inconsistent and outdated documentation** across its file tree:

- **Root `README.md`** (48 lines): Basic overview, missing badges, quick start, contributing, license sections that best practices require.
- **`research/xiong-pvbes-photoperiod-2026/README.md`** (233 lines): Comprehensive and well-structured — serves as the reference model for what a good README looks like (badges, install, quick start, CLI table, architecture, usage examples, research results, extending, citation).
- **`research/xiong-pvbes-photoperiod-2026/AGENTS.md`** (187 lines): **Severely outdated** — references legacy EnergyPlus architecture (`idf_builder.py`, `eso_to_csv.py`, IDF generation, EnergyPlus CLI commands) that no longer exists in the current ODE-based codebase.
- **No root `AGENTS.md`** exists — needed to guide AI agents working on the current architecture.
- **No `src/` subfolder READMEs** — the 7 source directories (`agent`, `design`, `devices`, `physics`, `plants`, `pvbes`, `weather`) have no module-level documentation.

**Goal**: Bring all README.md and AGENTS.md files up to date, aligned with the current ODE/PVBES architecture and following best practices.

---

## 2. Key Challenges and Analysis

### Challenge 1: Legacy Architecture References
The existing AGENTS.md (research subfolder) is a **complete mismatch** with the current codebase:
- References `idf_builder.py` — no longer exists; replaced by ODE physics solver
- References `eso_to_csv.py` — EnergyPlus output parser, not relevant
- References EnergyPlus IDF commands — the project no longer uses EnergyPlus for load generation
- The CLI commands listed are for the old `vfed idf build/run/extract-loads` interface, not the current `vfed design new/optimize/evaluate/sweep`

### Challenge 2: Source Module READMEs
Seven `src/` subfolders have no README. Need to decide:
- Should each get a minimal README (purpose, key files, conventions)?
- Or should this be handled via a single architecture section in the root README?
- **Decision**: Create minimal module READMEs (3-5 lines each) with purpose + key classes/files. Root README already has the layout tree.

### Challenge 3: Root README Enhancement
Current root README is functional but bare. Needs:
- Badges (Python version, license, build status)
- Installation section (pip install -e .)
- Quick start section (already has CLI but no install instructions)
- Contributing / License / Citation sections (research README has these — can adapt)

### Challenge 4: Keeping Files in Sync
Changes span multiple files across the project. Risk of:
- Inconsistent terminology between root and research READMEs
- Duplicated information that drifts over time
- **Mitigation**: Root README = project-level overview. Research README = archived reference. AGENTS.md = agent instructions only (commands, constraints, conventions — not documentation).

---

## 3. High-level Task Breakdown

| # | Task | File(s) | Estimate | Dependencies |
|---|------|---------|----------|--------------|
| T1 | Rewrite root `README.md` with best-practice sections | `README.md` (root) | Medium | T5 (need final layout) |
| T2 | Create root `AGENTS.md` — agent-focused, ~100 lines | `AGENTS.md` (root) | Medium | T5 |
| T3 | Update/replace `research/.../AGENTS.md` with current architecture | `research/.../AGENTS.md` | Medium | — |
| T4 | Add module READMEs for `src/` subfolders | 7 files in `src/*/README.md` | Low | T5 (need module inventory) |
| T5 | Audit current `src/` structure to confirm module boundaries | — | Low | — |
| T6 | Cross-validate: ensure root README, AGENTS.md, and module READMEs are consistent | — | Low | T1-T4 |

**Execution order**: T5 → T1, T2, T3, T4 (parallel after audit) → T6

---

## 4. Project Status Dashboard

| Task | Status | Notes |
|------|--------|-------|
| T1: Root README rewrite | 🔲 Pending | Need badges, install, quick start, contributing, license |
| T2: Root AGENTS.md | 🔲 Pending | Agent-focused: commands, conventions, constraints, file paths |
| T3: Research AGENTS.md update | 🔲 Pending | Remove all EnergyPlus references, align with ODE/PVBES architecture |
| T4: src/ module READMEs | 🔲 Pending | 7 subdirs: agent, design, devices, physics, plants, pvbes, weather |
| T5: Audit src/ structure | 🔲 Pending | Confirm current module layout and key files |
| T6: Cross-validate consistency | 🔲 Pending | Final pass after all writes complete |

**Overall**: 🔲 Not started — 0/6 tasks complete

---

## 5. Executor Feedback or Help Requests

- **Question for user**: Should the research subfolder README (`research/.../README.md`) also be updated, or is it intentionally archived as the legacy reference?
- **Question for user**: Should root `AGENTS.md` follow the same ~100-line target as the maestro-iems AGENTS.md pattern, or should it be more detailed given the scientific domain?
- **Question for user**: Any specific badges desired for root README (e.g., PyPI version, CI status, Codecov)?
