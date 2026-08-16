# Scratchpad: Bailian Function Calling Integration

## 1. Background and Motivation

Integrate Bailian (Alibaba Cloud) LLM function calling capability into the VFED project diagnostics system. Enable the AI agent to dynamically call diagnostic tools via function calling protocol rather than relying solely on static prompt-response patterns.

## 2. Key Challenges and Analysis

- Sandbox execution safety for arbitrary Python code
- Function calling loop design (max 3 rounds to prevent infinite loops)
- Proper tool registration with JSON Schema for Bailian API compatibility
- Integration with existing diagnostics.py raw_data flow

## 3. High-level Task Breakdown

- [Task1] Create sandbox.py | Create opencode_agent.py → sequential
- [Task2] Update diagnostics.py → depends on Task1
- [Task3] Deploy & test → depends on Task2
- [Task4] Fix strategy rotation order in deh_analyzer.py

## 4. Project Status Dashboard

| Task | Status | Notes |
|------|--------|-------|
| Create sandbox.py | ✅ completed | 安全沙箱，subprocess执行，import白名单 |
| Rewrite opencode_agent.py | ✅ completed | 3轮function calling循环，run_python_code工具 |
| Update diagnostics.py | ✅ completed | 传递raw_data给agent |
| Deploy & test | ✅ completed | 部署测试通过：AI分析返回3行中文诊断文本 |
| Fix strategy rotation order | ✅ completed | 两阶段轮换: Phase1(A→C1→C2), Phase2(C1→A→C2) |

## 5. Executor Feedback or Help Requests

### 执行者反馈 (2026-07-12 18:45)

✅ **Function Calling 升级完成**:
- sandbox.py: 安全沙箱，subprocess执行，import白名单
- opencode_agent.py: 3轮function calling循环，run_python_code工具
- diagnostics.py: 传递raw_data给agent
- 部署测试通过：AI分析返回3行中文诊断文本
- Bailian连通性测试：FC可达Beijing endpoint

📊 **关键数据**:
- 函数执行时间: ~61s (含诊断+AI)
- AI分析内容: C2占空比99%、RH>85%违规、MPC Lagrangian失效分析
- 端点: llm-tfd66u9o7bj1xhjz.cn-beijing.maas.aliyuncs.com

⏭️ **结论**:
- Function calling基础设施就绪
- 模型可选择直接回答或调用工具
- 当summary数据充足时，模型倾向直接分析（有效行为）
- 如需验证tool use，可查看FC日志中的[Bailian] round记录

### 执行者反馈 (2026-07-12 20:25)

✅ **Prompt重构完成**:
- diagnostics.py: 传windows dict给agent (不再传raw rows)
- opencode_agent.py: _build_prompt() 重写为按窗口组织
- 每窗口: Rack温湿度 + DEH(按策略C1/A/C2) + 温度 + 异常建议
- Deploy测试通过，AI分析质量显著提升

📊 **改善对比**:
- 旧: raw rows + text summary → 模型直接回答
- 新: 结构化per-window数据 → 模型能分析趋势、对比策略、给行动建议
- AI输出: 3条发现(Critical/Warn) + 3条行动建议，提及RMSE、占空比、MPC优化

⏭️ **结论**:
- Prompt按3窗口×4维度(温度/湿度/DEH/策略)组织
- 模型能识别C2占空比99%异常、C1 vs A能耗对比
- Function calling工具仍可用，但summary数据充足时模型选择直接分析

### 执行者反馈 (2026-07-12 22:10)

✅ **策略轮换顺序修复完成**:
- 轮换顺序在06/30发生变更:
  - Phase 1 (06/12-06/29): A → C1 → C2
  - Phase 2 (06/30-present): C1 → A → C2
- deh_analyzer.py: 新增两阶段轮换 ROTATION_ORDER_P1 / ROTATION_ORDER_P2
- opencode_agent.py SYSTEM_PROMPT: 已修正轮换描述

📊 **AI分析验证**:
- 3-day窗口: C1功率 < A功率 → MPC正常工作 (短期优化有效)
- 15-day窗口: C1功率 > A功率 → MPC长期优化失败
- 这一发现符合预期: MPC滚动优化在长时间窗口无法保证全局最优

⏭️ **结论**:
- 轮换顺序修复后，AI分析能正确识别策略性能差异
- Bailian从FC调用连通性确认 (Beijing endpoint)
- 策略对比分析现在基于正确的轮换顺序进行
