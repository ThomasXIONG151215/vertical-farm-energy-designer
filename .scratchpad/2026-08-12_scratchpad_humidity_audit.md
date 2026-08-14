# 2026-08-12 Scratchpad — 湿度仿真调研 (Humidity Audit)

## 1. Background and Motivation

用户反馈 VFED 湿度仿真容易出错，尤其是出现负数湿度。需要并行调研并核算仿真机理准确性。

## 2. Key Challenges and Analysis

湿度链路核心：
- 状态变量 W_z (绝对湿度 kg/kg)，RH 为导出量
- engine.py:285-286 聚合 M_total = E_trans - M_deh - M_hvac + M_inf + M_perm
- ode.py:55-65 step_humidity 显式 Euler + [0, W_sat] 双钳位

负湿度根因（5路调研+数值核算确认）：
1. 设备级无库存钳位：dehumidifier.py:127 m_dh=SMER·P_comp/3.6e6；hvac.py:158 M_target=Q_lat/h_fg
2. ODE 只钳结果不钳流量：ode.py:65 max(0,·) 静默销毁水分，能量统计仍满额计入
3. 夜间 E_trans=0 时 M_total 强负（数值验证：V=200m³,SHR=0.3 → W_new=-0.00077；V=100,SHR=0.5 → -0.00747）
4. psychrometrics 公共函数无守卫：temp_rh_to_ah 负RH→负AH；Magnus 公式 T=-237.3 除零
5. transpiration 6 方法均无符号 clamp：负 stage_factor/k_vpd 等 → 负蒸腾
6. 饱和钳位静默丢水、气压不一致（101.325 vs P_atm）、stomatal PM 单位错（kPa→Pa 缺 1000x）、van_henten T≈45°C 奇异点

测试缺口：无负湿度/守恒/钳位测试；step_humidity 从未直接单测。

## 3. High-level Task Breakdown

- [x] 并行调研 5 路（psychrometrics/ode、plants、devices/envelope、engine、tests）
- [x] 数值核算负湿度触发条件（已复现：夜间 DEH+HVAC 联合除湿）
- [x] 输出最终整合报告
- [x] A 级问题复查与修复（2026-08-13）：A1 stomatal PM 单位误报澄清、A2 van_henten 高温守卫、A3 气压一致性

## 4. Project Status Dashboard

- 调研完成度：100%（5 路并行调研 + 数值核算 + 最终报告已完结）
- 负湿度根因：已确认（设备级无钳位 + ODE 只钳结果）
- 修复状态：P0/P1 + A 级（A1/A2/A3）+ B 级（B1/B2/B3）修复已全部完成并通过全量测试（172 passed，覆盖率 75%）
- 待办：~~B 级改动 git commit~~ ✅ 已随 e220645 提交；docs 同步已随 bf28941 提交；HEAD 当前 bf28941
- 空调除湿校准（2026-08-14）：✅ 完成（shr.py T_coil_drop 14→9、shr_min 0.30→0.45，见下方记录章节）；C1/C2/C3/C4 收尾全部闭合；172 passed 无回归
- 待办：本次 C 级收尾改动（shr.py / engine.py / dehumidifier.py）尚未 git commit，待用户确认后提交

### 已完成任务（P0/P1 修复）

1. **P0-1 湿度流量钳位 + 能量守恒回退** — 已完成
   - `src/physics/ode.py`：`step_humidity` 新增 `return_meta=True` 返回 `(W_new, {floor_clipped_kg, sat_clipped_kg})`；`air_mass<=0` 抛 `ValueError`；饱和钳位加 `P_atm-p_sat>0` 守卫。
   - `src/design/engine.py`：湿度步后按 `(sat_clipped-floor_clipped)*L_v` 计算 `q_corr` 并二次 `step_temperature` 回补潜热；累计 `clamp_stats`。
