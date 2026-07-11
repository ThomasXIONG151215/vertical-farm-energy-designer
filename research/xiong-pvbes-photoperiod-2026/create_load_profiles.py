from pathlib import Path
import shutil
import logging
import pandas as pd
import numpy as np
import os
from eppy import modeleditor
from eppy.modeleditor import IDF
from eppy.runner.run_functions import run
from weather.city_coordinates import CITY_COORDINATES

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def find_energyplus():
    """Find EnergyPlus installation on Windows"""
    # First check environment variable
    ep_path = os.environ.get("ENERGYPLUS_EXE")
    if ep_path and os.path.exists(ep_path):
        logger.info(f"Found EnergyPlus from environment variable: {ep_path}")
        return ep_path
        
    # Check common installation paths for Windows
    possible_paths = [
        r"C:\EnergyPlusV22-1-0\EnergyPlus.exe",
        r"C:\EnergyPlusV23-1-0\EnergyPlus.exe",
        r"C:\Program Files\EnergyPlus-22-1-0\EnergyPlus.exe",
        r"C:\Program Files\EnergyPlus-23-1-0\EnergyPlus.exe",
    ]
    
    for path in possible_paths:
        if os.path.exists(path):
            logger.info(f"Found EnergyPlus at: {path}")
            return path
            
    # If not found, log an error and return None
    logger.error("EnergyPlus executable not found. Please install EnergyPlus or set ENERGYPLUS_EXE environment variable.")
    return None


def create_light_schedule(idf, schedule_name, start_hour, end_hour):
    """Update the N_Lights schedule with the specified hours"""
    # Find the existing N_Lights schedule
    n_lights = None
    for schedule in idf.idfobjects["Schedule:Day:Hourly"]:
        if schedule.Name == "N_Lights":
            n_lights = schedule
            break
    
    if n_lights is None:
        raise ValueError("N_Lights schedule not found in the IDF file")
    
    # Create hourly schedule values
    schedule_values = [0] * 24
    
    if start_hour <= end_hour:
        # Normal case (e.g., 9:00 to 17:00)
        for hour in range(start_hour, end_hour):
            schedule_values[hour] = 1
    else:
        # Schedule crosses midnight (e.g., 22:00 to 06:00)
        for hour in range(0, end_hour):
            schedule_values[hour] = 1
        for hour in range(start_hour, 24):
            schedule_values[hour] = 1
    
    # Update the hourly values in the N_Lights schedule
    for hour in range(24):
        setattr(n_lights, f"Hour_{hour+1}", schedule_values[hour])
    
    return n_lights

def make_eplaunch_options(idf, weather, output_dir):
    """Make options for EnergyPlus run"""
    idfversion = idf.idfobjects['version'][0].Version_Identifier.split('.')
    idfversion.extend([0] * (3 - len(idfversion)))
    idfversionstr = '-'.join([str(item) for item in idfversion])
    
    # Find EnergyPlus executable
    ep_exe = find_energyplus()
    
    options = {
        'ep_version': idfversionstr,
        'output_prefix': 'Template',
        'output_suffix': 'C',
        'output_directory': output_dir,
        'readvars': True,
        'expandobjects': True,
        'weather': weather
    }
    
    # Add ep_path if EnergyPlus executable was found
    #if ep_exe:
    #    options['ep_path'] = ep_exe
    
    return options

def cleanup_old_files(output_dir: Path):
    """Remove all existing schedule files to avoid confusion"""
    # Find all schedule files
    schedule_files = list(output_dir.glob("total_energy_schedule_*.csv"))
    
    # Remove all old schedule files
    for file in schedule_files:
        file.unlink()
        logger.info(f"Removed old file: {file.name}")

