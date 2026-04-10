# OpenCROPS

### Climate-Responsive Optimizer for Plant Systems

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

## Key Features

- **Location-Specific Load Profiles**: Generate PFAL load profiles with adjustable photoperiod schedules for any location
- **PV-Battery Optimization**: Optimize PV array size and battery capacity using genetic algorithms
- **Climate-Responsive Design**: Evaluate system performance across diverse climate zones
- **Economic Analysis**: Calculate LCOE, payback period, and grid dependency reduction
- **Single Diode Model**: Physics-based PV modeling with temperature dependence
- **Extensible Architecture**: Add custom models for PV, battery, and load profiles

## Quick Start

```bash
# Clone the repository
git clone https://github.com/ThomasXIONG151215/OpenCROPS.git
cd OpenCROPS

# Install dependencies
pip install -r requirements.txt

# Run optimization for default cities
python main.py --mode optimize
```

## Architecture Overview

```
OpenCROPS/
├── src/                    # Core modules
│   ├── system.py          # Energy system simulation (PV, battery, grid)
│   ├── optimizer.py       # Genetic algorithm optimization
│   ├── battery.py         # Battery power flow calculations
│   ├── utils.py           # Utility functions
│   └── visualization.py   # Plotting and visualization
│
├── data/                   # Data directory (Git LFS)
│   └── raw/               # Experimental data (BW_data.csv)
│
├── tests/                 # Test suite
├── docs/                  # Documentation
│   └── extensions/        # Guide to adding custom models
│
├── main.py                # CLI entry point
└── requirements.txt       # Dependencies
```

## Usage Examples

### Optimize PV-Battery System

```bash
# Optimize for specific cities
python main.py --mode optimize --cities shanghai dubai harbin

# Evaluate a specific configuration
python main.py --mode evaluate --pv-area 200 --battery-capacity 100 --city shanghai
```

### Generate Load Profiles

```bash
# Generate load profiles using EnergyPlus templates
python create_load_profiles.py --mode generate

# Validate custom IDF model
python create_load_profiles.py --mode validate --idf "path/to/model.idf" --epw "path/to/weather.epw"
```

### Analyze Results

```bash
# Comparative mechanism analysis
python main.py --mode mechanism --pv-area 200 --battery-capacity 100 --city shanghai --start-hour1 8 --start-hour2 12
```

## Research Results

OpenCROPS has been validated across five representative Chinese climate regions:

| Metric | Value |
|--------|-------|
| LCOE (0-3 year payback) | $0.037-0.042/kWh |
| LCOE (3-5 year payback) | $0.032-0.039/kWh |
| Grid Dependency Reduction | 59-93% |
| Payback Period | 0-5 years |

**Key Finding**: Photoperiod schedules aligned with peak solar hours (3:00-5:00) consistently outperform other options.

## Extending OpenCROPS

OpenCROPS is designed to be extensible. You can add custom models for:

- **PV Models**: Implement the `BaseModel` interface to add new PV panel models
- **Battery Models**: Extend the battery system with custom chemistry models
- **Load Profiles**: Create custom load profile generators for different crop types

See [docs/extensions/README.md](docs/extensions/README.md) for detailed guides.

## Data

Experimental data from the PFAL facility is available in `data/raw/`:

- `BW_data.csv`: Raw energy consumption measurements
- `BW_processed_data.csv`: Processed and cleaned data

Data is licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

## Contributing

Contributions are welcome! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## License

This project is licensed under the MIT License - see [LICENSE](LICENSE) for details.

## Citation

If you use OpenCROPS in your research, please cite:

```bibtex
@software{OpenCROPS,
  title = {OpenCROPS: Climate-Responsive Optimizer for Plant Systems},
  author = {Thomas XIONG},
  url = {https://github.com/ThomasXIONG151215/OpenCROPS},
  year = {2024}
}
```

## Support

- **Issues**: https://github.com/ThomasXIONG151215/OpenCROPS/issues
- **Discussions**: https://github.com/ThomasXIONG151215/OpenCROPS/discussions

---

<p align="center">
  Built with ❤️ for sustainable agriculture
</p>