2. **P0-2 钳位事件统计** — 已完成
   - `engine.py` summary 新增 `"moisture_clamp_stats"`（`floor_clip_events`/`floor_clip_water_kg`/`sat_clip_events`/`sat_clip_water_kg`，water 取 round 3 位）。
3. **P1-1 psychrometrics 守卫** — 已完成
   - `_MAGNUS_T_MIN/MAX = ±100` + `_check_temp`；`temp_rh_to_ah` 对 RH clamp `[0,100]`；`ah_to_temp_rh` 对负 AH 抛 `ValueError`。
4. **P1-2 配置校验** — 已完成
   - `project.py` `from_dict` 新增 `_require_nonnegative`（transpiration 10 字段 + deh 4 字段），`setpoints.RH` 限 `[0,100]`。
5. **P1-3 回归测试** — 已完成
   - `tests/test_03_numerical.py` 新增 14 个测试：`TestHumidityODEClamps` 5 个、`TestPsychrometricsGuards` 3 个、`TestConfigValidation` 4 个、`test_engine_over_dehumidification_never_negative_rh` 1 个（引擎级合成天气确定性测试）。
6. **全量 pytest** — 已完成
   - 163 passed（原 ~149 + 新增 14），覆盖率 75%，耗时 51s。

- Git 状态：本次修复尚未提交（未做 git commit）

### 已完成任务（A 级修复，2026-08-13）

1. **A1 stomatal PM 单位误报澄清** — 已完成
   - 复查结论：调研早期判断 stomatal Penman-Monteith 气动项 kPa→Pa 缺失 1000 倍是**误报**——Δ/γ/VPD 三者均 kPa 时单位自洽，kPa 与 Pa 表示数值等价（25°C/50%RH 验证均 206.1 W/m²）。
   - 处置：`src/plants/transpiration.py` stomatal 分支加单位防御注释块，**代码不变**；新增数值不变性测试 `test_stomatal_pm_unit_invariance`。
2. **A2 van_henten 高温奇异点** — 已完成
   - 根因：`co2_term` 在 T>42.1°C 为负，`den` 在 ~44.5°C 过零导致 φ 变号/爆炸、X_d 塌缩。
   - 修复：`src/plants/van_henten.py` `_phi_phot_c` 在 `co2_term<=0` 时 `return 0.0`（净光合不可能为负）。
3. **A3 气压一致性** — 已完成
   - `src/physics/psychrometrics.py` `temp_rh_to_ah`/`ah_to_temp_rh` 新增 `pressure_kpa=101.325` 参数。
   - `src/design/engine.py` 三处运行期调用（251 初始化、318 W_ext、366 子步 RH）传 `P_atm`（run() 内 surface_pressure nanmean/10）。
   - 选型处与其它设备调用保持默认气压（101.325），不受影响。
4. **A 级回归测试** — 已完成
   - `tests/test_03_numerical.py` 新增 4 个测试：`test_stomatal_pm_unit_invariance`、van_henten 高温守卫、psychrometrics 气压参数化、引擎级 950hPa 高原运行不崩溃且 RH 非负。
5. **全量 pytest** — 已完成
   - `tests/test_03_numerical.py` 28 passed；全量 **169 passed**（基线 165 + 新 4），覆盖率 75%。

- Git 状态：A 级改动尚未提交（将单独 commit：psychrometrics.py/van_henten.py/transpiration.py/engine.py/test_03_numerical.py）

## 5. Executor Feedback

无阻塞。所有调研在 src/ 活跃代码完成，未修改任何代码。
- P0/P1 修复阶段完成：6 项任务全部落盘并通过全量测试（163 passed，覆盖率 75%）。修复尚未 git commit，待用户确认后提交。
- A 级修复阶段完成（2026-08-13）：A1（误报澄清，代码不变+注释块+不变性测试）、A2（van_henten 高温守卫）、A3（气压一致性）全部落盘，全量 169 passed（基线 165 + 新 4），覆盖率 75%。A 级改动尚未 commit，将单独提交 5 个文件。

---

## 记录：P0/P1 修复完成

