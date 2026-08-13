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
- [ ] 输出最终整合报告

## 4. Project Status Dashboard

- 调研完成度：100%（5 路并行调研 + 数值核算 + 最终报告已完结）
- 负湿度根因：已确认（设备级无钳位 + ODE 只钳结果）
- 修复状态：P0/P1 修复已全部完成并通过全量测试
- 待办：输出最终报告给用户（已完成）

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

## 5. Executor Feedback

无阻塞。所有调研在 src/ 活跃代码完成，未修改任何代码。
- P0/P1 修复阶段完成：6 项任务全部落盘并通过全量测试（163 passed，覆盖率 75%）。修复尚未 git commit，待用户确认后提交。

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
