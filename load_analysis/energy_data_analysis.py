import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from sklearn.metrics import r2_score, mean_squared_error
from tqdm import tqdm
import warnings
from deap import base, creator, tools, algorithms
import random
import os
from src.visualization import PlotStyler
from PIL import Image
import base64
import io

# Path handling utility
def find_valid_path(relative_path, possible_drives=["D:", "G:"]):
    """
    Check for file existence in different drive paths and return the valid path.
    
    Args:
        relative_path (str): Relative path to the file
        possible_drives (list): List of drive letters to check
        
    Returns:
        str: Valid absolute path if found, otherwise returns the original relative path
    """
    # First try the relative path as is (in case it's already accessible)
    if os.path.exists(relative_path):
        return relative_path
    
    # Then try different drive letters
    for drive in possible_drives:
        potential_path = os.path.join(drive, relative_path.lstrip("/").lstrip("\\"))
        if os.path.exists(potential_path):
            print(f"Found file at: {potential_path}")
            return potential_path
    
    # If no valid path found, return the original
    print(f"Warning: Could not find valid path for {relative_path}. Using as-is.")
    return relative_path

# Common Utilities
def calculate_metrics(y_true, y_pred):
    """Calculate R2, NMBE and CV(RMSE)"""
    r2 = r2_score(y_true, y_pred)
    nmbe = np.mean(y_pred - y_true) / np.mean(y_true)
    cvrmse = np.sqrt(mean_squared_error(y_true, y_pred)) / np.mean(y_true)
    return r2, nmbe, cvrmse


def analyze_seasonal_energy(data_path, output_dir="load_analysis"):
    """
    Function 1: Analyze seasonal energy consumption patterns
    
    Args:
        data_path (str): Path to the processed data CSV file
        output_dir (str): Directory to save output files
        
    Returns:
        tuple: Seasonal power and energy averages DataFrames
    """
    # Ensure valid paths
    data_path = find_valid_path(data_path)
    output_dir = find_valid_path(output_dir)
    
    print("Loading and processing data...")
    processed_data = pd.read_csv(data_path)
    processed_data['time'] = pd.to_datetime(processed_data['time'])
    processed_data['date'] = processed_data['time'].dt.date
    
    # Calculate daily consumption
    print("Calculating daily consumption...")
    daily_consumption = processed_data.groupby(['date', 'Season']).agg({
        'HVAC_kW': 'mean',
        'LED1_kW': 'mean', 
        'LED2_kW': 'mean',
        'LED3_kW': 'mean',
        'FFU_kW': 'mean',
        'FAU_kW': 'mean'
    }).reset_index()

    daily_consumption['LED_total'] = (daily_consumption['LED1_kW'] + 
                                    daily_consumption['LED2_kW'] + 
                                    daily_consumption['LED3_kW'])

    daily_consumption['Total'] = (daily_consumption['HVAC_kW'] + 
                                daily_consumption['LED_total'] + 
                                daily_consumption['FFU_kW'] +
                                daily_consumption['FAU_kW'])

    # Calculate seasonal averages
    seasonal_avg = daily_consumption.groupby('Season').agg({
        'HVAC_kW': ['mean', 'std'],
        'LED_total': ['mean', 'std'],
        'FFU_kW': ['mean', 'std'], 
        'FAU_kW': ['mean', 'std'],
        'Total': ['mean', 'std']
    }).round(3)

    print("\nCreating power consumption plot...")
    seasons = ['spring', 'summer', 'fall', 'winter']
    components = ['HVAC_kW', 'LED_total', 'FFU_kW', 'FAU_kW', 'Total']

    fig = go.Figure()

    for i, component in enumerate(components):
        seasonal_means = [daily_consumption[daily_consumption['Season']==season][component].mean() 
                         for season in seasons]
        
        fig.add_trace(go.Bar(
            name=component.replace('_kW','').replace('_total',''),
            x=seasons,
            y=seasonal_means,
            marker_color=PlotStyler.COLORS[i % len(PlotStyler.COLORS)],
            text=[f'{x:.1f}' for x in seasonal_means],
            textposition='outside',
            textfont={'size': PlotStyler.ANNOTATION_FONT_SIZE}
        ))

    fig = PlotStyler.style_single_plot(
        fig,
        'Average Daily Power Consumption by Season and Component',
        'Power (kW)',
        'Season'
    )
    PlotStyler.save_plot(fig, "seasonal_power_consumption.png", output_dir)

    # Calculate daily energy consumption
    print("\nCalculating daily energy consumption...")
    daily_energy = processed_data.groupby(['date', 'Season']).agg({
        'HVAC_kW': lambda x: x.mean() * 24,
        'LED1_kW': lambda x: x.mean() * 24,
        'LED2_kW': lambda x: x.mean() * 24,
        'LED3_kW': lambda x: x.mean() * 24,
        'FFU_kW': lambda x: x.mean() * 24,
        'FAU_kW': lambda x: x.mean() * 24
    }).reset_index()

    # Rename columns to reflect kWh units
    daily_energy = daily_energy.rename(columns={
        'HVAC_kW': 'HVAC_kWh',
        'LED1_kW': 'LED1_kWh',
        'LED2_kW': 'LED2_kWh',
        'LED3_kW': 'LED3_kWh',
        'FFU_kW': 'FFU_kWh',
        'FAU_kW': 'FAU_kWh'
    })

    daily_energy['LED_total_kWh'] = (daily_energy['LED1_kWh'] + 
                                    daily_energy['LED2_kWh'] + 
                                    daily_energy['LED3_kWh'])

    daily_energy['Total_kWh'] = (daily_energy['HVAC_kWh'] +
                                daily_energy['LED_total_kWh'] +
                                daily_energy['FFU_kWh'] +
                                daily_energy['FAU_kWh'])

    components_kwh = ['HVAC_kWh', 'LED_total_kWh', 'FFU_kWh', 'FAU_kWh', 'Total_kWh']
    
    fig2 = go.Figure()

    for i, component in enumerate(components_kwh):
        seasonal_means = [daily_energy[daily_energy['Season']==season][component].mean() 
                         for season in seasons]
        
        fig2.add_trace(go.Bar(
            name=component.replace('_kWh','').replace('_total',''),
            x=seasons,
            y=seasonal_means,
            marker_color=PlotStyler.COLORS[i % len(PlotStyler.COLORS)],
            text=[f'{x:.1f}' for x in seasonal_means],
            textposition='outside',
            textfont={'size': PlotStyler.ANNOTATION_FONT_SIZE}
        ))

    fig2 = PlotStyler.style_single_plot(
        fig2,
        'Average Daily Energy Consumption by Season and Component',
        'Energy (kWh/day)',
        'Season'
    )
    PlotStyler.save_plot(fig2, "seasonal_energy_consumption.png", output_dir)

    return seasonal_avg, daily_energy.groupby('Season').agg({
        'HVAC_kWh': ['mean', 'std'],
        'LED_total_kWh': ['mean', 'std'],
        'FFU_kWh': ['mean', 'std'],
        'FAU_kWh': ['mean', 'std'],
        'Total_kWh': ['mean', 'std']
    }).round(2)

