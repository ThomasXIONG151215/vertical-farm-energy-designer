# 2026-08-16 Scratchpad — 第二轮全仓库审查（发现记录 + 细致调研）

## 1. Background and Motivation

用户指令（原文）："review整个repo物理和能源和植物仿真潜在问题；兵分四路" → 四路并行审查完成（物理核心 / 设备层 / 植物层 / 能源调度，各 agent 独立数值复算 + engine.py 接口守恒交叉验证）。
随后指令："先把major和minor问题都在新的scratchpad下记录下来，然后再面向major和三路共性的minor7号问题做更细致调研了解情况"。

状态：**发现记录 + 细致调研完成（本文件）；四组修复全部完成并验证**。修复顺序 A→B→D→C（用户已确认）：组 A（能源）/ B（设备）/ D（MINOR-7）/ C（MAJOR-5/6 + k_vpd 联动）全部完成并验证（全量 pytest 197 passed）。

## 2. Key Challenges and Analysis

四路审查结论：**无 CRITICAL**。6 个 MAJOR（能源 2 / 设备 2 / 植物 2）+ 14 个 MINOR（含三路共性 #7 h_fg/L_v 失配）+ 一批 INFO。
核心难点与聚类：
- **PV 温度系数单位混乱**（MAJOR-1/2 能源）：示例 YAML `alpha_sc` 为代码默认 100×（年发电量 1.68× 高估）；`beta_voc` 绝对 V/K vs 铭牌相对 %/K（低估 ~3.4%）。两者方向相反互相掩盖。
- **Fail Fast 缺口**（MAJOR-3 设备 COP 负值、MINOR-8 负含湿量、MINOR-9 BF 除零、INFO engine PVBES 软失败）：配置/边界错误被静默接受或运行深处崩溃。
- **设计定容点 vs 运行时量级失配**（MAJOR-5/6 植物、MAJOR-4 设备）：DEH 定容 X_d=0.05 vs 运行时 0.46（10× 欠配）；生长模型 400 W/m² vs 引擎 87.5 W/m² 光输入；size_hvac 漏 DEH 净热 ~21%。
- **三路共性**（MINOR-7）：设备硬编码 h_fg=2.5e6 vs 引擎温度相关 L_v=2501−2.36T，DEH 凝结热差 ~2%（年 ~241 kWh）。

## 3. High-level Task Breakdown

| # | 任务 | 状态 | 依赖 |
|---|------|------|------|
| 0 | 四路并行审查（物理/设备/植物/能源） | done | — |
| 1 | 新建 scratchpad 记录全部 major+minor | done | — |
| 2 | 细致调研 MAJOR-1/2（能源：alpha_sc/beta_vc） | done | — |
| 3 | 细致调研 MAJOR-3/4（设备：COP 负值防护/size_hvac） | done | — |
| 4 | 细致调研 MAJOR-5/6（植物：DEH 定容点/光输入校准基） | done | — |
| 5 | 细致调研 MINOR-7（跨路：h_fg/L_v 统一） | done | — |
| 6 | 调研汇总 → 向用户报告 → 确认修复顺序 A→B→D→C | done | 2–5 |
| 7 | 组 A 修复：MAJOR-1/2 + MINOR-20 + YAML parity + PV 量纲护栏 | done | 6 |
| 8 | 组 B 修复：MAJOR-3/4 + auto_size 写回 CAPEX | done | 6 |
| 9 | 组 D 修复：MINOR-7 方案 A（h_fg/L_v 温度相关统一） | done | 6 |
| 10 | 组 C 修复：MAJOR-5 DEH 定容 + MAJOR-6 校准基声明 + k_vpd 联动 | done | 6 |

并行组标记：`[2 | 3 | 4 | 5]` 相互独立，四路并行；修复阶段 `[7 | 8 | 9]` 相互独立，顺序 A→B→D 先做，C 最后（依赖 MAJOR-5/6 联动约束）。

## 4. Project Status Dashboard — 第二轮审查发现（修复进度：组 A/B/C/D 全部 ✅ done）

### 修复进度总览（2026-08-16 会话，顺序 A→B→D→C 用户已确认）

