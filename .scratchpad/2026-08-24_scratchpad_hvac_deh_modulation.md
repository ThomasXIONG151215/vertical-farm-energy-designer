# 2026-08-20 Scratchpad — HVAC/DEH 变频调制建模

## 1. Background and Motivation

609 上海 2023 复测发现冬季暗期 RH 崩溃至 min RH 3.3%（1月17日 hour 22），根因定位为**压缩机二值开关（bang-bang）模型**与物理变频设备的偏差：

- **暗期第一子步**（灯灭 + T_sp 22→18 触发制冷）：蒸腾瞬间归零、HVAC 盘管以 m_coil_max=1.5 g/s 满速冷凝、DEH 满速，单子步(600s)抽走 ~1.7 kg 水 → RH 64.5%→12.4% 过冲。
- **光照期**：DEH 满速抽到 62% 死区停机 → 蒸腾灌回 79% → 锯齿振荡（周期 3 子步=30min）。

用户纠正：真实空调/除湿机**随工况自适应输出**（变频），限制因素只有**延迟**和**最大上限**；输出按各自设定值调制（设定值越近达标输出越低甚至停）；600s 子步=10 分钟平均值 → **调制系数 m∈[0,1] 无下限**（占空比物理可实现任意低平均输出）。

## 2. Key Challenges and Analysis

### 根因（插桩实证，2026-08-20 diag_substep.py + engine.py 临时 DIAG）
1. **压缩机纯滞回开关**：`CompressorState.update() -> bool`，on 即满功率（hvac.py:247 `Q_total = P_rated * cop`），无比例调制。
2. **设备输出不可变**：HVAC Q_total=3000W×COP≈13.5kW 恒定、盘管冷凝固定 1.5 g/s；DEH M_nom=1.24 g/s。
3. **guard 滞后**：P4-1 `_apply_rh_guard` 仅按当前子步 RH_z 制动（≤55% 停冷凝），不感知蒸腾归零事件，暗期切换时 RH 仍高 → guard 失效。
4. **容量不匹配**：DEH 固定 2233W (1.24 g/s) < 收获期蒸腾 1.68 g/s；HVAC 制冷量过剩 ~3×。

### 设计决策（用户 m0179 三点约束 → 方案）
- **比例调制**：`m = clamp((demand - on_threshold)/pband, 0, 1)`，on 态；off 态 m=0。
  - HVAC demand = T_z − T_setpoint（制冷）
  - DEH demand = RH_z − RH_setpoint
- **滞回停机保留**：demand ≤ −deadband 且 min_on 满足 → off；滞回区已 on 保持 on 但 m→0（变频无 min_off 惩罚）。
- **无 m_min 下限**：m∈[0,1]（10 分钟占空比物理）。
- 所有输出按 m 缩放：Q_total、Q_sens、Q_lat、M_target、P_elec。

### 默认参数
| 设备 | 比例带 pband | 停机死区 | 说明 |
|---|---|---|---|
| HVAC cool/heat | 2.0 °C | 1.0 °C | 609 暗期 s=0 demand=1.08°C → m≈0.54 |
| DEH | 4.0 %RH | 2.0 %RH（原 3.0） | 文献 3-5%；deadband 收窄减少空转带 |

pband 可配置（0=退回纯开关）。m∈[0,1] 无硬下限（用户拍板：10 分钟平均占空比）；文献变频机 turndown m_min=0.25 仅作可配置选项（默认 0）。

**性能曲线（第二轮调研定稿，详见 2.7）**：
| 设备 | 曲线 | m 截断 |
|---|---|---|
| HVAC | CapSpeedModFac=0.167+0.991m−0.158m²；EIRSpeedModFac=0.488+0.553m−0.041m²（COP=1/EIR 随 m 上升） | m<0.2 按 0.2 |
| DEH | SMER(m)=SMER_rated·(0.30+1.0467m−0.3467m²)（随 m 下降）；capacity=m 线性 | m<0.2 按 0.2 |

### 2.5 调研结论存档（3 subagents，2026-08-20）

