import os
import pandas as pd
import numpy as np
from pathlib import Path
import logging
from src.optimizer import SystemOptimizer
from src.visualization import SystemVisualizer
from src.system import EnergySystem
from src.utils import (load_schedule, validate_optimization_results, 
                    performance_monitor, detailed_memory_profile,
                    save_aggregated_performance_data,
                    )
from weather.city_coordinates import CITY_COORDINATES
from weather.weather_extractor import WeatherExtractor
from weather.epw_converter import EPWConverter
from tqdm import tqdm
import re
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from load_analysis.energy_data_analysis import PlotStyler
import traceback
import sys
from typing import Dict
from analyze_results import (
    analyze_city_climate_energy,
    analyze_mechanism_results,
)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

# Create global DataFrame to store all optimization results
RESULTS_DF_PATH = Path("all_optimization_results.csv")
if RESULTS_DF_PATH.exists():
    results_df = pd.read_csv(RESULTS_DF_PATH)
else:
    results_df = pd.DataFrame(columns=[
        'city',                                      # City name
        'scenario',                                  # Grid scenario
        'schedule_start',                           # Schedule start hour
        'schedule_end',                             # Schedule end hour
        'photoperiod',                              # Photoperiod length
        'optimal_pv_area [m²]',                     # PV array area
        'optimal_battery_capacity [kWh]',           # Battery capacity
        'capital_cost [$]',                         # Total capital cost
        'annual_savings [$/year]',                  # Annual cost savings
        'annual_maintenance [$/year]',             # Annual maintenance cost
        'net_annual_profit [$/year]',              # Net annual profit (savings - maintenance)
        'payback_period [years]',                   # System payback period
        'lcoe [$/kWh]',                            # Levelized cost of energy
        'grid_cost [$/year]',                      # Annual grid electricity cost
        'pv_depreciation [$/year]',                # Annual PV depreciation
        'battery_depreciation [$/year]',           # Annual battery depreciation
        'annual_pv_generation [kWh/year]',        # Annual PV energy generation
        'annual_pv_used [kWh/year]',              # Annual PV energy directly used
        'annual_grid_import [kWh/year]',          # Annual energy imported from grid
        'annual_grid_export [kWh/year]',          # Annual energy exported to grid
        'annual_battery_charge [kWh/year]',       # Annual energy charged to battery
        'annual_battery_discharge [kWh/year]',    # Annual energy discharged from battery
        'tlps [%]',                               # Time loss of power supply percentage
        'tlps_max [%]',                           # Maximum allowed TLPS
        'is_feasible',                            # Whether solution meets all constraints
        'is_optimal',                             # Whether solution is the optimal one
        'constraint_violations'                    # List of any constraint violations
    ])


def update_results_df(city: str, result: dict, schedule_file: Path) -> None:
    """Update the global results DataFrame with new optimization results"""
    global results_df
    
    try:
        # Always extract schedule timing from filename
        # Format: annual_energy_schedule_START_END.csv
        parts = schedule_file.stem.split('_')
        start_hour = int(parts[-2])  # Start hour
        end_hour = int(parts[-1])    # End hour
        
        # Validate hours
        if not (0 <= start_hour <= 23 and 0 <= end_hour <= 23):
            logger.warning(f"Invalid hours in filename: {start_hour} to {end_hour}")
            return
            
        # Calculate photoperiod length considering wrap-around
        if end_hour < start_hour:  # e.g., 23 to 15 means 16 hours (23,00,01,...,15)
            photoperiod = (24 - start_hour) + end_hour
        else:  # e.g., 01 to 17 means 16 hours
            photoperiod = end_hour - start_hour
            
        logger.info(f"Processing schedule with photoperiod: {start_hour:02d}:00 to {end_hour:02d}:00 ({photoperiod} hours)")
        
        if result['success']:
            # Calculate net annual profit
            net_annual_profit = result['metrics']['annual_savings'] - result['metrics']['annual_maintenance']
            
            # Create new row data
            new_row = {
                'city': city,
                'scenario': result['scenario'],
                'schedule_start': start_hour,  # Store start hour (0-23)
                'schedule_end': end_hour,      # Store end hour (0-23)
                'photoperiod': photoperiod,    # Store photoperiod length in hours
                'optimal_pv_area [m²]': result['optimal_pv'],
                'optimal_battery_capacity [kWh]': result['optimal_battery'],
                'capital_cost [$]': result['metrics']['capital_cost'],
                'annual_savings [$/year]': result['metrics']['annual_savings'],
                'annual_maintenance [$/year]': result['metrics']['annual_maintenance'],
                'net_annual_profit [$/year]': net_annual_profit,
                'payback_period [years]': result['metrics']['payback_period'],
                'lcoe [$/kWh]': result['metrics']['lcoe'],
                'grid_cost [$/year]': result['metrics']['grid_cost'],
                'pv_depreciation [$/year]': result['metrics']['pv_depreciation'],
                'battery_depreciation [$/year]': result['metrics']['battery_depreciation'],
                'annual_pv_generation [kWh/year]': result['metrics']['annual_pv_generation'],
                'annual_pv_used [kWh/year]': result['metrics']['annual_pv_used'],
                'annual_grid_import [kWh/year]': result['metrics']['annual_grid_import'],
                'annual_grid_export [kWh/year]': result['metrics']['annual_grid_export'],
                'annual_battery_charge [kWh/year]': result['metrics']['annual_battery_charge'],
                'annual_battery_discharge [kWh/year]': result['metrics']['annual_battery_discharge'],
                'tlps [%]': result['metrics']['tlps'],
                'tlps_max [%]': result['metrics'].get('tlps_max', 100),
                'is_feasible': result['metrics']['is_feasible'],
                'is_optimal': result['metrics']['is_optimal'],
                'constraint_violations': result['metrics']['constraint_violations']
            }
            
            # Append new row to DataFrame
            results_df = pd.concat([results_df, pd.DataFrame([new_row])], ignore_index=True)
            
            # Save updated DataFrame
            results_df.to_csv(RESULTS_DF_PATH, index=False)
            logger.info(f"Updated results for {city} - {result['scenario']} - Schedule {start_hour:02d}:00 to {end_hour:02d}:00")
            
    except Exception as e:
        logger.error(f"Error updating results DataFrame: {str(e)}")
        logger.error(traceback.format_exc())