def analyze_cop_power_relationship(data_path, rated_power=1.65, output_dir="load_analysis"):
    """
    Function 2: Analyze COP and power consumption relationship
    
    Args:
        data_path (str): Path to the processed data CSV file
        rated_power (float): Rated power in kW
        output_dir (str): Directory to save output files
        
    Returns:
        DataFrame: COP analysis results
    """
    # Ensure valid paths
    data_path = find_valid_path(data_path)
    output_dir = find_valid_path(output_dir)
    
    print("Loading and processing data...")
    processed_data = pd.read_csv(data_path)
    
    # First, analyze COP time distribution without filtering
    print("\nAnalyzing COP time distribution...")
    cop_ranges = [
        (0, 2), (2, 4), (4, 6), (6, 8), (8, 10), (10, 12), (12, float('inf'))
    ]
    time_dist = []
    seasons = ['spring', 'summer', 'fall', 'winter']

    # Calculate for each season
    for season in seasons:
        season_data = processed_data[processed_data['Season'] == season]
        total_hours = len(season_data)
        
        for cop_min, cop_max in cop_ranges:
            hours = len(season_data[(season_data['actual_cop'] >= cop_min) & 
                                  (season_data['actual_cop'] < cop_max)])
            percentage = hours / total_hours * 100
            
            # Format range string for better display
            range_str = f"{cop_min}-{int(cop_max)}" if cop_max != float('inf') else f"≥{cop_min}"
            
            time_dist.append({
                'season': season,
                'cop_range': range_str,
                'hours': hours,
                'percentage': percentage,
                'range_min': cop_min  # 添加用于排序的字段
            })

    # Calculate overall statistics
    total_hours = len(processed_data)
    overall_stats = []

    for cop_min, cop_max in cop_ranges:
        hours = len(processed_data[(processed_data['actual_cop'] >= cop_min) & 
                                (processed_data['actual_cop'] < cop_max)])
        percentage = hours / total_hours * 100
        
        # Format range string for better display
        range_str = f"{cop_min}-{int(cop_max)}" if cop_max != float('inf') else f"≥{cop_min}"
        
        overall_stats.append({
            'season': 'Overall',
            'cop_range': range_str,
            'hours': hours,
            'percentage': percentage,
            'range_min': cop_min  # 添加用于排序的字段
        })

    time_dist_df = pd.concat([pd.DataFrame(time_dist), pd.DataFrame(overall_stats)])
    
    # Sort by range_min to ensure correct order
    time_dist_df = time_dist_df.sort_values('range_min')
    time_dist_df.to_csv(os.path.join(output_dir, 'cop_time_distribution.csv'), index=False)

    # Create time distribution plots
    for season in seasons + ['Overall']:
        season_data = time_dist_df[time_dist_df['season'] == season]
        
        fig = go.Figure()
        
        # Add percentage bars
        fig.add_trace(go.Bar(
            x=season_data['cop_range'],
            y=season_data['percentage'],
            marker_color=PlotStyler.BAR_COLORS[0],  # 使用半透明的柱状图颜色
            text=[f'{x:.1f}%' for x in season_data['percentage']],
            textposition='outside',
            textfont={'size': PlotStyler.ANNOTATION_FONT_SIZE},
            name='Percentage'
        ))

        # Add hour count as a line
        fig.add_trace(go.Scatter(
            x=season_data['cop_range'],
            y=season_data['hours'],
            yaxis='y2',
            mode='lines+markers',
            line=dict(color=PlotStyler.COLORS[1], width=2),
            marker=dict(size=8),
            name='Hours'
        ))

        # Update layout with dual axes
        fig.update_layout(
            yaxis2=dict(
                title='Hours',
                overlaying='y',
                side='right',
                showgrid=False
            ),
            yaxis_title='Percentage of Time (%)'
        )

        fig = PlotStyler.style_single_plot(
            fig,
            f'COP Distribution - {season.capitalize()}',
            'Percentage of Time (%)',
            'COP Range'
        )

        # Ensure x-axis shows all COP ranges
        fig.update_xaxes(
            type='category',
            categoryorder='array',
            categoryarray=season_data['cop_range'].tolist()
        )

        PlotStyler.save_plot(fig, f"cop_time_dist_{season.lower()}.png", output_dir)

    # Filter data for COP-Power relationship as we do not consider COP > 6.3 that can't be explained in this study
    mask = (processed_data['actual_cop'] < 6.3) & (processed_data['HVAC_kW'] > 0.08)
    filtered_data = processed_data[mask]
    
    # Now analyze COP-Power relationship
    print("\nAnalyzing COP-Power relationship...")
    power_ranges = [
        (0, 0.05), (0.05, 0.1), (0.1, 0.2), (0.2, 0.3),
        (0.3, 0.4), (0.4, 0.5), (0.5, 0.6), (0.6, 0.7),
        (0.7, 0.8), (0.8, 0.9), (0.9, 1.0)
    ]
    
    range_stats = []
    
    # Calculate statistics for each season and power range
    for season in seasons + ['Overall']:
        if season == 'Overall':
            season_data = filtered_data
        else:
            season_data = filtered_data[filtered_data['Season'] == season]
        
        for lower_pct, upper_pct in power_ranges:
            lower_kw = rated_power * lower_pct
            upper_kw = rated_power * upper_pct
            
            mask = (season_data['HVAC_kW'] >= lower_kw) & (season_data['HVAC_kW'] < upper_kw)
            range_data = season_data[mask]
            
            if len(range_data) > 0:
                stats = {
                    'season': season,
                    'power_range': f"{lower_pct*100:.0f}-{upper_pct*100:.0f}%",
                    'power_kw': f"{lower_kw:.2f}-{upper_kw:.2f}",
                    'count': len(range_data),
                    'mean_cop': range_data['actual_cop'].mean(),
                    'std_cop': range_data['actual_cop'].std(),
                    'min_cop': range_data['actual_cop'].min(),
                    'max_cop': range_data['actual_cop'].max()
                }
                range_stats.append(stats)
    
    cop_analysis = pd.DataFrame(range_stats)
    
    # Create individual plots for each season and overall
    for season in seasons + ['Overall']:
        season_data = cop_analysis[cop_analysis['season'] == season]
        
        fig = go.Figure()
        
        # Add mean COP bars with error bars
        fig.add_trace(go.Bar(
            x=season_data['power_range'],
            y=season_data['mean_cop'],
            error_y=dict(
                type='data',
                array=season_data['std_cop'],
                color=PlotStyler.ERROR_BAR_COLOR,  # 使用深色不透明的误差线
                thickness=2,  # 加粗误差线
                width=6  # 增加误差线横杠的宽度
            ),
            name='Mean COP',
            marker_color=PlotStyler.BAR_COLORS[0],  # 使用半透明的柱状图颜色
            text=[f'{x:.2f}' for x in season_data['mean_cop']],
            textposition='outside',
            textfont={'size': PlotStyler.ANNOTATION_FONT_SIZE}
        ))
        
        # Add min/max lines
        fig.add_trace(go.Scatter(
            x=season_data['power_range'],
            y=season_data['min_cop'],
            mode='lines+markers',
            name='Min COP',
            line=dict(color=PlotStyler.COLORS[1], dash='dash')
        ))
        
        fig.add_trace(go.Scatter(
            x=season_data['power_range'],
            y=season_data['max_cop'],
            mode='lines+markers',
            name='Max COP',
            line=dict(color=PlotStyler.COLORS[2], dash='dash')
        ))
        
        fig = PlotStyler.style_single_plot(
            fig,
            f'COP vs Power Range - {season.capitalize()}',
            'COP',
            'Power Range (% of Rated Power)'
        )
        
        # Update x-axis
        fig.update_xaxes(tickangle=45)
        
        PlotStyler.save_plot(fig, f"cop_power_dist_{season.lower()}.png", output_dir)
    
    return cop_analysis