def generate_test_schedules(city_dir: Path):
    """
    Generate test schedules with 16-hour light-on periods starting from each hour
    using EnergyPlus simulation results
    """
    # Convert to absolute path if needed
    city_dir = Path(city_dir).absolute()
    
    # Setup paths
    project_root = Path(__file__).parent.absolute()  # Get absolute path to script directory
    idd_dir = project_root / "idd"
    idfs_dir = city_dir / "idfs"  # City-specific idfs directory
    weather_dir = city_dir / "weather"
    output_dir = city_dir / "output"
    
    logger.info(f"City directory: {city_dir}")
    logger.info(f"Project root: {project_root}")
    logger.info(f"IDD directory: {idd_dir}")
    logger.info(f"IDFs directory: {idfs_dir}")
    logger.info(f"Weather directory: {weather_dir}")
    logger.info(f"Output directory: {output_dir}")
    
    # Create idfs directory if it doesn't exist
    idfs_dir.mkdir(exist_ok=True)
    
    # Clean up old files first
    cleanup_old_files(output_dir)
    
    # Set up IDD and EPW files
    iddfile = idd_dir / "Energy+.idd"
    if not iddfile.exists():
        raise FileNotFoundError(f"IDD file not found at {iddfile}")
    
    logger.info(f"Setting IDD file: {iddfile}")
    IDF.setiddname(str(iddfile))
    
    # Use city-specific EPW file
    city_name = city_dir.name
    epwfile = weather_dir / f"{city_name}_2024.epw"
    if not epwfile.exists():
        logger.warning(f"City-specific EPW file not found at {epwfile}, using template.epw")
        epwfile = project_root / "weather" / "template.epw"
        if not epwfile.exists():
            raise FileNotFoundError(f"Template weather file not found at {epwfile}")
    
    logger.info(f"Using weather file: {epwfile}")
    
    # Check if base IDF file exists
    base_idf_path = project_root / "idfs" / "light_schedule_24.idf"
    if not base_idf_path.exists():
        raise FileNotFoundError(f"Base IDF file not found at {base_idf_path}")
    
    logger.info(f"Using base IDF file: {base_idf_path}")
    
    # Load seasonal COP values
    seasonal_cop_file = Path("load_analysis/seasonal_cop_values.csv")
    if seasonal_cop_file.exists():
        logger.info(f"Loading seasonal COP values from {seasonal_cop_file}")
        seasonal_cop_values = pd.read_csv(seasonal_cop_file)
        seasonal_cop_dict = dict(zip(seasonal_cop_values['season'], seasonal_cop_values['mean_cop']))
        logger.info(f"Seasonal COP values: {seasonal_cop_dict}")
    else:
        logger.warning(f"Seasonal COP values file not found at {seasonal_cop_file}, using default values")
        seasonal_cop_dict = {
            'spring': 3.85,
            'summer': 2.73,
            'fall': 2.57,
            'winter': 3.94
        }
    
    # Function to determine season based on month
    def get_season(month):
        if 3 <= month <= 5:
            return 'spring'
        elif 6 <= month <= 8:
            return 'summer'
        elif 9 <= month <= 11:
            return 'fall'
        else:  # month == 12 or month <= 2
            return 'winter'
    
    # Generate schedules for each starting hour
    start_hours = list(range(24))
    end_hours = [(start + 16) % 24 if start != 0 else 24 for start in start_hours]
    results_list = []
    
    # Loop through each variant
    for start_hour, end_hour in zip(start_hours, end_hours):
        logger.info(f"Creating schedule: start={start_hour}, end={end_hour}")
        
        # Create a new IDF object for each variant
        try:
            idf_variant = IDF(str(base_idf_path), str(epwfile))
            
            # Update the N_Lights schedule
            create_light_schedule(idf_variant, f"LIGHT_SCHEDULE_{start_hour:02d}", start_hour, end_hour)
            
            # Save the IDF variant in city-specific idfs directory
            variant_path = idfs_dir / f"{city_name}_light_schedule_{start_hour:02d}.idf"
            idf_variant.saveas(str(variant_path))
            logger.info(f"Saved variant IDF to: {variant_path}")
            
            # Run the simulation with options including EnergyPlus path
            run_options = make_eplaunch_options(idf_variant, str(epwfile), str(output_dir))
            logger.info(f"Running simulation with options: {run_options}")
            run(idf_variant, **run_options)
            
            # Read results
            meter_file = output_dir / "TemplateMeter.csv"
            if not meter_file.exists():
                logger.error(f"Meter file not found at {meter_file}")
                continue
                
            logger.info(f"Reading results from {meter_file}")
            results = pd.read_csv(meter_file)
            results_list.append(results)
            
            # Save a copy of TemplateMeter with schedule info
            schedule_meter_file = output_dir / f"TemplateMeter_schedule_{start_hour:02d}_{end_hour:02d}.csv"
            results.to_csv(schedule_meter_file, index=False)
            
            # Convert meter time to datetime, handling the space at the start and 24:00:00
            results['Date/Time'] = results['Date/Time'].str.strip()
            results['Date/Time'] = results['Date/Time'].replace(' 24:00:00$', ' 00:00:00', regex=True)
            results['time'] = pd.to_datetime('2024-' + results['Date/Time'], format='%Y-%m/%d  %H:%M:%S')
            
            # Adjust any midnight times to next day
            midnight_mask = results['Date/Time'].str.contains(' 00:00:00$')
            results.loc[midnight_mask, 'time'] = results.loc[midnight_mask, 'time'] + pd.Timedelta(days=1)
            
            # Read and process weather data
            weather_data = pd.read_csv(weather_dir / f"{city_name}_2024.csv")
            weather_data['time'] = pd.to_datetime(weather_data['time'])
            
            # Merge weather data with results based on time
            merged_data = pd.merge(results, weather_data[['time', 'temperature_2m']], 
                                 on='time', how='left')
            
            # Determine season for each timestamp and assign corresponding COP
            results['month'] = results['time'].dt.month
            results['season'] = results['month'].apply(get_season)
            results['COP'] = results['season'].map(seasonal_cop_dict)
            
            # Log the seasonal distribution
            season_counts = results['season'].value_counts()
            logger.info(f"Season distribution: {season_counts.to_dict()}")
            
            # Calculate total energy with seasonal COP
            total_energy = pd.DataFrame({
                'time': results['time'],
                'Power (kWh)': (
                    results['InteriorEquipment:Electricity [J](Hourly) ']/3600000 +
                    results['InteriorLights:Electricity [J](Hourly)']/3600000 +
                    results['DistrictCooling:HVAC [J](Hourly)']/3600000/results['COP'] +
                    results['DistrictHeating:HVAC [J](Hourly)']/3600000/results['COP']
                ),
                'HVAC_kW': (
                    results['DistrictCooling:HVAC [J](Hourly)']/3600000/results['COP'] +
                    results['DistrictHeating:HVAC [J](Hourly)']/3600000/results['COP']
                ),
                'Other_kW': (
                    results['InteriorEquipment:Electricity [J](Hourly) ']/3600000 +
                    results['InteriorLights:Electricity [J](Hourly)']/3600000
                )
            })
            
            # Set time as index and save
            total_energy.set_index('time', inplace=True)
            
            # Save the total energy curve with annual indicator
            energy_file = output_dir / f"annual_energy_schedule_{start_hour:02d}_{end_hour:02d}.csv"
            total_energy.to_csv(energy_file)
            logger.info(f"Generated schedule: annual_energy_schedule_{start_hour:02d}_{end_hour:02d}.csv")
            
            # Also save a version with season information for reference
            seasonal_energy = pd.DataFrame({
                'time': results['time'],
                'season': results['season'],
                'COP': results['COP'],
                'Power (kWh)': (
                    results['InteriorEquipment:Electricity [J](Hourly) ']/3600000 +
                    results['InteriorLights:Electricity [J](Hourly)']/3600000 +
                    results['DistrictCooling:HVAC [J](Hourly)']/3600000/results['COP'] +
                    results['DistrictHeating:HVAC [J](Hourly)']/3600000/results['COP']
                )
            })
            seasonal_energy_file = output_dir / f"seasonal_energy_schedule_{start_hour:02d}_{end_hour:02d}.csv"
            seasonal_energy.to_csv(seasonal_energy_file, index=False)
            logger.info(f"Generated seasonal reference: seasonal_energy_schedule_{start_hour:02d}_{end_hour:02d}.csv")
            
        except Exception as e:
            logger.error(f"Error creating schedule: {str(e)}")
            continue