**A. 变频空调（EnergyPlus 变速盘管 `Coil:Cooling:DX:VariableSpeed`）**
- 各转速档自带额定容量+额定 COP，档间线性插值（SpeedRatio∈[0,1]）；**调制区间无部分负荷损失**（"there is no part-load loss"）；功率随转速**线性**缩放 `P=Q_rated·m·EIR`（非泵 m³ 亲和定律）
- **不要对变频机套 EIR-FPLR 降级曲线**（那是单速循环型的 `PLF=0.85+0.15·PLR`，会错误地让部分负荷效率变差）
- m_min（turndown）：变频压缩机 20-35% 额定（推荐 0.25）；但 10 分钟步长平均输出可低于物理下限（占空比）→ 无硬下限成立
- 单速循环→COP 变差（AHRI Cd=0.25）；变速调制→COP 持平或略升（EN 14825 线性插值 COP；NEEA 2024 实测塌陷仅在 turndown 以下循环区）
- 植物工厂 pband 0.5-1.0K、deadband ±0.2-0.5K（舒适空调 1-3K）
- 来源：EnergyPlus 23.1 Engineering Reference + AHRI 210/240 + EN 14825 + NEEA 2024

**B. 除湿机（EnergyPlus `ZoneHVAC:Dehumidifier:DX`）**
- 额定点 26.7°C/60%RH（AHAM DH-1）；容量/EF 双二次曲线 f(T,RH)；**定速循环模型（PLF=0.95+0.05·PLR），变频调制是其范围外扩展**
- 变频连续调制：容量功率近似线性同缩、**无潜热退化**（FSEC/NREL）→ m∈[0,1] 线性缩放 M/P 正确且优于 PLF 模型
- **SMER 在调制下近似常数**（30-100% 转速内容量∝功率）→ `latent_cop=m·M·L_v/(P_comp·m)=常数`（m 分子分母对消）
- SMER 参考：DOE 下限 1.30-2.80、ENERGY STAR ≥1.70-3.30、高效商用 ~3.6、实测真实 1.2-1.5；**植物工厂冷凝式取 2.0-2.5**（609 smer=2.0 合理）
- 商用控制器标准：Neptronic proportional ramp `m=clamp((RH−SP)/pband,0,1)`——与方案完全同构；**pband 默认 5%RH**（猪舍研究最优 5）；deadband 商用 1-3%、EnergyPlus humidistat ~2%
- 修正建议：pband_rh 3-5 默认 4、deadband_rh 3→2（减少空转带）、SMER 不随 m 变（可选 m<0.3 低端折减）
- 来源：EnergyPlus 文档 + NREL/TP-5500-61076 + FSEC-GP-151-06 + AHAM DH-1 + Neptronic/Viconics + Lambert 1999

**C. 植物工厂湿度（建模缺口校准）**
- **暗期蒸腾 ≠ 0**：Caird, Richards & Donovan (2007, Plant Physiology 143:4-10) E_night/E_day 典型 5-15%（最高 30%）；Kim et al. (2004, Ann. Botany 94:691) 生菜 g_night/g_day=11%（白光）/24%（红蓝）/27%/39%（纯绿）；**植物工厂夜间 VPD 不降（18°C/65%→0.73 kPa vs 22°C/65%→0.87）→ E_night/E_day≈(0.1-0.3)×0.85≈0.09-0.26 → 暗期因子取 0.10-0.15**（609 取 0.15）
- **ACH 是冬季崩溃第一物理根因**：密闭 PFAL 实测换气率 **0.01-0.02 h⁻¹**（Kozai 2013 / WUR WPR-1315）；VFED 0.5=商业建筑渗透量级（ASHRAE 0.35-0.5）高 25-50 倍 → **建议 ACH 0.05-0.15**
- `M_lat=m_dot×(W_ext−W_z)` 公式本身是标准单区全混合模型（ASHRAE/EnergyPlus/Graamans 2017/Talbot&Monfet 2024）——**形式正确，问题在参数，不要引入任意「水分交换效率」系数**（物理由 ACH×(1−ε_lat) 捕获；短路属冠层尺度对应 r_a 减小）
- VPD 模型量级：k≈40-100 W/m²/kPa/LAI；VFED van_henten k=1e-4 标定（λE≈100 W/m² 收获期）落区间内——日间合理，问题只在暗期置零
- 湿度设定：Kozai 叶菜 VPD 0.5-1.0 kPa、PFAL RH 60-75%；609 的 65% 符合主流；死区 ±2-5%RH；除湿优先（"HVACD 先除湿后空调"）
- **加湿器**：需要但修正 ACH+暗期蒸腾后是「精度层」修复——只修这两项冬季 RH 就不会塌到 <10%；短期不加模型
- 能耗佐证：湿度上限 65→75% 除湿能耗降 12.8%（arXiv:2405.09643）