def analyze_cop_clustering(data_path, output_dir="load_analysis"):
    """
    Function 3: Perform COP clustering analysis
    
    Args:
        data_path (str): Path to the processed data CSV file
        output_dir (str): Directory to save output files
        
    Returns:
        DataFrame: T_lif analysis results
    """
    # Ensure valid paths
    data_path = find_valid_path(data_path)
    output_dir = find_valid_path(output_dir)
    
    print("Loading and processing data...")
    processed_data = pd.read_csv(data_path)
    
    # Filter data
    mask = (processed_data['actual_cop'] < 6.3) & (processed_data['HVAC_kW'] > 0.08)
    filtered_data = processed_data[mask]
    
    # Calculate T_lif
    filtered_data['time'] = pd.to_datetime(filtered_data['time'])
    filtered_data['T_lif'] = np.where(
        (filtered_data['time'].dt.hour >= 6) & (filtered_data['time'].dt.hour <= 22),
        filtered_data['Outdoor_Temp_C'] - 22,
        filtered_data['Outdoor_Temp_C'] - 16
    )
    
    # Define genetic algorithm parameters
    MIN_T_LIF = -20
    MAX_T_LIF = 30
    N_RANGES = 15
    
    # Create fitness class and individual type
    creator.create("FitnessMin", base.Fitness, weights=(-1.0,))
    creator.create("Individual", list, fitness=creator.FitnessMin)
    
    def get_ranges(individual):
        breakpoints = sorted([MIN_T_LIF + (MAX_T_LIF - MIN_T_LIF) * x for x in individual])
        ranges = [(float('-inf'), MIN_T_LIF)]
        
        for i in range(len(breakpoints)-1):
            ranges.append((breakpoints[i], breakpoints[i+1]))
            
        ranges.append((MAX_T_LIF, float('inf')))
        
        final_neg_inf_max = float('-inf')
        for r in ranges:
            if r[1] == float('inf'):
                continue
            if r[0] == float('-inf'):
                final_neg_inf_max = max(final_neg_inf_max, r[1])
        
        adjusted_ranges = []
        for r in ranges:
            if r[1] != float('inf'):
                adjusted_ranges.append((r[0], max(r[1], final_neg_inf_max)))
            else:
                adjusted_ranges.append(r)
                
        return adjusted_ranges
    
    def evaluate(individual):
        ranges = get_ranges(individual)
        all_data = filtered_data
        y_true = all_data['actual_cop']
        y_pred = all_data['actual_cop'].mean() * np.ones(len(all_data))
        _, _, cvrmse = calculate_metrics(y_true, y_pred)
        return (cvrmse,)
    
    # Initialize genetic algorithm
    toolbox = base.Toolbox()
    toolbox.register("attr_float", random.random)
    toolbox.register("individual", tools.initRepeat, creator.Individual, toolbox.attr_float, n=N_RANGES-1)
    toolbox.register("population", tools.initRepeat, list, toolbox.individual)
    toolbox.register("evaluate", evaluate)
    toolbox.register("mate", tools.cxUniform, indpb=0.5)
    toolbox.register("mutate", tools.mutGaussian, mu=0, sigma=0.1, indpb=0.3)
    toolbox.register("select", tools.selTournament, tournsize=5)
    
    # Run genetic algorithm
    pop = toolbox.population(n=150)
    NGEN = 150
    CXPB = 0.8
    MUTPB = 0.4
    
    stats = tools.Statistics(lambda ind: ind.fitness.values)
    stats.register("avg", np.mean)
    stats.register("min", np.min)
    stats.register("max", np.max)
    
    best_solution = None
    best_fitness = float('inf')
    n_runs = 5
    
    for run in range(n_runs):
        random.seed(run)
        pop = toolbox.population(n=150)
        
        pop, _ = algorithms.eaSimple(pop, toolbox, CXPB, MUTPB, NGEN, 
                                   stats=stats, verbose=True)
        
        best_ind = tools.selBest(pop, k=1)[0]
        if best_ind.fitness.values[0] < best_fitness:
            best_fitness = best_ind.fitness.values[0]
            best_solution = best_ind
    
    # Analyze using optimal ranges
    optimal_ranges = get_ranges(best_solution)
    t_lif_stats = []
    
    for t_lif_range in optimal_ranges:
        mask = (filtered_data['T_lif'] >= t_lif_range[0]) & (filtered_data['T_lif'] <= t_lif_range[1])
        range_data = filtered_data[mask]
        
        if len(range_data) > 0:
            y_true = range_data['actual_cop']
            y_pred = range_data['actual_cop'].mean() * np.ones(len(range_data))
            _, _, cvrmse = calculate_metrics(y_true, y_pred)
            
            stats = {
                'T_lif_range': f"{t_lif_range[0]:.1f}-{t_lif_range[1]:.1f}",
                'T_lif_min': t_lif_range[0],
                'T_lif_max': t_lif_range[1],
                'count': len(range_data),
                'mean_cop': range_data['actual_cop'].mean(),
                'std_cop': range_data['actual_cop'].std(),
                'mean_hvac_kw': range_data['HVAC_kW'].mean(),
                'std_hvac_kw': range_data['HVAC_kW'].std(),
                'cvrmse': cvrmse,
                'min_cop': range_data['actual_cop'].min(),
                'max_cop': range_data['actual_cop'].max()
            }
            t_lif_stats.append(stats)
    
    t_lif_analysis = pd.DataFrame(t_lif_stats)
    
    # Create individual plots
    
    # 1. COP vs T_lif plot
    fig_cop = go.Figure()
    
    # Add mean COP bars with error bars
    fig_cop.add_trace(go.Bar(
        x=t_lif_analysis['T_lif_range'],
        y=t_lif_analysis['mean_cop'],
        error_y=dict(
            type='data',
            array=t_lif_analysis['std_cop'],
            color=PlotStyler.ERROR_BAR_COLOR,
            thickness=2,
            width=6
        ),
        name='Mean COP',
        marker_color=PlotStyler.BAR_COLORS[0],
        text=[f'{x:.2f}' for x in t_lif_analysis['mean_cop']],
        textposition='outside',
        textfont={'size': PlotStyler.ANNOTATION_FONT_SIZE}
    ))
    
    # Add min/max COP lines
    fig_cop.add_trace(go.Scatter(
        x=t_lif_analysis['T_lif_range'],
        y=t_lif_analysis['min_cop'],
        mode='lines+markers',
        name='Min COP',
        line=dict(color=PlotStyler.COLORS[1], dash='dash')
    ))
    
    fig_cop.add_trace(go.Scatter(
        x=t_lif_analysis['T_lif_range'],
        y=t_lif_analysis['max_cop'],
        mode='lines+markers',
        name='Max COP',
        line=dict(color=PlotStyler.COLORS[2], dash='dash')
    ))
    
    fig_cop = PlotStyler.style_single_plot(
        fig_cop,
        'COP Distribution by T_lif Range',
        'COP',
        'T_lif Range'
    )
    fig_cop.update_xaxes(tickangle=45)
    PlotStyler.save_plot(fig_cop, "cop_vs_tlif.png", output_dir)
    
    # 2. Mean HVAC kW vs T_lif plot
    fig_power = go.Figure()
    
    fig_power.add_trace(go.Bar(
        x=t_lif_analysis['T_lif_range'],
        y=t_lif_analysis['mean_hvac_kw'],
        error_y=dict(
            type='data',
            array=t_lif_analysis['std_hvac_kw'],
            color=PlotStyler.ERROR_BAR_COLOR,
            thickness=2,
            width=6
        ),
        name='Mean AC Power',
        marker_color=PlotStyler.BAR_COLORS[1],
        text=[f'{x:.2f}' for x in t_lif_analysis['mean_hvac_kw']],
        textposition='outside',
        textfont={'size': PlotStyler.ANNOTATION_FONT_SIZE}
    ))
    
    fig_power = PlotStyler.style_single_plot(
        fig_power,
        'AC Power Distribution by T_lif Range',
        'Power (kW)',
        'T_lif Range'
    )
    fig_power.update_xaxes(tickangle=45)
    PlotStyler.save_plot(fig_power, "power_vs_tlif.png", output_dir)
    
    # 3. CVRMSE by T_lif Range plot
    fig_cvrmse = go.Figure()
    
    fig_cvrmse.add_trace(go.Bar(
        x=t_lif_analysis['T_lif_range'],
        y=t_lif_analysis['cvrmse'],
        name='CVRMSE',
        marker_color=PlotStyler.BAR_COLORS[2],
        text=[f'{x:.3f}' for x in t_lif_analysis['cvrmse']],
        textposition='outside',
        textfont={'size': PlotStyler.ANNOTATION_FONT_SIZE}
    ))
    
    fig_cvrmse = PlotStyler.style_single_plot(
        fig_cvrmse,
        'CVRMSE by T_lif Range',
        'CVRMSE',
        'T_lif Range'
    )
    fig_cvrmse.update_xaxes(tickangle=45)
    PlotStyler.save_plot(fig_cvrmse, "cvrmse_vs_tlif.png", output_dir)
    
    # 4. Sample Count by T_lif Range plot
    fig_count = go.Figure()
    
    fig_count.add_trace(go.Bar(
        x=t_lif_analysis['T_lif_range'],
        y=t_lif_analysis['count'],
        name='Sample Count',
        marker_color=PlotStyler.BAR_COLORS[3],
        text=[f'{x:,}' for x in t_lif_analysis['count']],
        textposition='outside',
        textfont={'size': PlotStyler.ANNOTATION_FONT_SIZE}
    ))
    
    fig_count = PlotStyler.style_single_plot(
        fig_count,
        'Sample Count by T_lif Range',
        'Count',
        'T_lif Range'
    )
    fig_count.update_xaxes(tickangle=45)
    PlotStyler.save_plot(fig_count, "count_vs_tlif.png", output_dir)
    
    # Save the COP rules
    cop_rules = pd.DataFrame({
        'T_lif_min': t_lif_analysis['T_lif_min'],
        'T_lif_max': t_lif_analysis['T_lif_max'],
        'min_cop': t_lif_analysis['min_cop'],
        'mean_cop': t_lif_analysis['mean_cop'],
        'max_cop': t_lif_analysis['max_cop'],
        'mean_hvac_kw': t_lif_analysis['mean_hvac_kw']
    })
    cop_rules.to_csv(os.path.join(output_dir, "cop_rules.csv"), index=False)
    
    return t_lif_analysis

