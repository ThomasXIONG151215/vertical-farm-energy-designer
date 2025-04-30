import os
import sys
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from pathlib import Path
import logging
import argparse
import traceback
import plotly.express as px
from plotly.subplots import make_subplots
from src.visualization import PlotStyler
import glob

logger = logging.getLogger(__name__)

# 城市显示名称映射
CITY_DISPLAY_NAMES = {
    'shanghai': 'Shanghai',
    'beijing': 'Beijing',
    'harbin': 'Harbin',
    'lasa': 'Lasa',
    'urumqi': 'Urumqi',
    'haikou': 'Haikou',
    'jinan': 'Jinan',     # 为完整性提供，虽然会被过滤
    'zhengzhou': 'Zhengzhou'  # 为完整性提供，虽然会被过滤
}

# 需要分析的城市列表
CITIES_TO_ANALYZE = ['shanghai', 'harbin', 'haikou', 'lasa', 'urumqi']

# Standard display order for cities on x-axis (displayed names)
STANDARD_CITY_DISPLAY_ORDER = ['Shanghai', 'Harbin', 'Lasa', 'Urumqi', 'Haikou']

def merge_enumeration_results():
    """Merge all enumeration results from different cities and start hours into a single DataFrame."""
    global MERGED_RESULTS_DF
    
    try:
        all_dfs = []
        base_path = Path("G:/PVBES_Design/results/enumerations3")
        
        # Pattern for finding all relevant CSV files
        pattern = "enumeration_results_*_100_percent_grid_connected_start*_step10_5_max200.0_100.0.csv"
        
        # Find all matching files
        for file_path in base_path.glob(pattern):
            try:
                # Extract city and start hour from filename
                filename = file_path.name
                city = filename.split('_')[2]  # Extract city name
                start_hour = int(filename.split('start')[1].split('_')[0])  # Extract start hour
                
                # Read the CSV file
                df = pd.read_csv(file_path)
                
                # Add city and start_hour columns if they don't exist
                if 'city' not in df.columns:
                    df['city'] = city
                if 'start_hour' not in df.columns:
                    df['start_hour'] = start_hour
                
                all_dfs.append(df)
                logger.info(f"Loaded results for {city} with start hour {start_hour}")
                
            except Exception as e:
                logger.error(f"Error processing file {file_path}: {str(e)}")
                continue
        
        if not all_dfs:
            raise ValueError("No enumeration result files found")
        
        # Merge all DataFrames
        MERGED_RESULTS_DF = pd.concat(all_dfs, ignore_index=True)
        
        # Filter out Jinan and Zhengzhou
        MERGED_RESULTS_DF = MERGED_RESULTS_DF[~MERGED_RESULTS_DF['city'].isin(['jinan', 'zhengzhou'])]
        
        logger.info(f"Successfully merged {len(all_dfs)} result files. Total rows: {len(MERGED_RESULTS_DF)}")
        return MERGED_RESULTS_DF
        
    except Exception as e:
        logger.error(f"Error merging enumeration results: {str(e)}")
        logger.error(traceback.format_exc())
        raise

def standardize_city_name(city: str) -> str:
    """Standardize city name to proper case with specific rules."""
    special_cases = {
        'urumqi': 'Urumqi',
        'lasa': 'Lasa',
        'shanghai': 'Shanghai',
        'beijing': 'Beijing',
        'harbin': 'Harbin',
        'haikou': 'Haikou',
        'jinan': 'Jinan',
        'zhengzhou': 'Zhengzhou'
    }
    return special_cases.get(city.lower(), city.title())

def create_radiation_plot(city_data: dict, output_dir: Path) -> None:
    """Create and save Plot Climates-A: Daily Average Solar Radiation
    
    This function reads daily radiation data from radiation_data.csv and plots it for each city
    
    备注: climate-A - showing average daily solar radiation in each city
    """
    try:
        # Create output directory if it doesn't exist
        climate_dir = output_dir / "city_climate_energy"
        climate_dir.mkdir(parents=True, exist_ok=True)
        
        # Read the radiation data directly from CSV
        radiation_file = climate_dir / "radiation_data.csv"
        
        if not radiation_file.exists():
            # If file doesn't exist in the output directory, try the source file
            radiation_file = Path("results/city_climate_energy/radiation_data.csv")
            if not radiation_file.exists():
                logger.error(f"Radiation data file not found: {radiation_file}")
                return
        
        # Read radiation data
        logger.info(f"Reading radiation data from {radiation_file}")
        df = pd.read_csv(radiation_file)
        
        # Reorder based on STANDARD_CITY_DISPLAY_ORDER
        ordered_cities = [city for city in STANDARD_CITY_DISPLAY_ORDER if city in df['City'].values]
        df = df[df['City'].isin(ordered_cities)]
        df['City_Order'] = df['City'].map({city: i for i, city in enumerate(STANDARD_CITY_DISPLAY_ORDER)})
        df = df.sort_values('City_Order')
        
        # Create plot
        fig = go.Figure()
        fig.add_trace(go.Bar(
            name='Average Daily Radiation',
            x=df['City'],
            y=df['Mean_Radiation'],
            #marker_color=PlotStyler.COLORS[0],
            #text=[f"{rad:.2f}" for rad in df['Mean_Radiation']],
            #textposition='outside'
        ))
        
        # Get max y value and add 10% margin
        y_max = max(df['Mean_Radiation']) * 1.1
        
        # Apply styling with PlotStyler
        fig = PlotStyler.style_single_plot(
            fig,
            title="(a) Daily Average Solar Radiation",
            y_label="Solar Radiation (kWh/m²/day)"
        )
        
        # Update layout
        fig.update_layout(
            yaxis=dict(range=[0, y_max])
        )
        
        # Save plot
        PlotStyler.save_plot(fig, "Climates_A_daily_radiation.png", climate_dir)
        logger.info("Saved daily average solar radiation plot")
        
    except Exception as e:
        logger.error(f"Error creating daily radiation plot: {str(e)}")
        logger.error(traceback.format_exc())

def create_temperature_plot(city_data: dict, output_dir: Path) -> None:
    """Create and save Plot Climates-B: Daily Average Temperature with Standard Deviation
    
    备注: climate-B
    """
    # Prepare data
    data_dict = {'City': [], 'Mean_Temperature': [], 'Std_Temperature': []}
    
    for city, data in city_data.items():
        if 'daily_temperature' in data:
            city_name = standardize_city_name(city)
            mean_temp = data['daily_temperature'].mean()
            std_temp = data['daily_temperature'].std()
            data_dict['City'].append(city_name)
            data_dict['Mean_Temperature'].append(mean_temp)
            data_dict['Std_Temperature'].append(std_temp)
    
    # Save data to CSV
    df = pd.DataFrame(data_dict)
    df.to_csv(output_dir / "city_climate_energy" / "temperature_data.csv", index=False)
    
    # Reorder based on STANDARD_CITY_DISPLAY_ORDER
    # Filter to only include cities in our data and preserve the standard order
    ordered_cities = [city for city in STANDARD_CITY_DISPLAY_ORDER if city in df['City'].values]
    df = df[df['City'].isin(ordered_cities)]
    df['City_Order'] = df['City'].map({city: i for i, city in enumerate(STANDARD_CITY_DISPLAY_ORDER)})
    df = df.sort_values('City_Order')
    
    # Create plot
    fig = go.Figure()
    fig.add_trace(go.Bar(
        name='Temperature',
        x=df['City'],
        y=df['Mean_Temperature'],
        error_y=dict(
            type='data',
            array=df['Std_Temperature'],
            color=PlotStyler.ERROR_BAR_COLOR,
            thickness=2,
            width=6
        ),
        marker_color=PlotStyler.COLORS[1],
        #text=[f"{mean:.1f}±{std:.1f}" for mean, std in zip(data_dict['Mean_Temperature'], data_dict['Std_Temperature'])],
       # textposition='outside'
    ))
    
    fig.update_layout(
        title=None,
        xaxis_title="Cities",
        yaxis_title="Daily Average Temperature (°C)",
        showlegend=False,
        #plot_bgcolor='white',
        #width=800,
       # height=500,
        xaxis=dict(showgrid=False),
        yaxis=dict(showgrid=False)
    )
    
    fig = PlotStyler.style_single_plot(
        fig,
        title="(b) Daily Average Temperature",
        y_label="Temperature (°C)"
    )
    PlotStyler.save_plot(fig, "Climates_B_temperature_analysis.png", output_dir / "city_climate_energy")
    logger.info("Saved temperature analysis plot and data")