| 组 | 覆盖问题 | 状态 | 关键改动 | 验证 |
|---|---------|------|---------|------|
| A 能源 | MAJOR-1/2、MINOR-20、YAML parity | ✅ done | 3 YAML 同步 + pv.py 相对式 β + PVConfig 量纲护栏 + year 传递 + engine 补 C_pv/degradation | 年 PV 58,647→36,076 kWh（−38.5%）；新增 4 测试 |
| B 设备 | MAJOR-3/4、sweep 资本口径 | ✅ done | 配置护栏扩展 + cop_mode 白名单 + 运行时 max(0.5,…) 钳制 + DEH sizing 提前 + auto_size 写回 | 609 双 auto_size：hvac 3000→6633.1W、deh 2233→3106.6W；新增 14 测试 |
| C 植物 | MAJOR-5/6、k_vpd 联动 | ✅ done | C-1 轻量生长预跑定容；C-2 校准基声明 + 水账回归测试；C-3 k_vpd 2e-5→5e-5 | van_henten auto-size DEH 2233→**9303W**；w/f 3.4→**5.8 L/kg**；新增 2 水账测试；全量 **197 passed** |
| D 跨路 | MINOR-7（方案 A） | ✅ done | shr/hvac/dehumidifier/transpiration 计算路径全改 latent_heat_vaporization(T)；h_fg 字段保留 | 引擎焓平衡闭合差精确归零；全量 195 passed |

### MAJOR（6 个）

| # | 领域 | 位置 | 问题 | 影响 | 修复状态 |
|---|------|------|------|------|------|
| 1 | 能源 | `example_lcoe_full.yaml:103`/`example_sweep.yaml:88`/`test_project.yaml:103` | 示例 YAML `alpha_sc: 0.045` 为代码默认 `0.00045` 的 100×；I_mp=13.33/V_mp=46.0 未同步铭牌 12.66/45.85 | 年 PV 发电量高估 **1.68×**（奉贤 2023 实算 34,851→58,647 kWh） | ✅ 组 A：3 YAML 同步 + 量纲护栏 |
| 2 | 能源 | `pv.py:34,52` / `project.py:229` | `beta_voc=-0.25` 按绝对 V/K 使用；铭牌 βVoc 相对 −0.250%/K（57.34V 模组 ≈−0.143 V/K，代码强 1.75×） | 高温衰减过度，年发电量低估 ~3.4% | ✅ 组 A：相对式乘法 + YAML 同步 |
| 3 | 设备 | `hvac.py:54-70` + `project.py:400-404` | constant/table COP 模式无下限钳制，负 COP 静默制冷变制热 | 违反 Fail Fast；T_z 爬升 60°C 饱和、M_target<0 "注水" | ✅ 组 B：配置护栏 + 运行时钳制 |
| 4 | 设备 | `hvac.py:214-228` `size_hvac` | 设计感热负荷遗漏 DEH 净热排（≈P_comp+fan≈2.3kW） | auto-size 低估 ~21%（609 设计负荷 ~10.7kW） | ✅ 组 B：deh_net_heat_w + sizing 重排 + 写回 |
| 5 | 植物 | `engine.py:153` + `transpiration.py:73-76` | `van_henten` 蒸腾法 DEH 定容点 X_d=0.05（3.0 kg/h）vs 运行时峰值 0.46（27.6 kg/h） | 晚周期蒸腾 ~10× 定容点，DEH 严重欠配（RH 自锁 83-87%，非 100% 平台，见 §6） | ✅ 组 C-1：轻量生长预跑定容（van_henten auto-size DEH 2233→9303W） |
| 6 | 植物 | `engine.py:308-311` vs `van_henten.py:110` | 生长模型光输入：参考/测试/demo 400 W/m² vs 引擎 87.5 W/m²（LED PAR）；c_rad_phot=1e-8 校准基无记录 | 生长/蒸腾未互校准：water/鲜重 3.5 L/kg vs 真实 ~20 L/kg，KPI 失真 | ✅ 组 C-2：校准基声明 + 水账闭合回归测试 + k_van_henten 单位注释修正 |

### MINOR（14 个）

