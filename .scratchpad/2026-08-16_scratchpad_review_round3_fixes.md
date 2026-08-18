# 2026-08-16 Scratchpad — 第三轮审查修复（9-subagent 三维审查 → 分批修复）

## 1. Background and Motivation

用户指令（原文）："请你全面review仿真模型；三个subagents检查物理公式模型准确性 三个subagents检查仿真链路和参数传递情况，三个subagents从用户角度检查这个架构的易用性"。

9 个并行 subagent 完成审查（维度1物理公式×3、维度2仿真链路×3、维度3用户易用性×3）。审查基准：现有 REVIEW.md（用户选择不更新）。随后用户指令（原文）："创建scratchpad，然后记录问题细节；修复计划层面按照维度和subagent顺序一点点解决问题；要保持做好一打处理，更新scratchpad，更新下一步todos，继续处理的循环"。

本文件 = 第三轮审查问题细节记录 + 修复循环执行看板。第二轮的旧 scratchpad（review_round2）四路审查及其 A/B/C/D 组修复已完成（pytest 197 passed），与本轮部分问题重叠，详见 §4 交叉引用。

## 2. Key Challenges and Analysis

- 总体结论：物理公式主路径正确、链路单位链闭合，但存在 2 个系统性缺陷（冬季 HVAC RH 崩塌、天气缓存参数泄漏）+ 一批"静默失效"配置（7 死字段 + 枚举零校验）。
- 跨维度交叉印证（同一问题被多 subagent 独立发现 = 高置信）：
  - HVAC Carnot COP 低提升抬升（Devices MAJOR-1 ⚡ Engine B1）
  - pump_capital / pv.battery.maintenance / transpiration.photoperiod_hours / DEH 焓效率四件套死字段（Engine M2 ⚡ Config MAJOR 1-5 ⚡ PVBES）
  - 天气缓存 tilt/azimuth 泄漏（PVBES BLOCKING ⚡ Engine MINOR）
  - pv_area_m2>0 门控 → LCOE 不出现（Engine M1 ⚡ YAML BLOCKING-1 ⚡ Docs MAJOR）
  - power_w 被 auto_deduce 静默覆盖（Config MAJOR-7 ⚡ YAML MAJOR-4）
  - quickstart 文件名不匹配（CLI BLOCKING-2 ⚡ Docs BLOCKING）
- 与第二轮（review_round2）重叠项：h_fg 死参数（本轮多个 MINOR）、sweep building-only 分支丢弃 PV/电池（本轮 PVBES MAJOR = 旧 MINOR-17）、pump_capital（旧 MINOR-18）、maintenance 两套口径（旧 MINOR-19）、PV 无系统损耗（旧 INFO）、grid <24 项静默回退（旧 INFO）、stomatal R_n PAR-only（旧 MINOR-12）、γ 硬编码（旧 MINOR-13）、CO₂ 摩尔体积（旧 MINOR-14）。**第二轮未动的 MINOR-8（负含湿量）、MINOR-10（COP 顶到 17.5）、MINOR-11（DEH 停机残留热）、MINOR-12/13/14/16（植物）在本轮被独立重新发现。**

## 3. High-level Task Breakdown（修复循环计划：按维度 → subagent 顺序，每批"修复并行组 + 独立验证"）

**修复循环标准模式**（每批次均执行）：
1. **阶段 A — 修复执行**：本批次问题按文件依赖关系拆成 2~3 个并行组，各派 1 个 `general` subagent 执行（互不触及同一文件，避免冲突）。
2. **阶段 B — 独立验证**：本批次修复落盘后，派 1 个独立 `general` subagent 验证（无执行权/只读），按 REVIEW.md 规则复查：公式物理正确性、单位链闭合、fail-fast、死字段清理完整性、未引入回归（运行相关 pytest）。
3. **阶段 C — 收口**：验证通过 → 更新 §4 看板 → 更新 todos → 下一批；验证发现问题 → 回到阶段 A 修复后重验。
4. 批次 3/6/9/10 附带的"维度全量 pytest"由验证 subagent 一并执行（D1/D2/D3 全量回归）。
5. 所有 subagent 只读+可运行测试，不直接改 src/（改动由规划者统一落盘），避免并行写冲突。若 subagent 报错，由规划者定夺修改后落盘。

| 批次 | 覆盖（问题清单） | 阶段A 并行修复组（各 1 subagent） | 阶段B 验证 subagent 检查点 | 状态 |
|------|------|------|------|------|
| 0 | 记录 | — | — | ✅ 本文件 |
| 1 | S1 Physics（P1-1~8） | 组A: psychrometrics.py 冰面/沸点/露点（P1-1,3,4）；组B: envelope.py 渗透潜热能量显式化（P1-2，注意 ode/engine 调用链）；组C: shr.py + ode.py（P1-5,6,7,8） | 冰面切换 −10/−45°C 验算、渗透能量闭合、SHR 平滑无突变、ode 钳位一致性、pytest | ✅ 已完成并通过独立验证（P1-1~8 全部 8/8） |
| 2 | S2 Devices（P2-1~10） | 组A: hvac.py（P2-1,2,3,7）；组B: dehumidifier.py（P2-2,4,5,6,10）；组C: lag.py + led.py（P2-8,9） | Carnot COP 最小提升（T_ext=5/25→COP≤6）、DEH 冷凝热含渗透项、制热 COP 随 T_ext、死参数清零、pytest | ✅ 已完成并通过独立验证（P2-1~10 全部 10/10） |
| 3 | S3 Plants（P3-1~14） | 组A: transpiration.py 标定统一（P3-1,2,3,5,6,7,8,9,10）；组B: van_henten.py（P3-11,12,13,14）；组C: engine.py DEH auto-size 峰值口径（P3-4） | 6 方法同点收敛量级（24→同水平）、DEH 选型匹配峰值、per_plant=0 fail-fast、D1 全量 pytest | ✅ |
| 4 | S4 Engine（P4-1~18） | 组A: engine.py 核心（P4-1,2,4,6,7,8,9,10,11）；组B: presets.py C_z + pump_capital 接通（P4-3,5）；组C: weather_bridge + battery + project 小项（P4-12~18） | RH 崩塌复测（上海2023：RH 分布/最低值改善）、能量平衡闭合、无 PV 时经济块输出、pytest | ✅ 2026-08-16 已完成并通过独立验证（P4-1~18 中 12 项直接修复；P4-3/12/13/14→批次5、P4-15/17→批次6） |
| 5 | S5 配置契约（P5-1~16） | 组A: project.py 死字段清理+method 白名单（P5-1~5,7,8,9,13,14,15,16）；组B: presets.py + sweep.py 校验（P5-6,10,11,12） | method 非法值 fail-fast、死字段移除后 YAML 兼容、cop_table/tariff 守卫、pytest | ✅ 2026-08-16 已完成并通过独立验证（P5-1~16 全部 16/16；P5-12 实测已满足无 diff；阶段B 发现 P5-6 告警噪音已修——显式非默认 power_w 才 warn、round-trip 不误报） |
| 6 | S6 PVBES/缓存（P6-1~10） | 组A: weather_bridge.py 缓存键（P6-1,8,10）；组B: sweep.py（P6-2,3,4,9）；组C: energy_system.py + pv.py + battery.py（P6-5,6,7） | tilt=20 vs 55 缓存返回不同数组（重跑实测）、building-only 保留固定 PV、LCOE 口径注释、D2 全量 pytest | ✅ 2026-08-16 已完成并通过独立验证 |
| 7 | S7 CLI（P7-1~15） | 组A: 顶层包 src→vfed 重命名（P7-1，波及全部内部导入+pyproject）；组B: cli.py 健壮性+help+进度（P7-3,4,5,6,7,8,9,11,12,13,15）；组C: evaluator.py + README quickstart 同步（P7-2,10,14） | `vfed --help` 可启动、quickstart 两命令可跑通、sweep 进度/错误提示、pytest | ✅ 2026-08-16 已完成并通过独立验证（P7-1~15 全部 15/15；隔离 venv 污染回归通过；P7-11 补修 evaluator 透传 dry_matter_fraction） |
| 8 | S8 YAML 示例/产物（P8-1~15） | 组A: 3 示例 YAML 补 pv_area/注释（P8-1,2,4,6）；组B: project.py 注释+命名（P8-3,7,8,13,14,15）；组C: 校验补充+tariff 落地（P8-5,9,10,11,12） | example_lcoe_full evaluate 出现 LCOE/PV 输出、design new 产物带注释、pytest | ✅ 2026-08-16 已完成并通过独立验证（P8-1~15 全部 15/15；遗留1 test_web_yaml 删键+29→24 值修复、遗留2 index.html C_z 499597→200000；223 passed + 56 passed） |
| 9 | S9 文档（P9-1~12） | 组A: README quickstart + sweep 演示改例（P9-1,2,6）；组B: 结果解读+故障排除章节（P9-3,4,5）；组C: 杂项+CSV/result 单位（P9-7,8,9,10,11,12） | README 步骤逐条可执行、双语同步、D3 全量 pytest | ✅ 2026-08-16 已完成并通过独立验证（P9-1~12 全部 12/12；223 passed；src/ 零残留（活动代码）；双语 README 一致） |
| 10 | 收尾 | 全量 pytest + 能量基准对比（修复前 vs 后同项目输出对比） | 独立综合验证 subagent：全量 pytest + 抽查修复点 + 结果汇总报告 | ✅ 2026-08-16 收尾完成（全量 pytest 223 passed；能量基准对比通过——preset_609/上海2023 RH 分布 <50%=1619h/<30%=514h/<10%=11h/min RH=7.63 与 P4-1 修复后基线完全一致；Annual load 67128 kWh/yr、LCOE 0.5223 与批次4 冒烟记录 ~1% 差异为 example_lcoe_full vs preset_609 配置差异，非回归） |

修复优先级总纲（P0 修一个救一打）：① hvac.py COP 最小提升约束（同时解决 Devices MAJOR-1 与 Engine B1）；② weather_bridge 缓存键含 tilt/azimuth/tz；③ pyproject 顶层包 src→vfed + README quickstart 文件名；④ transpiration.method 白名单校验 + vpd/van_henten 标定；⑤ engine pv_area 门控 + 示例 YAML 补字段；⑥ 死字段删除/接通。

## 4. Project Status Dashboard — 第三轮审查问题清单（9 路全量）

### 维度 1：物理公式模型准确性（S1/S2/S3）

#### S1 Physics（psychrometrics.py / shr.py / envelope.py / ode.py）— 审查人 subagent-1

