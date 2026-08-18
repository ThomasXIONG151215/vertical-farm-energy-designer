# Scratchpad — 蒸腾模型收敛重构（5 方法集）

- 日期：2026-08-18
- 关联任务：REVIEW round 3 修复（P3 蒸腾/ P4 湿度）→ 用户要求「集中蒸腾模型」
- 基线 HEAD：`5c8e7e9`（197 tests 时代）

## 1. Background and Motivation

第三轮审查后蒸腾有 6 种方法（van_henten / vpd / stomatal / constant / daily / per_plant），
其中 vpd / stomatal / constant 物理建模重叠且参数冗余（k_vpd、g_stomata、r_a、r_n_canopy、E_max_kgs）。
用户要求收敛：保留 van_henten（生长耦合）+ 直接设定 4 种，删除模型法冗余，规划参数不冲突与仿真计算链条。

**用户决策（2026-08-18 确认）**：
1. 默认 method = **van_henten**（609 预设自动迁移）
2. period 默认需水量：`daily_water_L_period=[30,45,60]` L/day、`ml_per_plant_day_period=[10,30,50]` mL/株、`period_days=[10,10,10]`
3. `sum(period_days) == crop_cycle_days` **强校验 fail-fast**
4. 旧引用（3 YAML + web UI + 测试）**全部迁移到新默认**，不留兼容别名

## 2. Key Challenges and Analysis

- **参数不冲突**：每参数只服务一个方法族；公共乘子仅 stage_factor / plant_count
- **阶段-收获对齐**：period 方法需 cycle_day 时钟；engine 维护 cycle_h，harvest 时与 X_d 同点清零；sum(period_days)==crop_cycle_days 强校验防静默错位
- **DEH 定容口径**：非 van_henten 纯代数方法新增 `design_rate_kgs()` 取**峰值阶段**（延续 P3-4 峰值逻辑）；van_henten 保留 30 天 pre-run 峰值
- **fail-fast 迁移**：删除的 3 方法（vpd/stomatal→van_henten、constant→daily）报 ValueError 带迁移提示；unknown method 从静默返回 0.0 改 fail-fast

## 3. High-level Task Breakdown

- S1 ✅ transpiration.py 重构（5 方法集 + _stage_index + design_rate_kgs + step 加 cycle_day）
- S2 ✅ project.py TranspirationConfig 契约 + 校验（白名单/legacy hint/period 强校验/plant_count）
- S3 ✅ engine.py 定容链（design_rate_kgs）+ 运行时 cycle_h 累积 + harvest 同点清零
- S4 ✅ 3 示例 YAML + vfed-web UI + AGENTS.md + README/README_zh/vfed-models-plan/plants README（9 文档处）
- S5 ✅ 测试重写（test_transpiration 29 / test_03+test_05 47 / 全量 227 passed）
- S6 ✅ 609 上海 2023 复测对比（见 Dashboard）
- S7 🔲 scratchpad 同步 + git 提交

## 4. Project Status Dashboard

| 批次 | 状态 | 验证 |
|---|---|---|
| S1 transpiration.py | ✅ | 10 用例脚本（阶段/边界/design_rate/legacy/fail-fast） |
| S2 project.py | ✅ | 10 用例校验脚本 |
| S3 engine.py | ✅ | smoke 定容对比（van_henten 5769W ≈ 基线 5.77kW） |
| S4 文档/YAML/web | ✅ | grep 零残留（活跃代码） |
| S5 测试 | ✅ | 227 passed（原 210 + 17 新增） |
| S6 609 复测 | ✅ | 见下表 |
| S7 提交 | 🔲 | — |

**609/上海 2023 复测（vpd 基线 → van_henten 默认）**：

| 指标 | 基线 vpd | van_henten | 判定 |
|---|---|---|---|
| RH<50% | 1619h | 1688h | 略升 +4.3% |
| RH<30% | 514h | 478h | ✓ 改善 |
| RH<10% | 11h | 14h | 略升 |
| min RH | 7.63 | 7.48 | ≈ 达标 |
| 年负荷 | 67,128 kWh | 63,377 kWh | ✓ -5.6% |
| w/f | 5.8 | 3.79 | ✓ 带内 [3,12] |
| 年水耗 | — | 54.1 L/day | — |
| harvest_fw | — | 5213 kg/yr | ✓ >1000 |

**609 定容（smoke）**：van_henten P_ref=5769W（回归无损）；daily 2808 / per_plant 4308 / daily_per_period 3558 / per_plant_per_period 3183 W。

## 5. Executor Feedback or Help Requests

- **待用户知悉**：年水耗 54.1 L/day 显著低于设计点 117 L/day（van_henten 蒸腾 ∝ X_d，周期早期低）；这是模型语义，不是 bug
- 批次1-7（src→vfed 重命名、P1-P7 修复）+ 本次 S1-S6 全部改动仍**未提交**，准备一次性提交
- 暗期透蒸 0.15× 系数（上轮遗留决策项）仍未实现，等用户拍板
