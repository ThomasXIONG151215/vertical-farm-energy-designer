# OpenCROPS Data Directory

This directory contains experimental and processed data for the OpenCROPS project.

## Directory Structure

```
data/
├── raw/                    # Raw experimental data
│   ├── BW_data.csv        # Raw energy consumption data from PFAL facility
│   ├── BW_processed_data.csv  # Processed energy data
│   └── README.md          # Raw data documentation
│
├── processed/             # Processed simulation results
│   └── README.md         # Processed data documentation
│
└── README.md             # This file
```

## Data Overview

### Raw Data (`raw/`)

Contains original experimental data collected from the Plant Factory with Artificial Lighting (PFAL) facility:

- **BW_data.csv**: Raw energy consumption measurements (timestamped)
- **BW_processed_data.csv**: Processed and cleaned energy data

### Processed Data (`processed/`)

Contains results from EnergyPlus simulations and optimization runs.

## Data Licensing

The experimental data in this repository is licensed under **CC BY 4.0**. When using this data, please cite:

```
OpenCROPS: Climate-Responsive Optimizer for Plant Systems
https://github.com/ThomasXIONG151215/OpenCROPS
```

## Large File Handling

This repository uses **Git LFS** (Large File Storage) to handle large data files efficiently:

- CSV files (> 100KB) are stored in Git LFS
- Images and PDFs are stored in Git LFS
- Make sure you have Git LFS installed: `git lfs install`

## Contributing

If you have additional experimental data to contribute:
1. Place raw data in `data/raw/`
2. Document the data source in `data/raw/README.md`
3. Follow the FAIR principles (Findable, Accessible, Interoperable, Reusable)

## References

- [FAIR Principles](https://www.go-fair.org/fair-principles/)
- [Git LFS Documentation](https://git-lfs.github.io/)
