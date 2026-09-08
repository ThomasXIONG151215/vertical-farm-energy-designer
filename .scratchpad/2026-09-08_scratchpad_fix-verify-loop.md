# Scratchpad: VFED 修复-验证心跳账本（2h 例程）

## 1. Background and Motivation
用户指令（2026-09-08）：按 user-gym/SYNTHESIS.md 第 4 节修复路线图，每 2 小时一轮心跳——每轮派 fix subagent 修复一项 + verify subagent 独立验证，验证通过即 commit，本账本记录全部进度。
- 修复来源：user-gym/SYNTHESIS.md（P0×5 / P1×7 / P2×4 / P3×4，全部发现于 5 用户 persona 沙盒审计）
- 心跳节奏：cron `0 */2 * * *` Asia/Shanghai，每轮只修 1 项：fix → verify → commit → 更新本账本 → 向用户简报
- 与旧心跳 bfd3cf1e（3h，"检查修复进度+规划测试"，写 2026-09-08_scratchpad_heartbeat-repair-check.md）并行共存、各写各的文件，互不覆盖
- 用户确认的决策（2026-09-08）：①保留旧心跳 ②每项验证通过即 commit ③第 0 轮（P0-1）当次会话立即执行作为模板轮

## 2. Key Challenges and Analysis
- 验证独立性：verify subagent 不得只信 fix 报告——必须 pytest 全绿 + 复现原问题场景 + 基线回归三件套
- 基线管理：P0-1/2/3/5 只改经济计价/文档/警告层，物理基线必须不变（609 preset 基准 66,310 kWh/yr、13.06 kWh/kg fresh）；P0-4 修 preset 三元组会改物理基线，完成后必须记录新基线
- 重试上限：验证失败同项最多重试 2 次（fix subagent 须带失败反馈重做），之后标"需人工介入"跳到下一项
- commit 规范：`fix(P0-N)`/`feat(P1-N)`/`chore(P2-N)` 前缀 + 一行说明；只 add 本项相关文件；**不 push**
- 起点 commits（非路线图项）：fc66234（遗留 CRITICAL-1 cli 修复）、7fa43b8（scratchpad 同步 + ignore user-gym/）

## 3. High-level Task Breakdown（每轮心跳流程）
1. 读本账本 dashboard + user-gym/SYNTHESIS.md 第 4 节 → git log --oneline -10 / git status 确认状态（若有他人未提交改动，先 pytest 确认绿再单独提交，勿混入本项）
2. 取下一个待修项（顺序：P0-1→P0-5 → P1-1→P1-7 → P2 → P3）
3. 派 general fix subagent：附 SYNTHESIS 对应条目证据 + 修复要点 + 仓库 AGENTS.md 约束；改配置字段须同步 vfed/design/project.py + presets.py；跑 pytest 全绿；**不 commit**
4. 派 general verify subagent（独立验证，勿只信 fix 报告）：① pytest 全绿 ② 复现原问题场景确认修复生效 ③ 物理基线回归对照（66,310 kWh/yr；P0-4 除外需记录新基线）④ 不破坏 SYNTHESIS §7 优势项（物理内核/可复核性/性能/fail-fast）
5. 验证通过 → git add 本项相关文件 + commit（规范见上）；失败 → 本账本记录失败反馈，下轮重试（≤2 次）
6. 更新本账本 dashboard（状态/commit hash/验证结论）+ 向用户简报（本轮项/结论/下轮预告）
7. 全部完成或剩余全为"需人工介入" → 最终简报 + 建议用户删除本心跳

## 4. Project Status Dashboard

