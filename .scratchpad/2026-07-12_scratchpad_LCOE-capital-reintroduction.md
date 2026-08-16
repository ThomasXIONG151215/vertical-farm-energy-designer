# Scratchpad: LCOE + Full-System Capital Cost Reintroduction

**日期**: 2026-07-12
**主题**: Full-system capital costs, hourly electricity tariffs, RMB-USD conversion, LCOE as sweep objective
**角色**: 规划者 + 执行者

---

## 背景和动机 (Background & Motivation)

### 项目背景
The sweep framework was refactored to minimize kWh/kg (fresh) with no economic terms. PV area was optimized but always returned 0 — PV adds cost with no kWh/kg benefit since the building load is fixed. The user wants to reintroduce economic optimization: capital costs for ALL components (not just PVBES), hourly electricity pricing, and LCOE as the sweeping objective.

### 核心目标
1. Per-component capital costs with depreciation (LED, HVAC, DEH, PV, battery, equipment, envelope)
2. Hourly electricity price array (replacing 3-tier peak/valley/normal)
3. RMB-USD conversion support
4. LCOE + $/kg + kWh/kg as output metrics; LCOE as sweep objective

### 成功标准
- PV>0 when LCOE-optimal (PV value tied to hourly grid prices)
- CLI shows: LCOE ($/kWh), $/kg fresh, kWh/kg fresh, capital breakdown
- User can define any component cost in YAML (direct $ or per-watt $/W)
- Exchange rate field converts between RMB and USD display

---

## 关键挑战和分析 (Key Challenges & Analysis)

### 技术挑战
1. **PVBES capital resolution**: PVAreaConfig.C_pv must work with new CapitalCostConfig (mode=per_watt → use C_pv as rate_per_watt)
2. **DEH capital**: DEH cost is not per-watt (small compressor). Direct mode only.
3. **Grid cost computation**: Tariff.price_array() must return hourly prices matching the simulation hourly array (8760 entries)
4. **LCOE denominator**: Use annual_load_kwh (2nd formula) — clear, interpretable.

### 资源约束
- Only modify existing files (project.py, grid.py, sweep.py, cli.py, evaluator.py, presets.py)
- Back-compat: existing YAML without capital sections should default to zero cost
- No new dependencies

---

## 高层任务拆分 (High-level Task Breakdown)

### Phase 1: Core dataclasses ✅
- [x] 1.1 project.py: `CapitalCostConfig` dataclass (mode + cost + rate_per_watt + depreciation_years) ✅
- [x] 1.2 project.py: Attach `capital` to LEDConfig, HVACConfig, DEHConfig ✅
- [x] 1.3 project.py: PVConfig + BatteryConfig: add `capital` field ✅
- [x] 1.4 project.py: DesignProject: add `equipment_capital`, `envelope_capital`, `interest_rate`, `currency`, `exchange_rate` ✅
- [x] 1.5 project.py: Rewrite `TariffConfig` (hourly_prices + export_price + currency; remove peak/valley/normal) ✅

### Phase 2: Business logic ✅
- [x] 2.1 sweep.py: `_resolve_capital()` — resolves per-component cost ✅
- [x] 2.2 sweep.py: `_total_annualized_capital()` — CRF-weighted sum ✅
- [x] 2.3 sweep.py: Switch best → min(lcoe); add $/kg column ✅
- [x] 2.4 grid.py: Simplify Tariff class for hourly array lookup ✅
- [x] 2.5 energy_system.py: Update to use simplified Tariff ✅

### Phase 3: CLI + presets + test ✅
- [x] 3.1 cli.py: LCOE-first output; show $/kg, currency, capital breakdown ✅
- [x] 3.2 presets.py: Update preset_609 with capital defaults (all zero) ✅
- [x] 3.3 evaluator.py: Pass through LCOE + $/kg fields ✅
- [x] 3.4 Compile + sweep test (PV>0 should emerge) ✅

---

## 项目状态看板 (Project Status Dashboard)

### 当前阶段: Phase 3 - CLI + presets + evaluator + test ✅ Complete

#### 已完成 (COMPLETED)
- [x] 1.1 CapitalCostConfig ✅ 2026-07-12
- [x] 1.2 Attach capital to LED/HVAC/DEH ✅ 2026-07-12
- [x] 1.3 Attach capital to PV/Battery ✅ 2026-07-12
- [x] 1.4 DesignProject fields ✅ 2026-07-12
- [x] 1.5 TariffConfig rewrite ✅ 2026-07-12
- [x] 2.1 _resolve_capital() ✅ 2026-07-12
- [x] 2.2 _total_annualized_capital() ✅ 2026-07-12
- [x] 2.3 Switch best → LCOE ✅ 2026-07-12
- [x] 2.4 grid.py Tariff simplify ✅ 2026-07-12
- [x] 2.5 energy_system.py (no changes needed) ✅ 2026-07-12
- [x] 3.1 cli.py LCOE output ✅ 2026-07-12
- [x] 3.2 presets.py (unchanged) ✅ 2026-07-12
- [x] 3.3 evaluator.py pass-through ✅ 2026-07-12
- [x] 3.4 Compile + sweep test (225 configs) ✅ 2026-07-12

#### 进行中 (IN PROGRESS)
（空 — 全部完成）

#### 待处理 (TODO)
（空 — 全部完成）

---

## 执行者反馈或请求帮助 (Executor Feedback / Help Requests)

### 执行者反馈 (2026-07-12)

✅ **已完成**:
- Phase 1: project.py — CapitalCostConfig dataclass, TariffConfig hourly_prices rewrite, capital fields on all 7 components, DesignProject fields (interest_rate, currency, exchange_rate)
- Phase 2: sweep.py full rewrite — _resolve_capital, _total_capital, _annualized_capital (per-component CRF), _compute_lcoe, _compute_cost_per_kg_fresh; objective switched to min(LCOE)
- Phase 2b: grid.py Tariff simplified to hourly_prices[24] array + export_price (removed peak/valley/normal)
- Phase 2c: energy_system.py — no changes needed (Tariff interface unchanged)
- Phase 3: cli.py LCOE-first output ($/kWh, $/kg, kWh/kg, capital breakdown); evaluator.py passes currency/exchange_rate; presets.py unchanged
- All modules compile; end-to-end sweep tested with 225 configs (ppfd × photoperiod × PV × battery)
- PV=200 m², battery=40 kWh selected (net exporter with negative grid cost) — PV-LCOE tie verified

📊 **关键数据**:
- Files changed: project.py (+50 lines), grid.py (rewritten), sweep.py (rewritten, +120 lines), cli.py (rewritten), evaluator.py (+2 lines)
- Sample YAML: example_lcoe_full.yaml with full capital + Shanghai TOU pricing
- LCOE = 0.0893 RMB/kWh (with PV=200 m², bat=40 kWh, ppfd=200)
- Architecture: per-component depreciation via CRF, legacy C_pv/c_energy fallback for back-compat, hourly price array for granular TOU

⏭️ **下一步**:
- User can now define their own capital costs in YAML and sweep for min LCOE
- Consider adding grid export cap (utility policies limit export)
- Consider multi-objective Pareto (LCOE vs $/kg vs kWh/kg)

---
