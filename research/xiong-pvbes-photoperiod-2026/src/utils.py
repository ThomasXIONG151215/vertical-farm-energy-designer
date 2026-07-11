import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, Union, List, Callable, Any
import logging
import time
import functools
import psutil
import os
from memory_profiler import profile as memory_profile
import datetime
from line_profiler import LineProfiler

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create performance data directories
PERF_DATA_DIR = Path("performance_data")
PERF_METRICS_DIR = PERF_DATA_DIR / "metrics"
PERF_MEMORY_DIR = PERF_DATA_DIR / "memory_profiles"

# Create directories if they don't exist
for dir_path in [PERF_METRICS_DIR, PERF_MEMORY_DIR]:
    dir_path.mkdir(parents=True, exist_ok=True)

# Global storage for performance metrics
_performance_metrics = []
_memory_profiles = {}

def save_aggregated_performance_data() -> None:
    """Save aggregated performance metrics to a single CSV file and memory profiles to a single MD file"""
    if _performance_metrics:
        # Save performance metrics
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        metrics_file = PERF_METRICS_DIR / f"aggregated_metrics_{timestamp}.csv"
        df = pd.DataFrame(_performance_metrics)
        df.to_csv(metrics_file, index=False)
        
        # Create markdown report
        report_file = PERF_MEMORY_DIR / f"aggregated_memory_profile_{timestamp}.md"
        with open(report_file, 'w') as f:
            f.write("# Aggregated Performance Report\n\n")
            f.write(f"Generated at: {datetime.datetime.now().isoformat()}\n\n")
            
            # Add performance metrics summary
            f.write("## Performance Metrics Summary\n\n")
            f.write("| Function | Avg Time (s) | Avg Memory (MB) | Avg CPU (%) | Calls |\n")
            f.write("|----------|--------------|----------------|-------------|--------|\n")
            
            metrics_summary = df.groupby('function_name').agg({
                'execution_time_seconds': ['mean', 'count'],
                'memory_used_mb': 'mean',
                'cpu_percent': 'mean'
            }).round(2)
            
            for func, row in metrics_summary.iterrows():
                f.write(f"| {func} | {row[('execution_time_seconds', 'mean')]} | "
                       f"{row[('memory_used_mb', 'mean')]} | {row[('cpu_percent', 'mean')]} | "
                       f"{row[('execution_time_seconds', 'count')]} |\n")
            
            # Add memory profiles
            f.write("\n## Detailed Memory Profiles\n\n")
            for func_name, profile in _memory_profiles.items():
                f.write(f"\n### {func_name}\n")
                f.write("```\n")
                f.write(profile)
                f.write("\n```\n")
        
        # Clear the storage
        _performance_metrics.clear()
        _memory_profiles.clear()
        
        logger.info(f"Aggregated performance report saved to {report_file}")

def performance_monitor(func: Callable) -> Callable:
    """Decorator to monitor function execution time and memory usage"""
    @functools.wraps(func)
    def wrapper(*args, **kwargs) -> Any:
        process = psutil.Process(os.getpid())
        start_mem = process.memory_info().rss / 1024 / 1024
        start_time = time.time()
        start_cpu = process.cpu_percent()
        
        result = func(*args, **kwargs)
        
        end_time = time.time()
        end_mem = process.memory_info().rss / 1024 / 1024
        end_cpu = process.cpu_percent()
        
        # Calculate metrics
        metrics = {
            'timestamp': datetime.datetime.now().isoformat(),
            'function_name': func.__name__,
            'execution_time_seconds': end_time - start_time,
            'memory_used_mb': end_mem - start_mem,
            'cpu_percent': end_cpu,
            'total_memory_mb': end_mem,
            'args_count': len(args),
            'kwargs_count': len(kwargs)
        }
        
        # Store metrics
        _performance_metrics.append(metrics)
        
        return result
    return wrapper

