# 2026-08-16 Scratchpad — .scratchpad/.cursor 关系调整与 mainrepo 同步

## 1. Background and Motivation

用户请求（原文："调整下这里.scratchpad和.cursor关系；然后要确保mainrepo同步"）：
1. 调整项目内 `.scratchpad/`（新协议位置）与 `.cursor/mems/`（旧位置）的关系，统一 scratchpad 存放。
2. 确保 mainrepo（推断为 origin/main）与本地同步（提交 + push）。

## 2. Key Challenges and Analysis

- **双轨并存**：AGENTS.md 全局规则指定 scratchpad 路径为 `.scratchpad/{date}_scratchpad_{topic}.md`，但仓库历史上有 13 个旧 scratchpad 存放在 `.cursor/mems/`（2026-07 月，全部已被 git 跟踪）。`.gitignore` 未忽略两者。
- **未跟踪遗留**：`.scratchpad/2026-08-16_scratchpad_code_review.md` 与 `REVIEW.md`（上个 code_review 任务的审查产物）尚未提交；code_review 任务本身（6 项修复）仍 pending，其 scratchpad 记录需保留。
- **mainrepo 无直接引用**：grep 全仓库无 `mainrepo` 字样；`git remote -v` 仅 origin（`git@github.com:ThomasXIONG151215/vertical-farm-energy-designer.git`）。推断用户所指为 origin/main，待确认。
- **git 状态**：分支 main，本地与 origin/main 一致；仅 2 个 untracked 文件。

## 3. High-level Task Breakdown

| # | 任务 | 状态 | 依赖 |
|---|------|------|------|
| 0 | 探索 .scratchpad/.cursor 现状与 git 状态 | done | — |
| 1 | 创建本任务 scratchpad（本文件） | done | — |
| 2 | 确认 .scratchpad/.cursor 调整方案（迁移 vs 归档） | done | 用户确认（选迁移） |
| 3 | 执行调整（git mv 旧 scratchpad 至 .scratchpad/，删 .cursor） | done | 2 |
| 4 | 提交 REVIEW.md + 相关 scratchpad 变更 | done | 3 |
| 5 | push 到 origin/main 并验证同步 | done | 4 |

并行组：`[3]` 单线执行；`3 → 4 → 5` 顺序。

## 4. Project Status Dashboard

| 任务 | 状态 |
|------|------|
| 现状探索（目录结构 + git 状态） | done |
| 本 scratchpad 创建 | done |
| 方案确认（迁移 vs 归档） | done（用户选迁移） |
| 执行调整（13 个 git mv + 删除 .cursor） | done |
| commit + push 同步 | done |

### Git 状态

- 提交：`c2909cc`（docs(meta): consolidate scratchpads under .scratchpad, add architecture review report）
- 推送：`bb23745..c2909cc main -> main`，本地与 origin/main 一致，工作树干净

## 5. Executor Feedback or Help Requests

1. **mainrepo 含义待确认**：仓库无同名 remote/目录，推断为 origin/main（GitHub: ThomasXIONG151215/vertical-farm-energy-designer）。
2. **待用户决策**：`.cursor/mems/` 13 个旧 scratchpad（已跟踪）——(A) `git mv` 迁移到 `.scratchpad/` 统一管理；(B) 保留 `.cursor/mems` 作为历史归档并在 AGENTS.md/.scratchpad 说明关系。推荐 A。
3. **遗留状态**：REVIEW.md + code_review scratchpad 尚未提交，是否随本次同步一并提交待用户确认。
