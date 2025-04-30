import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np
from datetime import datetime
import os

def create_power_flow_plot(schedule_file: str, results: dict, output_dir: str = 'plots'):
    """Create power flow visualization for a given schedule"""
    # Create time index
    times = pd.date_range(start='2024-01-01', periods=len(results['pv_power']), freq='H')
    
    # Create figure with secondary y-axis
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    
    # Add PV Generation
    fig.add_trace(
        go.Scatter(x=times, y=results['pv_power']/1000,
                  name="PV Generation", line=dict(color="orange")),
        secondary_y=False,
    )
    
    # Add Load Profile
    fig.add_trace(
        go.Scatter(x=times, y=results['load_profile']/1000,
                  name="Power Consumption", line=dict(color="red")),
        secondary_y=False,
    )
    
    # Add Battery State of Charge
    fig.add_trace(
        go.Scatter(x=times, y=results['battery_soc']*100,
                  name="Battery SOC", line=dict(color="blue")),
        secondary_y=True,
    )
    
    # Update layout
    schedule_name = os.path.basename(schedule_file).replace('.csv', '')
    fig.update_layout(
        title=f"Power Flows - {schedule_name}",
        xaxis_title="Time",
        yaxis_title="Power (kW)",
        yaxis2_title="Battery State of Charge (%)",
        hovermode='x unified',
        showlegend=True
    )
    
    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)
    
    # Save plot
    output_file = os.path.join(output_dir, f"{schedule_name}_power_flows.html")
    fig.write_html(output_file)
    
    return output_file

def process_all_schedules(results_dir: str = 'results', output_dir: str = 'plots'):
    """Process all schedule results and create visualizations"""
    # Load results
    results_df = pd.read_csv(os.path.join(results_dir, 'optimization_results.csv'))
    
    plot_files = []
    for _, row in results_df.iterrows():
        schedule_file = row['schedule_file']
        
        # Load detailed results
        detail_file = os.path.join(results_dir, 
                                 f"{os.path.basename(schedule_file).replace('.csv', '_details.npz')}")
        if os.path.exists(detail_file):
            results = dict(np.load(detail_file))
            plot_file = create_power_flow_plot(schedule_file, results, output_dir)
            plot_files.append(plot_file)
    
    return plot_files

if __name__ == "__main__":
    plot_files = process_all_schedules()
    print(f"Generated {len(plot_files)} plot files in the 'plots' directory") 