def detailed_memory_profile(func: Callable) -> Callable:
    """Decorator for detailed memory profiling using memory_profiler"""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        # Create memory profiler
        profiler = LineProfiler()
        profiled_func = profiler(func)
        
        # Run the function with profiling
        result = profiled_func(*args, **kwargs)
        
        # Capture the profile output
        import io
        output = io.StringIO()
        profiler.print_stats(stream=output)
        _memory_profiles[func.__name__] = output.getvalue()
        output.close()
        
        return result
    
    return wrapper

def load_schedule(schedule_file: Path) -> np.ndarray:
    """
    Load and validate an energy schedule from a CSV file.
    Handles both total_energy_schedule_*.csv and annual_energy_schedule_*.csv formats.
    """
    logger.info(f"Loading schedule from {schedule_file}")
    
    try:
        # Read the CSV file
        df = pd.read_csv(schedule_file)
        
        # Extract the power column - handle both old and new formats
        if 'Power (kWh)' in df.columns:
            power_profile = df['Power (kWh)'].values
        else:
            # Assume first column is power if header not found
            power_profile = df.iloc[:, 0].values
        
        # Validate the data
        if len(power_profile) == 0:
            raise ValueError("Empty power profile")
            
        if np.any(np.isnan(power_profile)):
            raise ValueError("Power profile contains NaN values")
            
        if np.any(power_profile < 0):
            raise ValueError("Power profile contains negative values")
            
        logger.info(f"Loaded profile with shape {power_profile.shape}, range: [{power_profile.min():.2f}, {power_profile.max():.2f}] kWh")
        return power_profile
        
    except Exception as e:
        logger.error(f"Error loading schedule from {schedule_file}: {str(e)}")
        raise

def prepare_weather_data(file_path: Union[str, Path] = None) -> pd.DataFrame:
    """
    Prepare weather data for system simulation
    If no file path provided, generate synthetic data
    """
    if file_path is not None and Path(file_path).exists():
        df = pd.read_csv(file_path)
        
        # Ensure we have exactly 8760 hours (1 year)
        if len(df) != 8760:
            raise ValueError(f"Weather data must contain exactly 8760 hours, got {len(df)}")
        
        # Convert temperature column if needed
        if 'temperature_2m (°C)' in df.columns:
            df['temperature_2m'] = df['temperature_2m (°C)']
        
        # Split total radiation into components if needed
        if 'total_incident_radiation' in df.columns:
            total_radiation = df['total_incident_radiation']
            # Approximate split: 70% direct, 20% diffuse, 10% shortwave
            df['direct_radiation'] = total_radiation * 0.7
            df['diffuse_radiation'] = total_radiation * 0.2
            df['shortwave_radiation'] = total_radiation * 0.1
        
        required_columns = ['temperature_2m', 'direct_radiation', 'diffuse_radiation', 'shortwave_radiation']
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            raise ValueError(f"Missing required columns in weather data: {missing_columns}")
        
        return df
    
    # Generate synthetic weather data if no file provided
    hours = pd.date_range(start='2024-01-01', periods=8760, freq='H')
    
    # Temperature: Base + Seasonal + Daily variation
    temp_base = 20
    temp_seasonal_amp = 10
    temp_daily_amp = 5
    
    day_of_year = hours.dayofyear
    hour_of_day = hours.hour
    
    temperature = (temp_base + 
                  temp_seasonal_amp * np.sin(2 * np.pi * (day_of_year - 180) / 365) +
                  temp_daily_amp * np.sin(2 * np.pi * (hour_of_day - 14) / 24))
    
    # Solar radiation: Daily pattern with seasonal variation
    solar_max = 1000  # W/m²
    solar_seasonal = np.sin(2 * np.pi * (day_of_year - 172) / 365)  # Peak at summer solstice
    solar_daily = np.sin(2 * np.pi * (hour_of_day - 6) / 24)  # Peak at noon
    total_radiation = np.maximum(0, solar_max * solar_seasonal * solar_daily)
    
    # Create DataFrame with split radiation components
    df = pd.DataFrame({
        'time': hours,
        'temperature_2m': temperature,
        'direct_radiation': total_radiation * 0.7,
        'diffuse_radiation': total_radiation * 0.2,
        'shortwave_radiation': total_radiation * 0.1
    })
    
    return df

