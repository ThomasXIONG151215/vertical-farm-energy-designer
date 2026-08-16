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