def analyze_seasonal_cop(data_path, output_dir="load_analysis"):
    """
    Function to generate a bar plot showing the mean COP for each season
    
    Args:
        data_path (str): Path to the processed data CSV file
        output_dir (str): Directory to save output files
        
    Returns:
        DataFrame: Seasonal COP statistics
    """
    # Ensure valid paths
    data_path = find_valid_path(data_path)
    output_dir = find_valid_path(output_dir)
    
    print("Loading and processing data for seasonal COP analysis...")
    processed_data = pd.read_csv(data_path)
    
    # Filter data - using same filter as in other COP analysis functions
    mask = (processed_data['actual_cop'] < 6.3) & (processed_data['HVAC_kW'] > 0.08)
    filtered_data = processed_data[mask]
    
    # Calculate seasonal COP statistics
    seasons = ['spring', 'summer', 'fall', 'winter']
    seasonal_cop_stats = []
    
    for season in seasons:
        season_data = filtered_data[filtered_data['Season'] == season]
        
        if len(season_data) > 0:
            stats = {
                'season': season,
                'mean_cop': season_data['actual_cop'].mean(),
                'std_cop': season_data['actual_cop'].std(),
                'min_cop': season_data['actual_cop'].min(),
                'max_cop': season_data['actual_cop'].max(),
                'count': len(season_data)
            }
            seasonal_cop_stats.append(stats)
    
    # Create DataFrame with seasonal COP statistics
    seasonal_cop_df = pd.DataFrame(seasonal_cop_stats)
    
    # Create bar plot for mean COP by season
    fig = go.Figure()
    
    # Add mean COP bars with error bars
    fig.add_trace(go.Bar(
        x=seasonal_cop_df['season'],
        y=seasonal_cop_df['mean_cop'],
        error_y=dict(
            type='data',
            array=seasonal_cop_df['std_cop'],
            color=PlotStyler.ERROR_BAR_COLOR,
            thickness=2,
            width=6
        ),
        name='Mean COP',
        marker_color=PlotStyler.BAR_COLORS[0],
        text=[f'{x:.2f}' for x in seasonal_cop_df['mean_cop']],
        textposition='outside',
        textfont={'size': PlotStyler.ANNOTATION_FONT_SIZE}
    ))
    
    # Add min/max COP lines
    fig.add_trace(go.Scatter(
        x=seasonal_cop_df['season'],
        y=seasonal_cop_df['min_cop'],
        mode='lines+markers',
        name='Min COP',
        line=dict(color=PlotStyler.COLORS[1], dash='dash')
    ))
    
    fig.add_trace(go.Scatter(
        x=seasonal_cop_df['season'],
        y=seasonal_cop_df['max_cop'],
        mode='lines+markers',
        name='Max COP',
        line=dict(color=PlotStyler.COLORS[2], dash='dash')
    ))
    
    fig = PlotStyler.style_single_plot(
        fig,
        'Mean COP by Season',
        'COP',
        'Season'
    )
    
    PlotStyler.save_plot(fig, "seasonal_mean_cop.png", output_dir)
    
    # Save seasonal COP values to CSV for use in create_load_profiles.py
    seasonal_cop_values = seasonal_cop_df[['season', 'mean_cop']]
    seasonal_cop_values.to_csv(os.path.join(output_dir, "seasonal_cop_values.csv"), index=False)
    print(f"Saved seasonal COP values to {os.path.join(output_dir, 'seasonal_cop_values.csv')}")
    
    return seasonal_cop_df

