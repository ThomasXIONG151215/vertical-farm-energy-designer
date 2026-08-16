# 2026-08-16 Scratchpad — VFED 仿真架构代码审查与修复

## 1. Background and Motivation

用户请求对 VFED 整体仿真架构做代码审查（原文："希望你检查整个仿真架构看有哪些潜在隐患和传热传质能源调度方面的错误计算"）。审查已完成，输出为项目根目录 `REVIEW.md`（commit c2909cc 已提交）。审查聚焦：传热传质（潜热/显热口径、太阳时）、能源调度（PV/电池/电网记账、LCOE）、以及设备模型参数合理性。

状态：**审查 + 全部 6 项修复已完成**（commit 2166319），177 测试全部通过（覆盖率 59%→75%）。

## 2. Key Challenges and Analysis

审查覆盖 `src/physics/`、`src/devices/`、`src/pvbes/`、`src/design/`、`src/weather/`、`src/plants/` 全部模块。发现 6 个问题（2 CRITICAL / 3 MAJOR / 1 MINOR），核心难点：

- **潜热双重复计**（问题1）：HVAC 把总冷量（显+潜）同时从温度方程和湿度方程各扣一次，焓平衡破坏 → 房间偏冷、HVAC 能耗低估。这是传热传质层最深的隐患，修复涉及 hvac.py + engine.py 两处联动。
- **太阳时符号错误**（问题2）：weather_bridge 本地太阳时公式符号翻转，上海（lon≈121.5, tz=8）仅偏差 ~0.2h 可忽略，但乌鲁木齐（lon=87.6, tz=8）偏差 ~4.3h → 时角 ~65°，PV 几何严重失真。
- **DEH 风机热去向存疑**（问题3）：P_elec 记账含风机功率但 Q_target 不含 → 40W 默认值是否合理、风机散热是否入房间，需要外部调研支撑修复（用户指定派 explore agent 先查）。
- **能源记账语义**（问题4/5）：power_deficit 忽略电池放电、LCOE 两套实现（lifetime CRF vs 组件折旧年 CRF）不一致 —— 属能源调度层的口径问题。

## 3. High-level Task Breakdown

| # | 任务 | 状态 | 依赖 |
|---|------|------|------|
| 0 | 架构代码审查 + 输出完整 Review Report | done | — |
| 1 | 创建 REVIEW.md（项目根目录） | done | — |
| 2 | 【CRITICAL】修复 HVAC 潜热双重复计（hvac.py:157 + engine.py:342-343 q_removal_corr） | done | approve |
| 3 | 【CRITICAL】修复 weather_bridge.py:67 太阳时符号 + 补乌鲁木齐测试用例 | done | approve |
| 4 | 【MAJOR】修复 DEH 风机功率热未计入房间热平衡 | done | **explore agent 调研** → approve |
| 5 | 【MAJOR】修复 energy_system.py:53,95 power_deficit/TLPS 语义 | done | approve |
| 6 | 【MAJOR】对齐/删除 calculate_metrics LCOE 两套实现 | done | approve |
| 7 | 【MINOR】校准 pv.py 铭牌参数 + 处理 eta_pv 死字段 | done | approve |
| 8 | 回归测试 + pytest 全量验证 | done | 2–7 每项之后 |

并行组标记：`[2 | 3 | 4 | 5 | 6 | 7]` 相互独立（4 需先完成前置调研）；`7 → 8` 顺序。

## 4. Project Status Dashboard

### 审查发现（6 问题，全部已修复）

