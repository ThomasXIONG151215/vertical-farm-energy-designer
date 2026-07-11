# Raw Experimental Data

This directory contains raw experimental data collected from the Plant Factory with Artificial Lighting (PFAL) facility.

## Files

### BW_data.csv

**Description**: Raw energy consumption data from the PFAL facility

**Source**: PFAL monitoring system (Shanghai, China)

**Collection Period**: Multi-year monitoring data (2020-2024)

**Measurement Components**:
- LED Lighting: Power consumption (kWh)
- Air Conditioning (AC): Power consumption (kWh)
- Fresh Air Units (FAU): Power consumption (kWh)
- Fan Filter Units (FFU): Power consumption (kWh)

**Sampling Frequency**: Hourly

**Data Format**: CSV with columns
- `timestamp`: ISO 8601 datetime
- `lighting_kwh`: LED lighting energy
- `ac_kwh`: Air conditioning energy
- `fau_kwh`: Fresh air unit energy
- `ffu_kwh`: Fan filter unit energy
- `total_kwh`: Total energy consumption

---

### BW_processed_data.csv

**Description**: Processed and cleaned energy consumption data

**Processing Steps**:
1. Data cleaning: Remove outliers and handle missing values
2. Temporal alignment: Align timestamps to hourly intervals
3. Unit conversion: Standardize to kWh
4. Quality check: CV(RMSE) validation against measured data

**Related Publication**:
> Xiong et al. "Climate-Responsive Optimization of PV-Battery Systems for Plant Factories with Artificial Lighting"
> Energy, 2024

---

## Data Provenance

| Aspect | Details |
|--------|---------|
| **Origin** | PFAL monitoring system, Shanghai, China |
| **Collection Method** | Direct measurement from energy meters |
| **Collection Period** | 2020-2024 |
| **Data Owner** | Thomas XIONG (thomas-xiong@sjtu.edu.cn) |
| **License** | CC BY 4.0 |

---

## Citation

If you use this data in your research, please cite:

```bibtex
@software{OpenCROPS,
  title = {OpenCROPS: Climate-Responsive Optimizer for Plant Systems},
  author = {Thomas XIONG},
  url = {https://github.com/ThomasXIONG151215/OpenCROPS},
  year = {2024}
}
```

---

## Contact

For questions about the data:
- **Email**: thomas-xiong@sjtu.edu.cn
- **GitHub Issues**: https://github.com/ThomasXIONG151215/OpenCROPS/issues

---

## FAIR Principles Compliance

This data follows the FAIR principles:

| Principle | Implementation |
|-----------|----------------|
| **Findable** | Metadata embedded in CSV headers; unique DOI (if applicable) |
| **Accessible** | Publicly available via GitHub repository |
| **Interoperable** | Standard CSV format; ISO 8601 timestamps |
| **Reusable** | CC BY 4.0 license; clear documentation |