def analyze_daily_energy_consumption(data_path, output_dir="load_analysis"):
    """
    Function B: Analyze daily energy consumption from BW_data.csv
    
    Args:
        data_path (str): Path to the BW data CSV file
        output_dir (str): Directory to save output files
        
    Returns:
        DataFrame: Daily energy consumption data
    """
    # Ensure valid paths
    data_path = find_valid_path(data_path)
    output_dir = find_valid_path(output_dir)
    
    print("Loading and processing BW data for daily energy consumption...")
    
    # Load data
    bw_data = pd.read_csv(data_path)
    
    # Create datetime column
    bw_data['datetime'] = pd.to_datetime(bw_data['Date'] + ' ' + bw_data['Hour'].astype(str) + ':00:00')
    bw_data['date'] = bw_data['datetime'].dt.date
    
    # Calculate total energy for each component
    bw_data['LED_total'] = bw_data['LED1'] + bw_data['LED2'] + bw_data['LED3']
    bw_data['Total'] = bw_data['LED_total'] + bw_data['AC'] + bw_data['FAU'] + bw_data['FFU']
    
    # Calculate daily sums
    daily_energy = bw_data.groupby('date').agg({
        'LED_total': 'sum',
        'AC': 'sum',
        'FAU': 'sum',
        'FFU': 'sum',
        'Total': 'sum'
    }).reset_index()
    
    # Convert to proper datetime for plotting
    daily_energy['date'] = pd.to_datetime(daily_energy['date'])
    
    # Sort by date
    daily_energy = daily_energy.sort_values('date')
    
    # Save to CSV
    daily_energy.to_csv(os.path.join(output_dir, "daily_energy_consumption.csv"), index=False)
    
    # Create line plot
    fig = go.Figure()
    
    # Add traces for each component
    components = ['LED_total', 'AC', 'FAU', 'FFU', 'Total']
    component_names = ['LED', 'AC', 'FAU', 'FFU', 'Total']
    
    for i, (component, name) in enumerate(zip(components, component_names)):
        fig.add_trace(go.Scatter(
            x=daily_energy['date'],
            y=daily_energy[component],
            mode='lines',
            name=name,
            line=dict(
                color=PlotStyler.COLORS[i % len(PlotStyler.COLORS)],
                width=2
            )
        ))
    
    # Style and save plot
    fig.update_layout(
        xaxis=dict(showgrid=False),
        yaxis=dict(showgrid=False),
        width=PlotStyler.SINGLE_PLOT_WIDTH,
        height=PlotStyler.SINGLE_PLOT_HEIGHT
    )
    
    fig = PlotStyler.style_single_plot(
        fig,
        '(b) Daily Energy Consumption',
        'Energy (kWh/day)',
        'Date'
    )
    
    PlotStyler.save_plot(fig, "Load_B_daily_energy_consumption.png", output_dir)
    print(f"Saved daily energy consumption plot to {output_dir}/Load_B_daily_energy_consumption.png")
    
    return daily_energy

