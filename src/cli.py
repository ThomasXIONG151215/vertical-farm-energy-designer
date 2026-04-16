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


if __name__ == "__main__":
    app()
