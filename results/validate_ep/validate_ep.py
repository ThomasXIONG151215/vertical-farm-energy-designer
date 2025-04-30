import pandas as pd
import plotly.graph_objects as go
import numpy as np
import os
import sys

# Add the src directory to the Python path so we can import the PlotStyler
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'src')))
from visualization import PlotStyler

def calculate_metrics(y_true, y_pred):
    """
    Calculate validation metrics between true and predicted values
    
    Parameters:
    -----------
    y_true : array-like
        Observed/true values
    y_pred : array-like
        Predicted/model values
    
    Returns:
    --------
    dict
        Dictionary containing calculated metrics (R², CVRMSE, NMSE)
    """
    # Drop NaN values
    mask = ~np.isnan(y_true) & ~np.isnan(y_pred)
    y_true = np.array(y_true)[mask]
    y_pred = np.array(y_pred)[mask]
    
    # Calculate R² (coefficient of determination)
    mean_y_true = np.mean(y_true)
    ss_total = np.sum((y_true - mean_y_true) ** 2)
    ss_residual = np.sum((y_true - y_pred) ** 2)
    r2 = 1 - (ss_residual / ss_total)
    
    # Calculate CVRMSE (coefficient of variation of the RMSE)
    rmse = np.sqrt(np.mean((y_true - y_pred) ** 2))
    cvrmse = rmse / mean_y_true
    
    # Calculate NMSE (normalized mean square error)
    nmse = np.sum((y_true - y_pred) ** 2) / np.sum(y_true ** 2)
    
    return {
        'r2': r2,
        'cvrmse': cvrmse,
        'nmse': nmse
    }

def create_validation_plot(csv_file, output_file='ep_validation_plot'):
    """
    Creates a validation plot comparing measured and predicted values from EnergyPlus
    
    Parameters:
    -----------
    csv_file : str
        Path to the CSV file containing the validation data
    output_file : str, optional
        Base filename to save the output files (default: 'ep_validation_plot')
    
    Returns:
    --------
    plotly.graph_objects.Figure
        The plotly figure object for further customization if needed
    """
    # Read the CSV file
    df = pd.read_csv(csv_file)
    print(df.head())
    # Convert time column to datetime
    df['time'] = pd.to_datetime(df['time'])
    
    # Calculate validation metrics
    metrics = calculate_metrics(df['Measurement'], df['AC_Electricity_kWh'])
    
    # Create the line plot
    fig = go.Figure()
    
    # Add measured values trace
    fig.add_trace(go.Scatter(
        x=df['time'],
        y=df['Measurement'],
        mode='lines',
        name='Measured AC kWh',
        line=dict(color=PlotStyler.COLORS[0], width=3)
    ))
    
    # Add predicted values trace
    fig.add_trace(go.Scatter(
        x=df['time'],
        y=df['AC_Electricity_kWh'],
        mode='lines',
        name='Predicted AC kWh',
        line=dict(color=PlotStyler.COLORS[1], width=3)
    ))
    
    # Add metrics annotation
    metrics_text = (
        f"R² = {metrics['r2']:.3f}<br>"
        f"CV(RMSE) = {metrics['cvrmse']:.2%}<br>"
        f"NMSE = {metrics['nmse']:.3f}"
    )
    
    # Get data range for annotation positioning
    y_min = min(df['Measurement'].min(), df['AC_Electricity_kWh'].min())
    y_max = max(df['Measurement'].max(), df['AC_Electricity_kWh'].max())
    
    # Determine appropriate y-axis range with a small buffer (10%)
    # Set maximum to 1.5 as data is less than this value
    y_range = [0, 1.2]
    
    # Create a tighter, cleaner margin
    custom_margin = dict(l=60, r=30, t=100, b=60, pad=0)
    
    # Add annotation with more precise positioning
    fig.add_annotation(
        x=df['time'].iloc[-5],
        y=1.35,  # Fixed position given the new y-axis scale
        text=metrics_text,
        showarrow=False,
        xanchor='right',
        yanchor='top',
        font=dict(
            family=PlotStyler.FONT_FAMILY,
            size=PlotStyler.ANNOTATION_FONT_SIZE
        ),
        bgcolor='rgba(255, 255, 255, 0.2)',
        #bordercolor='black',
        #borderwidth=1
    )
    
    # Update y-axis range to match data more closely
    fig.update_yaxes(range=y_range)
    
    # Style the plot using PlotStyler but override certain settings
    PlotStyler.style_single_plot(
        fig, 
        '(a) EnergyPlus Model Validation (August 2023)', 
        'Electricity Usage (kWh)',
        'Date'
    )
    
    # Override margin settings to fix blank areas
    fig.update_layout(
        margin=custom_margin,
        legend=dict(
            y=PlotStyler.LEGEND_SETTINGS['y'] - 0.012
        )
        #legend=dict(
        #    yanchor="top",
        #    y=0.99,
        #    xanchor="right", 
        #    x=0.99,
        #    bgcolor='rgba(255,255,255,0.7)'
        #)
    )
    
    # Save the figure as PNG file using PlotStyler dimensions
    png_file = f"G:/PVBES_Design/results/validate_ep/Validate_A_ep_validation_plot.png"
    fig.write_image(
        png_file, 
        scale=8, 
        width=PlotStyler.SINGLE_PLOT_WIDTH,
        height=PlotStyler.SINGLE_PLOT_HEIGHT
    )
    print(f"Validation plot saved to {png_file}")
    
    # Also save as HTML for interactive viewing
    html_file = f"G:/PVBES_Design/results/validate_ep/Validate_A_ep_validation_plot.html"
    fig.write_html(html_file)
    print(f"Interactive plot saved to {html_file}")
    
    return fig