| # | 级别 | 位置 | 问题 | 修复状态 |
|---|------|------|------|---------|
| P1-1 | MAJOR | psychrometrics.py:52 | 亚零度用水面 Magnus（17.27/237.3），应切冰面（22.587/273.86）。−10°C 偏高10%，−45°C 偏高49% → 冬季渗透湿负荷系统性高估 | ✅ |
| P1-2 | MAJOR | envelope.py:72-87 + ode.py:5 | 渗透只返回 (Q_sens_W, M_lat_kgs)，无潜热能量项。验算：潜热≈1311W=显热(335W)的4倍，可能被调用方静默丢失，能量守恒不闭合 | ✅ |
| P1-3 | MINOR | psychrometrics.py:37-38,119-122 | 沸点附近 W_sat 变负（99.9°C→−121.9 kg/kg）无防护 | ✅ |
| P1-4 | MINOR | psychrometrics.py:78-86 | 露点反演仅 T_dp≥0°C 有效（冰面系数缺失） | ✅ |
| P1-5 | MINOR | shr.py:35 | h_fg=2.5e6 死字段与注释（"~22C"）不符（实际 2.449e6），已弃用应删 | ✅ |
| P1-6 | MINOR | shr.py:43-69 | T_adp≈T_dp 时 SHR 刀刃式突变（1.0→0.66，供风温差 0.1°C 即翻转）→ 除湿启停振荡 | ✅ |
| P1-7 | MINOR | ode.py:49-53 | 温度钳位 [−20,60] 与发散检查 ±100°C 不一致，60~100°C 能量静默丢弃 | ✅ |
| P1-8 | MINOR | ode.py:77-85 | 饱和钳位用旧 T_z；T_z=None 时静默跳过，RH>100% 不防护 | ✅ |

#### S2 Devices（hvac.py / dehumidifier.py / led.py / compressor.py / pump.py / lag.py）— 审查人 subagent-2

| # | 级别 | 位置 | 问题 | 修复状态 |
|---|------|------|------|---------|
| P2-1 | MAJOR | hvac.py:46-53 | Carnot COP 分母 0.1K 下限+50 上限 → 低提升工况抬至非物理高值。验算：T_ext=5/T_z=25 → COP=17.5（真实 4~5，高估3.5倍）；温和季 15/22.5 → 6.5（高估40%）。应加最小提升约束 T_cond−T_evap≥5~8K | ✅ 修复：min-lift=5K + 最终 COP 上限 4.5（hvac.py:32-33,76-77）；验算 5/22.5→4.5、15/22.5→4.5、35/22→2.79 不变，全带 ∈[2.79,4.5] |
| P2-2 | MAJOR | dehumidifier.py:137 + hvac.py:222-227 | DEH 冷凝热只与蒸腾潜热对消，渗透/透湿水分的冷凝热未计入 HVAC 设计负荷（609 设计点≈2kW，占 q_sens~15%；高 ACH 地区数 kW） | ✅ 机制接线完成：size_hvac 新参 deh_latent_residual_w；engine m_transp 块上移全模式可用 + 残余项 max(0, M_deh_design−m_transp)·L_v。⚠️ 量级注：默认预设下 vpd 蒸腾 2.08e-3 已超 DEH 容量 1.24e-3 → 残余 0W；仅 auto_size 时 ≈2.8kW。"~2kW@609" 注释与当前 k_vpd=5e-5 标定不符，待批次3（P3-2 蒸腾标定）后统一复核注释数值 |
| P2-3 | MINOR | hvac.py:82-83 | 制热 COP 恒 3.0 不随 T_ext 退化（−10°C 真实 1.8~2.0，冬季制热电量低估 20~40%） | ✅ 修复：_cop_heat_at Carnot 制热缩放（EN 14511 A7/W35 额定点），−20→1.76/−10→2.10/0→2.62/15→4.13/25→5.0(clamp) |
| P2-4 | MINOR | hvac.py:92、dehumidifier.py:75 | 死参数 h_fg=2.5e6（实际用 latent_heat_vaporization(T)） | ✅ 修复：两处 h_fg 参数与 self.h_fg 删除；dehumidifier 连带删 efficiency 死参数；EnthalpyEfficiency 类保留；残留仅 transpiration.py:57（P3-6 范围）+ psychrometrics 湿球局部变量（合法） |
| P2-5 | MINOR | dehumidifier.py:138 | SMER 若含风机则 P_ref 反推后再加 fan 双重计入 ~2% | ✅ 文档化：SMER 明确为压缩机输入基准，风机单独计量不双计；模块 docstring/smer 注释/size_deh docstring 三处写明换算公式 |
| P2-6 | MINOR | dehumidifier.py:150-151 + hvac.py:179-180 | Q/M 独立滞后 τ 不同 → 瞬态"有热无湿"（dt=60s 时 exp(−0.667)≈0.51 误差真实存在） | ✅ 修复：DEH Q_act=M_act·L_v+Q_sens_act 由 M 推导（dehumidifier.py:168-170），恒等式行差 ~1e-13；稳态零变化。HVAC 独立滞后保留（物理正确：潜热排室外冷凝器） |
| P2-7 | MINOR | hvac.py:154,184 | 压缩机关闭时风机同时停机（真实机组风机常续转） | ✅ 注释化：P2-7 简化说明（~70W <1%，保留低成本模型） |
| P2-8 | MINOR | lag.py:31 | 上升/下降按数值方向选取，有符号量（制冷 Q<0）是隐性陷阱 | ✅ 修复：abs(target)>=abs(current) 判断（lag.py:35-36）；τ_rise==τ_fall 时 200 步随机游走逐位一致 |
| P2-9 | MINOR | led.py:45,81 | heat_fraction=1.0 忽略 2~5% 光合固碳 | ✅ 注释化：led.py:45-48 说明（2-5% 固碳、config-only 可下调 0.95-0.98），数值不变 |
| P2-10 | MINOR | dehumidifier.py:143 | eta 命名与弃用 EnthalpyEfficiency 同名、不含风机功率 | ✅ 修复：改名 latent_cop（满负荷 1.3606）+ 保留 "eta" 弃用别名 |

#### S3 Plants（transpiration.py / van_henten.py）— 审查人 subagent-3

| # | 级别 | 位置 | 问题 | 修复状态 |
|---|------|------|------|---------|
| P3-1 | MAJOR | transpiration.py:50,86 | k_van_henten=4e-4 过高：收获期 X_d=0.68 → 616 W/m²、14.5 L/m²/day，是可用辐射(87.5W/m²)的 ~7 倍，物理不可能（依赖 DEH 冷凝热正反馈维持）。应取 k≈7e-5 或加辐射上限 | ✅ 4e-4→**1e-4**（transpiration.py + project.py 同步）：按实际 30 天周期收获 X_d≈0.45 反标定，收获期 λE≈102 W/m²（与 vpd 法 113 同水平），周期均值 ≈50 W/m²；不加辐射钳位 |
| P3-2 | MAJOR | transpiration.py:43-49 | vpd 标定 k=5e-5 刻意偏离真实植物需水 3.4 倍（注释自述 w/f≈5.8 vs 真实~20 L/kg）→ DEH 选型与潜热能耗系统性低估。应记录为已知偏差 | ✅ 保留 5e-5 + 偏差量化注释：609/2025 实测 k=6e-5 即反馈崩塌（harvest→0），真实 20 L/kg 需 k≈1.5e-4 不可达；w/f≈6.3 已知低估 3.2x 显式记录，根因=生长模型产量膨胀 ~2x |
| P3-3 | MAJOR | transpiration.py:52-54 | stomatal 默认 g=1e-3 m/s（r_s=1000 严重胁迫值），输出偏低 4~5 倍，与 vpd 法不可比 | ✅ g=1e-3→**1e-2**（r_s=100 健旺冠层；transpiration.py + project.py + 3 示例 YAML 同步），设计点 λE 24→102 W/m² |
| P3-4 | MAJOR | engine.py:119-152 | van_henten 蒸腾 DEH auto-size 用周期均值，收获期峰值超配 2.3 倍（晚周期 RH 设定值失守） | ✅ auto-size 改**周期峰值**定容（pre-run `m_peak=max(...)`）：k=1e-4 时 P_ref≈5.77kW、m_peak=2.07g/s@X_d=0.495；蒸腾主导季节收获期 RH 守住设定值（0% 小时>68%）。⚠️ 夏季室外渗透湿负荷超 DEH+HVAC 容量属既有物理极限（vpd 法更差），非本项引入 |
| P3-5 | MINOR | transpiration.py:37-41 | per_plant 默认 plant_count=0 静默零蒸腾（RH 塌陷、DEH 永不运行、无告警） | ✅ fail-fast：plant_count≤0 抛 ValueError（含字段名提示）；**暗期优先**：light_factor≤0 先返回 0.0 再校验（不误伤 test_method_zero_in_dark） |
| P3-6 | MINOR | transpiration.py:57 | h_fg=2.5e6 死字段 | ✅ 删除（全仓最后残留清理；grep 确认仅剩 psychrometrics 湿球迭代合法局部变量） |
| P3-7 | MINOR | transpiration.py:93,96 | γ=0.0655、ρ=1.2 kg/m³ 硬编码 20°C（与 L_v(T_z) 不同温 → ~2% 偏差）；应复用 envelope 的 rho_air/P_atm | ✅ γ 同温化：`cp·101.325/(0.622·L_v(T_z)·1000)`（22°C≈0.0668，λE 变化<1%）；ρ=1.2 注释文档化（P_atm 未透传 ~±1%） |
| P3-8 | MINOR | transpiration.py:99-100 | stomatal R_n 用 PAR-only（LED 电输入 160W/m² 的 55%），漏 45% 灯体散热/再辐射 → 辐射项低估 ~30-50% | ✅ 保留 PAR-only + 注释：非 PAR 45% 主要对流进入空气非辐射到冠层，全电输入反而高估；气动项主导部分抵消偏置 |
| P3-9 | MINOR | transpiration.py:87-90 | 全方法用空气 VPD 代替叶-气 VPD（T_leaf≈T_air 隐含），光下蒸腾略低估；应注释 | ✅ 模块 docstring 加 T_leaf≈T_air 一阶近似说明；顺带修正 L9 陈旧笔误 E=k_vpd×X_d → k_van_henten |
| P3-10 | MINOR | transpiration.py:59-67 | step() 的 dt 参数 6 种方法均未使用（返回瞬时速率），签名易误当积分器（重复乘 dt 双计） | ✅ 签名保留 + docstring 注明返回瞬时速率勿再乘 dt |
| P3-11 | MINOR | van_henten.py:51 | CO₂ ppm→kg/m³ 用 24.45 L/mol 固定值，未随 T/P 修正 → 高估 ~1.1% | ✅ T/P 相关化：`__init__` 加 P_atm=101.325 + `_co2_density(T)`（V_m=22.414·T/273.15·101.325/P）；22°C ρ=1.4534e-3（旧 1.4397e-3，**+0.95%**——审查方向更正：固定值实为低估非高估） |
| P3-12 | MINOR | van_henten.py:100 | 呼吸 2^(0.1T−2.5)（Q10=2, T_ref=25°C）无方程注释 | ✅ Q10 注释（van't Hoff, Q10=2, T_ref=25°C, Thornley & Johnson 2000） |
| P3-13 | MINOR | van_henten.py:84 | X_d 回退值 0.01 vs initial_dry_weight=0.001（高 10 倍），engine 总会传入故仅直接调用触发 | ✅ 行号更正：实际在 transpiration.py:84；回退值 →**0.02**（对齐 initial_dry_weight 新默认） |
| P3-14 | MINOR | van_henten.py:109-118 | _demo 声称"与参考脚本精确一致"不可验证（输入不同：恒定 vs OriginGrow.xlsx 时变）；初始干重 0.001 kg/m² 偏低（前 3 天生长极慢） | ✅ _demo docstring 如实化（自洽快照非参考 parity）+ X_d=0.02；project.py initial_dry_weight **0.001→0.02**（移栽苗真实 15-80 g/m²；年干产 246.5→260.8 kg +5.8%，带 [180,350] 内） |

