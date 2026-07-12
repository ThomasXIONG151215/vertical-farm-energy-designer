# Vertical Farm Energy Designer (VFED)

> [中文版](./README_zh.md) | English

> An open-source design simulator for **Plant Factories with Artificial Lighting (PFALs)** — couples a first-principles building energy model to a PV-Battery-Grid system for minimum-LCOE solar+storage sizing.

[![GitHub stars](https://img.shields.io/github/stars/ThomasXIONG151215/vertical-farm-energy-designer?style=social)](https://github.com/ThomasXIONG151215/vertical-farm-energy-designer/stargazers)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Python 3.8+](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://www.python.org/)

## Background

Plant Factories with Artificial Lighting (PFALs) — fully enclosed, multi-layer growing facilities that replace sunlight with LEDs — are among the most energy-intensive agricultural systems, consuming **200–500 kWh/m²/year** for lighting, HVAC, and dehumidification combined. Grid electricity dominates operating costs, often exceeding 30% of total production expense.

Integrating rooftop photovoltaics (PV) with battery energy storage (BES) can dramatically reduce grid dependency and operating costs. But the optimal PV array size and battery capacity depend on a complex interplay of factors: geographic location, local climate, building envelope, crop photoperiod schedule, and time-of-use electricity tariff. There is no universal rule of thumb — each facility needs a site-specific design.

**VFED** solves this problem. It simulates a PFAL's hourly energy balance using first-principles physics (wet-air thermodynamics, envelope heat transfer, ODE-based room model), then sweeps PV area × battery capacity to find the design that minimises the **Levelised Cost of Energy (LCOE)**.

> 📄 This tool accompanies the paper:
> **Xiong, T., Cai, W., Hu, Y., Song, M., Qian, T., & Bao, H. (2026).** *Photovoltaic-battery integration strategy in plant factories with artificial lighting.* Energy and Buildings, 361, 117462.
> [DOI: 10.1016/j.enbuild.2026.117462](https://doi.org/10.1016/j.enbuild.2026.117462)

The `research/xiong-pvbes-photoperiod-2026/` directory contains the archived code and experimental data from the published paper. The current active codebase (`src/`) replaces the EnergyPlus-based load generator with a pure-Python first-principles ODE solver and adds a parametric design sweep — see [research/xiong-pvbes-photoperiod-2026/](research/xiong-pvbes-photoperiod-2026/) for details.

## How VFED Works

| Challenge | VFED Approach |
|-----------|---------------|
| PFAL loads depend on climate, envelope, and lighting schedule | First-principles ODE solver — room heat & moisture balance, no EnergyPlus dependency |
| PV output varies with location, tilt, and weather | Single-diode PV model with Open-Meteo hourly weather data |
| Battery sizing is a trade-off between cost and self-sufficiency | Parametric sweep over (PV area × battery capacity) → LCOE-optimal design |
| Electricity tariff structure affects economics | Time-of-use tariff model (peak / normal / valley pricing) |
| Plant transpiration adds latent load | 4 configurable transpiration methods, from constant to Van Henten growth model |

## Quick Start

### Install

```bash
git clone https://github.com/ThomasXIONG151215/vertical-farm-energy-designer.git
cd vertical-farm-energy-designer
pip install -e .
# or with all optional dependencies:
pip install -e ".[all]"
```

### Create a Design

```bash
vfed design new my_farm --preset 609 --lat 30.9 --lon 121.5 --year 2023
```

### Optimise

```bash
vfed optimize my_farm.yaml --cache weather_cache --out results.csv
```

### Evaluate a Configuration

```bash
vfed evaluate my_farm.yaml --pv-area 120 --battery 40
```

### Parametric Sweep

```bash
vfed sweep my_farm.yaml --out sweep_results.csv
```

## Architecture

```
┌─────────────┐     ┌──────────────────────────────────────────────┐
│   Weather   │────▶│              Design Engine                   │
│  (Open-Meteo)│     │  (src/design/engine.py — ODE integration)   │
└─────────────┘     │                                              │
                    │  ┌──────────┐ ┌──────────┐ ┌──────────────┐ │
                    │  │ Physics  │ │ Devices  │ │   Plants     │ │
                    │  │ psychro- │ │ HVAC     │ │ transpiration│ │
                    │  │ metrics, │ │ dehumid. │ │ Van Henten   │ │
                    │  │ envelope,│ │ LED      │ │              │ │
                    │  │ ODE, SHR │ │ compressor│ │              │ │
                    │  └──────────┘ └──────────┘ └──────────────┘ │
                    └──────────────────┬───────────────────────────┘
                                       │ hourly load profile
                    ┌──────────────────▼───────────────────────────┐
                    │         PVBES Sweep & Optimisation           │
                    │  (src/design/sweep.py + src/pvbes/)         │
                    │  PVSystem → BatterySystem → Tariff → LCOE   │
                    └──────────────────┬───────────────────────────┘
                                       │
                              LCOE-optimal design
```

## Repository Layout

```
vertical-farm-energy-designer/
├── src/                    # Core simulator code
│   ├── physics/            # Psychrometrics, envelope, ODE solver, SHR
│   ├── devices/            # HVAC, dehumidifier, LED, compressor, lag
│   ├── pvbes/              # PV (single-diode), battery (Zhao 2024), grid (TOU), energy system
│   ├── design/             # Project config (YAML), engine, presets, sweep
│   ├── weather/            # Open-Meteo bridge, Erbs GHI split, POA, geocoding
│   ├── plants/             # Transpiration (4 methods), Van Henten growth model
│   ├── agent/              # Evaluator (preserves agent-cli error-code contract)
│   └── cli.py              # CLI entry point: vfed
├── research/               # Archived research paper code & data (see below)
├── reference/              # Reference literature
├── weather_cache/          # Cached weather CSVs (auto-generated)
├── pyproject.toml          # Project metadata & dependencies
└── README.md
```

## Research Papers & Data

The `research/xiong-pvbes-photoperiod-2026/` directory contains the archived code and experimental data from the published paper. This code is preserved for reproducibility but is no longer the active codebase — the current simulator lives in `src/`.

| Subfolder | Description |
|-----------|-------------|
| `research/xiong-pvbes-photoperiod-2026/` | Original PV-BES optimiser (EnergyPlus-based load generation). Contains the CLI, optimizer, battery model, weather processor, and validation data used in the published results. |

Each subfolder under `research/` has its own `README.md` with detailed documentation.

## CLI Reference

| Command | Description |
|---------|-------------|
| `vfed design new <name>` | Create a new YAML project file from a preset |
| `vfed design presets` | List available presets |
| `vfed optimize <project.yaml>` | Optimise PV-Battery system for a project |
| `vfed evaluate <project.yaml>` | Evaluate a specific PV-Battery configuration |
| `vfed sweep <project.yaml>` | Run parametric sweep over PV area × battery capacity |

## Configuration

All design parameters live in a single YAML file generated by `vfed design new`. Key sections:

- **site** — latitude, longitude, year, timezone
- **envelope** — U-values, area, solar absorptance, vapour permeance
- **hvac** — rated cooling capacity, COP, setpoints
- **dehumidifier** — rated capacity, RH setpoints, efficiency model
- **led** — PPFD, efficacy, photoperiod schedule
- **transpiration** — method (constant / VPD / Penman-Monteith / Van Henten)
- **pv** — panel efficiency, NOCT, tilt, azimuth
- **battery** — capacity, C-rates, round-trip efficiency, SOC limits
- **tariff** — peak/normal/valley electricity prices

## Contributing

1. Fork the repository
2. Create a branch: `git checkout -b feature/my-feature`
3. Make changes and add tests
4. Run tests: `pytest`
5. Submit a pull request

## License

This project is licensed under the MIT License — see [LICENSE](LICENSE) for details.

## Citation

If you use VFED in your research, please cite:

**Paper:**
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

**Software:**
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