def setup_city_directories(base_dir: Path, city_key: str) -> dict[str, Path]:
    """
    Create and return directory structure for a city
    """
    city_dir = base_dir / city_key
    dirs = {
        'output': city_dir / 'output',
        'results': city_dir / 'results',
        'weather': city_dir / 'weather'
    }
    
    # Create directories
    for dir_path in dirs.values():
        dir_path.mkdir(parents=True, exist_ok=True)
        
    return dirs

@performance_monitor
@detailed_memory_profile
def process_schedule(schedule_file: Path,
                    energy_system: EnergySystem,
                    optimizer: SystemOptimizer,
                    visualizer: SystemVisualizer,
                    weather_data: pd.DataFrame,
                    results_dir: Path,
                    city_key: str) -> dict:
    """Process a single schedule file with weather data for both scenarios"""
    try:
        logger.info(f"Processing {schedule_file.name}")
        
        # Extract schedule timing from filename
        # Format: annual_energy_schedule_START_END.csv
        parts = schedule_file.stem.split('_')
        start_hour = int(parts[-2])  # Start hour
        end_hour = int(parts[-1])    # End hour
        
        # Calculate photoperiod length considering wrap-around
        if end_hour < start_hour:  # e.g., 23 to 15 means 16 hours (23,00,01,...,15)
            photoperiod = (24 - start_hour) + end_hour
        else:  # e.g., 01 to 17 means 16 hours
            photoperiod = end_hour - start_hour
        
        # Load schedule data
        load_profile = load_schedule(schedule_file)
        
        # Run optimization for both scenarios
        results = optimizer.optimize_both_scenarios(
            load_profile=load_profile,
            weather_data=weather_data,
            base_constraints={
                'soc_min': 0.1,
                'soc_max': 0.9,
                'max_charge_rate': 1.0,
                'max_discharge_rate': 1.0,
                'min_annual_profit': True,  # Ensure annual savings > maintenance costs
                'schedule_start': start_hour,  # Add schedule info to constraints
                'schedule_end': end_hour,
                'photoperiod': photoperiod,
                'tlps_max': 100
            },
            city=city_key,
            scenarios=[
                ('100_percent_grid_connected', {
                    'tlps_max': 100,
                    'schedule_start': start_hour,
                    'schedule_end': end_hour,
                    'photoperiod': photoperiod
                })
            ]
        )
        
        # Process results and update global DataFrame
        for scenario, result in results.items():
            if result['success']:
                # Add schedule information to result
                result['schedule_start'] = start_hour
                result['schedule_end'] = end_hour
                result['photoperiod'] = photoperiod
                
                # Calculate PV utilization before updating results
                total_pv = result['metrics']['annual_pv_generation']
                total_load = np.sum(load_profile)
                pv_used = min(total_pv, total_load - result['metrics']['annual_grid_import'])
                result['metrics']['annual_pv_used'] = pv_used
                
                # Update global results DataFrame with metrics
                update_results_df(city_key, result, schedule_file)
                
                # Create hourly performance DataFrame
                performance = result.get('performance', {})
                if performance:
                    # Save hourly energy balance
                    save_hourly_energy_balance(
                        results_dir=results_dir,
                        city_key=city_key,
                        start_hour=start_hour,
                        end_hour=end_hour,
                        pv_area=result['optimal_pv'],
                        battery_capacity=result['optimal_battery'],
                        load_profile=load_profile,
                        performance=performance
                    )
                    
                    hourly_data = pd.DataFrame({
                        'timestamp': pd.date_range(start='2024-01-01', periods=len(load_profile), freq='H'),
                        'city': city_key,
                        'scenario': scenario,
                        'schedule_name': schedule_file.stem,
                        'schedule_start': start_hour,
                        'schedule_end': end_hour,
                        'photoperiod': photoperiod,
                        'pv_area_m2': result['optimal_pv'],
                        'battery_capacity_kWh': result['optimal_battery'],
                        'load_kWh': load_profile,
                        'pv_kW': performance.get('pv_power', np.zeros_like(load_profile)),
                        'battery_kWh': performance.get('battery_power', np.zeros_like(load_profile)),
                        'battery_soc': performance.get('battery_soc', np.zeros(len(load_profile) + 1))[:-1],
                        'grid_import_kWh': performance.get('grid_import', np.zeros_like(load_profile)),
                        'grid_export_kWh': performance.get('grid_export', np.zeros_like(load_profile)),
                        'direct_radiation_W/m2': weather_data['direct_radiation'],
                        'diffuse_radiation_W/m2': weather_data['diffuse_radiation'],
                        'shortwave_radiation_W/m2': weather_data['shortwave_radiation'],
                        'temperature_C': weather_data['temperature_2m']
                    })
                    
                    # Calculate total power balance for verification
                    power_balance = (hourly_data['pv_kW'] + 
                                   hourly_data['battery_kWh'] + 
                                   hourly_data['grid_import_kWh'] - 
                                   hourly_data['grid_export_kWh'] - 
                                   hourly_data['load_kWh'])
                    
                    # Log power balance statistics
                    logger.info(f"Power balance check - Mean: {power_balance.mean():.6f}, Max: {power_balance.max():.6f}, Min: {power_balance.min():.6f}")
                    
                    # Save hourly data
                    hourly_file = results_dir / f"{schedule_file.stem}_{scenario}_hourly.csv"
                    hourly_data.to_csv(hourly_file, index=False)
                    logger.info(f"Saved hourly data to {hourly_file}")
                
                # Generate and save visualizations
                figs = visualizer.create_system_plots(
                    load_profile=load_profile,
                    weather_data=weather_data,
                    result=result
                )
                
                # Save plots with scenario suffix
                for name, fig in figs.items():
                    fig.write_html(results_dir / f"{schedule_file.stem}_{scenario}_{name}.html")
            else:
                logger.error(f"Optimization failed for {scenario} scenario: {result.get('error', 'Unknown error')}")
        
        return {'success': True, 'metrics': results}
        
    except Exception as e:
        logger.error(f"Error processing {schedule_file.name}: {str(e)}")
        logger.error(traceback.format_exc())
        return {'success': False, 'error': str(e)}

