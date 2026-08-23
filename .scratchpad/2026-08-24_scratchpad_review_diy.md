# 2026-08-20 Scratchpad — 交接：本次修复复查 + 可提升诊断 + DIY 可用性

> 本 scratchpad 用于**引导新会话**：①复查 2026-08-20 完成的湿度/变频修复；②诊断其他可提升方向；③评估 VFED 在 **DIY 植物工厂设计**层面的可用性（用户重点）。
> 主任务 scratchpad：`.scratchpad/2026-08-20_scratchpad_hvac_deh_modulation.md`（含完整调研存档与对比表）。

## 1. Background and Motivation

本会话从「第三轮审查修复」开始，完成了一次大的模型收敛 + 两次湿度修复闭环。用户新诉求：把这些工作固化，并引导下一会话继续——尤其面向 DIY 植物工厂用户的可操作性。

**交接状态（新会话起点）**：
- git HEAD=`10b5b25`（docs scratchpad），提交链：`3b6f249`（蒸腾 5 方法收敛）→ `0f4cb42`（变频调制 T1-T8）→ `49030a0`（湿度二次修复：ACH 0.001 + 设定点钳制）→ `10b5b25`（scratchpad）
- 工作区 clean；pytest 226 passed（1 失败 test_weather_no_cache 纯网络环境，Open-Meteo 不可达）
- 609 复测脚本：`C:\Users\ADMINI~1\AppData\Local\Temp\opencode\s9_recheck.py`（fetch_weather(30.9,121.5,2023) + preset_609() + DesignEngine().run）

## 2. 本次解决的问题（复查锚点）

### 2.1 湿度崩溃闭环（3.3% → 63.0%）
| 阶段 | min RH | 修复 |
|---|---|---|
| 起点（bang-bang） | 3.3%（冬季暗期） | — |
| 三项修复（VFD 变频 + 暗期透蒸 0.15× + ACH 0.1） | 30.3% | 消除单子步过冲 + 冬季单向流失 |
| 二次修复（ACH 0.001 + 设定点钳制 + guard65 + pband6） | **63.0%** | 设备绝不抽过设定点；零渗透 |

机制链：**ACH 0.001（零渗透）→ 暗期透蒸 0.15×（Caird 2007/Kim 2004 文献）持续补湿 → 设定点钳制（`_limit_removal_by_inventory` 新增 `W_setpoint_kgs`，W_z≤设定点时设备禁止主动除湿）→ VFD 变频（设备接近设定值降速，600s 平均输出不抽过设定点）**。

### 2.2 设备建模升级（二值开关 → VFD 变频 + 真实实测曲线）
- `CompressorState.update() -> float m`（比例调制 + turndown 0.2 + min_on/min_off/deadband 保留）
- HVAC：`CapSpeedModFac=0.167+0.991m−0.158m²`、`EIRSpeedModFac=0.488+0.553m−0.041m²`（COP 随 m 上升：50%→1.33×、30%→1.54×；Effsys2/KTH/Szreder/Fahlén 实测拟合）；`speed_curve="default"|"flat"`（flat=Maxa 保守）
- DEH：`SMER(m)=0.30+1.0467m−0.3467m²`（**随 m 下降**——DOE 87 FR 35286 变频实测，与空调相反）；capacity=m 线性；latent_cop 非常数
- 参数默认：HVAC mod_band_c=2.0°C / guard=65%RH（=设定值）/ DEH mod_band_rh=6.0 / deadband_rh=2.0 / ach=0.001 / dark_transpiration_frac=0.15

### 2.3 最终指标（609/上海 2023）
min RH **63.0%**（设定 65%）、RH<50% **0h**、60-70% 健康带 5143h（59%）、年能耗 65,698 kWh（守 65% 代价 +6.4% vs 基线 60,556）、deh_util 0.858、w/f 3.87、harvest_fw 5108 kg/yr、年水耗 19.8 m³。

## 3. 待再检查清单（新会话必查）

