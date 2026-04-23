"""
OpenCROPS CLI - Command Line Interface for PV-Battery System Optimization
"""
import sys
from pathlib import Path

# Add parent directory to path for weather module access
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import typer
from typing import Optional, List
import logging

from src import __version__

app = typer.Typer(
    name="vfed",
    help="vertical-farm-energy-designer (vfed) - Climate-Responsive Photovoltaic-Battery System Optimizer",
    add_completion=False,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


VALID_CITIES = [
    "shanghai", "beijing", "newyork", "hohhot", "urumqi",
    "dubai", "paris", "sydney", "saopaulo", "harbin",
    "chongqing", "hangzhou", "tianjin", "zhengzhou", "hainan",
    "jinan", "lasa", "haikou",
]

VALID_OPTIMIZE_CITIES = [
    "shanghai", "dubai", "harbin", "haikou", "lasa", "urumqi",
    "jinan", "zhengzhou", "tianjin", "hangzhou", "chongqing",
    "beijing", "newyork", "paris", "saopaulo", "hohhot",
]


@app.command()
def version():
    """Show version / 显示版本"""
    typer.echo(f"vertical-farm-energy-designer (OpenCROPS) v{__version__}")


@app.command()
def optimize(
    cities: Optional[List[str]] = typer.Option(
        None,
        "--cities",
        "-c",
        help="Cities to optimize (default: all cities) / 要优化的城市（默认：全部）",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose output / 启用详细输出"),
):
    """
    Optimize PV-Battery system for all or selected cities.

    优化所有或选定城市的 PV-Battery 系统。
    """
    from main import process_city, RESULTS_DF_PATH, save_aggregated_performance_data
    from weather.city_coordinates import get_city_coordinates
    from pathlib import Path

    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Get available cities dynamically
    available_cities = list(get_city_coordinates().keys())

    base_dir = Path("test_case")
    cities_to_process = cities if cities else available_cities

    logger.info(f"Starting optimization for cities: {', '.join(cities_to_process)}")

    for city_key in cities_to_process:
        if city_key not in available_cities:
            typer.echo(f"Error: Unknown city '{city_key}'. Available cities: {', '.join(available_cities)}", err=True)
            raise typer.Exit(code=1)
        logger.info(f"\nProcessing city: {city_key}")
        try:
            process_city(city_key, base_dir)
        except Exception as e:
            logger.error(f"Error processing city {city_key}: {e}")

    typer.echo("Optimization complete!")


@app.command()
def evaluate(
    pv_area: float = typer.Option(
        ...,
        "--pv-area",
        "-p",
        help="PV area in m² / 光伏面积（平方米）",
    ),
    battery_capacity: float = typer.Option(
        ...,
        "--battery-capacity",
        "-b",
        help="Battery capacity in kWh / 电池容量（千瓦时）",
    ),
    city: str = typer.Option(
        ...,
        "--city",
        "-c",
        help="City key / 城市键值",
    ),
    start_hour: int = typer.Option(
        ...,
        "--start-hour",
        "-s",
        help="Start hour of photoperiod (0-23) / 光照期开始小时（0-23）",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose output / 启用详细输出"),
):
    """
    Evaluate a single PV-Battery configuration.

    评估单个 PV-Battery 配置。
    """
    from main import evaluate_single_config
    from pathlib import Path
    import pandas as pd
    from weather.city_coordinates import get_city_coordinates

    base_dir = Path("test_case")

    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    available_cities = list(get_city_coordinates().keys())
    if city not in available_cities:
        typer.echo(f"Error: Unknown city '{city}'. Available cities: {', '.join(available_cities)}", err=True)
        raise typer.Exit(code=1)

    if not (0 <= start_hour <= 23):
        typer.echo("Error: start-hour must be between 0 and 23", err=True)
        raise typer.Exit(code=1)

    base_dir = Path("test_case")
    city_dir = base_dir / city
    dirs = {
        "output": city_dir / "output",
        "results": city_dir / "results",
        "weather": city_dir / "weather",
    }

    for dir_path in dirs.values():
        dir_path.mkdir(parents=True, exist_ok=True)

    weather_csv = dirs["weather"] / f"{city}_2024.csv"
    if not weather_csv.exists():
        typer.echo(f"Error: Weather data not found for {city}. Run 'vfed optimize' first.", err=True)
        raise typer.Exit(code=1)

    weather_data = pd.read_csv(weather_csv)

    schedule_pattern = f"annual_energy_schedule_{start_hour:02d}_*.csv"
    schedule_files = list(dirs["output"].glob(schedule_pattern))
    if not schedule_files:
        typer.echo(f"Error: No schedule file found for start hour {start_hour:02d}", err=True)
        raise typer.Exit(code=1)

    schedule_file = schedule_files[0]
    logger.info(f"Using schedule file: {schedule_file.name}")

    result = evaluate_single_config(
        pv_area=pv_area,
        battery_capacity=battery_capacity,
        schedule_file=schedule_file,
        weather_data=weather_data,
        results_dir=dirs["results"],
        city_key=city,
    )

    if not result["success"]:
        typer.echo(f"Evaluation failed: {result.get('error', 'Unknown error')}", err=True)
        raise typer.Exit(code=1)

    typer.echo("Evaluation complete!")


@app.command()
def calibrate(
    city: str = typer.Option(
        ...,
        "--city",
        "-c",
        help="City key / 城市键值",
    ),
    pv_max: float = typer.Option(
        500.0,
        "--pv-max",
        help="Maximum PV area in m² / 最大光伏面积（平方米）",
    ),
    battery_max: float = typer.Option(
        500.0,
        "--battery-max",
        help="Maximum battery capacity in kWh / 最大电池容量（千瓦时）",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose output / 启用详细输出"),
):
    """
    Calibrate optimization step sizes for a city.

    校准城市的优化步长。
    """
    from src.calibrator import StepSizeCalibrator
    import json

    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    from weather.city_coordinates import get_city_coordinates
    available_cities = list(get_city_coordinates().keys())
    if city not in available_cities:
        typer.echo(f"Error: Unknown city '{city}'. Available cities: {', '.join(available_cities)}", err=True)
        raise typer.Exit(code=1)

    calibrator = StepSizeCalibrator(
        reference_city=city,
        pv_max=pv_max,
        battery_max=battery_max,
        step_sizes=[0.5, 1.0, 5.0, 10.0, 15.0, 20.0, 30, 50],
    )

    optimal_steps = calibrator.run()

    output_dir = Path("calibration_results")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"optimal_steps_{city}.json"

    with open(output_file, "w") as f:
        json.dump(optimal_steps, f, indent=4)

    typer.echo(f"Calibration complete! Results saved to {output_file}")


@app.command()
def analyze(
    results_file: Path = typer.Option(
        ...,
        "--results-file",
        "-r",
        help="Path to optimization results CSV / 优化结果 CSV 文件路径",
    ),
    output_dir: Path = typer.Option(
        Path("results"),
        "--output-dir",
        "-o",
        help="Output directory for analysis results / 分析结果输出目录",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose output / 启用详细输出"),
):
    """
    Analyze optimization results.

    分析优化结果。
    """
    from analyze_results import analyze_city_climate_energy

    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    if not results_file.exists():
        typer.echo(f"Error: Results file not found: {results_file}", err=True)
        raise typer.Exit(code=1)

    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Starting analysis...")
    analyze_city_climate_energy(output_dir=output_dir)
    typer.echo(f"Analysis complete! Results saved to {output_dir}")


@app.command()
def mechanism(
    pv_area: float = typer.Option(
        ...,
        "--pv-area",
        "-p",
        help="PV area in m² / 光伏面积（平方米）",
    ),
    battery_capacity: float = typer.Option(
        ...,
        "--battery-capacity",
        "-b",
        help="Battery capacity in kWh / 电池容量（千瓦时）",
    ),
    city: str = typer.Option(
        ...,
        "--city",
        "-c",
        help="City key / 城市键值",
    ),
    start_hour1: int = typer.Option(
        ...,
        "--start-hour1",
        help="First start hour (0-23) / 第一个开始小时（0-23）",
    ),
    start_hour2: int = typer.Option(
        ...,
        "--start-hour2",
        help="Second start hour (0-23) / 第二个开始小时（0-23）",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose output / 启用详细输出"),
):
    """
    Comparative mechanism analysis with two different start hours.

    使用两个不同开始小时进行对比机制分析。
    """
    from main import evaluate_mechanism_configs
    from pathlib import Path

    base_dir = Path("test_case")

    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    from weather.city_coordinates import get_city_coordinates
    available_cities = list(get_city_coordinates().keys())
    if city not in available_cities:
        typer.echo(f"Error: Unknown city '{city}'. Available cities: {', '.join(available_cities)}", err=True)
        raise typer.Exit(code=1)

    if not (0 <= start_hour1 <= 23):
        typer.echo("Error: start-hour1 must be between 0 and 23", err=True)
        raise typer.Exit(code=1)

    if not (0 <= start_hour2 <= 23):
        typer.echo("Error: start-hour2 must be between 0 and 23", err=True)
        raise typer.Exit(code=1)

    base_dir = Path("test_case")

    evaluate_mechanism_configs(
        pv_area=pv_area,
        battery_capacity=battery_capacity,
        start_hour1=start_hour1,
        start_hour2=start_hour2,
        city_key=city,
        base_dir=base_dir,
    )

    typer.echo("Mechanism analysis complete!")


# City subcommand group
city_app = typer.Typer(help="City management / 城市管理")
app.add_typer(city_app, name="city", help="City management commands / 城市管理命令")


@city_app.command("list")
def city_list():
    """
    List all available cities.

    列出所有可用城市。
    """
    from weather.city_coordinates import list_cities

    df = list_cities()
    typer.echo(f"\nAvailable cities ({len(df)} total):")
    typer.echo("-" * 60)
    for _, row in df.iterrows():
        typer.echo(f"  {row['city_key']:12} | {row['name']:20} | ({row['latitude']:+.4f}, {row['longitude']:+.4f}) | {row['timezone']}")
    typer.echo("-" * 60)


@city_app.command("search")
def city_search(
    query: str = typer.Argument(..., help="City name to search / 要搜索的城市名"),
    limit: int = typer.Option(5, "--limit", "-n", help="Maximum number of results / 最大结果数"),
):
    """
    Search for a city using Nominatim geocoding service.

    使用 Nominatim 地理编码服务搜索城市。
    """
    from geopy.geocoders import Nominatim
    from geopy.exc import GeocoderTimedOut, GeocoderServiceError
    import time

    typer.echo(f"Searching for: {query}")

    geolocator = Nominatim(user_agent="vfed-city-search", timeout=10)

    try:
        # Rate limit: 1 request per second
        time.sleep(1.1)

        locations = geolocator.geocode(query, exactly_one=False, limit=limit, addressdetails=True)

        if not locations:
            typer.echo(f"No results found for '{query}'", err=True)
            raise typer.Exit(code=1)

        typer.echo(f"\nFound {len(locations)} result(s):")
        typer.echo("-" * 60)

        for i, loc in enumerate(locations, 1):
            address = loc.raw.get('address', {})
            city_name = address.get('city', address.get('town', address.get('village', address.get('municipality', 'Unknown'))))
            country = address.get('country', 'Unknown')
            display_name = loc.address if hasattr(loc, 'address') else str(loc)

            typer.echo(f"\n{i}. {display_name}")
            typer.echo(f"   Coordinates: ({loc.latitude:.4f}, {loc.longitude:.4f})")
            typer.echo(f"   City: {city_name}, Country: {country}")

        typer.echo("-" * 60)

    except GeocoderTimedOut:
        typer.echo("Error: Geocoding service timed out. Please try again.", err=True)
        raise typer.Exit(code=1)
    except GeocoderServiceError as e:
        typer.echo(f"Error: Geocoding service error: {e}", err=True)
        raise typer.Exit(code=1)


@city_app.command("add")
def city_add(
    name: str = typer.Option(..., "--name", "-n", help="City key (unique identifier) / 城市键值（唯一标识符）"),
    lat: float = typer.Option(..., "--lat", "-lat", help="Latitude (-90 to 90) / 纬度（-90 到 90）"),
    lon: float = typer.Option(..., "--lon", "-lon", help="Longitude (-180 to 180) / 经度（-180 到 180）"),
    display_name: Optional[str] = typer.Option(None, "--display-name", "-dn", help="Display name / 显示名称"),
    timezone: str = typer.Option("Asia/Singapore", "--timezone", "-tz", help="IANA timezone / IANA 时区"),
):
    """
    Add a new city to the database.

    添加新城市到数据库。
    """
    from weather.city_coordinates import add_city

    # Validate coordinates
    if not -90 <= lat <= 90:
        typer.echo(f"Error: Latitude must be between -90 and 90, got {lat}", err=True)
        raise typer.Exit(code=1)

    if not -180 <= lon <= 180:
        typer.echo(f"Error: Longitude must be between -180 and 180, got {lon}", err=True)
        raise typer.Exit(code=1)

    # Use key as display name if not provided
    if display_name is None:
        display_name = name.capitalize()

    try:
        add_city(
            city_key=name.lower().replace(" ", "_"),
            name=display_name,
            latitude=lat,
            longitude=lon,
            timezone=timezone
        )
        typer.echo(f"Successfully added city: {name}")
        typer.echo(f"  Key: {name.lower().replace(' ', '_')}")
        typer.echo(f"  Display name: {display_name}")
        typer.echo(f"  Coordinates: ({lat:.4f}, {lon:.4f})")
        typer.echo(f"  Timezone: {timezone}")

    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1)
    except Exception as e:
        typer.echo(f"Error adding city: {e}", err=True)
        raise typer.Exit(code=1)


idf_app = typer.Typer(help="IDF file generation and simulation / IDF 文件生成与模拟")
app.add_typer(idf_app, name="idf", help="IDF file management commands / IDF 文件管理命令")


@idf_app.command("build")
def idf_build(
    name: str = typer.Option("PFAL", "--name", "-n", help="Building name / 建筑名称"),
    output: Path = typer.Option(..., "--output", "-o", help="Output IDF file path / 输出 IDF 文件路径"),
    floor_area: float = typer.Option(100.0, "--floor-area", "-fa", help="Floor area in m2 / 建筑面积（平方米）"),
    num_zones: int = typer.Option(1, "--zones", "-z", help="Number of growing zones (racks) / 种植区数量"),
    lighting_power: float = typer.Option(350.0, "--lighting-power", "-lp", help="Lighting power density W/m2 / 照明功率密度（瓦/平方米）"),
    ventilation_rate: float = typer.Option(0.3, "--ventilation", "-v", help="Ventilation rate (air changes/hr) / 换气次数"),
    heating: float = typer.Option(20.0, "--heating", "-heat", help="Heating setpoint C / 供暖设定温度（摄氏度）"),
    cooling: float = typer.Option(25.0, "--cooling", "-cool", help="Cooling setpoint C / 制冷设定温度（摄氏度）"),
    equipment_power: float = typer.Option(500.0, "--equipment", "-ep", help="Equipment heat gain W / 设备热收益（瓦）"),
):
    """
    Build a PFAL building IDF from scratch (no external files required).

    从零开始构建 PFAL 建筑 IDF（无需外部文件）。
    All schedules are inline, no ventilationSchedule.txt dependency.
    """
    from src.idf_builder import IDFBuilder

    try:
        typer.echo(f"Building IDF for: {name}")

        idf = IDFBuilder()
        idf.set_building(name, floor_area=floor_area, num_zones=num_zones)

        # Add zones
        for i in range(num_zones):
            idf.add_zone(
                name=f"Zone_{i:02d}",
                x=0, y=0, z=i * 2.5,  # stacked vertically
                multiplier=1,
                ceiling_height=2.5,
                floor_area=floor_area / num_zones
            )

        # Add lighting for each zone
        for i in range(num_zones):
            idf.add_lights(
                zone_idx=i,
                power_density=lighting_power,
                zone_name=f"Zone_{i:02d}",
                schedule_name="LightSchedule"
            )

        # Add equipment heat gain for each zone
        for i in range(num_zones):
            idf.add_electric_equipment(
                zone_idx=i,
                design_level=equipment_power,
                zone_name=f"Zone_{i:02d}",
                schedule_name="EquipSchedule"
            )

        # Add ventilation for each zone (air changes per hour)
        for i in range(num_zones):
            idf.add_ventilation(
                zone_idx=i,
                air_changes_per_hour=ventilation_rate,
                zone_name=f"Zone_{i:02d}",
                schedule_name="VentilationSchedule"
            )

        # Add thermostat for each zone
        for i in range(num_zones):
            idf.add_thermostat(
                zone_idx=i,
                heating_setpoint=heating,
                cooling_setpoint=cooling,
                zone_name=f"Zone_{i:02d}"
            )

        # Write IDF file
        output.parent.mkdir(parents=True, exist_ok=True)
        idf_content = idf.build()
        output.write_text(idf_content, encoding='utf-8')

        typer.echo(f"Successfully built IDF: {output}")
        typer.echo(f"  Building: {name}")
        typer.echo(f"  Floor area: {floor_area} m2")
        typer.echo(f"  Zones: {num_zones}")
        typer.echo(f"  Lighting power: {lighting_power} W/m2")
        typer.echo(f"  Ventilation rate: {ventilation_rate} ACH")
        typer.echo(f"  Heating: {heating} C / Cooling: {cooling} C")
        typer.echo(f"  Equipment: {equipment_power} W/zone")
        typer.echo("")
        typer.echo("No external file dependencies - all schedules are inline!")

    except Exception as e:
        typer.echo(f"Error building IDF: {e}", err=True)
        raise typer.Exit(code=1)


@idf_app.command("run")
def idf_run(
    idf_file: Path = typer.Option(..., "--idf", "-i", help="Input IDF file / 输入 IDF 文件"),
    weather: Path = typer.Option(..., "--weather", "-w", help="EPW weather file / EPW 气象文件"),
    output_dir: Path = typer.Option(Path("output"), "--output-dir", "-o", help="Output directory / 输出目录"),
):
    """
    Run EnergyPlus simulation with an IDF file.

    使用 IDF 文件运行 EnergyPlus 模拟。
    """
    import subprocess

    energyplus_exe = Path("C:/EnergyPlusV23-1-0/energyplus.exe")
    expand_objects_exe = Path("C:/EnergyPlusV23-1-0/ExpandObjects.exe")

    if not energyplus_exe.exists():
        typer.echo(f"Error: EnergyPlus not found at {energyplus_exe}", err=True)
        raise typer.Exit(code=1)

    if not idf_file.exists():
        typer.echo(f"Error: IDF file not found: {idf_file}", err=True)
        raise typer.Exit(code=1)

    if not weather.exists():
        typer.echo(f"Error: Weather file not found: {weather}", err=True)
        raise typer.Exit(code=1)

    output_dir.mkdir(parents=True, exist_ok=True)

    typer.echo(f"Running EnergyPlus simulation...")
    typer.echo(f"  IDF: {idf_file}")
    typer.echo(f"  Weather: {weather}")
    typer.echo(f"  Output: {output_dir}")

    try:
        # Check if IDF contains HVACTemplate objects that need ExpandObjects
        idf_content = idf_file.read_text(encoding='utf-8')
        needs_expand = 'HVACTemplate:' in idf_content

        if needs_expand and expand_objects_exe.exists():
            expanded_idf = output_dir / idf_file.name
            typer.echo("Running ExpandObjects to process HVACTemplate objects...")

            expand_result = subprocess.run(
                [
                    str(expand_objects_exe),
                    "-i", str(idf_file),
                    "-o", str(expanded_idf),
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )

            if expand_result.returncode != 0:
                typer.echo(f"ExpandObjects failed: {expand_result.stderr[:500]}", err=True)
                typer.echo("Trying to run EnergyPlus with original IDF...")

            if expand_result.returncode == 0:
                final_idf = str(expanded_idf)
            else:
                final_idf = str(idf_file)
        else:
            # No HVACTemplate objects - use IDF directly
            if not needs_expand:
                typer.echo("No HVACTemplate objects found - skipping ExpandObjects")
            final_idf = str(idf_file)

        typer.echo("Running EnergyPlus...")
        result = subprocess.run(
            [
                str(energyplus_exe),
                "-d", str(output_dir),
                "-w", str(weather),
                "-i", "C:/EnergyPlusV23-1-0/Energy+.idd",
                final_idf,
            ],
            capture_output=True,
            text=True,
            timeout=300,
        )

        if result.returncode == 0:
            typer.echo("Simulation completed successfully!")
            err_file = output_dir / "eplusout.err"
            if err_file.exists():
                with open(err_file) as f:
                    errors = f.read()
                    if "Fatal Error" in errors or "** Fatal" in errors:
                        typer.echo("Warning: Errors found in simulation:", err=True)
                        typer.echo(errors[:500], err=True)
        else:
            typer.echo(f"Simulation failed with code {result.returncode}", err=True)
            if result.stderr:
                typer.echo(result.stderr[:500], err=True)
            raise typer.Exit(code=1)

    except subprocess.TimeoutExpired:
        typer.echo("Error: Simulation timed out", err=True)
        raise typer.Exit(code=1)
    except Exception as e:
        typer.echo(f"Error running simulation: {e}", err=True)
        raise typer.Exit(code=1)


@idf_app.command("extract-loads")
def idf_extract_loads(
    eso_file: Path = typer.Option(..., "--eso", "-e", help="Input eplusout.eso file / 输入 eplusout.eso 文件"),
    output: Path = typer.Option(..., "--output", "-o", help="Output CSV file / 输出 CSV 文件"),
    include_hvac: bool = typer.Option(False, "--include-hvac", help="Include HVAC electricity estimate / 包含 HVAC 估算电耗"),
):
    """
    Extract building load profile from EnergyPlus ESO file for PV/Battery optimization.

    从 EnergyPlus ESO 文件提取建筑负荷曲线，用于 PV/电池优化。

    Outputs annual_energy_schedule_*.csv format compatible with main.py load_schedule().
    输出与 main.py load_schedule() 兼容的 annual_energy_schedule_*.csv 格式。
    """
    import re
    import csv

    if not eso_file.exists():
        typer.echo(f"Error: ESO file not found: {eso_file}", err=True)
        raise typer.Exit(code=1)

    typer.echo(f"Parsing {eso_file}...")

    with open(eso_file, 'r') as f:
        content = f.read()

    # Split header and data
    header, data = content.split('End of Data Dictionary')

    # Parse variable IDs from header
    var_map = {}
    for line in header.split('\n'):
        m = re.match(r'^(\d+),(\d+),([^,]+),(.+?) !', line)
        if m:
            vid = int(m.group(1))
            var_map[vid] = {
                'key': m.group(3).strip(),
                'name': m.group(4).strip()
            }

    # Initialize hourly storage - accumulate values per timestep
    # ESO format: each timestep has timestamp line (vid=2) followed by variable lines
    hourly_data = {
        'lights_j': [],
        'equipment_j': [],
        'heating_j': [],
        'cooling_j': [],
    }

    ts_lights = 0
    ts_equipment = 0
    ts_heating = 0
    ts_cooling = 0

    # Parse data lines
    for line in data.strip().split('\n'):
        line = line.strip()
        if not line:
            continue
        parts = line.split(',')
        if len(parts) < 2:
            continue

        try:
            vid = int(parts[0])
        except ValueError:
            continue

        # vid=1 is environment (only once at start), vid=2 marks new timestep
        if vid == 2:
            # Save previous timestep data if exists (skip first vid=2 which has no prior data)
            if ts_lights > 0 or ts_equipment > 0 or ts_heating > 0 or ts_cooling > 0:
                hourly_data['lights_j'].append(ts_lights)
                hourly_data['equipment_j'].append(ts_equipment)
                hourly_data['heating_j'].append(ts_heating)
                hourly_data['cooling_j'].append(ts_cooling)
            # Reset accumulators for new timestep
            ts_lights = 0
            ts_equipment = 0
            ts_heating = 0
            ts_cooling = 0
            continue

        if vid not in var_map:
            continue

        var_name = var_map[vid]['name']
        val = float(parts[1])

        # Accumulate values for this timestep (sum across zones)
        if 'Lights Electricity Energy' in var_name:
            ts_lights += val
        elif 'Electric Equipment Electricity Energy' in var_name:
            ts_equipment += val
        elif 'Heating Energy' in var_name:
            ts_heating += val
        elif 'Cooling Energy' in var_name:
            ts_cooling += val

    # Don't forget last timestep
    hourly_data['lights_j'].append(ts_lights)
    hourly_data['equipment_j'].append(ts_equipment)
    hourly_data['heating_j'].append(ts_heating)
    hourly_data['cooling_j'].append(ts_cooling)

    typer.echo(f"Hourly records: {len(hourly_data['lights_j'])}")

    # Convert J to kWh
    kwh_data = {
        'lights_kwh': [j / 3_600_000 for j in hourly_data['lights_j']],
        'equipment_kwh': [j / 3_600_000 for j in hourly_data['equipment_j']],
        'heating_kwh': [j / 3_600_000 for j in hourly_data['heating_j']],
        'cooling_kwh': [j / 3_600_000 for j in hourly_data['cooling_j']],
    }

    typer.echo(f"Annual totals:")
    typer.echo(f"  Lights: {sum(kwh_data['lights_kwh']):.2f} kWh")
    typer.echo(f"  Equipment: {sum(kwh_data['equipment_kwh']):.2f} kWh")
    typer.echo(f"  Heating: {sum(kwh_data['heating_kwh']):.2f} kWh")
    typer.echo(f"  Cooling: {sum(kwh_data['cooling_kwh']):.2f} kWh")

    # Calculate total load
    total_kwh = []
    for i in range(len(kwh_data['lights_kwh'])):
        load = kwh_data['lights_kwh'][i] + kwh_data['equipment_kwh'][i]
        if include_hvac:
            hvac_est = (kwh_data['heating_kwh'][i] + kwh_data['cooling_kwh'][i]) * 0.1
            load += hvac_est
        total_kwh.append(load)

    # Save CSV
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['Power (kWh)'])
        for p in total_kwh:
            writer.writerow([f'{p:.4f}'])

    typer.echo(f"Total building load: {sum(total_kwh):.2f} kWh/year")
    typer.echo(f"Saved {len(total_kwh)} hourly values to {output}")


@idf_app.command("template")
def idf_template():
    """
    Show available IDF templates.

    显示可用的 IDF 模板。
    """
    templates_dir = Path(__file__).resolve().parent.parent.parent / "OpenCROPS" / "idfs"
    templates = [
        ("container", "Template.idf", "Container-style PFAL template (recommended)"),
        ("noequip", "Template_NoEquip.idf", "Template without equipment"),
    ]

    typer.echo("\nAvailable templates:")
    typer.echo("-" * 70)
    for key, filename, desc in templates:
        template_path = templates_dir / filename
        status = "✓" if template_path.exists() else "✗"
        typer.echo(f"  {status} {key:12} | {filename:20} | {desc}")
    typer.echo("-" * 70)


if __name__ == "__main__":
    app()
