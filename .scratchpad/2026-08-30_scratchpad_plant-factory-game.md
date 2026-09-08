# 2026-08-30 Scratchpad — 像素植物工厂小游戏

## 1. Background and Motivation

用户请求（原始）：`做一个简单的，文件夹里；像素风植物工厂经营模拟小游戏；可以部分参考vfed src仿真代码了解`

交付 1：`plant-factory-game/` 单文件像素风植物工厂经营模拟小游戏（已完成并验证）。

用户追加请求：`我对这个游戏不太满意；希望发散想象力，并行三个 subagent 做几个不同方向、但核心主旨依然是设计建造和经营植物工厂的游戏。`

执行调整：subagent 并行两轮均返回空结果（0 文件），改为主线程顺序自建 3 个方向的游戏，每个均用 Node 无头测试验证。

## 2. Key Challenges and Analysis

- 单一 HTML 文件，Canvas 像素画 + HTML 控制面板，无依赖、双击即玩。
- 移植 vfed 核心物理做简化，数值缩放到游戏节奏。
- Node 桩（stub DOM/canvas/localStorage）+ 间接 eval 技巧提取脚本内部变量做无头验证。
- 每个游戏的经济平衡必须用"开局标准布局跑 60 天"冒烟测试验证生存性。

## 3. High-level Task Breakdown

1. 调研 vfed 源码（van_henten / led / hvac / transpiration / engine）✅
2. plant-factory-game（俯视角+侧栏参数面板，vfed 物理忠实简化）✅
3. game-factory-tycoon 像素工厂大亨（俯视角 tile 建造 + 物流链 + 订单经营）✅ 已验证 + README
4. game-tower-farm 立体农场（侧视塔层堆叠，层间 HVAC 梯度、事件系统）⏳ 进行中
5. game-farm-lab 工程实验室（合同驱动沙盒，vfed 物理忠实 + 科技树）✅
6. 三个游戏完成后更新 scratchpad 收尾 ✅

## 4. Project Status Dashboard

| 项目 | 状态 | 备注 |
|---|---|---|
| plant-factory-game/index.html | ✅ 完成 | 单文件游戏，localStorage 自动存档 |
| plant-factory-game/README.md | ✅ 完成 | 玩法说明 + vfed 模型对照表 |
| game-factory-tycoon/index.html | ✅ 完成并验证 | tile 建造+物流链+订单；无头测试 60 天生存，¥6522/300kg，跳闸路径 OK |
| game-factory-tycoon/README.md | ✅ 完成 | 玩法+设备表+机制说明 |
| game-tower-farm | ✅ 完成并验证 | 侧视塔层+垂直温度梯度+事件系统；ECON 60天生存(min¥317/rev¥5937)，SYS 梯度/停电电池/存档回读全过 |
| game-tower-farm/README.md | ✅ 完成 | 玩法+作物表+梯度机制说明 |
| game-farm-lab | ✅ 完成并验证 | 合同工程沙盘，vfed 物理忠实；ECON 70天 cn#10/¥13900/rp11，spec 达成机制正常 |
| game-farm-lab/README.md | ✅ 完成 | 玩法+物理对照表+三重约束博弈说明 |
| **全部交付** | ✅ | 3 个新游戏 + 1 个旧游戏，全部单文件可玩、无头测试通过、有 README |

## 5. Executor Feedback / Help Requests

- subagent 并行方案失败（返回空、零文件），主线程顺序构建替代，质量更可控。
- tycoon 修复史：count() 逗号表达式死循环、packer 产出未写入 dock（收入为零主因）、1 月开局 tempF≈0、订单量 vs 产能失衡 → 起始日改 105（4月中）、起始资金 800→900（消除开局资金为负）。
- tower 修复史：`Math.PI(h-9)` 缺乘号、newDay 漏 G.day++（日期冻结+破产误判）、水经济失衡（蒸腾 9→6L/床、水箱 800L、购水+500L）、 basil 24°C 适温不可达 → 加本底垂直梯度 +0.8°C/层、LED 1.2→1.0kW、电价 0.9→0.8、罗勒 ¥90、停电 eco-mode（LED 半功率 lightF 0.75）、电池 15kWh/级。
- lab 修复史（最多 bug）：`Math.PI(h-9)` 同款缺乘号；LED 功率 W/kW 混用致 3MW 热爆炸 → 全 kW 化；夜间加热 9kW×6min 粗步长震荡 → 热ODE 1 分钟×6 子步；DEH 无条件运行抽干到 RH 2% → 湿度开关（>60 启动）+ 基础容量 0.12g/s；电费双重计费（逐 tick + newDay）；**合同 deadline 存相对天数却与绝对 G.day 比较 → 每天午夜重置合同**（最隐蔽）→ 改绝对 deadline+issue 时补 G.day；kgTally/kgDone 两本账 → 统一 cn.kgDone；种植波次集中 → 初始 Xd 错开 0.024/床 实现日均平滑交付；破产 3→5 天缓冲。
- 无头测试资产（%TEMP%\opencode）：extract.js / l1econ.js / t1econ.js / t1sys.js / g1econ.js 可复用。