- [ ] **R1. 设定点钳制的边界**：`engine.py:34-66 _limit_removal_by_inventory` 的 `W_setpoint_kgs`——①苗期（X_d 小、蒸腾低）光照期 W 常低于设定点时设备是否长期停摆、湿度是否失控偏高；②钳制与 `_apply_rh_guard`（guard 65）的相互作用是否产生设备空转/短循环；③`removal_limited_events` 统计是否准确
- [ ] **R2. 能耗 +6.4% 的取舍**：守 65% 的代价。文献：湿度上限 65→75% 除湿能耗降 12.8%（arXiv:2405.09643）。评估「夜间/冬季放宽 RH 上限到 70%」策略是否值得（harvest/品质影响 vs 能耗）
- [ ] **R3. 变频曲线敏感度**：①HVAC 方案 A vs Maxa flat 曲线对 609 年能耗的差异（未实测）；②日常 m≈0.26 接近截断 0.2——统计 m<0.2 的时长占比（暗期夜间），评估循环区行为；③DEH SMER(m) 在苗期低负荷的能耗惩罚
- [ ] **R4. 暗期透蒸 0.15 的校准复核**：w/f 3.87 接近带内下沿 [3,12]，年水耗 19.8 m³——0.15 是否过保守（文献区间 0.10-0.15，取上限）；vpd/van_henten 标定与新链自洽性
- [ ] **R5. 测试鲁棒性**：`test_weather_no_cache` 依赖 Open-Meteo 网络（离线 CI 会红）。考虑 mock 或 local fixture 替代
- [ ] **R6. 物理一致性**：`q_removal_corr`（removal_scale 温度回补）在钳制下是否仍正确；`M_deh_act/M_hvac_act` 与 summary 的 deh_nominal/actual 口径一致性；暗期 T_z 控制（T_dark=18 但实际 ~19，HVAC 常制冷）合理性

## 4. 其他可提升方向（诊断候选）

- [ ] **P1. 加湿器建模**（精度层，曾拒但可选）：苗期/冬季透蒸不足时补湿，容量 m_hum ≥ m_dot·(W_sp−W_ext,design) − m_transp,night + safety；文献确认「修正 ACH+暗期蒸腾后是精度层缺口非崩溃层」
- [ ] **P2. 双二次进风工况曲线启用**：E+ 官方系数已存档（WR/EF f(T,RH)，T∈[21,32.2]°C、RH∈[40,80]%），609 室内 ±10% 影响小，但对不同气候区 DIY 用户有意义
- [ ] **P3. VPD 恒定控制替代 T/RH 分别控制**（Kozai；Inoue 2021：VPD 剧烈波动抑制生菜光合）——设定从「RH 65% 固定」升级为「VPD 0.5-1.0 kPa 目标」，夜间适度放宽
- [ ] **P4. 压比耦合建模**：方案 B（EIR=1.05−0.05m 只叠加驱动损失）可替代黑箱近似，若引擎显式算蒸发/冷凝温度
- [ ] **P5. 收获周期分阶段控制**：苗期/成株期不同湿度与温度设定（周期 30 天已可用 cycle_day 区分蒸腾，但环境设定仍全局单一）
- [ ] **P6. 设备 lag 参数校准**：tau_q/tau_m（90/60-120s）是否有厂商实测依据；600s 子步内 lag 效果验证
- [ ] **P7. weather_cache legacy 警告**：缓存未编码 tilt/azimuth/tz（每次重算 poa），可升级缓存格式
- [ ] **P8. DEH/HVAC 定容默认策略**：609 固定容量（DEH 2233W/HVAC 3000W）vs auto_size——对非 609 用户应默认开 auto_size 或提供引导

## 5. DIY 植物工厂可用性评估（用户重点）