def create_hvac_schedule_plot(city_data: dict, output_dir: Path) -> None:
    """Create and save Plot Climates-C: HVAC Energy by City with Schedule Variation
    
    备注: climate-C - Shows HVAC daily energy consumption with standard deviation between different photoperiod start hours
    """
    try:
        # Dictionary to store results
        results = {
            'City': [],
            'Start_Hour': [],
            'HVAC_Energy': []
        }
        
        # Process load profiles for each city and different photoperiod start hours
        for city in CITIES_TO_ANALYZE:
            logger.info(f"Processing HVAC data for {city}...")
            city_display_name = CITY_DISPLAY_NAMES[city]
            
            # Process each photoperiod start hour (1-23)
            for start_hour in range(1, 24):
                # Calculate end hour (start hour + 16) with wraparound
                end_hour = (start_hour + 16) % 24
                
                # Format the hours for filename
                start_hour_str = f"{start_hour:02d}"
                end_hour_str = f"{end_hour:02d}"
                
                # Construct file path
                file_path = Path(f"test_case/{city}/output/annual_energy_schedule_{start_hour_str}_{end_hour_str}.csv")
                
                # Check if file exists
                if not file_path.exists():
                    logger.warning(f"File not found for {city} with start hour {start_hour}: {file_path}")
                    continue
                
                # Read the CSV file
                df = pd.read_csv(file_path)
                
                # Convert time column to datetime
                df['time'] = pd.to_datetime(df['time'])
                
                # Create a date column
                df['date'] = df['time'].dt.date
                
                # Calculate daily energy by summing hourly HVAC_kW values for each day
                daily_hvac = df.groupby('date')['HVAC_kW'].sum()
                
                # Calculate the mean of daily sums
                daily_mean = daily_hvac.mean()
                
                # Add to results
                results['City'].append(city_display_name)
                results['Start_Hour'].append(start_hour)
                results['HVAC_Energy'].append(daily_mean)
        
        # Create detailed DataFrame
        detailed_df = pd.DataFrame(results)
        
        # Calculate statistics for each city
        city_stats = detailed_df.groupby('City').agg({
            'HVAC_Energy': ['mean', 'std', 'min', 'max']
        }).reset_index()
        
        # Flatten the multi-level column index
        city_stats.columns = ['City', 'Mean_HVAC_Energy', 'Std_HVAC_Energy', 'Min_HVAC_Energy', 'Max_HVAC_Energy']
        
        # Order cities according to standard display order
        # Filter to only include cities in our data and preserve the standard order
        ordered_cities = [city for city in STANDARD_CITY_DISPLAY_ORDER if city in city_stats['City'].values]
        city_stats = city_stats[city_stats['City'].isin(ordered_cities)]
        city_stats['City_Order'] = city_stats['City'].map({city: i for i, city in enumerate(STANDARD_CITY_DISPLAY_ORDER)})
        city_stats = city_stats.sort_values('City_Order')
        
        # Save data to CSV for future reference
        output_dir = Path(output_dir)
        climate_dir = output_dir / "city_climate_energy"
        climate_dir.mkdir(parents=True, exist_ok=True)
        
        city_stats.to_csv(climate_dir / "hvac_schedule_data.csv", index=False)
        detailed_df.to_csv(climate_dir / "Climates_C_hvac_schedule_data.csv", index=False)
        
        # Create plot
        fig = go.Figure()
        
        # Add bar chart with error bars
        fig.add_trace(go.Bar(
            x=city_stats['City'],
            y=city_stats['Mean_HVAC_Energy'],
            name='Daily HVAC Energy',
            marker_color=PlotStyler.COLORS[2],
            error_y=dict(
                type='data',
                array=city_stats['Std_HVAC_Energy'],
                visible=True,
                color=PlotStyler.ERROR_BAR_COLOR,
                thickness=2,
                width=6
            ),
            hovertemplate="<br>".join([
                "City: %{x}",
                "HVAC Energy: %{y:.2f} kWh",
                "<extra></extra>"
            ])
        ))
        
        # Style the plot
        fig = PlotStyler.style_single_plot(
            fig,
            title="(c) Daily HVAC Energy by City",
            x_label="City",
            y_label="Daily HVAC Energy (kWh)"
        )
        
        # Update layout
        fig.update_layout(
            barmode='group',
            bargap=0.15,
            bargroupgap=0.1,
        )
        
        # Save plot
        PlotStyler.save_plot(fig, "Climates_C_hvac_schedule_analysis.png", climate_dir)
        logger.info("Saved HVAC schedule analysis plot and data")
        
        # Also create a plot showing HVAC energy vs start hour for each city
        create_hvac_start_hour_plot(detailed_df, climate_dir)
        
    except Exception as e:
        logger.error(f"Error creating HVAC schedule plot: {str(e)}")
        logger.error(traceback.format_exc())

def create_hvac_start_hour_plot(detailed_df: pd.DataFrame, output_dir: Path) -> None:
    """Create a plot showing HVAC energy vs photoperiod start hour for each city.
    
    Args:
        detailed_df: DataFrame with detailed HVAC data by city and start hour
        output_dir: Directory to save the output plot
    """
    try:
        # Create figure
        fig = go.Figure()
        
        # Add a line trace for each city
        for i, city in enumerate(STANDARD_CITY_DISPLAY_ORDER):
            city_data = detailed_df[detailed_df['City'] == city]
            
            if city_data.empty:
                continue
                
            # Sort by start hour
            city_data = city_data.sort_values('Start_Hour')
            
            # Add trace
            fig.add_trace(go.Scatter(
                x=city_data['Start_Hour'],
                y=city_data['HVAC_Energy'],
                mode='lines+markers',
                name=city,
                line=dict(
                    color=PlotStyler.COLORS[i % len(PlotStyler.COLORS)],
                    width=2
                ),
                marker=dict(size=8),
                hovertemplate="<br>".join([
                    "City: %{fullData.name}",
                    "Start Hour: %{x}:00",
                    "HVAC Energy: %{y:.2f} kWh",
                    "<extra></extra>"
                ])
            ))
        
        # Style the plot
        fig = PlotStyler.style_single_plot(
            fig,
            title="Daily HVAC Energy vs Photoperiod Start Hour",
            x_label="Photoperiod Start Hour",
            y_label="Daily HVAC Energy (kWh)"
        )
        
        # Update x-axis to show every hour
        fig.update_xaxes(
            tickmode='linear',
            tick0=1,
            dtick=2
        )
        
        # Update layout
        fig.update_layout(
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                x=1
            )
        )
        
        # Save plot
        PlotStyler.save_plot(fig, "Climates_C_hvac_vs_start_hour.png", output_dir)
        logger.info("Saved HVAC vs start hour plot")
        
    except Exception as e:
        logger.error(f"Error creating HVAC vs start hour plot: {str(e)}")
        logger.error(traceback.format_exc())

def create_correlation_plot(cities_data: dict, output_dir: Path) -> None:
    """Create and save climates-D: 2D plot with line plots of solar radiation for each city
    across 6 time periods (0-4, 4-8, 8-12, 12-16, 16-20, 20-24)
    
    备注: climates-D - 2D plot showing average solar radiation for each city (lines)
    across different time periods of the day (x-axis)
    """
    try:
        # Create directories if they don't exist
        (output_dir / "city_climate_energy").mkdir(parents=True, exist_ok=True)
        
        # Define 6 time periods (4 hours each)
        time_periods = ["0-4", "4-8", "8-12", 
                        "12-16", "16-20", "20-24"]
        
        # Dictionary to store radiation data for each city and time period
        city_radiation_data = {}
        
        # Process data for each city
        for city, _ in cities_data.items():
            # Load city weather data from the appropriate file
            weather_file = Path(f"G:/PVBES_Design/test_case/{city}/weather/{city}_2024.csv")
            if not weather_file.exists():
                logger.warning(f"Weather file not found for {city}: {weather_file}")
                # Fall back to test for alternate paths
                weather_file = Path(f"/g/PVBES_Design/test_case/{city}/weather/{city}_2024.csv")
                if not weather_file.exists():
                    # Try relative path
                    weather_file = Path(f"test_case/{city}/weather/{city}_2024.csv")
                    if not weather_file.exists():
                        logger.warning(f"Could not find weather data for {city}")
                        continue
            
            # Read weather data
            try:
                weather_data = pd.read_csv(weather_file)
                logger.info(f"Loaded weather data for {city}: {len(weather_data)} rows")
            except Exception as e:
                logger.error(f"Error reading weather file for {city}: {str(e)}")
                continue
            
            # Check for radiation columns
            rad_col = None
            
            # Try to find appropriate column for radiation
            if 'direct_radiation' in weather_data.columns and 'diffuse_radiation' in weather_data.columns:
                # Calculate total radiation if components are available
                weather_data['total_radiation'] = weather_data['direct_radiation'] + weather_data['diffuse_radiation']
                rad_col = 'total_radiation'
            elif 'terrestrial_radiation' in weather_data.columns:
                rad_col = 'terrestrial_radiation'
            elif 'global_tilted_irradiance' in weather_data.columns:
                rad_col = 'global_tilted_irradiance'
            elif 'radiation' in weather_data.columns:
                rad_col = 'radiation'
            
            if rad_col is None:
                logger.warning(f"Missing radiation column for {city}. Available columns: {weather_data.columns.tolist()}")
                continue
            
            # Add hour of day column (0-23)
            dates = pd.date_range(start='2024-01-01', periods=len(weather_data), freq='H')
            weather_data['hour'] = dates.hour
            
            # Group data into 4-hour periods and calculate average radiation
            weather_data['time_period'] = weather_data['hour'] // 4
            
            # Calculate average radiation for each time period
            period_avg = weather_data.groupby('time_period')[rad_col].mean().tolist()
            
            # Store data for plotting
            city_radiation_data[standardize_city_name(city)] = period_avg
        
        # Create the 2D line plot
        fig = go.Figure()
        
        # Sort cities according to STANDARD_CITY_DISPLAY_ORDER
        # Filter to only include cities in our data and preserve the standard order
        ordered_cities = [city for city in STANDARD_CITY_DISPLAY_ORDER if city in city_radiation_data.keys()]
        
        # Add a line trace for each city in the ordered list
        for i, city in enumerate(ordered_cities):
            fig.add_trace(go.Scatter(
                x=time_periods,
                y=city_radiation_data[city],
                mode='lines+markers',
                name=city,
                line=dict(color=PlotStyler.COLORS[i % len(PlotStyler.COLORS)], width=3),
                marker=dict(size=10)
            ))
        
        # Save data to CSV for reference
        data_for_csv = []
        for city in ordered_cities:
            for period_idx, period in enumerate(time_periods):
                data_for_csv.append({
                    'City': city,
                    'Time_Period': period,
                    'Average_Radiation': city_radiation_data[city][period_idx]
                })
        
        pd.DataFrame(data_for_csv).to_csv(
            output_dir / "city_climate_energy" / "radiation_by_time_period.csv", 
            index=False
        )
        
        # Apply styling with PlotStyler
        fig = PlotStyler.style_single_plot(
            fig,
            title="(d) Average Solar Radiation by Time Period",
            y_label="Solar Radiation (W/m²)",
            x_label="Time Period"
        )
        
        # Set the legend y position to 1.2 specifically for this plot
        fig.update_layout(
            legend=dict(
                y=1.2
            )
        )
        
        PlotStyler.save_plot(
            fig, 
            "Climates_D_radiation_by_time_period.png", 
            output_dir / "city_climate_energy"
        )
        
        logger.info("Saved 2D radiation by time period plot to city_climate_energy directory")
            
    except Exception as e:
        logger.error(f"Error creating radiation by time period plot: {str(e)}")
        traceback.print_exc()

