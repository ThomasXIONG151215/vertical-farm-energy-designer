# Vertical Farm Energy Designer (VFED) (formerly OpenCROPS)

**[中文版](./README_zh.md)**

### An open-source framework for PV-Battery-Load energy modeling in vertical farms

---

[![Python](https://img.shields.io/badge/python-3.8%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![License: CC BY 4.0](https://img.shields.io/badge/License-CC%20BY%204.0-lightgrey)](https://creativecommons.org/licenses/by/4.0/)

[![GitHub stars](https://img.shields.io/github/stars/ThomasXIONG151215/vertical-farm-energy-designer)](https://github.com/ThomasXIONG151215/vertical-farm-energy-designer/stargazers)
[![GitHub forks](https://img.shields.io/github/forks/ThomasXIONG151215/vertical-farm-energy-designer)](https://github.com/ThomasXIONG151215/vertical-farm-energy-designer/network)
[![Downloads](https://img.shields.io/github/downloads/ThomasXIONG151215/vertical-farm-energy-designer/total)](https://github.com/ThomasXIONG151215/vertical-farm-energy-designer/releases)

---

**Vertical Farm Energy Designer (VFED)** is an open-source framework for optimizing the integration of photovoltaic and battery energy storage systems (PVBES) with Plant Factories with Artificial Lighting (PFALs).

## Key Features

| Feature | Description |
|---------|-------------|
| **Location-Specific Load Profiles** | Generate PFAL load profiles with adjustable photoperiod schedules for any location |
| **PV-Battery Optimization** | Optimize PV array size and battery capacity using genetic algorithms |
| **Climate-Responsive Design** | Evaluate system performance across diverse climate zones |
| **Economic Analysis** | Calculate LCOE, payback period, and grid dependency reduction |
| **Single Diode Model** | Physics-based PV modeling with temperature dependence |
| **Extensible Architecture** | Add custom models for PV, battery, and load profiles |

## Installation

```bash
# Clone the repository
git clone https://github.com/ThomasXIONG151215/vertical-farm-energy-designer.git
cd vertical-farm-energy-designer

# Install in development mode
pip install -e .

# Or install with all dependencies
pip install -e ".[all]"
```

## Quick Start

```bash
# Show CLI help
vfed --help

# Optimize for all cities
vfed optimize

# Optimize for specific cities
vfed optimize --cities shanghai dubai harbin

# Evaluate a specific configuration
vfed evaluate --pv-area 200 --battery-capacity 100 --city shanghai --start-hour 8

# Calibrate optimization parameters
vfed calibrate --city shanghai

# Analyze results
vfed analyze --results-file all_optimization_results.csv
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `vfed --version` | Show version |
| `vfed optimize` | Optimize PV-Battery system for all or selected cities |
| `vfed evaluate` | Evaluate a single PV-Battery configuration |
| `vfed calibrate` | Calibrate optimization step sizes for a city |
| `vfed analyze` | Analyze optimization results |
| `vfed mechanism` | Comparative mechanism analysis with two different start hours |

### Available Cities

```
shanghai, beijing, newyork, hohhot, urumqi, dubai, paris, sydney,
saopaulo, harbin, chongqing, hangzhou, tianjin, zhengzhou,
hainan, jinan, lasa, haikou
```

## Architecture Overview

```
vertical-farm-energy-designer/
├── src/                    # Core modules
│   ├── __init__.py        # Package init with version
│   ├── cli.py             # Typer CLI interface
│   ├── system.py          # Energy system simulation
│   ├── optimizer.py       # Genetic algorithm
│   ├── battery.py         # Battery power flow
│   ├── calibrator.py      # Step size calibration
│   ├── utils.py           # Utility functions
│   ├── visualization.py   # Plotting & visualization
│   └── models/            # Extensible model base classes
│       ├── base.py        # BaseModel, BasePVModel
│       └── pv_model.py    # PV models
│
├── data/                   # Data directory (Git LFS)
│   └── raw/               # Raw data
│
├── tests/                 # Test suite
├── docs/                  # Documentation
│   ├── _config.yml       # Jupyter Book config
│   └── extensions/        # Custom model guides
│
├── weather/               # Weather data tools
├── load_analysis/          # Load profile analysis
│
├── main.py                # Legacy CLI entry
├── pyproject.toml         # Project config
└── README.md
```

## Usage Examples

### Optimize PV-Battery System

```bash
# Optimize for default cities
vfed optimize

# Optimize for specific cities
vfed optimize --cities shanghai harbin

# Optimize with verbose output
vfed optimize --verbose
```

### Evaluate Configuration

```bash
# Evaluate specific PV-Battery configuration
vfed evaluate \
  --pv-area 200 \
  --battery-capacity 100 \
  --city shanghai \
  --start-hour 8
```

### Comparative Mechanism Analysis

```bash
# Compare two different photoperiod schedules
vfed mechanism \
  --pv-area 200 \
  --battery-capacity 100 \
  --city shanghai \
  --start-hour1 8 \
  --start-hour2 12
```

## Research Results

Vertical Farm Energy Designer has been validated across five representative Chinese climate regions:

| Metric | Value |
|--------|-------|
| LCOE (0-3 year payback) | $0.037-0.042/kWh |
| LCOE (3-5 year payback) | $0.032-0.039/kWh |
| Grid Dependency Reduction | 59-93% |
| Payback Period | 0-5 years |

**Key Finding**: Photoperiod schedules aligned with peak solar hours (3:00-5:00) consistently outperform other options.

## Extending

Vertical Farm Energy Designer is designed to be extensible. You can add custom models for:

- **PV Models**: Implement the `BaseModel` interface to add new PV panel models
- **Battery Models**: Extend the battery system with custom chemistry models
- **Load Profiles**: Create custom load profile generators for different crop types

See [docs/extensions/README.md](docs/extensions/README.md) for detailed guides.

## Data

Experimental data from the PFAL facility is available in `data/raw/`:

- `BW_data.csv`: Raw energy consumption measurements
- `BW_processed_data.csv`: Processed and cleaned data

Data is licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

## Requirements

| Package | Version | Description |
|---------|---------|-------------|
| numpy | >=1.20.0 | Numerical computing |
| pandas | >=1.3.0 | Data analysis |
| plotly | >=4.14.0 | Visualization |
| scikit-learn | >=0.24.0 | Machine learning |
| deap | >=1.3.0 | Genetic algorithms |
| scipy | >=1.6.0 | Scientific computing |
| typer | >=0.9.0 | CLI framework |
| tqdm | >=4.62.0 | Progress bars |

## Contributing

Contributions are welcome! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## License

This project is licensed under the MIT License - see [LICENSE](LICENSE) for details.

## Citation

If you use Vertical Farm Energy Designer in your research, please cite:

```bibtex
@software{vertical-farm-energy-designer,
  title = {Vertical Farm Energy Designer (VFED)},
  author = {Thomas XIONG},
  url = {https://github.com/ThomasXIONG151215/vertical-farm-energy-designer},
  year = {2024}
}
```

## Support

- **Issues**: https://github.com/ThomasXIONG151215/vertical-farm-energy-designer/issues
- **Discussions**: https://github.com/ThomasXIONG151215/vertical-farm-energy-designer/discussions

---

<p align="center">
  Built with ❤️ for sustainable agriculture
</p>