- 时间：2026-08-13
- 状态：P0-1（湿度流量钳位+能量守恒回补）、P0-2（clamp 事件统计）、P1-1（psychrometrics 守卫）、P1-2（配置校验）、P1-3（回归测试）全部完成落盘
- 验证：全量 pytest 163 passed（原 ~149 + 新增 14），覆盖率 75%，耗时 51s
- Git：本次修复尚未提交（未做 git commit），待用户确认后提交

---

## 记录：实际除湿量记录与除湿机性能反馈（2026-08-13）

### 用户需求
"重点记录实际除湿量，并以此反馈除湿机性能"。

### 实现（全部落盘）

1. **`src/design/engine.py` 新增模块级函数 `_limit_removal_by_inventory(M_deh_kgs, M_hvac_kgs, W_z, air_mass, dt)`**
   - 把 DEH/HVAC 名义除湿量按当前子步空气水分库存（`W_z*air_mass/dt`）钳位
   - 返回 `(M_deh_actual, M_hvac_actual, scale)`，两设备同比例缩放
2. **主循环湿度装配改造**
   - Q_total 加入能量修正 `q_removal_corr = (1-scale)*(M_hvac_nom - M_deh_nom)*L_v`（DEH 少放冷凝热从平衡扣除、HVAC 少带潜热补回）
   - M_total 改用 actual 值聚合
3. **新增 `deh_perf` 统计字典**：子步累计名义/实际除湿量 kg、`removal_limited_events`、`removal_limited_water_kg`
4. **summary 新增 `dehumidifier_performance` key**：
   - `deh_nominal_dehum_kg` / `deh_actual_dehum_kg` / `hvac_nominal_dehum_kg` / `hvac_actual_dehum_kg`
   - `removal_limited_events` / `removal_limited_water_kg`
   - `deh_utilization`（= actual/nominal，nominal=0 时 =1.0）

### 物理效果
- 设备级钳位后 ODE 的 floor clamp 在过除湿场景不再触发（流量先被截断）
- `moisture_clamp_stats` 保留为渗透等残余负通量的兜底诊断

### 测试（tests/test_03_numerical.py）
- 新增 `test_limit_removal_by_inventory`：单元级（不受限/受限/零库存/零除湿/dt<=0）
- 新增 `test_engine_reports_actual_dehumidification`：引擎级（perf keys 校验、actual≤nominal、utilization∈[0,1]、removal_limited_events>0）
- 更新 `test_engine_over_dehumidification_never_negative_rh`：`floor_clip_events` 断言由 `>0` 改为 `>=0`，改由 perf 的 `removal_limited_events>0` 证明超抽被记账

### 验证
- 全量 pytest：**165 passed**（原 163 + 新 2）

### Git
- 仍未提交（HEAD `1a985cb`），本次改造与 P0/P1 修复同批未 commit，待用户确认后一并提交。

### Dashboard 状态补充
- 除湿量记账/性能反馈功能：✅ 已完成落盘（engine.py + tests）
- 待办：git commit（HEAD 仍为 1a985cb，工作区含本次与历史 P0/P1 改动未提交）

---

## 记录：A 级问题修复完成（2026-08-13）

### A1 — stomatal Penman-Monteith 单位误报澄清（非代码修复）

- **复查结论**：早期调研认为 stomatal PM 气动项缺 kPa→Pa 1000 倍换算，经复核为**误报**。
  - Δ/γ（kPa/°C）与 VPD（kPa）三者同为 kPa 时公式单位自洽；kPa 与 Pa 表示只是数值 1000 倍关系，但比值（Δ/γ、VPD/γ）不变。
  - 数值验证：25°C、50%RH 下用 kPa 与 Pa 两组单位分别代入，结果均为 206.1 W/m²。
- **处置**：`src/plants/transpiration.py` stomatal 分支仅加**单位防御注释块**，代码逻辑不变；新增 `test_stomatal_pm_unit_invariance` 验证两种单位制数值等价。