def create_lcoe_schedule_plot(cities_data: dict, results_df: pd.DataFrame, output_dir: Path) -> None:
    """Create and save Results-A: Optimal LCOE for different payback periods
    
    备注: Results-A - showing optimal LCOEs for different PBPs (0-3, 3-5 years)
    """
    try:
        # Define column mapping
        column_mapping = {
            'city': ['city', 'location', 'site'],
            'lcoe [$/kWh]': ['lcoe [$/kWh]', 'lcoe', 'levelized_cost_of_energy'],
            'payback_period [years]': ['payback_period [years]', 'payback_period', 'payback', 'pp'],
            'tlps [%]': ['tlps [%]', 'tlps', 'loss_of_power_supply']  # Added TLPS column mapping
        }
        
        # Create new columns for the mapping
        actual_columns = {}
        for standard_name, possible_names in column_mapping.items():
            found = False
            for name in possible_names:
                if name in results_df.columns:
                    actual_columns[standard_name] = name
                    found = True
                    break
            if not found:
                logger.warning(f"Could not find any column matching {standard_name}")
                return
        
        # Filter for feasible solutions
        feasible_df = results_df[results_df['is_feasible']]
        
        # Group data by city and payback period ranges
        payback_ranges = [(0, 3), (3, 5)]
        cities_lcoe_data = []
        
        for city_name in cities_data.keys():
            city_data = feasible_df[feasible_df[actual_columns['city']] == city_name]
            
            for start, end in payback_ranges:
                # Filter data for current payback period range
                range_data = city_data[
                    (city_data[actual_columns['payback_period [years]']] >= start) & 
                    (city_data[actual_columns['payback_period [years]']] < end)
                ]
                
                if len(range_data) > 0:
                    # Find row with minimum LCOE that satisfies payback period
                    min_lcoe_idx = range_data[actual_columns['lcoe [$/kWh]']].idxmin()
                    best_solution = range_data.loc[min_lcoe_idx]
                    
                    # Calculate standard deviation around optimal solution
                    nearby_solutions = range_data[
                        (range_data[actual_columns['lcoe [$/kWh]']] <= best_solution[actual_columns['lcoe [$/kWh]']] * 1.1)
                    ]
                    std_lcoe = nearby_solutions[actual_columns['lcoe [$/kWh]']].std()
                    
                    cities_lcoe_data.append({
                        'City': standardize_city_name(city_name),
                        'Payback_Range': f"{start}-{end}",
                        'Mean_LCOE': best_solution[actual_columns['lcoe [$/kWh]']],
                        'Std_LCOE': std_lcoe if not pd.isna(std_lcoe) else 0,
                        'Mean_Payback': best_solution[actual_columns['payback_period [years]']],
                        'TLPS': best_solution[actual_columns['tlps [%]']]
                    })
        
        # Convert to DataFrame and order by standard city display order
        lcoe_df = pd.DataFrame(cities_lcoe_data)
        
        # Filter to only include cities in our data and preserve the standard order
        ordered_cities = [city for city in STANDARD_CITY_DISPLAY_ORDER if city in lcoe_df['City'].values]
        lcoe_df = lcoe_df[lcoe_df['City'].isin(ordered_cities)]
        lcoe_df['City_Order'] = lcoe_df['City'].map({city: i for i, city in enumerate(STANDARD_CITY_DISPLAY_ORDER)})
        lcoe_df = lcoe_df.sort_values(['City_Order', 'Payback_Range'])
        
        # Save data to CSV
        lcoe_df.to_csv(output_dir / "city_results" / "lcoe_payback_data.csv", index=False)
        
        # Create figure with secondary y-axis
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        
        # Add bars for each payback range
        for payback_range in [f"{start}-{end}" for start, end in payback_ranges]:
            range_data = lcoe_df[lcoe_df['Payback_Range'] == payback_range]
            range_data = range_data.sort_values('City_Order')  # Ensure consistent ordering
            
            # Add LCOE bars
            fig.add_trace(
                go.Bar(
                    x=range_data['City'],
                    y=range_data['Mean_LCOE'],
                    name=f'LCOE (PBP {payback_range}y)',
                    #error_y=dict(
                    #    type='data',
                    #    array=range_data['Std_LCOE'],
                    #    visible=True,
                    #    color=PlotStyler.ERROR_BAR_COLOR,
                    #    thickness=2,
                    #    width=6
                    #),
                    hovertemplate="<br>".join([
                        "City: %{x}",
                        "LCOE: $%{y:.4f}/kWh ± %{error_y.array:.4f}",
                        "Payback Range: %{fullData.name}",
                        "<extra></extra>"
                    ])
                ),
                secondary_y=False
            )
            
            # Add TLPS scatter with connecting lines
            fig.add_trace(
                go.Scatter(
                    x=range_data['City'],
                    y=range_data['TLPS'],
                    name=f'TLPS (PBP {payback_range}y)',
                    mode='lines+markers',
                    line=dict(dash='dash'),
                    marker=dict(size=8),
                    hovertemplate="<br>".join([
                        "City: %{x}",
                        "TLPS: %{y:.2f}%",
                        "<extra></extra>"
                    ])
                ),
                secondary_y=True
            )
        
        # Style the plot
        fig = PlotStyler.style_single_plot(
            fig,
            title="(a) LCOE for Target PBPs",
            x_label="City",
            y_label="LCOE ($/kWh)"
        )

        # Update layout with legend and secondary y-axis
        fig.update_layout(
            legend=dict(
                y=1.2
            ),
            yaxis2=dict(
                title="TLPS (%)",
                overlaying='y',
                side='right'
            )
        )

        # Save plot
        PlotStyler.save_plot(fig, "Results_A_lcoe_payback_analysis.png", output_dir / "city_results")
        logger.info("Saved LCOE payback analysis plot and data")
        
    except Exception as e:
        logger.error(f"Error creating LCOE payback plot: {str(e)}")
        traceback.print_exc()

def create_pv_battery_plot(cities_data: dict, results_df: pd.DataFrame, output_dir: Path) -> None:
    """Create and save Results-B: System sizing for Target PBPs
    
    备注: Results-B - showing optimal PV and battery sizes for different payback period ranges
    """
    try:
        # Define column mapping
        column_mapping = {
            'city': ['city', 'location', 'site'],
            'lcoe [$/kWh]': ['lcoe [$/kWh]', 'lcoe', 'levelized_cost_of_energy'],
            'payback_period [years]': ['payback_period [years]', 'payback_period', 'payback', 'pp'],
            'optimal_pv_area [m²]': ['optimal_pv_area [m²]', 'optimal_pv_area', 'pv_area'],
            'optimal_battery_capacity [kWh]': ['optimal_battery_capacity [kWh]', 'battery_capacity']
        }
        
        # Create new columns for the mapping
        actual_columns = {}
        for standard_name, possible_names in column_mapping.items():
            found = False
            for name in possible_names:
                if name in results_df.columns:
                    actual_columns[standard_name] = name
                    found = True
                    break
            if not found:
                logger.warning(f"Could not find any column matching {standard_name}")
                return
        
        # Filter for feasible solutions
        feasible_df = results_df[results_df['is_feasible']]
        
        # Group data by city and payback period ranges
        payback_ranges = [(0, 3), (3, 5)]
        # Prepare data for plots
        target_data = []
        for city_name in cities_data.keys():
            city_data = feasible_df[feasible_df[actual_columns['city']] == city_name]
            
            for min_pp, max_pp in payback_ranges:
                # Find solutions within payback period range
                range_solutions = city_data[
                    (city_data[actual_columns['payback_period [years]']] >= min_pp) &
                    (city_data[actual_columns['payback_period [years]']] < max_pp)
                ]
                
                if len(range_solutions) > 0:
                    # Get solution with minimum LCOE
                    best_solution = range_solutions.loc[
                        range_solutions[actual_columns['lcoe [$/kWh]']].idxmin()
                    ]
                    
                    target_data.append({
                        'City': standardize_city_name(city_name),
                        'Payback_Range': f'{min_pp}-{max_pp}',
                        'Actual_Payback': best_solution[actual_columns['payback_period [years]']],
                        'LCOE': best_solution[actual_columns['lcoe [$/kWh]']],
                        'PV_Area': best_solution[actual_columns['optimal_pv_area [m²]']],
                        'Battery_Capacity': best_solution[actual_columns['optimal_battery_capacity [kWh]']]
                    })
                    #find and print the minimum payback period that city got and the city name
                    min_payback = city_data[actual_columns['payback_period [years]']].min()
                    print(f"The minimum payback period that {city_name} got is {min_payback}")
                else:
                    #find and print the minimum payback period that city got and the city name
                    min_payback = city_data[actual_columns['payback_period [years]']].min()
                    print(f"The minimum payback period that {city_name} got is {min_payback}")
                    
        # Convert to DataFrame
        target_df = pd.DataFrame(target_data)
        
        # Order cities according to standard display order
        # Filter to only include cities in our data and preserve the standard order
        ordered_cities = [city for city in STANDARD_CITY_DISPLAY_ORDER if city in target_df['City'].values]
        target_df = target_df[target_df['City'].isin(ordered_cities)]
        target_df['City_Order'] = target_df['City'].map({city: i for i, city in enumerate(STANDARD_CITY_DISPLAY_ORDER)})
        target_df = target_df.sort_values(['City_Order', 'Payback_Range'])
        
        # Save data to CSV
        target_df.to_csv(output_dir / "city_results" / "pv_battery_data.csv", index=False)
        
        # Create figure
        fig = go.Figure()
        
        # Add PV area bars and battery capacity lines for each target payback period
        for target_pp, range_info in payback_ranges:
            target_data = target_df[target_df['Payback_Range'] == f'{target_pp}-{range_info}']
            
            # Add PV area bars
            fig.add_trace(go.Bar(
                x=target_data['City'].apply(standardize_city_name),
                y=target_data['PV_Area'],
                name=f'PV ({target_pp}-{range_info}y)',
                hovertemplate="<br>".join([
                    "City: %{x}",
                    "PV: %{y:.1f} m²", 
                    "BES: %{customdata[0]:.1f} kWh",
                    "LCOE: $%{customdata[1]:.4f}/kWh",
                    "<extra></extra>"
                ]),
                customdata=target_data[['Battery_Capacity', 'LCOE']]
            ))
            # Add battery capacity line
            fig.add_trace(go.Scatter(
                x=target_data['City'].apply(standardize_city_name),
                y=target_data['Battery_Capacity'],
                name=f'BES ({target_pp}-{range_info}y)',
                mode='markers+lines',
                marker=dict(size=10, symbol='diamond'),
                line=dict(dash='dot'),
                yaxis='y2',
                hovertemplate="<br>".join([
                    "City: %{x}",
                    "BES: %{y:.1f} kWh",
                    "PV: %{customdata[0]:.1f} m²",
                    "LCOE: $%{customdata[1]:.4f}/kWh",
                    "<extra></extra>"
                ]),
                customdata=target_data[['PV_Area', 'LCOE']]
            ))
        
        # Update layout for dual y-axis before styling
        fig.update_layout(
            barmode='group',
            bargap=0.15,
            bargroupgap=0.1,
            yaxis2=dict(
                title="Battery Capacity (kWh)",
                overlaying='y',
                side='right'
            )
        )
        
        # Style the sizing plot
        fig = PlotStyler.style_single_plot(
            fig,
            title="(b) System Sizing for Target PBPs",
            x_label="City",
            y_label="PV Array Size (m²)"
        )
        
        # Update legend position after styling
        fig.update_layout(
            legend=dict(
                y=1.2
            )
        )
        
        # Save plot
        PlotStyler.save_plot(fig, "Results_B_pv_battery_analysis.png", output_dir / "city_results")
        logger.info("Saved PV-Battery analysis plot and data")
        
    except Exception as e:
        logger.error(f"Error creating PV-Battery plot: {str(e)}")
        traceback.print_exc()

