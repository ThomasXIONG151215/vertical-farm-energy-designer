import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np
from typing import Dict, List


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

# Common Utilities
def calculate_metrics(y_true, y_pred):
    """Calculate R2, NMBE and CV(RMSE)"""
    r2 = r2_score(y_true, y_pred)
    nmbe = np.mean(y_pred - y_true) / np.mean(y_true)
    cvrmse = np.sqrt(mean_squared_error(y_true, y_pred)) / np.mean(y_true)
    return r2, nmbe, cvrmse

class PlotStyler:
    """Class to ensure consistent plot styling across all visualizations"""
    
    # Enhanced color palette with more earth tones and professional colors
    COLORS = [
        '#0047AB',  # 钴蓝色 Cobalt Blue
        '#8B0000',  # 深红色 Dark Red
        '#006400',  # 墨绿色 Dark Green
        '#00796B',  # 青绿色 Teal
        '#8B4513',  # 深棕色 Saddle Brown
        '#4B0082',  # 靛蓝色 Indigo
        '#B22222',  # 砖红色 Firebrick
        '#2F4F4F',  # 深青灰色 Dark Slate Gray
        '#A0522D',  # 赭石色 Sienna
        '#228B22',  # 森林绿 Forest Green
        '#483D8B',  # 深岩蓝 Dark Slate Blue
        '#800000',  # 栗色 Maroon
        '#008080',  # 水鸭色 Teal
        '#556B2F',  # 橄榄绿 Dark Olive Green
        '#5F4B32',  # 棕褐色 Brown
        '#004D40',  # 深青绿 Dark Teal
        '#880E4F',  # 深洋红 Deep Pink
        '#1B5E20',  # 深森林绿 Dark Forest Green
        '#3E2723',  # 深棕褐色 Deep Brown
        '#263238'   # 蓝灰色 Blue Grey
    ]
    
    ERROR_BAR_COLOR = 'rgba(0,0,0,0.7)'  # Darker error bars
    BAR_COLORS = [
        'rgba(0,71,171,0.7)',    # 钴蓝色 Cobalt Blue
        'rgba(139,0,0,0.7)',     # 深红色 Dark Red
        'rgba(0,100,0,0.7)',     # 墨绿色 Dark Green
        'rgba(0,121,107,0.7)',   # 青绿色 Teal
        'rgba(139,69,19,0.7)',   # 深棕色 Saddle Brown
        'rgba(75,0,130,0.7)',    # 靛蓝色 Indigo
        'rgba(178,34,34,0.7)',   # 砖红色 Firebrick
        'rgba(47,79,79,0.7)',    # 深青灰色 Dark Slate Gray
        'rgba(160,82,45,0.7)',   # 赭石色 Sienna
        'rgba(34,139,34,0.7)'    # 森林绿 Forest Green
    ]
    
    # Increased font settings
    FONT_FAMILY = "Times New Roman"
    TITLE_FONT_SIZE = 32
    AXIS_TITLE_FONT_SIZE = 36
    TICK_FONT_SIZE = 30
    LEGEND_FONT_SIZE = 36
    ANNOTATION_FONT_SIZE = 36
    
    # Plot dimensions
    SINGLE_PLOT_WIDTH = 800
    SINGLE_PLOT_HEIGHT = 700
    SUBPLOT_WIDTH = 1300
    SUBPLOT_HEIGHT = 900
    
    # Margins
    MARGIN = dict(l=100, r=100, t=120, b=100, pad=4)
    
    # Grid and border settings
    GRID_COLOR = 'rgba(128,128,128,0.15)'
    BORDER_COLOR = 'black'
    BORDER_WIDTH = 2.0

    # 统一的图例设置
    LEGEND_SETTINGS = dict(
        yanchor="top",
        y=1.15,
        xanchor="center", 
        x=0.5,
        bgcolor='rgba(255,255,255,0)',
        orientation="h"  # Horizontal legend
        
    )

    @classmethod
    def style_single_plot(cls, fig, title, y_label, x_label=None, enforce_colors=True):
        """Style a single plot with consistent formatting
        
        Args:
            fig (plotly.graph_objects.Figure): The figure to style
            title (str): The title of the plot
            y_label (str): The y-axis label
            x_label (str, optional): The x-axis label. Defaults to None.
            enforce_colors (bool, optional): Whether to enforce the color scheme from PlotStyler.COLORS
                                           for all traces. Defaults to True.
        
        Returns:
            plotly.graph_objects.Figure: The styled figure
        """
        # Apply consistent color scheme to all traces if enforce_colors is True
        if enforce_colors and hasattr(fig, 'data') and fig.data:
            for i, trace in enumerate(fig.data):
                # Get a color from the PlotStyler.COLORS array using modulo to handle more traces than colors
                color_index = i % len(cls.COLORS)
                color = cls.COLORS[color_index]
                
                # Handle different trace types
                if trace.type == 'bar':
                    # For bar charts, set marker color directly
                    if not hasattr(trace, 'marker') or trace.marker is None:
                        trace.marker = dict(color=color)
                    else:
                        # If marker exists but doesn't have color or color is None
                        if not hasattr(trace.marker, 'color') or trace.marker.color is None:
                            trace.marker.color = color
                
                elif trace.type == 'scatter':
                    mode = getattr(trace, 'mode', '')
                    
                    # Check if this is a scatter plot with lines
                    if mode and 'lines' in mode:
                        if not hasattr(trace, 'line') or trace.line is None:
                            trace.line = dict(color=color, width=3)
                        else:
                            # Don't override dashed or dotted line styles
                            dash = getattr(trace.line, 'dash', None)
                            if not dash:
                                # If line exists but doesn't have color or color is None
                                if not hasattr(trace.line, 'color') or trace.line.color is None:
                                    trace.line.color = color
                    
                    # Check if this is a scatter plot with markers
                    if mode and 'markers' in mode:
                        if not hasattr(trace, 'marker') or trace.marker is None:
                            trace.marker = dict(color=color, size=8)
                        else:
                            # If marker exists but doesn't have color or color is None
                            if not hasattr(trace.marker, 'color') or trace.marker.color is None:
                                trace.marker.color = color
                
                # Handle error bars consistently
                if hasattr(trace, 'error_y') and trace.error_y:
                    if not hasattr(trace.error_y, 'color') or trace.error_y.color is None:
                        trace.error_y.color = cls.ERROR_BAR_COLOR

        # Get current y-axis range
        if hasattr(fig.layout, 'yaxis') and hasattr(fig.layout.yaxis, 'range'):
            y_range = fig.layout.yaxis.range
            if y_range and len(y_range) == 2:
                y_max = y_range[1]
                # Increase y-axis maximum by 15% to make room for legend
                new_y_max = y_max * 1.15
                fig.update_yaxes(range=[y_range[0], new_y_max])
        
        fig.update_layout(
            title={
                'text': title,
                'font': {'size': cls.TITLE_FONT_SIZE, 'family': cls.FONT_FAMILY},
                'y': 1,
                'x': 0.5,
                'xanchor': 'center',
                'yanchor': 'top'
            },
            yaxis_title={
                'text': y_label,
                'font': {'size': cls.AXIS_TITLE_FONT_SIZE, 'family': cls.FONT_FAMILY}
            },
            xaxis_title={
                'text': x_label if x_label else '',
                'font': {'size': cls.AXIS_TITLE_FONT_SIZE, 'family': cls.FONT_FAMILY}
            },
            font={'size': cls.TICK_FONT_SIZE, 'family': cls.FONT_FAMILY},
            showlegend=True,
            legend=cls.LEGEND_SETTINGS,
            plot_bgcolor='rgba(0,0,0,0)',
            paper_bgcolor='rgba(0,0,0,0)',
            width=cls.SINGLE_PLOT_WIDTH,
            height=cls.SINGLE_PLOT_HEIGHT,
            margin=cls.MARGIN
        )
        
        # Update x-axis
        fig.update_xaxes(
            showgrid=False,
            gridwidth=1,
            gridcolor=cls.GRID_COLOR,
            zeroline=False,
            showline=True,
            linewidth=cls.BORDER_WIDTH,
            linecolor=cls.BORDER_COLOR,
            mirror=True,
            ticks='inside',
            tickfont={'family': cls.FONT_FAMILY, 'size': cls.TICK_FONT_SIZE},
            tickcolor='black'
        )
        
        # Update primary y-axis
        fig.update_yaxes(
            showgrid=False,
            gridwidth=1,
            gridcolor=cls.GRID_COLOR,
            zeroline=False,
            showline=True,
            linewidth=cls.BORDER_WIDTH,
            linecolor=cls.BORDER_COLOR,
            mirror=True,
            ticks='inside',
            tickfont={'family': cls.FONT_FAMILY, 'size': cls.TICK_FONT_SIZE},
            tickcolor='black'
        )
        
        # Update secondary y-axis if it exists
        if hasattr(fig.layout, 'yaxis2'):
            fig.layout.yaxis2.update(
                showgrid=False,
                gridwidth=1,
                gridcolor=cls.GRID_COLOR,
                zeroline=False,
                showline=True,
                linewidth=cls.BORDER_WIDTH,
                linecolor=cls.BORDER_COLOR,
                mirror=True,
                ticks='inside',
                tickfont={'family': cls.FONT_FAMILY, 'size': cls.TICK_FONT_SIZE},
                tickcolor='black'
            )
            
            # Update secondary y-axis title if it exists
            if hasattr(fig.layout, 'yaxis2_title'):
                fig.layout.yaxis2_title.update(
                    font={'size': cls.AXIS_TITLE_FONT_SIZE, 'family': cls.FONT_FAMILY}
                )
        
        return fig
    
    @classmethod
    def style_multi_panel_plot(cls, fig, title, subplot_titles=None):
        """Style a multi-panel plot with consistent formatting"""
        fig.update_layout(
            title={
                'text': title,
                'font': {'size': cls.TITLE_FONT_SIZE, 'family': cls.FONT_FAMILY},
                'y': 0.98,
                'x': 0.5,
                'xanchor': 'center',
                'yanchor': 'top'
            },
            showlegend=True,
            legend=cls.LEGEND_SETTINGS,
            plot_bgcolor='rgba(0,0,0,0)',
            paper_bgcolor='rgba(0,0,0,0)',
            width=cls.SUBPLOT_WIDTH,
            height=cls.SUBPLOT_HEIGHT,
            margin=cls.MARGIN,
            font={'family': cls.FONT_FAMILY, 'size': cls.TICK_FONT_SIZE}
        )
        
        # Check if we can determine the number of rows and columns
        rows = 0
        cols = 0
        
        # Try to get rows and cols from grid
        if hasattr(fig.layout, 'grid') and fig.layout.grid is not None:
            rows = getattr(fig.layout.grid, 'rows', 0)
            cols = getattr(fig.layout.grid, 'cols', 0)
        
        # If we couldn't get rows and cols from grid, try to determine from annotations
        if rows == 0 or cols == 0:
            if hasattr(fig.layout, 'annotations') and fig.layout.annotations:
                # Estimate rows and cols from number of annotations
                # Assuming annotations are for subplot titles
                n_subplots = len(fig.layout.annotations)
                if n_subplots == 4:  # 2x2 grid
                    rows, cols = 2, 2
                elif n_subplots == 6:  # 2x3 or 3x2 grid
                    rows, cols = 2, 3
                elif n_subplots == 9:  # 3x3 grid
                    rows, cols = 3, 3
                else:
                    # Default to 1 row and n_subplots columns
                    rows, cols = 1, n_subplots
        
        # If we still couldn't determine rows and cols, use default values
        if rows == 0 or cols == 0:
            rows, cols = 2, 2  # Default to 2x2 grid
            
        # Update all axes with consistent styling
        for i in range(1, rows + 1):
            for j in range(1, cols + 1):
                # Update x-axes
                fig.update_xaxes(
                    showgrid=False,
                    gridwidth=1,
                    gridcolor=cls.GRID_COLOR,
                    zeroline=False,
                    showline=True,
                    linewidth=cls.BORDER_WIDTH,
                    linecolor=cls.BORDER_COLOR,
                    mirror=True,
                    ticks='inside',
                    tickfont={'family': cls.FONT_FAMILY, 'size': cls.TICK_FONT_SIZE},
                    tickcolor='black',
                    row=i, col=j
                )
                
                # Update y-axes
                fig.update_yaxes(
                    showgrid=False,
                    gridwidth=1,
                    gridcolor=cls.GRID_COLOR,
                    zeroline=False,
                    showline=True,
                    linewidth=cls.BORDER_WIDTH,
                    linecolor=cls.BORDER_COLOR,
                    mirror=True,
                    ticks='inside',
                    tickfont={'family': cls.FONT_FAMILY, 'size': cls.TICK_FONT_SIZE},
                    tickcolor='black',
                    row=i, col=j
                )
                
                # Update secondary y-axes if they exist
                if hasattr(fig.layout, f'yaxis{i}{j}'):
                    fig.update_yaxes(
                        showgrid=False,
                        gridwidth=1,
                        gridcolor=cls.GRID_COLOR,
                        zeroline=False,
                        showline=True,
                        linewidth=cls.BORDER_WIDTH,
                        linecolor=cls.BORDER_COLOR,
                        mirror=True,
                        ticks='inside',
                        tickfont={'family': cls.FONT_FAMILY, 'size': cls.TICK_FONT_SIZE},
                        tickcolor='black',
                        row=i, col=j,
                        secondary_y=True
                    )
                
                # Increase y-axis maximum by 15% to make room for legend
                if i == 1 and j == 1:  # Only for the first subplot
                    fig.update_yaxes(range=[None, None], row=i, col=j)  # Reset range first
                    # We'll adjust the range after data is plotted
        
        # 调整子图标题位置和样式
        if hasattr(fig.layout, 'annotations') and fig.layout.annotations:
            for i, annotation in enumerate(fig.layout.annotations):
                if i < len(subplot_titles) if subplot_titles else True:
                    # 更新字体
                    annotation.font.update(
                        size=cls.AXIS_TITLE_FONT_SIZE,
                        family=cls.FONT_FAMILY
                    )
                    # 调整位置到子图上方
                    annotation.update(
                        yanchor='bottom',
                        y=annotation.y + 0.05  # 向上移动
                    )
        
        return fig
    
    @classmethod
    def save_plot(cls, fig, filename, output_dir="load_analysis"):
        """Save a plot to a file with consistent formatting.
        
        Args:
            fig (plotly.graph_objects.Figure): The figure to save
            filename (str): The filename to save to
            output_dir (str): The directory to save to
        """
        # Create output directory if it doesn't exist
        if isinstance(output_dir, str):
            os.makedirs(output_dir, exist_ok=True)
            output_path = os.path.join(output_dir, filename)
        else:  # Assume it's a Path object
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = output_dir / filename
            
        # Save with higher quality settings
        fig.write_image(
            output_path, 
            scale=8.0,  # Increase scale for higher resolution
            width=fig.layout.width,
            height=fig.layout.height,
            engine="kaleido"
        )
        
        print(f"Plot saved to {output_path}")
        return output_path