| # | 领域 | 位置 | 问题 | 修复状态 |
|---|------|------|------|------|
| 7 | 三路共性 | `shr.py:32,60`/`hvac.py:90,163`/`dehumidifier.py:75,132` vs `engine.py:328` | 设备硬编码 `h_fg=2.5e6` vs 引擎温度相关 `L_v=2501−2.36T`（22°C≈2.449e6），DEH 凝结热差 ~2%（年 ~241 kWh） | ✅ 组 D：方案 A 全改 latent_heat_vaporization(T) |
| 8 | 物理 | `psychrometrics.py:55-63` | `temp_rh_to_ah` 在 p_vapor≥P_atm 时静默返回负含湿量（100°C/100%RH → −71.6 kg/kg） | ⬜ 未动 |
| 9 | 物理 | `shr.py:45` + `project.py:115` | `shr_BF=1.0` 时 `(1−BF)` 除零；无配置校验 | ✅ 组 B：shr_BF∈[0,1) 配置护栏 |
| 10 | 设备 | `hvac.py:49-53` | 冬季 T_cond−T_evap<0 时 Carnot COP 顶到 17.5，3kW 机组 Q_total~50kW | ⬜ 未动 |
| 11 | 设备 | `dehumidifier.py:140-146` | 停机后残留凝结热方向存疑（应再蒸发吸热而非继续放热） | ⬜ 未动 |
| 12 | 植物 | `transpiration.py:89-90` | stomatal R_n 用 PAR-only 低估净冠层辐射 11-26%；定容回退 250 W/m² 与运行时不一致 | ⬜ 未动 |
| 13 | 植物 | `transpiration.py:83` | γ=0.0655 kPa/K 硬编码（101.325kPa 真值≈0.0667，低 ~2%），忽略站压 | ⬜ 未动 |
| 14 | 植物 | `van_henten.py:45` | CO₂ 摩尔体积固定 24.45 L/mol(25°C)，未按室温修正（~1.2% 偏高） | ⬜ 未动 |
| 15 | 植物 | `project.py:203` | `k_van_henten` 单位注释错：`m²/(s·kPa)` 应为 `1/(s·kPa)` | ✅ 组 C-2：注释修正为 `1/(s·kPa)` |
| 16 | 植物 | `transpiration.py:59` | 暗期蒸腾=0（光因子二值化），609 运行 105 次 RH 钳 0%；真实夜间 ~5-15% | ⬜ 未动 |
| 17 | 能源 | `sweep.py:345-352` | 无 PVBES 扫描分支忽略已配置 pv_area/battery 且 net_grid=0，LCOE 不含购电成本 | ⬜ 未动 |
| 18 | 能源 | `project.py:290` + `sweep.py:101-140` | `pump_capital` 配置从未计入资本/LCOE，静默忽略 | ⬜ 未动 |
| 19 | 能源 | `energy_system.py:30,73` vs `sweep.py:306-309` | 运维成本两套口径（0.01 vs 0.02+水+人工）；`pv.maintenance`/`battery.maintenance` 从未生效 | ⬜ 未动 |
| 20 | 能源 | `pv.py:80`/`sweep.py:143-148` | LCOE 用首年电量，`degradation=0.004` 配置了但 year 从不传入 | ✅ 组 A：sweep/engine 传 year=es.lifetime//2，degradation 生效 |

### INFO 摘要（记录不展开）

engine PVBES 软失败（677-679）、PV 无自遮挡/BOS 损耗（pv.py:77）、电池 soc0 固定/年末不收敛/无 TOU 套利（battery.py:38,45）、grid <24 项静默回退 0.10（grid.py:26）、PumpDevice 未接线（pump.py:44-51）、Erbs 近地平线 DNI 非物理放大（weather_bridge.py:94-110）、Magnus 守卫超有效范围/无冰面分支（psychrometrics.py:32-38）、方位角注释误导（weather_bridge.py:77）、收获负生长仍上重置（engine.py:421-427）、transpiration.photoperiod_hours 死字段（engine.py:127）。

### 核查通过清单（四路独立复算确认无问题）

