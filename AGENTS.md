# Vertical Farm Energy Designer (VFED) Agent Guidelines

## Project Overview

Vertical Farm Energy Designer (VFED) is a framework for optimizing PV-Battery integration with Plant Factories with Artificial Lighting (PFALs).

**Key Components:**
- `src/idf_builder.py` - EnergyPlus IDF file generator
- `src/cli.py` - Typer CLI interface
- `main.py` - Legacy CLI entry point
- `src/eso_to_csv.py` - EnergyPlus output parser

## Architecture

```
VerticalFarmEnergyDesigner/
├── src/
│   ├── idf_builder.py     # IDF building (Zone, Lights, Equipment, Schedule)
│   ├── cli.py              # CLI interface
│   ├── system.py           # Energy system simulation
│   ├── optimizer.py        # Genetic algorithm optimization
│   └── eso_to_csv.py       # ESO output parser
├── weather/               # Weather data (EPW files)
├── idfs/                   # IDF templates
└── tests/                 # Test suite
```

## EnergyPlus IDF Building

### Core IDFBuilder Usage

```python
from src.idf_builder import IDFBuilder

idf = IDFBuilder()
idf.set_building('PFAL', floor_area=100, num_zones=2)
idf.set_location('Shanghai', latitude=31.2, longitude=121.5, timezone=8, elevation=4.0)
idf.set_ground_temperatures([20.4, 20.4, 20.4, 20.4, 21.5, 22.7, 22.9, 23.0, 23.0, 21.9, 20.7, 20.5])

# Add zones with rectangular geometry
idf.add_zone(name='UNZ_0', x=0, y=0, z=0, floor_area=13.51, length=5.8, width=2.33, ceiling_height=2.9)

# Daily schedules (24 values for 24 hours)
idf.add_daily_schedule('LightDaily', 'Fraction', [0.0]*7 + [1.0]*14 + [0.0]*3)
idf.add_daily_schedule('EquipDaily', 'Fraction', [0.75]*7 + [1.0]*17)

# Add loads with schedules
idf.add_lights(zone_name='UNZ_0', power_density=350, schedule_name='LightDaily')
idf.add_electric_equipment(zone_name='UNZ_0', design_level=500, schedule_name='EquipDaily')
idf.add_ventilation(zone_name='UNZ_0', air_changes_per_hour=0.5, schedule_name='EquipDaily')
idf.add_thermostat(zone_name='UNZ_0', heating_setpoint=18, cooling_setpoint=25)

idf_text = idf.build()
```

### Key IDFBuilder Methods

| Method | Description |
|--------|-------------|
| `set_building(name, floor_area, num_zones)` | Set building parameters |
| `set_location(name, lat, lon, tz, elev)` | Set geographic location |
| `set_ground_temperatures([12 monthly temps])` | Set ground temperatures |
| `add_zone(name, x, y, z, floor_area, length, width, ceiling_height)` | Add zone with rectangular geometry |
| `add_daily_schedule(name, type, [24 hourly values])` | Add daily repeating schedule |
| `add_weekly_schedule(name, type, monday, tuesday, ...)` | Add weekly schedule |
| `add_lights(zone_name, power_density, schedule_name)` | Add lighting |
| `add_electric_equipment(zone_name, design_level, schedule_name)` | Add equipment |
| `add_ventilation(zone_name, air_changes_per_hour, schedule_name)` | Add ventilation |
| `add_thermostat(zone_name, heating, cooling)` | Add thermostat |
| `build()` | Generate IDF string |

### Schedule:Compact Format

```idf
Schedule:Compact,
    LightDaily,                !- Name
    Fraction,       !- Schedule Type Limits Name
    Through: 12/31,
    For: AllDays,
    Until: 01:00, 0.0,
    Until: 02:00, 0.0,
    ...
    Until: 24:00, 0.0;
```

**Important:** Use `Through: 12/31` (not `1/1`) for daily repeating schedules.

## CLI Commands

```bash
# IDF generation
vfed idf build -n Test -fa 100 -z 2 -o output.idf
vfed idf run -i output.idf -w weather.epw -o output/
vfed idf extract-loads -e output/eplusout.eso -o loads.csv

# Optimization
vf-ed optimize --cities shanghai harbin
vf-ed evaluate --pv-area 200 --battery-capacity 100 --city shanghai
```

## EnergyPlus Integration

**EnergyPlus Location:** `C:/EnergyPlusV23-1-0/`

**IDD File:** `C:/EnergyPlusV23-1-0/IDD_Version23_1_0.idd`

**ESO Output Variables:**
- `Zone Lights Electricity Energy [J]` - Lighting energy
- `Zone Electric Equipment Electricity Energy [J]` - Equipment energy
- `Zone Ideal Loads Zone Total Heating Energy [J]` - HVAC heating
- `Zone Ideal Loads Zone Total Cooling Energy [J]` - HVAC cooling

**Conversion:** J → kWh = ÷ 3,600,000

## Common Issues

1. **Schedule missing days error**: Use `Through: 12/31` not `Through: 1/1`
2. **Zone not found error**: Ensure lights/equipment use correct zone names
3. **Ground temperature warning**: Add `Site:GroundTemperature:BuildingSurface`
4. **ExpandObjects error**: Only run when IDF contains `HVACTemplate:` objects

## Testing

```bash
# Run EnergyPlus
"/c/EnergyPlusV23-1-0/energyplus.exe" -i "/c/EnergyPlusV23-1-0/IDD_Version23_1_0.idd" -w weather.epw -d output test.idf

# Parse ESO
python -c "from src.eso_to_csv import parse_eso; data = parse_eso('output/eplusout.eso')"
```

## Weather Files

Weather files (EPW) are in `weather/` directory:
- `shanghai_2024.epw`
- `beijing_2024.epw`
- `harbin_2024.epw`
- etc.

## Alternative: eppy-based IDF Modification

For modifying existing IDF files programmatically, `create_load_profiles.py` in the root directory uses **eppy**:

```python
from eppy import modeleditor
from eppy.modeleditor import IDF
from eppy.runner.run_functions import run

# Initialize IDF
iddfile = "path/to/Energy+.idd"
fname = "path/to/Template.idf"
 IDF(iddfile)
idf = IDF(fname)

# Modify schedule
def create_light_schedule(idf, schedule_name, start_hour, end_hour):
    n_lights = None
    for schedule in idf.idfobjects["Schedule:Day:Hourly"]:
        if schedule.Name == "N_Lights":
            n_lights = schedule
            break
    # Create hourly values (0 or 1)
    schedule_values = [0] * 24
    for hour in range(start_hour, end_hour):
        schedule_values[hour] = 1
    # Update schedule
    for hour in range(24):
        setattr(n_lights, f"Hour_{hour+1}", schedule_values[hour])
    return n_lights

# Run simulation
options = {
    'ep_version': '23.1',
    'output_prefix': 'Template',
    'output_suffix': 'C',
    'output_directory': output_dir,
    'weather': epwfile
}
run(options, idf)
```

## Validation Data

NOE building validation data: `results/validate_ep/NOE.csv`

- Time range: 2023/8/21 - 2023/9/6 (16 days, 384 records)
- Columns: time, Measurement, Prediction, AC_Electricity_kWh
