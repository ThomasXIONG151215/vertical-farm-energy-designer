# Scratchpad: user3 — 暖通工程师（物理白盒验证）

## 1. Background and Motivation
扮演设计院暖通工程师（10年经验，物理怀疑派），对 VFED 做白盒物理正确性验证。
目的：评估该开源工具能否用于植物工厂前期负荷估算。
方法：黑盒跑通 → 白盒逐式核对源码 → 手算对账 → 输出体检 → 报告。

## 2. Key Challenges and Analysis
- 黑盒基准：design new 0.5s + evaluate 1.8s（上海=内置离线天气）
- 关键输出：年负荷 66,310 kWh；LED 42,048 (63.4%) / DEH 12,225 (18.4%) / HVAC 12,037 (18.2%)；水 19.91 m³；DEH 15,653 kg + 盘管 4,254 kg；RH clamp 0
- 手算对账：LED 0.00%；焓湿 5 项 <0.1%；水量守恒 0.02%；年能量闭合隐含 COP 3.97 ≈ 模型 4.0-4.2；冬夜隐含 COP 4.40 vs 公式 4.50(−2.2% 风扇)
- 两大发现：
  - F1 夜间 18°C 设定点不可达 → 100% 夜时 HVAC 满速 3070W，8,964 kWh=74% HVAC=13.5% 年电耗；heat mode 0 小时
  - F2 DEH 夜间 m_min=0.2 低速爬行 → 有效 SMER 0.95 vs 铭牌 2.0，DEH 电耗 +56% vs naive 手算
- 次级发现：产量 113 kg/m²/yr ≈ 文献生菜 2x（自曝）→ kWh/kg fresh 偏乐观；冬季 COP 全靠 cap=4.5 硬顶；RH 光期浮至 71-80

## 3. High-level Task Breakdown
- [x] T1: 黑盒基准（0.5s + 1.8s）
- [x] T2: 白盒源码核对 16 项（psychrometrics/envelope/shr/ode/hvac/compressor/deh/led/lag/transpiration/van_henten/engine 全读）
- [x] T3: 手算对比（hand_calc.py + hand_calc2.py，>6 量）
- [x] T4: 输出体检（T_z/RH/DEH 月形态/X_d 锯齿/clamp）
- [x] T5: report.md

## 4. Project Status Dashboard
| 任务 | 状态 | 备注 |
|---|---|---|
| T1 黑盒基准 | ✅ | audit609.yaml + export_base/ |
| T2 源码核对 | ✅ | 16 项核对表 |
| T3 手算对比 | ✅ | 13 OK / 3 SUSPECT / 0 BUG |
| T4 输出体检 | ✅ | |
| T5 报告 | ✅ | user-gym/user3/report.md |

## 5. Executor Feedback or Help Requests
无阻塞。判定统计：13 OK / 3 SUSPECT / 0 BUG；最严重一条 = 夜间设定点不可达引发全年满速制冷（F1，配置×控制问题，模型如实模拟但无诊断告警）。