- 物理：Magnus p_sat ✓、含湿量/焓/露点/湿球 ✓、SHR BF-ADP ✓、envelope/渗透 ✓、ODE 单位守恒（1000W×3600s=+1.0K@1000Wh/K）✓、太阳时修复验证 ✓、POA beam 690.3 vs 691 ✓、Erbs ✓、Open-Meteo direct=BHI 处理 ✓、焓平衡闭合差仅 M_deh·(h_fg−L_v)（即 #7）。
- 设备：Carnot COP 35/22→2.792 ✓、DEH SMER 1.24 g/s ✓、上轮修复 1/2 验证 ✓、LED 拆分 ✓、lag DC 增益=1 ✓。
- 植物：vpd 1.09 kg/m²·16h ✓、stomatal P-M λE=40.7 W/m² ✓、van_henten 与 reference 逐式一致 ✓、engine 潜热耦合闭合（除 #7）✓、609 运行健康 ✓。
- 能源：电池 SOC∈[0.1,0.9] 精确/库仑方向 ✓、能量守恒 8760h 残差 3.55e-15 kW ✓、PV 铭牌 580.46W ✓、CF≈0.17 ✓、Shanghai TOU 24h 全覆盖 ✓、CRF(0.06,25)=0.0782 ✓、LCOE 复算 ✓、本地时对齐 ✓、engine 积分 kW·h ✓。

## 5. Executor Feedback or Help Requests

### 给执行者的调研问题（已全部核实，结论见 §6）

1. **MAJOR-1**：示例 YAML alpha_sc 的来源与影响面——三处 YAML 各自用途；除 alpha_sc/I_mp/V_mp 外是否还有其它参数与代码默认/铭牌失配；preset_609 代码路径是否同样受影响；修复后 LCOE 扫描结论变化量级。
2. **MAJOR-2**：beta_voc 设计意图——代码为何选绝对式；改相对式 vs 改取值两种方案各自的波及面（project.py/示例 YAML/测试断言）。
3. **MAJOR-3**：negative COP 的完整触发链与防护位置——project.py 校验 vs hvac.py 运行时钳制哪个是正确层级；线性/表格插值边界。
4. **MAJOR-4**：size_hvac 与 size_deh 的关系——设计点 DEH 运行状态如何确定；把 DEH 净热并入设计负荷的正确口径（避免与 SHR 设计假设冲突）。
5. **MAJOR-5**：DEH 定容流程（engine.py:153）全貌——定容点 X_d=0.05 的取值依据；改为周期峰/均值定容的方案与副作用。
6. **MAJOR-6**：c_rad_phot 校准基来源——van_henten.py/reference 数据/609 OriginGrow 数据集的实际光单位；生长与蒸腾未互校准的根因。
7. **MINOR-7**：h_fg/L_v 统一方案——统一到 latent_heat_vaporization 后各调用点的行为变化（SHR 盘管、DEH 凝结、q_removal_corr）；是否有温度无关场景需保留常量。

### 修复实施记录（2026-08-16 会话，顺序 A→B→D→C 用户已确认）

