# Vertical Farm Energy Designer (VFED) (原 OpenCROPS)

**[English Version](./README.md)**

### 面向垂直农场的光伏-储能-负荷一体化能源建模开源框架

---

[![Python](https://img.shields.io/badge/python-3.8%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![License: CC BY 4.0](https://img.shields.io/badge/License-CC%20BY%204.0-lightgrey)](https://creativecommons.org/licenses/by/4.0/)

[![GitHub stars](https://img.shields.io/github/stars/ThomasXIONG151215/vertical-farm-energy-designer)](https://github.com/ThomasXIONG151215/vertical-farm-energy-designer/stargazers)
[![GitHub forks](https://img.shields.io/github/forks/ThomasXIONG151215/vertical-farm-energy-designer)](https://github.com/ThomasXIONG151215/vertical-farm-energy-designer/network)
[![Downloads](https://img.shields.io/github/downloads/ThomasXIONG151215/vertical-farm-energy-designer/total)](https://github.com/ThomasXIONG151215/vertical-farm-energy-designer/releases)

---

**Vertical Farm Energy Designer (VFED)** 是一个开源框架，用于优化光伏电池储能系统 (PVBES) 与人工光植物工厂 (PFAL) 的集成。

## 核心特性

| 特性 | 说明 |
|------|------|
| **地点特定负荷曲线** | 为任意地点生成可调节光周期的 PFAL 负荷曲线 |
| **光伏电池优化** | 使用遗传算法优化光伏阵列和电池容量 |
| **气候响应式设计** | 评估不同气候区的系统性能 |
| **经济分析** | 计算 LCOE、回本周期和电网依赖性降低 |
| **单二极管模型** | 基于物理的光伏建模，考虑温度影响 |
| **可扩展架构** | 添加自定义光伏、电池和负荷模型 |

## 安装

```bash
# 克隆仓库
git clone https://github.com/ThomasXIONG151215/vertical-farm-energy-designer.git
cd vertical-farm-energy-designer

# 开发模式安装
pip install -e .

# 安装全部依赖
pip install -e ".[all]"
```

## 快速开始

```bash
# 显示 CLI 帮助
vf-ed --help

# 优化所有城市
vf-ed optimize

# 优化特定城市
vf-ed optimize --cities shanghai dubai harbin

# 评估特定配置
vf-ed evaluate --pv-area 200 --battery-capacity 100 --city shanghai --start-hour 8

# 校准优化参数
vf-ed calibrate --city shanghai

# 分析结果
vf-ed analyze --results-file all_optimization_results.csv
```

## CLI 命令

| 命令 | 说明 |
|------|------|
| `vf-ed --version` | 显示版本 |
| `vf-ed optimize` | 优化所有或选定城市的光伏电池系统 |
| `vf-ed evaluate` | 评估单个光伏电池配置 |
| `vf-ed calibrate` | 校准某城市的优化步长 |
| `vf-ed analyze` | 分析优化结果 |
| `vf-ed mechanism` | 对比分析两种不同起始时间的光周期机制 |

### 支持的城市

```
shanghai, beijing, newyork, hohhot, urumqi, dubai, paris, sydney,
saopaulo, harbin, chongqing, hangzhou, tianjin, zhengzhou,
hainan, jinan, lasa, haikou
```

## 架构概览

```
vertical-farm-energy-designer/
├── src/                    # 核心模块
│   ├── __init__.py        # 包初始化与版本信息
│   ├── cli.py             # Typer CLI 接口
│   ├── system.py          # 能源系统仿真
│   ├── optimizer.py        # 遗传算法
│   ├── battery.py          # 电池功率流
│   ├── calibrator.py       # 步长校准
│   ├── utils.py            # 工具函数
│   ├── visualization.py    # 绘图与可视化
│   └── models/             # 可扩展模型基类
│       ├── base.py         # BaseModel, BasePVModel
│       └── pv_model.py     # 光伏模型
│
├── data/                   # 数据目录 (Git LFS)
│   └── raw/               # 原始数据
│
├── tests/                  # 测试套件
├── docs/                   # 文档
│   ├── _config.yml        # Jupyter Book 配置
│   └── extensions/         # 自定义模型指南
│
├── weather/                # 天气数据工具
├── load_analysis/          # 负荷分析
│
├── main.py                 # 遗留 CLI 入口
├── pyproject.toml          # 项目配置
└── README.md
```

## 使用示例

### 优化光伏电池系统

```bash
# 优化默认城市
vf-ed optimize

# 优化特定城市
vf-ed optimize --cities shanghai harbin

# 详细输出
vf-ed optimize --verbose
```

### 评估配置

```bash
# 评估特定光伏电池配置
vf-ed evaluate \
  --pv-area 200 \
  --battery-capacity 100 \
  --city shanghai \
  --start-hour 8
```

### 对比机制分析

```bash
# 比较两种不同光周期
vf-ed mechanism \
  --pv-area 200 \
  --battery-capacity 100 \
  --city shanghai \
  --start-hour1 8 \
  --start-hour2 12
```

## 研究结果

Vertical Farm Energy Designer 已在五个代表性的中国气候区进行了验证：

| 指标 | 值 |
|------|-----|
| LCOE（0-3年回本） | $0.037-0.042/kWh |
| LCOE（3-5年回本） | $0.032-0.039/kWh |
| 电网依赖性降低 | 59-93% |
| 回本周期 | 0-5 年 |

**关键发现**：与峰值太阳小时（3:00-5:00）对齐的光周期始终优于其他方案。

## 扩展

Vertical Farm Energy Designer 设计为可扩展的，您可以添加自定义模型：

- **光伏模型**：实现 `BaseModel` 接口以添加新的光伏面板模型
- **电池模型**：使用自定义化学模型扩展电池系统
- **负荷曲线**：为不同作物类型创建自定义负荷曲线生成器

详见 [docs/extensions/README.md](docs/extensions/README.md)。

## 数据

PFAL 设施的实验数据位于 `data/raw/`：

- `BW_data.csv`：原始能耗测量
- `BW_processed_data.csv`：处理后的数据

数据采用 [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) 许可。

## 依赖

| 包 | 版本 | 说明 |
|----|------|------|
| numpy | >=1.20.0 | 数值计算 |
| pandas | >=1.3.0 | 数据分析 |
| plotly | >=4.14.0 | 可视化 |
| scikit-learn | >=0.24.0 | 机器学习 |
| deap | >=1.3.0 | 遗传算法 |
| scipy | >=1.6.0 | 科学计算 |
| typer | >=0.9.0 | CLI 框架 |
| tqdm | >=4.62.0 | 进度条 |

## 贡献

欢迎贡献！请参阅 [CONTRIBUTING.md](CONTRIBUTING.md) 获取指南。

## 许可证

本项目采用 MIT 许可证 - 详见 [LICENSE](LICENSE)。

## 引用

如果您在研究中使用 Vertical Farm Energy Designer，请引用：

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

---

<p align="center">
  用 ❤️ 为可持续农业建设
</p>
