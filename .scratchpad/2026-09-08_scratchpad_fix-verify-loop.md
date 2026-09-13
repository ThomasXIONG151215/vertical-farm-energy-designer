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
| P0-2 | 无 PV 电费静默归零（energy system 禁用时按 grid_import×tariff 计价；对齐 evaluate/sweep 口径；LCOE 标注） | 已验证 | 93add0f | PASS：evaluate lcoe 0.6284 == sweep (0,0) 逐位一致（0.004%）；邮票实验跳变消除（0.6284 vs 0.6281, 0.048%）；物理基线逐位不变（66,309.99 kWh/yr、13.0615 kWh/kg、5,076.75 kg）；pytest 251 passed（247+4）；engine enabled 路径零触碰 |
| P0-3 | 产量 2× 警示前移（growth 节 yaml 明示番茄系数未标定、年产约为商业 PFAL 2-4×；README 警示） | 已验证 | 3079495 | PASS 全 8 项：yaml 注释 3/3 要素（tomato/2-4x/optimistic）；README 双语两处警示；物理基线逐位不变（66,309.99 kWh/yr、13.0615 kWh/kg、5,076.75 kg）；pytest 251 passed；engine/plants/physics 零改动 |
| P0-3R | 生菜参数标定（用户指令真修 P0-3）：c_rad_phot 1e-8→3.5e-9 kg/J（番茄→生菜，单参数） | 已验证 | 9a9fd01 | PASS 全 16 项：年产 112.26→44.51 kg fresh/m²/yr 落 30-60 商业带中值（硬判据逐位复现）；新基线 62,452.72 kWh/yr / 31.177 kWh/kg / 水量 10.40 m³ / HVAC 10,170 / 暗期满速 165/2920 静默；守恒 0.04%（水量 99.96%）；pytest 267 passed（266+1 含新产量带锁定用例）；yaml/README 警示改写为"已标定+残余不确定性"无矛盾残留 |
| P0-4 | 满载/可达性诊断（HVAC/DEH 连续满载>24h 输出 WARNING）+ 修 609 preset (T_dark,C_z,P_rated) 三元组【会改物理基线，完成后记录新基线】 | 已验证 | 896db3b | PASS：新基线 64,184 kWh/yr / HVAC 10,393（16.2%）/ 暗期满速 195/2920 / 暗期均温 22.32°C（设定 21，偏差 1.32K）/ 12.7060 kWh/kg；双向告警（cooling/heating/DEH）真实+合成双验证；pytest 262 passed（251+11）；物理守恒全保；ODE/设备模型零触碰 |
| P0-5 | sweep 护栏（capital=0 警告同步到 sweep 分支；best 打印补 annual_om；边界最优提示 "optimum at grid boundary"） | 已验证 | 28e3a71 | PASS：266 passed（262+4）；数值零漂移（sweep CSV 100×24 逐位一致）；evaluate 输出逐字不变；单点 sweep 补 LCOE/annual_om/Capital total+capital=0 警告（与 evaluate 同源常量逐字一致）；边界提示 pv=200/battery=40 命中、pv=150 内点不误报；物理基线 64,184 kWh/yr / 12.7060 逐位不变（P0-3R 前口径） |
| P1-1 | DEH 湿控器循环模式（on/off ±deadband、满速取铭牌 SMER）与 VFD 并列 + 报告 effective SMER | 已验证 | 50f6774 | PASS 全 7 项：默认 vfd 逐位不变（62,452.72/31.177 复现）；on_off 满速精确回铭牌 2.000；双口径 SMER（effective 1.325 名义/delivered 0.775 实际）独立复算一致；pytest 279 passed（267+12）；物理路径零改动；非法 control 值 exit 1 |
| P1-2 | 投资指标：CSV 补 grid_independence/self_consumption/annual_savings/payback 列（后两代码已算）+ NPV/IRR 增量口径 + 电池"允许电网充电"开关 | 已验证 | e1ffde2 | PASS 全 7 项：diff 审查 6 文件全落范围（engine.py 仅 1 行透传，默认关）；sweep CSV 24→32 列（8 新列，与 evaluate 命名一致）；独立复算 NPV maxrel 1.13e-14/IRR 6.66e-16/savings 1.82e-12（机器精度）；(0,0) 行 0/inf/NaN 语义正确；零漂移（609 基线 12 项全中+example_sweep 24 旧列×100 行 bitwise）；谷充 confined {0-5,22,23} 账单 −11.7%、往返比 0.8275≈η²、缺省=显式 false；pytest 305 passed（279+26 新 test_08_investment.py） |
| P1-3 | monthly.csv 加电费列 + harvest_kg 标注干/鲜 + timeseries 时间轴回卷（去 +8h 偏移）【已拆 P1-3a 输出管道 / P1-3b 时间轴两步】 | 已验证 | 1f6f918 + 7aed25f | P1-3a PASS 全 7 项：pytest 318 passed（305+13 新 test_09_output_columns.py）；物理零漂移（62,452.72/31.177/6,245.27/LCOE 0.6608 逐位，timeseries.csv bitwise 不变，sweep 32 列对 HEAD bitwise identical）；monthly 新列验收：electricity_cost 12 月合计 6245.272、grid_import_kwh 62452.72、water_m3 10.405、harvest_fw_kg 月度纯事件 1974.02；standing 单列 1.4574 不再并入 m1（m1.harvest_kg=8.296396 纯事件）；summary 7 新标量+literal_eval 全格通过 0 np.repr；README 双语列字典。**P1-3b PASS 全 6 项（见第 9 轮）**：pytest 327 passed（318+9 新 test_10_time_axis.py）；city 对齐守卫+51 城重生成+timestamp/price 列；**city 路径基线迁移 62,452.72→62,444.50；example_sweep 经济基线不迁移（r5 bitwise 复现确认）** |
| P1-4 | RH 合规 KPI（超标小时数/p95/max/病害风险标记） | 已验证 | fe3b2ac | PASS 全 7 项（见第 10 轮）：pytest 335 passed（327+8 新 test_11_rh_compliance.py）；物理零漂移（62,444.50/31.0499/100.55/6,244.45/LCOE 0.6608 逐位）；summary 6 新标量实测 65.0/7095h(81.0%)/0.8099/69.1/69.49/0；ts RH_z 同源重算逐位自洽；monthly rh_exceed_hours 12 月合计=summary；阈值 (0,100] fail-fast + 50% 触发用例过；literal_eval 全格 0 失败 |
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
| 第 1 轮 | 2026-09-08 14:20 | P0-2 | ✅ 已验证+已提交(93add0f) | 心跳轮：fix(tariff 按全负荷计价+sweep 同缺陷同修+CLI 自证行)→verify PASS 全 5 项→commit |
| 第 2 轮 | 2026-09-08 16:25 | P0-3 | ✅ 已验证+已提交(3079495) | 心跳轮：fix(yaml 模板 7 行 WARNING+README 双语警示，纯文档层)→verify PASS 全 8 项→commit |
| 第 3 轮 | 2026-09-08 18:40 | P0-4 | ✅ 已验证+已提交(896db3b) | 心跳轮：fix(仅改 T_dark 18→21.0+engine 汇报层双向满载诊断+CLI WARNING)→verify PASS 8 项声明全证实→commit 896db3b+新基线写回回归卡 |
| 第 4 轮 | 2026-09-08 20:15 | P0-5 | ✅ 已验证+已提交(28e3a71) | 心跳轮：fix(共享警告常量+单点 sweep 经济自证行+边界提示纯 ASCII)→verify PASS 全项→commit |
| 第 5 轮 | 2026-09-08 21:31 | P0-3R | ✅ 已验证+已提交(9a9fd01) | 用户指令插队轮：fix(生菜单参数标定 3.5e-9+文档/警示全面改写+测试带更新)→verify PASS 全 16 项→commit |
| 第 6 轮 | 2026-09-11 09:28 | P1-1 | ✅ 已验证+已提交(50f6774) | 中断恢复轮：前次派发被取消留下半成品，fix subagent 审查后沿用补全（口径缺陷修正：effective 改名义口径+delivered 并列）→verify PASS 全 7 项→commit |
| 第 7 轮 | 2026-09-12 | P1-2 | ✅ 已验证+已提交(e1ffde2) | 会话直执轮：fix（NPV/IRR/payback/savings/self-consumption 8 新列 + battery.allow_grid_charging 开关默认关）→ 三路并行 verify 全 PASS（①P1-2 独立交叉验证 round6 ②P0-1..P0-5+P0-3R 回归卡复跑 ③P1-1 复核+已修项代码特征抽查）→commit；报告 user-gym/regression/crosscheck_round6_p1-2.md / recheck_p0_cards_20260912.md / recheck_p1-1_features_20260912.md |
| 第 8 轮 | 2026-09-12 | P1-3a | ✅ 已验证+已提交(1f6f918) | 用户确认拆 a/b 轮：fix（additive 输出管道：monthly grid/cost/water/fw 列 + summary 7 标量 + standing 单列 + summary CSV json-safe + README 双语列字典；general subagent 实现）→ 主会话独立 verify PASS 全 7 项（含 sweep bitwise 与 yaml 混淆假警报排查，见 Executor Feedback）→commit；工件 %TEMP%\opencode\p13a\；scratchpad 2026-09-12_scratchpad_p1-3a-output-pipeline.md |
| 第 9 轮 | 2026-09-12 | P1-3b | ✅ 已验证+已提交(7aed25f) | 用户确认「启动」轮：fix（①weather_bridge.py:246-280 city 路径 P4-16 式对齐守卫+tz_localize(None) 剥离假 UTC 标签，不满足→纯 ASCII WARNING 沿用禁插值 ②data/weather 51/51 城在线重生成对齐窗（0 降级，原件备份 %TEMP%\opencode\p13b\backup\）③engine.py:1030-1035 ts 末尾 additive timestamp/price 两列 ④tests/test_10_time_axis.py 9 新测+test_09 Shanghai 钉迁移 ⑤README 双语时间轴口径）→ 主会话独立 verify PASS 全 6 项（pytest 327 独立复跑/diff 审查物理零触碰/evaluate 新基线逐位/CSV 断言全过含 ts 单调无重复+m1=744h+price 循环+literal_eval/**sweep 23 数值列对 r5 bitwise identical 经济基线不迁移**）→commit；scratchpad 2026-09-12_scratchpad_p1-3b-time-axis-alignment.md |
| 第 10 轮 | 2026-09-12 | P1-4 | ✅ 已验证+已提交(fe3b2ac) | 用户确认「启动」轮：fix（①project.py SetpointConfig 加 rh_disease_risk_threshold=85.0（灰霉病风险带下沿，reporting-only）+(0,100] fail-fast 校验+cli.py 模板注释同步 ②engine.py summary 6 新标量 rh_setpoint_pct/rh_exceed_hours/rh_exceed_pct/rh_p95_pct/rh_max_pct/rh_disease_risk_hours（同源 RH_z_out，物理零触碰）+risk>0 纯 ASCII WARNING ③monthly 加 rh_exceed_hours 月度列 ④tests/test_11_rh_compliance.py 8 新测 ⑤README 双语 RH 合规说明）→ 主会话独立 verify PASS 全 7 项（pytest 335 独立复跑/diff 审查/evaluate 独立实跑基线全中/KPI 6 钉值 MATCH/ts 同源重算自洽/monthly 合计=summary/literal_eval 0 失败）→commit；scratchpad 2026-09-12_scratchpad_p1-4-rh-compliance-kpis.md |

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
- 【P0-2 行为变化提醒】无 PV evaluate 的 lcoe 0.5284→0.6284、specific_cost_per_kg 变为含电费口径（~7.21→8.21）——后续 P0-3/P0-5/P1 项验证对照经济数字时以此为准（回归卡 L244 联动规则）
- 【P0-2 遗留观察】flake8 用 verify 严格参数（max-line-length=100）有 6 处存量告警（cli.py:435/project.py:244 E501、engine.py:878-879/pv.py:58/weather_bridge.py:201 F841），CI 实际参数（120 + ignore E501/F841）下干净 exit=0——非本修复引入，暂不处理
- 【独立交叉验证 round 2（2026-09-08，HEAD=a57fe60）】P0-1/P0-2 双 PASS + pytest 251 passed；报告：user-gym/regression/crosscheck_round2.md。**基线勘误**：example_sweep legacy best LCOE 可复现值为 **0.7300**（非 0.7305）——已用临时 worktree 检出 3155c10 + 同一 weather_cache 重跑逐位复核（0.7300/capital 23,256 完全一致），P0-2 对 enabled 路径零漂移；0.7305 判定为当时心跳环境性偏差（疑似联网实拉天气）。后续 P0-5/P1-2 验证以 **0.7300** 为准。另：沙盒 venv user1 无 pytest，交叉验证用系统 Python 3.12.6（251 passed 与账本一致）
- 【P0-3 遗留观察】turnaround_days（茬间空床）未做：需 engine.py 年化逻辑 365/(cycle+turnaround) 改动，超出文档层安全边界，留独立任务；cli.py 实际新增 6 行注释（fix 报告称 7 行含 banner 计数差 1，无实质影响）
- 【P0-3 验证注意】基线复现必须用 preset 默认坐标（奉贤 30.9/121.5）——verify 曾误用 --lat 31.23 --lon 121.47 触发坐标覆盖 WARN，得到 66,285 kWh/yr（0.04% 偏差），属复现参数错误非 fix 缺陷
- 【P0-3 行为变化】无：纯警示/文档层，所有数值输出逐位不变（P0-2 后经济基线仍为准：无 PV lcoe 0.6284、specific_cost_per_kg 含电费口径）
- 【P0-4 新物理基线（权威，896db3b）】609 preset @Shanghai2025：annual load 64,184 kWh/yr、HVAC 10,393 kWh/yr（16.2%）、暗期满速 195/2920、暗期均温 22.32°C（T_dark=21）、kwh_per_kg_fresh 12.7060、暗期 min T_z 21.67——**P0-5 及全部 P1/P2/P3 验证以此为准**（旧基线 66,310/13.0615 已作废）；回归卡 user-gym/regression/README.md 卡 P0-4 下表已写回
- 【P0-4 行为变化提醒】preset_609 显式 T_dark=21.0（原走默认 18）；SetpointConfig 类默认 18 不变，default preset 不受影响（回归 17,586 kWh/yr 正常无告警）；已生成的旧 yaml（T_dark=18）不受影响且会触发满载 WARNING（设计使然，是诊断正确性的证据）
- 【P0-4 遗留观察】①满速口径双轨：summary 子步≥99% 口径 210h vs p04_night_check.py 能量口径 195h（mod≈0.997 边缘差异，均 <<1460 通过阈）；②DEH 满载阈值 60%（609 修复后 49.8%/default 41.3% 属正常态，病理才趋近 100%）；③T_dark=21 均温偏差 1.32K 距 1.5K 上限余量 0.18K，换天气年份/围护改动需复验；④vfed-web/worker.js 生成物未同步（无功能影响）
- 【P0-5 遗留观察】example_sweep legacy best LCOE 0.7300 勘误修订：HEAD 实跑与 worktree 复核均为 0.7305（CSV 0.730473），0.7300 判定为当时环境状态差异（cache 重算告警佐证）——后续 P1-2 验证以 0.7305 为准；回归卡 P0-5 判据为"输出行为"非具体数值
- 【P0-3R 权威基线（9a9fd01，已被 P1-3b 对齐窗基线取代，旋转窗口径历史存档）】609 preset @Shanghai2025（45 m²）：annual load 62,452.72 kWh/yr、kwh_per_kg_fresh 31.177、年产 2,003.17 kg 鲜重（44.51 kg/m²/yr）、干重 100.16 kg、水量 10.40 m³、HVAC/DEH/LED 10,170/10,235/42,048 kWh、暗期满速 165/2920（静默）、暗期均温 22.31°C、LCOE(无资本) 0.6608、grid cost(no PV) 6,245.27 USD/yr——P1-3b（7aed25f）起作废，验证一律用下方 P1-3b 新基线；旧基线 64,184/12.7060（P0-4）与 66,310/13.0615（P0-4 前）均已作废；回归卡 user-gym/regression/README.md P0-3R 节已记录全套数字+复现命令
- 【P1-3b 新权威基线（7aed25f，city 路径对齐窗，替代 P0-3R 基线）】609 preset @Shanghai2025（45 m²，--city Shanghai + 仓库根 weather_cache）：annual load 62,444.50 kWh/yr、kwh_per_kg_fresh 31.0499、年产 2,011.10 kg 鲜重（44.69 kg/m²/yr）、干重 100.55 kg、standing 1.4617 kg（单列不落月）、水量 10.37 m³、HVAC/DEH/LED 10,163.59/10,232.91(comp 9,882.51)/42,048 kWh、LCOE(无资本) 0.6608、grid cost(no PV) 6,244.45 USD/yr、m1=744h/4,941.19 kWh/电费 494.12、收割事件月 [1,3,4,5,6,7,8,9,10,11,12]（Feb=0）、m1 事件 8.3285 kg——**P1/P2/P3 全部验证以此为准**；旧 P0-3R 基线 62,452.72/31.177/100.16/6,245.27（旋转窗口径）作废为历史；62,446.74 预期值系 lat/lon 缓存路径口径（POA 几何略异，−0.004%），city 路径实测 62,444.50 为准
- 【P1-3b 重要反转：example_sweep 经济基线不迁移】窗口对齐对 sweep 零影响——r4_p05_example_sweep.yaml 走 lat/lon 缓存路径（P4-16 抓取管线本就产出对齐窗），51 城重生成只动 data/weather city 文件；独立实跑确认 23 个数值列对 r5_example_sweep_results.csv **bitwise identical（0 changed）**，best LCOE 0.7697603292315144/capital 23,255.81395348837/dry 77.57 不变；第 8 轮预告的「sweep 基线整体迁移」不成立，撤销该预期
- 【P0-3R 遗留观察】①单参数标定：c_resp_d/c_alpha_beta 沿用文献值，生长曲线形状未做两点校准（有 609 逐茬称重数据时可做 c_rad_phot 定量级+c_resp_d 定形状）；②30-60 带按 m² 栽培面积口径应用，建筑面积口径文献数不可直接对比（已写入注释）；③kwh_per_kg 12.7→31.2 为产量回归带后的分母效应，负荷实际下降 2.7%——后续验证防误判为回归；④回归卡 --city Shanghai 路径坐标写 31.23/121.47 但因 preset-609 city 文件优先收敛到同一气象文件，结果逐位一致（verify 实测），建议回归卡注明
- 【P1-1 行为变化/方向反转】609 场景下 vfd 反而比 on_off 省电 47.7%（DEH 10,235 vs 19,584 kWh/yr；全楼 62,453 vs 73,435）——user3 的「VFD 贵 56%」系其特定场景结论，在 609 小湿库存场景不成立（on_off 满速脉冲致 27.0t 名义除湿被库存 cap 浪费、利用率仅 30%）；可见性目标经双口径报告达成，向 user3 persona 交代时注意方向
- 【P1-1 基线复现坐标澄清】P0-3R 权威基线（62,452.72/31.177）须用回归卡命令 --city Shanghai（坐标 31.23/121.47）；--lat 30.9 --lon 121.5 是另一站点（62,261.59/30.9442），勿混用——修正账本早期「两路径逐位一致」的表述
- 【P1-1 遗留观察】on_off 模式会触发 P0-4 满载 WARNING（8739h 满速，99.8%）——bang-bang+库存钳位的预期形态非缺陷；deh_smer 的 None 分支（DEH 全年未运行）仅代码审阅无运行时用例
- 【P1-1 测试计数勘误】fix 报告称 +8（基线 271）系记数笔误，实际 +12（267→279：devices 6/config 3/engine 级 3）；终值 279 正确
- 【P1-2 权威经济基线（e1ffde2）】example_sweep 32 列 CSV：best=pv200+batt0+ppfd300 三边界，LCOE 0.7698（CSV 0.7697603292315144）、capital 23,255.814 USD、dry 77.57 kg——新增 8 列：grid_independence/self_consumption/annual_savings/payback_years/npv_25yr/irr_pct（增量口径，vs 无 PV 基线）；P1-3+ 验证经济列以此为准；旧 24 列 bitwise 不变
- 【P1-2 遗留观察（7 条非阻断）】①evaluate summary 无 savings/payback 列（仅 sweep 侧）②单点 sweep 控制台不打投资块 ③README 未同步新列 ④谷充 C-rate 理论越限（实际 0 发生）⑤N-5 子项（CO2/月度发电）顺延 ⑥pv=0+batt 自放电微循环（既有、bitwise 同 round5）⑦基线对照须仓库根 cache + r5_example_sweep_results.csv（regcache 0.76924 变体勿用）
- 【三路复核记录（2026-09-12，HEAD=e1ffde2 后）】①P0-1..P0-5 回归卡复跑全 PASS（P0-1 capital_pv@200m²=162,790.70 RMB；P0-2 grid_cost_net=6245.27 与 sweep(0,0) 逐位等；P0-3 警示 3 要素+31.177/44.51/100.16 全中；P0-4 暗期满速 165/2920+T_dark=35 双向告警；P0-5 单点+best+C_pv=0 边界全过）；②P1-1 复核全 PASS 逐位（vfd 62,452.72/31.177/SMER 1.325/0.775；on_off 73,435.29/19,583.84/2.000/满载 8739h）；③已修项代码特征抽查全在——漂移归因均非回归
- 【P0-2 代码位置勘误】禁用路径计价实际落点 engine.py:1137-1153 + cli.py:585 自证行 + sweep.py（早期记录笼统写 energy_system.py，后者仅启用路径 tariff）
- 【P1-1 on_off SMER 补录】on_off delivered SMER=0.598（账本原只录 vfd 口径 0.775；effective 2.000=铭牌满速、vfd delivered 0.775、on_off delivered 0.598 三口径并存）
- 【环境注意】vfed CLI 不在系统 PATH（沙盒命令须用 user1 venv exe 绝对路径）；user1 venv 无 pytest（回归卡 $PY 照抄会失败，须系统 Python）；`-k engine_deh` 会漏 engine_reports_deh 用例，点名补跑
- 【P1-3a 新列与验收数字（1f6f918）】monthly 新列：electricity_cost/grid_import_kwh/water_m3/harvest_fw_kg（grid-only）；PV 启用另加 pv_generation_kwh/grid_export_kwh/battery_net_kwh；summary 新标量：annual_led_kwh/annual_hvac_kwh/hvac_pct/deh_pct/led_pct/misc_pct（0-1 分数，0.30=30%）/harvest_final_standing_kg；save_summary_csv 已套 _ensure_json_safe（literal_eval 全格可解析）
- 【⚠ sweep 基线 yaml 警示】r5 权威基线（LCOE 0.76976/capital 23,255.814/dry 77.57）对照必须用 `user-gym/regression/r4_p05_example_sweep.yaml`（C_pv=500 legacy 回退计价 C_pv×kWp）；**勿用 `p05_example_sweep.yaml`（C_pv=110，市场价）**——后者 best capital_pv=5116.28（0.22×），曾引发假警报；物理列两 yaml 逐位一致，仅资本计价不同
- 【P1-3a fw 双口径】月度 harvest_fw_kg 合计 1974.02 = 纯收割事件口径（annual−standing 换算）；年度 annual_harvest_fw_kg 2003.17 含年末在田 standing——两口径均正确，README 已写明，验证勿混
- 【P1-3b 排队预告→已完成（第 9 轮）】①city 摄取路径 P4-16 式对齐守卫 ✅（weather_bridge.py:246-280，WARNING+沿用禁插值）②50 城数据重生成 ✅（51/51 在线成功，对齐窗+去 +00:00 误导标签）③ts ISO8601 timestamp+price 列 ✅（additive）④基线迁移重记录 ✅（仅 city 路径迁移 62,444.50；example_sweep 不迁移——见上方反转条目）；离线降级 relabel 路径已实现未实测（网络全程可用，守卫对旋转窗文件告警已由测试覆盖）
- 【P1-4 实测 RH 基线（fe3b2ac，609@Shanghai2025 对齐窗）】rh_setpoint 65.0 / exceed 7095h（81.0% 小时超标）/ p95 69.1 / max 69.49 / disease-risk(≥85%) 0h——DEH 控制偏差（81% 超标）现已可见；max 69.49 远低于 user3 时代的 93.98%，系 P0-3R 蒸腾标定后湿负荷下降所致（历史对照勿误判回归）；基线不触发 WARNING（max<85），触发逻辑由 50% 阈值用例验证
- 【P1-4 配置口径】setpoints.rh_disease_risk_threshold 默认 85.0（reporting-only，无设备行为依赖）；校验 (0,100] fail-fast（0 排除——全时风险阈值无意义）；exceed 口径严格 >setpoint、risk 口径 ≥threshold
- 【CLI 勘误】evaluate 无 --city 参数（city 在 yaml site.city；--city 是 design new 的参数）——回归卡早期「--city Shanghai」实指 design new 阶段；evaluate 复现只须 yaml 内 site.city=Shanghai + --cache weather_cache