- **组 A（能源）✅ 完成并验证**：3 个示例 YAML（test_project.yaml / example_lcoe_full.yaml / example_sweep.yaml）pv 段同步——alpha_sc 0.045→0.00045、I_mp_stc 13.33→12.66、V_mp_stc 46.0→45.85、beta_voc −0.25→−0.0025；`src/pvbes/pv.py` 改相对式乘法 `V_oc=V_oc_stc·(1+β·ΔT)`，默认 −0.0025；`src/design/project.py` PVConfig 量纲护栏（alpha_sc∈(0,0.01)、beta_voc∈(−0.1,0) fail-fast）；`sweep.py` calculate_metrics / `engine.py` simulate_performance 传 `year=es.lifetime//2`（degradation 生效），engine.py PVSystem 补传 C_pv/degradation。新增 test_sample_yaml_pv_params_match_code_default + 3 条 PV 护栏测试。数值验证：年 PV 58,647→36,076 kWh（**−38.5%**）。
- **组 B（设备）✅ 完成并验证**：project.py hvac 配置护栏（_require_nonnegative 扩展至 cop_value/cop_heat/eta_II/delta_T_evap/delta_T_cond/P_rated_w/P_rated_heat_w/Q_cool_nom/P_rated_max/safety_factor；cop_mode 白名单 carnot|constant|linear|table；cop_table 值非负；shr_BF∈[0,1)）；hvac.py COPModel constant/table/fallthrough 全部 max(0.5,…) 钳制 + cop_heat 钳制；size_hvac 新增 `deh_net_heat_w=0.0` 参数；engine.py `_build_devices` 重排（DEH sizing 提前到 HVAC sizing 之前，`deh_net_heat_w = deh._poly_power(T_sp,W_z)+fan_power_w` 传入，auto_size 写回 p.deh.P_ref_w / p.hvac.P_rated_w → CAPEX/LCOE 口径）。新增 7 条配置护栏 + 4 条 COP 钳制 + 2 条 size_hvac DEH 热 + 1 条 auto_size 写回测试。数值验证（609 双 auto_size）：hvac.P_rated_w 3000→**6633.1**、deh.P_ref_w 2233→**3106.6**。
- **组 D（MINOR-7 方案 A）✅ 完成并验证**：shr.py `q_lat = latent_heat_vaporization(T_adp)·1000·dW`；hvac.py `M_target = Q_lat/(latent_heat_vaporization(T_supply)·1000)`，T_supply=T_setpoint−shr.t_coil_drop；dehumidifier.py Q_dh/eta 用 `L_v=latent_heat_vaporization(T_z)·1000`（与引擎闭合差精确归零）；transpiration.py stomatal `E_rate = λE/(latent_heat_vaporization(T_z)·1000)`；h_fg 字段全部保留（构造签名兼容），仅计算路径改温度相关。test_03_numerical.py test_stomatal_pm_unit_invariance 手算同步更新。
- **组 C（植物）✅ 完成并验证**（三子项 C-1/C-2/C-3，联动约束按 §6 同批落地）：
  - **C-1 MAJOR-5 DEH 定容**：engine.py auto_size 分支 van_henten 法改轻量生长预跑——前向 `crop_cycle_days` 步（毫秒级、无容量约束），取光期平均蒸腾作为设计 X_d 定容。数值验证：van_henten auto_size DEH P_ref_w 2233→**9303W**（设计点回到晚周期真实蒸腾量级）。
  - **C-2 MAJOR-6 校准基声明**：GrowthConfig.c_rad_phot + van_henten.py `_defaults` 加校准基声明注释（VH2003 番茄默认、参考带 25-100 W/m²、引擎 87.5 W/m² 在带内、产量 ~109 vs 真实 30-60 kg 鲜/m²/yr）；project.py `k_van_henten` 单位注释 `m²/(s·kPa)`→`1/(s·kPa)`（顺带修 MINOR-15）。新增 `test_water_balance_closure`（w/f∈[3,12] L/kg + harvest>1000kg + 水量有限）+ `test_growth_energy_use_efficiency_band`（RUE∈[1.5,4] g/MJ）。
  - **C-3 k_vpd 回调联动**：k_vpd 默认 2e-5→**5e-5**（transpiration.py + project.py + 3 个 YAML + 2 处测试断言同步：test_transpiration.py、test_03_numerical.py）。用户决策：**温和回调 5e-5**——实测 1e-4 致 harvest=0（正反馈爆炸），不可取。数值验证：w/f 3.4→**5.8 L/kg**（固定 DEH）/ 6.8（auto_size）；3 个极端鲁棒性测试显式固定 k_vpd=2e-5（避免小房间热发散）。
- **当前验证状态**：四组全部完成后全量 pytest **197 passed**（195 基线 + 2 个新水账测试：test_water_balance_closure + test_growth_energy_use_efficiency_band）。

### MINOR-7 调研结论（本文件 subtask 5，只读）

