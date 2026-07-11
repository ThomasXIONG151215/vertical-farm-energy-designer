# Quick Start Guide

Get up and running with OpenCROPS in 5 minutes.

## Prerequisites

- Python 3.8+
- pip package manager
- Git

## Installation

### 1. Clone the Repository

```bash
git clone https://github.com/ThomasXIONG151215/OpenCROPS.git
cd OpenCROPS
```

### 2. Create Virtual Environment (Recommended)

```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

## Basic Usage

### Run Optimization for Default Cities

```bash
python main.py --mode optimize
```

This will optimize PV-battery systems for all configured cities.

### Optimize Specific Cities

```bash
python main.py --mode optimize --cities shanghai dubai harbin
```

### Evaluate a Specific Configuration

```bash
python main.py --mode evaluate --pv-area 200 --battery-capacity 100 --city shanghai
```

### Comparative Mechanism Analysis

Compare different photoperiod schedules:

```bash
python main.py --mode mechanism --pv-area 200 --battery-capacity 100 --city shanghai --start-hour1 8 --start-hour2 12
```

## Project Structure

```
OpenCROPS/
├── src/                    # Core modules
│   ├── system.py          # Energy system simulation
│   ├── optimizer.py       # Optimization algorithms
│   ├── battery.py        # Battery models
│   └── utils.py          # Utilities
├── data/                  # Data directory
│   └── raw/              # Experimental data
├── tests/                 # Test suite
├── docs/                  # Documentation
│   └── extensions/        # Custom model guides
├── main.py                # CLI entry point
└── requirements.txt       # Dependencies
```

## Configuration

### City Coordinates

Edit `weather/city_coordinates.json` to add custom locations:

```json
{
  "mycity": {
    "name": "My City",
    "latitude": 35.6895,
    "longitude": 139.6917,
    "timezone": "Asia/Tokyo"
  }
}
```

### Photoperiod Schedules

IDF templates in `idfs/` control lighting schedules. Each `light_schedule_XX.idf` represents a different photoperiod start time.

## Next Steps

- Read the [Introduction](intro.md) for a deeper understanding
- Explore [Extension Guide](../extensions/README.md) to add custom models
- Check [API Reference](../reference/api.md) for detailed module documentation

## Troubleshooting

### numba Installation Issues

If you encounter numba installation errors:

```bash
pip install numba --no-cache-dir
```

### Missing Weather Data

Run the weather processor first:

```bash
python weather_processor.py
```

### Running Tests

```bash
pytest tests/ -v
```

## Getting Help

- **GitHub Issues**: https://github.com/ThomasXIONG151215/OpenCROPS/issues
- **GitHub Discussions**: https://github.com/ThomasXIONG151215/OpenCROPS/discussions