def create_cop_time_distribution_plot(data_path, output_dir="load_analysis"):
    """
    Function C: Create seasonal energy consumption plot in PlotStyler format
    
    Args:
        data_path (str): Path to the processed data CSV file
        output_dir (str): Directory to save output files
        
    Returns:
        DataFrame: Seasonal energy consumption data
    """
    # Ensure valid paths
    data_path = find_valid_path(data_path)
    output_dir = find_valid_path(output_dir)
    
    print("Creating seasonal energy consumption plot in PlotStyler format...")
    
    # Load data
    processed_data = pd.read_csv(data_path)
    processed_data['time'] = pd.to_datetime(processed_data['time'])
    processed_data['date'] = processed_data['time'].dt.date
    
    # Calculate daily energy consumption
    print("Calculating daily energy consumption...")
    daily_energy = processed_data.groupby(['date', 'Season']).agg({
        'HVAC_kW': lambda x: x.mean() * 24,
        'LED1_kW': lambda x: x.mean() * 24,
        'LED2_kW': lambda x: x.mean() * 24,
        'LED3_kW': lambda x: x.mean() * 24,
        'FFU_kW': lambda x: x.mean() * 24,
        'FAU_kW': lambda x: x.mean() * 24
    }).reset_index()

    # Rename columns to reflect kWh units
    daily_energy = daily_energy.rename(columns={
        'HVAC_kW': 'HVAC_kWh',
        'LED1_kW': 'LED1_kWh',
        'LED2_kW': 'LED2_kWh',
        'LED3_kW': 'LED3_kWh',
        'FFU_kW': 'FFU_kWh',
        'FAU_kW': 'FAU_kWh'
    })

    daily_energy['LED_total_kWh'] = (daily_energy['LED1_kWh'] + 
                                    daily_energy['LED2_kWh'] + 
                                    daily_energy['LED3_kWh'])

    daily_energy['Total_kWh'] = (daily_energy['HVAC_kWh'] +
                                daily_energy['LED_total_kWh'] +
                                daily_energy['FFU_kWh'] +
                                daily_energy['FAU_kWh'])
    
    # Calculate seasonal averages
    seasonal_energy = daily_energy.groupby('Season').agg({
        'HVAC_kWh': ['mean', 'std'],
        'LED_total_kWh': ['mean', 'std'],
        'FFU_kWh': ['mean', 'std'],
        'FAU_kWh': ['mean', 'std'],
        'Total_kWh': ['mean', 'std']
    }).round(2)
    
    # Save to CSV
    seasonal_energy.to_csv(os.path.join(output_dir, "seasonal_energy_stats.csv"))
    
    # Create plot
    fig = go.Figure()
    
    # Ensure consistent season order
    seasons = ['spring', 'summer', 'fall', 'winter']
    components = ['HVAC_kWh', 'LED_total_kWh', 'FFU_kWh', 'FAU_kWh', 'Total_kWh']
    component_names = ['AC', 'LED', 'FFU', 'FAU', 'Total']
    
    for i, (component, name) in enumerate(zip(components, component_names)):
        seasonal_means = [daily_energy[daily_energy['Season']==season][component].mean() 
                         for season in seasons]
        
        fig.add_trace(go.Bar(
            name=name,
            x=seasons,
            y=seasonal_means,
            #marker_color=PlotStyler.COLORS[i % len(PlotStyler.COLORS)],
            #text=[f'{x:.1f}' for x in seasonal_means],
            #textposition='outside',
            #textfont={'size': PlotStyler.ANNOTATION_FONT_SIZE}
        ))
    
    # Update layout
    fig.update_layout(
        xaxis=dict(showgrid=False),
        yaxis=dict(showgrid=False),
        width=PlotStyler.SINGLE_PLOT_WIDTH,
        height=PlotStyler.SINGLE_PLOT_HEIGHT
    )
    
    # Style and save plot
    fig = PlotStyler.style_single_plot(
        fig,
        '(c) Average Daily Energy Consumption by Season',
        'Energy (kWh/day)',
        'Season'
    )
    
    PlotStyler.save_plot(fig, "Load_C_seasonal_energy_consumption_styled.png", output_dir)
    print(f"Saved seasonal energy consumption plot to {output_dir}/Load_C_seasonal_energy_consumption_styled.png")
    
    return seasonal_energy

