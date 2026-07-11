import os
import sys
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from pathlib import Path
import logging
import traceback

# Try to import PlotStyler from src.visualization
try:
    from src.visualization import PlotStyler
except ImportError:
    # Define a simplified PlotStyler class if the import fails
    class PlotStyler:
        """Simplified PlotStyler class for styling plots"""
        COLORS = ['rgba(55, 126, 184, 0.7)', 'rgba(228, 26, 28, 0.7)', 
                 'rgba(77, 175, 74, 0.7)', 'rgba(152, 78, 163, 0.7)', 
                 'rgba(255, 127, 0, 0.7)']
        ERROR_BAR_COLOR = 'rgba(55, 126, 184, 1.0)'
        
        @staticmethod
        def style_single_plot(fig, title=None, x_label=None, y_label=None):
            """Apply styling to a single plot"""
            fig.update_layout(
                title=title,
                xaxis_title=x_label,
                yaxis_title=y_label,
                template="plotly_white",
                font=dict(family="Arial", size=12),
                margin=dict(l=50, r=50, t=80, b=50),
            )
            return fig
            
        @staticmethod
        def save_plot(fig, filename, output_dir):
            """Save plot as image and HTML"""
            # Ensure output directory exists
            output_dir = Path(output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
            
            # Save plot
            fig.write_image(output_dir / filename)
            fig.write_html(output_dir / f"{filename.split('.')[0]}.html")

# Configure logging
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Cities to analyze
CITIES_TO_ANALYZE = ['shanghai', 'harbin', 'haikou', 'lasa', 'urumqi']

# Display names for cities
CITY_DISPLAY_NAMES = {
    'shanghai': 'Shanghai',
    'harbin': 'Harbin',
    'lasa': 'Lasa',
    'urumqi': 'Urumqi',
    'haikou': 'Haikou'
}

# Standard display order for cities on x-axis
STANDARD_CITY_DISPLAY_ORDER = ['Shanghai', 'Harbin', 'Lasa', 'Urumqi', 'Haikou']

def calculate_daily_hvac_means(city, start_hour):
    """
    Calculate daily mean HVAC_kW for a specific city and photoperiod start hour.
    
    This function finds the load profile file for the given city and photoperiod
    start hour, reads the file, and calculates the daily mean of HVAC_kW values.
    
    Args:
        city (str): City name (e.g., 'shanghai', 'harbin')
        start_hour (int): Photoperiod start hour (1-23)
    
    Returns:
        float: Daily mean HVAC_kW value, or None if file not found or error occurs
    """
    try:
        # Calculate the end hour (start hour + 16) with wraparound
        end_hour = (start_hour + 16) % 24
        
        # Format the hours for filename
        start_hour_str = f"{start_hour:02d}"
        end_hour_str = f"{end_hour:02d}"
        
        # Construct file path
        file_path = Path(f"test_case/{city}/output/annual_energy_schedule_{start_hour_str}_{end_hour_str}.csv")
        
        # Check if file exists
        if not file_path.exists():
            logger.warning(f"File not found for {city} with start hour {start_hour}: {file_path}")
            return None
        
        # Read the CSV file
        df = pd.read_csv(file_path)
        
        # Convert time column to datetime
        df['time'] = pd.to_datetime(df['time'])
        
        # Create a date column
        df['date'] = df['time'].dt.date
        
        # Calculate daily mean of HVAC_kW
        daily_hvac = df.groupby('date')['HVAC_kW'].mean()
        
        # Return the mean of daily means
        return daily_hvac.mean()
    
    except Exception as e:
        logger.error(f"Error processing {city} with start hour {start_hour}: {str(e)}")
        return None

def analyze_hvac_profiles():
    """
    Analyze HVAC load profiles for different photoperiod start hours across cities.
    
    This function:
    1. Processes all cities in CITIES_TO_ANALYZE
    2. For each city, analyzes load profiles with photoperiod start hours 1-23
    3. Calculates the mean and standard deviation of daily HVAC_kW values
    4. Orders cities according to STANDARD_CITY_DISPLAY_ORDER
    5. Saves results to CSV
    
    Returns:
        pd.DataFrame: DataFrame with mean and std of daily HVAC_kW for each city
    """
    # Dictionary to store results
    results = {
        'City': [],
        'Mean_HVAC_Energy': [],
        'Std_HVAC_Energy': [],
        'Min_HVAC_Energy': [],
        'Max_HVAC_Energy': []
    }
    
    # Dictionary to store detailed data for each city and start hour
    detailed_results = {
        'City': [],
        'Start_Hour': [],
        'HVAC_Energy': []
    }
    
    # Process each city
    for city in CITIES_TO_ANALYZE:
        logger.info(f"Processing {city}...")
        
        # Store daily HVAC means for different start hours
        daily_hvac_means = []
        city_display_name = CITY_DISPLAY_NAMES[city]
        
        # Calculate daily HVAC means for start hours 1-23
        for start_hour in range(1, 24):
            daily_mean = calculate_daily_hvac_means(city, start_hour)
            if daily_mean is not None:
                daily_hvac_means.append(daily_mean)
                # Add to detailed results
                detailed_results['City'].append(city_display_name)
                detailed_results['Start_Hour'].append(start_hour)
                detailed_results['HVAC_Energy'].append(daily_mean)
        
        # Skip if no valid data found
        if not daily_hvac_means:
            logger.warning(f"No valid data found for {city}")
            continue
        
        # Calculate statistics
        results['City'].append(city_display_name)
        results['Mean_HVAC_Energy'].append(np.mean(daily_hvac_means))
        results['Std_HVAC_Energy'].append(np.std(daily_hvac_means))
        results['Min_HVAC_Energy'].append(np.min(daily_hvac_means))
        results['Max_HVAC_Energy'].append(np.max(daily_hvac_means))
    
    # Create DataFrame
    df = pd.DataFrame(results)
    
    # Order cities according to standard display order
    df['City_Order'] = df['City'].map({city: i for i, city in enumerate(STANDARD_CITY_DISPLAY_ORDER)})
    df = df.sort_values('City_Order')
    
    # Create detailed DataFrame
    detailed_df = pd.DataFrame(detailed_results)
    
    # Save results to CSV
    output_dir = Path("results/city_climate_energy")
    output_dir.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_dir / "hvac_schedule_data.csv", index=False)
    detailed_df.to_csv(output_dir / "Climates_C_hvac_schedule_data.csv", index=False)
    
    return df

