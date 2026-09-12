# P1-3a 输出管道 additive 修复 — scratchpad

## 1. Background and Motivation
VFED user-gym 修复路线图（账本 `.scratchpad/2026-09-08_scratchpad_fix-verify-loop.md`）的下一排队项 P1-3，经用户确认拆为两步执行：
- **P1-3a（本任务）**：零物理漂移的 additive 输出管道修复——monthly.csv 补列、summary 补标量、年末在田收割单列、summary CSV dict 列消毒、README 列字典。
- **P1-3b（后续）**：时间轴与窗口对齐（city 摄取守卫 + 50 城市数据文件再生 + ISO8601 timestamp 列 + price 列），会整体迁移权威物理基线（62,452.72 → 62,446.74 kWh/yr，−0.01%），独立步骤处理。

规格权威来源：
- `user-gym/user11/report.md`（D-1..D-9 发现 + Top3 修复建议）
- `user-gym/audit/recheck_user11.md`（独立审计：8 CONFIRMED / 1 CORRECTED，§3 给出 4 处规格缺口修正）

## 2. Key Challenges and Analysis
1. **兼容地雷**：vfed-web/worker.js 引用 `harvest_kg/hour_of_year/X_d`；tests/test_result.py 钉住 `energy_kwh__total` 表头 → 全部改动必须 additive（加列不改名不删列）。
2. **harvest 归属普适行为**：engine.py:810-813 把年末在田生物量并入最后一行标签月（旋转窗下落 1 月虚高 15%，对齐窗下落 12 月虚高）→ 单列 `harvest_final_standing_kg`，不并入任何月份。
3. **电费口径一致性**：monthly `electricity_cost` 必须与 P0-2 修复的计价口径一致（grid_import × tariff，禁用计价分支见 engine.py:1137-1153 附近）。
4. **dict 列消毒根因**：save_summary_csv（result.py:158-165）直接写 self.summary，绕过 to_dict() 的 _ensure_json_safe（result.py:18-36）→ np.float64(...) repr 混入 CSV。
5. **零漂移约束**：年度基线 62,452.72 kWh / 31.177 kWh/kg fw / 6,245.27 USD grid cost / LCOE 0.6608（609@Shanghai2025）与 example_sweep 经济基线（best LCOE 0.7697603292315144 / capital 23,255.814 / dry 77.57 kg）必须逐位不变。

## 3. High-level Task Breakdown
- [x] T1: monthly 补列（D-4）：grid_import_kwh、electricity_cost、water_m3、harvest_fw_kg；PV/battery 启用时追加 pv_generation_kwh/grid_export_kwh/battery_net_kwh
- [x] T2: summary 补标量（D-7 + 审计查漏#2）：annual_led_kwh、annual_hvac_kwh、energy_breakdown 占比列（hvac_pct/deh_pct/led_pct/misc_pct 扁平化）
- [x] T3: harvest 归属修正（D-3）：harvest_final_standing_kg 单列（summary 级标量；monthly 不加对应列，保持 12 行纯列表）
- [x] T4: dict 列消毒（D-5 根因）：save_summary_csv 套 _ensure_json_safe
- [x] T5: README/README_zh 列字典：三个 CSV 每列含义/单位/口径（dry vs fw、electricity_cost 净额口径、无禁用电价模式说明）
- [x] T6: 独立 verify（年度基线零漂移 + 新列正确性 + literal_eval 验收）——本会话自检全绿，待主会话复核
- [ ] T7: commit + 账本 round 8（按约束不 commit，由主会话 verify 后提交）

## 4. Project Status Dashboard
| 任务 | 状态 |
|---|---|
| T1 monthly 补列 | done（engine.py 累加器/月 dict/两条经济分支） |
| T2 summary 标量 | done（engine.py summary 构造） |
| T3 standing 单列 | done（m1=8.296396 / standing=1.4574 实测） |
| T4 dict 消毒 | done（result.py save_summary_csv） |
| T5 README 列字典 | done（README.md + README_zh.md 各 +57 行） |
| T6 独立 verify | done（318 passed；sweep 32 列字符串级逐位一致；timeseries bitwise 不变） |
| T7 commit+账本 | done（commit 1f6f918；账本 round 8 已更新） |

