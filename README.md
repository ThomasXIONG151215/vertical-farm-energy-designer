# OpenCROPS: Climate-Responsive Optimizer for Plant System

An open-source framework for optimizing the integration of photovoltaic and battery energy storage systems (PVBES) with Plant Factories with Artificial Lighting (PFALs) to enhance energy efficiency, reduce grid dependency, and improve economic viability.

[中文版](#opencrops-气候响应型植物系统优化器)

## Overview

High energy consumption is a critical barrier to the widespread adoption of Plant Factories with Artificial Lighting (PFALs), despite their potential for sustainable, climate-resilient food production. OpenCROPS addresses this challenge by providing a comprehensive optimization framework that:

1. Analyzes PFAL energy consumption patterns across different components and seasons
2. Generates location-specific load profiles using validated energy models
3. Simulates photovoltaic (PV) generation using Single Diode Model (SDM)
4. Models battery energy storage (BES) behavior using power flow calculations
5. Optimizes the integration of PVBES components with PFALs across diverse climate zones
6. Evaluates both technical performance and economic viability

This framework enables significant reductions in levelized cost of electricity (LCOE) and grid dependency while maintaining economic feasibility through customized, climate-responsive system design.

## Key Features

- Generate location-specific PFAL load profiles with adjustable photoperiod schedules
- Optimize PV array size and battery capacity for different cities and operational scenarios
- Analyze impact of photoperiod scheduling on PVBES performance
- Evaluate economic metrics including LCOE and payback period
- Provide climate-responsive design guidelines for different geographical contexts
- Generate detailed visualizations of system performance and economic outcomes

## Using main.py

The main script supports multiple operational modes:

```bash
# Optimize PV-battery systems for all cities
C:/Users/Administrator/AppData/Local/Programs/Python/Python311/python.exe main.py --mode optimize

# Optimize specific cities
C:/Users/Administrator/AppData/Local/Programs/Python/Python311/python.exe main.py --mode optimize --cities shanghai dubai harbin

# Evaluate a specific configuration
C:/Users/Administrator/AppData/Local/Programs/Python/Python311/python.exe main.py --mode evaluate --pv-area 200 --battery-capacity 100 --city shanghai --start-hour 8

# Comparative mechanism analysis
C:/Users/Administrator/AppData/Local/Programs/Python/Python311/python.exe main.py --mode mechanism --pv-area 200 --battery-capacity 100 --city shanghai --start-hour1 8 --start-hour2 12

# Analyze optimization results
C:/Users/Administrator/AppData/Local/Programs/Python/Python311/python.exe main.py --mode analyze --results-file all_optimization_results.csv
```

## Creating Load Profiles with create_load_profiles.py

The tool supports creating custom load profiles for PFALs using EnergyPlus simulations:

```bash
# Generate default load profiles for all cities
C:/Users/Administrator/AppData/Local/Programs/Python/Python311/python.exe create_load_profiles.py --mode generate

# Validate a custom IDF model and create load profiles
C:/Users/Administrator/AppData/Local/Programs/Python/Python311/python.exe create_load_profiles.py --mode validate --idf "path/to/your/model.idf" --epw "path/to/weather.epw" --output_prefix "your_model"
```

### Additional usage options:

1. **Using existing template IDF files directly**:
   ```bash
   # Use an existing template from the idfs directory
   C:/Users/Administrator/AppData/Local/Programs/Python/Python311/python.exe create_load_profiles.py --mode validate --idf "idfs/light_schedule_24.idf" --epw "weather/shanghai_2024.epw" --output_prefix "template_test"
   ```

2. **Modifying existing IDF files**:
   - Copy a template file from the `idfs` directory (e.g., `light_schedule_24.idf`)
   - Modify building parameters, schedules, or other settings in the copy
   - Run the validation with your modified file:
   ```bash
   C:/Users/Administrator/AppData/Local/Programs/Python/Python311/python.exe create_load_profiles.py --mode validate --idf "path/to/your/modified_template.idf" --epw "weather/shanghai_2024.epw" --output_prefix "custom_building"
   ```

3. **Changing base IDF file for generation**:
   - Replace or modify the base IDF file used by the generator:
   - Find the base file at `idfs/light_schedule_24.idf`
   - After modifying, run the generation process again:
   ```bash
   C:/Users/Administrator/AppData/Local/Programs/Python/Python311/python.exe create_load_profiles.py --mode generate
   ```

For custom IDF validation:
1. Make sure EnergyPlus is installed on your system
2. Prepare your IDF model file with desired building parameters
3. Use an appropriate EPW weather file for your location
4. The output will include both original and converted energy profiles
5. Results will be saved in the `ep_model_validations/[output_prefix]` directory

## Processing Weather Data with weather_processor.py

Extract and process weather data for locations defined in the CITY_COORDINATES:

```bash
# Process weather data for all cities
C:/Users/Administrator/AppData/Local/Programs/Python/Python311/python.exe weather_processor.py

# To add custom locations, update the CITY_COORDINATES dictionary in weather/city_coordinates.py
```

The weather processor:
1. Downloads historical weather data for each location
2. Converts data to EPW format for EnergyPlus simulations
3. Organizes files in the weather directory structure
4. Creates both CSV and EPW files for each location

## Using analyze_results.py

The analyze_results module provides functions for visualizing and analyzing optimization results:

- `analyze_city_climate_energy()`: Creates climate and energy profiles for different cities
- `analyze_mechanism_results()`: Compares different operational schedules for the same system
- Various visualization functions for different metrics and relationships

These analysis functions provide insights into system performance across different climate zones and operational scenarios, helping to identify optimal configurations and operational strategies.

## Research Findings

OpenCROPS has been applied across five representative Chinese climate regions, demonstrating that:

1. LCOE-optimized systems achieve values of 0.037-0.042 \$/kWh with 0-3 year payback period (56-61% reduction from grid price)
2. LCOE decreases to 0.032-0.039 \$/kWh with 3-5 year payback period (59-67% reduction)
3. System requirements vary significantly by location:
   - PV arrays ranging from 30-70 m²
   - Battery capacity from 10-30 kWh
4. Photoperiod schedules that align high energy demand with peak solar hours (3:00-5:00) consistently outperform other options
5. Properly designed systems can reduce grid dependency by 59.4-76.7% under 0-3 year payback constraints and 84.1-92.8% with 3-5 year constraints

## Understanding PFAL Photoperiod and IDF Models

### Photoperiod in Plant Factories

In Plant Factories with Artificial Lighting (PFALs), photoperiod refers to the daily cycle of light and darkness that plants are exposed to. Unlike traditional agriculture, PFALs use LED lighting systems to create fully customizable photoperiods regardless of external weather or seasonal conditions. This control allows for:

1. **Optimized plant growth**: Different crops have different photoperiod requirements for optimal growth
2. **Production scheduling**: Manipulating photoperiods can accelerate or decelerate growth cycles
3. **Energy management**: Timing lighting cycles to align with energy availability or pricing

The default configuration in OpenCROPS uses a standard 16-hour photoperiod (light period) and 8-hour dark period, which is typical for many leafy green crops grown in PFALs. However, the critical variable for energy optimization is the *start time* of this photoperiod, as it determines how the energy consumption pattern aligns with PV generation and grid pricing.

### IDF Files and PFAL Modeling

The `idfs` directory contains Energy Plus Input Data Files (IDF) that model the exemplary PFAL described in the manuscript. These files translate the physical and operational parameters of the real PFAL into a format that Energy Plus can simulate:

- **light_schedule_XX.idf**: Each file represents a different photoperiod start time (XX = hour 00-23)
- **LIGHT_SCHEDULE_XX_XX.idf**: Additional variants with specific start and end timing
- **Template.idf**: Base template for the PFAL structure

The IDF files include specifications for:

1. **Building envelope**: Dimensions, materials, thermal properties matching the exemplary PFAL
2. **HVAC systems**: Air conditioning units with performance characteristics derived from real measurements
3. **Lighting systems**: LED fixtures with power ratings and heat dissipation properties
4. **Equipment loads**: Other energy-consuming components like fans and pumps
5. **Schedules**: Operation timing for all systems, especially lighting schedules

When running a simulation, these IDF files are combined with location-specific weather data to generate energy consumption profiles that account for both internal loads (lighting, equipment) and external factors (temperature, solar radiation).

### Exemplary PFAL Characteristics

The IDF models are based on measurements from an operational PFAL facility that was monitored throughout a full year. Key characteristics include:

- **Component-level energy monitoring**: LED lighting, AC units, fresh air units (FAU), and fan filter units (FFU)
- **Seasonal variation**: AC energy consumption varies by >140% between seasons while lighting remains stable
- **COP measurements**: The air conditioning efficiency shows seasonal variation (2.57-3.94)
- **LED lighting patterns**: Consistent energy consumption (10.2-12.7 kWh/day) with periodic adjustments

These measurements were used to validate the EnergyPlus models, ensuring accurate representation of energy consumption patterns across different climate conditions and operational schedules.

## Directory Structure

```
OpenCROPS/
  ├── main.py                 # Main entry point for the tool
  ├── analyze_results.py      # Results analysis and visualization
  ├── create_load_profiles.py # Load profile generation
  ├── weather_processor.py    # Weather data extraction and processing
  ├── src/                    # Core modules
  │   ├── system.py           # Energy system simulation
  │   ├── optimizer.py        # Optimization algorithms
  │   ├── visualization.py    # Visualization functionality
  │   └── utils.py            # Utility functions
  ├── weather/                # Weather data processing
  │   ├── city_coordinates.py # City location data
  │   ├── weather_extractor.py# Weather data retrieval
  │   └── epw_converter.py    # Weather file conversion
  ├── test_case/              # Test case data
  └── results/                # Generated results and visualizations
```

-----

# OpenCROPS: 气候响应型植物系统优化器

一个开源框架，用于优化光伏和电池储能系统(PVBES)与人工光植物工厂(PFALs)的集成，以提高能源效率，减少电网依赖，并改善经济可行性。

## 概述

高能耗是人工光植物工厂(PFALs)广泛应用的关键障碍，尽管它们在可持续、气候适应型食品生产方面具有潜力。OpenCROPS通过提供全面的优化框架来解决这一挑战：

1. 分析PFAL在不同组件和季节的能源消耗模式
2. 使用经验证的能源模型生成特定位置的负荷曲线
3. 使用单二极管模型(SDM)模拟光伏(PV)发电
4. 使用功率流计算模拟电池储能(BES)行为
5. 在不同气候区域优化PVBES组件与PFALs的集成
6. 评估技术性能和经济可行性

该框架通过定制的、气候响应型系统设计，实现了平准化电力成本(LCOE)和电网依赖度的显著降低，同时保持经济可行性。

## 主要功能

- 生成特定位置的PFAL负荷曲线，可调整光周期计划
- 为不同城市和运行方案优化光伏阵列尺寸和电池容量
- 分析光周期安排对PVBES性能的影响
- 评估包括LCOE和投资回收期在内的经济指标
- 为不同地理环境提供气候响应型设计指南
- 生成系统性能和经济效益的详细可视化图表

## 使用 main.py

主脚本支持多种操作模式：

```bash
# 为所有城市优化光伏-电池系统
C:/Users/Administrator/AppData/Local/Programs/Python/Python311/python.exe main.py --mode optimize

# 优化特定城市
C:/Users/Administrator/AppData/Local/Programs/Python/Python311/python.exe main.py --mode optimize --cities shanghai dubai harbin

# 评估特定配置
C:/Users/Administrator/AppData/Local/Programs/Python/Python311/python.exe main.py --mode evaluate --pv-area 200 --battery-capacity 100 --city shanghai --start-hour 8

# 比较机制分析
C:/Users/Administrator/AppData/Local/Programs/Python/Python311/python.exe main.py --mode mechanism --pv-area 200 --battery-capacity 100 --city shanghai --start-hour1 8 --start-hour2 12

# 分析优化结果
C:/Users/Administrator/AppData/Local/Programs/Python/Python311/python.exe main.py --mode analyze --results-file all_optimization_results.csv
```

## 使用 create_load_profiles.py 创建负荷曲线

该工具支持使用EnergyPlus模拟为PFALs创建自定义负荷曲线：

```bash
# 为所有城市生成默认负荷曲线
C:/Users/Administrator/AppData/Local/Programs/Python/Python311/python.exe create_load_profiles.py --mode generate

# 验证自定义IDF模型并创建负荷曲线
C:/Users/Administrator/AppData/Local/Programs/Python/Python311/python.exe create_load_profiles.py --mode validate --idf "path/to/your/model.idf" --epw "path/to/weather.epw" --output_prefix "your_model"
```

### 附加使用选项：

1. **直接使用现有模板IDF文件**：
   ```bash
   # 使用idfs目录中的现有模板
   C:/Users/Administrator/AppData/Local/Programs/Python/Python311/python.exe create_load_profiles.py --mode validate --idf "idfs/light_schedule_24.idf" --epw "weather/shanghai_2024.epw" --output_prefix "template_test"
   ```

2. **修改现有IDF文件**：
   - 从`idfs`目录复制模板文件（例如，`light_schedule_24.idf`）
   - 在副本中修改建筑参数、时间表或其他设置
   - 使用修改后的文件运行验证：
   ```bash
   C:/Users/Administrator/AppData/Local/Programs/Python/Python311/python.exe create_load_profiles.py --mode validate --idf "path/to/your/modified_template.idf" --epw "weather/shanghai_2024.epw" --output_prefix "custom_building"
   ```

3. **更改用于生成的基本IDF文件**：
   - 替换或修改生成器使用的基本IDF文件：
   - 基本文件位于`idfs/light_schedule_24.idf`
   - 修改后，再次运行生成过程：
   ```bash
   C:/Users/Administrator/AppData/Local/Programs/Python/Python311/python.exe create_load_profiles.py --mode generate
   ```

对于自定义IDF验证：
1. 确保系统上已安装EnergyPlus
2. 准备包含所需建筑参数的IDF模型文件
3. 为您的位置使用适当的EPW天气文件
4. 输出将包括原始和转换后的能耗曲线
5. 结果将保存在`ep_model_validations/[output_prefix]`目录中

## 使用 weather_processor.py 处理天气数据

为CITY_COORDINATES中定义的位置提取和处理天气数据：

```bash
# 处理所有城市的天气数据
C:/Users/Administrator/AppData/Local/Programs/Python/Python311/python.exe weather_processor.py

# 要添加自定义位置，请更新weather/city_coordinates.py中的CITY_COORDINATES字典
```

天气处理器：
1. 下载每个位置的历史天气数据
2. 将数据转换为EPW格式用于EnergyPlus模拟
3. 在天气目录结构中组织文件
4. 为每个位置创建CSV和EPW文件

## 使用 analyze_results.py

analyze_results模块提供了可视化和分析优化结果的功能：

- `analyze_city_climate_energy()`: 创建不同城市的气候和能源分析图表
- `analyze_mechanism_results()`: 比较同一系统在不同运行时间表下的性能
- 各种可视化功能，用于展示不同指标和关系

这些分析功能提供了系统在不同气候区域和运行方案下的性能洞察，帮助识别最佳配置和运行策略。

## 研究发现

OpenCROPS已在中国五个具有代表性的气候区域应用，结果表明：

1. LCOE优化系统在0-3年回收期内达到0.037-0.042 \$/kWh（较电网价格降低56-61%）
2. 在3-5年回收期内，LCOE降至0.032-0.039 \$/kWh（较电网价格降低59-67%）
3. 系统需求因地点而异：
   - 光伏阵列面积从30-70 m²不等
   - 电池容量从10-30 kWh不等
4. 将高能耗与峰值太阳能时段（3:00-5:00）对齐的光周期安排始终优于其他选项
5. 设计合理的系统可在0-3年回收期约束下减少59.4-76.7%的电网依赖，在3-5年约束下减少84.1-92.8%

## Understanding PFAL Photoperiod and IDF Models

### Photoperiod in Plant Factories

In Plant Factories with Artificial Lighting (PFALs), photoperiod refers to the daily cycle of light and darkness that plants are exposed to. Unlike traditional agriculture, PFALs use LED lighting systems to create fully customizable photoperiods regardless of external weather or seasonal conditions. This control allows for:

1. **Optimized plant growth**: Different crops have different photoperiod requirements for optimal growth
2. **Production scheduling**: Manipulating photoperiods can accelerate or decelerate growth cycles
3. **Energy management**: Timing lighting cycles to align with energy availability or pricing

The default configuration in OpenCROPS uses a standard 16-hour photoperiod (light period) and 8-hour dark period, which is typical for many leafy green crops grown in PFALs. However, the critical variable for energy optimization is the *start time* of this photoperiod, as it determines how the energy consumption pattern aligns with PV generation and grid pricing.

### IDF Files and PFAL Modeling

The `idfs` directory contains Energy Plus Input Data Files (IDF) that model the exemplary PFAL described in the manuscript. These files translate the physical and operational parameters of the real PFAL into a format that Energy Plus can simulate:

- **light_schedule_XX.idf**: Each file represents a different photoperiod start time (XX = hour 00-23)
- **LIGHT_SCHEDULE_XX_XX.idf**: Additional variants with specific start and end timing
- **Template.idf**: Base template for the PFAL structure

The IDF files include specifications for:

1. **Building envelope**: Dimensions, materials, thermal properties matching the exemplary PFAL
2. **HVAC systems**: Air conditioning units with performance characteristics derived from real measurements
3. **Lighting systems**: LED fixtures with power ratings and heat dissipation properties
4. **Equipment loads**: Other energy-consuming components like fans and pumps
5. **Schedules**: Operation timing for all systems, especially lighting schedules

When running a simulation, these IDF files are combined with location-specific weather data to generate energy consumption profiles that account for both internal loads (lighting, equipment) and external factors (temperature, solar radiation).

### Exemplary PFAL Characteristics

The IDF models are based on measurements from an operational PFAL facility that was monitored throughout a full year. Key characteristics include:

- **Component-level energy monitoring**: LED lighting, AC units, fresh air units (FAU), and fan filter units (FFU)
- **Seasonal variation**: AC energy consumption varies by >140% between seasons while lighting remains stable
- **COP measurements**: The air conditioning efficiency shows seasonal variation (2.57-3.94)
- **LED lighting patterns**: Consistent energy consumption (10.2-12.7 kWh/day) with periodic adjustments

These measurements were used to validate the EnergyPlus models, ensuring accurate representation of energy consumption patterns across different climate conditions and operational schedules.

## 目录结构

```
OpenCROPS/
  ├── main.py                 # 工具的主入口点
  ├── analyze_results.py      # 结果分析和可视化
  ├── create_load_profiles.py # 负荷曲线生成
  ├── weather_processor.py    # 天气数据提取和处理
  ├── src/                    # 核心模块
  │   ├── system.py           # 能源系统模拟
  │   ├── optimizer.py        # 优化算法
  │   ├── visualization.py    # 可视化功能
  │   └── utils.py            # 实用函数
  ├── weather/                # 天气数据处理
  │   ├── city_coordinates.py # 城市位置数据
  │   ├── weather_extractor.py# 天气数据获取
  │   └── epw_converter.py    # 天气文件转换
  ├── test_case/              # 测试案例数据
  └── results/                # 生成的结果和可视化图表
``` 