### 修复项状态表（权威进度记录）
| 项 | 内容 | 状态 | commit | 验证结论 |
|---|---|---|---|---|
| P0-1 | 统一资本单位（rate_per_watt 1000× 陷阱：PV 乘 kWp/电池乘 kWh 名实不符；example 3.5→3500 RMB/kWp 口径；C_pv 默认提市场区间；输出单位造价自证行） | 已验证 | 3155c10 | PASS-with-notes：物理基线 0.0000% 漂移（66,310 kWh/yr 逐列一致）；斜率 813.95=3500/4.3 精确；sweep 最优 200m² 边界→150m²+40kWh 内部最优；旧拼写 E001 fail-fast 带迁移指引；pytest 247 passed（229+18）；engine.py 零改动 |
| P0-2 | 无 PV 电费静默归零（energy system 禁用时按 grid_import×tariff 计价；对齐 evaluate/sweep 口径；LCOE 标注） | 未开始 | — | — |
| P0-3 | 产量 2× 警示前移（growth 节 yaml 明示番茄系数未标定、年产约为商业 PFAL 2-4×；README 警示） | 未开始 | — | — |
| P0-4 | 满载/可达性诊断（HVAC/DEH 连续满载>24h 输出 WARNING）+ 修 609 preset (T_dark,C_z,P_rated) 三元组【会改物理基线，完成后记录新基线】 | 未开始 | — | — |
| P0-5 | sweep 护栏（capital=0 警告同步到 sweep 分支；best 打印补 annual_om；边界最优提示 "optimum at grid boundary"） | 未开始 | — | — |
| P1-1 | DEH 湿控器循环模式（on/off ±deadband、满速取铭牌 SMER）与 VFD 并列 + 报告 effective SMER | 未开始 | — | — |
| P1-2 | 投资指标：CSV 补 grid_independence/self_consumption/annual_savings/payback 列（后两代码已算）+ NPV/IRR 增量口径 + 电池"允许电网充电"开关 | 未开始 | — | — |
| P1-3 | monthly.csv 加电费列 + harvest_kg 标注干/鲜 + timeseries 时间轴回卷（去 +8h 偏移） | 未开始 | — | — |
| P1-4 | RH 合规 KPI（超标小时数/p95/max/病害风险标记） | 未开始 | — | — |
| P1-5 | 物理参数词汇表（hvac/deh 30+ 字段注释 + U_wall_A/C_z 估值指引 + 输出术语 removal-limited/RH clamp/X_d 解释【P2-4 与此项合并做】） | 未开始 | — | — |
| P1-6 | transpiration/growth 逐参数注释（单位+范围+一句话语义）+ 5 方法枚举写全 + 统一默认水情景 + plants_per_m2 密度参数 | 未开始 | — | — |
| P1-7 | OPEX 默认值明示（人工 30,000+杂项 5,000 不写即生效）+ 货币量级护栏（RMB 数字贴 USD 标签问题） | 未开始 | — | — |
| P2-1 | Windows GBK 控制台 UTF-8 乱码（警告文案去 em-dash 或设 UTF-8 输出） | 未开始 | — | — |
| P2-2 | 控制台自证天气来源（pre-downloaded / cache hit / live，别染红） | 未开始 | — | — |
| P2-3 | --version + 输出显示文件名 + README 修正（5/6 methods、耗时声明、LCOE 小例子、默认坐标对齐城市表） | 未开始 | — | — |
| P3 | README "Model scope & limitations" 集中声明（P3-1..P3-4 各项） | 未开始 | — | — |

### 轮次记录
| 轮次 | 时间(北京) | 项 | 结果 | 备注 |
|---|---|---|---|---|
| 第 0 轮 | 2026-09-08 12:40 | P0-1 | ✅ 已验证+已提交(3155c10) | 模板轮：fix(方案B按组件改名 per_kwp/per_kwh/per_watt)→verify PASS-with-notes→commit |
| 第 1 轮 | 待心跳触发 | P0-2 | 排队中 | 2h 心跳接管，下一项：无 PV 电费静默归零 |

## 5. Executor Feedback or Help Requests
- 基线数字（回归对照）：609 preset 基准 66,310 kWh/yr、13.06 kWh/kg fresh、HVAC 占比 18.2%（P0-4 修复后 HVAC 占比应显著下降并记录新基线）
- user4 修正 PV 市场价后真实最优：150 m²+40 kWh、回收 5.4 年、IRR≈18%（P0-1/P1-2 验证对照）
- 各问题复现命令见 user-gym/user{1..5}/report.md（user-gym/ 已 gitignore 但磁盘保留可读）
- 未跟踪的 game-*/、plant-factory-game/、vfed-workspace.code-workspace 与本路线图无关：勿提交、勿删除
- 心跳每轮开始前若发现账本"修复中"但 git log 无对应提交且工作区干净 → 判定为上轮中断，该项重置为"未开始"重新派发
- 【P0-1 遗留观察→P0-5 范围】example_lcoe_full 最优 battery=40 顶自身 range 上限（LCOE 对 battery 单调递减）；example_sweep（legacy C_pv=500 路径）best 仍 pv=200 网格上限——市场价下经济上真实的约束最优，属 P0-5「边界提示」未修范畴，非单位残留
- 【P0-1 行为变化提醒】C_pv 默认 110→500 是类级默认：所有无 capital 块的 legacy 项目经济输出随之改变（example_sweep best LCOE 0.6879→0.7305）——P0-2/P0-5/P1-2 验证时以此为新基线，commit 3155c10 message 已点明
- 【并行心跳资产】3h 心跳 bfd3cf1e 首轮（12:00）产出：①user-gym/regression/ P0-1..P0-5 五张回归验证卡（复现命令+基线数字，verify subagent 即用）②user6 极端气候测试（Harbin/Dubai/Bangkok vs 上海，新发现并入 SYNTHESIS.md §9）
- 【本轮新增笔记】.scratchpad/2026-09-08_scratchpad_p0-1-capital-units.md（fix 笔记）、p0-regression-cards.md、user6-extreme-climate.md
- 【验证基线更新】P0-1 后的新快照：609 preset 66,310 kWh/yr / 13.06 kWh/kg 不变；example_lcoe_full capital total 115,516 RMB、PV 单价 3500 RMB/kWp 自证行；example_sweep legacy total 23,256 USD=500×46.512