### 2.6 设计修正（相对 m0180 原方案）
1. **D 方向转向**：文献明确「不要任意水分交换效率系数」→ **ACH 0.5→0.1**（密闭 PFAL 泄漏上限）替代 moisture_mix_eff；影响 presets.py 609 + 3 示例 YAML + 显热/HVAC 定容（对密闭 PFAL 物理正确）
2. **m_min**：无硬下限（用户拍板）；文献 0.25 作可配置选项默认 0
3. **deadband_rh 3→2%**、**pband_rh 默认 4%**（文献 3-5）
4. **latent_cop 调制下为常数**（m 对消），不再乘 m
5. 调制区 EIR 恒定（中立，无 PLF 降级）✓ 与 m0180 一致
6. **暗期透蒸 0.15 有强文献支撑**（Caird 2007 + Kim 2004 + VPD 不降论证）✓
7. **2.6 的 4/5 已被第二轮真实曲线调研推翻/修正**（见 2.7）：
   - 原 4「latent_cop 调制下常数」→ **推翻**：DEH SMER 随 m 下降（DOE 实测），latent_cop 随之变化
   - 原 5「调制区 EIR 恒定中立」→ **修正**：HVAC 用 EIRSpeedModFac 曲线（COP 随 m 上升）；DEH 用 SMER(m) DOE 下降曲线

### 2.7 真实性能曲线（第二轮调研，3 subagents，2026-08-20）——推翻 2.5B「SMER 常数」假设

**A. 变频空调压缩机（COP 随 m 下降而上升，拱形）**
- 物理：降速→质量流量↓→压比↓→COP↑；反向力=驱动/电机损失（满速~4%、30%转速 6-10%、<20%转速 15%+）；COP 峰值在中低转速（~40-50Hz）
- 实测锚点：50% 负荷 COP≈满负荷 **1.2-1.5×**、30% ≈**1.4-1.6×**（Effsys2/KTH Madani、Szreder&Miara 2020 Sustainability 12:10521、Fahlén 2012 REHVA、Inampudi&Elbel 2024 ATE 247:123033）
- **推荐方案 A 黑箱曲线**（m∈[0.2,1]，m=1 归一 1.0）：
  - `CapSpeedModFac(m) = 0.167 + 0.991·m − 0.158·m²`
  - `EIRSpeedModFac(m) = 0.488 + 0.553·m − 0.041·m²`，`COP(m)/COP_rated = 1/EIRSpeedModFac`
  - m=0.20→COP 1.68、0.30→1.54、0.50→1.33、0.70→1.17、1.00→1.00
- 保守备选（Maxa 定风量空气-水机同温实测）：`EIRSpeedModFac = 1.1332 − 0.410m + 0.280m²`（部分负荷效率几乎不涨）
- **勿双重计入**：VFED Carnot COP 已含温度项，速度曲线只管转速一维；方案 B（耦合物理 EIR=1.05−0.05m 只叠加驱动损失）不选
- EN 14825 四点表混入温度效应不宜作转速曲线；AHRI IPLV=0.01×EER100+0.42×75+0.45×50+0.12×25（75%+50% 权重 87%）
- EnergyPlus 官方 IDF 10 档容量比严格线性（0.226…1.000），COP 全为占位常数 → **官方无非线性 COP 曲线，需外部数据**
- 数据缺口：m<0.15 无调制数据（最低 ~0.2，厂商油回油卡 ~15%）；植物工厂高温高湿无公开数据

**B. 变频除湿机（SMER 随 m 下降——与空调相反！DOE 87 FR 35286 官方实测）**
- 物理：析水需蒸发温度显著低于进风露点；降速→蒸发温度向露点靠拢→单位制冷量析水效率降
- DOE 实测 EF/EF_full：定速 100/75/50/25% = 1.00/0.99/~0.85/~0.73；**变频 = 1.00/0.89/~0.72/0.54**
- DOE 结论「变频不是除湿机提效的可行技术路径」（市售多定速，美国仅 1 台真变频；低负荷实际启停循环）
- **推荐 DOE 曲线**（三点二次拟合，numpy 复核）：
  - `capacity(m) = m · capacity_rated`（线性，质量流量∝转速）
  - `SMER(m) = SMER_rated · (0.30 + 1.0467·m − 0.3467·m²)`
  - `P(m) = m·P_rated/(0.30 + 1.0467·m − 0.3467·m²)`
  - m=0.25→SMER 0.540、0.30→0.583、0.50→0.737、0.70→0.863、0.75→0.890、1.00→1.000
