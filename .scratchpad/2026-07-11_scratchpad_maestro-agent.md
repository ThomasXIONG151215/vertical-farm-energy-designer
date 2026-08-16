## Background and Motivation

Build the maestro-agent system as defined in `G:\VFLab\VFLAB\energy-optimize-interface\maestro-agent\maestro-agent-def.md`. This involves creating 3 types of agents (diagnosis, tuning, architecture) deployed as Alibaba FC functions with Feishu bot integration, starting with the 609 (lettuce) project's diagnosis agent.

User decisions:
- Runtime: Python + opencode CLI (subprocess call)
- opencode runs inside FC function (fresh start each invocation)
- Phase 1 scope: 609 diagnosis agent only

## Key References

- **FC deployment pattern**: `G:\VFLab\VFLAB\business_projects\fengxian-strawberry-pfal\cvdc_controller` (s.yaml, code/index.py, requirements.txt, pre-deploy scripts)
- **Feishu bot pattern**: `G:\VFLab\VFLAB\business_projects\fengxian-strawberry-pfal\cuberry-bot` (alert/channel_feishu.py, wework WebSocket)
- **TableStore client**: `cvdc_controller/code/utils/tablestore_client.py` (1986 lines)
- **609 project structure**: `G:\VFLab\VFLAB\business_projects\fengxian-lettuce-pfal` (controller, predictor, digital_twin, farm-bot)
- **OpenCode SDK docs**: `@opencode-ai/sdk` (JS/TS SDK for opencode server API)
- **Existing farm-bot**: `G:\VFLab\VFLAB\business_projects\fengxian-lettuce-pfal\farm-bot` (simple FC health monitor + Feishu)

## Key Challenges and Analysis

- **Module isolation**: Shared library (`maestro_core/`) lives in `shared/`, needs `copy_shared.ps1` pre-deploy hook to vendor into `code/` directory before FC packaging.
- **Stateless FC runtime**: opencode CLI runs as a fresh subprocess each invocation — no persistent state between runs. TableStore is the sole persistent layer.
- **Strategy-mode routing**: A/C1/C2 strategy detection requires parsing controller telemetry; strategy transitions (rapid switching) are a key anomaly signal.
- **Feishu card templates**: Cards use ok/warn/critical severity templates with colour-coded headers + compact data tables for mobile readability.

## High-level Task Breakdown

Phase 1 (current): Build 609 diagnosis agent
1. Build shared library `shared/maestro_core/` (tablestore_client, feishu_notifier, report_generator)
2. Build 609 diagnose agent FC skeleton (s.yaml, code/index.py, code/diagnostics.py)
3. Implement analysis modules (strategy_analyzer, model_evaluator, objective_checker)
4. Integrate opencode CLI bridge
5. Feishu report + TableStore persistence
6. Deploy & verify

Phase 2: 609 tuning agent + architecture agent
Phase 3: cuberry (strawberry) 3 agents
Phase 4: Advanced opencode integration

## Project Status Dashboard

| Task | Status | Notes |
|------|--------|-------|
| Create scratchpad | ✅ done | 2026-07-11 |
| Plan AGENTS.md | ✅ done | maestro-agent/AGENTS.md, 609-agents/AGENTS.md, opencode.json updated |
| Step 1: Shared library | ✅ done | maestro_core/: tablestore_client, feishu_notifier, report_generator + requirements.txt |
| Step 2: FC skeleton | ✅ done | s.yaml (FC3: python3.9, 1024MB, 300s, timer+HTTP), code/index.py, code/diagnostics.py |
| Step 3: Analysis modules | ✅ done | strategy_analyzer, model_evaluator, objective_checker |
| Step 4: opencode bridge | ✅ done | opencode_bridge.py (subprocess call to opencode CLI) |
| Step 5: Reports & persistence | ✅ done | FeishuNotifier (ok/warn/critical cards), MaestroTableStoreClient (query + write), ReportGenerator |
| Step 6: Deploy & verify | ⏳ pending | `cd diagnose && pwsh ./scripts/copy_shared.ps1 && s deploy` then `s local invoke` |
| Phase 2: 609 tuning agent | 🔜 upcoming | |
| Phase 2: 609 architecture agent | 🔜 upcoming | |
| Phase 3: cuberry 3 agents | 🔜 upcoming | |
| Phase 4: Advanced opencode | 🔜 upcoming | |

## File Inventory

| File | Status | Path |
|------|--------|------|
| maestro-agent-def.md | exists | maestro-agent/maestro-agent-def.md |
| maestro-agent AGENTS.md | ✅ created | maestro-agent/AGENTS.md |
| 609-agents AGENTS.md | ✅ created | maestro-agent/609-agents/AGENTS.md |
| opencode.json | ✅ updated | energy-optimize-interface/opencode.json |
| **Shared library** | | |
| `__init__.py` | ✅ created | maestro-agent/shared/maestro_core/__init__.py |
| `tablestore_client.py` | ✅ created | maestro-agent/shared/maestro_core/tablestore_client.py |
| `feishu_notifier.py` | ✅ created | maestro-agent/shared/maestro_core/feishu_notifier.py |
| `report_generator.py` | ✅ created | maestro-agent/shared/maestro_core/report_generator.py |
| `requirements.txt` | ✅ created | maestro-agent/shared/maestro_core/requirements.txt |
| **609 diagnose agent** | | |
| `s.yaml` | ✅ created | maestro-agent/609-agents/diagnose/s.yaml |
| `code/index.py` | ✅ created | maestro-agent/609-agents/diagnose/code/index.py |
| `code/diagnostics.py` | ✅ created | maestro-agent/609-agents/diagnose/code/diagnostics.py |
| `code/analysis/__init__.py` | ✅ created | maestro-agent/609-agents/diagnose/code/analysis/__init__.py |
| `code/analysis/strategy_analyzer.py` | ✅ created | maestro-agent/609-agents/diagnose/code/analysis/strategy_analyzer.py |
| `code/analysis/model_evaluator.py` | ✅ created | maestro-agent/609-agents/diagnose/code/analysis/model_evaluator.py |
| `code/analysis/objective_checker.py` | ✅ created | maestro-agent/609-agents/diagnose/code/analysis/objective_checker.py |
| `code/opencode_bridge.py` | ✅ created | maestro-agent/609-agents/diagnose/code/opencode_bridge.py |
| `code/requirements.txt` | ✅ created | maestro-agent/609-agents/diagnose/code/requirements.txt |
| `scripts/copy_shared.ps1` | ✅ created | maestro-agent/609-agents/diagnose/scripts/copy_shared.ps1 |
| `test_event.json` | ✅ created | maestro-agent/609-agents/diagnose/test_event.json |

**Total: 18 new files + 1 existing (maestro-agent-def.md) = 19 files in maestro-agent/**

## Executor Feedback or Help Requests

2026-07-11 (earlier): AGENTS.md files created for maestro-agent and 609-agents subdirectory. opencode.json updated to reference maestro-agent AGENTS.md paths.

2026-07-11 (update): Phase 1 complete — all 18 files created across shared library + 609 diagnose agent. Ready for deploy. No git commits yet (pending deploy verification first). Next: `copy_shared.ps1 && s deploy` then `s local invoke --event-file test_event.json`.