def extract_schedule_info(file_name: str) -> Dict[str, int]:
    """Extract schedule timing information from filename"""
    # Expected format: total_energy_schedule_HH_HH.csv
    try:
        parts = file_name.split('_')
        start_hour = int(parts[-2])
        end_hour = int(parts[-1].split('.')[0])
        
        return {
            'start_hour': start_hour,
            'end_hour': end_hour
        }
    except (IndexError, ValueError):
        raise ValueError(f"Invalid schedule filename format: {file_name}")

def calculate_daily_metrics(schedule_data: pd.DataFrame) -> Dict[str, float]:
    """Calculate daily energy consumption metrics"""
    # Convert hourly power to daily energy
    daily_energy = schedule_data['Power (kWh)'].values.reshape(-1, 24).sum(axis=1)
    
    return {
        'daily_mean': np.mean(daily_energy),
        'daily_std': np.std(daily_energy),
        'daily_min': np.min(daily_energy),
        'daily_max': np.max(daily_energy)
    }

def validate_optimization_results(results: List[Dict]) -> bool:
    """Validate optimization results for consistency"""
    required_keys = [
        'optimal_pv', 'optimal_battery', 'lcoe', 'actual_electricity_cost', 'tlps',
        'capital_cost', 'pv_cost', 'battery_cost', 'annual_pv_generation',
        'annual_electricity_saved', 'annual_electricity_consumed', 'payback_period',
        'annual_maintenance'
    ]
    
    for result in results:
        # Check for required keys
        if not all(key in result for key in required_keys):
            logger.error(f"Missing required keys in result. Required: {required_keys}, Got: {list(result.keys())}")
            return False
        
        # Check for valid values
        if (result['optimal_pv'] <= 0 or 
            result['optimal_battery'] <= 0 or
            result['lcoe'] < 0 or 
            result['actual_electricity_cost'] < 0 or
            result['tlps'] < 0 or result['tlps'] > 1 or
            result['capital_cost'] <= 0 or
            result['pv_cost'] <= 0 or
            result['battery_cost'] <= 0 or
            result['annual_pv_generation'] <= 0 or
            result['annual_electricity_saved'] <= 0 or
            result['annual_electricity_consumed'] <= 0 or
            result['payback_period'] <= 0 or
            result['annual_maintenance'] <= 0):
            logger.error(f"Invalid values in result: {result}")
            return False
    
    return True

def generate_load_profile(hours_per_year: int, photoperiod_start: int, 
                          photoperiod_duration: int, base_load_kw: float, 
                          peak_load_kw: float) -> np.ndarray:
    """
    Generate a synthetic load profile based on photoperiod parameters.
    
    Args:
        hours_per_year: Number of hours in the simulation period (typically 8760)
        photoperiod_start: Hour of day when photoperiod starts (0-23)
        photoperiod_duration: Duration of photoperiod in hours
        base_load_kw: Base load in kW (minimum load during off-hours)
        peak_load_kw: Peak load in kW (maximum load during photoperiod)
    
    Returns:
        np.ndarray: Hourly load profile for the entire simulation period
    """
    # Create an empty array for the load profile
    load_profile = np.zeros(hours_per_year)
    
    # Calculate photoperiod end hour
    photoperiod_end = (photoperiod_start + photoperiod_duration) % 24
    
    # Generate load profile for each hour
    for hour in range(hours_per_year):
        hour_of_day = hour % 24
        
        # Check if current hour is within photoperiod
        if photoperiod_start <= hour_of_day < photoperiod_end:
            # During photoperiod - peak load with some randomness
            load_profile[hour] = peak_load_kw * (0.8 + 0.4 * np.random.random())
        else:
            # Outside photoperiod - base load with some randomness
            load_profile[hour] = base_load_kw * (0.7 + 0.6 * np.random.random())
    
    logger.info(f"Generated load profile with shape {load_profile.shape}, " +
                f"range: [{load_profile.min():.2f}, {load_profile.max():.2f}] kW")
    return load_profile 