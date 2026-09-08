# Scratchpad: VFED 用户使用体验测试（user-gym Persona 沙盒评测）

## 1. Background and Motivation

用户目标：让 VFED repo「尽可能地好用 + 物理上正确」。
方法：并行派发多个 subagent 扮演植物工厂行业专业客户（Persona），在独立沙盒目录中实测 vfed 的仿真测算和设计流程，收集 UX 问题与物理正确性问题。

已确认的决策（用户 2026-09-08 确认）：
- 安装测试：user1 用独立 venv 串行先行，完整模拟新客户从零安装；后续用户复用该 venv
- Persona 阵容：5 人 = 初学者 + 运营经理 + HVAC工程师 + 能源分析师 + 农学研究员
- 产物管理：user-gym/ 整体加入 .gitignore
- 物理验证深度：白盒（读源码核对公式）+ 手算对比

## 2. Key Challenges and Analysis

- 环境事实（Phase 0 侦察确认）：
  - Windows/pwsh，Python 3.12.6，主环境未安装 vfed（pip show 为空）
  - Open-Meteo 网络可达（HTTP 200）
  - README.md 432 行，文档体系完整（Quickstart/DI指南/错误码表/KPI表/CLI参考）
  - data/weather/ 内置 51 城市 2025 年 CSV（离线路径可用）
  - 根目录有 example_sweep.yaml、example_lcoe_full.yaml、test_project.yaml
  - weather_cache/ 当前为空
- 关键约束：
  - pip install 不能并行（Windows 文件锁风险）→ user1 必须串行先行
  - 子代理只能写 user-gym/userN/，禁止改 vfed/、tests/、git 状态
  - sweep 网格 ≤ 100 配置（控制耗时，README 称 100 配置约 1-2 分钟）
  - 遇 bug 只记录不修复（发现问题是测试目的）

## 3. High-level Task Breakdown

- [x] Phase 0: 准备沙盒（user-gym/user1..user5 目录、.gitignore 追加 user-gym/、本 scratchpad）
- [x] Phase 1: user1 初学者（串行）：venv 安装 + README Quickstart 逐字执行 → report.md
- [x] Phase 2（并行）: [user2 运营经理 | user3 HVAC工程师白盒物理验证 | user4 能源分析师 LCOE/sweep | user5 农学研究员蒸腾/产量] → 各自 report.md
- [x] Phase 3: 汇总 5 份报告 → user-gym/SYNTHESIS.md（问题按严重度×频率排序 + 修复建议）
- [x] Phase 4: 向用户汇报 top findings 与修复优先级

Persona 任务摘要：
- user1 研究生初学者：venv 安装、Quickstart 逐字跑、DIY offline quickstart、example_sweep
- user2 运营经理：杭州 600m² 生菜厂年电费/kWh/kg 测算（609 preset + Hangzhou，改参数）
- user3 HVAC 工程师：白盒核对 psychrometrics/Carnot COP/SHR/envelope/van Henten 源码公式 + 手算对比仿真输出
- user4 能源分析师：example_lcoe_full sweep、tariff 换地区对比、results.csv 敏感性分析可用性、LCOE 语义清晰度
- user5 农学研究员：5 种蒸腾方法对比、crop_cycle/PPFD/photoperiod 产量-能耗响应、参数文档解释

## 4. Project Status Dashboard

| 阶段 | 状态 | 备注 |
|---|---|---|
| Phase 0 准备 | ✅ 完成 | user-gym/ 5 目录已建，.gitignore 已更新 |
| Phase 1 user1 | ✅ 完成 | 安装遇本机 pip 镜像源 SSL 问题（机器环境问题非 repo 问题），装好后 Quickstart 逐字可跑、离线承诺属实、evaluate 仅 1.9s |
| Phase 2 user2-5 | ✅ 完成 | 四路并行报告全部完成（user2 运营经理/user3 HVAC白盒物理/user4 能源分析师/user5 农学研究员） |
| Phase 3 综合 | ✅ 完成 | SYNTHESIS.md 已生成（P0×5/P1×7/P2×4/P3×4 分级 + 修复路线图三批） |
| Phase 4 汇报 | ✅ 完成 | top findings 与修复优先级已向用户汇报，测试完结 |

产出文件清单：
- user-gym/user1/report.md ✅（user1 报告已完成，评分：安装2/上手5/文档4/CLI4/可信度4）
- user-gym/user2/report.md ✅
- user-gym/user3/report.md ✅
- user-gym/user4/report.md ✅
- user-gym/user5/report.md ✅
- user-gym/SYNTHESIS.md ✅（综合发现报告：P0×5 / P1×7 / P2×4 / P3×4 分级 + 修复路线图三批 + 评分汇总 + 跨用户印证）

## 5. Executor Feedback or Help Requests

### 最终关键结论（2026-09-08 收尾，测试完结）

- 物理内核可信：16 项核对 13 OK / 3 SUSPECT / 0 BUG，CSV 可复核到机器精度
- 四大静默误导：
  - rate_per_watt 1000× 单位陷阱（PV 乘 kWp）
  - 无 PV 电费静默归零
  - 产量 2× 偏高未到用户界面（kwh_per_kg_fresh 是 sweep 目标函数）
  - 夜间设定点不可达致 HVAC 满速空转，浪费 13.5% 年电耗
- 两个官方示例最优都顶在 200m² 边界 = 伪最优；修正 PV 市场价后真实最优 150m²+40kWh、回收 5.4 年、IRR≈18%
- 贯穿模式「静默误导」：fail-fast 在参数层好，但输出语义层缺护栏
- 优势保持：物理内核 / 可复核性 / 性能 / 文档文化 / Quickstart

### user1 关键发现（2026-09-08）
- 安装环节：本机 pip 配置了 NVIDIA 镜像源导致 SSL 重试风暴，耗时 25 分钟失败一次后成功——机器环境问题，非 repo 问题，但 README 对 pip 镜像源问题零提示（低优先级文档改进点）
- Quickstart 逐字可跑，README「fully offline」承诺经验证属实（data/weather/Shanghai_2025.csv 生效）
- evaluate 仅 1.9 秒出结果，性能优秀
- 改参数（photoperiod/面积）响应方向符合农学直觉
- user1 venv 已建好（user-gym/user1/.venv），已验证 vfed CLI 可用，Phase 2 四个用户复用此环境
