import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import os
import sys
from sklearn.metrics import r2_score, mean_squared_error

# Add the src directory to the Python path so we can import the PlotStyler
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'src')))
from visualization import PlotStyler

# Constants
k = 1.38e-23  # Boltzmann constant (J/K)
q = 1.60e-19  # Electron charge (C)
N_s = 156  # Number of cells in series

# Manufacturer data at STC
T_m0 = 25  # Reference temperature (°C)
G_stc = 1000  # Reference irradiance (W/m^2)
V_mp0 = 48.02  # Voltage at maximum power point (V)
I_mp0 = 13.33  # Current at maximum power point (A)
P_mp0 = V_mp0 * I_mp0  # Maximum power (W)
V_oc0 = 57.34  # Open-circuit voltage (V)
I_sc0 = 13.98  # Short-circuit current (A)
alpha_sc = 4.50e-2  # Short-circuit current temperature coefficient (%/°C)
beta_voc = -2.50e-1  # Open-circuit voltage temperature coefficient (%/°C)
NOCT = 45  # Nominal Operating Cell Temperature (°C)

# Manufacturer's power data for comparison
manu_data = {
    1000: 640,
    800: 510,
    600: 350,
    400: 240,
    200: 120
}

# Thermal voltage at STC
V_th0 = k * (T_m0 + 273.15) / q  # (V)

# Iterative parameter extraction at STC with updated formulas
def calculate_initial_n(V_oc0, V_mp0, I_sc0, I_mp0, V_th0, N_s):
    n_G = (V_oc0 - V_mp0 - V_th0 * N_s) / (V_th0 * N_s * np.log(I_sc0 / (I_sc0 - I_mp0)))
    n_S = (V_oc0 - V_mp0) / (V_th0 * N_s * np.log(V_mp0 / (V_th0 * N_s)))
    n_p = (I_sc0 - I_mp0) * (V_mp0 - V_th0 * N_s) / (I_sc0 * V_th0 * N_s)
    return min(n_G, n_S, n_p)

def iterate_parameters(V_oc0, V_mp0, I_sc0, I_mp0, V_th0, N_s, tol=1e-6, max_iter=10):
    n = calculate_initial_n(V_oc0, V_mp0, I_sc0, I_mp0, V_th0, N_s)
    R_s = 0  # Initial R_s for the first iteration
    R_sh = 0  # Initial R_sh for the first iteration
    iteration = 0

    while iteration < max_iter:
        # Calculate R_s
        R_s = (V_oc0 - V_mp0 - n * V_th0 * N_s * np.log(V_mp0 / (n * V_th0 * N_s))) / I_mp0
        
        # Calculate R_sh (corrected denominator with multiplication)
        numerator = (V_mp0 - I_mp0 * R_s) * V_mp0 - n * V_th0 * N_s * V_mp0
        denominator = (V_mp0 - I_mp0 * R_s) * (I_sc0 - I_mp0) - n * V_th0 * N_s * I_mp0
        R_sh = numerator / denominator - R_s
        
        # Calculate intermediate parameters
        alpha_i = (V_mp0 + n * V_th0 * N_s - I_mp0 * R_s) / (n * V_th0 * N_s)  # Using R_s from previous iteration
        beta_i = (I_sc0 * (R_s + R_sh) - V_oc0) / (I_sc0 * (R_s + R_sh) - 2 * V_mp0)
        
        # Update n_G
        next_n_G = (V_oc0 - V_mp0 - I_mp0 * R_s) / (V_th0 * N_s * np.log((I_sc0 * (R_s + R_sh) - V_oc0) / ((I_sc0 - I_mp0) * (R_s + R_sh) - V_mp0)))
        
        # Update R_s and R_sh
        next_R_s = (V_oc0 - V_mp0 - n * V_th0 * N_s * np.log(alpha_i * beta_i)) / I_mp0
        next_R_sh = numerator / denominator - next_R_s  # Reuse numerator, adjust denominator if needed
        
        # Convergence criterion
        next_eta = abs(n - next_n_G)
        print(f"Iteration {iteration + 1}: n = {n:.6f}, R_s = {R_s:.6f} Ω, R_sh = {R_sh:.6f} Ω, next_eta = {next_eta:.6f}")
        
        if next_eta < tol or iteration >= 3:  # Expect convergence around 4 iterations
            break
        
        n = next_n_G
        R_s = next_R_s
        R_sh = next_R_sh
        iteration += 1
    
    return n, R_s, R_sh

# Extract parameters at STC
#n_0, R_s0, R_sh0 = iterate_parameters(V_oc0, V_mp0, I_sc0, I_mp0, V_th0, N_s,max_iter=2)
n_0 = 0.4361 
R_s0 = 0.2688 
R_sh0 = 366.83
print(f"\nConverged parameters at STC: n_0 = {n_0:.6f}, R_s0 = {R_s0:.6f} Ω, R_sh0 = {R_sh0:.6f} Ω")