@performance_monitor
@detailed_memory_profile
def process_city(city_key: str, base_dir: Path) -> None:
    """
    Process all schedules for a single city
    """
    try:
        logger.info(f"Processing city: {CITY_COORDINATES[city_key]['name']}")
        
        # Setup directories
        dirs = setup_city_directories(base_dir, city_key)
        
        # Check if weather data already exists
        weather_csv = dirs['weather'] / f"{city_key}_2024.csv"
        if weather_csv.exists():
            logger.info(f"Found existing weather data for {city_key}")
            weather_data = pd.read_csv(weather_csv)
            
            # Remove February 29 data if present (leap year)
            if len(weather_data) > 8760:
                logger.info("Removing February 29 data from weather dataset")
                # Create datetime index
                dates = pd.date_range(start='2024-01-01', periods=len(weather_data), freq='H')
                weather_data['date'] = dates
                # Remove February 29
                weather_data = weather_data[~((weather_data['date'].dt.month == 2) & 
                                            (weather_data['date'].dt.day == 29))]
                weather_data = weather_data.drop('date', axis=1)
                # Save the corrected data
                weather_data.to_csv(weather_csv, index=False)
        else:
            # Get weather data
            weather_extractor = WeatherExtractor()
            city_info = CITY_COORDINATES[city_key]
            weather_data = weather_extractor.get_weather_data(
                latitude=city_info["latitude"],
                longitude=city_info["longitude"],
                timezone=city_info["timezone"],
                city_name=CITY_COORDINATES[city_key]['name'],
                output_dir=dirs['weather']
            )
            
            if weather_data is None:
                raise ValueError(f"Failed to get weather data for {city_key}")
        
        # Convert to EPW if needed
        epw_file = dirs['weather'] / f"{city_key}_2024.epw"
        if not epw_file.exists():
            epw_converter = EPWConverter()
            template_epw = base_dir / "weather" / "template.epw"
            
            if not epw_converter.modify_epw_with_data(
                template_epw,
                weather_data,
                epw_file
            ):
                raise ValueError(f"Failed to create EPW file for {city_key}")
        
        # Initialize systems
        energy_system = EnergySystem()
        optimizer = SystemOptimizer(energy_system)
        visualizer = SystemVisualizer()
        
        # Process schedules
        schedule_files = list(dirs['output'].glob("annual_energy_schedule_*.csv"))
        if not schedule_files:
            logger.warning(f"No annual energy schedule files found in {dirs['output']}, checking for old format...")
            schedule_files = list(dirs['output'].glob("total_energy_schedule_*.csv"))
            if not schedule_files:
                raise ValueError(f"No schedule files found in {dirs['output']}")
        
        results = []
        with tqdm(schedule_files, desc="Processing schedules", unit="file") as pbar:
            for schedule_file in pbar:
                result = process_schedule(
                    schedule_file,
                    energy_system,
                    optimizer,
                    visualizer,
                    weather_data,
                    dirs['results'],
                    city_key
                )
                if result is not None:
                    results.append(result)
        
        # Save and validate results
        if results and validate_optimization_results(results):
            df_results = pd.DataFrame(results)
            results_file = dirs['results'] / "optimization_results.csv"
            df_results.to_csv(results_file, index=False)
            
            logger.info(f"Successfully processed {len(results)} schedules for {city_key}")
        else:
            logger.error(f"No valid results obtained for {city_key}")
            
    except Exception as e:
        logger.error(f"Error processing city {city_key}: {str(e)}")
        raise  # Re-raise to show the full error stack