- **「SMER 常数」假设只在 m≥0.75 成立（偏差≤11%）；m 0.5-0.75 偏离 11-26%；m<0.5 完全失效（26-46%）→ latent_cop 随 m 变化，不再常数**
- 可选叠加 E+ 官方双二次进风工况曲线（ZoneHVAC:Dehumidifier:DX，NREL 六机拟合 NREL/TP-5500-52791）：WR/WR_rated 与 EF/EF_rated = a+bT+cT²+dRH+eRH²+fT·RH（T∈[21,32.22]°C、RH∈[40,80]%；@26.7/60 输出 0.981/0.975）——**609 室内 ±10%，先省略**
- 额定点 26.7°C/60%RH（AHAM DH-1）；SMER 2.0-2.5 合理（609 smer=2.0）；厂商无转速表（行业缺口）；定速循环回蒸损失 NREL/TP-5500-61076（变频路径无此损失，但低转速本身掉 SMER）

**C. 选型逻辑（m0221-0222 澄清）**
- 容量由**峰值日负荷×safety（1.1-1.2）**定，日常 m≈0.3-0.5 是正确选型自然结果（**不是目标**）
- m=0.5 是「高效区+峰值覆盖+成本」平衡点；m=0.2 COP 最高（1.68×）但需 5× 容量+压循环区边界
- 609 现状 HVAC 13.5kW 制冷量 vs 日常 ~3.5kW → m≈0.26（COP 高处但成本 3×+夜间 m<0.2 进循环区）

## 3. High-level Task Breakdown

- [ ] T1: `vfed/devices/compressor.py` — `CompressorState.update()` 返回 float m（band>0 时比例调制，band=0 保持 0.0/1.0）；新增 `proportional_band` 构造参数；保留 is_on/min_on/min_off/deadband；m∈[0.2,1] 截断说明
- [ ] T2: `vfed/devices/hvac.py` — `__init__` 加 `mod_band_c=2.0` + 速度曲线系数（CapSpeedModFac=0.167+0.991m−0.158m²、EIRSpeedModFac=0.488+0.553m−0.041m²，m 截断 0.2）；cool/heat 分支 `Q_total=P_rated×cop×CapSpeedModFac×m`、`EIR_eff=EIR×EIRSpeedModFac`（COP 随 m 升）；P_elec=Q_total×EIR_eff+fan；返回 dict 加 `"mod"` 键
- [ ] T3: `vfed/devices/dehumidifier.py` — `__init__` 加 `mod_band_rh=4.0` + `smer_mod_fac(m)=0.30+1.0467m−0.3467m²`（DOE 实测）；`s_dh=mod` 全链缩放；`SMER_eff=SMER×smer_mod_fac(m)`（随 m 降）→ latent_cop 随 m 变（非常数）；deadband_rh 3→2；m 截断 0.2
- [ ] T4: `vfed/plants/transpiration.py` — 暗期透蒸 `dark_transpiration_frac=0.15`（light_factor 暗期分支 0→0.15）
- [ ] T5: `vfed/physics/envelope.py` + 参数 — **ACH 0.5→0.1**（presets.py 609 + 3 示例 YAML + test_project.yaml）
- [ ] T6: `vfed/design/project.py` — HVACConfig.comp_mod_band_c=2.0、DEHConfig.comp_mod_band_rh=4.0、TranspirationConfig.dark_transpiration_frac=0.15 + 校验 + engine `_build_devices` 传参
- [ ] T7: 测试更新 — test_devices（hvac/deh 数值断言按 m 重算）、test_transpiration（暗期 0.15× 替代归零）、test_03/05（609 数值/RH 断言、ach）
- [ ] T8: 609 上海 2023 复测 — 前后对比表回填实测值
- [ ] T9: scratchpad 更新 + git 提交

## 4. Project Status Dashboard