| # | 级别 | 位置 | 问题 | 修复方案（已实施） |
|---|------|------|------|----------|
| 1 | CRITICAL | `src/devices/hvac.py:153-158` + `src/design/engine.py:342-343` | HVAC 除湿潜热双重复计：Q_target 扣整段总冷量（温度方程），M_target 又扣潜热（湿度方程）→ 房间偏冷、HVAC 能耗低估 | ✅ hvac.py: Q_target 改显热口径 `-(shr·Q_total − fan)`，潜热经 M_target 入湿度方程、冷凝热室外排出；engine.py: q_removal_corr 改为 `-(1-scale)·M_deh_nom·L_v`（只回退 DEH 幻影热，HVAC 项删除） |
| 2 | CRITICAL | `src/weather/weather_bridge.py:67` | 太阳时符号错误：`lst = hour + minute/60 + (lon/15.0 − tz_hours)`，应为 `hour + tz_hours − lon/15`。上海偏差 0.2h 可忽略；乌鲁木齐(lon=87.6, tz=8) 偏差 ~4.3h → 时角 ~65°，PV 几何严重失真 | ✅ 符号翻转 `(tz_hours − lon/15)`；补乌鲁木齐/上海太阳正午测试（test_02_physics.py TestSolarGeometry） |
| 3 | MAJOR | `src/devices/dehumidifier.py:129-130` | DEH 风机功率热未计入房间热平衡：P_elec=P_comp+fan_power_w（记账含风机），但 Q_target=Q_dh=P_comp+m_dh·h_fg 不含风机热（默认 40W） | ✅ 调研（Quest 225/Anden A321/Munters 规格书+ENERGY STAR）确认风机热入室内，Q_target 加 `fan_power_w`；40W 默认保留（≤300 m³/h 小风量合理） |
| 4 | MAJOR | `src/pvbes/energy_system.py:53,95` | power_deficit/TLPS 语义错误：`power_deficit=max(0,load−pv)` 只减 PV 不减电池放电；电池可覆盖时仍计失电 | ✅ 改为 `max(0, load − pv − battery_discharge)`（孤岛视角：负载超出 PV+电池放电能力才算失电），注释说明并网场景语义 |
| 5 | MAJOR | `src/pvbes/energy_system.py:57-68` vs `sweep.py`/`engine.py` `_compute_lcoe` | LCOE 两套实现不一致：calculate_lcoe 用单一 lifetime CRF；主路径 _compute_lcoe 按组件折旧年 CRF。sweep 中忽略 calculate_metrics 的 lcoe 字段 | ✅ 删除 `calculate_lcoe` 方法与 lcoe 字段；docstring 注明 LCOE 由 `sweep._compute_lcoe` 统一（单一来源） |
| 6 | MINOR | `src/devices/pv.py:22,27-28,71` | 铭牌参数不符 + eta_pv 死字段：V_mp_stc·I_mp_stc=46·13.33=613W 与 Jinko 78HL4-BDV 真实铭牌(~570-580W)不符 → n_modules 偏小；eta_pv=0.233 定义后从未使用 | ✅ V_mp 46→45.85V、I_mp 13.33→12.66A（JKM580N-78HL4-BDV 铭牌，P=580.5W）；eta_pv 标注为信息性字段（配置契约保留，不参与 SDM 计算）。project.py 同步 |

### 任务状态

| 任务 | 状态 |
|------|------|
| 审查探索（完整 Review Report 输出） | done |
| REVIEW.md 创建（项目根目录） | done（c2909cc 已提交） |
| 6 项修复（问题1–6） | **全部 done** |
| 问题3 前置调研（explore agent 查 DEH 风机功率/散热） | done |
| 回归测试 + pytest（每项修复后） | **done — 177 passed**（覆盖率 59%→75%） |

### 核查通过清单（无问题模块）

psychrometrics.py、shr.py、envelope.py、ode.py、battery.py、transpiration.py（stomatal P-M 与 FAO-56 一致）、van_henten.py、dehumidifier.py SMER 换算、compressor.py、led.py、engine.py 时步/功率汇总/收割/ES 块、grid.py/Tariff —— 单位与守恒核查通过。

## 5. Executor Feedback or Help Requests

### 给执行者的反馈/请求（已全部落实）

1. **问题3 外部调研**（用户要求）：已派 explore agent 完成调研——Quest 225（1230W/1070m³/h）、Anden A321（1960W）、Munters ComDry M160L（150m³/h 风机~170W）、ENERGY STAR。结论：40W 仅≤300m³/h 小风量合理；直吹式除湿机空气回排同一房间，风机电机热+摩擦热全部留室内（得热≈输入电×3~3.4）。修复采用"Q_target 含 fan_power_w"。✅
2. **问题1 焓平衡口径**：hvac.py 显热口径 `-(shr·Q_total − fan)`，潜热仅经湿度方程；engine.py q_removal_corr 只回退 DEH 幻影热。温度方程不再含任何潜热项，焓平衡闭合。✅
3. **问题2 补测试**：test_02_physics.py TestSolarGeometry 含乌鲁木齐（太阳正午≈CST 09:50）与上海（≈12:06）用例，验证符号修复。✅
4. **问题6 数据来源**：JKM580N-78HL4-BDV 铭牌（V_mp=45.85V, I_mp=12.66A → 580.5W）写入 pv.py 注释。✅

### Git 状态

- 最近 commit：`2166319`（fix(review): latent-heat accounting, solar-time sign, DEH fan heat, TLPS/LCOE, PV nameplate — 8 files, +84/-32）
- 前置提交：`c2909cc`（docs(meta): 提交 REVIEW.md + 本 scratchpad 初稿）、`ca48275`（repo_sync scratchpad 同步）
- 工作区干净（修复全部提交）

---

## 6. 第二轮：全仓库四路并行审查（2026-08-16）

用户指令："review整个repo物理和能源和植物仿真潜在问题；兵分四路"。按现有 REVIEW.md 规则运行，四路并行 general agent：物理核心 / 设备层 / 植物层 / 能源调度。**只读审查，未改任何代码**（当前 REVIEW.md 未更新，用户选择直接运行）。

