# Scratchpad — P0-1 统一资本单位（rate_per_watt 1000× 陷阱修复）

## 1. Background and Motivation

- 5 用户审计（user-gym/SYNTHESIS.md P0-1）：`rate_per_watt` 名义"每瓦"，实际 PV 乘 kWp（sweep.py:113）、电池乘 kWh、LED/HVAC 乘 W —— 同名字段三种单位基。
- 实锤：example_lcoe_full.yaml `rate_per_watt: 3.5` → 46.5 kWp 光伏总价仅 162.79 RMB（差 1000 倍）；capital_pv 斜率 0.814 RMB/m² = 3.5 RMB/kWp（user4 pandas 拟合）。
- legacy 默认 C_pv=110 USD/kWp 低于市场 4-8 倍（中国工商业分布式 2025 ≈ 3000-3500 RMB/kWp ≈ 420-490 USD/kWp）。
- 后果：两个官方示例 sweep 最优都顶在 200 m² 扫描上限（边界伪最优）。

## 2. Key Challenges and Analysis

- **方案选择**（任务给出 A/B 两选一）：
  - A = PV 的 per_watt 改为真乘 Wp：需启发式市价区间护栏区分新旧意图，且护栏随货币（JPY/RMB/USD）漂移，可能误杀合法值。
  - B = 改名 + 明示单位（**已选**）：新增 `per_kwp`（PV）/ `per_kwh`（电池）模式与字段；pv/battery 上的旧 `per_watt` 拼写加载即 fail-fast 报错并给出迁移指令 —— 零静默语义变更、零启发式、模式名自带计价基数。
- **向后兼容**：LED/HVAC/DEH 的 per_watt（×W）语义本就正确，保持不变；电池数值语义不变（500×kWh → per_kwh: 500 同数）；PV 旧拼写被拒绝而非静默重释。
- C_pv 默认 110 → 500（USD 锚定市场区间中值 ≈ 3.5 RMB/W @7.2）。
- engine.py 接口不动：capital 解析集中在 sweep._resolve_capital/_total_capital，engine 只是调用方。
- vfed-web 不产生 capital 块（已 grep 验证），worker.js 为 bundle.py 生成物，改完 vfed/ 需重跑 bundle（遗留项）。

## 3. High-level Task Breakdown

1. [DONE] 读 AGENTS.md / sweep.py / project.py / pv.py / cli.py / 3 个示例 yaml / README / user-gym 证据
2. [DONE] 基线 pytest：229 passed (96s)
3. [DONE] project.py：CapitalCostConfig + rate_per_kwp/rate_per_kwh + CAPITAL_MODES_BY_COMPONENT + validate_capital_config + from_dict 挂钩（pv/battery/led/hvac/deh/equipment/envelope/pump） + C_pv 500
4. [DONE] sweep.py：_resolve_capital 增加 component 参数，per_kwp×kWp / per_kwh×kWh，_total_capital 传组件名（接口签名不变，engine.py 零改动）
5. [DONE] pv.py：C_pv 默认 500（市场锚定注释）
6. [DONE] cli.py：自证行（evaluate 全组件表 + sweep best/单点 PV/电池行）+ yaml 注释模板更新 + capital=0 警告字段名修正（顺带把该行 em-dash 改 ASCII）
7. [DONE] 3 个示例 yaml：example_lcoe_full per_kwp 3500 / per_kwh 500 + 注释；example_sweep / test_project C_pv 500 + 回退说明注释
8. [DONE] README §4 重写（单位表 + legacy 回退 + 自证行说明）+ DIY 列表单位注记
9. [DONE] tests：test_04_config §4.4/§4.5（13 项）+ test_07_cli §7.6（4 项）
10. [DONE] pytest 247 passed（229 基线 + 18 新增，0 failed）；black --check vfed/ 通过（CI 版本 23.12.1）；flake8 按 CI 参数通过
11. [DONE] 真实命令验证：evaluate 自证行 ✓；sweep 最优 150 m²+40 kWh 内部最优（与 user4 市场价重建完全一致：资本 163,893 RMB）；旧拼写 E001 迁移报错（PV/电池两条路径）✓；design new → validate 往返 ✓
12. [DONE] 不 commit / 不 push（待 verify subagent）

## 4. Project Status Dashboard

| 项 | 状态 | 备注 |
|---|---|---|
| 基线 229 passed | ✅ | |
| 方案决策 | ✅ 选 B（显式单位模式 per_kwp/per_kwh） | 零静默变更 + 零启发式 |
| 代码 + yaml + README | ✅ 全部完成 | git diff 仅含本任务文件 |
| 测试 | ✅ 247 passed / 0 failed | +18 新增 |
| 端到端验证 | ✅ 最优逃离 200 m² 边界 | 150 m²+40 kWh, 163,893 RMB = user4 复算值 |

## 5. Executor Feedback or Help Requests

- 遗留（非本任务范围）：(1) vfed-web/worker.js 为 bundle.py 生成物，需重跑 bundle 才携带新 schema（web 端不产生 capital 块，无功能影响）；(2) example_sweep.yaml 在新计价下最优仍在 200 m² 边界（平价电价+默认 OPEX 下 PV 到边界仍划算，属 P0-5 边界提示缺失问题，非单位残留）；(3) 电池 legacy c_energy=220 未动（任务未要求，且在市场区间内）。