def create_test_structure():
    """Create test case directory structure and generate schedules"""
    project_root = Path(__file__).parent.absolute()
    base_dir = project_root / "test_case"
    base_dir.mkdir(exist_ok=True)
    
    logger.info(f"Creating test case structure in {base_dir}")
    
    # Create weather directory
    weather_dir = base_dir / "weather"
    weather_dir.mkdir(exist_ok=True)
    
    # Check if EnergyPlus executable exists
    ep_exe = find_energyplus()
    if not ep_exe:
        logger.error("EnergyPlus executable not found. Make sure EnergyPlus is installed.")
        logger.error("You can set the ENERGYPLUS_EXE environment variable to the path of the executable.")
        raise FileNotFoundError("EnergyPlus executable not found")
    
    # Get base IDF file
    base_idf = project_root / "idfs" / "light_schedule_24.idf"
    if not base_idf.exists():
        logger.error(f"Base IDF file not found at {base_idf}")
        raise FileNotFoundError(f"Base IDF file not found at {base_idf}")
    
    logger.info(f"Using base IDF file: {base_idf}")
    
    # Process each city
    for city_key in CITY_COORDINATES.keys():
        try:
            logger.info(f"Processing city: {city_key}")
            
            # Create city directories
            city_dir = base_dir / city_key
            city_dir.mkdir(exist_ok=True)
            
            output_dir = city_dir / "output"
            results_dir = city_dir / "results"
            weather_dir = city_dir / "weather"
            idfs_dir = city_dir / "idfs"
            
            # Create all required directories
            output_dir.mkdir(exist_ok=True)
            results_dir.mkdir(exist_ok=True)
            weather_dir.mkdir(exist_ok=True)
            idfs_dir.mkdir(exist_ok=True)
            
            # Generate schedules for this city
            generate_test_schedules(city_dir)
            
        except Exception as e:
            logger.error(f"Error processing city {city_key}: {str(e)}")
            logger.error("Continuing with next city...")
            continue