def extract_schedule_hours(filename: str) -> tuple:
    """Extract start and end hours from schedule filename"""
    match = re.search(r'annual_energy_schedule_(\d{2})_(\d{2})\.csv', filename)
    if match:
        return int(match.group(1)), int(match.group(2))
    return None, None

def save_hourly_energy_balance(
    results_dir: Path, 
    city_key: str, 
    start_hour: int, 
    end_hour: int, 
    pv_area: float, 
    battery_capacity: float, 
    load_profile: np.ndarray, 
    performance: Dict
) -> None:
    """
    Save hourly energy balance to a CSV file
    
    Args:
        results_dir: Directory to save results
        city_key: City identifier
        start_hour: Start hour of schedule
        end_hour: End hour of schedule
        pv_area: PV area in m²
        battery_capacity: Battery capacity in kWh
        load_profile: Hourly load profile
        performance: Performance dictionary from simulation
    """
    # Create timestamp for hourly data
    timestamps = pd.date_range(start='2024-01-01', periods=len(load_profile), freq='H')
    
    # Prepare hourly energy balance DataFrame
    hourly_balance = pd.DataFrame({
        'timestamp': timestamps,
        'city': city_key,
        'schedule_start': f"{start_hour:02d}:00",
        'schedule_end': f"{end_hour:02d}:00",
        'pv_area_m2': pv_area,
        'battery_capacity_kWh': battery_capacity,
        'load_kWh': load_profile,
        'pv_generation_kWh': performance['pv_power'],
        'battery_discharge_kWh': -np.minimum(performance['battery_power'], 0),
        'battery_charge_kWh': np.maximum(performance['battery_power'], 0),
        'grid_import_kWh': performance['grid_import']
    })
    
    # Save hourly energy balance to CSV
    balance_file = results_dir / f"{city_key}_hourly_energy_balance.csv"
    hourly_balance.to_csv(balance_file, index=False)
    logger.info(f"Saved hourly energy balance to {balance_file}")

def evaluate_single_config(pv_area: float,
                         battery_capacity: float,
                         schedule_file: Path,
                         weather_data: pd.DataFrame,
                         results_dir: Path,
                         city_key: str) -> dict:
    """
    Evaluate a single PV-battery configuration
    
    Args:
        pv_area: PV area in m²
        battery_capacity: Battery capacity in kWh
        schedule_file: Path to load profile CSV
        weather_data: Weather data DataFrame
        results_dir: Directory to save results
        city_key: City identifier
    """
    try:
        logger.info(f"Evaluating configuration: PV={pv_area:.1f}m², Battery={battery_capacity:.1f}kWh")
        
        # Initialize systems
        energy_system = EnergySystem()
        
        # Load schedule data
        load_profile = load_schedule(schedule_file)
        
        # Create configuration array
        x = np.array([pv_area, battery_capacity])
        
        # Simulate performance
        performance = energy_system.simulate_performance(
            x,
            weather_data,
            load_profile,
            is_independent=False
        )
        
        # Calculate metrics
        metrics = energy_system.calculate_metrics(
            x,
            weather_data,
            load_profile
        )
        
        # Extract schedule timing from filename
        parts = schedule_file.stem.split('_')
        start_hour = int(parts[-2])
        end_hour = int(parts[-1])
        
        # Save hourly energy balance
        save_hourly_energy_balance(
            results_dir=results_dir,
            city_key=city_key,
            start_hour=start_hour,
            end_hour=end_hour,
            pv_area=pv_area,
            battery_capacity=battery_capacity,
            load_profile=load_profile,
            performance=performance
        )
        
        # Detailed Energy Balance Debugging
        print("\n" + "="*50)
        print("DETAILED ENERGY BALANCE DEBUGGING")
        print("="*50)
        print(f"Total Load: {np.sum(load_profile):,.2f} kWh")
        print(f"Total PV Generation: {np.sum(performance['pv_power']):,.2f} kWh")
        print(f"Total Battery Discharge: {np.sum(np.maximum(0, -performance['battery_power'])):,.2f} kWh")
        print(f"Total Grid Import: {np.sum(performance['grid_import']):,.2f} kWh")
        
        # Calculate battery energy metrics
        battery_charge = np.sum(np.maximum(0, performance['battery_power']))  # Sum of positive power (charging)
        battery_discharge = np.sum(np.maximum(0, -performance['battery_power']))  # Sum of negative power (discharging)
        
        # Calculate PV utilization
        total_pv = metrics['annual_pv_generation']
        total_load = np.sum(load_profile)
        pv_used = min(total_pv, total_load - metrics['annual_grid_import'])
        pv_wasted = max(0, total_pv - pv_used)
        
        # Print all results in organized sections
        print("\n" + "="*50)
        print("SYSTEM CONFIGURATION")
        print("="*50)
        print(f"City: {city_key}")
        print(f"Schedule: {start_hour:02d}:00 to {end_hour:02d}:00")
        print(f"PV Area: {pv_area:.1f} m²")
        print(f"Battery Capacity: {battery_capacity:.1f} kWh")
        
        print("\n" + "="*50)
        print("LOAD PROFILE METRICS")
        print("="*50)
        print(f"Annual Load: {total_load:,.0f} kWh")
        print(f"Average Daily Load: {total_load/365:,.1f} kWh")
        print(f"TLPS: {metrics['tlps']:.2f}%")
        
        print("\n" + "="*50)
        print("PV GENERATION METRICS")
        print("="*50)
        print(f"Annual Generation: {metrics['annual_pv_generation']:,.0f} kWh")
        print(f"Average Daily Generation: {metrics['annual_pv_generation']/365:,.1f} kWh")
        print(f"PV Utilization: {pv_used/total_pv*100:.1f}%")
        print(f"PV Curtailment: {pv_wasted/total_pv*100:.1f}%")
        
        print("\n" + "="*50)
        print("BATTERY PERFORMANCE METRICS")
        print("="*50)
        print(f"Total Charged Energy: {performance.get('total_charged_energy', battery_charge):,.0f} kWh")
        print(f"Total Discharged Energy: {performance.get('total_discharged_energy', battery_discharge):,.0f} kWh")
        print(f"Battery Throughput: {performance.get('battery_throughput', 0):,.0f}")
        
        # Additional battery performance details
        if performance.get('battery_soc') is not None:
            print(f"Battery SOC Range: {np.min(performance['battery_soc']):.2f}-{np.max(performance['battery_soc']):.2f}")
        
        print("\n" + "="*50)
        print("GRID INTERACTION METRICS")
        print("="*50)
        print(f"Annual Grid Import: {metrics['annual_grid_import']:,.0f} kWh")
        print(f"Average Daily Grid Import: {metrics['annual_grid_import']/365:,.1f} kWh")
        print(f"Grid Dependency: {metrics['annual_grid_import']/total_load*100:.1f}%")
        
        print("\n" + "="*50)
        print("FINANCIAL METRICS")
        print("="*50)
        print(f"LCOE: ${metrics['lcoe']:.4f}/kWh")
        print(f"Capital Cost: ${metrics['capital_cost']:,.0f}")
        print(f"Annual Grid Cost: ${metrics['grid_cost']:,.0f}")
        print(f"Annual Savings: ${metrics['annual_savings']:,.0f}")
        print(f"Payback Period: {metrics['payback_period']:.1f} years")
        print("="*50 + "\n")
        
        metrics['PV_utilization'] = pv_used/total_pv*100
        metrics['grid_dependency'] = metrics['annual_grid_import']/total_load*100
        
        return {
            'success': True,
            'metrics': metrics,
            'performance': performance
        }
        
    except Exception as e:
        logger.error(f"Error evaluating configuration: {str(e)}")
        logger.error(traceback.format_exc())
        return {
            'success': False,
            'error': str(e)
        }