def create_seasonal_cop_plot(data_path, output_dir="load_analysis"):
    """
    Function D: Create seasonal COP bar plot with standard deviation
    
    Args:
        data_path (str): Path to the processed data CSV file
        output_dir (str): Directory to save output files
        
    Returns:
        DataFrame: Seasonal COP statistics
    """
    # Ensure valid paths
    data_path = find_valid_path(data_path)
    output_dir = find_valid_path(output_dir)
    
    print("Creating seasonal COP bar plot with standard deviation...")
    
    # Load data
    processed_data = pd.read_csv(data_path)
    
    # Calculate seasonal COP statistics
    seasonal_cop = processed_data.groupby('Season')['actual_cop'].agg(['mean', 'std']).reset_index()
    seasonal_cop.columns = ['season', 'mean_cop', 'std_cop']
    
    # Ensure consistent season order
    season_order = ['spring', 'summer', 'fall', 'winter']
    seasonal_cop['season'] = pd.Categorical(seasonal_cop['season'], categories=season_order, ordered=True)
    seasonal_cop = seasonal_cop.sort_values('season')
    
    # Save to CSV
    seasonal_cop.to_csv(os.path.join(output_dir, "seasonal_cop_stats.csv"), index=False)
    
    # Create plot
    fig = go.Figure()
    
    # Add bar chart with error bars
    fig.add_trace(go.Bar(
        x=seasonal_cop['season'],
        y=seasonal_cop['mean_cop'],
        #error_y=dict(
        #    type='data',
        #    array=seasonal_cop['std_cop'],
        #    color=PlotStyler.ERROR_BAR_COLOR,
        #    thickness=2,
        #    width=6
        #),
        #marker_color=PlotStyler.COLORS[2],
        #text=[f"{mean:.2f}" for mean, std in zip(seasonal_cop['mean_cop'], seasonal_cop['std_cop'])],
        #textposition='outside',
        name='Mean COP'  # Changed legend name to 'Mean COP'
    ))
    
    # Update layout
    fig.update_layout(
        xaxis=dict(showgrid=False),
        yaxis=dict(showgrid=False),
        width=PlotStyler.SINGLE_PLOT_WIDTH,
        height=PlotStyler.SINGLE_PLOT_HEIGHT
    )
    
    # Style and save plot
    fig = PlotStyler.style_single_plot(
        fig,
        '(d) Seasonal '#with Standard Deviation',
        'COP',
        'Season'
    )
    
    PlotStyler.save_plot(fig, "Load_D_seasonal_cop_with_std.png", output_dir)
    print(f"Saved seasonal COP plot to {output_dir}/Load_D_seasonal_cop_with_std.png")
    
    return seasonal_cop