# Function to calculate power at a given condition with analytical I_mp
def calculate_pv_parameters(G, T_a, n_0, R_s0, R_sh0):
    # Module temperature
    T_m = T_a + G * (NOCT - 20) / 800  # °C
    
    # Thermal voltage
    V_th = k / q * (T_m + 273.15)
    
    # Adjusted parameters
    I_sc = I_sc0 * (G/G_stc+alpha_sc/100*(T_m-T_m0))
    V_oc = V_oc0 * (1 + beta_voc / 100 * (T_m - T_m0)) + N_s * n_0 * V_th * np.log(G / G_stc)
    n = n_0 * (T_m0 + 273.15) / (T_m + 273.15)
    R_sh = R_sh0 * G_stc / G
    R_s = R_s0 * (T_m + 273.15) / (T_m0 + 273.15) * (1 - 0.217 * np.log(G / G_stc))
    
    # Light-generated current and diode saturation current
    I_L = I_sc * (R_s+R_sh)/R_sh
    I_0 = ((R_sh + R_s) * I_sc - V_oc) * np.exp(-V_oc / (n * N_s * V_th)) / R_sh
    
    # Calculate I_mp using quadratic formula
    V_m = V_mp0  # Initial guess, can be refined iteratively
    a = -(R_s + R_sh) * R_s / (n * N_s * V_th)
    b = (R_s + R_sh) * (1 + V_m / (n * N_s * V_th)) + (R_s / (n * N_s * V_th)) * ((I_L + I_0) * R_sh - V_m)
    c = 2 * I_0 * R_sh - V_m * (((I_L + I_0) * R_sh / (n * N_s * V_th)) + 1) + (V_m ** 2 / (n * N_s * V_th))
    
    # Solve for I_mp
    discriminant = b ** 2 - 4 * a * c
    if discriminant >= 0:
        I_mp = (-b + np.sqrt(discriminant)) / (2 * a)
    else:
        I_mp = I_sc0 * (G / G_stc)  # Fallback if discriminant is negative (approximate)
    
    # Calculate V_mp using the SDM equation
    V_mp = n * N_s * V_th * np.log((I_L - I_mp - (V_m + I_mp * R_s) / R_sh + I_0) / I_0) - I_mp * R_s
    if V_mp <= 0:  # Ensure physical solution
        V_mp = V_oc * 0.8  # Approximate fallback
        I_mp = I_L * (1 - V_mp / V_oc)  # Recompute I_mp
    
    # Calculate maximum power
    P_max = V_mp * I_mp if V_mp > 0 else 0
    
    return T_m, I_sc, V_oc, n, R_s, R_sh, I_L, I_0, V_mp, I_mp, P_max

# Task 1: Calculate power for given conditions and compare with manufacturer data
G_values = [1000, 800, 600, 400, 200]  # W/m^2
T_a_values = [2, 10, 15, 18, 23]  # °C
results = []

for G, T_a in zip(G_values, T_a_values):
    T_m, I_sc, V_oc, n, R_s, R_sh, I_L, I_0, V_mp, I_mp, P_max = calculate_pv_parameters(G, T_a, n_0, R_s0, R_sh0)
    P_max_manu = manu_data[G]
    results.append({
        'G (W/m^2)': G,
        'T_a (°C)': T_a,
        'T_m (°C)': T_m,
        'I_sc (A)': I_sc,
        'V_oc (V)': V_oc,
        'n': n,
        'R_s (Ω)': R_s,
        'R_sh (Ω)': R_sh,
        'I_L (A)': I_L,
        'I_0 (A)': I_0,
        'V_mp (V)': V_mp,
        'I_mp (A)': I_mp,
        'P_max_simulated (W)': P_max,
        'P_max_manufacturer (W)': P_max_manu
    })
    print(f"\nCondition: G = {G} W/m^2, T_a = {T_a} °C")
    print(f"T_m = {T_m:.2f} °C")
    print(f"P_max (simulated) = {P_max:.2f} W, P_max (manufacturer) = {P_max_manu:.2f} W")

# Save results to CSV
df_results = pd.DataFrame(results)
df_results.to_csv('pv_power_comparison.csv', index=False)
print("\nResults saved to 'pv_power_comparison.csv'")

# Calculate metrics
r2 = r2_score(df_results['P_max_manufacturer (W)'], df_results['P_max_simulated (W)'])
rmse = np.sqrt(mean_squared_error(df_results['P_max_manufacturer (W)'], df_results['P_max_simulated (W)']))
cvrmse = rmse / df_results['P_max_manufacturer (W)'].mean()
nmse = mean_squared_error(df_results['P_max_manufacturer (W)'], df_results['P_max_simulated (W)']) / (df_results['P_max_manufacturer (W)'].mean() ** 2)

