# 仓库重组计划（2026-11-03）

## 1. 背景与动机

用户反馈仓库架构"不容易让人理解"。诊断覆盖两层：根目录布局（32 个条目，约一半无角色说明）与
`vfed/` 代码结构（engine.py 是 2201 行的中枢文件，模块依赖关系无处可查）。用户选择"激进重组，
先详细计划"；`user-gym/` 确认为本机评测工场，保持本地不进 git。

## 2. 诊断结论（事实基础）

### 2.1 根目录 32 个条目的分类

| 类别 | 条目 | 问题 |
|------|------|------|
| 活跃代码（跟踪） | `vfed/`, `scripts/`, `tests/` | 无。AGENTS.md 已有模块表 |
| 数据资产（跟踪） | `data/`, `reference/`, `research/`, `.planning/`(6 md), `deliverables/`(1 md) | 根目录层无任何地图说明各自角色与活跃状态 |
| 配置示例（跟踪） | `example_lcoe_full.yaml`, `example_sweep.yaml` | 躺在根目录，不在 examples/ 目录 |
| 标准文件（跟踪） | README×2, LICENSE, CHANGELOG, CONTRIBUTING, pyproject, .git*, .github/ | 无 |
| 本地杂物（未跟踪） | `gadget/`(同步层锁定), `user-gym/`, `backups/`(232 文件), `weather_cache/`, `.scratchpad/`, `.workbuddy/`, `vfed-workspace.code-workspace` | 无文档说明"这是什么、能不能删" |
| 垃圾（未跟踪） | `_probe.png`, `.coverage`, `.pytest_cache/` | 可直接删除 |

### 2.2 代码结构事实

- 依赖方向（由实际 import 证实）：`physics/ devices/ plants/ weather/` → `design/engine.py`（中枢）
  → `design/sweep.py`（同时直接 import `pvbes/` 四件套）→ `agent/evaluator.py` → `cli.py`。
  `calibration/` 独立存在，读引擎输出。`design/project.py`（2643 行）是配置契约，被 engine/sweep/cli/evaluator 共同 import。
- 巨型文件：`project.py` 2643 行、`engine.py` 2201 行、`cli.py` 1479 行、`sweep.py` 918 行。
- `vfed/design/README.md` 已存在但只有 25 行的文件清单，无依赖图、无数据流。

### 2.3 环境约束（已验证）

- G: 盘由双向云同步层管理（FeRp reparse tags）。`gadget/` 的移动在两次验证成功后均被回滚；
  因此 `gadget/`、`user-gym/`、`backups/` 等**本地大目录一律不搬**，只做文档标注。
- git 跟踪层的操作（commit 1b5db18 的 445 个删除）在同步层下存活，说明对**被跟踪文件**的
  git mv/git rm 是安全的，但每次移动后需延迟复查（见 §6 验证）。
- `tests/` 路径被 CI（.github/workflows/ci.yml，Python 3.10-3.12）引用，不动。
- `research/` 路径被 README 论文段落引用，冻结不动。
- `examples/` 未被任何 ignore 规则覆盖（早前 check-ignore 的"已忽略"结论是尾部斜杠参数的
  误报，已用真实文件实测推翻）。

## 3. 目标

1. 新来者 5 分钟内通过一张地图理解根目录每个条目的角色与活跃状态。
2. `vfed/` 模块依赖与仿真数据流有图可查（docs/architecture.md）。
3. 本地目录明确标注 local-only，防止未来 agent 或用户误删误搬。
4. 根目录条目数从 32 降到 23 左右；剩余"减不掉"的部分（gadget 等）由地图兜底。

## 4. 分阶段执行计划（每阶段一个 commit）

### Phase 1 — 地图文档（零风险，不移动任何文件）

1. 新建 `docs/architecture.md`，内容：
   - 根目录地图表：条目 | 角色 | 跟踪状态 | 活跃/归档/本地。含 gadget、user-gym、backups 的 local-only 标注。
   - `vfed/` 模块依赖图（Mermaid，基于 §2.2 的实际 import 关系）。
   - 仿真数据流：YAML → project.py → engine.py 逐时 ODE → SimulationResult → sweep.py（pvbes 调度 × 设计空间）→ LCOE → cli/agent。
   - 巨型文件清单（行数 + 职责 + 修改注意事项）。
2. `README.md` 与 `README_zh.md` 在"What's New"之前加"Repository structure"一节，指向 docs/architecture.md。
   3. `AGENTS.md` 的 Architecture 表扩展为两层：根目录层 + vfed/ 层；File Conventions 更新 examples/ 与 docs/planning/ 路径。
   4. `REVIEW.md`：路径审计已完成（唯一路径引用是第 34 行 `research/`，该目录不动，无需改写）；在头部约束区加一行指向 docs/architecture.md 作为架构参考。
   5. `vfed/design/README.md` 扩充：引擎时序、hub 职责、与 sweep/pvbes 的关系。

### Phase 2 — 根目录清理（低风险，只动跟踪文件与垃圾）

1. 删除 `_probe.png`、`.coverage`、`.pytest_cache/`（全部未跟踪，磁盘直删）。
2. `git mv example_lcoe_full.yaml example_sweep.yaml examples/`。
3. `.gitignore` 追加 `_probe.png` 精确规则（防再生）；检查 README 是否引用这两个 yaml 路径并同步更新。
4. `scripts/` 拆分（D5 决定）：`scripts/benchmarks/` → 根 `benchmarks/`；两个工具 + README → 根 `tools/`；
   同 commit 更新 15 处引用（README×2 共 4 处、AGENTS.md 架构表 1 行、pyproject 注释 1 处、
   vfed/ docstring 4 处、tests 注释 3 处）；清理残留 `scripts/__pycache__` 后删除空壳 scripts/。

