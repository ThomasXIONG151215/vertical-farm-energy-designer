## 3. Results and Discussion

### 3.1 System Performance Metrics

The comparative analysis of the four system configurations revealed significant variations in performance metrics:

**PV Utilization:**
- PV03: 13.2%
- PVB03: 27.5%
- PV19: 16.6%
- PVB19: 27.5%

**Grid Dependency:**
- PV03: 52.4%
- PVB03: 0.9%
- PV19: 40.1%
- PVB19: 0.5%

These results demonstrate that integrating battery storage substantially improves PV utilization, more than doubling the effectiveness compared to PV-only systems. The most dramatic impact is observed in grid dependency reduction, where battery-integrated systems achieve near grid independence (less than 1% dependency) compared to 40-52% grid reliance in PV-only configurations.

Notably, shifting the photoperiod start time from 03:00 to 19:00 reduces grid dependency by approximately 12 percentage points in PV-only systems, while having minimal additional benefit in battery-integrated systems that already achieve near-zero grid dependency.

### 3.2 Temporal Power Flow Analysis

#### 3.2.1 Early Morning Photoperiod Start (03:00)

**PV-Only System (PV03)**:
The temporal power flow analysis reveals distinct patterns in the PV03 configuration. With photoperiod beginning at 03:00, there is a significant mismatch between generation and consumption periods. The PFAL requires power during early morning hours when no solar generation is available, necessitating grid imports. During peak solar generation (midday), most PFAL systems operate at minimum power as the photoperiod has concluded, resulting in substantial unused PV generation. This temporal discrepancy explains the low 13.2% PV utilization rate.

**PV-Battery System (PVB03)**:
With battery storage integration, the system behavior changes dramatically. Excess PV generation during daylight hours charges the battery to capacity (reaching 10kWh). The stored energy is then discharged during the early morning photoperiod when PV generation is unavailable. However, the battery capacity is insufficient to cover the entire night-time load, requiring minimal grid imports before sunrise. This configuration achieves 27.5% PV utilization and reduces grid dependency to just 0.9%.

#### 3.2.2 Evening Photoperiod Start (19:00)

**PV-Only System (PV19)**:
With a 19:00 photoperiod start, the PV19 configuration improves synchronization between generation and consumption. The PFAL operates at peak power during evening hours when PV generation is declining or absent, and at lower power during morning hours when PV generation is available. This improved temporal alignment results in better PV utilization (16.6%) compared to PV03, and reduced grid dependency (40.1%).

**PV-Battery System (PVB19)**:
The PVB19 configuration demonstrates optimal performance by combining battery storage with evening photoperiod start. Battery charging occurs during peak solar hours, while discharge aligns with evening PFAL operation. The temporal distribution shows effective energy management with battery discharge aligned with peak PFAL demand. This configuration maintains the high PV utilization (27.5%) similar to PVB03 while achieving the lowest grid dependency (0.5%) among all tested configurations.

### 3.3 Key Findings and Implications

Several significant findings emerge from this analysis:

1. **Battery Storage Impact**: Battery integration is the dominant factor in improving system performance, with dramatic reductions in grid dependency regardless of photoperiod timing.

2. **Photoperiod Scheduling Effects**: Shifting photoperiod to evening hours (19:00) provides moderate benefits in PV-only systems but minimal additional improvement in battery-integrated systems.

3. **Synergistic Effects**: The combination of battery storage and optimized photoperiod scheduling (PVB19) achieves the best overall performance with near-complete grid independence (0.5% dependency).

4. **Battery Sizing Considerations**: The current 10kWh battery sizing appears adequate for the modeled load profile, as evidenced by the near-zero grid dependency in PVB configurations.

These findings highlight the substantial potential for integrating renewable energy with controlled environment agriculture through strategic system design and operational scheduling.

## 4. Conclusion

This modeling study demonstrates that PVBES integration with PFALs can dramatically reduce grid dependency while maximizing renewable energy utilization. The flexibility in photoperiod scheduling unique to PFALs creates opportunities for energy optimization not available in conventional agriculture or building applications.