- **调用点清单（5 处硬编码 2.5e6 + 1 处已温度相关）**：`shr.py:32,60`（SHR 除湿比 q_lat=h_fg·dW，盘管温度 T_adp）、`hvac.py:90,163`（M_target=Q_lat/h_fg，盘管温）、`dehumidifier.py:75,132,138`（Q_DH=P_comp+M·h_fg + eta 上报，蒸发器 ~10°C）、`transpiration.py:47,100`（stomatal λE→E，叶温≈T_z）、`engine.py:328`（L_v(T_z)，唯一温度相关，三处共用：蒸腾冷却/removal_corr/q_corr）。van_henten 无潜热。
- **推荐方案 A（全部改 latent_heat_vaporization(T)，DEH/蒸腾取 T_z，盘管取盘管温）**：与引擎 L_v(T_z) 同温 → 闭合差 M·(h_fg−L_v) 归零；SHR/hvac 盘管侧用 T_adp/T_supply 保物理。方案 B（注入 callable）接口过重；方案 C（单一共享常量）残余 ±0.2% 不归零。
- **数值量化**：2.5e6 vs L_v(22)=2.449e6 → +2.08%；vs L_v(10)=2.477e6 → +0.91%。DEH 残留 = M·50.9 kJ/kg（T_z=22 满额 P_ref=2233W 时 ~63W，年 ~241 kWh 与实测一致）。修复后引擎焓平衡闭合差归零。
- **测试面**：无测试断言 2.5e6 字面量；test_03:373 读 model.h_fg 属性（保留属性即通过）；SHR 区间/年度 45-75MWh 断言余量大（0.4% 位移）。回归面 LOW。
- 报告已输出给用户（MINOR-7 调研报告）。
- **已实施（组 D）**：方案 A 已按调研结论落地——引擎焓平衡闭合差精确归零，全量 195 passed，详见"修复实施记录"。

### Git 状态

- 四组（A/B/C/D）修复**已改代码但未提交**：工作区共 **19 个文件待提交**（9 src/ + 5 tests/ + 3 YAML + 2 scratchpad）——18 个已跟踪文件为修改 + 本 scratchpad 新增（untracked）。
  - src/（9）：src/pvbes/pv.py、src/design/{project,engine,sweep}.py、src/devices/{hvac,dehumidifier}.py、src/physics/shr.py、src/plants/{transpiration,van_henten}.py
  - tests/（5）：test_03_numerical / test_04_config / test_05_regression / test_devices / test_transpiration
  - YAML（3）：example_lcoe_full / example_sweep / test_project
  - scratchpad（2）：2026-08-16_scratchpad_code_review.md（M）+ 2026-08-16_scratchpad_review_round2.md（本文件，untracked）
- 最近提交 `934f595 docs(meta): mark all 6 review fixes done` 为上一轮（round 1）修复收尾；本轮 scratchpad 尚未入库（untracked）。
- 待办：全量 pytest **197 passed** 已验证 → 统一 commit（含本 scratchpad）。

---

## 6. 细致调研结论（7 个目标问题，全部核实）

### MAJOR-1（能源 alpha_sc）— 确认成立，但范围缩小
- **100% 由 alpha_sc=0.045 驱动**：年发电量 58,647 vs 34,851 kWh（+1.68×），奉贤 2023 真实缓存天气复算。
- **I_mp_stc(13.33)/V_mp_stc(46.0) 失配输出零影响**：pv.py:59 组件功率 ∝ I_mp·V_mp 与 pv.py:76 组件数 ∝ 1/(I_mp·V_mp) 完全对消。属配置卫生问题，仍应修。
- **仅 3 个示例/测试 YAML 受影响**（example_lcoe_full / example_sweep / test_project，pv 段逐字相同）；preset_609 不设 pv 配置→走代码默认，**不受影响**。但 example_lcoe_full.yaml 名为 `fengxian_lettuce_609`，极易被当官方参数传播。
- 修复：3 个 YAML 改 alpha_sc→0.00045、I_mp→12.66、V_mp→45.85；project.py PVConfig 加量纲护栏（alpha_sc<0.01 断言）。LCOE 影响：0.9962→1.0175 RMB/kWh（+2.1%）。
- **新发现**：`year` 在 sweep.py:300 / engine.py:612 均未传（恒 0）→ `degradation=0.004` **从未生效**（PV 老化未计）；engine.py:586 还漏传 C_pv/degradation（默认兜底，当前无害）。

### MAJOR-2（能源 beta_voc）— 确认成立
- −0.25 V/K 绝对 vs 铭牌 −0.250%/K 相对（≡−0.143 V/K@57.34V），高温功率多压 ~35% → 年发电量低估 3.5%（34,851→36,080）。
- 方案：(a) 相对乘法 `V_oc=V_oc_stc·(1+β·ΔT)`、默认 −0.0025（推荐，与 α_sc 及行业 datasheet 惯例统一）；(b) 绝对式改 −0.143（改动最小）。**两方案都必须同步 3 个 YAML**——只改公式不改 YAML 会把 −0.25 当 −25%/K，V_oc 塌到 0。
- 测试零破坏（tests 无任何 PV 数值断言）；建议新增 `test_sample_yaml_pv_params_match_code_default` parity 测试。

