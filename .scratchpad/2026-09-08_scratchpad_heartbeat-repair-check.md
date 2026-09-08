# Scratchpad: VFED 三小时心跳 — 修复检查 + 新测试规划

## 1. Background and Motivation
用户设立常驻例程（heartbeat）：每 3 小时自动执行两件事——①检查修复计划完成情况（基于 user-gym/SYNTHESIS.md 的 P0×5/P1×7/P2×4/P3×4 修复路线图）②规划并派发新的模拟测试（回归测试优先，其次新 persona/新场景）。要求：重活用 subagent，每次执行后更新本 scratchpad，必要时创建当日新文件（yyyy-mm-dd_scratchpad_heartbeat-repair-check.md）。
- Heartbeat ID: `bfd3cf1e`（名称 "VFED修复检查+测试规划"，cron `0 */3 * * *`，Asia/Shanghai，创建于 2026-09-08 11:26 北京时间，下次触发 12:00）
- 背景：前序 UX 测试（5 个模拟用户）已完成，结论见 user-gym/SYNTHESIS.md——物理内核可信但存在 4 大静默误导（rate_per_watt 1000× 单位陷阱、无 PV 电费静默归零、产量 2× 偏高未到用户界面、夜间设定点不可达致 HVAC 满速空转 13.5% 年电耗），两个官方示例最优顶在 200m² 边界为伪最优。
- 并行心跳分工（第 1 轮确认）：另有 2h 修复-验证心跳（账本 2026-09-08_scratchpad_fix-verify-loop.md）负责 fix→verify→commit 闭环；本心跳（3h）负责进度检查 + 新测试规划。两账本并行共存、互不覆盖。user-gym/regression/ 的回归验证卡是给 fix-verify 心跳 verify subagent 的即用资产。

## 2. Key Challenges and Analysis
- 修复进度追踪：修复可能由用户/其他会话进行，心跳只能通过 git log/git status + 文件内容对照判断状态，需防误判（提交信息与实际改动不符）
- 回归验证成本：每轮测试要控制在合理规模，避免沙盒膨胀（user-gym/ 已 gitignore 但磁盘会积累）
- 知识连续性：心跳每次是独立触发，必须靠本 scratchpad + SYNTHESIS.md 恢复上下文，section 更新要自包含

## 3. High-level Task Breakdown
每次心跳执行（每 3 小时）：进度检查 → 测试规划/执行 → 收尾（更新本 scratchpad + 简洁汇报）

**第 1 轮（2026-09-08 12:00）✅**
- [x] 进度检查：SYNTHESIS.md 路线图 + git log/status → P0-1 修复中（fix-verify 心跳，fix subagent 11:39 派出，尚无 commit）、P0-2..P0-5 未开始、最新 commit 7fa43b8、工作区无未提交源码改动
- [x] 回归就绪包：user-gym/regression/README.md — P0-1..P0-5 五张回归验证卡（复现命令全部实跑验证，基线数字当前 HEAD 全部对上）
- [x] user6 极端气候测试：Harbin/Dubai/Bangkok vs 上海 → user-gym/user6/report.md，4 项新发现已并入 SYNTHESIS.md §9

**第 2 轮（2026-09-08 15:00）预告**
- [ ] 若 P0-1 已 commit → 用回归卡 P0-1 独立交叉验证（与 fix-verify 心跳的 verify 互补）
- [ ] 继续规划新测试（新 persona/新场景）
- [ ] 收尾：更新本 scratchpad + 简洁汇报

## 4. Project Status Dashboard
| 任务 | 状态 | 备注 |
|---|---|---|
| Heartbeat 创建（bfd3cf1e） | ✅ | 2026-09-08 11:26，cron `0 */3 * * *` |
| 本 scratchpad 初始化 | ✅ | 2026-09-08 |
| 第 1 轮心跳执行（2026-09-08 12:00） | ✅ | 进度基线 + 回归就绪包 + user6 极端气候测试 |
| 修复进度基线确认 | ✅ | P0-1 修复中（fix-verify 心跳第 0 轮，fix subagent 11:39 派出，尚无 commit）；P0-2..P0-5 未开始；最新 commit 7fa43b8（scratchpad 同步）；工作区无未提交源码改动 |
| user-gym/regression/README.md | ✅ | P0-1..P0-5 五张回归验证卡；复现命令全部实跑验证；基线数字当前 HEAD 全部对上 |
| user-gym/user6/report.md | ✅ | 极端气候测试 Harbin/Dubai/Bangkok vs 上海；4 项新发现已并入 SYNTHESIS.md §9 |
| 下轮（15:00）预告 | ⏳ | 若 P0-1 已 commit → 回归卡 P0-1 独立交叉验证（与 fix-verify 的 verify 互补）；继续规划新测试 |

## 5. Executor Feedback or Help Requests
- 前序测试遗留参照：user-gym/user{1..5}/report.md + user-gym/SYNTHESIS.md（P0-P3 全清单）
- 修复前基线数字（回归对照用）：609 preset 基准 66,310 kWh/yr、13.06 kWh/kg fresh、kwh_per_kg_fresh 是 sweep 目标函数；user2 杭州案例 700,288 kWh、482,797 元/年（需邮票光伏才计价）；user4 修正 PV 市场价后真实最优 150m²+40kWh、回收 5.4 年、IRR≈18%
- 注意：心跳不得擅自改 vfed/ 源码、不 commit/push；重活全走 subagent

### 第 1 轮关键发现（2026-09-08 12:00）
- user6 新发现（已并入 SYNTHESIS.md §9）：N-1 严寒全年零制热（heat_pump 死代码，P1 能力缺口）；N-2 Dubai 光期静默超温 1,068h 无告警（P0-4 诊断须双向）；N-3 气候归一化失效（77.7K 温度跨度仅 -5.4%~+6.4% 能耗极差，选址筛选失效，P1 适用域声明）；N-4 负提升程 COP=4.5 假运行（P3-1 扩展）。评分：物理可信度 3.5/5、极端气候适用性 2/5
- 回归卡制作意外发现：parameter_ranges 不接受 min==max（两点网格绕过）；所有 SYNTHESIS 基线数字当前 HEAD 全部对上、无失配；P0-1 判据对两种修复形态均鲁棒