### A2 — van_henten 高温奇异点修复（代码修复）

- **根因**：`co2_term` 在 T>42.1°C 时为负；`den` 在 ~44.5°C 过零，导致光合同化速率 φ 变号/爆炸，干物质 X_d 塌缩。
- **修复**：`src/plants/van_henten.py` `_phi_phot_c` 在 `co2_term<=0` 时 `return 0.0`（净光合不可能为负），消除变号与过零爆炸。

### A3 — 气压一致性（代码修复）

- **改动**：
  - `src/physics/psychrometrics.py`：`temp_rh_to_ah` / `ah_to_temp_rh` 新增可选参数 `pressure_kpa=101.325`，缺省保持原行为。
  - `src/design/engine.py`：三处运行期调用传 `P_atm`（run() 内由 `surface_pressure` nanmean/10 得到）：
    - 251 行（初始化 W_z）
    - 318 行（W_ext 室外含湿量）
    - 366 行（子步 RH 计算）
  - 选型处与其它设备调用保持默认 101.325 kPa，不受影响。

### 测试（tests/test_03_numerical.py）

- 新增 4 个测试：
  - `test_stomatal_pm_unit_invariance`（A1 单位不变性）
  - van_henten 高温守卫（A2，co2_term<=0 时 φ=0）
  - psychrometrics 气压参数化（A3，不同 pressure_kpa 输出不同且合理）
  - 引擎级 950hPa 高原运行不崩溃且 RH 非负（A3 端到端）

### 验证

- `tests/test_03_numerical.py`：**28 passed**
- 全量 pytest：**169 passed**（基线 165 + 新 4），覆盖率 75%

### Git

- A 级改动**尚未提交**（5 个文件：`src/physics/psychrometrics.py`、`src/plants/van_henten.py`、`src/plants/transpiration.py`、`src/design/engine.py`、`tests/test_03_numerical.py`）。
- 将单独 commit，与 P0/P1 修复及除湿量记账改动分开。

### Dashboard 状态补充
- A1/A2/A3 修复：✅ 全部落盘，169 passed，覆盖率 75%
- 待办：A 级 5 文件 git commit（工作区另有 vfed-web/cli/presets 等无关改动，需分开提交）

---

## 记录：B 级问题修复完成（2026-08-13）

### 范围（用户确认：统一 k_vpd 到 2e-5）

1. **B1 k_vpd 5 倍差** — 已完成
   - 三个示例 YAML（test_project.yaml / example_lcoe_full.yaml / example_sweep.yaml）的 `transpiration.k_vpd` 从 0.0001（1e-4）改为 0.00002（2e-5），与代码默认对齐。
   - 代码默认 2e-5 有文献依据（提交 1a985cb "lowered to 2e-5 per literature"）；1e-4 时蒸腾 ~389 L/day 偏高、默认 DEH 欠配。
2. **B2 auto_size 选型方法错配** — 已完成
   - `engine.py` `_build_devices` 中 TranspirationModel 构造提前到 auto_size 之前；
   - auto_size 分支从"constant/daily/per_plant 分派 + else 用 k_vpd"重构为统一委托 `transp.step(T_sp, RH_sp, True, 3600.0, X_d=0.05)`（X_d=0.05 中期冠层干重，van_henten 用）；
   - 选型与运行共用同一方法同一公式；顺带修正 constant 分支漏乘 stage_factor 的问题；compute_vpd 在 auto_size 不再使用（import 保留）。
3. **B3 r_n_canopy 固定不随光强** — 已完成
   - `transpiration.py` `step()` 签名加 `light_wm2: Optional[float] = None`；
   - stomatal 分支 `R_n = light_wm2 if (light_wm2 is not None and light_wm2 > 0.0) else r_n_canopy*light_factor`；
   - `engine.py` 主循环把 `light_wm2 = ppfd_target/par_factor`（实际 LED PAR，默认 87.5 W/m²）计算提前并在 transp.step 调用处传入。默认不传 light_wm2 → 行为不变（向后兼容）。