def evaluate_mechanism_configs(pv_area: float,
                            battery_capacity: float,
                            start_hour1: int,
                            start_hour2: int,
                            city_key: str,
                            base_dir: Path) -> None:
    """
    Evaluate system configurations for mechanism analysis with two different start hours
    
    Args:
        pv_area: PV area in m²
        battery_capacity: Battery capacity in kWh
        start_hour1: First start hour (0-23)
        start_hour2: Second start hour (0-23)
        city_key: City identifier
        base_dir: Base directory for the project
    """
    try:
        # Setup directories
        city_dir = base_dir / city_key
        dirs = {
            'output': city_dir / 'output',
            'results': city_dir / 'results',
            'weather': city_dir / 'weather'
        }
        
        # Create directories if they don't exist
        for dir_path in dirs.values():
            dir_path.mkdir(parents=True, exist_ok=True)
        
        # Load weather data
        weather_csv = dirs['weather'] / f"{city_key}_2024.csv"
        if not weather_csv.exists():
            raise ValueError(f"Weather data not found for {city_key}")
        weather_data = pd.read_csv(weather_csv)
        
        # Create timestamp for hourly data
        timestamps = pd.date_range(start='2024-01-01', periods=8760, freq='H')
        
        # Initialize results dictionary
        results = {
            'timestamp': timestamps,
            'city': city_key,
            'config_metrics': []  # List to store configuration metrics
        }
        
        # Add radiation data to results for visualization
        if 'direct_radiation' in weather_data.columns and 'diffuse_radiation' in weather_data.columns:
            results['direct_radiation_W/m2'] = weather_data['direct_radiation'].values
            results['diffuse_radiation_W/m2'] = weather_data['diffuse_radiation'].values
            if 'shortwave_radiation' in weather_data.columns:
                results['shortwave_radiation_W/m2'] = weather_data['shortwave_radiation'].values
        
        # Add temperature data if available
        if 'temperature_2m' in weather_data.columns:
            results['temperature_C'] = weather_data['temperature_2m'].values
        
        # Process each configuration
        for start_hour in [start_hour1, start_hour2]:
            # Find corresponding schedule file
            schedule_pattern = f"annual_energy_schedule_{start_hour:02d}_*.csv"
            schedule_files = list(dirs['output'].glob(schedule_pattern))
            if not schedule_files:
                raise ValueError(f"No schedule file found for start hour {start_hour:02d}")
            schedule_file = schedule_files[0]
            
            # Load schedule data
            load_profile = load_schedule(schedule_file)
            
            # Add load profile to results
            results[f'load_profile_h{start_hour:02d}'] = load_profile
            
            # Configuration labels
            pv_only_label = f"PV{start_hour:02d}"  # e.g., "PV08" for PV-only at 8:00
            full_sys_label = f"PVB{start_hour:02d}"  # e.g., "PVB08" for PV+Battery at 8:00
            
            # Evaluate with PV only (no battery)
            pv_only_result = evaluate_single_config(
                pv_area=pv_area,
                battery_capacity=0.0,
                schedule_file=schedule_file,
                weather_data=weather_data,
                results_dir=dirs['results'],
                city_key=city_key
            )
            
            if not pv_only_result['success']:
                raise ValueError(f"PV-only evaluation failed for start hour {start_hour}")
            
            # Add PV-only results
            prefix = f'h{start_hour:02d}_pv_only'
            pv_generation = pv_only_result['performance']['pv_power']
            grid_import = pv_only_result['performance']['grid_import']
            
            results[f'{prefix}_pv_generation'] = pv_generation
            results[f'{prefix}_grid_import'] = grid_import
            results[f'{prefix}_battery_charge'] = np.zeros_like(load_profile)
            results[f'{prefix}_battery_discharge'] = np.zeros_like(load_profile)
            
            # Calculate PV-only metrics
            total_load = np.sum(load_profile)
            total_pv = np.sum(pv_generation)
            total_grid = np.sum(grid_import)
            
            pv_only_metrics = {
                'config_label': pv_only_label,
                'description': f'PV-only system starting at {start_hour:02d}:00',
                'start_hour': start_hour,
                'pv_area': pv_area,
                'battery_capacity': 0.0,
                'total_load': total_load,
                'total_pv_generation': total_pv,
                'total_grid_import': total_grid,
                'pv_utilization': pv_only_result['metrics']['PV_utilization'],
                'grid_dependency': pv_only_result['metrics']['grid_dependency']
            }
            results['config_metrics'].append(pv_only_metrics)
            
            # Evaluate with PV and battery
            full_result = evaluate_single_config(
                pv_area=pv_area,
                battery_capacity=battery_capacity,
                schedule_file=schedule_file,
                weather_data=weather_data,
                results_dir=dirs['results'],
                city_key=city_key
            )
            
            if not full_result['success']:
                raise ValueError(f"Full system evaluation failed for start hour {start_hour}")
            
            # Add full system results
            prefix = f'h{start_hour:02d}_full_system'
            pv_generation = full_result['performance']['pv_power']
            grid_import = full_result['performance']['grid_import']
            battery_charge = np.maximum(0, full_result['performance']['battery_power'])
            battery_discharge = -np.minimum(0, full_result['performance']['battery_power'])
            
            results[f'{prefix}_pv_generation'] = pv_generation
            results[f'{prefix}_grid_import'] = grid_import
            results[f'{prefix}_battery_charge'] = battery_charge
            results[f'{prefix}_battery_discharge'] = battery_discharge
            
            # Calculate full system metrics
            total_pv = np.sum(pv_generation)
            total_grid = np.sum(grid_import)
            total_batt_charge = np.sum(battery_charge)
            total_batt_discharge = np.sum(battery_discharge)
            
            full_sys_metrics = {
                'config_label': full_sys_label,
                'description': f'PV-Battery system starting at {start_hour:02d}:00',
                'start_hour': start_hour,
                'pv_area': pv_area,
                'battery_capacity': battery_capacity,
                'total_load': total_load,
                'total_pv_generation': total_pv,
                'total_grid_import': total_grid,
                'total_battery_charge': total_batt_charge,
                'total_battery_discharge': total_batt_discharge,
                'pv_utilization': full_result['metrics']['PV_utilization'],
                'grid_dependency': full_result['metrics']['grid_dependency']
            }
            results['config_metrics'].append(full_sys_metrics)
        
        # Convert results to DataFrames
        df_timeseries = pd.DataFrame({k: v for k, v in results.items() if k not in ['config_metrics']})
        df_metrics = pd.DataFrame(results['config_metrics'])
        
        # Create filenames with city prefix
        timeseries_file = dirs['results'] / f"{city_key}_mechanism_analysis_pv_{pv_area:.1f}m2_battery_{battery_capacity:.1f}kWh_start_hour1_{start_hour1:02d}_start_hour2_{start_hour2:02d}.csv"
        metrics_file = dirs['results'] / f"{city_key}_mechanism_analysis_metrics_pv_{pv_area:.1f}m2_battery_{battery_capacity:.1f}kWh_start_hour1_{start_hour1:02d}_start_hour2_{start_hour2:02d}.csv"
        
        # Save data files
        df_timeseries.to_csv(timeseries_file, index=False)
        df_metrics.to_csv(metrics_file, index=False)
        logger.info(f"Mechanism analysis data saved to {timeseries_file} and {metrics_file}")
        
        # Create output directory for plots
        plots_dir = dirs['results'] / "mechanism_plots"
        plots_dir.mkdir(parents=True, exist_ok=True)
        
        # Generate and save plots
        analyze_mechanism_results(
            timeseries_file=timeseries_file,
            metrics_file=metrics_file,
            output_dir=plots_dir
        )
        
        # Print metrics summary
        print("\nConfiguration Metrics Summary:")
        print("=" * 80)
        for _, metrics in df_metrics.iterrows():
            print(f"\nConfiguration: {metrics['config_label']} - {metrics['description']}")
            print(f"PV Utilization: {metrics['pv_utilization']:.1f}%")
            print(f"Grid Dependency: {metrics['grid_dependency']:.1f}%")
        print("=" * 80)
        
    except Exception as e:
        logger.error(f"Error in mechanism analysis: {str(e)}")
        logger.error(traceback.format_exc())
        raise