### 维度 2：仿真链路与参数传递（S4/S5/S6）

#### S4 Engine 枢纽（engine.py + 其调用链）— 审查人 subagent-4

| # | 级别 | 位置 | 问题 | 修复状态 |
|---|------|------|------|---------|
| P4-1 | BLOCKING | hvac.py:153-170,46-53 + shr.py:43-69 + engine.py:34-56,384-400 | **冬季/夜间 RH 崩塌**：COP 封顶 50 → Q_total 27-150kW → M_target 无盘管冷凝速率上界 → 单步清空房间水汽库存(2.5-3kg)。实测上海2023：RH 最低 1.8%，全年 2907h<50%、716h<30%，156 次 floor-clip（14kg 幻影凝结水）。DEH 运行/能耗系统性低估，RH/VPD→transpiration→SHR 全链失真。建议：RH<55% 时 SHR=1 停除湿 + M_target 物理上界 + COP 现实天花板 | ✅ hvac.py 三管齐下：(a) `_apply_rh_guard`（SHR_RH_GUARD=55% 停除湿，band 3% 线性混合）+ (b) `_COIL_CONDENSE_K=5e-7`（3000W→1.5 g/s 盘管冷凝上界，`M_target=min(Q_lat/L_v, cap)`）+(c) COP 4.5（P2-1 已修）+ (d) `_limit_removal_by_inventory` 加步内 E_trans/M_inf/M_perm 净源补给。project.py HVACConfig 新字段 shr_rh_guard/rh_guard_band/coil_condense_max_gps。**复测（609/上海2023）：<50% 2920→1619h（-45%）、<30% 811→514h、<10% 81→11h、min RH 4.27→7.63**。⚠️ 暗期透蒸 0.15×（transpiration.py）为跨组暂缓项（仅它能把 <30%→0） |
| P4-2 | MAJOR | engine.py:630 | pv_area_m2>0 门控吞掉整个经济/储能块：电池-only/纯建筑配置时 LCOE/capital/grid 指标全缺失，而 sweep 路径正常 → evaluate 与 sweep 口径不一致 | ✅ 门控改 `pv_area_m2>0 or battery_kwh>0` + else 分支 grid-only 经济（_total_capital/_annualized_capital/_compute_lcoe，15 键输出：lcoe/specific_cost_per_kg/capital_total/annual_om/grid_import_kwh=Σload 等，对齐 sweep.py:361-372 口径） |
| P4-3 | MAJOR | project.py:299 + sweep.py:101-112 | pump_capital 从未被读取 → 资本成本静默低估 | → 批次5（P5-1 同项，sweep._total_capital 接入） |
| P4-4 | MAJOR | engine.py:732-734 | PVBES 块 except Exception 静默降级，任何 PV/电池 bug 让经济指标静默消失，与 fail-fast 相悖 | ✅ 嵌套 try：非关键明细（pv_power/free_energy/grid_independence）降级写 `energy_system_detail_status`；核心键（lcoe/capital_total/annual_om/annual_grid_cost_net/total_electricity_cost）缺失→`raise RuntimeError(...) from e`（CLI/agent 映射 E101） |
| P4-5 | MAJOR | presets.py:30 + engine.py:355-357 | 609 校准 C_z=499,597 Wh/K 热状态准冻结，制热模式全年几乎不启动（冷季以 COP 6-16 制冷维持 18°C），冷区 LCOE 对比失真 | ✅ presets.py C_z **499,597→200,000** Wh/K（430m³ 水当量→物理合理带 100-300 kWh/K 中点）+ docstring 校准边界声明；3 个 YAML（test_project/example_lcoe_full/example_sweep）L18 同步。验算：年负荷 67,233kWh∈[45,75k]、T_z min 17.99、制热 0→~27h、wf 5.89 |
| P4-6 | MINOR | engine.py:271-274 | surface_pressure 用 np.nanmean 吞 NaN（其余数组 fail-fast）；全 NaN → P_atm=NaN 污染全链 | ✅ `np.isfinite().all()` 校验 fail-fast + `np.mean`（NaN 注入实测抛 ValueError） |
| P4-7 | MINOR | engine.py:114,105 | DEH auto-size W_ext/W_z 用默认海平面压力，未传 P_atm（高海拔低估） | ✅ L115/L191 设计点 `temp_rh_to_ah(..., pressure_kpa=P_atm)`（运行期 L375/L451 已传） |
| P4-8 | MINOR | engine.py:293 | int(round(crop_cycle_days)) 银行家舍入（30.5→30）不对称截断 | ✅ 时间基收割：harvest_hours/next_harvest_h + `if (h+1)>=next_harvest_h`；预跑 `int(days*144+0.5)` 同步。30.5d：预跑 4392 步/12 次收割（分叉消除） |
| P4-9 | MINOR | engine.py:176-177,206-208 | run() 原地改写调用方 project（写回 auto-size 的 P_ref_w/P_rated_w） | ✅ 写回保留（load-bearing：sweep CAPEX 读取）+ docstring 副作用声明 + SimulationResult 新增 `sizing` 字段（hvac_P_rated_w/hvac_P_rated_heat_w/deh_P_ref_w/deh_M_design_kgs） |
| P4-10 | MINOR | engine.py:351-353 | LED 光周期整小时量化，photoperiod_hours 小数部分(16.5h)丢失 | ✅ `led.is_light(hours[h])`/`led.step(hours[h])` 分数小时（hour_of_day 保留供 typical_load 索引）；is_light(22.49)=T/(22.51)=F |
| P4-11 | MINOR | engine.py:359-360 | auto_deduce=False 时 light_wm2 仍用 ppfd_target/par_factor，与实际 power_w 对应的 PPFD 不一致 | ✅ led.py 新增 `par_wm2` 属性=power_w·efficacy/par_factor/covered_area；engine 三处（预跑/else 选型/运行期）统一用 par_wm2。auto=87.53、manual(5400W)=65.65 |
| P4-12 | MINOR | project.py:208 vs 161 | transpiration.photoperiod_hours 与 led.photoperiod_hours 双份配置（engine 用 led 的）→ sweep 扫 photoperiod 不同步 | → 批次5（P5-3 同项，删 transpiration 侧字段） |
| P4-13 | MINOR | project.py:141-144 | DEH eta_ref/eta_max/ah_min/ah_ref 死字段（EnthalpyEfficiency 已弃用） | → 批次5（P5-4 同项，契约删除/标记废弃） |
| P4-14 | MINOR | project.py:243,256 | pv.maintenance / battery.maintenance 传参后无消费（O&M 走 opex.maintenance_pct） | → 批次5（P5-2 同项） |
| P4-15 | MINOR | project.py:255 + battery.py:29 | battery.cycle_life 存储但无电池更换成本模型；self_discharge 恒 0 不可配 | ✅ battery.py cycle_life/maintenance 注释；energy_system.calculate_metrics 返回 battery_life_years（=cycle_life/annual_cycles）+ battery_replacement_annual（<lifetime 折现年金化）；E_bat=20 → life≈20.5yr 25yr 内 1 次更换；权威接入经 sweep _annualized_capital min() |
| P4-16 | MINOR | weather_bridge.py:244 | 本地时转换使窗口偏移 tz_hours：缺 1/1 0-7 时数据、8h 标为次年 1 月 | ✅ 查询窗扩 [(year-1)-12-31,(year+1)-01-02] + `tz_convert(timezone(timedelta(hours=tz_hours)))` + 切片对齐 + `tz_localize(None)` 落盘 naive 本地 + 陈旧检测（首行≠year-01-01 或 len≠(365\|366)\*24→warn+重取）+ 离线 fallback 返回旧缓存。实测缺 1/1 0-7h/幻影 2024-01-01 均修复，非边界日逐值 0 变化 |
| P4-17 | MINOR | weather_bridge.py:194-199 | 缓存 CSV 已有 poa_radiation 时跳过 add_poa，tilt/azimuth 变更后 POA 过期复用 | → 批次6（P6-1 同项合并：缓存键含 tilt/azimuth/tz） |
| P4-18 | MINOR | battery.py:38 | SOC 固定从 0.5 起、年末不回 0.5，年能量平衡忽略 ~E_bat·Δsoc（实测 ~4 kWh） | ✅ 年末回补：soc_target=clamp(soc0)、recon_grid_kwh（正→import/负→export）+双侧同增减；能量平衡精确闭合（|误差|=5e-12）、soc[-1]=0.5、E_bat=20→recon 8.79kWh |

#### S5 配置契约（project.py / presets.py / 示例 YAML）— 审查人 subagent-5