### Phase 3 — 归并内容目录（中风险，逐项验证）

1. `deliverables/`（1 个跟踪 md）→ `docs/reports/`（git mv + 路径引用检查）。
2. （待用户定夺）`reference/` → `docs/references/`：论文 PDF 与验证资料并入 docs。
3. （待用户定夺）`.planning/` → `docs/planning/`：减少点前缀目录。代价是偏离现有 agent 约定。
4. `gadget/`、`user-gym/`、`backups/`、`weather_cache/` 原地不动，仅由地图标注。

### Phase 4 — 代码可理解性（文档优先，不改代码）

1. 在 docs/architecture.md 写明分层规则：config（project.py）← models（physics/devices/plants/weather）
   ← hub（engine.py）← sweep（+pvbes）← frontend（cli/agent）。禁止反向 import。
2. 新增 `tests/test_architecture.py`（或 import-linter，倾向前者零依赖）：断言分层规则，
   例如 physics/devices/plants 不得 import design/engine，engine 不得 import cli。
3. 巨型文件拆分只记路线图不执行：engine.py 可拆"设备编排"与"时步循环"，属接口级变更，
   按仓库规范需单独申请批准（Phase 5 预留）。

## 5. 重组后的目标根目录

```
README.md / README_zh.md / AGENTS.md / REVIEW.md / CHANGELOG.md / CONTRIBUTING.md / LICENSE / pyproject.toml
vfed/ tests/                    # 活跃代码
tools/                          # 维护工具（download_weather_db.py 刷新 data/weather/，generate_eta_rel.py）
benchmarks/                     # 物理验证台（bestest / bjaaf_growth / respiration / uc_davis）
examples/                       # 2 个示例 yaml
data/                           # 数据集 + 城市 weather CSV
docs/                           # architecture.md + reports/(原 deliverables) [+ references/ + planning/ 待定]
research/                       # 论文归档（冻结）
# local-only（地图标注）: gadget/ user-gym/ backups/ weather_cache/ .scratchpad/ .workbuddy/ vfed-workspace.code-workspace
```

## 6. 验证协议（每阶段强制）

1. 移动/删除后立即 `git status` 确认无意外；5 分钟后复查一次（防同步层回滚，gadget 教训）。
2. 每阶段结束跑冒烟集：`pytest tests/test_01_smoke.py tests/test_04_config.py`（约 99 例）。
3. Phase 2/3 结束跑全量 `pytest`（CI 同口径）。
4. README/AGENTS 中所有新加的相对链接逐一核对。

## 7. 风险与回滚

- 风险最高的是 Phase 3 的 git mv 触发同步层异常：缓解 = 每次只动一个目录 + 5 分钟复查 + 单独 commit。
- 回滚单位 = commit；每阶段独立可 revert，不影响已发布历史。
- research/ 与 tests/ 完全不在本次范围内。

## 8. 决策记录（2026-11-03 用户已拍板）

| # | 问题 | 决定 |
|---|------|------|
| D1 | `reference/` 去留 | **并入 `docs/references/`**，同步改 .gitignore 的 3 条路径规则 |
| D2 | `.planning/` 去留 | **并入 `docs/planning/`**，同步更新引用 |
| D3 | 分层守护 | **加 `tests/test_architecture.py`**（零依赖 import 检查） |
| D4 | engine.py 拆分 | **本轮就拆**：接口保持式（DesignEngine/run_project/full_load_warnings/SimulationResult 的导入路径不变），设备编排与时步循环分离，作为 Phase 5 单独 commit |
| D5 | scripts/ 命名 | **拆成根 `benchmarks/` + 根 `tools/`**：验证台升为一等公民，工具归 tools/；根目录 22→23（用户接受）；15 处文档/注释引用同 commit 更新，零运行时 import |

## 9. 执行顺序（调整后，每步一个 commit）

原计划 P1（文档）先行；调整为物理变更先行、文档描述终态，避免地图写两遍：

1. **C1（原 P2）**：删垃圾（_probe.png/.coverage/.pytest_cache）+ example yaml → examples/ + .gitignore 补规则
2. **C2（原 P3）**：deliverables→docs/reports、reference→docs/references、.planning→docs/planning；改 .gitignore 路径与全仓库引用；5 分钟同步复查
3. **C2b（D5 新增）**：scripts/ 拆分 → 根 benchmarks/ + 根 tools/（git mv ×2，同 commit 更新 15 处文档/注释引用，清理残留 __pycache__ 与空壳 scripts/）；5 分钟同步复查
4. **C3（原 P1）**：文档批量更新，逐文件清单：
   - `docs/architecture.md` 新建（终态地图：根目录条目表 | Mermaid 依赖图 | 数据流 | 巨型文件清单）
   - `README.md` + `README_zh.md`：加"Repository structure"节，指向 docs/architecture.md
   - `AGENTS.md`：Architecture 表扩为根目录层 + vfed/ 层；File Conventions 更新（examples/、docs/planning/、docs/references/）
   - `REVIEW.md`：头部约束区加 docs/architecture.md 指针（路径审计已完成，仅 research/ 引用，不受影响）
   - `vfed/design/README.md`：扩充引擎时序、hub 职责、与 sweep/pvbes 关系
5. **C4（原 P4）**：tests/test_architecture.py 分层守护
6. **C5（原 P5）**：engine.py 接口保持式拆分（先通读 2201 行出拆分方案，接口零变更，全量 pytest 验证）；
   拆分落地后同步核对 `REVIEW.md` 第 4 行与 `AGENTS.md` 中"engine.py 为枢纽"的措辞是否需要更新