def create_hvac_schedule_plot(hvac_df):
    """
    Create and save plot showing HVAC Energy by City with Schedule Variation.
    
    This function creates a bar chart similar to the one in the original
    create_hvac_schedule_plot function, with error bars representing
    the standard deviation of daily HVAC_kW values for different start hours.
    
    Args:
        hvac_df (pd.DataFrame): DataFrame with HVAC data
    """
    try:
        # Create plot
        fig = go.Figure()
        
        # Add bar chart with error bars
        fig.add_trace(go.Bar(
            x=hvac_df['City'],
            y=hvac_df['Mean_HVAC_Energy'],
            name='Daily HVAC Energy',
            marker_color=PlotStyler.COLORS[2] if hasattr(PlotStyler, 'COLORS') else 'rgba(55, 126, 184, 0.7)',
            error_y=dict(
                type='data',
                array=hvac_df['Std_HVAC_Energy'],
                visible=True,
                color=PlotStyler.ERROR_BAR_COLOR if hasattr(PlotStyler, 'ERROR_BAR_COLOR') else 'rgba(55, 126, 184, 1.0)',
                thickness=2,
                width=6
            ),
            hovertemplate="<br>".join([
                "City: %{x}",
                "HVAC Energy: %{y:.2f} kWh",
                "<extra></extra>"
            ])
        ))
        
        # Style the plot using PlotStyler if available
        if hasattr(PlotStyler, 'style_single_plot'):
            fig = PlotStyler.style_single_plot(
                fig,
                title="(c) Daily HVAC Energy by City",
                x_label="City",
                y_label="Daily HVAC Energy (kWh)"
            )
        else:
            # Fallback styling
            fig.update_layout(
                title="(c) Daily HVAC Energy by City",
                xaxis_title="City",
                yaxis_title="Daily HVAC Energy (kWh)",
                template="plotly_white",
                barmode='group',
                bargap=0.15,
                bargroupgap=0.1,
                width=800,
                height=500
            )
        
        # Update layout
        fig.update_layout(
            barmode='group',
            bargap=0.15,
            bargroupgap=0.1,
        )
        
        # Save plot
        output_dir = Path("results/city_climate_energy")
        output_dir.mkdir(parents=True, exist_ok=True)
        
        if hasattr(PlotStyler, 'save_plot'):
            PlotStyler.save_plot(fig, "Climates_C_hvac_schedule_analysis.png", output_dir)
        else:
            # Fallback save method
            fig.write_image(output_dir / "Climates_C_hvac_schedule_analysis.png")
            fig.write_html(output_dir / "Climates_C_hvac_schedule_analysis.html")
        
        logger.info("Saved HVAC schedule analysis plot and data")
        
    except Exception as e:
        logger.error(f"Error creating HVAC schedule plot: {str(e)}")
        logger.error(traceback.format_exc())