def create_city_feasibility_plots(cities_data: dict, results_df: pd.DataFrame, output_dir: Path) -> None:
    """Create and save (Results-E): Optimal Photoperiod Start Hours Analysis
    
    This function analyzes the optimal photoperiod start hours under different scenarios:
    1. PBP 0-3 years
    2. PBP 3-5 years
    3. LCOE ≤ 0.06 $/kWh
    4. LCOE ≤ 0.04 $/kWh
    
    备注: Results-E - showing optimal photoperiod start hours for each city under different 
    optimization targets and constraints
    """
    try:
        # Ensure output directories exist
        city_results_dir = output_dir / "city_results"
        city_results_dir.mkdir(parents=True, exist_ok=True)
        
        # Define column mapping
        column_mapping = {
            'city': ['city', 'location', 'site'],
            'lcoe [$/kWh]': ['lcoe [$/kWh]', 'lcoe', 'levelized_cost_of_energy'],
            'payback_period [years]': ['payback_period [years]', 'payback_period', 'payback', 'pp'],
            'start_hour': ['start_hour', 'schedule_start', 'start']
        }
        
        # Get actual column names
        actual_columns = {}
        for standard_name, possible_names in column_mapping.items():
            found = False
            for name in possible_names:
                if name in results_df.columns:
                    actual_columns[standard_name] = name
                    found = True
                    break
            if not found:
                logger.warning(f"Could not find column matching {standard_name}")
                return
        
        # Filter for feasible solutions
        feasible_df = results_df[results_df['is_feasible']]
        
        # Ensure start_hour is numeric and filter for hours 1-23
        start_hour_col = actual_columns['start_hour']
        lcoe_col = actual_columns['lcoe [$/kWh]']
        pbp_col = actual_columns['payback_period [years]']
        feasible_df[start_hour_col] = pd.to_numeric(feasible_df[start_hour_col], errors='coerce')
        feasible_df = feasible_df[feasible_df[start_hour_col].between(1, 23)]
        
        # Define scenarios
        scenarios = [
            {
                'name': 'PBP 0-3y',
                'constraint': 'pbp',
                'constraint_range': (0, 3),
                'color': PlotStyler.COLORS[0],
                'marker_symbol': 'circle'
            },
            {
                'name': 'PBP 3-5y',
                'constraint': 'pbp',
                'constraint_range': (3, 5),
                'color': PlotStyler.COLORS[1],
                'marker_symbol': 'square'
            },
            {
                'name': 'LCOE ≤0.06',
                'constraint': 'lcoe',
                'constraint_value': 0.06,
                'color': PlotStyler.COLORS[2],
                'marker_symbol': 'diamond'
            },
            {
                'name': 'LCOE ≤0.04',
                'constraint': 'lcoe',
                'constraint_value': 0.04,
                'color': PlotStyler.COLORS[3],
                'marker_symbol': 'cross'
            }
        ]
        
        # Store results for each city and scenario
        optimal_hours = []
        
        # Process each city
        for city in cities_data.keys():
            city_data = feasible_df[feasible_df[actual_columns['city']] == city]
            
            for scenario in scenarios:
                filtered_data = city_data.copy()
                
                # Apply constraints
                if scenario['constraint'] == 'pbp':
                    min_pbp, max_pbp = scenario['constraint_range']
                    filtered_data = filtered_data[
                        (filtered_data[pbp_col] >= min_pbp) & 
                        (filtered_data[pbp_col] < max_pbp)
                    ]
                elif scenario['constraint'] == 'lcoe':
                    filtered_data = filtered_data[
                        filtered_data[lcoe_col] <= scenario['constraint_value']
                    ]
                
                if len(filtered_data) > 0:
                    # Find optimal solution (minimum LCOE for each scenario)
                    best_solution = filtered_data.loc[filtered_data[lcoe_col].idxmin()]
                    
                    optimal_hours.append({
                        'City': standardize_city_name(city),
                        'Scenario': scenario['name'],
                        'Start_Hour': best_solution[start_hour_col],
                        'LCOE': best_solution[lcoe_col],
                        'PBP': best_solution[pbp_col],
                        'Color': scenario['color'],
                        'Marker': scenario['marker_symbol']
                    })
                else:
                    logger.info(f"No feasible solutions for {city} with scenario {scenario['name']}")
        
        # Convert to DataFrame
        results_df = pd.DataFrame(optimal_hours)
        
        # Order cities according to standard display order
        ordered_cities = [city for city in STANDARD_CITY_DISPLAY_ORDER if city in results_df['City'].unique()]
        results_df['City_Order'] = results_df['City'].map({city: i for i, city in enumerate(ordered_cities)})
        results_df = results_df.sort_values(['City_Order', 'Scenario'])
        
        # Create plot
        fig = go.Figure()
        
        # Add traces for each scenario
        for scenario in scenarios:
            scenario_data = results_df[results_df['Scenario'] == scenario['name']]
            
            if len(scenario_data) > 0:
                fig.add_trace(go.Scatter(
                    x=scenario_data['City'],
                    y=scenario_data['Start_Hour'],
                    name=scenario['name'],
                    mode='lines+markers',
                    line=dict(
                        color=scenario['color'],
                        width=2,
                        dash='dash'
                    ),
                    marker=dict(
                        size=10,
                        symbol=scenario['marker_symbol'],
                        color=scenario['color']
                    ),
                    hovertemplate="<br>".join([
                        "City: %{x}",
                        "Start Hour: %{y:.0f}:00",
                        "LCOE: $%{customdata[0]:.4f}/kWh",
                        "PBP: %{customdata[1]:.2f} years",
                        "<extra></extra>"
                    ]),
                    customdata=scenario_data[['LCOE', 'PBP']]
                ))
        
        # Style the plot
        fig = PlotStyler.style_single_plot(
            fig,
            title="(e) Optimal Photoperiod Start Hours",
            x_label="City",
            y_label="Start Hour (hour of day)"
        )
        
        # Update layout with fewer y-axis ticks
        fig.update_layout(
            yaxis=dict(
                tickmode='linear',
                tick0=2,
                dtick=1,  # Reduced tick spacing for smaller range
                range=[0.5, 6]  # Set maximum to 6 as requested
            ),
            legend=dict(
                y=1.2,
                xanchor="center",
                x=0.5,
                orientation="h"
            )
        )
        
        # Save plot and data
        PlotStyler.save_plot(fig, "Results_E_optimal_hours.png", city_results_dir)
        results_df.to_csv(city_results_dir / "optimal_hours_data.csv", index=False)
        logger.info("Saved optimal photoperiod start hours analysis")
        
    except Exception as e:
        logger.error(f"Error creating optimal hours plot: {str(e)}")
        traceback.print_exc()