### 审查结论概览

**无 CRITICAL**。4 个 MAJOR + 跨路共性的 h_fg/L_v 失配 + 一批 MINOR/INFO。

| 级别 | 位置 | 问题 | 路径 |
|---|---|---|---|
| MAJOR | `example_lcoe_full.yaml:103`/`example_sweep.yaml:88`/`test_project.yaml:103` | `alpha_sc: 0.045` 为代码默认 `0.00045` 的 100×，年 PV 发电量高估 **1.68×**；I_mp=13.33/V_mp=46.0 未同步铭牌 12.66/45.85 | 能源 |
| MAJOR | `pv.py:34,52` / `project.py:229` | `beta_voc=-0.25` 按绝对 V/K 使用，铭牌 βVoc 为相对 −0.250%/K（≈−0.143 V/K@57.34V），高温衰减过度，年发电量低估 ~3.4% | 能源 |
| MAJOR | `hvac.py:54-70` + `project.py:400-404` | constant/table COP 模式无下限钳制，`cop_value<0` 静默把制冷变制热（Fail Fast 违反） | 设备 |
| MAJOR | `hvac.py:214-228` `size_hvac` | 设计感热负荷遗漏 DEH 净热排（≈P_comp+fan≈2.3kW，~21% 设计负荷），auto-size 低估铭牌 | 设备 |
| MAJOR | `engine.py:153` + `transpiration.py:73-76` | `van_henten` 蒸腾法 DEH 定容点 X_d=0.05 vs 运行时峰值 0.46 → 晚周期蒸腾 ~10× 定容点，DEH 严重欠配 | 植物 |
| MAJOR | `engine.py:308-311` vs `van_henten.py:110` | 生长模型光输入：参考/测试/demo 用 400 W/m²，引擎喂 87.5 W/m²（LED PAR），c_rad_phot=1e-8 校准基未验证；生长/蒸腾未互校准（water/鲜重 3.5 L/kg vs 真实 ~20 L/kg） | 植物 |
| MINOR（跨路共性） | `shr.py:32,60`/`hvac.py:90,163`/`dehumidifier.py:75,132` vs `engine.py:328` | 设备硬编码 `h_fg=2.5e6` vs 引擎温度相关 `L_v=2501−2.36T`（22°C≈2.449e6），DEH 凝结热差 ~2%（年 ~241 kWh，0.4%） | 物理/设备/植物 |
| MINOR | `psychrometrics.py:55-63` | `temp_rh_to_ah` 在 p_vapor≥P_atm 时静默返回负含湿量（100°C/100%RH → −71.6 kg/kg） | 物理 |
| MINOR | `shr.py:45` + `project.py:115` | `shr_BF=1.0` 时 `(1−BF)` 除零，配置无校验 | 物理 |
| MINOR | `hvac.py:49-53` | 冬季 T_cond−T_evap<0 时 Carnot COP 顶到 17.5，3kW 机组 Q_total~50kW（自由冷却上限失真） | 设备 |
| MINOR | `dehumidifier.py:140-146` | 停机后残留凝结热方向存疑（应再蒸发吸热而非继续放热） | 设备 |
| MINOR | `transpiration.py:89-90` | stomatal R_n 用 PAR-only 低估净冠层辐射 ~11-26%；定容回退 250 W/m² 与运行时不一致 | 植物 |
| MINOR | `transpiration.py:83` | γ=0.0655 kPa/K 硬编码（101.325kPa 真值≈0.0667，低 ~2%），忽略站压 | 植物 |
| MINOR | `van_henten.py:45` | CO₂ 摩尔体积固定 24.45 L/mol(25°C)，未按室温修正（~1.2% 偏高） | 植物 |
| MINOR | `project.py:203` | `k_van_henten` 单位注释错：`m²/(s·kPa)` 应为 `1/(s·kPa)` | 植物 |
| MINOR | `transpiration.py:59` | 暗期蒸腾=0（光因子二值化），609 运行 105 次 RH 钳 0%；真实夜间 ~5-15% | 植物 |
| MINOR | `sweep.py:345-352` | 无 PVBES 扫描分支忽略已配置 pv_area/battery 且 net_grid=0，LCOE 不含购电成本 | 能源 |
| MINOR | `project.py:290` + `sweep.py:101-140` | `pump_capital` 配置从未计入资本/LCOE，静默忽略 | 能源 |
| MINOR | `energy_system.py:30,73` vs `sweep.py:306-309` | 运维成本两套口径（0.01 vs 0.02+水+人工）；`pv.maintenance`/`battery.maintenance` 从未生效 | 能源 |
| MINOR | `pv.py:80`/`sweep.py:143-148` | LCOE 用首年电量，`degradation=0.004` 配置了但 year 从不传入，衰减未折现 | 能源 |
| INFO | `engine.py:677-679` | PVBES 块 try/except 软失败，LCOE/PV 指标静默缺失（Fail Fast 违反） | 能源 |
| INFO | `pv.py:77` | 无自遮挡/失配/BOS 损耗（eta_inv 常数 3%） | 能源 |
| INFO | `battery.py:38,45` | soc0=0.5 固定、年末 SOC 不收敛、无 TOU 谷充峰放套利 | 能源 |
| INFO | `grid.py:26` | <24 项 tariff 静默回退 0.10，未校验 24h 全覆盖 | 能源 |
| INFO | `pump.py:44-51` | PumpDevice 未在 engine 路径实例化，电耗/产热不参与房间热平衡 | 设备 |
| INFO | `weather_bridge.py:94,96-110` | Erbs 近地平线 cos_z 下限 1e-3 + kt 截断 → 日出日落 DNI 数千 W/m² 非物理（年影响 <1%） | 物理 |
| INFO | `psychrometrics.py:32-38` | Magnus 守卫 ±100°C 超有效范围 [−40,50]，0°C 以下无冰面分支（−20°C 高估 ~10%） | 物理 |
| INFO | `weather_bridge.py:77` | 方位角注释"from south, ±"与实现（北向 0-360°，正午 180°）不符 | 物理 |
| INFO | `engine.py:421-427` | 周期净生长为负时 X_d 仍上重置，静默增加生物量 | 植物 |
| INFO | `engine.py:127` | `transpiration.photoperiod_hours` 被 led 恒覆盖（死字段）；LED 整点截断 16.5→17h 与 daily 法 ÷16.5 有 ~3% 日水量偏差 | 植物 |