def validate_single_model(idf_path: str, epw_path: str, output_prefix: str = "default"):
    """
    Validate a single IDF model and generate energy profiles
    
    Args:
        idf_path (str): Path to the IDF file to validate
        epw_path (str): Path to the EPW weather file
        output_prefix (str): Prefix for output files
    """
    logger.info(f"Running validation mode for {idf_path}")
    
    # Setup paths
    project_root = Path(__file__).parent.absolute()
    idd_dir = project_root / "idd"
    base_output_dir = project_root / "ep_model_validations"
    output_dir = base_output_dir / output_prefix
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Convert input paths to absolute paths if they're not already
    idf_path = Path(idf_path).absolute()
    epw_path = Path(epw_path).absolute()
    
    logger.info(f"Using absolute paths:")
    logger.info(f"  IDF: {idf_path}")
    logger.info(f"  EPW: {epw_path}")
    logger.info(f"  Output: {output_dir}")
    
    # Check if files exist
    if not idf_path.exists():
        raise FileNotFoundError(f"IDF file not found: {idf_path}")
    if not epw_path.exists():
        raise FileNotFoundError(f"EPW file not found: {epw_path}")
    
    # Check if EnergyPlus executable exists
    ep_exe = find_energyplus()
    if not ep_exe:
        logger.error("EnergyPlus executable not found. Make sure EnergyPlus is installed.")
        logger.error("You can set the ENERGYPLUS_EXE environment variable to the path of the executable.")
        raise FileNotFoundError("EnergyPlus executable not found")
    
    # Set up IDD file
    iddfile = idd_dir / "Energy+.idd"
    if not iddfile.exists():
        raise FileNotFoundError(f"IDD file not found: {iddfile}")
    
    logger.info(f"Setting IDD file: {iddfile}")
    IDF.setiddname(str(iddfile))
    
    # Load seasonal COP values
    seasonal_cop_file = project_root / "load_analysis" / "seasonal_cop_values.csv"
    if seasonal_cop_file.exists():
        logger.info(f"Loading seasonal COP values from {seasonal_cop_file}")
        seasonal_cop_values = pd.read_csv(seasonal_cop_file)
        seasonal_cop_dict = dict(zip(seasonal_cop_values['season'], seasonal_cop_values['mean_cop']))
        logger.info(f"Seasonal COP values: {seasonal_cop_dict}")
    else:
        logger.warning(f"Seasonal COP values file not found at {seasonal_cop_file}, using default values")
        seasonal_cop_dict = {
            'spring': 3.85,
            'summer': 2.73,
            'fall': 2.57,
            'winter': 3.94
        }
    
    # Function to determine season based on month
    def get_season(month):
        if 3 <= month <= 5:
            return 'spring'
        elif 6 <= month <= 8:
            return 'summer'
        elif 9 <= month <= 11:
            return 'fall'
        else:  # month == 12 or month <= 2
            return 'winter'
    
    try:
        # Create IDF object
        logger.info(f"Creating IDF object")
        idf = IDF(str(idf_path), str(epw_path))
        
        # Run the simulation with options including EnergyPlus path
        run_options = make_eplaunch_options(idf, str(epw_path), str(output_dir))
        logger.info(f"Running simulation with options: {run_options}")
        run(idf, **run_options)
        
        # Read results
        meter_file = output_dir / "TemplateMeter.csv"
        if not meter_file.exists():
            raise FileNotFoundError(f"Expected meter file not found: {meter_file}")
            
        logger.info(f"Reading results from {meter_file}")
        results = pd.read_csv(meter_file)
        
        # Process timestamp
        results['Date/Time'] = results['Date/Time'].str.strip()
        results['Date/Time'] = results['Date/Time'].replace(' 24:00:00$', ' 00:00:00', regex=True)
        results['time'] = pd.to_datetime('2024-' + results['Date/Time'], format='%Y-%m/%d  %H:%M:%S')
        
        # Adjust midnight times to next day
        midnight_mask = results['Date/Time'].str.contains(' 00:00:00$')
        results.loc[midnight_mask, 'time'] = results.loc[midnight_mask, 'time'] + pd.Timedelta(days=1)
        
        # Create DataFrame with original EnergyPlus values (in kWh)
        original_energy = pd.DataFrame({
            'time': results['time'],
            'Interior_Equipment_kWh': results['InteriorEquipment:Electricity [J](Hourly) '] / 3600000,
            'Interior_Lights_kWh': results['InteriorLights:Electricity [J](Hourly)'] / 3600000,
            'District_Cooling_kWh': results['DistrictCooling:HVAC [J](Hourly)'] / 3600000,
            'District_Heating_kWh': results['DistrictHeating:HVAC [J](Hourly)'] / 3600000
        })
        
        # Calculate original totals
        original_energy['Total_HVAC_kWh'] = (
            original_energy['District_Cooling_kWh'] + 
            original_energy['District_Heating_kWh']
        )
        original_energy['Total_Other_kWh'] = (
            original_energy['Interior_Equipment_kWh'] + 
            original_energy['Interior_Lights_kWh']
        )
        original_energy['Total_Energy_kWh'] = (
            original_energy['Total_HVAC_kWh'] + 
            original_energy['Total_Other_kWh']
        )
        
        # Save original energy data
        original_energy.set_index('time', inplace=True)
        original_file = output_dir / f"{output_prefix}_original_energy_profile.csv"
        original_energy.to_csv(original_file)
        logger.info(f"Generated original energy profile: {original_file}")
        
        # Process with seasonal COP
        results['month'] = results['time'].dt.month
        results['season'] = results['month'].apply(get_season)
        results['COP'] = 4  # Fixed COP value
        
        # Calculate total energy with seasonal COP
        converted_energy = pd.DataFrame({
            'time': results['time'],
            'Power_kWh': (
                results['InteriorEquipment:Electricity [J](Hourly) ']/3600000 +
                results['InteriorLights:Electricity [J](Hourly)']/3600000 +
                results['DistrictCooling:HVAC [J](Hourly)']/3600000/results['COP'] +
                results['DistrictHeating:HVAC [J](Hourly)']/3600000/results['COP']
            ),
            'HVAC_kWh': (
                results['DistrictCooling:HVAC [J](Hourly)']/3600000/results['COP'] +
                results['DistrictHeating:HVAC [J](Hourly)']/3600000/results['COP']
            ),
            'Other_kWh': (
                results['InteriorEquipment:Electricity [J](Hourly) ']/3600000 +
                results['InteriorLights:Electricity [J](Hourly)']/3600000
            ),
            'COP': results['COP'],
            'Season': results['season']
        })
        
        # Save converted energy data
        converted_energy.set_index('time', inplace=True)
        converted_file = output_dir / f"{output_prefix}_converted_energy_profile.csv"
        converted_energy.to_csv(converted_file)
        logger.info(f"Generated converted energy profile: {converted_file}")
        
        # Extract summer data (August 20 to September 5)
        summer_mask = (
            (original_energy.index.month == 8) & (original_energy.index.day >= 20) |
            (original_energy.index.month == 9) & (original_energy.index.day <= 5)
        )
        
        # Save summer profiles
        summer_original = original_energy[summer_mask].copy()
        summer_original_file = output_dir / f"{output_prefix}_summer_original_profile.csv"
        summer_original.to_csv(summer_original_file)
        logger.info(f"Generated summer original profile: {summer_original_file}")
        
        summer_converted = converted_energy[summer_mask].copy()
        summer_converted_file = output_dir / f"{output_prefix}_summer_converted_profile.csv"
        summer_converted.to_csv(summer_converted_file)
        logger.info(f"Generated summer converted profile: {summer_converted_file}")
        
        # Create comprehensive results summary for both annual and summer periods
        results_summary = {
            # Annual original values
            'Annual_Original_Total_Energy_kWh': original_energy['Total_Energy_kWh'].sum(),
            'Annual_Original_HVAC_Energy_kWh': original_energy['Total_HVAC_kWh'].sum(),
            'Annual_Original_Other_Energy_kWh': original_energy['Total_Other_kWh'].sum(),
            'Annual_Original_Cooling_Energy_kWh': original_energy['District_Cooling_kWh'].sum(),
            'Annual_Original_Heating_Energy_kWh': original_energy['District_Heating_kWh'].sum(),
            'Annual_Original_Equipment_Energy_kWh': original_energy['Interior_Equipment_kWh'].sum(),
            'Annual_Original_Lighting_Energy_kWh': original_energy['Interior_Lights_kWh'].sum(),
            'Annual_Original_Peak_Load_kWh': original_energy['Total_Energy_kWh'].max(),
            'Annual_Original_Peak_Load_Time': original_energy['Total_Energy_kWh'].idxmax(),
            
            # Annual converted values
            'Annual_Converted_Total_Energy_kWh': converted_energy['Power_kWh'].sum(),
            'Annual_Converted_HVAC_Energy_kWh': converted_energy['HVAC_kWh'].sum(),
            'Annual_Converted_Other_Energy_kWh': converted_energy['Other_kWh'].sum(),
            'Annual_Converted_Peak_Load_kWh': converted_energy['Power_kWh'].max(),
            'Annual_Converted_Peak_Load_Time': converted_energy['Power_kWh'].idxmax(),
            'Annual_Average_COP': converted_energy['COP'].mean(),
            
            # Summer original values
            'Summer_Original_Total_Energy_kWh': summer_original['Total_Energy_kWh'].sum(),
            'Summer_Original_HVAC_Energy_kWh': summer_original['Total_HVAC_kWh'].sum(),
            'Summer_Original_Other_Energy_kWh': summer_original['Total_Other_kWh'].sum(),
            'Summer_Original_Cooling_Energy_kWh': summer_original['District_Cooling_kWh'].sum(),
            'Summer_Original_Heating_Energy_kWh': summer_original['District_Heating_kWh'].sum(),
            'Summer_Original_Equipment_Energy_kWh': summer_original['Interior_Equipment_kWh'].sum(),
            'Summer_Original_Lighting_Energy_kWh': summer_original['Interior_Lights_kWh'].sum(),
            'Summer_Original_Peak_Load_kWh': summer_original['Total_Energy_kWh'].max(),
            'Summer_Original_Peak_Load_Time': summer_original['Total_Energy_kWh'].idxmax(),
            
            # Summer converted values
            'Summer_Converted_Total_Energy_kWh': summer_converted['Power_kWh'].sum(),
            'Summer_Converted_HVAC_Energy_kWh': summer_converted['HVAC_kWh'].sum(),
            'Summer_Converted_Other_Energy_kWh': summer_converted['Other_kWh'].sum(),
            'Summer_Converted_Peak_Load_kWh': summer_converted['Power_kWh'].max(),
            'Summer_Converted_Peak_Load_Time': summer_converted['Power_kWh'].idxmax(),
            'Summer_Average_COP': summer_converted['COP'].mean()
        }
        
        # Save results summary
        results_summary_df = pd.DataFrame([results_summary])
        results_summary_file = output_dir / f"{output_prefix}_energy_summary.csv"
        results_summary_df.to_csv(results_summary_file, index=False)
        logger.info(f"Generated energy summary: {results_summary_file}")
        
    except Exception as e:
        logger.error(f"Error in validation mode: {str(e)}")
        raise

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Generate or validate energy load profiles')
    parser.add_argument('--mode', type=str, choices=['generate', 'validate'], default='generate',
                      help='Operation mode: generate test schedules or validate single model')
    parser.add_argument('--idf', type=str, help='Path to IDF file (required for validate mode)')
    parser.add_argument('--epw', type=str, help='Path to EPW file (required for validate mode)')
    parser.add_argument('--output_prefix', type=str, default='default',
                      help='Prefix for output files (default: "default")')
    
    args = parser.parse_args()
    
    if args.mode == 'generate':
        create_test_structure()
    elif args.mode == 'validate':
        if not args.idf or not args.epw:
            parser.error("validate mode requires both --idf and --epw arguments")
        validate_single_model(args.idf, args.epw, args.output_prefix) 