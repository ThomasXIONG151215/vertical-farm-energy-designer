# Introduction to OpenCROPS

**OpenCROPS** (Climate-Responsive Optimizer for Plant Systems) is an open-source framework designed to optimize the integration of photovoltaic (PV) and battery energy storage systems (BESS) with Plant Factories with Artificial Lighting (PFALs).

## What is OpenCROPS?

OpenCROPS addresses one of the critical challenges in modern agriculture: the high energy consumption of indoor farming systems. By leveraging advanced optimization algorithms and climate-responsive design principles, OpenCROPS enables:

- **Significant energy cost reduction** through optimal PV-battery sizing
- **Grid dependency minimization** while maintaining crop production
- **Climate-adaptive system design** across diverse geographical contexts

## Key Capabilities

### 1. Energy System Simulation

OpenCROPS provides physics-based models for:

- **Photovoltaic Systems**: Single Diode Model (SDM) with temperature dependence
- **Battery Energy Storage**: Power flow calculations with state-of-charge management
- **Load Profiles**: PFAL energy consumption based on photoperiod scheduling

### 2. Optimization Engine

Using genetic algorithms (DEAP), OpenCROPS finds optimal system configurations:

- PV array sizing (30-70 m² range)
- Battery capacity (10-30 kWh range)
- Operational schedules (photoperiod timing)

### 3. Multi-Climate Support

Pre-validated for diverse climate zones including:

| Climate Zone | Example Cities |
|--------------|----------------|
| Cold | Harbin, Hohhot |
| Temperate | Shanghai, Beijing |
| Hot-Humid | Haikou, Zhengzhou |
| Hot-Dry | Dubai |

## Research Impact

Based on validation across five representative Chinese climate regions:

- **LCOE**: $0.032-0.042/kWh (56-67% reduction from grid price)
- **Grid Dependency**: 59-93% reduction
- **Payback Period**: 0-5 years

## Who Should Use OpenCROPS?

OpenCROPS is designed for:

- **Researchers** studying sustainable agriculture and energy systems
- **PFAL Operators** optimizing their energy infrastructure
- **Engineers** designing new PFAL facilities
- **Policymakers** evaluating climate-smart agriculture investments

## Quick Links

- [Quick Start Guide](quickstart.md) - Get up and running in 5 minutes
- [Extension Guide](../extensions/README.md) - Add your own models
- [API Reference](../reference/api.md) - Detailed module documentation
- [GitHub Repository](https://github.com/ThomasXIONG151215/OpenCROPS)

## License and Citation

OpenCROPS is open-source under the MIT License. Experimental data is available under CC BY 4.0.

If you use OpenCROPS in your research, please cite:

```bibtex
@software{OpenCROPS,
  title = {OpenCROPS: Climate-Responsive Optimizer for Plant Systems},
  author = {Thomas XIONG},
  url = {https://github.com/ThomasXIONG151215/OpenCROPS},
  year = {2024}
}
```