def create_envelope_heatmap(csv_file, output_file='envelope_heatmap'):
    """
    Creates a heatmap visualization of envelope optimization data.
    
    Parameters:
    -----------
    csv_file : str
        Path to the CSV file containing the envelope optimization data
    output_file : str, optional
        Base filename to save the output files (default: 'envelope_heatmap')
    
    Returns:
    --------
    plotly.graph_objects.Figure
        The plotly figure object for further customization if needed
    """
    # Read the CSV file
    df = pd.read_csv(csv_file)
    
    # Extract unique values for thermal conductivity and thickness
    thermal_conductivity_values = sorted(df['thermal conductivity'].unique())
    thickness_values = sorted(df['thickness'].unique())
    
    # Create a 2D matrix for the heatmap
    energy_matrix = np.zeros((len(thermal_conductivity_values), len(thickness_values)))
    
    # Fill the matrix with annual energy values
    for i, tc in enumerate(thermal_conductivity_values):
        for j, t in enumerate(thickness_values):
            mask = (df['thermal conductivity'] == tc) & (df['thickness'] == t)
            if mask.any():
                energy_matrix[i, j] = df.loc[mask, 'annual_energy_kWh'].values[0]
    
    # Create tighter margin settings
    custom_margin = dict(l=60, r=30, t=100, b=60, pad=0)
    
    # Create the heatmap using Plotly
    fig = go.Figure(data=go.Heatmap(
        z=energy_matrix,
        x=thickness_values,
        y=thermal_conductivity_values,
        colorscale='RdBu_r',  # Red-Blue color scale (reversed so blue is low energy)
        colorbar=dict(
            title='Annual Energy (kWh)',
            titleside='right',
            titlefont=dict(
                family=PlotStyler.FONT_FAMILY,
                size=PlotStyler.AXIS_TITLE_FONT_SIZE
            ),
            tickfont=dict(
                family=PlotStyler.FONT_FAMILY,
                size=PlotStyler.TICK_FONT_SIZE
            ),
            len=0.9,  # Adjust colorbar length
            y=0.5,    # Center colorbar
            yanchor='middle'
        )
    ))
    
    # Create a base layout following PlotStyler guidelines but with tighter margins
    fig.update_layout(
        title={
            'text': '(b) AC Energy vs. Envelope Parameters',
            'font': {'size': PlotStyler.TITLE_FONT_SIZE, 'family': PlotStyler.FONT_FAMILY},
            'y': 1,  # Changed from 0.98 to 1 to match plot A
            'x': 0.5,
            'xanchor': 'center',
            'yanchor': 'top'
        },
        xaxis={
            'title': 'Thickness (m)',
            'titlefont': {'size': PlotStyler.AXIS_TITLE_FONT_SIZE, 'family': PlotStyler.FONT_FAMILY},
            'tickfont': {'size': PlotStyler.TICK_FONT_SIZE, 'family': PlotStyler.FONT_FAMILY},
            'showgrid': True,
            'gridwidth': 1,
            'gridcolor': PlotStyler.GRID_COLOR,
            'zeroline': False,
            'showline': True,
            'linewidth': PlotStyler.BORDER_WIDTH,
            'linecolor': PlotStyler.BORDER_COLOR,
            'mirror': True
        },
        yaxis={
            'title': 'Thermal Conductivity (W/m·K)',
            'titlefont': {'size': PlotStyler.AXIS_TITLE_FONT_SIZE, 'family': PlotStyler.FONT_FAMILY},
            'tickfont': {'size': PlotStyler.TICK_FONT_SIZE, 'family': PlotStyler.FONT_FAMILY},
            'showgrid': True,
            'gridwidth': 1,
            'gridcolor': PlotStyler.GRID_COLOR,
            'zeroline': False,
            'showline': True,
            'linewidth': PlotStyler.BORDER_WIDTH,
            'linecolor': PlotStyler.BORDER_COLOR,
            'mirror': True
        },
        width=PlotStyler.SINGLE_PLOT_WIDTH,
        height=PlotStyler.SINGLE_PLOT_HEIGHT,
        margin=custom_margin,
        plot_bgcolor='rgba(0,0,0,0)',
        paper_bgcolor='rgba(0,0,0,0)',
        font={'family': PlotStyler.FONT_FAMILY, 'size': PlotStyler.TICK_FONT_SIZE}
    )
    
    """ 
       # Add annotations to show the minimum energy value
    min_energy = np.min(energy_matrix)
    min_idx = np.where(energy_matrix == min_energy)
    min_tc = thermal_conductivity_values[min_idx[0][0]]
    min_thickness = thickness_values[min_idx[1][0]]
    
    fig.add_annotation(
        x=min_thickness,
        y=min_tc,
        text=f"Min: {min_energy:.2f} kWh<br>TC: {min_tc}, Thickness: {min_thickness}m",
        showarrow=True,
        arrowhead=1,
        arrowsize=1,
        arrowwidth=2,
        arrowcolor="black",
        font=dict(
            family=PlotStyler.FONT_FAMILY,
            size=PlotStyler.ANNOTATION_FONT_SIZE, 
            color="black"
        ),
        bgcolor="white",
        bordercolor="black",
        borderwidth=2,
        borderpad=4,
        opacity=0.8
    )

    """
    # Save the figure as PNG file using PlotStyler dimensions
    png_file = f"G:/PVBES_Design/results/validate_ep/Validate_B_envelope_heatmap.png"
    fig.write_image(
        png_file, 
        scale=8,
        width=PlotStyler.SINGLE_PLOT_WIDTH,
        height=PlotStyler.SINGLE_PLOT_HEIGHT
    )
    print(f"Heatmap saved to {png_file}")
    
    # Also save as HTML for interactive viewing
    html_file = f"G:/PVBES_Design/results/validate_ep/Validate_B_envelope_heatmap.html"
    fig.write_html(html_file)
    print(f"Interactive heatmap saved to {html_file}")
    
    return fig

def main():
    """
    Main function to generate all validation plots for Figure S1
    """
    # Check if kaleido is installed (required for PNG export)
    try:
        import kaleido
    except ImportError:
        print("Warning: kaleido package not found. Installing it for PNG export...")
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "kaleido"])
        print("kaleido installed successfully.")
    
    # Generate EnergyPlus validation plot
    print("Generating EnergyPlus validation plot...")
    create_validation_plot("G:/PVBES_Design/results/validate_ep/NOE.csv", "ep_validation_plot")
    
    # Generate envelope optimization heatmap
    print("Generating envelope optimization heatmap...")
    create_envelope_heatmap("G:/PVBES_Design/results/validate_ep/LoadResults2.csv", "envelope_heatmap")
    
    print("All plots generated successfully in the validate_ep directory.")

if __name__ == "__main__":
    # Call the main function to generate all plots
    main() 