| # | 级别 | 位置 | 问题 | 修复状态 |
|---|------|------|------|---------|
| P5-1 | MAJOR | project.py:299,325,468 | 死字段 pump_capital（同 P4-3） | ✅ 注释+接入：sweep._total_capital/_annualized_capital 加 "Pump" 项（dep=15 CRF），pump=2000→total+2000、annualized+205.93 |
| P5-2 | MAJOR | project.py:243,256 | 死字段 pv.maintenance / battery.maintenance（同 P4-14） | ✅ 删除字段+engine.py:746/sweep.py:180 传参+2 示例 YAML 键；O&M 统一走 opex.maintenance_pct |
| P5-3 | MAJOR | project.py:208 | 死字段 transpiration.photoperiod_hours（engine 读 led 的，同 P4-12） | ✅ 删除字段+test_04 round-trip 同步 |
| P5-4 | MAJOR | project.py:141-144 | 死字段 deh 焓效率四件套（同 P4-13） | ✅ 删除字段+3 示例 YAML 各删 4 键（eta_ref/eta_max/ah_min/ah_ref） |
| P5-5 | MAJOR | project.py:390-395 | **transpiration.method 零校验**：非法值静默零蒸腾 → 湿度源归零、DEH 容量不足（全契约最贵静默失败）。应对齐 cop_mode 白名单 | ✅ from_dict 白名单（constant/daily/per_plant/vpd/stomatal/van_henten），bogus→ValueError；test_04 改写为 _rejected；模型层 return 0.0 保留纵深防御 |
| P5-6 | MAJOR | led.py:57-60 + 示例 YAML:70 | power_w:1300 被 auto_deduce:true 静默覆盖为 7200W（5.5倍），609 实际 LED 负荷是声明值 5.5 倍，用户改 power_w 无反应 | ✅ 注释+from_dict 告警（auto_deduce=True 且 power_w 显式非默认 1300 时 UserWarning）；led.py __post_init__ 注释；round-trip 不误报（阶段B 发现噪音已修） |
| P5-7 | MINOR | project.py:168 | led.spectrum 未校验，非法值静默回退 white 4.57 | ✅ from_dict 白名单（white/rb_3to1/rb_4to1/rb_2to1），purple→ValueError |
| P5-8 | MINOR | project.py:439-440 | hvac.cop_table 传 list 崩溃 AttributeError（无 isinstance 守卫） | ✅ isinstance(dict) 守卫+友好报错，list→ValueError |
| P5-9 | MINOR | project.py:260-268 + grid.py:22-26 | tariff.hourly_prices 长度未校验，<24 静默回退 0.10（实测 12 值 13:00-23:00 全按 0.10） | ✅ _tariff 精确 24 校验，非 24→ValueError；3 示例 YAML 均 24 值 |
| P5-10 | MINOR | project.py:276 + sweep.py:191 | space.parameter_ranges 形状未在加载时校验（缺 step 运行时才 ValueError） | ✅ sweep._validate_ranges 形状预校验（dict/[min,max,step]/整数步数），含参数名报错 |
| P5-11 | MINOR | sweep.py:87-91 + project.py | capital.mode 未校验，拼错静默落 legacy_fallback（组件成本变 0） | ✅ sweep._VALID_CAPITAL_MODES + _resolve_capital 入口白名单，per_wt→ValueError |
| P5-12 | MINOR | sweep.py:245-252 | 单点路径跳过 objective 校验（与多点不一致） | ✅ 无 diff：objective 校验（L268-272）天然先于单点分支（L275-282），实测单点+非法 objective 已抛 ValueError |
| P5-13 | MINOR | project.py:365-374 | _tariff legacy 分支不校验未知键（peak_price 绕过 sub()） | ✅ legacy 键白名单（peak_price/normal_price/valley_price/peak_hours/valley_hours/export_price），pke_hours→ValueError |
| P5-14 | MINOR | project.py:9-21 | strategy docstring 仍描述不存在的 4 模式与 ScenarioConfig（契约层已拒绝） | ✅ docstring 改 "NOT implemented"，明确 strategy 键被拒 |
| P5-15 | MINOR | project.py | hvac.deadband_c/deh.T_mean/battery.cycle_life 等缺单位注释 | ✅ deadband_c °C/T_mean·T_std °C/W_mean·W_std kg/kg/cycle_life 循环数注释补全 |
| P5-16 | MINOR | project.py | hvac.heat_mode 未校验（≠heat_pump 静默按电阻加热） | ✅ from_dict 白名单（heat_pump/resistive），plasma→ValueError |

#### S6 PVBES/扫参（pv.py / battery.py / grid.py / energy_system.py / sweep.py / result.py + weather_bridge）— 审查人 subagent-6

| # | 级别 | 位置 | 问题 | 修复状态 |
|---|------|------|------|---------|
| P6-1 | BLOCKING | weather_bridge.py:42-44,194-199 | **缓存键仅 lat/lon/year，命中且含 poa_radiation 时跳过重算**。实测 tilt=20 与 55、tz=8 与 5 返回数组逐元素相同 → 改 tilt/方位角/时区后重跑静默沿用旧 POA，PV 发电量与 LCOE 排序失真。应将 tilt/azimuth/tz 纳入缓存键或元数据校验 | ✅ `_cache_path` 文件名纳入 tilt/azimuth/tz（weather_{lat}_{lon}_{year}_t{tilt}_a{azimuth}_z{tz}.csv）+ `_legacy_cache_path` 旧名回退；legacy 命中且 aligned 时 drop poa/direct/diffuse 3 列从 GHI Erbs 重算（warn）；离线 fallback 同样重算。实测 tilt=20 vs 55 数组不同（max|Δ|=1115.5 W/m²） |
| P6-2 | MAJOR | sweep.py:348-359 | 仅扫 building 参数分支静默丢弃固定 PV/电池（_total_capital(p,0,0)+net_grid_cost=0），与单点路径行为不一致 | ✅ else 分支评估固定 pv_area_m2/battery_kwh（惰性 _build_energy_system）；row 对齐 PVBES schema（+7 capital_* 键 + 4 PVBES 键）；实测 building-only+固定 pv=80/bat=50 → lcoe 0.6025/capital 13046.51 与单点 engine 完全一致；无固定 PV 时 net_grid=0 基线不变 |
| P6-3 | MINOR | sweep.py:315 + _compute_lcoe:143-148 | LCOE 分母=建筑年负荷（设施每 kWh 全成本），非发电侧 LCOE；应改名 cost_per_kwh_consumed 或文档化 | ✅ _compute_lcoe docstring 改 "Levelised facility cost per kWh of building load"（lcoe 列名保留） |
| P6-4 | MINOR | sweep.py:302-305 vs project.py:51 | 中寿年 12 输出 × 15 年折旧口径不匹配；电池更换成本从不建模 | ✅ _annualized_capital 加 battery_life_years: Optional[float]=None，Battery dep=min(配置, life)；PVBES 分支传 m.get("battery_life_years")；609（life≈78）min() 零变化 |
| P6-5 | MINOR | project.py:243,256 + energy_system.py:30 | pv/battery.maintenance 死参数；EnergySystem 与 sweep 两套资本口径易分叉 | ✅ energy_system.py docstring/字段/成本段标注 ALTERNATIVE/legacy scope（权威 LCOE 在 sweep/engine） |
| P6-6 | MINOR | energy_system.py:58,90 | TLPS 定义为购电小时占比（非能量加权），名称误导 → 建议 grid_dependency_pct | ✅ tlps→grid_dependency_pct（=mean(grid_import>0)*100）+ 新增 lpsp_pct（能量加权）；tlps 保留别名键。实测 A=100/E_bat=20：gdep 74.7-76.5%、lpsp 53.5-55.5% |
| P6-7 | MINOR | pv.py:80-84 | 只计 eta_inv=0.97，缺污垢/线损/失配/自遮挡 → PV 高估 5-8% | ✅ pv.py 新增 eta_system=0.95（P_ac_w 乘 eta_inv*eta_system）；project.py PVConfig 加字段；engine/sweep 构造传参。年 PV -5%（实测 26560.68/27958.61=0.95 精确） |
| P6-8 | MINOR | weather_bridge.py:144-145,122-130 | add_poa 注释称简化 Hay 实际纯各向同性；旧缓存无 poa_radiation 列时 dni=direct/cos(zen) 放大风险 | ✅ add_poa 入口加 poa_radiation 列防护（warn+drop+Erbs 重算）；docstring 如实 isotropic（无 Hay） |
| P6-9 | MINOR | sweep.py:246-252 | 单点 sweep 丢弃 engine 计算的 LCOE（cli 单点分支也不打印） | ✅ 单点 best dict 透传 engine 经济键（lcoe/cost_per_kg_fresh/capital_total/annual_om/annual_grid_cost/annual_pv_generation/annual_grid_import/annual_grid_export/battery_cycles） |
| P6-10 | MINOR | 天气数据 | 仓库 CSV 标注 UTC 但内容为当地时间（上海 GHI 峰在 hour 12）；tz_hours 固定不处理 DST | ✅ city CSV 与时区转换处加注释（+00:00 后缀内容本地墙钟；固定偏移无 DST 已知局限） |

### 维度 3：用户易用性（S7/S8/S9）

#### S7 CLI（cli.py / pyproject.toml / agent/evaluator.py）— 审查人 subagent-7，**易用性评分 4/10**