def create_pfal_images_plot(image_path1, image_path2, output_dir="load_analysis"):
    """
    Function A: Create a vertical arrangement of two PFAL images
    
    Args:
        image_path1 (str): Path to the first image (top)
        image_path2 (str): Path to the second image (bottom)
        output_dir (str): Directory to save output files
        
    Returns:
        plotly.graph_objects.Figure: The created figure
    """
    # Ensure valid paths
    image_path1 = find_valid_path(image_path1)
    image_path2 = find_valid_path(image_path2)
    output_dir = find_valid_path(output_dir)
    
    print("Creating PFAL images plot...")
    
    # Open images to get dimensions for proper scaling
    from PIL import Image
    import io
    import base64
    
    img1 = Image.open(image_path1)
    img2 = Image.open(image_path2)
    
    # Get aspect ratios
    aspect1 = img1.width / img1.height
    aspect2 = img2.width / img2.height
    
    # Create a figure with fixed height for consistency
    total_height = PlotStyler.SUBPLOT_HEIGHT
    spacing = 20  # Pixels between images
    
    # Calculate individual image heights (with equal allocation)
    img_height = (total_height - spacing) / 2
    
    # Create figure with subplots - using fixed height ratio
    fig = make_subplots(
        rows=2, cols=1,
        vertical_spacing=spacing/total_height,  # Convert spacing to fraction of total height
        subplot_titles=('', ''),  # Empty titles as we'll use a main title
        row_heights=[0.5, 0.5]  # Equal height allocation
    )
    
    # Function to encode image
    def encode_image(image_path):
        img = Image.open(image_path)
        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format=img.format)
        img_byte_arr = img_byte_arr.getvalue()
        return base64.b64encode(img_byte_arr).decode()
    
    # Add images with consistent sizing approach
    # Using 'contain' instead of 'stretch' to maintain aspect ratio
    fig.add_layout_image(
        dict(
            source=f'data:image/png;base64,{encode_image(image_path1)}',
            xref="x domain",
            yref="y domain",
            x=0.5,  # Center the image horizontally
            y=0.5,  # Center the image vertically
            sizex=1,
            sizey=1,
            sizing="contain",  # Maintain aspect ratio
            xanchor="center",
            yanchor="middle",
            layer="below"
        ),
        row=1, col=1
    )
    
    fig.add_layout_image(
        dict(
            source=f'data:image/png;base64,{encode_image(image_path2)}',
            xref="x2 domain",
            yref="y2 domain",
            x=0.5,  # Center the image horizontally
            y=0.5,  # Center the image vertically
            sizex=1,
            sizey=1,
            sizing="contain",  # Maintain aspect ratio
            xanchor="center",
            yanchor="middle",
            layer="below"
        ),
        row=2, col=1
    )
    
    # Update layout using PlotStyler settings
    fig.update_layout(
        height=total_height,
        width=PlotStyler.SINGLE_PLOT_WIDTH,
        showlegend=False,
        margin=dict(l=10, r=10, t=80, b=10),  # Tighter margins
        plot_bgcolor='white',  # White background to match images
        paper_bgcolor='white',
        title={
            'text': '(a) The studied PFAL',
            'font': {'size': PlotStyler.TITLE_FONT_SIZE, 'family': PlotStyler.FONT_FAMILY},
            'y': 0.98,
            'x': 0.5,
            'xanchor': 'center',
            'yanchor': 'top'
        }
    )
    
    # Remove axes but keep boundaries to maintain structure
    fig.update_xaxes(
        showticklabels=False, 
        showgrid=False, 
        zeroline=False, 
        showline=True,
        linecolor='white',  # Invisible but structural
        mirror=True
    )
    fig.update_yaxes(
        showticklabels=False, 
        showgrid=False, 
        zeroline=False, 
        showline=True,
        linecolor='white',  # Invisible but structural
        mirror=True
    )
    
    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, "Load_A_pfal_images.png")
    
    # Save using improved quality settings
    try:
        fig.write_image(
            output_path,
            scale=4.0,  # Higher scale for better quality
            width=fig.layout.width,
            height=fig.layout.height,
            engine="kaleido"
        )
        print(f"Plot saved to {output_path}")
    except Exception as e:
        print(f"Direct PNG save failed: {str(e)}")
        # Fall back to HTML
        html_path = os.path.join(output_dir, "Load_A_pfal_images.html")
        fig.write_html(html_path)
        print(f"Saved as HTML to {html_path}")
    
    return fig

if __name__ == "__main__":
    # Example usage
    base_data_path = "BW_processed_data.csv"
    base_bw_data_path = "BW_data.csv"
    output_dir = "load_analysis"
    
    # Find valid paths for data files
    data_path = find_valid_path(base_data_path)
    bw_data_path = find_valid_path(base_bw_data_path)
    
    # Ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)
    
    # Create Figure A - PFAL images
    print("\nCreating PFAL Images Plot (Plot A)...")
    pfal_fig = create_pfal_images_plot("writings/fig_sources/Fig1_A.jpg", "writings/fig_sources/Fig2_A2.jpg", output_dir)
    
    # Run individual analyses
    print("\nRunning Seasonal Energy Analysis...")
    seasonal_power_avg, seasonal_energy_avg = analyze_seasonal_energy(data_path, output_dir)
    print("\nSeasonal Power Analysis Results:")
    print(seasonal_power_avg)
    print("\nSeasonal Energy Analysis Results:")
    print(seasonal_energy_avg)
    
    print("\nRunning Daily Energy Consumption Analysis (Plot B)...")
    daily_energy = analyze_daily_energy_consumption(bw_data_path, output_dir)
    print("\nDaily Energy Analysis Results (first 5 days):")
    print(daily_energy.head())
    
    print("\nRunning COP Time Distribution Analysis (Plot C)...")
    cop_distribution = create_cop_time_distribution_plot(data_path, output_dir)
    print("\nCOP Distribution Results:")
    print(cop_distribution)
    
    print("\nRunning Seasonal COP Analysis (Plot D)...")
    seasonal_cop_stats = create_seasonal_cop_plot(data_path, output_dir)
    print("\nSeasonal COP Analysis Results:")
    print(seasonal_cop_stats)
    
    print("\nRunning COP-Power Relationship Analysis...")
    cop_power_analysis = analyze_cop_power_relationship(data_path, output_dir=output_dir)
    print("\nCOP-Power Analysis Results:")
    print(cop_power_analysis)
    
    print("\nRunning Seasonal COP Analysis...")
    seasonal_cop_stats = analyze_seasonal_cop(data_path, output_dir=output_dir)
    print("\nSeasonal COP Analysis Results:")
    print(seasonal_cop_stats) 