### 核查通过（第二轮独立复算确认）

- **物理**：Magnus p_sat(25°C)=3.168、0°C=0.611 ✓；含湿量/焓/露点/湿球 ✓；SHR BF-ADP 模型 ✓；envelope 方向/渗透 ✓；ODE 单位守恒（1000W×3600s=+1.0K@1000Wh/K）✓；weather_bridge 太阳时修复验证 ✓；POA beam 复算 690.3 vs 手算 691 ✓；Erbs 系数 ✓；Open-Meteo direct=BHI 约定处理正确 ✓；引擎焓平衡闭合差仅 = M_deh·(h_fg−L_v)。
- **设备**：Carnot COP 35/22→2.792 ✓；DEH SMER 凝水量 1.24 g/s ✓；上轮修复 1/2 验证无误；LED 拆分 ✓；lag 一阶指数 DC 增益=1 ✓。
- **植物**：vpd 法 1.09 kg/m²·16h ✓；stomatal P-M 双单位复算 λE=40.7 W/m² ✓；van_henten 与 reference 逐式一致、_demo X_d=0.0256 逐位 ✓；engine 潜热耦合闭合（除 h_fg/L_v 残余）✓；609 年水量 17.0 m³/收获 246 kg 干/4916 kg 鲜 ✓。
- **能源**：电池一天循环 SOC∈[0.1,0.9] 精确、库仑计数方向 ✓、throughput 公式 ✓；能量守恒 8760h 最大残差 3.55e-15 kW ✓；PV 铭牌复现 580.46W ✓、CF≈0.17 ✓；Shanghai TOU 24h 全覆盖 ✓；CRF(0.06,25)=0.0782 ✓；LCOE 复算 ✓；时间轴本地时对齐 ✓；engine 积分 kW·h 正确 ✓。

### 执行者反馈（第二轮）

1. **建议优先修复**（按影响排序）：能源 MAJOR-1（示例 YAML alpha_sc 100×，影响最大 1.68×，且三处 YAML 同病）→ 能源 MAJOR-2（beta_voc 单位）→ 设备 MAJOR-1（COP 负值防护，Fail Fast）→ 设备 MAJOR-2（size_hvac 漏 DEH 热）→ 植物 MAJOR-1（DEH 定容点 X_d）。
2. **跨路共性**：h_fg/L_v 统一（shr/hvac/dehumidifier 改用 `latent_heat_vaporization`）——三路同时报，修一处即可闭合。
3. 示例 YAML 失配需补 parity 测试（参照 test_sample_yaml_k_vpd_matches_code_default，覆盖 alpha_sc、I_mp、V_mp）。
4. REVIEW.md 可考虑在 Always flag 增加：温度系数单位（%/K vs 1/K vs V/K）、示例 YAML 与代码默认 parity、COP 负值防护、设计定容点与运行时量级一致性。

### Git 状态（第二轮）

- 本轮只读审查，无代码/文档变更，工作区干净。