def create_feasibility_correlation_plot(cities_data: dict, results_df: pd.DataFrame, output_dir: Path) -> None:
    """Create and save Results-F: Start Hour Impact Analysis
    
    This function analyzes how different photoperiod start hours affect system performance:
    
    1. Data Processing:
       - Groups feasible solutions by start hour across all cities
       - Calculates average LCOE and PBP for each start hour
       - Shows the relationship between scheduling and system economics
       
    2. Visualization:
       - Dual y-axis scatter plot
       - X-axis: Photoperiod start hours (0-23)
       - Primary y-axis: Average LCOE across all cities
       - Secondary y-axis: Average PBP across all cities
       - Custom markers: ⚡ for LCOE, ⏰ for PBP
    
    备注: Results-F - showing how photoperiod start time affects system economics across all cities,
    using dual y-axis scatter plot to visualize LCOE and PBP trends
    """
    global MERGED_RESULTS_DF
    try:
        # Read results
        results_df = MERGED_RESULTS_DF
        
        # Filter out Jinan and Zhengzhou
        if 'city' in results_df.columns:
            results_df = results_df[~results_df['city'].isin(['jinan', 'zhengzhou'])]
        
        # Define column mapping
        column_mapping = {
            'city': ['city', 'location', 'site'],
            'lcoe [$/kWh]': ['lcoe [$/kWh]', 'lcoe', 'levelized_cost_of_energy'],
            'payback_period [years]': ['payback_period [years]', 'payback_period', 'payback', 'pp'],
            'start_hour': ['start_hour', 'schedule_start', 'start']
        }
        
        # Get actual column names
        actual_columns = {}
        for standard_name, possible_names in column_mapping.items():
            found = False
            for name in possible_names:
                if name in results_df.columns:
                    actual_columns[standard_name] = name
                    found = True
                    break
            if not found:
                logger.warning(f"Could not find column matching {standard_name}")
                return
        
        # Filter for feasible solutions
        feasible_df = results_df[results_df['is_feasible']]
        
        # Ensure start_hour is numeric and filter for hours 1-23
        start_hour_col = actual_columns['start_hour']
        feasible_df[start_hour_col] = pd.to_numeric(feasible_df[start_hour_col], errors='coerce')
        feasible_df = feasible_df[feasible_df[start_hour_col].between(1, 23)]
        
        # Group by start hour and calculate averages
        grouped_data = feasible_df.groupby(start_hour_col).agg({
            actual_columns['lcoe [$/kWh]']: 'mean',
            actual_columns['payback_period [years]']: 'mean'
        }).reset_index()
        
        # Sort by start hour
        grouped_data = grouped_data.sort_values(start_hour_col)
        
        # Create figure with secondary y-axis
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        
        # Add LCOE scatter (⚡)
        fig.add_trace(
            go.Scatter(
                x=grouped_data[start_hour_col],
                y=grouped_data[actual_columns['lcoe [$/kWh]']],
                name='LCOE',
                mode='lines+markers',
                line=dict(
                    color=PlotStyler.COLORS[0],
                    width=2,
                    dash='dash'
                ),
                marker=dict(
                    symbol='star',  # Using star as electricity symbol
                    size=12,
                    color=PlotStyler.COLORS[0]
                ),
                hovertemplate="Start Hour: %{x}<br>LCOE: $%{y:.4f}/kWh<extra></extra>"
            ),
            secondary_y=False
        )
        
        # Add PBP scatter (⏰)
        fig.add_trace(
            go.Scatter(
                x=grouped_data[start_hour_col],
                y=grouped_data[actual_columns['payback_period [years]']],
                name='PBP',
                mode='lines+markers',
                line=dict(
                    color=PlotStyler.COLORS[1],
                    width=2,
                    dash='dash'
                ),
                marker=dict(
                    symbol='circle-cross',  # Using circle-cross as clock symbol
                    size=12,
                    color=PlotStyler.COLORS[1]
                ),
                hovertemplate="Start Hour: %{x}<br>PBP: %{y:.2f} years<extra></extra>"
            ),
            secondary_y=True
        )
        
        # Style the plot using PlotStyler
        fig = PlotStyler.style_single_plot(
            fig,
            title="F: Impact of Photoperiod Start Time",
            x_label="Start Hour",
            y_label="LCOE ($/kWh)"
        )
        
        # Update layout with secondary y-axis
        fig.update_layout(
            xaxis=dict(
                tickmode='linear',
                tick0=1,  # Start from 1
                dtick=2,  # Show every 2 hours
                ticktext=[f"{i:02d}:00" for i in range(1, 23, 2)],
                tickvals=list(range(1, 23, 2))  # Only show odd hours
            ),
            yaxis2=dict(
                title="Payback Period (years)",
                #titlefont=dict(color=PlotStyler.COLORS[1]),
                #tickfont=dict(color=PlotStyler.COLORS[1]),
                showgrid=False
            ),
            legend=dict(
               # y=1.2,
                #xanchor="center",
                #x=0.5
            )
        )
        
        # Save plot
        PlotStyler.save_plot(fig, "Results_F_start_hour_impact.png", output_dir / "city_results")
        logger.info("Saved start hour impact analysis plot")
        # Save data
        grouped_data.columns = ['Start_Hour', 'Average_LCOE', 'Average_PBP']
        grouped_data.to_csv(output_dir / "city_results" / "start_hour_impact_data.csv", index=False)
        
    except Exception as e:
        logger.error(f"Error in create_feasibility_correlation_plot: {str(e)}")
        logger.error(traceback.format_exc())
        raise

def analyze_city_climate_energy(cities=CITIES_TO_ANALYZE,
                              output_dir: Path = Path("results")) -> None:
    """Create separate plots showing climate and energy characteristics for cities.
    
    This function creates the following plots:
    - Climate plots:
        - Climates-A: Annual average solar hours
        - Climates-B: Temperature analysis
        - Climates-C: HVAC schedule analysis
        - Climates-D: Radiation by time period
    - Results plots:
        - Results-A: Optimal LCOE for different payback periods
        - Results-B: PV Area vs Battery Capacity for optimal solutions
        - Results-C: Target LCOE analysis
        - Results-D: System sizing for target LCOEs
        - Results-E: Minimum cost for TLPS < 1%
        - Results-F: Correlation map
    """
    global MERGED_RESULTS_DF
    
    try:
        # Ensure output directories exist
        output_dir.mkdir(parents=True, exist_ok=True)
        city_climate_dir = output_dir / "city_climate_energy"
        city_climate_dir.mkdir(parents=True, exist_ok=True)
        city_results_dir = output_dir / "city_results"
        city_results_dir.mkdir(parents=True, exist_ok=True)
        
        # Merge all enumeration results if not already done
        if MERGED_RESULTS_DF is None:
            MERGED_RESULTS_DF = merge_enumeration_results()
        
        # Dictionary to store city data
        cities_results = {}
        
        # Process each city's weather data
        for city in cities:
            logger.info(f"\nProcessing {city}...")
            
            # Load weather data
            weather_file = Path(f"test_case/{city}/weather/{city}_2024.csv")
            if not weather_file.exists():
                logger.warning(f"Weather file not found for {city}")
                continue
                
            weather_data = pd.read_csv(weather_file)
            logger.info(f"Loaded weather data for {city}: {len(weather_data)} rows")
            
            # Calculate total radiation
            if 'terrestrial_radiation' in weather_data.columns:
                weather_data['total_radiation'] = weather_data['terrestrial_radiation']
            elif all(col in weather_data.columns for col in ['direct_radiation', 'diffuse_radiation']):
                weather_data['total_radiation'] = (weather_data['direct_radiation'] + 
                                                 weather_data['diffuse_radiation'])
            else:
                logger.warning(f"No suitable radiation columns found for {city}")
                continue
            
            # Calculate daily average radiation
            weather_data['date'] = pd.to_datetime(weather_data['time']).dt.date
            daily_radiation = weather_data.groupby('date')['total_radiation'].mean().reset_index()
            
            # Calculate daily accumulative radiation
            daily_radiation['cumulative_radiation'] = daily_radiation['total_radiation'].cumsum()
            
            # Calculate annual average solar hours
            solar_threshold = 120  # W/m²
            solar_hours = (weather_data['total_radiation'] > solar_threshold).sum() / 365
            
            # Calculate daily temperature
            weather_data['daily_temperature'] = weather_data['temperature_2m']
            
            # Store city data
            cities_results[city] = {
                'weather_data': weather_data,
                'daily_radiation': daily_radiation,
                'daily_temperature': weather_data['daily_temperature'],
                'avg_solar_hours_per_day': solar_hours
            }
            
            logger.info(f"Processed {city} data - Annual average solar hours: {solar_hours:.2f}")
        
        # Create climate plots
        if cities_results:
            logger.info(f"Creating climate plots for {len(cities_results)} cities")
            try:
                # Create Climates-A: Annual average solar hours
                create_radiation_plot(cities_results, output_dir)
                
                # Create Climates-B: Temperature analysis
                create_temperature_plot(cities_results, output_dir)
                
                # Create Climates-C: HVAC schedule analysis
                create_hvac_schedule_plot(cities_results, output_dir)
                
                # Create Climates-D: Radiation by time period
                create_correlation_plot(cities_results, output_dir)
                
            except Exception as e:
                logger.error(f"Error creating climate plots: {str(e)}")
                logger.error(traceback.format_exc())
        
        # Create results plots if we have data
        if cities_results:
            logger.info(f"Creating results plots for {len(cities_results)} cities")
            try:
                # Create Results-A: Optimal LCOE for different payback periods
                create_lcoe_schedule_plot(cities_results, MERGED_RESULTS_DF, output_dir)
                
                # Create Results-B: PV Area vs Battery Capacity
                create_pv_battery_plot(cities_results, MERGED_RESULTS_DF, output_dir)
                
                # Create Results-C and D: Target LCOE analysis
                create_target_lcoe_analysis(cities_results, MERGED_RESULTS_DF, output_dir)
                
                # Create Results-D: System sizing for target LCOEs
                #create_target_lcoe_plot(cities_results, MERGED_RESULTS_DF, output_dir)
                
                # Create Results-E: Minimum cost for TLPS < 1%
                create_city_feasibility_plots(cities_results, MERGED_RESULTS_DF, output_dir)
                
                # Create Results-F: Correlation map
                create_feasibility_correlation_plot(cities_results, MERGED_RESULTS_DF, output_dir)
                
            except Exception as e:
                logger.error(f"Error creating results plots: {str(e)}")
                logger.error(traceback.format_exc())
        else:
            logger.warning("No cities with feasible solutions found")
        
        logger.info("Completed creating all analysis plots and saving data files")
        
    except Exception as e:
        logger.error(f"Error in analyze_city_climate_energy: {str(e)}")
        logger.error(traceback.format_exc())
        raise

