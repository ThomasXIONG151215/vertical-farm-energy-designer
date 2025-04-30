# Energy Consumption Analysis of a Typical Plant Factory with Artificial Lighting (PFAL)

## 1. Introduction and Background

Previous research by YZT established the initial energy consumption profile of an existing plant factory with artificial lighting (PFAL) and validated methodologies for calculating thermal load distribution. While that study provided valuable insights, it was limited to summer 2023 data collection. This current analysis expands upon that foundation with comprehensive year-round data collected throughout 2024, offering a more complete understanding of PFAL energy dynamics across seasonal variations.

The present study focuses on operational energy consumption patterns under normal functioning conditions. Equipment loads are characterized according to specifications, while plant thermal loads—previously validated in YZT's research—are reasonably estimated using LED lighting data as a proxy indicator.

To ensure data representativeness, cultivation planning was intentionally left to the discretion of the professional growers without researcher intervention, reflecting authentic operational conditions of commercial PFAL facilities.

## 2. Methodology

### 2.1 Data Collection

Data collection spanned a complete calendar year (January-December 2024), with continuous monitoring of all major energy-consuming components:

- LED lighting systems
- Air conditioning (AC) units
- Fresh air units (FAU)
- Fan filter units (FFU)

Energy consumption was measured at 15-minute intervals using calibrated power meters installed on each subsystem circuit, with an accuracy of ±1.5%.

### 2.2 COP Calculation

The air conditioning coefficient of performance (COP) was calculated following the methodology established in YZT's study, where:

COP = Total thermal load / AC energy consumption

Since detailed operational parameters within the AC systems were not available, data filtration was applied to exclude low-load periods (typically during dark photoperiods) when AC units might operate at suboptimal efficiency levels. This approach ensures the COP values reasonably represent normal operational conditions.

## 3. Results and Discussion

### 3.1 Annual Energy Consumption Patterns

**Figure 1B: Daily Energy Consumption** presents a comprehensive visualization of daily energy consumption throughout 2024. The time-series plot reveals distinct consumption patterns across different components of the PFAL system:

- **Total energy consumption** (orange line) shows significant seasonal variations, ranging from approximately 20 kWh/day during winter months to peak values exceeding 45 kWh/day during summer and early fall.
- **LED lighting** (blue line) demonstrates relatively consistent consumption patterns (10-20 kWh/day) with periodic adjustments likely corresponding to crop production cycles.
- **Air conditioning** (red line) exhibits the most pronounced seasonal variation, with minimal usage in winter months (below 5 kWh/day) and significantly higher consumption during summer (up to 25 kWh/day).
- **Fan and ventilation systems** (green and teal lines) maintain relatively stable consumption throughout the year.

A notable operation interruption occurred during February-March coinciding with the Spring Festival holiday period, when the facility temporarily suspended operations.

### 3.2 Seasonal Energy Distribution

**Figure 1C: Average Daily Energy Consumption by Season** quantifies the seasonal variations in energy use and the relative contribution of each component to the total energy footprint:

- **Summer** exhibits the highest total daily energy consumption (31.5 kWh/day), driven primarily by increased HVAC demands (13.4 kWh/day) while maintaining consistent lighting requirements (12.7 kWh/day).
- **Fall** shows the second-highest consumption (27.9 kWh/day), with more balanced distribution between HVAC (10.7 kWh/day) and lighting (10.7 kWh/day).
- **Spring** demonstrates moderate energy use (23.4 kWh/day), with lighting (12.5 kWh/day) exceeding HVAC requirements (5.9 kWh/day).
- **Winter** presents the lowest total consumption (20.6 kWh/day), with minimal HVAC demand (5.5 kWh/day) and continued lighting requirements (10.2 kWh/day).

The data reveals that while lighting energy consumption remains relatively consistent across seasons (10.2-12.7 kWh/day), HVAC energy consumption varies by more than 140% between summer and winter. Fan filter units (FFU) show modest seasonal variation (4.3-5.8 kWh/day), while fresh air units (FAU) contribute minimally to the overall energy profile (0.1-0.7 kWh/day).

