# 2026-08-16 Scratchpad — VFED 仿真架构代码审查与修复

## 1. Background and Motivation

用户请求对 VFED 整体仿真架构做代码审查（原文："希望你检查整个仿真架构看有哪些潜在隐患和传热传质能源调度方面的错误计算"）。审查已完成，输出为项目根目录 `REVIEW.md`（未提交，untracked）。审查聚焦：传热传质（潜热/显热口径、太阳时）、能源调度（PV/电池/电网记账、LCOE）、以及设备模型参数合理性。

状态：用户已批准审查计划，**等待 approve 后实施修复**。6 个问题全部标记 pending。

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
| 2 | 【CRITICAL】修复 HVAC 潜热双重复计（hvac.py:157 + engine.py:342-343 q_removal_corr） | pending | approve |
| 3 | 【CRITICAL】修复 weather_bridge.py:67 太阳时符号 + 补乌鲁木齐测试用例 | pending | approve |
| 4 | 【MAJOR】修复 DEH 风机功率热未计入房间热平衡 | pending | **explore agent 调研** → approve |
| 5 | 【MAJOR】修复 energy_system.py:53,95 power_deficit/TLPS 语义 | pending | approve |
| 6 | 【MAJOR】对齐/删除 calculate_metrics LCOE 两套实现 | pending | approve |
| 7 | 【MINOR】校准 pv.py 铭牌参数 + 处理 eta_pv 死字段 | pending | approve |
| 8 | 回归测试 + pytest 全量验证 | pending | 2–7 每项之后 |

并行组标记：`[2 | 3 | 4 | 5 | 6 | 7]` 相互独立（4 需先完成前置调研）；`7 → 8` 顺序。

## 4. Project Status Dashboard

### 审查发现（6 问题，均待修复）

| # | 级别 | 位置 | 问题 | 修正方案 |
|---|------|------|------|----------|
| 1 | CRITICAL | `src/devices/hvac.py:153-158` + `src/design/engine.py:342-343` | HVAC 除湿潜热双重复计：Q_target 扣整段总冷量（温度方程），M_target 又扣潜热（湿度方程）→ 房间偏冷、HVAC 能耗低估。注：engine.py:322-327 注释声称 E_trans 与 M_deh 稳态抵消仅对 DEH 成立 | hvac.py:157 改显热口径 `-(shr·Q_total − fan)`；engine.py 修正 q_removal_corr 的 HVAC 项 `+(1-scale)·M_hvac_nom·L_v` 符号/语义错误（DEH 项正确，HVAC 项多余） |
| 2 | CRITICAL | `src/weather/weather_bridge.py:67` | 太阳时符号错误：`lst = hour + minute/60 + (lon/15.0 − tz_hours)`，应为 `hour + tz_hours − lon/15`。上海偏差 0.2h 可忽略；乌鲁木齐(lon=87.6, tz=8) 偏差 ~4.3h → 时角 ~65°，PV 几何严重失真 | 符号翻转 + 补乌鲁木齐测试用例 |
| 3 | MAJOR | `src/devices/dehumidifier.py:129-130` | DEH 风机功率热未计入房间热平衡：P_elec=P_comp+fan_power_w（记账含风机），但 Q_target=Q_dh=P_comp+m_dh·h_fg 不含风机热（默认 40W） | **先派 explore agent 查 DEH/除湿机风机功率实际典型值及散热去向**，再定修复（fan_power 默认值合理性 + 散热是否入房间） |
| 4 | MAJOR | `src/pvbes/energy_system.py:53,95` | power_deficit/TLPS 语义错误：`power_deficit=max(0,load−pv)` 只减 PV 不减电池放电；电池可覆盖时仍计失电 | 计入电池放电 或 重命名 |
| 5 | MAJOR | `src/pvbes/energy_system.py:57-68` vs `sweep.py`/`engine.py` `_compute_lcoe` | LCOE 两套实现不一致：calculate_lcoe 用单一 lifetime CRF；主路径 _compute_lcoe 按组件折旧年 CRF。sweep 中忽略 calculate_metrics 的 lcoe 字段 | 对齐或删除 calculate_metrics 的 LCOE |
| 6 | MINOR | `src/devices/pv.py:22,27-28,71` | 铭牌参数不符 + eta_pv 死字段：V_mp_stc·I_mp_stc=46·13.33=613W 与 Jinko 78HL4-BDV 真实铭牌(~570-580W)不符 → n_modules 偏小；eta_pv=0.233 定义后从未使用 | 校准 V_mp·I_mp，启用或删除 eta_pv |

### 任务状态

| 任务 | 状态 |
|------|------|
| 审查探索（完整 Review Report 输出） | done |
| REVIEW.md 创建（项目根目录） | done |
| 6 项修复（问题1–6） | pending（等用户 approve） |
| 问题3 前置调研（explore agent 查 DEH 风机功率/散热） | pending（用户要求） |
| 回归测试 + pytest（每项修复后） | pending |

### 核查通过清单（无问题模块）

psychrometrics.py、shr.py、envelope.py、ode.py、battery.py、transpiration.py（stomatal P-M 与 FAO-56 一致）、van_henten.py、dehumidifier.py SMER 换算、compressor.py、led.py、engine.py 时步/功率汇总/收割/ES 块、grid.py/Tariff —— 单位与守恒核查通过。

## 5. Executor Feedback or Help Requests

### 给执行者的反馈/请求

1. **问题3 需外部调研**（用户明确要求）：修复前先派 explore agent 上网查 DEH/除湿机风机功率实际典型值及最终散热去向（是否排入室内），据此判定 fan_power 默认值 40W 合理性及 Q_target 是否应含风机热。调研结果将决定修复口径，**不要自行拍板修复**。
2. **问题1 修复注意**：engine.py:322-327 注释声称 "E_trans 与 M_deh 稳态抵消" 仅对 DEH 成立，HVAC 项修正时不要沿用该假设；修正后需确认焓平衡（温度方程只扣 Q_sens=shr·Q_total，冷凝热在室外排出）。
3. **问题2 补测试**：符号翻转后补乌鲁木齐（lon=87.6, tz=8）太阳时用例，验证时角不再失真。
4. **问题6 数据来源**：Jinko 78HL4-BDV 真实铭牌 (~570-580W) 需在修复时给出引用来源，遵循 AGENTS.md "No hardcoded science"。

### Git 状态

- 最近 commit：`bb23745`（feat(web): browser-side weather fetch via pyodide, vfed-web UI rework）
- 未跟踪：`REVIEW.md`（审查产物，待修复实施后一并提交）