def create_target_lcoe_analysis(cities_results: dict, df: pd.DataFrame, output_dir: Path) -> None:
    """Create and save Results-C: Target LCOE analysis
    
    备注: Results-C and Results-D - showing optimal solutions for different target LCOEs with their corresponding payback periods
    """
    try:
        # Define column mapping
        column_mapping = {
            'city': ['city', 'location', 'site'],
            'lcoe [$/kWh]': ['lcoe [$/kWh]', 'lcoe', 'levelized_cost_of_energy'],
            'payback_period [years]': ['payback_period [years]', 'payback_period', 'payback', 'pp'],
            'optimal_pv_area [m²]': ['optimal_pv_area [m²]', 'optimal_pv_area', 'pv_area'],
            'optimal_battery_capacity [kWh]': ['optimal_battery_capacity [kWh]', 'battery_capacity'],
            'tlps [%]': ['tlps [%]', 'tlps', 'tlp']
        }
        
        # Create new columns for the mapping
        actual_columns = {}
        for standard_name, possible_names in column_mapping.items():
            found = False
            for name in possible_names:
                if name in df.columns:
                    actual_columns[standard_name] = name
                    found = True
                    break
            if not found:
                logger.warning(f"Could not find any column matching {standard_name}")
                return
        
        # Filter for feasible solutions
        feasible_df = df[df['is_feasible']]
        
        # Target LCOEs to analyze
        target_lcoes = [0.04, 0.06]  # $/kWh
        tolerance = 0.005  # $/kWh
        
        # Store data for plotting
        target_data = []
        
        # Process each city
        for city in cities_results.keys():
            city_data = feasible_df[feasible_df[actual_columns['city']] == city]
            
            for target_lcoe in target_lcoes:
                # Find solutions within tolerance of target LCOE
                solutions = city_data[
                    (city_data[actual_columns['lcoe [$/kWh]']] >= target_lcoe - tolerance) &
                    (city_data[actual_columns['lcoe [$/kWh]']] <= target_lcoe + tolerance)
                ]
                
                if len(solutions) > 0:
                    # Get solution with minimum payback period
                    best_solution = solutions.nsmallest(1, actual_columns['payback_period [years]']).iloc[0]
                else:
                    # Find closest solutions if none within tolerance
                    solutions = city_data.copy()
                    solutions['lcoe_diff'] = abs(solutions[actual_columns['lcoe [$/kWh]']] - target_lcoe)
                    best_solution = solutions.nsmallest(1, 'lcoe_diff').iloc[0]
                
                # Add to target data with actual values
                target_data.append({
                    'City': standardize_city_name(city),
                    'Target_LCOE': target_lcoe,
                    'Actual_LCOE': best_solution[actual_columns['lcoe [$/kWh]']],
                    'PV_Area': best_solution[actual_columns['optimal_pv_area [m²]']],
                    'Battery_Capacity': best_solution[actual_columns['optimal_battery_capacity [kWh]']],
                    'Payback_Period': best_solution[actual_columns['payback_period [years]']],
                    'TLPS': best_solution[actual_columns['tlps [%]']]
                })
        
        # Convert to DataFrame
        plot_df = pd.DataFrame(target_data)
        
        # Order cities according to standard display order
        # Filter to only include cities in our data and preserve the standard order
        ordered_cities = [city for city in STANDARD_CITY_DISPLAY_ORDER if city in plot_df['City'].values]
        plot_df = plot_df[plot_df['City'].isin(ordered_cities)]
        plot_df['City_Order'] = plot_df['City'].map({city: i for i, city in enumerate(STANDARD_CITY_DISPLAY_ORDER)})
        plot_df = plot_df.sort_values(['City_Order', 'Target_LCOE'])

        # Create Results-C: Payback Period plot with secondary y-axis
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        
        # Add bars and scatter for each target LCOE
        for i, target_lcoe in enumerate(target_lcoes):
            target_data = plot_df[plot_df['Target_LCOE'] == target_lcoe]
            target_data = target_data.sort_values('City_Order')  # Ensure consistent ordering
            
            # Add bars for payback period
            fig.add_trace(
                go.Bar(
                    name=f'PBP (LCOE {target_lcoe:.2f}$)',
                    x=target_data['City'],
                    y=target_data['Payback_Period'],
                    #text=[f"{val:.2f}y" for val in target_data['Payback_Period']],
                    #textposition='outside',
                    hovertemplate="<br>".join([
                        "City: %{x}",
                        "LCOE: $%{customdata:.4f}/kWh", 
                        "PBP: %{y:.2f} years",
                        "<extra></extra>"
                    ]),
                    customdata=target_data['Actual_LCOE']
                ),
                secondary_y=False
            )
            
            # Add scatter for TLPS with connecting lines
            fig.add_trace(
                go.Scatter(
                    name=f'TLPS (LCOE {target_lcoe:.2f}$)',
                    x=target_data['City'],
                    y=target_data['TLPS'],
                    mode='lines+markers',
                    line=dict(dash='dash', width=2),
                    marker=dict(size=10, symbol='circle'),
                    hovertemplate="<br>".join([
                        "City: %{x}",
                        "TLPS: %{y:.2f}%",
                        "<extra></extra>"
                    ]),
                    showlegend=True
                ),
                secondary_y=True,
            )
        
        # Style the plot
        fig = PlotStyler.style_single_plot(
            fig,
            title="(c) PBP for Target LCOEs",
            x_label="City",
            y_label="Payback Period (years)",
        )
        
        # Update layout
        fig.update_layout(
            barmode='group',
            bargap=0.15,
            bargroupgap=0.1,
            legend=dict(
                y=1.2
            ),
            yaxis2=dict(
                title="TLPS (%)",
                overlaying='y',
                side='right',
                showgrid=True,
                gridcolor='rgba(128, 128, 128, 0.2)',
                zeroline=True,
                zerolinecolor='rgba(128, 128, 128, 0.2)'
            )
        )
        
        # Save plot and data
        PlotStyler.save_plot(fig, "Results_C_target_lcoe_analysis.png", output_dir / "city_results")
        plot_df.to_csv(output_dir / "city_results" / "Results_C_target_lcoe_analysis_data.csv", index=False)
        logger.info("Saved target LCOE analysis plot and data")
    
        # Create Results-D plot
        logger.info("Creating Results-D plot")
        
        # Create a figure for Results-D
        fig_d = go.Figure()
        
        # Plot each target LCOE as a separate bar group
        for target_lcoe in target_lcoes:
            target_data = plot_df[plot_df['Target_LCOE'] == target_lcoe]
            target_data = target_data.sort_values('City_Order')  # Ensure consistent ordering
            
            # Add PV area bars
            fig_d.add_trace(go.Bar(
                x=target_data['City'],
                y=target_data['PV_Area'],
                name=f'PV (LCOE=${target_lcoe:.2f})',
                hovertemplate="<br>".join([
                    "City: %{x}",
                    "PV: %{y:.1f} m²", 
                    "BES: %{customdata[0]:.1f} kWh",
                    "LCOE: $%{customdata[1]:.4f}/kWh",
                    "TLPS: %{customdata[2]:.4f}%",
                    "<extra></extra>"
                ]),
                customdata=target_data[['Battery_Capacity', 'Actual_LCOE', 'TLPS']]
            ))
            
            # Add battery capacity line
            fig_d.add_trace(go.Scatter(
                x=target_data['City'],
                y=target_data['Battery_Capacity'],
                name=f'BES (LCOE=${target_lcoe:.2f})',
                mode='markers+lines',
                marker=dict(size=10, symbol='diamond'),
                line=dict(dash='dot'),
                yaxis='y2',
                hovertemplate="<br>".join([
                    "City: %{x}",
                    "BES: %{y:.1f} kWh",
                    "PV: %{customdata[0]:.1f} m²",
                    "LCOE: $%{customdata[1]:.4f}/kWh",
                    "TLPS: %{customdata[2]:.4f}%",
                    "<extra></extra>"
                ]),
                customdata=target_data[['PV_Area', 'Actual_LCOE', 'TLPS']]
            ))
        
        # Style the plot
        fig_d = PlotStyler.style_single_plot(
            fig_d,
            title="(d) System Sizing for Target LCOEs",
            x_label="City",
            y_label="PV Array Size (m²)"
        )
        
        # Update layout for dual y-axis
        fig_d.update_layout(
            barmode='group',
            bargap=0.15,
            bargroupgap=0.1,
            yaxis2=dict(
                title="Battery Capacity (kWh)",
                overlaying='y',
                side='right'
            ),
            legend=dict(
                y=1.2
            )
        )
        
        # Save plot
        PlotStyler.save_plot(fig_d, "Results_D_target_lcoe_analysis.png", output_dir / "city_results")
        logger.info("Saved target LCOE system sizing analysis plot")
    except Exception as e:
        logger.error(f"Error creating target LCOE analysis plot: {str(e)}")
        logger.error(traceback.format_exc())
        raise
    

