# OpenCROPS / OpenCROPS

### Climate-Responsive Optimizer for Plant Systems / 气候响应式植物系统优化器

---

[![CI](https://github.com/ThomasXIONG151215/OpenCROPS/actions/workflows/ci.yml/badge.svg)](https://github.com/ThomasXIONG151215/OpenCROPS/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.8%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![License: CC BY 4.0](https://img.shields.io/badge/License-CC%20BY%204.0-lightgrey)](https://creativecommons.org/licenses/by/4.0/)

[![GitHub stars](https://img.shields.io/github/stars/ThomasXIONG151215/OpenCROPS)](https://github.com/ThomasXIONG151215/OpenCROPS/stargazers)
[![GitHub forks](https://img.shields.io/github/forks/ThomasXIONG151215/OpenCROPS)](https://github.com/ThomasXIONG151215/OpenCROPS/network)
[![Downloads](https://img.shields.io/github/downloads/ThomasXIONG151215/OpenCROPS/total)](https://github.com/ThomasXIONG151215/OpenCROPS/releases)

---

**OpenCROPS** is an open-source framework for optimizing the integration of photovoltaic and battery energy storage systems (PVBES) with Plant Factories with Artificial Lighting (PFALs).

**OpenCROPS** 是一个开源框架，用于优化光伏电池储能系统 (PVBES) 与人工光植物工厂 (PFAL) 的集成。

## Key Features / 核心特性

| English | 中文 |
|---------|------|
| **Location-Specific Load Profiles**: Generate PFAL load profiles with adjustable photoperiod schedules for any location | **地点特定负荷曲线**: 为任意地点生成可调节光周期的 PFAL 负荷曲线 |
| **PV-Battery Optimization**: Optimize PV array size and battery capacity using genetic algorithms | **光伏电池优化**: 使用遗传算法优化光伏阵列和电池容量 |
| **Climate-Responsive Design**: Evaluate system performance across diverse climate zones | **气候响应式设计**: 评估不同气候区的系统性能 |
| **Economic Analysis**: Calculate LCOE, payback period, and grid dependency reduction | **经济分析**: 计算 LCOE、回本周期和电网依赖性降低 |
| **Single Diode Model**: Physics-based PV modeling with temperature dependence | **单二极管模型**: 基于物理的光伏建模，考虑温度影响 |
| **Extensible Architecture**: Add custom models for PV, battery, and load profiles | **可扩展架构**: 添加自定义光伏、电池和负荷模型 |

## Installation / 安装

```bash
# Clone the repository / 克隆仓库
git clone https://github.com/ThomasXIONG151215/OpenCROPS.git
cd OpenCROPS

# Install in development mode / 开发模式安装
pip install -e .

# Or install with all dependencies / 或安装全部依赖
pip install -e ".[all]"
```

## Quick Start / 快速开始

```bash
# Show CLI help / 显示 CLI 帮助
opencrops --help

# Optimize for all cities / 优化所有城市
opencrops optimize

# Optimize for specific cities / 优化特定城市
opencrops optimize --cities shanghai dubai harbin

# Evaluate a specific configuration / 评估特定配置
opencrops evaluate --pv-area 200 --battery-capacity 100 --city shanghai --start-hour 8

# Calibrate optimization parameters / 校准优化参数
opencrops calibrate --city shanghai

# Analyze results / 分析结果
opencrops analyze --results-file all_optimization_results.csv
```

## CLI Commands / CLI 命令

| Command | 说明 / Description |
|---------|-------------------|
| `opencrops --version` | Show version / 显示版本 |
| `opencrops optimize` | Optimize PV-Battery system / 优化光伏电池系统 |
| `opencrops evaluate` | Evaluate single configuration / 评估单个配置 |
| `opencrops calibrate` | Calibrate step sizes / 校准步长 |
| `opencrops analyze` | Analyze results / 分析结果 |
| `opencrops mechanism` | Comparative analysis / 对比分析 |

### Available Cities / 支持的城市

```
shanghai, beijing, newyork, hohhot, urumqi, dubai, paris, sydney, 
saopaulo, harbin, chongqing, hangzhou, tianjin, zhengzhou, 
hainan, jinan, lasa, haikou
```

## Architecture Overview / 架构概览

```
OpenCROPS/
├── src/                    # Core modules / 核心模块
│   ├── __init__.py        # Package init with version / 版本信息
│   ├── cli.py             # Typer CLI interface / Typer CLI 接口
│   ├── system.py          # Energy system simulation / 能源系统仿真
│   ├── optimizer.py       # Genetic algorithm / 遗传算法
│   ├── battery.py         # Battery power flow / 电池功率流
│   ├── calibrator.py      # Step size calibration / 步长校准
│   ├── utils.py           # Utility functions / 工具函数
│   ├── visualization.py   # Plotting & visualization / 可视化
│   └── models/            # Extensible model base classes / 可扩展模型基类
│       ├── base.py        # BaseModel, BasePVModel / 基类
│       └── pv_model.py    # PV models / 光伏模型
│
├── data/                   # Data directory (Git LFS) / 数据目录
│   └── raw/               # Raw data / 原始数据
│
├── tests/                 # Test suite / 测试套件
├── docs/                  # Documentation / 文档
│   ├── _config.yml       # Jupyter Book config / Jupyter Book 配置
│   └── extensions/        # Custom model guides / 自定义模型指南
│
├── weather/               # Weather data tools / 天气数据工具
├── load_analysis/          # Load profile analysis / 负荷分析
│
├── main.py                # Legacy CLI entry / 遗留 CLI 入口
├── pyproject.toml         # Project config / 项目配置
└── README.md
```

## Usage Examples / 使用示例

### Optimize PV-Battery System / 优化光伏电池系统

```bash
# Optimize for default cities / 优化默认城市
opencrops optimize

# Optimize for specific cities / 优化特定城市
opencrops optimize --cities shanghai harbin

# Optimize with verbose output / 详细输出
opencrops optimize --verbose
```

### Evaluate Configuration / 评估配置

```bash
# Evaluate specific PV-Battery configuration / 评估特定配置
opencrops evaluate \
  --pv-area 200 \
  --battery-capacity 100 \
  --city shanghai \
  --start-hour 8
```

### Comparative Mechanism Analysis / 对比机制分析

```bash
# Compare two different photoperiod schedules / 比较两种不同光周期
opencrops mechanism \
  --pv-area 200 \
  --battery-capacity 100 \
  --city shanghai \
  --start-hour1 8 \
  --start-hour2 12
```

## Research Results / 研究结果

OpenCROPS has been validated across five representative Chinese climate regions:

OpenCROPS 已在五个代表性的中国气候区进行了验证：

| Metric / 指标 | Value / 值 |
|--------------|-----------|
| LCOE (0-3 year payback) / LCOE（0-3年回本） | $0.037-0.042/kWh |
| LCOE (3-5 year payback) / LCOE（3-5年回本） | $0.032-0.039/kWh |
| Grid Dependency Reduction / 电网依赖性降低 | 59-93% |
| Payback Period / 回本周期 | 0-5 years / 年 |

**Key Finding / 关键发现**: Photoperiod schedules aligned with peak solar hours (3:00-5:00) consistently outperform other options. / 与峰值太阳小时（3:00-5:00）对齐的光周期始终优于其他方案。

## Extending OpenCROPS / 扩展 OpenCROPS

OpenCROPS is designed to be extensible. You can add custom models for:

OpenCROPS 设计为可扩展的。您可以添加自定义模型：

- **PV Models / 光伏模型**: Implement the `BaseModel` interface to add new PV panel models / 实现 `BaseModel` 接口以添加新的光伏面板模型
- **Battery Models / 电池模型**: Extend the battery system with custom chemistry models / 使用自定义化学模型扩展电池系统
- **Load Profiles / 负荷曲线**: Create custom load profile generators for different crop types / 为不同作物类型创建自定义负荷曲线生成器

See [docs/extensions/README.md](docs/extensions/README.md) for detailed guides. / 详见 [docs/extensions/README.md](docs/extensions/README.md)。

## Data / 数据

Experimental data from the PFAL facility is available in `data/raw/`:

PFAL 设施的实验数据位于 `data/raw/`:

- `BW_data.csv`: Raw energy consumption measurements / 原始能耗测量
- `BW_processed_data.csv`: Processed and cleaned data / 处理后的数据

Data is licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). / 数据采用 [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) 许可。

## Requirements / 依赖

| Package / 包 | Version / 版本 | Description |
|-------------|---------------|-------------|
| numpy | >=1.20.0 | Numerical computing / 数值计算 |
| pandas | >=1.3.0 | Data analysis / 数据分析 |
| plotly | >=4.14.0 | Visualization / 可视化 |
| scikit-learn | >=0.24.0 | Machine learning / 机器学习 |
| deap | >=1.3.0 | Genetic algorithms / 遗传算法 |
| scipy | >=1.6.0 | Scientific computing / 科学计算 |
| typer | >=0.9.0 | CLI framework / CLI 框架 |
| tqdm | >=4.62.0 | Progress bars / 进度条 |

## Contributing / 贡献

Contributions are welcome! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

欢迎贡献！请参阅 [CONTRIBUTING.md](CONTRIBUTING.md) 获取指南。

## License / 许可证

This project is licensed under the MIT License - see [LICENSE](LICENSE) for details.

本项目采用 MIT 许可证 - 详见 [LICENSE](LICENSE)。

## Citation / 引用

If you use OpenCROPS in your research, please cite:

如果您在研究中使用 OpenCROPS，请引用：

```bibtex
@software{OpenCROPS,
  title = {OpenCROPS: Climate-Responsive Optimizer for Plant Systems},
  author = {Thomas XIONG},
  url = {https://github.com/ThomasXIONG151215/OpenCROPS},
  year = {2024}
}
```

## Support / 支持

- **Issues**: https://github.com/ThomasXIONG151215/OpenCROPS/issues
- **Discussions**: https://github.com/ThomasXIONG151215/OpenCROPS/discussions

---

<p align="center">
  Built with ❤️ for sustainable agriculture / 用 ❤️ 为可持续农业建设
</p>
