# 2026-08-14 Scratchpad — 文档同步修复 (doc_sync)

## 1. Background and Motivation

用户要求「检查所有文档是否过时，包括 readme 和 agentsmd」，调研已完成（见下），现按优先级修复文档并 commit push。

仓库：VFED (Vertical Farm Energy Designer) v2.0.0，Python 参数化植物工厂仿真器。本项目耦合第一性原理 ODE 建筑模型（无 EnergyPlus）与 PV-电池-电网能源系统，用于 LCOE 最优光伏+储能容量配置。

## 2. Key Challenges and Analysis

调研发现的文档与代码不一致清单（已通过实际运行 CLI 与 grep 验证）：

- **严重**
  - `vfed optimize` 命令不存在（CLI 只有 design/evaluate/sweep）
  - `evaluate --pv-area/--battery` 参数不存在（只有 --cache）
  - pyproject.toml 无 `[all]` extra（只有 dev）
  - src/agent/README.md 示例 `agent_evaluate(tlps_max=200)` 参数不存在会 TypeError

- **中等**
  - README/README_zh/plants README 声称蒸腾 4 种方法（实际 6 种：constant/daily/per_plant/vpd/stomatal/van_henten）
  - 配置章节 dehumidifier 应为 deh、tariff 现为 hourly_prices、缺 growth/space/opex/currency 新字段
  - AGENTS.md "Strategy modes are exactly 4" 与 scenario 约束针对未实现功能（仅 project.py docstring 计划）
  - design README sweep 描述过窄（实际可枚举任意 HARD_LIMITS 内参数）

- **轻微**
  - pyproject.toml Documentation URL 指向 opencrops.readthedocs.io（复制粘贴错误）
  - sdist include 引用不存在的 /docs

## 3. High-level Task Breakdown

1. 修复 README.md + README_zh.md（高优先）
2. 修复 AGENTS.md（高优先）
3. 修复 pyproject.toml（中）
4. 修复 src/agent/README.md（中）
5. 修复 src/plants/README.md + src/design/README.md（中）
6. 验证：pytest + 命令冒烟测试 + 文档复核
7. git commit + push

## 4. Project Status Dashboard

| 任务 | 状态 | 备注 |
|------|------|------|
| README.md + README_zh.md | ✅ completed | 7 处编辑（命令/蒸腾6法/.[dev]/配置schema/design cities+tariffs） |
| AGENTS.md | ✅ completed | 5 处编辑（strategy/scenario 改为未实现、命令修正、.[dev]） |
| pyproject.toml | ✅ completed | Documentation URL 改为 GitHub；sdist include 移除 /docs |
| agent/README.md | ✅ completed | 移除不存在的 tlps_max 示例参数 |
| plants+design README | ✅ completed | plants 4→6 方法；design 补充 growth/space/opex/sweep 描述 |
| 验证 (pytest/冒烟) | ✅ completed | pytest 172 passed；CLI 冒烟全部一致 |
| commit + push | ✅ completed | commit bf28941 `docs: sync README/AGENTS/module docs with CLI and config contract`，已 push 到 main |

## 5. Executor Feedback or Help Requests

无阻塞。

✅ **完成情况 (2026-08-14)**：全部 7 项任务 completed。8 个文档文件修复并验证通过（pytest 172 passed + CLI 冒烟一致），已提交并推送。
- Git 提交：`bf28941`（8 files changed, +61/-56），分支 main，远端 `git@github.com:ThomasXIONG151215/vertical-farm-energy-designer.git`。

🔍 **遗留工作流处理 (2026-08-14 追加)**：用户指示湿度审计 commit+push，已按主题分组提交并推送：
- `25fa578` fix(humidity): calibrate AC latent removal（湿度审计会话遗留本地提交：shr.py T_coil_drop 14→9、SHR floor 0.30→0.45，engine.py/dehumidifier.py）
- `b357ea0` fix(humidity): C-level - SHR floor 0.45 and realistic coil drop (9C)（shr.py 相关 mems 记录）
- `b37a27a` feat(cost): wire currency/OPEX into result and sweep, preset city for local weather CSV（cli.py/presets.py/result.py/sweep.py + currency-opex mems）
- 已推送：`bf28941..b37a27a main -> main`。湿度审计源码改动全部落地，pytest 172 passed。

**仍未提交（独立 vfed-web 工作流，未纳入本次提交）**：
- 已跟踪修改：`src/weather/weather_bridge.py`（Pyodide 回退，浏览器端用）、`vfed-web/bundle.py`、`vfed-web/index.html`、`vfed-web/package.json`、`vfed-web/worker.js`、`vfed-web/worker.template.js`、`vfed-web/wrangler.toml`，`vfed-web/main.js`(已删除)
- 未跟踪：`.coverage`、`.cursor/mems/2026-07-26_scratchpad_vfed-web-model-params.md`、`vfed-web/node_modules/`、`weather_cache/*.csv`、`.scratchpad/2026-08-14_scratchpad_doc_sync.md`

⏭️ **建议下一步**：如需提交 vfed-web UI 改动（含 weather_bridge.py 的 Pyodide 支持），与用户确认后再处理。

技术备忘：
- PowerShell 读取 GBK 中文文件会乱码，读取/编辑中文文档时注意编码（用 UTF-8 显式处理）
- 关键验证命令：
  - `python -m src.cli optimize` → 应报 invalid choice
  - `python -m src.cli evaluate --help` → 只显示 --cache