### 3.3 Seasonal COP Analysis

**Figure 1D: Seasonal COP** illustrates the efficiency performance of the HVAC system throughout different seasons:

- **Winter** demonstrates the highest COP value (3.94), indicating optimal efficiency when thermal load requirements are predominantly heating-oriented.
- **Spring** exhibits similarly high efficiency (3.85 COP), suggesting favorable operating conditions during moderate temperature periods.
- **Summer** shows reduced efficiency (2.73 COP), reflecting the challenges of maintaining optimal growing conditions during periods of high external temperatures and humidity.
- **Fall** presents the lowest seasonal COP (2.57), which may be attributed to transitional weather patterns requiring frequent switching between heating and cooling modes.

The substantial variation in COP values (ranging from 2.57 to 3.94) underscores the significant impact of seasonal environmental conditions on HVAC system efficiency within controlled environment agriculture facilities.

## 4. Load Profile Generation for Different Geographic Locations

To facilitate PFAL energy analysis across diverse geographical contexts, a methodology was developed to generate location-specific load profiles. This process utilizes:

1. Acquisition of annual meteorological data for the target region from the Open-Meteo API
2. Application of validated EnergyPlus simulation models with parameters established in the previous research
3. Generation of heating/cooling load profiles and equipment energy consumption estimates
4. Incorporation of seasonally-adjusted COP values to calculate HVAC energy consumption
5. Integration of all energy sources to produce comprehensive annual load profiles specific to the target location

The Open-Meteo API provides a reliable and comprehensive source of historical meteorological data with high spatial resolution (ranging from 1 to 11 kilometers). This data service combines multiple observation sources including weather stations, aircraft, buoy, radar, and satellite measurements through reanalysis datasets to create accurate historical weather records, particularly valuable for locations without nearby weather stations [Open-Meteo, 2023](https://open-meteo.com/en/docs/historical-weather-api). 

For our study, we utilized key parameters including temperature, relative humidity, solar radiation (shortwave_radiation_sum), and wind data. The ECMWF IFS dataset employed by Open-Meteo offers exceptional resolution and precision in depicting historical weather conditions, making it particularly suitable for our energy simulation requirements. This approach allows us to generate reliable load profiles for virtually any geographic location worldwide, even in regions with limited historical weather station coverage.

The EnergyPlus simulation framework employed in this study has been verified against YZT's model results, ensuring consistency and reliability in the load profile generation process. By incorporating Open-Meteo's high-quality meteorological data, our methodology provides a robust foundation for analyzing PFAL energy dynamics across diverse climatological contexts.

## 5. Conclusion

This comprehensive year-round energy analysis of a commercial PFAL facility provides valuable insights into the seasonal dynamics of energy consumption patterns. The findings reveal that while lighting energy requirements remain relatively consistent, HVAC energy demands fluctuate significantly across seasons, substantially impacting overall facility efficiency.

The seasonal COP analysis demonstrates that HVAC systems achieve peak efficiency during winter and spring months, with notable performance degradation during summer and fall. These observations highlight the importance of optimizing HVAC design and control strategies to maintain high efficiency across diverse seasonal conditions.

The methodology developed for generating location-specific load profiles enables the extension of these findings to diverse geographical contexts, supporting more accurate feasibility assessments and system designs for PFAL implementations worldwide. By leveraging reliable meteorological data from the Open-Meteo API and validated energy simulation models, this approach facilitates comprehensive energy analysis for virtually any location, providing a valuable tool for PFAL planning and optimization in different climate zones.

These insights contribute significantly to the growing body of knowledge on PFAL energy dynamics and will help inform more energy-efficient designs and operational strategies for controlled environment agriculture facilities. Future research should focus on developing climate-specific optimization algorithms for HVAC systems and exploring innovative approaches to reduce the seasonal variation in system efficiency.