### MAJOR-3（设备 COP 负值）— 确认成立
- constant/table 无下限 + `cop_heat` 无钳制 + 未知 `cop_mode` 静默落 `return self.value`（test_04_config 明确接受未知字符串）。
- 传播链完整核实：hvac.py:149-173（P_elec 仍正、Q_total<0、Q_target>0 加热、M_target<0 加湿）→ lag 传递 → engine.py:335-361 温湿度方程全污染。注意 engine.py:89 有 `max(cop_design,0.5)` 但**运行时 hvac.py:149 无**。
- 修复层级：**配置期校验为主**（project.py `_require_nonnegative` 扩展覆盖 cop_value/cop_heat/eta_II/delta_T_evap/delta_T_cond/shr_BF/cop_table 边值 + cop_mode 白名单）+ **运行时 max(0.5,…) 钳制兜底**（对齐 carnot 地板与 size_hvac 地板 0.5）。table 越界已是端点钳制不外推，仅需边值非负校验。
- 测试零破坏（现有全正输入）。

### MAJOR-4（设备 size_hvac 漏 DEH 热）— 确认成立
- 设计点 q_sens_raw≈9.26kW，漏 DEH 净热 P_comp+fan≈2.27kW ≈ **24%**。
- **口径铁律**：只加纯显热 `P_comp_design + fan`（`/shr_design` 之前）；**不得**加 m_dh·h_fg（与平衡式未计的 E_trans·L_v 相消，加了即双计）。
- 需重排 _build_devices：DEH P_ref 计算提前到 HVAC sizing 之前（engine.py:94-104 → 143-158）。
- 推荐方案 B（新增 `size_hvac(deh_net_heat_w=0.0)` 参数，默认 0 隔离全部现有单测）；方案 C（预设参考值）违反"无硬编码"弃用。
- **新发现**：sweep.py:103-104 资本成本用 config 的 P_rated_w/P_ref_w，**auto_size 结果不回写** → MAJOR-4 修复不传导 CAPEX/LCOE（sizing 与资本口径不一致，建议同批处理）。

### MAJOR-5（植物 DEH 定容点）— 确认成立（9.0×），但修正一处表述
- 定容点 X_d=0.05：注释称"mid-cycle"但实际第 3-4 天即达；**物理依据 = k_vpd/k_van_henten = 2e-5/4e-4 = 0.05 的对齐截点**，无独立物理基础。
- 峰值蒸腾 27.1 kg/h（day 29, X_d=0.4525）为定容点 3.0 kg/h 的 **9.0×**。
- **修正**：上轮"长时间 100% RH 平台"在 609 默认配置**未精确复现**——实际 RH 自锁在 83-87%（DEH 满载排冷凝热 5.3kW 抬室温→光合放缓→X_d 只长到 0.27）。欠配机理成立，只是自锁平衡点低于 100%。
- van_henten 法 water/鲜重 = 63.6 L/kg（vpd 法 3.5）。
- 方案：峰点定容（16.3kW，资本×7-9）❌ 过配；均值定容（~8.5kW）晚周期仍欠；**轻量生长预跑**（grow 模型前向 30 天，毫秒级，无容量约束）取峰/均值设计 X_d ✅ 推荐；或重校准 k_van_henten 到 vpd 尺度同点定容。另需补 auto_size 结果写回 p.deh.P_ref_w（现 sweep 资本用固定 2233W）。