def create_hvac_start_hour_plot(detailed_df):
    """
    Create a plot showing how HVAC energy varies with different photoperiod start hours for each city.
    
    Args:
        detailed_df (pd.DataFrame): DataFrame with detailed HVAC data by city and start hour
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
                    color=PlotStyler.COLORS[i % len(PlotStyler.COLORS)] if hasattr(PlotStyler, 'COLORS') else None,
                    width=2
                ),
                marker=dict(size=6),
                hovertemplate="<br>".join([
                    "City: %{fullData.name}",
                    "Start Hour: %{x}:00",
                    "HVAC Energy: %{y:.4f} kWh",
                    "<extra></extra>"
                ])
            ))
        
        # Style the plot
        if hasattr(PlotStyler, 'style_single_plot'):
            fig = PlotStyler.style_single_plot(
                fig,
                title="HVAC Energy vs Photoperiod Start Hour",
                x_label="Photoperiod Start Hour",
                y_label="Daily HVAC Energy (kWh)"
            )
        else:
            fig.update_layout(
                title="HVAC Energy vs Photoperiod Start Hour",
                xaxis_title="Photoperiod Start Hour",
                yaxis_title="Daily HVAC Energy (kWh)",
                template="plotly_white",
                legend=dict(
                    orientation="h",
                    yanchor="bottom",
                    y=1.02,
                    xanchor="right",
                    x=1
                )
            )
        
        # Update x-axis to show every hour
        fig.update_xaxes(
            tickmode='linear',
            tick0=1,
            dtick=1
        )
        
        # Save plot
        output_dir = Path("results/city_climate_energy")
        output_dir.mkdir(parents=True, exist_ok=True)
        
        if hasattr(PlotStyler, 'save_plot'):
            PlotStyler.save_plot(fig, "HVAC_vs_start_hour.png", output_dir)
        else:
            fig.write_image(output_dir / "HVAC_vs_start_hour.png")
            fig.write_html(output_dir / "HVAC_vs_start_hour.html")
            
        logger.info("Saved HVAC vs start hour plot")
        
    except Exception as e:
        logger.error(f"Error creating HVAC vs start hour plot: {str(e)}")
        logger.error(traceback.format_exc())

def main():
    """
    Main function to execute the HVAC load profile analysis.
    
    This function:
    1. Analyzes HVAC profiles for all cities
    2. Creates and saves the HVAC schedule plot
    """
    try:
        # Analyze HVAC profiles
        hvac_df = analyze_hvac_profiles()
        
        # Create bar plot
        create_hvac_schedule_plot(hvac_df)
        
        # Load detailed data
        detailed_df = pd.read_csv(Path("results/city_climate_energy/Climates_C_hvac_schedule_data.csv"))
        
        # Create start hour line plot
        create_hvac_start_hour_plot(detailed_df)
        
        logger.info("HVAC analysis completed successfully")
        
        # Display summary of results
        print("\nSummary of Daily HVAC Energy by City:")
        print("=====================================")
        for _, row in hvac_df.sort_values('City_Order').iterrows():
            print(f"{row['City']}: {row['Mean_HVAC_Energy']:.4f} kWh (±{row['Std_HVAC_Energy']:.4f})")
        
    except Exception as e:
        logger.error(f"Error in main execution: {str(e)}")
        logger.error(traceback.format_exc())

if __name__ == "__main__":
    main() 