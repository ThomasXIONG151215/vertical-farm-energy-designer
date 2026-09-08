# Scratchpad: user6 极端气候物理可信度测试

## 1. Background and Motivation
- 角色：植物工厂环境控制研究员（user6），课题：VFED 仿真工具在极端气候下的物理可信度
- 前提：user1-5 已测上海/杭州温和气候，已知问题：609 preset 夜间 18°C 不可达→HVAC 全年夜时满速（2920/2920）；RH 设定 65% 实际年均 69%；DEH removal-limited；产量 2× 偏高；PV 单位陷阱等（见 SYNTHESIS.md）
- 本任务：测极端气候是否放大已知问题或暴露新问题
- 约束：产出全部放 user-gym/user6/，不改 vfed/ 源码，不 git commit

## 2. Key Challenges and Analysis
- 城市选择：需覆盖严寒（制热行为、围护热损、冬季 COP cap=4.5）、湿热（DEH/HVAC 失控、RH 失守）、干热/高海拔
- 天气来源：需确认城市离线 CSV 与 --cache 行为，记录实际来源
- 分析脚本需对比 4 城市：年总负荷、分项占比、kWh/kg fresh、年水量、暗期满速占比、T_z/RH_z 统计、制热小时、DEH removal-limited

## 3. High-level Task Breakdown
- [x] T1 选城市：Harbin（严寒，Text min -31.2°C）/ Bangkok（湿热，mean 28.2°C）/ Dubai（干热，max 46.5°C）+ Shanghai 自跑基准（与 user3/export_base 逐字段一致）
- [x] T2 3+1 城市 design new (1.6s) + evaluate (1.63-1.85s/城)，天气全部离线源自 data/weather/{City}_2025.csv
- [x] T3 上海基准验证：66310 kWh / 29017 events 与 user3 完全一致
- [x] T4 analyze_extreme.py → results_extreme.csv（5 张对比表）+ 3 轮深挖（最冷周、制热模糊带、Dubai 光期超温）
- [x] T5 重点问题全部回答（见 report.md 新发现清单 N1-N8）
- [x] T6 report.md 完成

## 4. Project Status Dashboard
| 日期 | 状态 | 说明 |
|---|---|---|
| 2026-09-08 12:32 | IN_PROGRESS | scratchpad 建立，开始侦察 |
| 2026-09-08 13:00 | DONE | 全部任务完成，report.md 已交付 |

核心结论：极端气候被理想化围护(ach=0.001/permeance=0)+LED内热(63-67%)归一化——4 城总能耗极差仅 -5.4%~+6.4%；Harbin 零制热（heat_pump 模式死代码）；Dubai 1068h 光期静默超温；RH 失守气候不变（41% 年时数 >70%）。零崩溃、零物理不可能值。

## 5. Executor Feedback or Help Requests
- 无阻塞。注意：workdir 传相对路径调 vfed.exe 会失败（NotFound / 模块加载错误），必须用绝对路径——user-gym 沙盒后续用户可参照。