### MAJOR-6（植物光输入校准基）— 部分修正：87.5 W/m² 并无错误
- **上轮表述不准确**：reference 脚本（PSO_Win.py:46 `'radiation': 70`、pandagrow.py:12、grow_one_state2003.py:38）光单位是 **W/m²，名义 70，校准带 25-100**；400 W/m² 仅存在于 van_henten.py:110 `_demo`（"outdoor ref"）与 test_02_physics.py:28，**非校准基**。
- **引擎 87.5 W/m² 恰落在参考校准带内** → 光输入与参考模型自洽，非"光输入错误"。c_rad_phot=1e-8 为 Van Henten 2003 番茄文献默认，未对 609 生菜再校准（无文档记录基准）。
- X_d 峰值 0.46 合理：RUE≈2.9 g 干/MJ（C3 区间 2.2-3.5）；但生长 ~109 kg 鲜/m²/年 vs 真实 PFAL 生菜 30-60，**偏高 ~2×**。
- **根因（两个 MAJOR 实为同一水账闭合问题两端）**：k_vpd=2e-5 是 B1 修复（humidity_audit e220645）为匹配 2233W 默认 DEH 而降 5×（原 1e-4 得 water/鲜重≈17.5 L/kg≈真实 ~20）→ **B1 修错了杠杆（拿物理换设备匹配）**；van_henten 反向过冲（63 L/kg）。两条链路各自独立，无 WUE/水账闭合约束。
- 方案：声明校准基（文档+注释，零风险）+ 水账闭合回归测试（water/鲜重∈[10,25] L/kg + RUE∈[1.5,4] g/MJ）；若要 KPI 真实（20 L/kg），k_vpd→~1e-4 是正解但**必须与 MAJOR-5 联动**（否则 DEH 欠配）并同步改 2 处 k_vpd 硬断言（test_transpiration.py:40-42、test_03_numerical.py:472-483）。

### MINOR-7（三路共性 h_fg/L_v）— 确认成立，方案 A 推荐
- 5 处硬编码 2.5e6（shr.py:32,60 / hvac.py:90,163 / dehumidifier.py:75,132,138 / transpiration.py:47,100）vs 引擎唯一温度相关基准 L_v(T_z)（engine.py:328）。**温度无关场景不存在**——每个调用点都能拿到正确温度。
- 量化：DEH 满额残留 ~63W（M=1.24 g/s），年 ~241 kWh（0.4%）；修复后闭合差**精确归零**。
- 方案 A（推荐）：全改 `latent_heat_vaporization(T)`——T_z 系（DEH/transpiration/引擎）取 T_z 对齐；盘管系（shr q_lat 取 T_adp、hvac M_target 取 T_supply）保物理。方案 B（注入 callable）接口过重；方案 C（共享常量）残留 ±0.2% 不闭合。
- 测试影响 LOW：test_03:373 手算读 `model.h_fg` 属性→保留属性即自动通过；SHR 移 ~0.9% 仍在边界内。
- 注意：hvac.py 与 shr.py 的 h_fg 是两个独立字段（engine 构造 DynamicSHR 未传 h_fg），需保证同一盘管温口径。

### 调研结论汇总（7 问题核实状态）

| # | 问题 | 核实 | 关键修正/新发现 |
|---|------|------|------|
| 1 | alpha_sc 100× | ✅ 成立 | I_mp/V_mp 失配零输出影响；仅 3 示例 YAML；degradation 从未生效（year 恒 0） |
| 2 | beta_voc 单位 | ✅ 成立 | 建议相对式 −0.0025；两方案都须同步 YAML |
| 3 | COP 负值 | ✅ 成立 | 未知 cop_mode 静默回落；配置期校验+运行时钳制双层级 |
| 4 | size_hvac 漏 DEH 热 | ✅ 成立（24%） | 只加纯显热；DEH sizing 需提前；sweep 资本用 config 值不回写 |
| 5 | DEH 定容点 | ✅ 成立（9×） | RH 自锁 83-87% 非 100% 平台；X_d=0.05 是 k_vpd/k_van_henten 对齐截点 |
| 6 | 光输入校准基 | ⚠️ 部分修正 | 87.5 W/m² 在参考校准带内无错；核心是 k_vpd 降 5×（B1 修错杠杆）+ 水账未闭合 |
| 7 | h_fg/L_v | ✅ 成立 | 方案 A 闭合差归零；无温度无关场景；两独立 h_fg 字段需统一口径 |

### 修复联动约束（关键）

- **MAJOR-5 + MAJOR-6 必须联动**：k_vpd 上调（回真实 ET）必须与 DEH 定容修复同做，否则 DEH 欠配加剧；单独动一端会冲另一端。
- **MAJOR-1 + MAJOR-2 联动**：两方案方向相反互相掩盖，必须一起修并同步 3 个 YAML + 加量纲护栏 + parity 测试。
- **MAJOR-4 + sweep 资本口径**：建议同批把 auto_size 结果写回，否则修复不传导 LCOE。