## 5. Executor Feedback or Help Requests
- 验收标准（审计 §3 补充）：①monthly electricity_cost 12 月合计 = 6,245.27 USD（grid-only）；②m1.harvest_kg = 8.2964（事件1 精确值）且 standing 单列 = 1.4574；③harvest_fw_kg 月度合计 = 2003.17 kg；④ast.literal_eval 可解析 summary.csv 全部 dict 列；⑤pytest 全绿（305 基线 + 新增测试）；⑥grid-only 下既有 32 列 sweep CSV bitwise 不变。
- 环境：vfed 不在系统 PATH（用 user-gym/user1/.venv/Scripts/vfed.exe 或 python -m）；pytest 须系统 Python；回归对照须仓库根 --cache weather_cache + --city Shanghai。
- HEAD 起点 = 50f3997（chore: fix-verify ledger round 7）。

### 执行者反馈（2026-09-12，P1-3a 实现完成，未 commit）

**⚠️ 验收口径勘误（重要）**：任务书验收④"harvest_fw_kg 合计 ≈ 2003.17"与 T3/测试要求"monthly 合计=annual−standing"数学上不可同时成立——T3 后月度仅含收割事件，fw 合计 = (100.1585−1.4574)/0.05 = **1974.02 kg**；2003.17 是**年度口径**（含 standing 的 annual_harvest_fw_kg，保持不变零漂移）。实测 fw 合计 1974.0208，已按 T3 权威口径实现并在 README 写明两条口径。

**自检结果**（609@Shanghai2025 实跑，audit_farm.yaml + 仓库根 weather_cache）：
- ①基线逐位：annual 62452.72 / 31.177 / 6245.27 / LCOE 0.6608 / DEH 10235.01 / LED 42048.0 / HVAC 10169.71 / 干重 100.16 全部精确复现；timeseries.csv 与改动前 bitwise 相同（物理零漂移）
- ②electricity_cost 12 月合计 6245.2720 vs 6245.27，diff = 0.0020 < 0.01 ✓
- ③m1.harvest_kg = 8.296396（事件1）✓；standing = 1.4574 ✓（round 4dp）
- ④fw 合计 = 1974.02（=年度 2003.17 − standing/0.05 = 29.15，见勘误）
- ⑤literal_eval 全部通过，0 个 np. repr 单元格
- ⑥sweep 32 列对改动前 HEAD **字符串级逐位一致**（原始 CSV 0 diff；pandas compare 的 23 处"差异"是我临时 to_csv 快照的 ULP 伪影）；old-24 列对 r5_example_sweep_results.csv 0 mismatch；best lcoe 0.7697603292315144 / capital 23255.81395348837 / dry 77.57 不变
- ⑦pytest **318 passed**（305 基线 + 13 新增 tests/test_09_output_columns.py，含上海基线钉、PV 探针闭合、sweep 32 列集钉）
- PV 探针（pv=100/batt=100）：PV 32837.19 / grid 30848.64 / cost 月和 3084.86 = annual_grid_cost_net ✓；battery_net_kwh 月和 −1233.11（放电 5940.29 − 充电 7173.40）

**diff 概要**：`vfed/design/engine.py` +89（_monthly_sum 辅助、monthly_water_kg 累加、standing 单列、summary 7 个新标量、monthly 2 个平铺键 + 两条经济分支各接月度 grid/cost/PV 列）；`vfed/design/result.py` +6-1（save_summary_csv 套 _ensure_json_safe）；`tests/test_09_output_columns.py` 新增 13 测试；README.md / README_zh.md 各 +57（CSV 列字典节）。sweep.py / 物理层 / 设备层 / 植物层零改动；无列改名无删列（worker.js 的 harvest_kg/hour_of_year/X_d 与 test_result.py 的 energy_kwh__total 全部保持）。

**遗留给主会话**：T7 commit（建议 message：feat(P1-3a): additive output pipeline — monthly grid/cost/water/fw columns, summary LED/HVAC/pct/standing scalars, summary CSV json-safe, README column dictionary）+ 账本 round 8。临时工件在 %TEMP%\opencode\p13a\（pre/post/post_pv 三套导出 + 对照脚本）。
