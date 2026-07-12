# Vertical Farm Energy Designer (VFED)

[中文版](./README_zh.md) | [English](./README.md)

> 面向**人工光植物工厂 (PFALs)** 的开源设计模拟器 — 将基于第一性原理的建筑能耗模型与光伏-储能-电网系统耦合，实现最低 LCOE 的光伏+储能容量优化。

[![GitHub stars](https://img.shields.io/github/stars/ThomasXIONG151215/vertical-farm-energy-designer?style=social)](https://github.com/ThomasXIONG151215/vertical-farm-energy-designer/stargazers)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Python 3.8+](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://www.python.org/)

## 背景

人工光植物工厂 (PFALs) — 用 LED 替代阳光的封闭式多层种植设施 — 是能耗最高的农业系统之一，照明、空调和除湿的合计能耗高达 **200–500 kWh/m²/年**。电网电力在运营成本中占主导地位，往往超过总生产成本的 30%。

将屋顶光伏 (PV) 与电池储能 (BES) 结合，可以显著降低电网依赖和运营成本。但最优光伏阵列面积和电池容量取决于多个复杂因素的交织：地理位置、当地气候、建筑围护结构、作物光周期安排以及分时电价。没有放之四海而皆准的经验法则 — 每个设施都需要因地制宜的设计。

**VFED** 解决了这个问题。它使用第一性原理物理（湿空气热力学、围护结构传热、基于 ODE 的房间模型）模拟植物工厂的逐时能量平衡，然后扫描光伏面积 × 电池容量，找到使**平准化能源成本 (LCOE)** 最小的设计。

> 📄 本工具配套论文：
> **Xiong, T., Cai, W., Hu, Y., Song, M., Qian, T., & Bao, H. (2026).** *Photovoltaic-battery integration strategy in plant factories with artificial lighting.* Energy and Buildings, 361, 117462.
> [DOI: 10.1016/j.enbuild.2026.117462](https://doi.org/10.1016/j.enbuild.2026.117462)

`research/xiong-pvbes-photoperiod-2026/` 目录包含该论文的归档代码和实验数据。当前活跃代码库 (`src/`) 用纯 Python 第一性原理 ODE 求解器替代了基于 EnergyPlus 的负荷生成器，并增加了参数化设计扫描 — 详见 [research/xiong-pvbes-photoperiod-2026/](research/xiong-pvbes-photoperiod-2026/)。

## VFED 工作原理

| 挑战 | VFED 方法 |
|------|-----------|
| PFAL 负荷取决于气候、围护结构和光照计划 | 第一性原理 ODE 求解器 — 房间热湿平衡，无 EnergyPlus 依赖 |
| 光伏输出随位置、倾角和天气变化 | 单二极管 PV 模型 + Open-Meteo 逐时天气数据 |
| 电池容量是成本与自给率之间的权衡 | 对 (光伏面积 × 电池容量) 进行参数化扫描 → LCOE 最优设计 |
| 电价结构影响经济性 | 分时电价模型（峰/平/谷定价） |
| 植物蒸腾增加潜热负荷 | 4 种可配置蒸腾方法，从恒定到 Van Henten 生长模型 |

## 快速开始

### 安装

```bash
git clone https://github.com/ThomasXIONG151215/vertical-farm-energy-designer.git
cd vertical-farm-energy-designer
pip install -e .
# 或安装所有可选依赖：
pip install -e ".[all]"
```

### 创建设计

```bash
vfed design new my_farm --preset 609 --lat 30.9 --lon 121.5 --year 2023
```

### 优化

```bash
vfed optimize my_farm.yaml --cache weather_cache --out results.csv
```

### 评估配置

```bash
vfed evaluate my_farm.yaml --pv-area 120 --battery 40
```

### 参数化扫描

```bash
vfed sweep my_farm.yaml --out sweep_results.csv
```

## 架构

```
┌─────────────┐     ┌──────────────────────────────────────────────┐
│   天气数据   │────▶│              设计引擎                       │
│  (Open-Meteo)│     │  (src/design/engine.py — ODE 积分)         │
└─────────────┘     │                                              │
                    │  ┌──────────┐ ┌──────────┐ ┌──────────────┐ │
                    │  │  物理模型 │ │  设备模型 │ │   植物模型    │ │
                    │  │ 湿空气,  │ │ 空调,    │ │ 蒸腾,        │ │
                    │  │ 围护,    │ │ 除湿,    │ │ Van Henten   │ │
                    │  │ ODE, SHR │ │ LED,     │ │              │ │
                    │  │          │ │ 压缩机    │ │              │ │
                    │  └──────────┘ └──────────┘ └──────────────┘ │
                    └──────────────────┬───────────────────────────┘
                                       │ 逐时负荷曲线
                    ┌──────────────────▼───────────────────────────┐
                    │         PVBES 扫描与优化                     │
                    │  (src/design/sweep.py + src/pvbes/)         │
                    │  PVSystem → BatterySystem → Tariff → LCOE   │
                    └──────────────────┬───────────────────────────┘
                                       │
                               LCOE 最优设计
```

## 仓库结构

```
vertical-farm-energy-designer/
├── src/                    # 核心模拟器代码
│   ├── physics/            # 湿空气热力学、围护传热、ODE 求解器、SHR
│   ├── devices/            # 空调、除湿机、LED、压缩机、热滞后
│   ├── pvbes/              # 光伏（单二极管）、电池（Zhao 2024）、电网（分时）、能源系统
│   ├── design/             # 项目配置（YAML）、引擎、预设、扫描
│   ├── weather/            # Open-Meteo 接口、Erbs GHI 分解、POA、地理编码
│   ├── plants/             # 蒸腾（4 种方法）、Van Henten 生长模型
│   ├── agent/              # 评估器（保留 agent-cli 错误码契约）
│   └── cli.py              # CLI 入口：vfed
├── research/               # 论文归档代码与数据（见下）
├── reference/              # 参考文献
├── weather_cache/          # 缓存的天气 CSV（自动生成）
├── pyproject.toml          # 项目元数据与依赖
└── README.md
```

## 论文与数据

`research/xiong-pvbes-photoperiod-2026/` 目录包含该论文的归档代码和实验数据。此代码为可复现性而保留，但已不再是活跃代码库 — 当前模拟器位于 `src/`。

| 子目录 | 描述 |
|--------|------|
| `research/xiong-pvbes-photoperiod-2026/` | 原始 PV-BES 优化器（基于 EnergyPlus 的负荷生成）。包含论文所用 CLI、优化器、电池模型、天气处理器和验证数据。 |

`research/` 下每个子目录都有自己的 `README.md` 提供详细文档。

## CLI 命令参考

| 命令 | 描述 |
|------|------|
| `vfed design new <name>` | 从预设创建新的 YAML 项目文件 |
| `vfed design presets` | 列出可用预设 |
| `vfed optimize <project.yaml>` | 为项目优化光伏-电池系统 |
| `vfed evaluate <project.yaml>` | 评估特定光伏-电池配置 |
| `vfed sweep <project.yaml>` | 对光伏面积 × 电池容量进行参数化扫描 |

## 配置

所有设计参数都位于 `vfed design new` 生成的单个 YAML 文件中。主要部分：

- **site** — 纬度、经度、年份、时区
- **envelope** — 传热系数、面积、太阳吸收率、透湿率
- **hvac** — 额定制冷量、COP、设定点
- **dehumidifier** — 额定容量、相对湿度设定点、效率模型
- **led** — PPFD、光效、光周期计划
- **transpiration** — 方法（constant / VPD / Penman-Monteith / Van Henten）
- **pv** — 面板效率、NOCT、倾角、方位角
- **battery** — 容量、C-rate、往返效率、SOC 限制
- **tariff** — 峰/平/谷电价

## 贡献

1. Fork 仓库
2. 创建分支：`git checkout -b feature/my-feature`
3. 进行修改并添加测试
4. 运行测试：`pytest`
5. 提交 Pull Request

## 许可证

本项目基于 MIT 许可证 — 详见 [LICENSE](LICENSE)。

## 引用

如果您在研究中使用了 VFED，请引用：

**论文：**
```bibtex
@article{xiong2026photovoltaic,
  title={Photovoltaic-battery integration strategy in plant factories with artificial lighting},
  author={Xiong, Tianzheng and Cai, Wenxin and Hu, Yue and Song, Mingxuan and Qian, Tao and Bao, Huashan},
  journal={Energy and Buildings},
  volume={361},
  pages={117462},
  year={2026},
  publisher={Elsevier},
  doi={10.1016/j.enbuild.2026.117462}
}
```

**软件：**
```bibtex
@software{vertical-farm-energy-designer,
  title = {Vertical Farm Energy Designer (VFED)},
  author = {Thomas XIONG},
  url = {https://github.com/ThomasXIONG151215/vertical-farm-energy-designer},
  year = {2024}
}
```

## 支持

- **Issues**: https://github.com/ThomasXIONG151215/vertical-farm-energy-designer/issues
- **Discussions**: https://github.com/ThomasXIONG151215/vertical-farm-energy-designer/discussions