class SystemVisualizer:
    """Visualization tools for PV-Battery system"""
    def __init__(self):
        # 使用更新后的颜色方案，增加更多墨绿、深棕、深红和青绿色系
        self.colors = {
            'pv': PlotStyler.COLORS[1],          # 深红色 Dark Red
            'battery': PlotStyler.COLORS[0],      # 钴蓝色 Cobalt Blue
            'load': PlotStyler.COLORS[6],         # 砖红色 Firebrick
            'grid': PlotStyler.COLORS[2],         # 墨绿色 Dark Green
            'battery_charge': PlotStyler.COLORS[3],    # 青绿色 Teal
            'battery_discharge': PlotStyler.COLORS[5], # 靛蓝色 Indigo
            'grid_export': PlotStyler.COLORS[4],      # 深棕色 Saddle Brown
            'radiation': PlotStyler.COLORS[9],        # 森林绿 Forest Green
            'temperature': PlotStyler.COLORS[7],      # 深青灰色 Dark Slate Gray
            'direct_radiation': PlotStyler.COLORS[8], # 赭石色 Sienna
            'diffuse_radiation': PlotStyler.COLORS[10], # 深岩蓝 Dark Slate Blue
            'shortwave_radiation': PlotStyler.COLORS[12], # 水鸭色 Teal
            'pv_only': PlotStyler.COLORS[11],     # 栗色 Maroon
            'pv_battery': PlotStyler.COLORS[13],  # 橄榄绿 Dark Olive Green
            'config1': PlotStyler.COLORS[15],     # 深青绿 Dark Teal
            'config2': PlotStyler.COLORS[16],     # 深洋红 Deep Pink
            'config3': PlotStyler.COLORS[17],     # 深森林绿 Dark Forest Green
            'config4': PlotStyler.COLORS[18]      # 深棕褐色 Deep Brown
        }
    
    def _apply_common_styling(self, fig: go.Figure) -> go.Figure:
        """Apply common styling to plots"""
        # Get current y-axis range for all y-axes
        for axis in fig.layout:
            if axis.startswith('yaxis') and hasattr(fig.layout[axis], 'range'):
                y_range = fig.layout[axis].range
                if y_range and len(y_range) == 2 and y_range[1] is not None:
                    y_max = y_range[1]
                    # Increase y-axis maximum by 15% to make room for legend
                    new_y_max = y_max * 1.15
                    fig.layout[axis].range = [y_range[0], new_y_max]
        
        fig.update_layout(
            plot_bgcolor='white',
            font=dict(family=PlotStyler.FONT_FAMILY, size=PlotStyler.TICK_FONT_SIZE),
            showlegend=True,
            legend=PlotStyler.LEGEND_SETTINGS,
            title=dict(
                font=dict(family=PlotStyler.FONT_FAMILY, size=PlotStyler.TITLE_FONT_SIZE)
            )
        )
        
        # Update axes
        for axis in fig.layout:
            if axis.startswith('xaxis') or axis.startswith('yaxis'):
                fig.layout[axis].update(
                    showgrid=False,
                    gridwidth=1,
                    gridcolor='rgba(200,200,200,0.2)',
                    showline=True,
                    linewidth=PlotStyler.BORDER_WIDTH,
                    linecolor=PlotStyler.BORDER_COLOR,
                    mirror=True,
                    ticks='inside',
                    tickfont=dict(family=PlotStyler.FONT_FAMILY, size=PlotStyler.TICK_FONT_SIZE),
                    tickwidth=2,
                    ticklen=8,
                    title=dict(font=dict(family=PlotStyler.FONT_FAMILY, size=PlotStyler.AXIS_TITLE_FONT_SIZE))
                )
        
        return fig
    
    def plot_power_flows(self, time_data: pd.Series, 
                        pv_power: np.ndarray,
                        load_profile: np.ndarray,
                        battery_power: np.ndarray,
                        grid_import: np.ndarray,
                        grid_export: np.ndarray) -> go.Figure:
        """Create power flow visualization"""
        fig = go.Figure()
        
        # Add traces
        fig.add_trace(
            go.Scatter(x=time_data, y=pv_power,
                      name='PV Generation',
                      line=dict(color=self.colors['pv'], width=3))
        )
        
        fig.add_trace(
            go.Scatter(x=time_data, y=load_profile,
                      name='Load',
                      line=dict(color=self.colors['load'], width=3))
        )
        
        fig.add_trace(
            go.Scatter(x=time_data, y=battery_power,
                      name='Battery Power',
                      line=dict(color=self.colors['battery'], width=3))
        )
        
        fig.add_trace(
            go.Scatter(x=time_data, y=grid_import,
                      name='Grid Import',
                      line=dict(color=self.colors['grid'], width=3, dash='dash'))
        )
        
        fig.add_trace(
            go.Scatter(x=time_data, y=-grid_export,
                      name='Grid Export',
                      line=dict(color=self.colors['grid'], width=3, dash='dot'))
        )
        
        # Update layout
        fig.update_layout(
            title='System Power Flows',
            xaxis_title='Time',
            yaxis_title='Power (kW)',
            width=PlotStyler.SINGLE_PLOT_WIDTH,
            height=PlotStyler.SINGLE_PLOT_HEIGHT
        )
        
        # Calculate y-axis range to add 15% headroom for legend
        y_values = np.concatenate([pv_power, load_profile, battery_power, grid_import, -grid_export])
        y_min = np.min(y_values)
        y_max = np.max(y_values)
        y_range = [y_min, y_max * 1.15]  # Add 15% to max for legend
        
        fig.update_yaxes(range=y_range)
        
        return self._apply_common_styling(fig)
    
    def plot_battery_state(self, time_data: pd.Series,
                          battery_soc: np.ndarray,
                          battery_energy: np.ndarray) -> go.Figure:
        """Create battery state visualization"""
        fig = make_subplots(rows=2, cols=1,
                           subplot_titles=('Battery State of Charge',
                                         'Battery Energy Level'),
                           vertical_spacing=0.2)
        
        # Add SOC trace
        fig.add_trace(
            go.Scatter(x=time_data, y=battery_soc * 100,
                      name='State of Charge',
                      line=dict(color=self.colors['battery'], width=3)),
            row=1, col=1
        )
        
        # Add energy level trace
        fig.add_trace(
            go.Scatter(x=time_data, y=battery_energy,
                      name='Energy Level',
                      line=dict(color=self.colors['battery'], width=3)),
            row=2, col=1
        )
        
        # Update layout
        fig.update_layout(
            height=PlotStyler.SUBPLOT_HEIGHT,
            width=PlotStyler.SINGLE_PLOT_WIDTH,
            title='Battery Performance'
        )
        
        fig.update_yaxes(title_text='SOC (%)', row=1, col=1)
        fig.update_yaxes(title_text='Energy (kWh)', row=2, col=1)
        
        # Calculate y-axis ranges to add 15% headroom for legend
        soc_max = np.max(battery_soc * 100)
        energy_max = np.max(battery_energy)
        
        fig.update_yaxes(range=[0, soc_max * 1.15], row=1, col=1)
        fig.update_yaxes(range=[0, energy_max * 1.15], row=2, col=1)
        
        return self._apply_common_styling(fig)
    
    def plot_daily_profiles(self, time_data: pd.Series,
                           pv_power: np.ndarray,
                           load_profile: np.ndarray,
                           battery_power: np.ndarray) -> go.Figure:
        """Create average daily profiles"""
        # Convert to DataFrame for easier grouping
        df = pd.DataFrame({
            'hour': time_data.hour,
            'pv': pv_power,
            'load': load_profile,
            'battery': battery_power
        })
        
        # Calculate average profiles
        daily = df.groupby('hour').mean()
        
        fig = go.Figure()
        
        # Add traces
        fig.add_trace(
            go.Scatter(x=daily.index, y=daily.pv,
                      name='Average PV Generation',
                      line=dict(color=self.colors['pv'], width=3))
        )
        
        fig.add_trace(
            go.Scatter(x=daily.index, y=daily.load,
                      name='Average Load',
                      line=dict(color=self.colors['load'], width=3))
        )
        
        fig.add_trace(
            go.Scatter(x=daily.index, y=daily.battery,
                      name='Average Battery Power',
                      line=dict(color=self.colors['battery'], width=3))
        )
        
        # Update layout
        fig.update_layout(
            title='Average Daily Profiles',
            xaxis_title='Hour of Day',
            yaxis_title='Power (kW)',
            width=PlotStyler.SINGLE_PLOT_WIDTH,
            height=PlotStyler.SINGLE_PLOT_HEIGHT
        )
        
        # Calculate y-axis range to add 15% headroom for legend
        y_values = np.concatenate([daily.pv, daily.load, daily.battery])
        y_min = np.min(y_values)
        y_max = np.max(y_values)
        y_range = [y_min, y_max * 1.15]  # Add 15% to max for legend
        
        fig.update_yaxes(range=y_range)
        
        return self._apply_common_styling(fig)
    
    def plot_cost_analysis(self, result: Dict) -> go.Figure:
        """Create cost analysis visualization"""
        fig = make_subplots(rows=1, cols=2,
                           subplot_titles=('Cost Breakdown',
                                         'System Metrics'),
                           specs=[[{'type': 'pie'}, {'type': 'bar'}]])
        
        # Cost breakdown pie chart
        lifetime_maintenance = result['annual_maintenance'] * 20  # Lifetime maintenance
        lifetime_electricity = result['actual_electricity_cost'] * 20  # Lifetime electricity cost
        
        costs = [
            result['capital_cost'],
            lifetime_maintenance,
            lifetime_electricity
        ]
        labels = ['Capital Cost', 'Lifetime Maintenance', 'Lifetime Electricity']
        
        fig.add_trace(
            go.Pie(values=costs,
                   labels=labels,
                   hole=0.4,
                   textinfo='label+percent',
                   marker=dict(colors=[PlotStyler.COLORS[0], PlotStyler.COLORS[1], PlotStyler.COLORS[2]])),
            row=1, col=1
        )
        
        # System metrics bar chart
        metrics = {
            'LCOE ($/kWh)': result['lcoe'],
            'Annual Savings ($)': result['annual_savings'],
            'Payback Period (years)': result['payback_period']
        }
        
        fig.add_trace(
            go.Bar(x=list(metrics.keys()),
                   y=list(metrics.values()),
                   marker_color=[self.colors['pv'], 
                               self.colors['grid'],
                               self.colors['battery']]),
            row=1, col=2
        )
        
        # Update layout
        fig.update_layout(
            height=PlotStyler.SINGLE_PLOT_HEIGHT,
            width=PlotStyler.SUBPLOT_WIDTH,
            title='System Cost Analysis'
        )
        
        # Increase y-axis maximum for bar chart by 15%
        y_max = max(metrics.values())
        fig.update_yaxes(range=[0, y_max * 1.15], row=1, col=2)
        
        return self._apply_common_styling(fig)
    
    def plot_payback_analysis(self, result: Dict) -> go.Figure:
        """Create payback period analysis visualization"""
        # Calculate yearly progression
        years = np.arange(0, int(np.ceil(result['payback_period'])) + 1)
        
        # Calculate cumulative savings for each year
        annual_savings = result['annual_savings']
        annual_maintenance = result['annual_maintenance']
        capital_cost = result['capital_cost']
        net_annual_savings = annual_savings - annual_maintenance
        
        cumulative_savings = np.array([net_annual_savings * year for year in years])
        
        # Create figure with secondary y-axis
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        
        # Add cumulative savings trace
        fig.add_trace(
            go.Scatter(x=years, y=cumulative_savings,
                      name='Cumulative Net Savings',
                      line=dict(color=self.colors['pv'], width=3)),
            secondary_y=False
        )
        
        # Add capital cost line
        fig.add_trace(
            go.Scatter(x=[0, max(years)],
                      y=[capital_cost, capital_cost],
                      name='Capital Cost',
                      line=dict(color=self.colors['grid'], 
                               width=3, dash='dash')),
            secondary_y=False
        )
        
        # Add payback point
        payback_period = result['payback_period']
        if payback_period < 999:  # Only show if valid payback period
            fig.add_trace(
                go.Scatter(x=[payback_period],
                          y=[capital_cost],
                          name='Payback Point',
                          mode='markers',
                          marker=dict(color=PlotStyler.COLORS[3], size=15, symbol='star')),
                secondary_y=False
            )
        
        # Add annual metrics as bar chart
        annual_metrics = {
            'Annual Savings': annual_savings,
            'Annual Maintenance': annual_maintenance,
            'Net Annual Savings': net_annual_savings
        }
        
        fig.add_trace(
            go.Bar(x=list(annual_metrics.keys()),
                   y=list(annual_metrics.values()),
                   name='Annual Metrics',
                   marker_color=[self.colors['pv'], 
                               self.colors['battery'],
                               self.colors['grid']]),
            secondary_y=True
        )
        
        # Update layout
        fig.update_layout(
            title='Payback Period Analysis',
            height=PlotStyler.SINGLE_PLOT_HEIGHT,
            width=PlotStyler.SINGLE_PLOT_WIDTH,
            hovermode='x'
        )
        
        # Update axes
        fig.update_xaxes(title_text='Years')
        fig.update_yaxes(title_text='Cumulative Savings ($)', secondary_y=False)
        fig.update_yaxes(title_text='Annual Amounts ($)', secondary_y=True)
        
        # Calculate y-axis ranges to add 15% headroom for legend
        primary_max = max(max(cumulative_savings), capital_cost)
        secondary_max = max(annual_metrics.values())
        
        fig.update_yaxes(range=[0, primary_max * 1.15], secondary_y=False)
        fig.update_yaxes(range=[0, secondary_max * 1.15], secondary_y=True)
        
        return self._apply_common_styling(fig)
    
    def create_system_plots(self, load_profile: np.ndarray,
                           weather_data: pd.DataFrame,
                           result: Dict) -> Dict[str, go.Figure]:
        """Create all system visualizations"""
        time_data = pd.date_range(start='2024-01-01',
                             periods=len(load_profile),
                             freq='H')
        
        # Extract performance and metrics data
        performance = result['performance']
        metrics = result['metrics']
        
        return {
            'power_flows': self.plot_power_flows(
                time_data,
                performance['pv_power'],
                load_profile,  # Already in kWh
                performance['battery_power'],
                performance['grid_import'],
                np.zeros_like(load_profile) if 'grid_export' not in performance else performance['grid_export']
            ),
            'battery_state': self.plot_battery_state(
                time_data,
                performance['battery_soc'],
                performance['battery_energy']
            ),
            'daily_profiles': self.plot_daily_profiles(
                time_data,
                performance['pv_power'],
                load_profile,
                performance['battery_power']
            ),
            'cost_analysis': self.plot_cost_analysis({
                'capital_cost': metrics['capital_cost'],
                'annual_maintenance': metrics['annual_maintenance'],
                'actual_electricity_cost': metrics['grid_cost'],
                'lcoe': metrics['lcoe'],
                'annual_savings': metrics['annual_savings'],
                'payback_period': metrics['payback_period']
            }),
            'payback_analysis': self.plot_payback_analysis({
                'capital_cost': metrics['capital_cost'],
                'annual_maintenance': metrics['annual_maintenance'],
                'annual_savings': metrics['annual_savings'],
                'payback_period': metrics['payback_period']
            })
        } 