### 5.1 现状（从 DIY 用户视角的 gap）
1. **预设单一**：仅 `preset_609`（奉贤 609 项目），无小型/家用/模块化预设。DIY 用户无从下手
2. **auto_size 默认关闭**：`p.deh.auto_size=False`、`p.hvac.auto_size=False`，固定容量（DEH 2233W/HVAC 3000W）是 609 定制值——DIY 用户必须手写设备容量，门槛极高
3. **配置契约面向工程师**：YAML 字段（SHR/VPD/ACH/COP/tau_q/lag）无 DIY 解释层；`vfed design new` 需要 preset/城市/年份，无交互向导
4. **无硬件规格映射**：真实市售设备（某型号除湿机 SMER/容量、空调 COP/P_rated）无法直接导入，DIY 用户需自行换算
5. **输出不直观**：SimulationResult summary 是 dict（annual_energy_kwh、specific_energy_kwh_per_kg、lcoe），无图表/报告；sweep 产出 CSV
6. **文档面向研究**：README 描述架构与命令，无「从 0 设计一个 10m² 植物工厂」教程

### 5.2 建议方向（供新会话评估，按优先级）
- [ ] **D1. DIY 预设集**：新增小型预设（如 10-50 m²、1-2 层货架、家用 LED），参数全走 auto_size；`presets.py` + 示例 YAML
- [ ] **D2. 默认 auto_size 引导**：`design new` 无显式设备容量时默认开 auto_size（或交互询问），消除固定容量陷阱
- [ ] **D3. 设备规格模板**：支持从「真实设备型号规格表」构建（SMER/COP/容量/风量 → HVACConfig/DEHConfig 映射），含常见型号库
- [ ] **D4. 配置向导（CLI 交互）**：`vfed design new` 增加交互模式——规模→作物→城市→设备偏好，自动生成 YAML
- [ ] **D5. 报告/可视化输出**：run 结果生成 HTML/MD 报告（能耗构成、RH 分布、LCOE、设备利用率图表）
- [ ] **D6. DIY 文档**：中文入门教程——「用 VFED 设计你的第一个植物工厂」（含 609 复现步骤、参数解释表、常见坑）
- [ ] **D7. 参数敏感度速查**：sweep 封装成 `vfed design explore`（对关键参数一键扫描输出对比图），降低 sweep 门槛

### 5.3 已知有利因素
- 配置全 YAML、无 EnergyPlus 依赖、Python 3.8+ 轻依赖（numpy/pandas/pyyaml/requests）——DIY/自托管友好
- 天气自动获取 + 缓存（fetch_weather 自动地理编码）——无数据门槛
- LCOE 经济性模块对 DIY 预算评估直接有用
- 现有 5 方法蒸腾 + VFD 设备曲线已足够贴近真实，DIY 用户可直接产出可信 sizing

## 6. 新会话启动指引

1. 读本文件 + `.scratchpad/2026-08-20_scratchpad_hvac_deh_modulation.md`（调研存档 2.5/2.6/2.7 节）
2. `git log --oneline -8` 确认提交链；`git status` 确认 clean
3. `python -m pytest -q --no-cov` 基线（期望 226 passed + 1 网络失败）
4. 如需复现 609：跑 `s9_recheck.py`（或 python -c fetch_weather + run）
5. 按第 3 节 R1-R6 逐项复查；再按第 4/5 节优先级诊断
6. 每次子任务完成更新本文件 Section 3/4 勾选状态

## 7. Executor Feedback or Help Requests

- 待用户拍板的方向：①是否接受「守 65% 能耗 +6.4%」或探索夜间放宽策略（R2）；②DIY 方向优先级（D1-D7 哪些先做）；③加湿器是否建模（P1）。
- 数据/代码事实（新会话直接可用）：SimulationResult.timeseries 是 dict-of-list（用 np.asarray）；summary keys：annual_energy_kwh / annual_harvest_fw_kg / annual_water_m3 / specific_energy_kwh_per_kg / lcoe / dehumidifier_performance.deh_utilization / moisture_clamp_stats；609 天气缓存 weather_cache\weather_30.900_121.500_2023.csv。