| # | 级别 | 位置 | 问题 | 修复状态 |
|---|------|------|------|---------|
| P7-1 | BLOCKING | pyproject.toml:65 | **顶层包名 `src` 与 OpenCROPS 冲突**：实测 `vfed.exe --help` 崩溃 `ImportError: cannot import name 'main' from 'src.cli' (G:\PVBES_Design\OpenCROPS\src\cli.py)`。应重命名顶层包为 vfed 并更新入口点+内部导入 | ✅ `git mv src vfed` 原子重命名 + pyproject 5 处入口 + ci.yml + vfed-web/bundle.py+worker.template.js + tests 全部 + scripts + 7 个 vfed/*/README.md `from src.`→`from vfed.`；pip 重装后 `import vfed.cli` 解析本仓库、`python -m vfed.cli --help` 正常；隔离 venv 验证无 OpenCROPS/src 残留（Agent2 独立验证） |
| P7-2 | BLOCKING | README.md:50/56/64 | 快速开始按文档操作必失败：design new my_farm 实际输出 --out 默认 project.yaml，文档却让 evaluate my_farm.yaml → E001 | ✅ cli.py 默认输出 `<name>.yaml`（`Path(args.name + ".yaml")`）；README 修复归批次9（P9-1） |
| P7-3 | MAJOR | cli.py:195-197 | sweep --out 写入不存在目录时泄漏完整 pandas 堆栈 traceback | ✅ `_write_results_csv(df, path)` 助手：except OSError→stderr `[ERROR] cannot write '{path}': {e}. Create the parent directory first (e.g. mkdir -p).` + return 1；手动验证无堆栈泄漏 |
| P7-4 | MAJOR | cli.py:138-142,195 | 单点模式 --out 被静默忽略（不写 CSV 不提示） | ✅ 单点分支 `pd.DataFrame([best])` → `_write_results_csv`（CSV 含 kwh_per_kg_fresh 等 12 列，手动验证 EXIT=0） |
| P7-5 | MAJOR | cli.py:209-233 | 关键参数几乎全无 help 文本（仅 --city 有） | ✅ name/preset/out/city/lat/lon/year/project/cache/out 全补 help + design/evaluate/sweep 子命令 help（"project management"/"simulate a single design configuration"/"run a design sweep (single-point if no ranges)"）；test help_describes_parameters 通过 |
| P7-6 | MAJOR | cli.py:91-95 + evaluator.py:64-70 | 天气错误归 E101（requests 错误消息不含 weather/fetch 子串）；首次离线运行 120s 无输出 | ✅ 新增 `WeatherFetchError`（weather_bridge.py，含 __all__）；evaluate/agent_evaluate/agent_simulate except WeatherFetchError→E003；首请求 print "Fetching weather for lat=…, lon=…, year=… from Open-Meteo (timeout=…s)...", flush=True；test fetch_weather_connection_error_wrapped 通过 |
| P7-7 | MAJOR | 全 CLI | 长任务零进度反馈（864 组扫参 ~25min 全程静默） | ✅ evaluate 前 stderr "Fetching weather for ({lat:.1f}, {lon:.1f}) year {year} (cache: '...')..."；sweep 前 stderr "Loading '{args.project}', fetching weather if needed (cache: '...')..." |
| P7-8 | MAJOR | cli.py:88-90 | 文件不存在报"配置非法"（应区分 not found 与 YAML 错误） | ✅ evaluate/sweep 入口 is_file 检查→`[ERROR E001] project file not found…design new` return 1；test missing_file_e001 通过 |
| P7-9 | MINOR | cli.py:204 | 裸 vfed 报 `arguments required: cmd` 暴露内部 dest | ✅ `add_subparsers(dest="cmd")` 去 required + main 无 cmd 时 `parser.print_help(); return 2`；手动 `python -m vfed.cli` EXIT=2；test bare_vfed 通过 |
| P7-10 | MINOR | cli.py:39-55 + city_db.py:28-80 | --city 走网络 geocode 但不设 tz_hours（固定 8.0）；_COORDS 表有正确时区未用 | ✅ city_db.py 新增 `city_coords(name) -> Optional[tuple]`（_COORDS 内置 lat/lon/tz_hours，Urumqi +6 等）+ __all__；cli 三元组赋值 + print "Set '...' -> lat=…, lon=…, tz=+… h"（city 未知→stderr 列城+exit 1）；test city_coords（--city Urumqi → tz_hours==6.0）通过 |
| P7-11 | MINOR | cli.py:139 | kWh/kg 硬编码 5% DM（growth.dry_matter_fraction 改动后标签错误） | ✅ cli 单点分支 `dm = res.get("dry_matter_fraction", 0.05)` → "kWh/kg (fresh, {dm*100:.0f}% DM)"；**补修**：evaluator 返回 dict 透传 `"dry_matter_fraction": project.growth.dry_matter_fraction`（自定义 DM 配置真实反映到标签）；复测 38 passed 无回归 |
| P7-12 | MINOR | cli.py:211 | 默认 --out=project.yaml 重复运行静默覆盖 | ✅ 默认改 `<name>.yaml` + out.exists() 时 stderr `(overwriting existing file: {out})`；test overwrite_warning 通过 |
| P7-13 | MINOR | cli.py:27-32 | _currency_label 死代码 | ✅ 删除 + 导入重写（删 sweep_design/lookup_tariff/geocode_city）；grep 零残留 |
| P7-14 | MINOR | evaluator.py:36-38 | E103 契约名存实亡（CLI 从不调用 agent_simulate） | ✅ agent_evaluate E103 检查 `best.get("annual_load_kwh", 0) <= 0` + cli.py evaluate 同检查（annual_load=load.sum()<=0）；test agent_simulate_zero_load_e103 + agent_evaluate 路径通过 |
| P7-15 | MINOR | cli.py:104 | `if summary.get("lcoe"):` 为 0 时跳过；pv_area=0 时静默不报 PV | ✅ 改 `if summary.get("lcoe") is not None:`；`pv_area_m2<=0 and battery_kwh<=0` 时 print "Energy system = disabled"；pv_gen>0 时打印 PV generation/Grid import/Grid export |

#### S8 YAML 配置（示例 YAML / design new 产物 / README 配置节）— 审查人 subagent-8

| # | 级别 | 位置 | 问题 | 修复状态 |
|---|------|------|------|---------|
| P8-1 | BLOCKING | README.md:59 + engine.py:630 | 文档承诺的 PV/电网输出在示例上不会出现：3 示例均无顶层 pv_area_m2/battery_kwh（默认 0）→ evaluate example_lcoe_full.yaml 实测无任何 LCOE/PV 输出（尽管文件名 lcoe_full）。应补 pv_area_m2:80/battery_kwh:50 并修正 README 措辞 | ✅ example_lcoe_full.yaml:135-136 补 pv_area_m2:80.0/battery_kwh:50.0，evaluate 实测 LCOE/PV/电网输出齐全；example_sweep/test_project 不补（扫参枚举/网格直供基线）；README 措辞归批次9 |
| P8-2 | BLOCKING | 全部示例 + design new 产物 | 529 行示例 YAML 零注释（~110 字段）；design new 产物同样零注释；README 配置节仅 17 行。用户必须读源码 | ✅ 3 示例 YAML 全区块中文注释（文件头/区块/行尾），注释只放区块上方与标量行尾不破坏结构；design new 产物注释归批次9 |
| P8-3 | MAJOR | battery.c_energy | 命名误导：是 $/kWh 单价却像容量；电池容量概念分散三处（c_energy/顶层 battery_kwh/sweep ranges） | ✅ c_energy 注释「单价不是容量」（project.py:262-263）+ 顶层 battery_kwh 交叉引用（:328）；DesignSpace 注释说明 sweep key pv_area/battery 与顶层字段独立 |
| P8-4 | MAJOR | 示例 YAML:70 | led.power_w:1300 无效占位被 auto_deduce 静默覆盖（同 P5-6） | ✅ 三示例 power_w/auto_deduce 行尾注释说明 1300→7200W 重算（400×45/2.5） |
| P8-5 | MAJOR | project.py:317-475 | 无类型/长度校验：ppfd_target:"six" 加载成功运行才 TypeError；hourly_prices 5 值静默按 0.10（同 P5-9） | ✅ _require_number 类型校验集（project.py:443-454）+ tariff 24 值元素数值/legacy 数值/ranges 三元素结构/objective 白名单；测试 test_04_config.py:237-258 |
| P8-6 | MAJOR | example_sweep.yaml:126-167 | 示例 sweep 规模 864 组 ≈25min 无进度反馈（同 P7-7）；参数名不一致（YAML pv_area vs 字段 pv_area_m2 vs CSV battery_kwh） | ✅ example_sweep 缩为 3 参数 ppfd_target×pv_area×battery=100 组（原 21600 组）；key 保持 pv_area/battery（sweep 注册表键，改 pv_area_m2 会被拒）；lcoe_full 4 参数 225 组保留 |
| P8-7 | MAJOR | project.py:229-257 | PV/Battery 两节字段注释覆盖率 ~3%（1/22）；C_pv=110.0 是 $/kWp 却像容量 | ✅ PVConfig 14 字段 + BatteryConfig 7 字段全中文单位注释（project.py:243-256/262-269） |
| P8-8 | MINOR | project.py:342-355 | typo 报错用 Python 类名（HVACConfig）而非 YAML 路径 | ✅ sub() 加必填 yaml_path 参数 + 17 调用点 + 报错改 YAML 路径（project.py:368）；test_04_config.py:48 同步 match |
| P8-9 | MINOR | cli.py:210-217 + tariff_db.py | design tariffs 列出的电价无落地途径（design new 无 --tariff）；示例手写电价与上海参考价矛盾 | ✅ design new --tariff 落地（cli.py）；Shanghai 实测 hourly_prices[8]=1.0/export=0.4155 rc=0，Mars 列 10 区域 rc=1 |
| P8-10 | MINOR | project.py:361-375 | 两套 tariff 格式并存（hourly_prices vs peak_price/valley_hours），README 只文档化前者 | ✅ example_sweep.yaml:108-110 tariff legacy 注释（P5-13 白名单兼容保留）；README 双格式文档化归批次9 |
| P8-11 | MINOR | sweep.py:238-242 | space.objective 只在 sweep 运行时校验；无 validate/dry-run 命令 | ✅ objective 白名单移入 from_dict + validate 子命令（cli.py:101-118/301-303）；实测 OK/rc=0、E001×2 |
| P8-12 | MINOR | engine.py:240-246 | timestep_s 不整除 3600 运行时才报错 | ✅ from_dict 镜像 engine 校验（project.py:598-603，max(1,round(3600/dt))+|sub*dt-3600|<=1）；ts=700/0 拒 600 过；测试 test_04_config.py:224-235 |
| P8-13 | MINOR | project.py | 无必填字段，漏写静默用默认值（删 C_z 行从 499,597 回落 80,000，热惯量错 6 倍） | ✅ name/site.lat-lon 缺省 UserWarning（project.py:613-622）+ C_z 默认值依据注释（200 m³ 空气≈67 kWh/K） |
| P8-14 | MINOR | project.py:301-303 | currency 改不改 exchange_rate 静默按 1:1 | ✅ currency≠USD 且 fx==1.0 → UserWarning（project.py:623-629） |
| P8-15 | MINOR | project.py:74-80 | site.tz_hours/year 默认值（8.0/2025）README 未提 | ✅ SiteConfig docstring 默认值说明（project.py:68-80：上海/UTC+8/2025）；README 同步归批次9 |

#### S9 文档与结果解读（README.md / README_zh.md / result.py / tests）— 审查人 subagent-9

| # | 级别 | 位置 | 问题 | 修复状态 |
|---|------|------|------|---------|
| P9-1 | BLOCKING | README.md:50-56 | quickstart 命令自相矛盾（同 P7-2） | ✅ README/zh 双语 quickstart 全文替换为 5 步（design new --city Shanghai --year 2025 → validate → evaluate → sweep example_sweep.yaml → vfed-web）实测逐条可执行 |
| P9-2 | MAJOR | README.md:61-67 | 核心卖点演示失败：preset 609 无 parameter_ranges → sweep 单点分支不写 CSV，用户拿不到最优 PV/电池容量；README 未指向 example_lcoe_full.yaml | ✅ README 注明 609 无 ranges→单点、指向 example_sweep.yaml（100 组）与 example_lcoe_full.yaml（225 组）、无 optimize 命令 |
| P9-3 | MAJOR | 全 README | 无结果解读章节：LCOE/kWh/kg/grid_independence_pct 等 KPI 无单位；CSV 列名无单位无货币标注 | ✅ README/zh 新增「## 输出结果解读」（evaluate KPI 表 + sweep CSV 列清单表含 currency 列 + 货币说明 exchange_rate 仅标注不换算） |
| P9-4 | MAJOR | README.md:96-112 | 唯一可视化入口 vfed-web/ 完全隐形 | ✅ 仓库树补 vfed-web/ 行 + README/zh 新增「## Web 可视化（vfed-web）」（本地 http.server 8000/BUILTIN_PRESETS/仿真链路/bundle.py） |
| P9-5 | MAJOR | 全 README | 无故障排除章节（错误码 E001/E003/E101 无文档）；timestep_s 整除、HARD_LIMITS 等坑无提示 | ✅ README/zh 新增「## 故障排除」（错误码表 E001/E003/E101/E103 + timestep 规则 + HARD_LIMITS 11 项表 + 天气离线三解法 + LCOE 口径） |
| P9-6 | MAJOR | 快速开始 | 离线假设与网络现实冲突：design cities 标注 pre-downloaded(2025)，quickstart 用 --year 2023 静默联网，无网即 E003；preset 609 内定 Shanghai，--lat/--lon 实际被忽略 | ✅ quickstart 改用 --city Shanghai --year 2025 全程离线；README/zh 新增「天气数据」小节（三来源优先级/site.city: null 强制 lat/lon/example 2023 首跑联网） |
| P9-7 | MINOR | README.md:87,33,99,105 | PVBES/SHR/kWh/kg 首现无展开 | ✅ PVBES（PV-Battery-Grid (PVBES) system）、SHR（sensible heat ratio / 显热比）、kWh/kg（of fresh biomass / 每千克鲜重的千瓦时）双语展开 |
| P9-8 | MINOR | README.md:128 | CLI 表 design new 描述"Create a new YAML project file"误导（实际产出固定 --out 路径） | ✅ CLI 表全文替换：design new 描述含 7 选项、新增 validate 行、cities 补 2025、evaluate/sweep 补 --cache/--out |
| P9-9 | MINOR | sweep.py:320-344 | CSV 列名下划线混合命名、无单位、无 currency 列 | ✅ sweep.py 3 处加 currency 列（L304 best/L389 多点多目标 row/L452 单点 row）；列名不改（消费方耦合）；README CSV 表文档化单位 |
| P9-10 | MINOR | result.py:52-68 | SimulationResult 裸 dict/list 无单位元数据，下游展示难以加单位 | ✅ result.py 类 docstring 加 Units 段 + summary 字段单位注释（纯文档零运行时） |
| P9-11 | MINOR | 根目录 | 残留 test_project.yaml、test_web_yaml.py（开发产物）未引用 | ✅ 仓库树补两行说明（最小夹具 YAML — 仅供 tests/ / vfed-web 端到端契约脚本）；不移动（test_03_numerical.py 硬编码读取） |
| P9-12 | 正面 | tests/ | 9 个测试文件分层清晰，但**无 CLI 端到端测试**（design new→evaluate→sweep CSV 落盘）——两个 BLOCKING 漏网的原因 | ✅ 已由批次7 test_07_cli.py 18 项端到端测试解决（design new/evaluate/sweep/E001/E003/E103/validate/--tariff） |

## 5. Executor Feedback or Help Requests

### 修复顺序与联动约束（执行时注意）

- **P4-1（RH 崩塌）与 P2-1（COP 提升）同一根因**（Carnot COP 上限 + 潜热去除无界），应同批修复（批次 2 或 4 任一处先行，另一处跟随）。修复后需用真实上海 2023 天气复跑验证 RH 分布。
- **P3-1/P3-2/P3-3 联动**：6 种蒸腾方法默认参数需统一到同一物理水平；改 k_van_henten 必须与 DEH auto-size（P3-4）同批，否则 DEH 欠配。参考第二轮 MAJOR-5/6 联动教训。
- **P6-1（缓存键）牵动 weather_bridge 接口**：按 AGENTS.md 属"Ask first"（weather_bridge.py 修改需谨慎——API 响应可能变化）。缓存键方案（加 tilt/azimuth/tz）不改外部 API，低风险。
- **P7-1（顶层包重命名）波及面最大**：pyproject.toml + 所有内部相对导入 + 测试 + CLI 入口。属结构性改动，需全量 pytest + 手动 vfed 命令验证。
- **修复原则**（AGENTS.md）：fail-fast（不静默兜底）、单位显式、公式有文献注释、改 project.py 字段必须同步 presets.py/示例 YAML/测试。
- **每批完成后**：运行相关测试 → 更新本文件 §4 状态 → 更新 todos → 下一批。全部完成后全量 pytest + 报告。

### 修复实施记录（按批次追加）

#### 批次 1（S1 Physics）— ✅ 已完成并通过独立验证（2026-08-16）

阶段A：三个并行 general subagent 出方案 → 规划者统一落盘 5 文件：
- **P1-1** `psychrometrics.py`：新增模块级 `_WATER_MAGNUS_A/B/C`(17.27/237.3/0.61078) 与 `_ICE_MAGNUS_A/B/C`(22.587/273.86/0.61121)，`saturation_vapor_pressure` T<0 切冰面（验算 −10°C→0.2597kPa、−45°C→0.0072kPa，旧水面分别高 10%/49%）；docstring 注明 ASHRAE 出处与 0°C 三相点 ~0.07% 不连续。
- **P1-2** `envelope.py`：`infiltration` 返回三元组 `(Q_sens_W, M_lat_kgs, Q_lat_W)`，`Q_lat=M_lat·L_v(T_z)·1000`；ach≤0 返回 (0,0,0)。`engine.py` L373 三元组解包 + L402-404 Q_total 含 `+Q_lat_inf`（全年净 +1.27 MWh，夏 +2.49/冬 −1.23）。
- **P1-3** `psychrometrics.py`：`temp_rh_to_ah`/`saturation_humidity` 分母 ≤0 抛 ValueError（含 T/RH/P 信息）。
- **P1-4** `temp_rh_to_dewpoint` 两遍反演（水面 → 若 T_dp<0 用冰面）；T_dp(25/60%)=16.70°C 回归不变。
- **P1-5** `shr.py` h_fg 死字段删除；模块 docstring 改 `q_lat = L_v(T_adp)`。
- **P1-6** `shr.py` 新增 `shr_transition_band=0.5`，calc_shr 在 `T_dp−band<T_adp<T_dp` 线性混合（1.0→0.823 连续）。⚠️ 原审 0.66 突变误报（真不连续 1.0→0.989 物理连续），大幅翻转实为 hvac on/off 迟滞（P2 范围）。
- **P1-7** `ode.py` `step_temperature` 加 `return_meta`，meta 含 clipped_deg_c；`engine.py` 两调用点改 return_meta=True 并累计 `temperature_clamp_stats`（summary L570-573）。
- **P1-8** `step_humidity` docstring 强化 T_z 必传 + 顺序 Euler 近似注释。

阶段B：独立验证 subagent 只读复查 **8/8 通过**（代码检查 + 数值验算表 + grep 全链一致 + pytest **197 passed**）。h_fg 残留仅 hvac/dehumidifier/transpiration（P2-4/P3-6 后续批次范围，非错误）。

#### 批次 2（S2 Devices）— ✅ 已完成并通过独立验证（2026-08-16）

阶段A：三个并行 general subagent 出方案 → 规划者统一落盘 5 文件：
- **P2-1** `hvac.py`：模块级 `_COP_MIN_LIFT_C=5.0`/`_COP_COOL_MAX=4.5`；carnot 分支 `lift=max(T_cond−T_evap,5.0)` + 最终 COP 上限 4.5（删 0.1K 下限与 50 上限）。验算：5/22.5→4.5（旧 17.5）、15/22.5→4.5（旧 6.5）、35/22→2.79 不变。设计点不受影响。
- **P2-2** `hvac.py` + `engine.py`：size_hvac 新参 `deh_latent_residual_w=0.0` 计入 q_sens_raw；engine 配合点 A（m_transp 块含 van_henten 预跑上移 DEH 分支外，全模式可用）、B（`max(0.0, P_ref·smer/3.6e6 − m_transp)·L_v`）、C（传参）、D（过时注释更新）。⚠️ 量级：默认预设下残余=0W（vpd 蒸腾 2.08e-3 已超 DEH 容量），auto_size 时 2.8kW；"~2kW@609" 注释与 k_vpd=5e-5 标定不符，待批次3 P3-2 后复核。
- **P2-3** `hvac.py`：新方法 `_cop_heat_at`（Carnot 制热缩放，EN 14511 A7/W35 额定点）+ heat_pump 分支改用；−20→1.76/−10→2.10/0→2.62/15→4.13/25→5.0(clamp)，上下限 [1.5,5.0]。
- **P2-4** `hvac.py`/`dehumidifier.py`：h_fg 参数与 self.h_fg 全删；dehumidifier 连带删 `efficiency` 死参数（typing 去 Optional）；EnthalpyEfficiency 类保留。
- **P2-5** `dehumidifier.py`：SMER 基准文档化三处（模块 docstring/smer 注释/size_deh docstring）——压缩机输入基准、风机单独计量、spec-sheet 换算公式。
- **P2-6** `dehumidifier.py`：step() 重构 `Q_act = M_act·L_v + Q_sens_act`（Q 由 M 推导）；dt=60 首步新 Q_act=2301.4W，恒等式行差 ~1e-13，稳态 5311.2W 零变化。
- **P2-7** `hvac.py`：cool 分支前注释化简化说明。
- **P2-8** `lag.py`：`abs(target)>=abs(current)` 判断；τ 相等时 200 步随机游走逐位一致。
- **P2-9** `led.py`：heat_fraction 注释化（2-5% 固碳，config-only），数值不变。
- **P2-10** `dehumidifier.py`：返回键改名 `latent_cop`（满负荷 1.3606）+ 保留 `"eta"` 弃用别名。

阶段B：独立验证 subagent 只读复查 **9/9 通过**（P2-1/3/4/5/6/7/8/9/10 全 ✅；P2-2 机制接线正确仅量级备注）。pytest **195 passed + 2 deselected（slow 网络测试）**，无回归：test_annual_load_stable=67.76 MWh（带内 [45,75]）、test_water_balance_closure ✅。2 个 slow 测试（test_weather_fetch_real/test_weather_no_cache）均网络依赖，当前环境不可达，与代码修改无关。

新发现记录：
- slow 网络测试共 2 个（非 1 个）。
- `psychrometrics.py:144-149` 的 h_fg 为湿球迭代合法局部计算变量，非死参数。
- P2-2 残余项量级与批次3 P3-2（vpd 蒸腾标定）联动，批次3 完成后需回核 hvac.py:288/engine.py:182 注释数值。

#### 批次 3（S3 Plants）— ✅ 已完成并通过独立验证（2026-08-16）

阶段A：三个并行 general subagent 出方案 → 规划者统一落盘 8 文件：
- **P3-1** `transpiration.py` + `project.py`：k_van_henten 4e-4→1e-4（按实际 30 天收获 X_d≈0.452 反标定；收获 λE 616→102 W/m²，与 vpd 113 同水平）。
- **P3-2** `transpiration.py`：k_vpd 保留 5e-5 + 量化注释（6e-5 崩塌证据、w/f 低估 3.2x、根因=生长模型产量膨胀）。
- **P3-3** `transpiration.py` + `project.py` + 3 示例 YAML：g_stomata 1e-3→1e-2（r_s=100）。
- **P3-4** `engine.py` auto-size 块：van_henten 分支均值→周期峰值 `m_peak=max(...)`；else 分支补传 `light_wm2=ppfd_target/par_factor`；P2-2 注释失实清理（engine.py:182 + hvac.py:288 删 "~2kW@609"）。
- **P3-5** `transpiration.py`：per_plant fail-fast（暗期优先返回 0.0）。
- **P3-6** `transpiration.py`：删 h_fg 死字段（全仓清零）。
- **P3-7** `transpiration.py`：γ 同温化公式；test_03_numerical.py:372 同步。
- **P3-8/9/10** `transpiration.py`：R_n 注释 / docstring T_leaf≈T_air + L9 笔误修正 / step 瞬时速率说明。
- **P3-11** `van_henten.py`：P_atm 可选参 + `_co2_density(T)`（T/P 相关，22°C +0.95%）。
- **P3-12** `van_henten.py`：Q10 呼吸注释。
- **P3-13** `transpiration.py:84`：_xd 回退 0.01→0.02。
- **P3-14** `project.py:198`：initial_dry_weight 0.001→0.02；_demo docstring 如实化。
- 测试同步：test_transpiration per_plant 断言改 ValueError。

阶段B：独立验证 subagent 只读复查 **P3-1~14 全 ✅**（数值验算：k=1e-4 设计点 λE=102.4、γ(22)=0.0668、_co2_density(22)=1.4534e-3、auto-size P_ref=5.77kW@X_d=0.495 实际路径）。pytest **195 passed + 2 slow deselected**，无回归。

诊断修复（规划者，非批次3 范围但同批落地）：
- **test_04_config.py:258 test_unknown_objective_raises 污染 session-scoped project_609**（原地设 objective="maximize_happiness" 不恢复）→ 分片组合中 test_04→test_06 顺序使 test_06 两个 sweep 测试报 "Unknown objective 'maximize_happiness'"。修复：该测试改用 copy.deepcopy(project_609)。此为既有缺陷（被 test_05 的"顺手重置"长期掩盖），非批次3 引入。修复后 123 passed（分片3 全绿）。

新发现记录（阶段B 验证反馈）：
- P3-4 的"收获期 RH 守住设定值"仅对蒸腾主导季节成立；夏季室外渗透湿负荷超 DEH+HVAC 容量（7 月光照期 31% 小时>68%）属**既有物理极限**（vpd 法 9 月 100% 超调更差），非 P3-4 引入。方案表述已限定。
- transpiration.py:63 注释引用 X_d≈0.45 vs 引擎实际 pre-run 生长至 X_d=0.495（initial=0.02）：0.452 为真实农场目标值，Van Henten 已知过产 ~2x。选型用实际模型路径自洽，仅叙事数值与注释略有漂移，后续批次可校准注释。

#### 批次 4（S4 Engine）—— ✅ 已完成并通过独立验证（2026-08-16）

阶段A 落盘（10 文件，组A/B/C 并行方案）：
- **P4-1 [BLOCKING]** hvac.py `_apply_rh_guard`（SHR_RH_GUARD=55/band 3）+ `_COIL_CONDENSE_K=5e-7` 盘管冷凝上界（3000W→1.5 g/s）+ `M_target=min(Q_lat/L_v, cap)`；project.py HVACConfig 新字段 shr_rh_guard/rh_guard_band/coil_condense_max_gps；engine `_limit_removal_by_inventory` 加 E_trans/M_inf/M_perm 净源补给（P4-1d）。
- **P4-2** PVBES 门控 `pv_area>0 or battery_kwh>0` + else grid-only 经济 15 键；**P4-4** except 嵌套 try（核心 5 键缺失 raise，明细降级 energy_system_detail_status）；**P4-6** surface_pressure fail-fast；**P4-7** 设计点 temp_rh_to_ah 补 pressure_kpa=P_atm；**P4-8** 时间基收割（harvest_hours/next_harvest_h，预跑同步 +0.5）；**P4-9** run docstring 副作用声明 + result.sizing；**P4-10** LED 分数小时 is_light(hours[h])；**P4-11** led.par_wm2 属性三处统一。
- **P4-5** presets.py C_z 499,597→200,000 Wh/K + docstring + 3 YAML 同步；**P4-16** weather_bridge 查询窗扩/时区转换/切片对齐/陈旧检测/离线 fallback；**P4-18** battery 年末 SOC 回补 + energy_system 双侧 recon 闭合。

阶段B 独立验证（只读 subagent）：18 项中 17 项直接通过；**发现 1 MAJOR 已修**——P4-1b 线圈冷凝上限 auto 路径单位错误（`_COIL_CONDENSE_K=5e-4`→1.5 kg/s 而非 1.5 g/s，漏除 1000，cap 形同虚设）；修正为 5e-7 后实测：min RH 3.73→7.63、<10% 81→11h。
**RH 复测最终值（609/上海2023）**：<50% 2920→**1619h**（-45%）、<30% 811→514h、<10% 81→11h、min RH 4.27→7.63、年负荷 67,128kWh∈[45,75k]。pytest 独立复核 197 collected 全绿（规划者分片口径 195 passed + 2 slow deselected）。

新发现记录（阶段B 验证反馈）：
- ⚠️ **P4-1 跨组暂缓项：暗期透蒸 0.15×（transpiration.py，S3 范围）**——组A 实测仅 (a)(b) 修复后 <30% 仍 514h、min RH 7.63；叠加暗期透蒸 0.15× 后 min RH→30.9、<30%→0。已记录待用户决策（是否接受"夜间切流系数"修正）。
- [MINOR] vfed-web/index.html + worker.js 仍含 `C_z: 499597.0`（打包 preset 副本 3 处），Python 侧已全改；web 部署需同步（批次8/9 处理）。

#### 批次 5（S5 配置契约）—— ✅ 已完成并通过独立验证（2026-08-16）

阶段A 落盘（8 文件，组A/B 并行方案）：
- **project.py 13 处**：P5-1 pump_capital 注释（接入在 sweep 侧）；P5-2 删 pv.maintenance/battery.maintenance 字段；P5-3 删 transpiration.photoperiod_hours；P5-4 删 deh 四件套 eta_ref/eta_max/ah_min/ah_ref；P5-5 transpiration.method 白名单；P5-6 LED auto_deduce+power_w 告警（显式非默认 1300 才 warn）+ 注释；P5-7 spectrum 白名单；P5-8 cop_table isinstance 守卫；P5-9 hourly_prices 精确 24；P5-13 legacy tariff 键白名单；P5-14 strategy docstring "NOT implemented"；P5-15 单位注释（deadband_c/T_mean/T_std/W_mean/W_std/cycle_life）；P5-16 heat_mode 白名单。
- **sweep.py 4 处**：P5-1 _total_capital/_annualized_capital 加 "Pump"（dep=15 CRF）；P5-10 _validate_ranges 形状预校验（dict/[min,max,step]/整数步数）；P5-11 _VALID_CAPITAL_MODES + _resolve_capital 白名单；删 battery maintenance 传参（L180）。
- **联动**：engine.py:746 删 maintenance 传参；led.py __post_init__ P5-6 注释；test_04_config.py 2 测试改写（round_trip 去 photoperiod_hours / unknown_method_rejected）；3 示例 YAML 删 deh 四件套 + battery maintenance。
- **P5-12** 实测已满足（objective 校验 L268-272 天然先于单点分支），无 diff。

阶段B 独立验证（只读 subagent）：P5-1~16 全部 16/16 通过（含 python 实测：bogus method/spectrum purple/cop_table list/hourly_prices 短表/legacy 拼错键/heat_mode plasma/capital.mode per_wt 均 ValueError；P5-1 pump=2000→annualized +205.93=CRF(0.06,15)×2000 ✓）。pytest **195 passed + 2 deselected**。
**发现 2 条 LOW 已处理**：① P5-6 告警噪音（round-trip/预设/sweep 组合 15 条 UserWarning）→ 已修为 `power_w not in (None, 1300.0)` 才告警（显式 5000 仍告警、round-trip 不再误报，-W error::UserWarning 下 test_04 30 passed）；② 根目录 test_web_yaml.py 内嵌 YAML 仍含已删键（eta_ref 四件套 + battery.maintenance，L48-51/L78/L220,227）→ 非 pytest 收集范围（testpaths=["tests"]），vfed-web 契约测试，批次8/9 随 web 同步处理。

#### 批次 6（S6 PVBES/缓存）—— ✅ 已完成并通过独立验证（2026-08-16）

阶段A 落盘（9 文件，组A/B/C 并行方案）：
- **P6-1** `weather_bridge.py`：`_cache_path` 文件名纳入 tilt/azimuth/tz（`weather_{lat}_{lon}_{year}_t{tilt}_a{azimuth}_z{tz}.csv`）+ `_legacy_cache_path` 旧名回退；legacy 命中且 aligned 时 drop poa/direct/diffuse 3 列从 GHI Erbs 重算（warn）；离线 fallback 同样重算。
- **P6-2** `sweep.py`：else 分支评估固定 pv_area_m2/battery_kwh（惰性 _build_energy_system）；row 对齐 PVBES schema（+7 capital_* 键 + 4 PVBES 键）。
- **P6-3** `sweep.py`：_compute_lcoe docstring 改 "Levelised facility cost per kWh of building load"（lcoe 列名保留）。
- **P6-4** `sweep.py`：_annualized_capital 加 `battery_life_years: Optional[float]=None`，Battery dep=min(配置, life)；PVBES 分支传 `m.get("battery_life_years")`。
- **P6-9** `sweep.py`：单点 best dict 透传 engine 经济键（lcoe/cost_per_kg_fresh/capital_total/annual_om/annual_grid_cost/annual_pv_generation/annual_grid_import/annual_grid_export/battery_cycles）。
- **P6-5** `energy_system.py`：docstring/字段/成本段标注 ALTERNATIVE/legacy scope（权威 LCOE 在 sweep/engine）。
- **P6-6** `energy_system.py`：tlps→grid_dependency_pct（=mean(grid_import>0)*100）+ 新增 lpsp_pct（能量加权）；tlps 保留别名键。
- **P6-7** `pv.py` + `project.py` + `engine.py`：新增 eta_system=0.95（P_ac_w 乘 eta_inv*eta_system）；PVConfig 加字段；engine/sweep 构造传参。
- **P6-8** `weather_bridge.py`：add_poa 入口加 poa_radiation 列防护（warn+drop+Erbs 重算）；docstring 如实 isotropic（无 Hay）。
- **P6-10** `weather_bridge.py`：city CSV 与时区转换处加注释（+00:00 后缀内容本地墙钟；固定偏移无 DST 已知局限）。
- **P4-15** `battery.py` + `energy_system.py`：cycle_life/maintenance 注释；calculate_metrics 返回 battery_life_years（=cycle_life/annual_cycles）+ battery_replacement_annual（<lifetime 折现年金化）；权威接入经 sweep _annualized_capital min()。
- 文件编辑计数：weather_bridge.py（P6-1/8/10，6 处编辑）、sweep.py（P6-2/3/4/9，4 处编辑）、energy_system.py（P6-5/6/P4-15）、pv.py（P6-7）、battery.py（P4-15 注释）、project.py（PVConfig eta_system）、engine.py（PVSystem 构造传 eta_system）。

阶段B 独立验证（只读 subagent）：**10/10 全 ✅**：
- tilt 缓存键分离：tilt=20 vs 55 数组不同（max|Δ|=1115.5 W/m²）。
- building-only 对齐：固定 pv=80/bat=50 → lcoe 0.6025 / capital 13046.51 与单点 engine 完全一致；无固定 PV 时 net_grid=0 基线不变。
- grid_dependency_pct / lpsp_pct：A=100/E_bat=20 → gdep 74.7-76.5%、lpsp 53.5-55.5%。
- eta_system -5%：年 PV 26560.68/27958.61=0.95 精确。
- battery_life_years：E_bat=20 → life≈20.5yr，25yr 内 1 次更换；609（life≈78）min() 零变化。
- 单点透传 + grep tlps 别名键 + pytest **195 passed + 2 deselected** 全绿。

新发现记录（阶段B 验证反馈）：
- [MEDIUM 缓存残留非代码缺陷] `weather_cache/weather_30.900_121.500_2025_t20.000_a180.000_z8.000.csv` 为 pre-P4-16 旧格式（含 wind_speed_10m 列、tz-aware 08:00 起始）→ 每次 2025 fetch 走 stale 警告+网络重取；建议删除后重新生成（缓存可再生，git-ignored）。
- [LOW] pv.py:32 注释 "580.5 W" 为标牌舍入（实际 580.461）；energy_system.py:140 变量名 pv_extra 命名误导（实为电池更换折现成本）；test_06 @pytest.mark.slow 未注册 mark（PytestUnknownMarkWarning 无害）。
- [INFO] archive API 年度请求当前 ReadTimeout，fresh 网络路径无法端到端复现（legacy/fallback 路径均已确定性验证）；weather_30.900_121.500_2023.csv 被 git 强制跟踪（.gitignore L24 但已入库），批次前既有现象。

### Git 状态

- 当前 HEAD：`5c8e7e9 docs(meta): sync repo_sync scratchpad - REVIEW fixes verified (197 tests)`。第二轮 A/B/C/D 修复 19 文件**已全部提交，无残留**。
- 本轮未提交改动（批次1~6 全部 + 批次7 组A）：**源码目录已由 `src/` git mv 重命名为 `vfed/`**（含批次1~6 全部修改）。源码文件 20 个：vfed/physics/{psychrometrics,envelope,shr,ode}.py、vfed/design/{engine,hvac→devices,dehumidifier→devices,lag→devices,led→devices,transpiration→plants,van_henten→plants,project,presets,result,sweep}.py、vfed/weather/weather_bridge.py、vfed/pvbes/{battery,energy_system,pv}.py、vfed/cli.py + 测试 4 文件（test_transpiration / test_03_numerical / test_04_config / test_06_edge_cases）+ 3 示例 YAML（example_lcoe_full / example_sweep / test_project）+ pyproject.toml + ci.yml + vfed-web/{bundle.py,worker.template.js,worker.js} + tests 全部（导入 src→vfed）+ 7 个 vfed/*/README.md。
- 提交策略：待用户确认（每批一提交 vs 攒批提交）。**批次7 组A（P7-1 包重命名）已 git mv + 全部导入替换 + 重装 + 验证完成，建议作为单独提交点。**