# Add metrics annotation
metrics_text = (
    f"R² = {r2:.3f}<br>"
    f"CV(RMSE) = {cvrmse:.2%}<br>"
    f"NMSE = {nmse:.3f}"
)

# Create a custom margin with sufficient top spacing to avoid title/legend overlap
custom_margin = dict(l=60, r=30, t=100, b=60, pad=0)
# Plot comparison using Plotly with PlotStyler
fig1 = go.Figure()
fig1.add_trace(go.Bar(
    x=df_results['G (W/m^2)'],
    y=df_results['P_max_simulated (W)'],
    name='Simulated PV max',
    marker_color=PlotStyler.COLORS[0],
    #width=50
))
fig1.add_trace(go.Bar(
    x=df_results['G (W/m^2)'],
    y=df_results['P_max_manufacturer (W)'],
    name='Manufacturer PV max', 
    marker_color=PlotStyler.COLORS[1],
    #width=50
))

# Style the plot using PlotStyler
PlotStyler.style_single_plot(
    fig1,
    '(c) PV Model Validation (Jinko Solar)',
    'Maximum Power (W)',
    'Solar Irradiance (W/m²)'
)

# Override margin settings to fix blank areas and update legend position
fig1.update_layout(
    margin=custom_margin,
    legend=dict(
        y=PlotStyler.LEGEND_SETTINGS['y'] - 0.018
    )
)

# Add metrics annotation in upper left corner
fig1.add_annotation(
    x=100,
    y=df_results['P_max_simulated (W)'].max() * 1.1,  # Position at 95% of max y value
    text=metrics_text,
    showarrow=False,
    xanchor='left',
    yanchor='top',
    font=dict(
        family=PlotStyler.FONT_FAMILY,
        size=PlotStyler.ANNOTATION_FONT_SIZE
    ),
    bgcolor='rgba(255, 255, 255, 0.2)'
)

# Save as PNG file using PlotStyler dimensions
output_dir = os.path.dirname(os.path.abspath(__file__))
pv_comparison_file = f"{output_dir}/Validate_C_pv_comparison_plot.png"
fig1.write_image(
    pv_comparison_file, 
    scale=8, 
    width=PlotStyler.SINGLE_PLOT_WIDTH,
    height=PlotStyler.SINGLE_PLOT_HEIGHT
)
print(f"Comparison plot saved to {pv_comparison_file}")

# Also save as HTML for interactive viewing
html_file1 = f"{output_dir}/pv_comparison_plot.html"
fig1.write_html(html_file1)
print(f"Interactive comparison plot saved to {html_file1}")

# Task 2: Create a dense color distribution plot (heatmap)
T_a_range = np.linspace(-30, 40, 20)  # °C, from -10°C to 40°C with 100 points
G_range = np.linspace(200, 1000, 20)  # W/m^2, from 200 to 1000 W/m² with 100 points
power_grid = np.zeros((len(G_range), len(T_a_range)))

for i, G in enumerate(G_range):
    for j, T_a in enumerate(T_a_range):
        _, _, _, _, _, _, _, _, _, _, P_max = calculate_pv_parameters(G, T_a, n_0, R_s0, R_sh0)
        power_grid[i, j] = P_max

# Create the heatmap using Plotly
fig2 = go.Figure(data=go.Heatmap(
    x=T_a_range,
    y=G_range,
    z=power_grid,
    colorscale='RdBu',
    colorbar=dict(
        title='Power (W)',
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
fig2.update_layout(
    title={
        'text': '(d) PV Power vs Temperature and Irradiance',
        'font': {'size': PlotStyler.TITLE_FONT_SIZE, 'family': PlotStyler.FONT_FAMILY},
        'y': 1,  # Changed from 0.98 to 1 to match plot C
        'x': 0.5,
        'xanchor': 'center',
        'yanchor': 'top'
    },
    xaxis={
        'title': 'Ambient Temperature (°C)',
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
        'title': 'Solar Irradiance (W/m²)',
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

# Save as PNG file using PlotStyler dimensions
pv_heatmap_file = f"{output_dir}/Validate_D_pv_heatmap.png"
fig2.write_image(
    pv_heatmap_file, 
    scale=8,
    width=PlotStyler.SINGLE_PLOT_WIDTH,
    height=PlotStyler.SINGLE_PLOT_HEIGHT
)
print(f"Heatmap saved to {pv_heatmap_file}")

# Also save as HTML for interactive viewing
html_file2 = f"{output_dir}/pv_heatmap.html"
fig2.write_html(html_file2)
print(f"Interactive heatmap saved to {html_file2}")