def main():
    try:
        base_dir = Path("test_case")
        
        if RESULTS_DF_PATH.exists():
            # Create results directory
            output_dir = Path("results")
            output_dir.mkdir(parents=True, exist_ok=True)
            
            # Run analysis
            logger.info("Starting analysis...")
            #analyze_optimization_results(RESULTS_DF_PATH, output_dir)
            #analyze_power_distribution(RESULTS_DF_PATH, output_dir)
            #analyze_system_sizing(RESULTS_DF_PATH, output_dir)
            #analyze_city_climate()  # Will use default cities: shanghai, dubai, harbin
            #analyze_feasibility_distribution(RESULTS_DF_PATH, output_dir)
            #analyze_constraint_violations(RESULTS_DF_PATH, output_dir)
            #analyze_city_feasibility_distribution(RESULTS_DF_PATH, output_dir)
            #analyze_system_performance_combined(RESULTS_DF_PATH, output_dir)
            #analyze_power_distribution_combined(RESULTS_DF_PATH, output_dir)
            #analyze_system_sizing_combined(RESULTS_DF_PATH, output_dir)
            logger.info("Analysis complete. Check results directory for output plots.")
        else:
            logger.warning("No optimization results found for visualization")
        
        # Save aggregated performance data
        save_aggregated_performance_data()
            
    except Exception as e:
        logger.error(f"Fatal error: {str(e)}")
        # Save performance data even if there's an error
        save_aggregated_performance_data()
        raise

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='PV-Battery System Optimization and Evaluation Tool')
    parser.add_argument('--mode', type=str, required=True,default='optimize', choices=['optimize', 'evaluate', 'calibrate', 'analyze', 'mechanism'],
                      help='Operation mode: optimize (all cities), evaluate (single config), calibrate (step sizes), analyze (results), or mechanism (comparative analysis)')
    
    # Arguments for evaluation mode
    eval_group = parser.add_argument_group('Evaluation mode arguments')
    eval_group.add_argument('--pv-area', type=float,
                         help='PV area in m² (required for evaluate and mechanism modes)')
    eval_group.add_argument('--battery-capacity', type=float,
                         help='Battery capacity in kWh (required for evaluate and mechanism modes)')
    eval_group.add_argument('--city', type=str, choices=['shanghai', 'dubai', 'harbin'],
                         help='City key e.g., shanghai, dubai, harbin (required for evaluate, calibrate, and mechanism modes)')
    eval_group.add_argument('--start-hour', type=int, choices=range(24),
                         help='Start hour of photoperiod 0-23 (required for evaluate mode)')
    
    # Arguments for mechanism mode
    mech_group = parser.add_argument_group('Mechanism mode arguments')
    mech_group.add_argument('--start-hour1', type=int, choices=range(24),
                         help='First start hour of photoperiod 0-23 (required for mechanism mode)')
    mech_group.add_argument('--start-hour2', type=int, choices=range(24),
                         help='Second start hour of photoperiod 0-23 (required for mechanism mode)')
    
    # Arguments for calibration mode
    calib_group = parser.add_argument_group('Calibration mode arguments')
    calib_group.add_argument('--pv-max', type=float, default=500.0,
                          help='Maximum PV area in m² for calibration (default: 500)')
    calib_group.add_argument('--battery-max', type=float, default=500.0,
                          help='Maximum battery capacity in kWh for calibration (default: 500)')
    
    # Arguments for optimization mode
    opt_group = parser.add_argument_group('Optimization mode arguments')
    opt_group.add_argument('--cities', type=str, nargs='+', choices=['shanghai', 'harbin', 'haikou', 'lasa', 'urumqi'],
                        help='Cities to optimize (default: all cities)')
    
    # Arguments for analyze mode
    analyze_group = parser.add_argument_group('Analyze mode arguments')
    analyze_group.add_argument('--results-file', type=str,
                           help='Path to the optimization results CSV file (required for analyze mode)')
    
    args = parser.parse_args()
    
    try:
        base_dir = Path("test_case")
        
        if args.mode == 'analyze':
            if not args.results_file:
                parser.error("Analyze mode requires --results-file")
            
            results_file = Path(args.results_file)
            if not results_file.exists():
                raise ValueError(f"Results file not found: {results_file}")
            
            # Create results directory
            output_dir = Path("results")
            output_dir.mkdir(parents=True, exist_ok=True)
            
            try:
                # Run analysis
                logger.info("Starting analysis...")
                #analyze_optimization_results(results_file, output_dir)
                #analyze_power_distribution(results_file, output_dir)
                #analyze_system_sizing(results_file, output_dir)
                #analyze_city_climate(['shanghai', 'dubai', 'harbin'])
                #analyze_feasibility_distribution(results_file, output_dir)
                #analyze_constraint_violations(results_file, output_dir)
                #analyze_city_feasibility_distribution(results_file, output_dir)
                #analyze_system_performance_combined(results_file, output_dir)
                #analyze_power_distribution_combined(results_file, output_dir)
                #analyze_system_sizing_combined(results_file, output_dir)
                analyze_city_climate_energy(#results_file, 
                                            output_dir=output_dir)
                logger.info("Analysis complete. Check results directory for output plots.")
            except Exception as e:
                logger.error(f"Error during analysis: {str(e)}")
                raise
            
        elif args.mode == 'calibrate':
            # Validate required arguments for calibrate mode
            if not args.city:
                parser.error("Calibrate mode requires --city")
            
            from src.calibrator import StepSizeCalibrator
            
            # Initialize calibrator with specified step sizes
            calibrator = StepSizeCalibrator(
                reference_city=args.city,
                pv_max=args.pv_max,
                battery_max=args.battery_max,
                step_sizes=[0.5, 1.0, 5.0, 10.0, 15.0, 20.0, 30, 50]
            )
            
            # Run calibration
            optimal_steps = calibrator.run()
            
            # Save results to JSON
            import json
            with open(f"calibration_results/optimal_steps_{args.city}.json", 'w') as f:
                json.dump(optimal_steps, f, indent=4)
            
            logger.info("Calibration results saved to JSON file")
            
        elif args.mode == 'evaluate':
            # Validate required arguments for evaluate mode
            if not all([args.pv_area, args.battery_capacity, args.city, args.start_hour is not None]):
                parser.error("Evaluate mode requires --pv-area, --battery-capacity, --city, and --start-hour")
            
            # Setup directories
            city_dir = base_dir / args.city
            dirs = {
                'output': city_dir / 'output',
                'results': city_dir / 'results',
                'weather': city_dir / 'weather'
            }
            
            # Create directories if they don't exist
            for dir_path in dirs.values():
                dir_path.mkdir(parents=True, exist_ok=True)
            
            # Load weather data
            weather_csv = dirs['weather'] / f"{args.city}_2024.csv"
            if not weather_csv.exists():
                raise ValueError(f"Weather data not found for {args.city}")
            weather_data = pd.read_csv(weather_csv)
            
            # Find corresponding schedule file
            schedule_pattern = f"annual_energy_schedule_{args.start_hour:02d}_*.csv"
            schedule_files = list(dirs['output'].glob(schedule_pattern))
            if not schedule_files:
                raise ValueError(f"No schedule file found for start hour {args.start_hour:02d}")
            schedule_file = schedule_files[0]  # Take the first matching file
            
            logger.info(f"Using schedule file: {schedule_file.name}")
            
            # Evaluate configuration
            result = evaluate_single_config(
                pv_area=args.pv_area,
                battery_capacity=args.battery_capacity,
                schedule_file=schedule_file,
                weather_data=weather_data,
                results_dir=dirs['results'],
                city_key=args.city
            )
            
            if not result['success']:
                logger.error(f"Evaluation failed: {result.get('error', 'Unknown error')}")
                sys.exit(1)
                
        elif args.mode == 'mechanism':
            # Validate required arguments for mechanism mode
            if not all([args.pv_area, args.battery_capacity, args.city, 
                       args.start_hour1 is not None, args.start_hour2 is not None]):
                parser.error("Mechanism mode requires --pv-area, --battery-capacity, --city, --start-hour1, and --start-hour2")
            
            # Evaluate mechanism configurations
            evaluate_mechanism_configs(
                pv_area=args.pv_area,
                battery_capacity=args.battery_capacity,
                start_hour1=args.start_hour1,
                start_hour2=args.start_hour2,
                city_key=args.city,
                base_dir=base_dir
            )
            
        else:  # optimize mode
            visualization_dir = base_dir / "visualization"
            visualization_dir.mkdir(parents=True, exist_ok=True)
            
            # Use only shanghai, dubai, harbin
            chinese_cities = ['shanghai', 'harbin', 'haikou', 'lasa', 'urumqi']
            cities_to_process = args.cities if args.cities else ['jinan','haikou','zhengzhou','lasa','tianjin','hangzhou','chongqing','shanghai', 'dubai', 'harbin','beijing','urumqi','newyork','paris','saopaulo','hohhot',]
            logger.info(f"Starting optimization for cities: {', '.join(cities_to_process)}")
            
            # Process selected cities
            for city_key in cities_to_process:
                logger.info(f"\nProcessing city: {city_key}")
                process_city(city_key, base_dir)
            
            # Create visualizations
            if RESULTS_DF_PATH.exists():
                output_dir = Path("results")
                output_dir.mkdir(parents=True, exist_ok=True)
                #analyze_optimization_results(RESULTS_DF_PATH, output_dir)
                #analyze_power_distribution(RESULTS_DF_PATH, output_dir)
                #analyze_system_sizing(RESULTS_DF_PATH, output_dir)
                #analyze_city_climate()
                logger.info("Completed processing and visualization for all cities")
            else:
                logger.warning("No optimization results found for visualization")
            
            # Save aggregated performance data
            save_aggregated_performance_data()
            logger.info("Optimization complete!")
            
    except Exception as e:
        logger.error(f"Fatal error: {str(e)}")
        if args.mode == 'optimize':
            # Save performance data even if there's an error in optimization mode
            save_aggregated_performance_data()
        raise