### 批次 7（S7 CLI）—— ✅ 已完成并通过独立验证（2026-08-16）

**组A（P7-1 顶层包重命名）—— ✅ 已完成并验证**
- `git mv src vfed` 原子重命名（含未提交修改一并搬移）；pyproject.toml 5 处（scripts vfed=vfed.cli:main / sdist /vfed / wheel [vfed] / --cov=vfed / source=[vfed]）；ci.yml 4 处 black/flake8 vfed/；vfed-web/bundle.py VFED_SRC；worker.template.js 8 处 `from vfed.design.`；tests 全部（6 个 SRC 文件 SRC=/vfed + MODULES 表 21 字符串 + 4 个无 SRC 文件导入串）+ scripts/download_weather_db.py + test_web_yaml.py + 7 个 vfed/*/README.md 全部 `from src.`→`from vfed.`；`cd vfed-web && python bundle.py` 重新生成 worker.js。
- 重装：`pip uninstall -y vertical-farm-energy-designer` → `pip install -e .`（600s 超时重试成功）→ `pip install -e ".[dev]"`。
- 验证：`import vfed.cli` → 本仓库 `G:\VFLab\VFLAB\vertical-farm-energy-designer\vfed\cli.py`（不再 OpenCROPS）✅；`python -m vfed.cli --help` 正常 ✅；**隔离 venv 独立验证（Agent2）**：干净 venv 中 `vfed.exe --help` 正常、`import vfed` 解析到本仓库（CWD 在仓库外也正确）、site-packages 无 src/opencrops 残留、`import src`→ModuleNotFoundError。⚠️ 环境附注：本机 pip 全局 extra-index-url=pypi.ngc.nvidia.com 导致 pip install -e 卡死（SSL 握手失败重试风暴），验证 agent 用 `--no-build-isolation --no-deps` 离线 wheel 绕开，建议后续环境级修复。

**组B（cli.py）—— ✅ 全部落盘（9 处）**
1. imports 重写：删 sweep_design/lookup_tariff/geocode_city（P7-13）；city_db 导入加 city_coords（P7-10）；加 `from .weather.weather_bridge import WeatherFetchError`；删 _currency_label 死代码；新增 `_write_results_csv(df, path)->int` 助手（P7-3：try to_csv/except OSError→stderr `[ERROR] cannot write '{path}': {e}. Create the parent directory first (e.g. mkdir -p).`+return 1/成功 print "  Enumeration table -> {path}"）。
2. `_cmd_design_new`（P7-2+P7-10+P7-12）：`out = Path(args.out) if args.out else Path(args.name + ".yaml")`；out.exists()→stderr `(overwriting existing file: {out})`；`preset.site.year = args.year if args.year is not None else 2025`；city 分支 `canonical = lookup_city(args.city)` → None 时 stderr 列城+sys.exit(1)；`coords = city_coords(canonical)` 三元组赋值 lat/lon/tz_hours + print "Set '{canonical}' -> lat=…, lon=…, tz=+… h" / coords None 时 WARN（无网络）。
3. `_cmd_evaluate`（P7-8/7/6/14/15）：is_file 检查→E001 return 1；DesignProject.load except→E001；engine.run 前 stderr "Fetching weather for ({lat:.1f}, {lon:.1f}) year {year} (cache: '...')..."；`except WeatherFetchError`→"[ERROR E003] {e}"（置于 E101 前）；except Exception→E101；`annual_load = result.get("load", np.zeros(1)).sum()`；<=0→"[ERROR E103] load profile is empty or zero…"；`if summary.get("lcoe") is not None:` 才打印 LCOE；`if pv_area_m2<=0 and battery_kwh<=0: print("  Energy system    = disabled (pv_area_m2=0, battery_kwh=0)")`；pv_gen>0 时打印 PV generation/Grid import/Grid export。
4. `_cmd_sweep` 开头（P7-8+7）：is_file 检查→E001 + stderr "Loading '{args.project}', fetching weather if needed (cache: '...')..."。
5. `_cmd_sweep` 单点分支（P7-4+P7-11）：`dm = res.get("dry_matter_fraction", 0.05)`；标签 "kWh/kg (fresh, {dm*100:.0f}% DM)"；`if args.out: import pandas as pd; return _write_results_csv(pd.DataFrame([best]), args.out)`。
6. `_cmd_sweep` 末尾（P7-3）：`if args.out: return _write_results_csv(results, args.out); return 0`。
7. `build_parser`（P7-5 help 全补 + P7-9）：`add_subparsers(dest="cmd")` 去 required；全部参数补 help=（name/preset/out/city/lat/lon/year/cache/out）；design/evaluate/sweep 子命令 help 补全。
8. `main`（P7-9）：`if not getattr(args, "cmd", None): parser.print_help(); return 2`；`return args.func(args)`；`if __name__ == "__main__": sys.exit(main())`。
9. `city_db.py`：新增 `city_coords(name) -> Optional[tuple]`（`_COORDS.get(name.strip())` 返回 (lat, lon, tz_hours)，docstring 说明内置坐标带正确 UTC offset 不像网络 geocode 默认 +8）+ `__all__` 加 city_coords。

**组C（weather_bridge.py + evaluator.py）—— ✅ 全部落盘**
- weather_bridge.py：新增 `class WeatherFetchError(Exception)`（docstring：E003，覆盖缺 requests/传输失败/非 2xx）+ `__all__` 加 WeatherFetchError；fetch_weather 签名末尾加 `timeout: float = 120.0`；`if not _HAS_REQUESTS and not _HAS_PYODIDE: raise WeatherFetchError(...)`（原 ImportError）；网络请求块先 print "Fetching weather for lat=…, lon=…, year=… from Open-Meteo (timeout=…s)...", flush=True；pyodide 分支 except Exception→`raise WeatherFetchError(f"Weather API request failed: {e}") from e`；外层 `except WeatherFetchError: raise`（防双包）；`except Exception as e:` → P4-16 离线 fallback 原样（fb=locals().get("fallback_df") 存在则 warn+drop 3 列+add_poa 重算+return）否则 `raise WeatherFetchError(f"weather fetch failed: {e}. Check network connectivity or provide a cached/offline weather CSV.") from e`。
- evaluator.py：import WeatherFetchError；agent_evaluate/agent_simulate 的 except 改 `except WeatherFetchError`→E003（删 "weather"/"fetch" 子串匹配）；E103 检查 `best = sweep.get("best") or {}; if best.get("annual_load_kwh", 0) <= 0: →E103`；**P7-11 补修**：返回 dict 加 `"dry_matter_fraction": project.growth.dry_matter_fraction`。

**新增测试 tests/test_07_cli.py（13 项，全部通过）**
- 7.1 design new：default_out（无 --out→<name>.yaml）、explicit_out、overwrite_warning（capsys 查 "overwriting"）、city_coords（--city Urumqi→tz_hours==6.0）
- 7.2 evaluate：missing_file_e001（rc==1 + "E001"）、evaluate_ok（rc==0 + "Annual load"）
- 7.3 sweep：single_point_out_csv（rc==0 + CSV 含 kwh_per_kg_fresh）、out_missing_dir（rc==1 + "cannot write"）
- 7.4 bare/help：bare_vfed（rc==2 + "usage"）、help_describes_parameters（SystemExit 0 + "CSV output file"）
- 7.5 contract：fetch_weather_connection_error_wrapped（monkeypatch requests.get→ConnectionError → raises WeatherFetchError）、agent_evaluate_weather_error_e003、agent_simulate_zero_load_e103

**阶段B 独立验证（只读 subagent）**：P7-1~15 全部 15/15 通过（附行号证据 + 手动命令抽查：裸 vfed EXIT=2、sweep --help 含 "CSV output file"、design new/evaluate 缓存命中、evaluate 不存在文件 E001、单点 sweep --out CSV 落盘、--city Urumqi tz=+6.0）；发现 5 项 MINOR：① scripts/download_weather_db.py:17 注释 `so we can import src.*` 陈旧 ② weather_bridge.py:76-77 注释 "Project root = directory containing src/" 陈旧 ③ evaluator.py:5 docstring 引用 src/agent/evaluator.py ④ P7-11 标签非真正动态（已补修：evaluator 透传 dry_matter_fraction）⑤ AGENTS.md 路径（批次9 文档批）。
- pytest：test_07_cli 13 passed；全量 **210 passed, 1 warning in 81.6s**（原 195 + 新增 13 + 2 网络 slow 本次通过）；P7-11 补修后复测 `test_07_cli + test_01_smoke` **38 passed** 无回归。
- 冒烟：design new→evaluate 命中缓存 EXIT=0（Annual load 67778 kWh/yr、LCOE 0.5173 USD/kWh、Energy system disabled）；sweep 单点 --out CSV 落盘（kwh_per_kg_fresh=13.1007 等 12 列）EXIT=0。

**批次7 收尾步骤（完成）**：pytest 回归（210 passed）✅ → 阶段B 只读验证（P7-1~15 逐项 + 隔离 venv 污染回归）✅ → scratchpad §4 P7 表标 ✅ + §3 批次7 ✅（本段）→ 下一步批次8（S8 YAML）。