### 测试（tests/test_03_numerical.py 追加 3 个）

- `test_sample_yaml_k_vpd_matches_code_default`：3 个 YAML 的 k_vpd == 2e-5。
- `test_auto_size_delegates_to_transpiration_model`：6 种蒸腾方法（vpd/stomatal/van_henten/constant/daily/per_plant+plant_count=100）auto_size=True 时 `_build_devices` 返回的 deh.P_ref > 0。
- `test_stomatal_transpiration_follows_light`：light_wm2=87.5 时蒸腾 < legacy(r_n_canopy=250)；light_wm2=200 > 87.5；暗期传 light_wm2 仍为 0。

### 验证

- `tests/test_03_numerical.py`：**31 passed**（原 28 + B 级 3）。
- 全量 pytest：**172 passed in ~62s**（原 169 + 3），覆盖率 75%，无回归。

### Git

- B 级改动**尚未提交**（本次同步后由主代理提交，commit message 拟 "fix(humidity): B-level — sample-YAML k_vpd parity, auto-size transpiration delegation, stomatal LED-PAR response"）。HEAD 当前 a72aa9f。

### Dashboard 状态补充
- B1/B2/B3 修复：✅ 全部落盘，172 passed（test_03 31 passed），覆盖率 75%
- 待办：B 级改动 git commit（A 级已随 a72aa9f 提交）

---

## 记录：C 级收尾与空调除湿校准（2026-08-14）

### 背景

用户反馈"空调除湿太厉害，真实没这么会除湿"。核算确认：12kW 制冷量空调在 24°C/65%RH 工况下，旧模型 SHR=0.53、除湿 8.1 kg/h；真实空调 5-7 kg/h（SHR 0.6-0.7）。根源是 `calc_shr_fallback` 硬编码 T_coil_drop=14（送风=设定点−14=8°C，盘管表面 5.2°C，凝结过强）。

### 用户决策与修改（src/physics/shr.py）

- **T_coil_drop=14 → 9**（送风 13°C，SHR≈0.61、M≈6.8 kg/h，与真实空调 5-7 kg/h 对齐）；加注释：真实送风温差 8-12°C，9 为中值。
- **shr_min 0.30 → 0.45**（潜热占比上限 70%→55%）；加注释：真实空调潜热占比极限 ~55%。
- `T_adp>=T_dp` 处加"湿度自限"注释（SHR=1.0 停止除湿，非设定点控制 —— C2 关闭依据）。
- 验证：全量 pytest **172 passed**，无回归。

### C1 收尾 — 凝结水核算（src/design/engine.py）

- `total_water_kg` 累加处加注释：凝结水直接排放不回收，蒸腾量即供水量，`annual_water_m3` 不扣 sat_clip（用户决策"凝结水直接排掉"）。

### C3 收尾 — 除湿机残流（src/devices/dehumidifier.py）

- lag 残流处加注释：停机后残流 = 盘管挂水惯性（M_act>0、Q_act>0、P_elec=0 均物理自洽）。

### C4 检查 — README 表述

- 根 README.md:33 与 src/plants/README.md 均已为 **6 种方法**，无残留"4 种"表述，**无需修改**。

### C2 结论 — HVAC 无 RH 设定点

- SHR（BF-ADP 盘管模型）已内置露点自限湿度反馈（T_adp>=T_dp → SHR=1.0），干涸平衡点 ~30%RH 而非 0%。
- "HVAC 无 RH 设定点"不是 bug——真实空调确实不管湿度。**C2 关闭，不引入 RH 设定点控制。**

### Git 状态

- 本次 C 级收尾改动**尚未提交**（工作区含 shr.py / engine.py / dehumidifier.py 的注释与参数改动；另有 vfed-web、cli、presets 等无关改动需分开提交）。
- 相关已提交记录：e220645（B 级）、bf28941（docs 同步），HEAD 当前 bf28941。
