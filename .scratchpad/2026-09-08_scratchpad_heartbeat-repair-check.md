# Scratchpad: VFED 三小时心跳 — 修复检查 + 新测试规划

## 1. Background and Motivation
用户设立常驻例程（heartbeat）：每 3 小时自动执行两件事——①检查修复计划完成情况（基于 user-gym/SYNTHESIS.md 的 P0×5/P1×7/P2×4/P3×4 修复路线图）②规划并派发新的模拟测试（回归测试优先，其次新 persona/新场景）。要求：重活用 subagent，每次执行后更新本 scratchpad，必要时创建当日新文件（yyyy-mm-dd_scratchpad_heartbeat-repair-check.md）。
- Heartbeat ID: `bfd3cf1e`（名称 "VFED修复检查+测试规划"，cron `0 */3 * * *`，Asia/Shanghai，创建于 2026-09-08 11:26 北京时间，下次触发 12:00）
- 背景：前序 UX 测试（5 个模拟用户）已完成，结论见 user-gym/SYNTHESIS.md——物理内核可信但存在 4 大静默误导（rate_per_watt 1000× 单位陷阱、无 PV 电费静默归零、产量 2× 偏高未到用户界面、夜间设定点不可达致 HVAC 满速空转 13.5% 年电耗），两个官方示例最优顶在 200m² 边界为伪最优。

## 2. Key Challenges and Analysis
- 修复进度追踪：修复可能由用户/其他会话进行，心跳只能通过 git log/git status + 文件内容对照判断状态，需防误判（提交信息与实际改动不符）
- 回归验证成本：每轮测试要控制在合理规模，避免沙盒膨胀（user-gym/ 已 gitignore 但磁盘会积累）
- 知识连续性：心跳每次是独立触发，必须靠本 scratchpad + SYNTHESIS.md 恢复上下文，section 更新要自包含

## 3. High-level Task Breakdown
每次心跳执行（每 3 小时）：
- [ ] 任务一：读 SYNTHESIS.md 路线图 + 本 scratchpad → git log -15/status → P0 五项逐项标状态（未开始/进行中/已完成/已验证）→ 有新修复则派 subagent 回归验证
- [ ] 任务二：规划新一轮 user-gym 模拟测试（已修复项回归优先；新 persona 如补贴政策分析师/安装调试工程师/极端气候鲁棒性）→ TodoWrite → 并行 subagent 执行 → 新发现分级并入 SYNTHESIS.md 或独立报告
- [ ] 收尾：更新本 scratchpad（或当日新文件）+ 向用户简洁汇报（修复进度快照/新测试结论/下一步建议）

## 4. Project Status Dashboard
| 任务 | 状态 | 备注 |
|---|---|---|
| Heartbeat 创建（bfd3cf1e） | ✅ | 2026-09-08 11:26，下次触发 12:00 |
| 本 scratchpad 初始化 | ✅ | 2026-09-08 |
| 第 1 轮心跳执行 | ⏳ | 等待 12:00 触发 |
| 修复进度基线（P0 五项） | ⏸ | 尚无修复提交记录，全部"未开始"待首轮确认 |

## 5. Executor Feedback or Help Requests
- 前序测试遗留参照：user-gym/user{1..5}/report.md + user-gym/SYNTHESIS.md（P0-P3 全清单）
- 修复前基线数字（回归对照用）：609 preset 基准 66,310 kWh/yr、13.06 kWh/kg fresh、kwh_per_kg_fresh 是 sweep 目标函数；user2 杭州案例 700,288 kWh、482,797 元/年（需邮票光伏才计价）；user4 修正 PV 市场价后真实最优 150m²+40kWh、回收 5.4 年、IRR≈18%
- 注意：心跳不得擅自改 vfed/ 源码、不 commit/push；重活全走 subagent
