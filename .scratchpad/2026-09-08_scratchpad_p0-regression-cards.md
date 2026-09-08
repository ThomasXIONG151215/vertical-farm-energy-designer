# Scratchpad — 2026-09-08 P0 regression cards (user-gym/regression)

## 1. Background and Motivation
- 修复流水线正在修 user-gym/SYNTHESIS.md 路线图 P0-1..P0-5，每项修完由独立 verify subagent 验证。
- 本任务：为 P0-1..P0-5 各制作一张回归验证卡（README.md in user-gym/regression/），复现命令必须实跑验证。
- CLI: user-gym\user1\.venv\Scripts\vfed.exe；不修改 vfed/ 源码、不 commit。

## 2. Key Challenges and Analysis
- P0-1: rate_per_watt 对 PV 乘 kWp（sweep.py:113），200 m²=46.5 kWp × 3.5 = 162.79 RMB（差 1000 倍）
- P0-2: engine.py:975 energy system 禁用时 annual_grid_cost_net=0.0 但 grid_import_kwh=全负荷
- P0-3: van_henten.py:39-44 自认产量 2×；kwh_per_kg_fresh=13.0615 是 sweep 目标函数
- P0-4: 2920/2920 夜时 HVAC 满速 3070 W；夜均 T_z=22.06 vs T_dark=18（609 preset + city Shanghai 2025）
- P0-5: cli.py 单点 sweep 分支(464-475)只打 kWh/kg/load/biomass，无 LCOE 无 capital 警告；best 顶 200 m² 边界无提示
- 天气依赖：example 系 yaml 用 30.9/121.5/2023（需缓存，user1/weather_cache 有）；609+city Shanghai 用预下载 data/weather/Shanghai_2025.csv（离线）
- 物理基线：66,310 kWh/yr（66309.99）、13.0615 kWh/kg fresh（P0-4 修复会改基线）

## 3. High-level Task Breakdown
1. [P] 读 SYNTHESIS + user1/2/3/4 报告 — done
2. [P] 检查 cli.py/sweep.py/engine.py/presets.py 关键行 — done
3. 建沙盒 user-gym/regression/（weather_cache 复制、生成 base609.yaml）— done
4. 实跑 5 张卡的复现命令并核对基线数字 — done（全部跑通、基线全部对上）
5. 写 README.md（五张卡）— done
6. 汇报意外发现 — done（见 5）

## 4. Project Status Dashboard
| 子任务 | 状态 | 结果 |
|---|---|---|
| 读报告/源码 | done | 关键行已定位 |
| 沙盒搭建 | done | weather_cache 3 份 + base609.yaml |
| P0-1 复现 | done | capital_pv@200m² = 162.79 ✓ 斜率 0.814 ✓ battery 500×kWh ✓ LED 2.0×W ✓ |
| P0-2 复现 | done | evaluate grid_cost=0 vs sweep(0,0)=6631.00 ✓ LCOE 0.5284→0.6280(stamp) ✓ |
| P0-3 复现 | done | 13.0615 ✓ 112.8 kg/m²/yr ✓ growth 注释仅 "keep defaults" ✓ |
| P0-4 复现 | done | 2920/2920 ✓ 夜均 22.06 ✓ dark HVAC 8964 kWh ✓ |
| P0-5 复现 | done | 单点无 LCOE/警告 ✓ best 200 m²/5116 USD ✓ C_pv=0 边界变体 ✓ |
| README.md | done | user-gym/regression/README.md（275 行，五卡+附录） |

## 5. Executor Feedback or Help Requests
意外发现（均为小项，无阻断）：
1. sweep 的 parameter_ranges 不接受 min==max（"Invalid range"），卡片改用 [100,200,100]/[0,40,40] 两点网格。
2. user3 报告写 "min 20.55°C"，实测 dark min T_z = 20.56°C（四舍五入差异，卡片按实测值记录）。
3. python -c 内嵌中文标签在 GBK 控制台乱码 → 卡片 one-liner 全部改 ASCII 标签。
4. 控制台 "Fetching weather for (31.2, 121.5)" 是四舍五入显示，实际读 31.23/121.47 缓存（P2-2 措辞问题的一部分，卡片注意事项已注明）。
5. p05 边界用例的 C_pv 替换正则从字面 `110\.0` 改为 `[0-9.]+`，防 P0-1 修复改 example 默认值后卡片静默失效。
6. 所有 SYNTHESIS 引用数字（162.79、0.814、66310、13.06/13.1、0.5284、5116、200 m²、2920/2920、22.06、8964、12,037）均在当前 HEAD 复现成功，无一失配。