def analyze_mechanism_results(timeseries_file: Path, metrics_file: Path, output_dir: Path) -> None:
    """Analyze and visualize mechanism analysis results.
    
    Args:
        timeseries_file: Path to the mechanism timeseries CSV file
        metrics_file: Path to the mechanism metrics CSV file
        output_dir: Directory to save output plots
    """
    try:
        logger.info("Analyzing mechanism results")
        
        # Define plot height for mechanism plots
        mechanism_plot_height = 700
        
        # Define legend settings for mechanism plots
        mechanism_legend_settings = dict(
            orientation="h",
            yanchor="top",
            y=1.22,
            xanchor="center",
            x=0.5,
            bgcolor='rgba(255, 255, 255, 0)',
            #bordercolor='rgba(0, 0, 0, 0.2)',
            #borderwidth=1,
            font=dict(size=PlotStyler.LEGEND_FONT_SIZE)
        )
        
        # Define x-axis settings for mechanism plots
        mechanism_xaxis_settings = dict(
            tickformat='%H:00',
            dtick=3600000 * 6,  # Show ticks every 6 hours
            tickfont={'size': PlotStyler.TICK_FONT_SIZE}
        )
        
        # Create output directory
        mechanism_dir = output_dir / "mechanism_analysis"
        mechanism_dir.mkdir(parents=True, exist_ok=True)
        
        # Read data
        df_timeseries = pd.read_csv(timeseries_file)
        df_metrics = pd.read_csv(metrics_file)
        
        # Convert timestamp to datetime
        df_timeseries['timestamp'] = pd.to_datetime(df_timeseries['timestamp'])
        
        # Add total radiation column for reference
        if 'direct_radiation_W/m2' in df_timeseries.columns and 'diffuse_radiation_W/m2' in df_timeseries.columns:
            df_timeseries['total_radiation_W/m2'] = df_timeseries['direct_radiation_W/m2'] + df_timeseries['diffuse_radiation_W/m2']
        
        # Filter to a representative period (3 days in May)
        # Use a period with good solar radiation for better visualization
        mask = (df_timeseries['timestamp'] >= '2024-05-01') & (df_timeseries['timestamp'] <= '2024-05-03')
        df_timeseries = df_timeseries[mask]
        
        # Get unique start hours from metrics
        start_hours = sorted(df_metrics['start_hour'].unique())
        
        # Create separate plots for each configuration
        # Plot C: First start hour, PV only
        fig_c = go.Figure()
        pv_prefix = f'h{start_hours[0]:02d}_pv_only'
        load_profile_key = f'load_profile_h{start_hours[0]:02d}'
        
        # Add radiation trace to show solar pattern
        if 'total_radiation_W/m2' in df_timeseries.columns:
            # Create a secondary y-axis for radiation
            fig_c.add_trace(go.Scatter(
                x=df_timeseries['timestamp'],
                y=df_timeseries['total_radiation_W/m2'],
                name='Radiation',
                line=dict(color='rgba(255,215,0,0.7)', width=3, dash='dot'),
                yaxis='y2'
            ))
        
        # Add traces in specific order: Load, PV, Grid
        fig_c.add_trace(go.Scatter(
            x=df_timeseries['timestamp'],
            y=df_timeseries[load_profile_key],
            name='Load',
            line=dict(color=PlotStyler.COLORS[4], width=3)
        ))
        fig_c.add_trace(go.Scatter(
            x=df_timeseries['timestamp'],
            y=df_timeseries[f'{pv_prefix}_pv_generation'],
            name='PV',
            line=dict(color=PlotStyler.COLORS[0], width=3)
        ))
        fig_c.add_trace(go.Scatter(
            x=df_timeseries['timestamp'],
            y=df_timeseries[f'{pv_prefix}_grid_import'],
            name='Grid',
            line=dict(color=PlotStyler.COLORS[1], width=3)
        ))
        
        # First apply PlotStyler styling
        fig_c = PlotStyler.style_single_plot(
            fig_c,
            title=f"(a) PV-only System (Start: {start_hours[0]:02d}:00)",
            x_label="Time",
            y_label="Power (kW)"
        )
        
        # Then update layout with custom height
        fig_c.update_layout(
            yaxis2=dict(
                title="Solar Radiation (W/m²)",
                overlaying="y",
                side="right",
                showgrid=False,
                showline=True,
                linewidth=PlotStyler.BORDER_WIDTH,
                linecolor=PlotStyler.BORDER_COLOR,
                mirror=True,
                tickfont={'family': PlotStyler.FONT_FAMILY, 'size': PlotStyler.TICK_FONT_SIZE}
            ),
            xaxis=mechanism_xaxis_settings,
            width=PlotStyler.SINGLE_PLOT_WIDTH,
            height=mechanism_plot_height,
            margin=PlotStyler.MARGIN,
            showlegend=True,
            #legend=mechanism_legend_settings
            
        )
        
        # Plot D: First start hour, PV+Battery
        fig_d = go.Figure()
        full_prefix = f'h{start_hours[0]:02d}_full_system'
        
        # Add radiation trace
        if 'total_radiation_W/m2' in df_timeseries.columns:
            fig_d.add_trace(go.Scatter(
                x=df_timeseries['timestamp'],
                y=df_timeseries['total_radiation_W/m2'],
                name='Radiation',
                line=dict(color='rgba(255,215,0,0.7)', width=3, dash='dot'),
                yaxis='y2'
            ))
        
        # Add traces in specific order: Load, PV, Grid, Battery
        fig_d.add_trace(go.Scatter(
            x=df_timeseries['timestamp'],
            y=df_timeseries[load_profile_key],
            name='Load',
            line=dict(color=PlotStyler.COLORS[4], width=3)
        ))
        fig_d.add_trace(go.Scatter(
            x=df_timeseries['timestamp'],
            y=df_timeseries[f'{full_prefix}_pv_generation'],
            name='PV',
            line=dict(color=PlotStyler.COLORS[0], width=3)
        ))
        fig_d.add_trace(go.Scatter(
            x=df_timeseries['timestamp'],
            y=df_timeseries[f'{full_prefix}_grid_import'],
            name='Grid',
            line=dict(color=PlotStyler.COLORS[1], width=3)
        ))
        fig_d.add_trace(go.Scatter(
            x=df_timeseries['timestamp'],
            y=df_timeseries[f'{full_prefix}_battery_charge'],
            name='Charge',
            line=dict(color=PlotStyler.COLORS[2], width=3)
        ))
        fig_d.add_trace(go.Scatter(
            x=df_timeseries['timestamp'],
            y=df_timeseries[f'{full_prefix}_battery_discharge'],
            name='Discharge',
            line=dict(color=PlotStyler.COLORS[3], width=3)
        ))
        
        # First apply PlotStyler styling
        fig_d = PlotStyler.style_single_plot(
            fig_d,
            title=f"(b) PV-Battery System (Start: {start_hours[0]:02d}:00)",
            x_label="Time",
            y_label="Power (kW)"
        )
        
        # Then update layout with custom height
        fig_d.update_layout(
            yaxis2=dict(
                title="Solar Radiation (W/m²)",
                overlaying="y",
                side="right",
                showgrid=False,
                showline=True,
                linewidth=PlotStyler.BORDER_WIDTH,
                linecolor=PlotStyler.BORDER_COLOR,
                mirror=True,
                tickfont={'family': PlotStyler.FONT_FAMILY, 'size': PlotStyler.TICK_FONT_SIZE}
            ),
            xaxis=mechanism_xaxis_settings,
            width=PlotStyler.SINGLE_PLOT_WIDTH,
            height=mechanism_plot_height,
            margin=PlotStyler.MARGIN,
            showlegend=True,
            #legend=mechanism_legend_settings
            legend=dict(
                y=1.2
            )
        )
        
        # Plot E: Second start hour, PV only
        fig_e = go.Figure()
        pv_prefix = f'h{start_hours[1]:02d}_pv_only'
        load_profile_key = f'load_profile_h{start_hours[1]:02d}'
        
        # Add radiation trace
        if 'total_radiation_W/m2' in df_timeseries.columns:
            fig_e.add_trace(go.Scatter(
                x=df_timeseries['timestamp'],
                y=df_timeseries['total_radiation_W/m2'],
                name='Radiation',
                line=dict(color='rgba(255,215,0,0.7)', width=3, dash='dot'),
                yaxis='y2'
            ))
        
        # Add traces in specific order: Load, PV, Grid
        fig_e.add_trace(go.Scatter(
            x=df_timeseries['timestamp'],
            y=df_timeseries[load_profile_key],
            name='Load',
            line=dict(color=PlotStyler.COLORS[4], width=3)
        ))
        fig_e.add_trace(go.Scatter(
            x=df_timeseries['timestamp'],
            y=df_timeseries[f'{pv_prefix}_pv_generation'],
            name='PV',
            line=dict(color=PlotStyler.COLORS[0], width=3)
        ))
        fig_e.add_trace(go.Scatter(
            x=df_timeseries['timestamp'],
            y=df_timeseries[f'{pv_prefix}_grid_import'],
            name='Grid',
            line=dict(color=PlotStyler.COLORS[1], width=3)
        ))
        
        # First apply PlotStyler styling
        fig_e = PlotStyler.style_single_plot(
            fig_e,
            title=f"(c) PV-only System (Start: {start_hours[1]:02d}:00)",
            x_label="Time",
            y_label="Power (kW)"
        )
        
        # Then update layout with custom height
        fig_e.update_layout(
            yaxis2=dict(
                title="Solar Radiation (W/m²)",
                overlaying="y",
                side="right",
                showgrid=False,
                showline=True,
                linewidth=PlotStyler.BORDER_WIDTH,
                linecolor=PlotStyler.BORDER_COLOR,
                mirror=True,
                tickfont={'family': PlotStyler.FONT_FAMILY, 'size': PlotStyler.TICK_FONT_SIZE}
            ),
            xaxis=mechanism_xaxis_settings,
            width=PlotStyler.SINGLE_PLOT_WIDTH,
            height=mechanism_plot_height,
            margin=PlotStyler.MARGIN,
            showlegend=True,
            #legend=mechanism_legend_settings
        )
        
        # Plot F: Second start hour, PV+Battery
        fig_f = go.Figure()
        full_prefix = f'h{start_hours[1]:02d}_full_system'
        
        # Add radiation trace
        if 'total_radiation_W/m2' in df_timeseries.columns:
            fig_f.add_trace(go.Scatter(
                x=df_timeseries['timestamp'],
                y=df_timeseries['total_radiation_W/m2'],
                name='Radiation',
                line=dict(color='rgba(255,215,0,0.7)', width=3, dash='dot'),
                yaxis='y2'
            ))
        
        # Add traces in specific order: Load, PV, Grid, Battery
        fig_f.add_trace(go.Scatter(
            x=df_timeseries['timestamp'],
            y=df_timeseries[load_profile_key],
            name='Load',
            line=dict(color=PlotStyler.COLORS[4], width=3)
        ))
        fig_f.add_trace(go.Scatter(
            x=df_timeseries['timestamp'],
            y=df_timeseries[f'{full_prefix}_pv_generation'],
            name='PV',
            line=dict(color=PlotStyler.COLORS[0], width=3)
        ))
        fig_f.add_trace(go.Scatter(
            x=df_timeseries['timestamp'],
            y=df_timeseries[f'{full_prefix}_grid_import'],
            name='Grid',
            line=dict(color=PlotStyler.COLORS[1], width=3)
        ))
        fig_f.add_trace(go.Scatter(
            x=df_timeseries['timestamp'],
            y=df_timeseries[f'{full_prefix}_battery_charge'],
            name='Charge',
            line=dict(color=PlotStyler.COLORS[2], width=3)
        ))
        fig_f.add_trace(go.Scatter(
            x=df_timeseries['timestamp'],
            y=df_timeseries[f'{full_prefix}_battery_discharge'],
            name='Discharge',
            line=dict(color=PlotStyler.COLORS[3], width=3)
        ))
        
        # First apply PlotStyler styling
        fig_f = PlotStyler.style_single_plot(
            fig_f,
            title=f"(d) PV-Battery System (Start: {start_hours[1]:02d}:00)",
            x_label="Time",
            y_label="Power (kW)"
        )
        
        # Then update layout with custom height
        fig_f.update_layout(
            yaxis2=dict(
                title="Solar Radiation (W/m²)",
                overlaying="y",
                side="right",
                showgrid=False,
                showline=True,
                linewidth=PlotStyler.BORDER_WIDTH,
                linecolor=PlotStyler.BORDER_COLOR,
                mirror=True,
                tickfont={'family': PlotStyler.FONT_FAMILY, 'size': PlotStyler.TICK_FONT_SIZE}
            ),
            xaxis=mechanism_xaxis_settings,
            width=PlotStyler.SINGLE_PLOT_WIDTH,
            height=mechanism_plot_height,
            margin=PlotStyler.MARGIN,
            showlegend=True,
            #legend=mechanism_legend_settings
            legend=dict(
                y=1.2
            )
        )
        
        # Save all plots
        PlotStyler.save_plot(fig_c, "mechanism_plot_A.png", mechanism_dir)
        PlotStyler.save_plot(fig_d, "mechanism_plot_B.png", mechanism_dir)
        PlotStyler.save_plot(fig_e, "mechanism_plot_C.png", mechanism_dir)
        PlotStyler.save_plot(fig_f, "mechanism_plot_D.png", mechanism_dir)
        
        # Create metrics comparison plot
        fig_metrics = go.Figure()
        
        # Sort configurations by start hour and system type
        df_metrics = df_metrics.sort_values(['start_hour', 'config_label'])
        
        # Add PV Utilization bars
        fig_metrics.add_trace(go.Bar(
            name='PV Utilization',
            x=df_metrics['config_label'],
            y=df_metrics['pv_utilization'],
            text=[f"{val:.1f}%" for val in df_metrics['pv_utilization']],
            textposition='outside',
            marker_color=PlotStyler.COLORS[0],
            width=0.3,
            offset=-0.2,
            textfont={'size': PlotStyler.ANNOTATION_FONT_SIZE}
        ))
        
        # Add Grid Dependency bars
        fig_metrics.add_trace(go.Bar(
            name='Grid Dependency',
            x=df_metrics['config_label'],
            y=df_metrics['grid_dependency'],
            text=[f"{val:.1f}%" for val in df_metrics['grid_dependency']],
            textposition='outside',
            marker_color=PlotStyler.COLORS[1],
            width=0.3,
            offset=0.2,
            textfont={'size': PlotStyler.ANNOTATION_FONT_SIZE}
        ))
        
        # Style metrics plot
        fig_metrics = PlotStyler.style_single_plot(
            fig_metrics,
            title="System Performance Metrics",
            x_label="Configuration",
            y_label="Percentage (%)"
        )
        
        # Update metrics plot layout
        fig_metrics.update_layout(
            barmode='group',
            bargap=0.15,
            bargroupgap=0.1,
            yaxis=dict(
                range=[0, max(max(df_metrics['pv_utilization']), 
                            max(df_metrics['grid_dependency'])) * 1.15]
            ),
            width=PlotStyler.SINGLE_PLOT_WIDTH,
            height=PlotStyler.SINGLE_PLOT_HEIGHT,
            margin=PlotStyler.MARGIN,
            showlegend=True,
            legend=PlotStyler.LEGEND_SETTINGS
        )
        
        # Save metrics plot
        PlotStyler.save_plot(fig_metrics, "mechanism_metrics.png", mechanism_dir)
        
        # Create daily profile plot to show alignment of PV with solar radiation
        fig_daily = go.Figure()
        
        # Filter to a single day for clarity
        day_mask = (df_timeseries['timestamp'] >= '2024-05-01') & (df_timeseries['timestamp'] < '2024-05-02')
        df_day = df_timeseries[day_mask]
        
        # Add radiation trace
        if 'total_radiation_W/m2' in df_day.columns:
            fig_daily.add_trace(go.Scatter(
                x=df_day['timestamp'],
                y=df_day['total_radiation_W/m2'],
                name='Radiation',
                line=dict(color='rgba(255,215,0,0.7)', width=3, dash='dot'),
                yaxis='y2'
            ))
        
        # Add PV for both start hours
        for start_hour in start_hours:
            pv_prefix = f'h{start_hour:02d}_pv_only'
            fig_daily.add_trace(go.Scatter(
                x=df_day['timestamp'],
                y=df_day[f'{pv_prefix}_pv_generation'],
                name=f'PV Gen (Start: {start_hour:02d}:00)',
                line=dict(color=PlotStyler.COLORS[start_hours.index(start_hour)], width=3)
            ))
        
        # Update layout with secondary y-axis
        fig_daily.update_layout(
            yaxis2=dict(
                title="Solar Radiation (W/m²)",
                overlaying="y",
                side="right",
                showgrid=False,
                showline=True,
                linewidth=PlotStyler.BORDER_WIDTH,
                linecolor=PlotStyler.BORDER_COLOR,
                mirror=True,
                tickfont={'family': PlotStyler.FONT_FAMILY, 'size': PlotStyler.TICK_FONT_SIZE}
            ),
            width=PlotStyler.SINGLE_PLOT_WIDTH,
            height=PlotStyler.SINGLE_PLOT_HEIGHT,
            margin=PlotStyler.MARGIN,
            showlegend=True,
            legend=PlotStyler.LEGEND_SETTINGS
        )
        
        fig_daily = PlotStyler.style_single_plot(
            fig_daily,
            title="Daily Profile: PV vs Solar Radiation",
            x_label="Time",
            y_label="Power (kW)"
        )
        
        # Save daily profile plot
        PlotStyler.save_plot(fig_daily, "mechanism_daily_profile.png", mechanism_dir)
        
        logger.info("Mechanism analysis plots saved successfully")
        
    except Exception as e:
        logger.error(f"Error in analyze_mechanism_results: {str(e)}")
        logger.error(traceback.format_exc())
        raise