### 前后对比（T8 实测回填，609 上海 2023）

| 指标 | 基线（bang-bang） | 实测（VFD + 暗期0.15 + ACH 0.1） | 判定 |
|---|---|---|---|
| min RH | 3.3% | **30.3%**（2月最差，余 34-44%） | ✓✓ 冬季崩溃消除 |
| RH<10% | 24h | 0h | ✓ |
| RH<20% | 135h | 0h | ✓ |
| RH<30% | 429h | 0h | ✓ |
| RH<50% | 1619h | 1141h（−30%） | ✓ |
| 年能耗 | 63,377 kWh | 60,556 kWh（−4.5%） | ✓ 变频省电 |
| w/f | 3.79 | 4.25 L/kg | ✓ 带内 [3,12] |
| 年水耗 | 19.7 m³ | 21.9 m³ | 暗期透蒸贡献 |
| harvest | 5213 kg/yr | 5151 kg/yr | 稳定 |
| LCOE | — | 0.579 | 稳定 |
| removal_limited | 0 | 0 | 无限制事件 |

**三项修复贡献**：ACH 0.5→0.1（渗透干燥降 80%）+ 暗期透蒸 0.15×（暗期 0.25 g/s 补水）= 冬季不再单向流失；变频调制（盘管 m 限速 + SMER 曲线）= 消除单子步过冲 + 年能耗 −4.5%。

### 二次修复（49030a0，2026-08-20 用户驱动：ACH 0.001 + 设定点钳制）

| 指标 | 前（ACH 0.1 + guard55 + pband4） | 二次修复后 |
|---|---|---|
| min RH | 30.3% | **63.0%**（设定 65%，仅差 DEH deadband 2%） |
| RH<10/20/30/40/50% | 0/0/0/11/1141h | **全 0h** |
| RH 60-70% 健康带 | — | **5143h（59%）** |
| 年能耗 | 60,556 kWh | 65,698 kWh（守 65% 代价 +6.4% vs 基线） |
| deh_util | 1.000 | 0.858（有停机时段） |
| w/f | 3.79 | 3.87 L/kg（带内） |

**二次修复内容**：① ACH 0.5→0.1→**0.001**（用户拍板全密闭，m_dot=6.7e-5 kg/s）；② engine `_limit_removal_by_inventory` 加 `W_setpoint_kgs` 设定点钳制（设备绝不抽过设定点，镜像 VFD 降速）；③ shr_rh_guard 55→**65**（=设定值）；④ DEH mod_band_rh 4→**6**（提前降速）。
**残留**：<50% 141h（钳制前）成因=苗期无蒸腾+无加湿器物理漂移，已被钳制根治。**遗留**：加湿器精度层未建模；test_weather_no_cache 网络环境失败与代码无关。

### 完成状态

| 任务 | 状态 |
|---|---|
| 根因定位（二值开关 + 插桩证据） | ✅ 完成 |
| 方案定稿 + 选型确认（A 曲线 / DOE SMER / m 截断 0.2） | ✅ 完成 |
| T1 compressor.py（调制系数 m + proportional_band + m_min） | ✅ 完成 |
| T2 hvac.py（Cap/EIR 速度曲线 + m 缩放 + mod 键） | ✅ 完成 |
| T3 dehumidifier.py（DOE SMER(m) 曲线 + deadband 3→2） | ✅ 完成 |
| T4 transpiration.py（dark_transpiration_frac=0.15） | ✅ 完成 |
| T5 ACH 0.5→0.1（project/envelope/presets/3 YAML） | ✅ 完成 |
| T6 project.py 字段 + 校验 + engine 传参 | ✅ 完成 |
| T7 测试更新（暗期 0.15× 改造；全量 227 passed） | ✅ 完成 |
| T8 609 复测对比（min RH 3.3→30.3%→**63.0%** 二次修复） | ✅ 完成 |
| T9 scratchpad + git（0f4cb42 + 49030a0） | ✅ 完成 |

## 5. Executor Feedback or Help Requests

- 无阻塞。T1-T9 全部完成。
- 提交：`49030a0`（二次修复：ACH 0.001 + 设定点钳制 + guard65/pband6）；`0f4cb42`（T1-T8 变频调制）。
- 测试全量 226 passed（1 网络环境失败 test_weather_no_cache，与代码无关）。