if __name__ == "__main__":
    # Set up logging
    logging.basicConfig(level=logging.INFO,
                       format='%(asctime)s - %(levelname)s - %(message)s')
    
    # Declare global variables
    global MERGED_RESULTS_DF
    
    # Add argument parser for mechanism analysis
    parser = argparse.ArgumentParser(description='Analysis tools for PV-Battery system results')
    parser.add_argument('--mode', type=str, required=True, 
                       choices=['climate', 'mechanism'],
                       help='Analysis mode: climate or mechanism')
    
    # Arguments for mechanism analysis with defaults
    parser.add_argument('--timeseries-file', type=str,
                       default="G:/PVBES_Design/test_case/shanghai/results/shanghai_mechanism_analysis_pv_30.0m2_battery_10.0kWh_start_hour1_04_start_hour2_20.csv",
                       help='Path to mechanism timeseries CSV file')
    parser.add_argument('--metrics-file', type=str,
                       default="G:/PVBES_Design/test_case/shanghai/results/shanghai_mechanism_analysis_metrics_pv_30.0m2_battery_10.0kWh_start_hour1_04_start_hour2_20.csv",
                       help='Path to mechanism metrics CSV file')
    parser.add_argument('--output-dir', type=str, default='results',
                       help='Directory to save output files')
    
    args = parser.parse_args()
    output_dir = Path(args.output_dir)
    
    if args.mode == 'mechanism':
        timeseries_file = Path(args.timeseries_file)
        metrics_file = Path(args.metrics_file)
        
        if not all([timeseries_file.exists(), metrics_file.exists()]):
            parser.error("Input files not found")
            
        analyze_mechanism_results(
            timeseries_file=timeseries_file,
            metrics_file=metrics_file,
            output_dir=output_dir
        )
    else:  # climate mode
        print(f"Saving outputs to {output_dir}")
        
        # Merge all enumeration results at the start
        MERGED_RESULTS_DF = merge_enumeration_results()
        
        analyze_city_climate_energy(
            output_dir=output_dir
        )
    
    print("Analysis complete")