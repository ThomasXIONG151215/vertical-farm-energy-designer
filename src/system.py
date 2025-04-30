from dataclasses import dataclass
import numpy as np
import pandas as pd
from typing import Dict, Tuple, List, Union, Optional, Any
import logging
logger = logging.getLogger(__name__)
import numba
from numba import cuda, jit, float32, int32, void
import warnings
from numba.core.errors import NumbaPerformanceWarning
import os
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from sklearn.metrics import r2_score, mean_squared_error
from scipy.optimize import minimize
import time
import functools

# Suppress Numba related warnings
warnings.filterwarnings('ignore', category=NumbaPerformanceWarning)
warnings.filterwarnings('ignore', module='numba')

from .utils import performance_monitor, detailed_memory_profile

@dataclass
class PVSystem:
    """PV system parameters and calculations based on Single Diode Model"""
    eta_pv: float = 0.233      # PV module efficiency according to Jinko 78 HL4-BDV
    beta: float = -0.0029     # Temperature coefficient (%/°C) according to Jinko 78 HL4-BDV
    eta_inv: float = 0.97     # Inverter efficiency
    T_ref: float = 25.0       # Reference temperature (°C)
    degradation_rate: float = 0.004  # Annual degradation rate 0.4% per year according to Jinko 78 HL4-BDV
    
    # Area and cost parameters
    area_to_power: float = 4.3  # Area to power ratio (m²/kWp)
    module_power: float = 0.64011  # Module power at STC (kWp) = V_mp0 * I_mp0
    module_area: float = 2.752  # Module area (m²) = area_to_power * module_power
    C_pv: float = 110.0       # Cost per kWp ($/kWp)
    install_rate: float = 0.11 # Installation cost rate
    maintenance_rate: float = 0.01  # Annual maintenance rate (1% of capital cost from Zhao 2024)
    
    # SDM parameters at STC
    I_sc_stc: float = 13.98    # Short circuit current at STC (A)
    V_oc_stc: float = 57.34    # Open circuit voltage at STC (V)
    I_mp_stc: float = 13.33    # Maximum power point current at STC (A)
    V_mp_stc: float = 48.02    # Maximum power point voltage at STC (V)
    N_s: int = 156            # Number of cells in series
    alpha_sc: float = 0.045   # Temperature coefficient of Isc (%/°C)
    beta_voc: float = -0.25   # Temperature coefficient of Voc (%/°C)
    NOCT: float = 45.0       # Nominal Operating Cell Temperature (°C)
    
    # Pre-calculated SDM parameters
    n: float = 0.4361        # Diode ideality factor
    R_s: float = 0.2688      # Series resistance (Ω)
    R_sh: float = 366.83     # Shunt resistance (Ω)
    
    @staticmethod
    @jit(nopython=True, fastmath=True)
    def _calculate_thermal_voltage(T_m: float) -> float:
        """Calculate thermal voltage"""
        k = 1.38e-23  # Boltzmann constant (J/K)
        q = 1.602e-19  # Electron charge (C)
        return (k * (T_m + 273.15)) / q
    
    @staticmethod
    @jit(nopython=True, fastmath=True)
    def _calculate_cell_temperature(T_amb: np.ndarray, G: np.ndarray, NOCT: float) -> np.ndarray:
        """Calculate cell temperature"""
        return T_amb + G * (NOCT - 20) / 800
    
    @staticmethod
    @jit(nopython=True, fastmath=True)
    def _calculate_reference_saturation_current(I_sc_stc: float, V_oc_stc: float, 
                                             R_s: float, R_sh: float, n: float, 
                                             N_s: int, V_th_stc: float) -> float:
        """Calculate reference saturation current at STC"""
        return ((R_sh + R_s) * I_sc_stc - V_oc_stc) / R_sh * np.exp(-V_oc_stc / (n * N_s * V_th_stc))
    
    @staticmethod
    @jit(nopython=True, fastmath=True)
    def _calculate_saturation_current(I_0_ref: float, T_m: float, T_ref: float) -> float:
        """Calculate temperature-dependent saturation current"""
        k = 1.38e-23  # Boltzmann constant
        E_g = 1.12 * 1.602e-19  # Bandgap energy of silicon in Joules
        return (I_0_ref * ((T_m + 273.15) / (T_ref + 273.15))**3 * 
                np.exp((E_g/k) * (1/(T_ref + 273.15) - 1/(T_m + 273.15))))
    
    @staticmethod
    @jit(nopython=True, fastmath=True)
    def _calculate_light_current(I_sc_stc: float, G: np.ndarray, G_stc: float,
                               alpha_sc: float, T_m: np.ndarray, T_ref: float,
                               R_s: float, R_sh: float) -> np.ndarray:
        """Calculate light-generated current"""
        return (I_sc_stc * G/G_stc + alpha_sc * (T_m - T_ref)) * (R_s + R_sh) / R_sh
    
    @staticmethod
    @jit(nopython=True, fastmath=True)
    def _calculate_pv_output_sdm(G: np.ndarray, T_amb: np.ndarray,
                               I_sc_stc: float, V_oc_stc: float,
                               n: float, N_s: int, R_s: float, R_sh: float,
                               alpha_sc: float, NOCT: float, T_ref: float,
                               eta_inv: float, A_pv: float) -> np.ndarray:
        """Calculate PV output using Single Diode Model"""
        # Constants
        G_stc = 1000.0  # Standard irradiance (W/m²)
        V_th_stc = 0.0257  # Thermal voltage at STC (V)
        k = 1.38e-23  # Boltzmann constant (J/K)
        q = 1.602e-19  # Electron charge (C)
        E_g = 1.12 * q  # Bandgap energy of silicon in Joules
        
        # Calculate cell temperature
        T_m = T_amb + G * (NOCT - 20) / 800
        
        # Calculate thermal voltage
        V_th = k * (T_m + 273.15) / q
        
        # Calculate reference saturation current
        I_0_ref = ((R_sh + R_s) * I_sc_stc - V_oc_stc) / R_sh * np.exp(-V_oc_stc / (n * N_s * V_th_stc))
        
        # Calculate temperature-dependent parameters
        I_L = (I_sc_stc * G/G_stc + alpha_sc * (T_m - T_ref)) * (R_s + R_sh) / R_sh
        
        # Calculate temperature-dependent saturation current with explicit array operations
        T_m_K = T_m + 273.15
        T_ref_K = T_ref + 273.15
        temp_ratio = T_m_K / T_ref_K
        temp_ratio_cubed = temp_ratio * temp_ratio * temp_ratio
        exp_term = np.exp((E_g/k) * (1/T_ref_K - 1/T_m_K))
        I_0 = I_0_ref * temp_ratio_cubed * exp_term
        
        # Initial guess for V_mp (80% of V_oc)
        V_mp = 0.8 * V_oc_stc * np.ones_like(G)
        
        # Calculate MPP using quadratic approximation
        a = -(R_s + R_sh) * R_s / (n * N_s * V_th)
        b = ((R_s + R_sh) * (1 + V_mp/(n * N_s * V_th)) + 
             (R_s/(n * N_s * V_th)) * ((I_L + I_0) * R_sh - V_mp))
        c = (2 * I_0 * R_sh - V_mp * ((I_L + I_0) * R_sh/(n * N_s * V_th) + 1) + 
             V_mp**2/(n * N_s * V_th))
        
        # Calculate I_mp using quadratic formula
        I_mp = (-b + np.sqrt(b**2 - 4*a*c))/(2*a)
        
        # Calculate power
        P_pv = V_mp * I_mp * eta_inv * A_pv / 1000  # Convert to kW
        
        return P_pv
    
    def calculate_pv_output(self, weather_data: pd.DataFrame, A_pv: float, use_gpu: bool = True) -> np.ndarray:
        """Calculate PV array output power in kW based on total PV area"""
        # Validate weather data
        required_columns = ['shortwave_radiation', 'direct_radiation', 'diffuse_radiation', 'temperature_2m']
        missing_columns = [col for col in required_columns if col not in weather_data.columns]
        if missing_columns:
            raise ValueError(f"Missing required columns in weather_data: {missing_columns}")
        
        # Pre-calculate total radiation
        G = (weather_data['direct_radiation'].values + 
             weather_data['diffuse_radiation'].values)
        T_amb = weather_data['temperature_2m'].values
        
        # Create a mask for zero radiation
        zero_radiation_mask = G <= 0
        
        if use_gpu and cuda.is_available():
            # GPU calculation
            stream = cuda.stream()
            with cuda.pinned(G), cuda.pinned(T_amb):
                G_gpu = cuda.to_device(G, stream=stream)
                T_amb_gpu = cuda.to_device(T_amb, stream=stream)
                output_gpu = cuda.device_array(len(G), stream=stream)
                
                threads_per_block = 256
                blocks_per_grid = (len(G) + threads_per_block - 1) // threads_per_block
                
                self._calculate_pv_output_gpu[blocks_per_grid, threads_per_block, stream](
                    G_gpu, T_amb_gpu,
                    self.I_sc_stc, self.V_oc_stc,
                    self.n, self.N_s, self.R_s, self.R_sh,
                    self.alpha_sc, self.NOCT, self.T_ref,
                    self.eta_inv, A_pv,
                    output_gpu
                )
                
                P_pv = output_gpu.copy_to_host(stream=stream)
                stream.synchronize()
        else:
            # CPU calculation with vectorized operations
            P_pv = self._calculate_pv_output_sdm(
                G, T_amb,
                self.I_sc_stc, self.V_oc_stc,
                self.n, self.N_s, self.R_s, self.R_sh,
                self.alpha_sc, self.NOCT, self.T_ref,
                self.eta_inv, A_pv
            )
        
        # Ensure PV output is positive (generation is positive)
        P_pv = np.abs(P_pv)
        
        # Set PV output to zero when there's no solar radiation
        P_pv[zero_radiation_mask] = 0.0
        
        return P_pv
    
    def validate_with_reference_data(self, ref_data_path: str = 'literature_review/ref_data.csv', 
                                  use_gpu: bool = False, fit_model: bool = True) -> Dict:
        """
        Validate the PV model using reference data
        
        Args:
            ref_data_path: Path to reference data CSV file
            use_gpu: Whether to use GPU acceleration
            fit_model: Whether to fit the cell temperature model coefficients
            
        Returns:
            Dictionary with validation results and metrics
        """
        # Check if reference data file exists
        if not os.path.exists(ref_data_path):
            raise FileNotFoundError(f"Reference data file not found: {ref_data_path}")
        
        # Load reference data
        ref_data = pd.read_csv(ref_data_path)
        
        # Extract required columns
        DNI = ref_data['radiation(W/m2)'].values
        T_amb = ref_data['outdoor_T(C)'].values
        P_measured = ref_data['ref_pv_output(W)'].values
        
        # Fit cell temperature model if requested
        if fit_model:
            self._fit_cell_temperature_model(ref_data)
            logger.info(f"Fitted cell temperature model: Tc = {self.a_coef:.6f}*T_amb^2 + {self.b_coef:.6f}*T_amb + {self.c_coef:.6f} + {self.d_coef:.6f}*DNI")
            logger.info(f"Fitted PV efficiency model: eta = {self.eta_ref:.6f} * [1 + {self.beta_ref:.6f}*(T_c - {self.T_ref})]")
        
        # Calculate cell temperature using the model
        T_c = self._calculate_cell_temperature(T_amb, DNI, self.a_coef, self.b_coef, self.c_coef, self.d_coef)
        
        # Calculate PV efficiency
        eta = self._calculate_pv_efficiency(T_c, self.eta_ref, self.beta_ref, self.T_ref)
        
        # Calculate PV output using literature model
        P_predicted = self.calculate_pv_output_literature(DNI, T_c, use_gpu=use_gpu)
        
        # Calculate performance metrics
        r2 = r2_score(P_measured, P_predicted)
        nmbe = np.mean(P_predicted - P_measured) / np.mean(P_measured) if np.mean(P_measured) > 0 else np.nan
        cvrmse = np.sqrt(mean_squared_error(P_measured, P_predicted)) / np.mean(P_measured) if np.mean(P_measured) > 0 else np.nan
        
        # Group data by date for daily analysis
        ref_data['date'] = pd.to_datetime(ref_data['date']).dt.date
        dates = ref_data['date'].unique()
        
        daily_metrics = {}
        for date in dates:
            date_mask = ref_data['date'] == date
            P_measured_day = ref_data.loc[date_mask, 'ref_pv_output(W)'].values
            P_predicted_day = P_predicted[date_mask]
            
            # Calculate daily metrics
            r2_day = r2_score(P_measured_day, P_predicted_day) if len(P_measured_day) > 1 else np.nan
            nmbe_day = np.mean(P_predicted_day - P_measured_day) / np.mean(P_measured_day) if np.mean(P_measured_day) > 0 else np.nan
            cvrmse_day = np.sqrt(mean_squared_error(P_measured_day, P_predicted_day)) / np.mean(P_measured_day) if np.mean(P_measured_day) > 0 else np.nan
            
            daily_metrics[str(date)] = {
                'r2': r2_day,
                'nmbe': nmbe_day,
                'cvrmse': cvrmse_day,
                'measured': P_measured_day,
                'predicted': P_predicted_day,
                'hours': ref_data.loc[date_mask, 'hour'].values,
                'T_amb': T_amb[date_mask],
                'T_c': T_c[date_mask],
                'DNI': DNI[date_mask],
                'eta': eta[date_mask]
            }
        
        # Prepare results dictionary
        results = {
            'overall_metrics': {
                'r2': r2,
                'nmbe': nmbe,
                'cvrmse': cvrmse
            },
            'daily_metrics': daily_metrics,
            'measured': P_measured,
            'predicted': P_predicted,
            'radiation': DNI,
            'temperature': {
                'ambient': T_amb,
                'cell': T_c
            },
            'efficiency': eta,
            'hours': ref_data['hour'].values,
            'dates': [str(date) for date in dates],
            'ref_data': ref_data,
            'cell_temp_model': {
                'a': self.a_coef,
                'b': self.b_coef,
                'c': self.c_coef,
                'd': self.d_coef
            },
            'pv_efficiency_model': {
                'eta_ref': self.eta_ref,
                'beta_ref': self.beta_ref,
                'T_ref': self.T_ref
            }
        }
        
        return results
    
    def _fit_cell_temperature_model(self, ref_data: pd.DataFrame) -> None:
        """
        Fit the cell temperature model and PV efficiency model coefficients using reference data
        
        Args:
            ref_data: Reference data DataFrame
        """
        from scipy.optimize import minimize
        
        # Extract data
        T_amb = ref_data['outdoor_T(C)'].values
        P_measured = ref_data['ref_pv_output(W)'].values
        DNI = ref_data['radiation(W/m2)'].values
        
        # Define the objective function for optimization
        def objective(params):
            a, b, c, d, eta_ref, beta_ref = params
            T_c = self._calculate_cell_temperature(T_amb, DNI, a, b, c, d)
            P_predicted = self._calculate_pv_output_literature_cpu(
                DNI, T_c,
                self.P_m_stc, self.DNI_stc, self.alpha_p, self.T_c_stc,
                4, eta_ref, beta_ref, self.T_ref
            )
            return np.sum((P_predicted - P_measured)**2)
        
        # Initial guess for coefficients
        initial_guess = [self.a_coef, self.b_coef, self.c_coef, self.d_coef, self.eta_ref, self.beta_ref]
        
        # Parameter bounds
        bounds = [
            (-0.01, 0.01),    # a: small quadratic effect
            (0.8, 1.2),       # b: close to 1
            (0.0, 10.0),      # c: positive offset
            (0.0, 0.05),      # d: small radiation effect
            (0.1, 0.25),      # eta_ref: typical PV efficiency range
            (-0.01, -0.001)   # beta_ref: negative temperature coefficient
        ]
        
        try:
            # Method 1: Direct optimization of PV output with bounds
            result = minimize(objective, initial_guess, method='L-BFGS-B', bounds=bounds)
            if result.success:
                self.a_coef, self.b_coef, self.c_coef, self.d_coef, self.eta_ref, self.beta_ref = result.x
                logger.info(f"Successfully fitted cell temperature and PV efficiency models")
                logger.info(f"Cell temperature model: Tc = {self.a_coef:.6f}*T_amb^2 + {self.b_coef:.6f}*T_amb + {self.c_coef:.6f} + {self.d_coef:.6f}*DNI")
                logger.info(f"PV efficiency model: eta = {self.eta_ref:.6f} * [1 + {self.beta_ref:.6f}*(T_c - {self.T_ref})]")
            else:
                logger.warning(f"Failed to fit models using direct optimization: {result.message}")
                
                # Use reasonable default values if optimization fails
                self.a_coef = 0.001    # Small quadratic effect
                self.b_coef = 1.05     # Slightly higher than ambient
                self.c_coef = 3.0      # Offset due to solar heating
                self.d_coef = 0.01     # Small radiation effect
                self.eta_ref = 0.15    # Typical PV efficiency
                self.beta_ref = -0.004 # Typical temperature coefficient
                
        except Exception as e:
            logger.error(f"Error fitting models: {str(e)}")
            # Use default values
            self.a_coef = 0.001
            self.b_coef = 1.05
            self.c_coef = 3.0
            self.d_coef = 0.01
            self.eta_ref = 0.15
            self.beta_ref = -0.004
    
    def plot_validation_results(self, validation_results: Dict) -> Dict[str, go.Figure]:
        """
        Create plots for validation results using PlotStyler
        
        Args:
            validation_results: Dictionary with validation results from validate_with_reference_data
            
        Returns:
            Dictionary of plotly figures
        """
        from .visualization import PlotStyler
        
        figures = {}
        
        # 1. Measured vs Predicted scatter plot
        fig_scatter = go.Figure()
        
        fig_scatter.add_trace(go.Scatter(
            x=validation_results['measured'],
            y=validation_results['predicted'],
            mode='markers',
            marker=dict(
                color=PlotStyler.COLORS[0],
                size=10,
                opacity=0.7
            ),
            name='Data Points'
        ))
        
        # Add identity line
        max_val = max(np.max(validation_results['measured']), np.max(validation_results['predicted']))
        fig_scatter.add_trace(go.Scatter(
            x=[0, max_val],
            y=[0, max_val],
            mode='lines',
            line=dict(color='black', dash='dash'),
            name='Identity Line'
        ))
        
        # Add metrics annotation
        metrics_text = (
            f"R² = {validation_results['overall_metrics']['r2']:.3f}<br>"
            f"NMBE = {validation_results['overall_metrics']['nmbe']:.2%}<br>"
            f"CV(RMSE) = {validation_results['overall_metrics']['cvrmse']:.2%}"
        )
        
        fig_scatter.add_annotation(
            x=0.05 * max_val,
            y=0.95 * max_val,
            text=metrics_text,
            showarrow=False,
            font=dict(size=PlotStyler.ANNOTATION_FONT_SIZE),
            bgcolor='rgba(255, 255, 255, 0.8)',
            bordercolor='black',
            borderwidth=1
        )
        
        PlotStyler.style_single_plot(
            fig_scatter, 
            'PV Model Validation: Measured vs Predicted Output',
            'Measured PV Output (W)',
            'Predicted PV Output (W)'
        )
        
        figures['scatter'] = fig_scatter
        
        # 2. Daily profiles
        fig_daily = make_subplots(
            rows=len(validation_results['dates']), 
            cols=1,
            subplot_titles=[f"Daily Profile: {date}" for date in validation_results['dates']],
            vertical_spacing=0.1
        )
        
        for i, date in enumerate(validation_results['dates']):
            daily_data = validation_results['daily_metrics'][date]
            
            fig_daily.add_trace(
                go.Scatter(
                    x=daily_data['hours'],
                    y=daily_data['measured'],
                    mode='lines+markers',
                    name=f'Measured ({date})',
                    line=dict(color=PlotStyler.COLORS[0], width=2),
                    marker=dict(size=8),
                    showlegend=(i == 0)  # Only show legend for first date
                ),
                row=i+1, col=1
            )
            
            fig_daily.add_trace(
                go.Scatter(
                    x=daily_data['hours'],
                    y=daily_data['predicted'],
                    mode='lines+markers',
                    name=f'Predicted ({date})',
                    line=dict(color=PlotStyler.COLORS[1], width=2, dash='dash'),
                    marker=dict(size=8),
                    showlegend=(i == 0)  # Only show legend for first date
                ),
                row=i+1, col=1
            )
            
            # Add metrics annotation
            metrics_text = (
                f"R² = {daily_data['r2']:.3f}, "
                f"NMBE = {daily_data['nmbe']:.2%}, "
                f"CV(RMSE) = {daily_data['cvrmse']:.2%}"
            )
            
            fig_daily.add_annotation(
                x=daily_data['hours'][0],
                y=max(np.max(daily_data['measured']), np.max(daily_data['predicted'])),
                text=metrics_text,
                showarrow=False,
                font=dict(size=PlotStyler.ANNOTATION_FONT_SIZE - 2),
                bgcolor='rgba(255, 255, 255, 0.8)',
                bordercolor='black',
                borderwidth=1,
                xanchor='left',
                yanchor='top',
                row=i+1, col=1
            )
        
        # Update layout
        fig_daily.update_layout(
            height=300 * len(validation_results['dates']),
            width=PlotStyler.SINGLE_PLOT_WIDTH,
            title={
                'text': 'PV Model Validation: Daily Profiles',
                'font': {'size': PlotStyler.TITLE_FONT_SIZE},
                'y': 0.99,
                'x': 0.5,
                'xanchor': 'center',
                'yanchor': 'top'
            },
            margin=PlotStyler.MARGIN,
            plot_bgcolor='rgba(0,0,0,0)',
            paper_bgcolor='rgba(0,0,0,0)'
        )
        
        # Update all xaxes and yaxes
        for i in range(len(validation_results['dates'])):
            fig_daily.update_xaxes(
                title_text='Hour of Day',
                title_font={'size': PlotStyler.AXIS_TITLE_FONT_SIZE - 2},
                tickfont={'size': PlotStyler.TICK_FONT_SIZE - 2},
                row=i+1, col=1
            )
            
            fig_daily.update_yaxes(
                title_text='PV Output (W)',
                title_font={'size': PlotStyler.AXIS_TITLE_FONT_SIZE - 2},
                tickfont={'size': PlotStyler.TICK_FONT_SIZE - 2},
                row=i+1, col=1
            )
        
        figures['daily_profiles'] = fig_daily
        
        # 3. Combined daily profile with all days
        fig_combined = go.Figure()
        
        for i, date in enumerate(validation_results['dates']):
            daily_data = validation_results['daily_metrics'][date]
            
            fig_combined.add_trace(
                go.Scatter(
                    x=daily_data['hours'],
                    y=daily_data['measured'],
                    mode='lines+markers',
                    name=f'Measured ({date})',
                    line=dict(color=PlotStyler.COLORS[i % len(PlotStyler.COLORS)], width=2),
                    marker=dict(size=8)
                )
            )
            
            fig_combined.add_trace(
                go.Scatter(
                    x=daily_data['hours'],
                    y=daily_data['predicted'],
                    mode='lines+markers',
                    name=f'Predicted ({date})',
                    line=dict(color=PlotStyler.COLORS[i % len(PlotStyler.COLORS)], width=2, dash='dash'),
                    marker=dict(size=8)
                )
            )
        
        PlotStyler.style_single_plot(
            fig_combined, 
            'PV Model Validation: Combined Daily Profiles',
            'PV Output (W)',
            'Hour of Day'
        )
        
        figures['combined_profile'] = fig_combined
        
        # 4. Cell Temperature Model
        fig_temp = go.Figure()
        
        # Get unique ambient temperatures and sort them
        T_amb = validation_results['temperature']['ambient']
        T_c = validation_results['temperature']['cell']
        
        # Create a range of temperatures for the model curve
        T_amb_range = np.linspace(np.min(T_amb), np.max(T_amb), 100)
        a = validation_results['cell_temp_model']['a']
        b = validation_results['cell_temp_model']['b']
        c = validation_results['cell_temp_model']['c']
        d = validation_results['cell_temp_model']['d']
        
        # For visualization, use average DNI value
        avg_DNI = np.mean(validation_results['radiation'])
        T_c_model = a * T_amb_range**2 + b * T_amb_range + c + d * avg_DNI
        
        # Add scatter plot of actual data points
        fig_temp.add_trace(
            go.Scatter(
                x=T_amb,
                y=T_c,
                mode='markers',
                marker=dict(
                    color=PlotStyler.COLORS[0],
                    size=10,
                    opacity=0.7
                ),
                name='Calculated Cell Temperature'
            )
        )
        
        # Add model curve
        fig_temp.add_trace(
            go.Scatter(
                x=T_amb_range,
                y=T_c_model,
                mode='lines',
                line=dict(color=PlotStyler.COLORS[1], width=2),
                name=f'Model: Tc = {a:.4f}*T_amb² + {b:.4f}*T_amb + {c:.4f} + {d:.4f}*DNI'
            )
        )
        
        # Add identity line (Tc = Tamb)
        fig_temp.add_trace(
            go.Scatter(
                x=[np.min(T_amb), np.max(T_amb)],
                y=[np.min(T_amb), np.max(T_amb)],
                mode='lines',
                line=dict(color='black', dash='dash'),
                name='Tc = Tamb'
            )
        )
        
        PlotStyler.style_single_plot(
            fig_temp, 
            'Cell Temperature Model',
            'Ambient Temperature (°C)',
            'Cell Temperature (°C)'
        )
        
        figures['cell_temperature'] = fig_temp
        
        # 5. PV Efficiency Model
        fig_eff = go.Figure()
        
        # Get efficiency data
        eta = validation_results['efficiency']
        
        # Create a range of cell temperatures for the model curve
        T_c_range = np.linspace(np.min(T_c), np.max(T_c), 100)
        eta_ref = validation_results['pv_efficiency_model']['eta_ref']
        beta_ref = validation_results['pv_efficiency_model']['beta_ref']
        T_ref = validation_results['pv_efficiency_model']['T_ref']
        eta_model = eta_ref * (1.0 + beta_ref * (T_c_range - T_ref))
        
        # Add scatter plot of calculated efficiency
        fig_eff.add_trace(
            go.Scatter(
                x=T_c,
                y=eta,
                mode='markers',
                marker=dict(
                    color=PlotStyler.COLORS[0],
                    size=10,
                    opacity=0.7
                ),
                name='Calculated PV Efficiency'
            )
        )
        
        # Add model curve
        fig_eff.add_trace(
            go.Scatter(
                x=T_c_range,
                y=eta_model,
                mode='lines',
                line=dict(color=PlotStyler.COLORS[1], width=2),
                name=f'Model: η = {eta_ref:.4f} * [1 + {beta_ref:.4f}*(Tc - {T_ref})]'
            )
        )
        
        PlotStyler.style_single_plot(
            fig_eff, 
            'PV Efficiency Model',
            'Cell Temperature (°C)',
            'PV Efficiency'
        )
        
        figures['pv_efficiency'] = fig_eff
        
        # 6. Temperature and Radiation Profiles
        fig_temp_rad = make_subplots(
            rows=len(validation_results['dates']), 
            cols=1,
            subplot_titles=[f"Temperature and Radiation: {date}" for date in validation_results['dates']],
            vertical_spacing=0.1,
            specs=[[{"secondary_y": True}] for _ in range(len(validation_results['dates']))]
        )
        
        for i, date in enumerate(validation_results['dates']):
            daily_data = validation_results['daily_metrics'][date]
            
            # Add ambient temperature
            fig_temp_rad.add_trace(
                go.Scatter(
                    x=daily_data['hours'],
                    y=daily_data['T_amb'],
                    mode='lines+markers',
                    name=f'Ambient Temp ({date})',
                    line=dict(color=PlotStyler.COLORS[0], width=2),
                    marker=dict(size=8),
                    showlegend=(i == 0)  # Only show legend for first date
                ),
                row=i+1, col=1,
                secondary_y=False
            )
            
            # Add cell temperature
            fig_temp_rad.add_trace(
                go.Scatter(
                    x=daily_data['hours'],
                    y=daily_data['T_c'],
                    mode='lines+markers',
                    name=f'Cell Temp ({date})',
                    line=dict(color=PlotStyler.COLORS[1], width=2, dash='dash'),
                    marker=dict(size=8),
                    showlegend=(i == 0)  # Only show legend for first date
                ),
                row=i+1, col=1,
                secondary_y=False
            )
            
            # Add radiation
            fig_temp_rad.add_trace(
                go.Scatter(
                    x=daily_data['hours'],
                    y=daily_data['DNI'],
                    mode='lines+markers',
                    name=f'Radiation ({date})',
                    line=dict(color=PlotStyler.COLORS[2], width=2),
                    marker=dict(size=8),
                    showlegend=(i == 0)  # Only show legend for first date
                ),
                row=i+1, col=1,
                secondary_y=True
            )
        
        # Update layout
        fig_temp_rad.update_layout(
            height=300 * len(validation_results['dates']),
            width=PlotStyler.SINGLE_PLOT_WIDTH,
            title={
                'text': 'Temperature and Radiation Profiles',
                'font': {'size': PlotStyler.TITLE_FONT_SIZE},
                'y': 0.99,
                'x': 0.5,
                'xanchor': 'center',
                'yanchor': 'top'
            },
            margin=PlotStyler.MARGIN,
            plot_bgcolor='rgba(0,0,0,0)',
            paper_bgcolor='rgba(0,0,0,0)'
        )
        
        # Update all xaxes and yaxes
        for i in range(len(validation_results['dates'])):
            fig_temp_rad.update_xaxes(
                title_text='Hour of Day',
                title_font={'size': PlotStyler.AXIS_TITLE_FONT_SIZE - 2},
                tickfont={'size': PlotStyler.TICK_FONT_SIZE - 2},
                row=i+1, col=1
            )
            
            fig_temp_rad.update_yaxes(
                title_text='Temperature (°C)',
                title_font={'size': PlotStyler.AXIS_TITLE_FONT_SIZE - 2},
                tickfont={'size': PlotStyler.TICK_FONT_SIZE - 2},
                row=i+1, col=1,
                secondary_y=False
            )
            
            fig_temp_rad.update_yaxes(
                title_text='Radiation (W/m²)',
                title_font={'size': PlotStyler.AXIS_TITLE_FONT_SIZE - 2},
                tickfont={'size': PlotStyler.TICK_FONT_SIZE - 2},
                row=i+1, col=1,
                secondary_y=True
            )
        
        figures['temp_rad_profiles'] = fig_temp_rad
        
        return figures
    
    def calculate_costs(self, A_pv: float) -> Dict[str, float]:
        """
        Calculate PV system costs based on total area
        Returns costs in $
        """
        # Convert area to peak power
        P_peak = A_pv / self.area_to_power  # Convert m² to kWp
        
        # Calculate capital cost based on peak power
        capital_cost = P_peak * self.C_pv * (1 + self.install_rate)
        
        # Annual maintenance cost (1% of capital cost as per Zhao 2024)
        annual_maintenance = self.maintenance_rate * capital_cost
        
        return {
            'capital_cost': capital_cost,
            'annual_maintenance': annual_maintenance,
            'peak_power': P_peak
        }

@dataclass
class BatterySystem:
    """Battery system parameters and calculations based on Zhao 2024 model"""
    # Battery parameters
    c_energy: float = 220.0   # Energy capacity cost ($/kWh) - Zhao 2024 Chinese price was 280, we use current price of 90 according to the 0.65CNY/kWh estimated by PWCC
    c_rate: float = 1     # C-rate limit for charge/discharge (Zhao 2024)
    eta_ch: float = 0.91     # Charging efficiency (Zhao 2024)
    eta_dis: float = 0.91    # Discharging efficiency (Zhao 2024)
    soc_min: float = 0.1     # Minimum SOC (Zhao 2024)
    soc_max: float = 0.9     # Maximum SOC (Zhao 2024)
    cycle_life: float = 4000  # Battery cycle life (Zhao 2024)
    calendar_life: float = 25  # Calendar life in years (Zhao 2024)
    self_discharge: float = 0 #0.0009  # Daily self-discharge rate (Zhao 2024)
    maintenance_rate: float = 0.01  # Annual maintenance rate (1% of capital cost from Zhao 2024)
    maintenance_cost: float = 1.24  # Maintenance cost ($/kWh) - CYBD
    
    @staticmethod
    @jit(nopython=True, fastmath=True)
    def _calculate_battery_flows(power_balance, E_bat, eta_ch, eta_dis,
                               soc_min, soc_max, c_rate, self_discharge,
                               initial_soc=0.5):
        """
        Optimized battery power flow calculation
        """
        n_steps = len(power_balance)
        battery_power = np.zeros(n_steps)  # Total battery power flow
        battery_discharge = np.zeros(n_steps)  # Discharge power for load satisfaction
        battery_energy = np.zeros(n_steps + 1)
        battery_soc = np.zeros(n_steps + 1)
        
        # Initialize battery state
        battery_energy[0] = initial_soc * E_bat
        battery_soc[0] = initial_soc
        
        total_charged = 0.0
        total_discharged = 0.0
        hourly_self_discharge = self_discharge / 24
        max_power = c_rate * E_bat
        
        for t in range(n_steps):
            # Apply self-discharge
            battery_energy[t] *= (1 - hourly_self_discharge)
            current_soc = battery_energy[t] / E_bat
            
            # Note: power_balance = pv_power - load_profile
            # With positive PV values, excess power is when power_balance > 0
            if power_balance[t] > 0:  # Excess power, can charge battery
                if current_soc < soc_max:
                    # Calculate available space ensuring we don't exceed soc_max
                    available_space = (soc_max * E_bat - battery_energy[t]) / eta_ch
                    charge_power = min(power_balance[t], available_space, max_power)
                    battery_power[t] = charge_power
                    
                    # Calculate new energy level and ensure it doesn't exceed max SOC
                    new_energy = battery_energy[t] + charge_power * eta_ch
                    battery_energy[t + 1] = min(new_energy, soc_max * E_bat)
                    
                    # Only count actual energy stored in the battery
                    actual_charged = battery_energy[t + 1] - battery_energy[t]
                    total_charged += actual_charged
                else:
                    battery_power[t] = 0
                    battery_energy[t + 1] = battery_energy[t]
                battery_discharge[t] = 0  # No discharge during charging
            else:  # Power deficit, may discharge battery
                power_needed = -power_balance[t]  # Convert to positive value
                if current_soc > soc_min and power_needed > 0:
                    # Calculate available energy ensuring we don't go below soc_min
                    available_energy = (battery_energy[t] - soc_min * E_bat) * eta_dis
                    discharge_power = min(power_needed, available_energy, max_power)
                    battery_power[t] = -discharge_power  # Negative for discharge in battery_power
                    battery_discharge[t] = discharge_power  # Positive for load satisfaction
                    
                    # Calculate new energy level and ensure it doesn't go below min SOC
                    new_energy = battery_energy[t] - discharge_power / eta_dis
                    battery_energy[t + 1] = max(new_energy, soc_min * E_bat)
                    
                    # Only count actual energy discharged from the battery
                    actual_discharged = (battery_energy[t] - battery_energy[t + 1]) * eta_dis
                    total_discharged += actual_discharged
                else:
                    battery_power[t] = 0
                    battery_discharge[t] = 0
                    battery_energy[t + 1] = battery_energy[t]
            
            battery_soc[t + 1] = battery_energy[t + 1] / E_bat
        
        return battery_power, battery_discharge, battery_energy, battery_soc, total_charged, total_discharged
    
    def calculate_battery_parameters(self, E_bat: float) -> Dict[str, float]:
        """
        Calculate battery system parameters based on total energy capacity
        
        Args:
            E_bat: Total battery capacity in kWh
            
        Returns:
            Dictionary of battery parameters
        """
        return {
            'capacity': E_bat,  # kWh
            'max_charge_rate': self.c_rate * E_bat,    # kW
            'max_discharge_rate': self.c_rate * E_bat,  # kW
            'charge_efficiency': self.eta_ch,
            'discharge_efficiency': self.eta_dis
        }
    
    def calculate_power_flows(self, power_balance: np.ndarray, load_profile: np.ndarray, 
                            E_bat: float, use_gpu: bool = False) -> Dict[str, np.ndarray]:
        """Calculate battery power flows based on power balance and load"""
        # If no battery capacity, return zero arrays
        if E_bat <= 0:
            n_steps = len(load_profile)
            return {
                'battery_energy': np.zeros(n_steps + 1),
                'battery_power': np.zeros(n_steps),
                'battery_discharge': np.zeros(n_steps),  # Add discharge power array
                'battery_soc': np.zeros(n_steps + 1),
                'battery_throughput': 0.0,
                'total_charged_energy': 0.0,
                'total_discharged_energy': 0.0
            }
        
        # Calculate battery flows using optimized function
        battery_power, battery_discharge, battery_energy, battery_soc, total_charged, total_discharged = \
            self._calculate_battery_flows(
                power_balance, E_bat,
                self.eta_ch, self.eta_dis,
                self.soc_min, self.soc_max,
                self.c_rate, self.self_discharge
            )
        
        # Calculate battery throughput
        battery_throughput = np.sum(np.abs(battery_power))
        
        return {
            'battery_energy': battery_energy,
            'battery_power': battery_power,
            'battery_discharge': battery_discharge,  # Add discharge power to return dict
            'battery_soc': battery_soc,
            'battery_throughput': battery_throughput,
            'total_charged_energy': total_charged,
            'total_discharged_energy': total_discharged
        }
    
    def calculate_costs(self, E_bat: float) -> Dict[str, float]:
        """
        Calculate battery system costs based on Zhao 2024 model
        Returns costs in $
        """
        # Calculate capital cost based on energy capacity
        capital_cost = E_bat * self.c_energy
        
        # Annual maintenance cost (1% of capital cost as per Zhao 2024)
        annual_maintenance = self.maintenance_cost * E_bat
        
        return {
            'capital_cost': capital_cost,
            'annual_maintenance': annual_maintenance
        }

class EnergySystem:
    """Combined PV-Battery system manager based on Zhao 2024 model"""
    def __init__(self, use_gpu: bool = False):
        self.pv = PVSystem()
        self.battery = BatterySystem()
        self.interest_rate = 0.06  # 6% discount rate
        self.lifetime = 25.0       # Project lifetime in years
        self.use_gpu = use_gpu and cuda.is_available()
        
        # Grid electricity prices (location-specific)
        self.grid_prices = {
            'peak': 0.096,     # Peak price ($/kWh) #0.7CNY/kWh
            'normal': 0.096,   # Normal price ($/kWh)
            'valley': 0.096    # Valley price ($/kWh)
        }
        
        # Time periods definition
        self.peak_hours = list(range(10, 15)) + list(range(18, 22))     # 10:00-14:00, 18:00-21:00
        self.valley_hours = list(range(0, 6)) + [23]                     # 23:00-5:00
        
        if self.use_gpu:
            logger.info("Using GPU acceleration for system calculations")
        else:
            logger.info("Using CPU optimization for system calculations")
    
    def validate_pv_model(self, ref_data_path: str = 'literature_review/ref_data.csv', 
                       output_dir: str = 'results/pv_validation', 
                       save_plots: bool = True,
                       fit_model: bool = True) -> Dict:
        """
        Validate the PV model using reference data
        
        Args:
            ref_data_path: Path to reference data CSV file
            output_dir: Directory to save validation plots
            save_plots: Whether to save plots to files
            fit_model: Whether to fit the cell temperature model
            
        Returns:
            Dictionary with validation results and metrics
        """
        # Validate PV model
        validation_results = self.pv.validate_with_reference_data(
            ref_data_path=ref_data_path,
            use_gpu=self.use_gpu,
            fit_model=fit_model
        )
        
        # Generate plots
        figures = self.pv.plot_validation_results(validation_results)
        
        # Save plots if requested
        if save_plots:
            self.save_validation_plots(figures, output_dir)
        
        return {
            'validation_results': validation_results,
            'figures': figures
        }
    
    def save_validation_plots(self, figures: Dict[str, go.Figure], output_dir: str) -> None:
        """
        Save validation plots to the specified output directory.
        
        Args:
            figures: Dictionary of plotly figures to save
            output_dir: Directory to save plots to
        """
        # Create output directory if it doesn't exist
        os.makedirs(output_dir, exist_ok=True)
        
        # Save each figure
        for name, fig in figures.items():
            # Save as PNG
            png_path = os.path.join(output_dir, f"{name}.png")
            fig.write_image(png_path, width=1200, height=800)
            logger.info(f"Saved plot to {png_path}")
            
            # Save as HTML
            html_path = os.path.join(output_dir, f"{name}.html")
            fig.write_html(html_path)
            logger.info(f"Saved interactive plot to {html_path}")
            
        logger.info(f"All validation plots saved to {output_dir}")
        
        # Create an index.html file that links to all the HTML plots
        index_path = os.path.join(output_dir, "index.html")
        with open(index_path, "w") as f:
            f.write("<html>\n<head>\n")
            f.write("<title>PV Model Validation Results</title>\n")
            f.write("<style>\n")
            f.write("body { font-family: Arial, sans-serif; margin: 20px; }\n")
            f.write("h1 { color: #2c3e50; }\n")
            f.write("h2 { color: #3498db; margin-top: 30px; }\n")
            f.write(".plot-container { margin-bottom: 30px; }\n")
            f.write(".plot-link { display: inline-block; margin-right: 20px; }\n")
            f.write("</style>\n")
            f.write("</head>\n<body>\n")
            f.write("<h1>PV Model Validation Results</h1>\n")
            
            for name in figures.keys():
                title = name.replace('_', ' ').title()
                f.write(f"<h2>{title}</h2>\n")
                f.write("<div class='plot-container'>\n")
                f.write(f"  <div class='plot-link'><a href='{name}.html'>Interactive Plot (HTML)</a></div>\n")
                f.write(f"  <div class='plot-link'><a href='{name}.png'>Static Image (PNG)</a></div>\n")
                f.write(f"  <img src='{name}.png' width='800' />\n")
                f.write("</div>\n")
            
            f.write("</body>\n</html>")
            
        logger.info(f"Created index file at {index_path}")
        
        return
    
    @performance_monitor
    @detailed_memory_profile
    def calculate_metrics(self,
                        x: np.ndarray,
                        weather_data: pd.DataFrame,
                        load_profile: np.ndarray) -> Dict:
        """Calculate all system metrics for given configuration"""
        # Simulate system performance
        performance = self.simulate_performance(x, weather_data, load_profile)
        
        # Calculate costs and financial metrics
        cost_metrics = self.calculate_costs(x, performance, load_profile)
        
        # Calculate TLPS (Time Loss of Power Supply) using battery discharge
        power_deficit = np.maximum(0, load_profile - 
                                 (performance['pv_power'] + performance['battery_discharge']))
        tlps = np.sum(power_deficit > 0) / len(load_profile)
        
        # Calculate annual metrics
        annual_pv_generation = np.sum(performance['pv_power'])
        annual_grid_import = np.sum(performance['grid_import'])
        
        # Create complete metrics dictionary
        metrics = {
            'capital_cost': cost_metrics['capital_cost'],
            'annual_savings': cost_metrics['annual_savings'],
            'payback_period': cost_metrics['payback_period'],
            'annual_maintenance': cost_metrics['annual_maintenance'],
            'grid_cost': cost_metrics['actual_cost'],  # Grid import cost
            'pv_depreciation': cost_metrics['capital_cost'] / self.lifetime,
            'battery_depreciation': cost_metrics['battery_capital'] / self.lifetime,
            'annual_pv_generation': annual_pv_generation,
            'annual_grid_import': annual_grid_import,
            'annual_grid_export': 0.0,  # No grid export
            'tlps': tlps * 100,  # Convert to percentage
            'lcoe': cost_metrics['lcoe']
        }
        
        return metrics
    
    def simulate_performance(self, x: np.ndarray, weather_data: pd.DataFrame, 
                            load_profile: np.ndarray, is_independent: bool = False) -> Dict[str, np.ndarray]:
        """Simulate system performance based on Zhao 2024 model"""
        A_pv = max(0, x[0])  # PV area in m²
        E_bat = max(0, x[1])  # Battery capacity in kWh
        
        # Calculate PV generation
        pv_power = self.pv.calculate_pv_output(weather_data, A_pv, use_gpu=self.use_gpu)
        
        # Set PV generation to 0 when it's negative (no generation at night)
        pv_power = np.maximum(pv_power, 0)
        
        # Initialize grid import array and grid export (excess PV) array
        n_steps = len(load_profile)
        grid_import = np.zeros(n_steps)
        grid_export = np.zeros(n_steps)  # Track excess PV that's not used or stored
        
        # Calculate power balance
        power_balance = pv_power - load_profile
        
        # Initialize battery results
        battery_flows = {
            'battery_power': np.zeros_like(load_profile),
            'battery_discharge': np.zeros_like(load_profile),
            'battery_energy': np.zeros(n_steps + 1),
            'battery_soc': np.zeros(n_steps + 1),
            'battery_throughput': 0.0
        }
        
        if E_bat > 0:
            # Battery operation when battery exists
            battery_flows = self.battery.calculate_power_flows(
                power_balance=power_balance,
                load_profile=load_profile,
                E_bat=E_bat,
                use_gpu=self.use_gpu
            )
            
            # Recalculate grid import based on battery operation
            for t in range(n_steps):
                # Calculate direct PV usage (limited by load)
                direct_pv_usage = min(pv_power[t], load_profile[t])
                
                # Calculate remaining load after direct PV usage
                remaining_load = load_profile[t] - direct_pv_usage
                
                # Use battery discharge to meet remaining load
                battery_used = min(battery_flows['battery_discharge'][t], remaining_load)
                
                # Any remaining load must be imported from grid
                grid_import[t] = remaining_load - battery_used
                
                # Calculate excess PV after direct usage and battery charging
                excess_pv = pv_power[t] - direct_pv_usage - battery_flows['battery_power'][t]
                
                # Any excess PV is exported/wasted
                grid_export[t] = max(0, excess_pv)
        else:
            # No battery: direct grid import if PV is insufficient
            for t in range(n_steps):
                # Calculate direct PV usage (limited by load)
                direct_pv_usage = min(pv_power[t], load_profile[t])
                
                # Calculate remaining load after direct PV usage
                remaining_load = load_profile[t] - direct_pv_usage
                
                # Any remaining load must be imported from grid
                grid_import[t] = remaining_load
                
                # Calculate excess PV after direct usage
                excess_pv = pv_power[t] - direct_pv_usage
                
                # Any excess PV is exported/wasted
                grid_export[t] = max(0, excess_pv)
        
        # Calculate battery cycles
        battery_cycles = (battery_flows['battery_throughput'] / (2 * E_bat) 
                         if E_bat > 0 else 0.0)
        
        return {
            'pv_power': pv_power,
            'battery_power': battery_flows['battery_power'],
            'battery_discharge': battery_flows['battery_discharge'],
            'battery_energy': battery_flows['battery_energy'],
            'battery_soc': battery_flows['battery_soc'],
            'grid_import': grid_import,
            'grid_export': grid_export,  # Add grid export to track wasted PV
            'battery_cycles': battery_cycles,
            'battery_throughput': battery_flows['battery_throughput'],
            'total_charged_energy': battery_flows.get('total_charged_energy', 0),
            'total_discharged_energy': battery_flows.get('total_discharged_energy', 0)
        }
    
    def calculate_costs(self, 
                       x: np.ndarray,
                       performance: Dict[str, np.ndarray],
                       load_profile: np.ndarray) -> Dict[str, float]:
        """Calculate all system costs"""
        A_pv = x[0]  # PV area in m²
        E_bat = x[1]  # Battery capacity in kWh
        
        # Get component costs - only if components exist
        pv_costs = self.pv.calculate_costs(A_pv) if A_pv > 0 else {'capital_cost': 0, 'annual_maintenance': 0}
        battery_costs = self.battery.calculate_costs(E_bat) if E_bat > 0 else {'capital_cost': 0, 'annual_maintenance': 0}
        
        # Calculate capital costs (C_cap)
        capital_cost = pv_costs['capital_cost'] + battery_costs['capital_cost']
        
        # Calculate O&M costs
        annual_om = pv_costs['annual_maintenance'] + battery_costs['annual_maintenance']
        
        # Calculate electricity costs with time-of-use pricing
        times = pd.date_range(start='2024-01-01', periods=len(load_profile), freq='H')
        baseline_costs = np.zeros_like(load_profile)
        actual_costs = np.zeros_like(performance['grid_import'])
        
        peak_cost = 0
        valley_cost = 0
        normal_cost = 0
        
        for t in range(len(load_profile)):
            hour = times[t].hour
            if hour in self.peak_hours:
                price = self.grid_prices['peak']
                peak_cost += performance['grid_import'][t] * price
            elif hour in self.valley_hours:
                price = self.grid_prices['valley']
                valley_cost += performance['grid_import'][t] * price
            else:
                price = self.grid_prices['normal']
                normal_cost += performance['grid_import'][t] * price
            
            baseline_costs[t] = load_profile[t] * price
            actual_costs[t] = performance['grid_import'][t] * price
        
        annual_baseline = np.sum(baseline_costs)
        annual_actual = np.sum(actual_costs)
        annual_savings = annual_baseline - annual_actual
        
        # Calculate total annual energy served (load met by all sources)
        total_annual_energy = np.sum(load_profile)
        
        # Calculate LCOE using the dedicated method
        lcoe = self.calculate_lcoe(
            capital_cost=capital_cost,
            annual_om=annual_om,
            annual_grid_cost=annual_actual,
            annual_energy=total_annual_energy
        )
        
        # Calculate total costs for reporting
        total_lifetime_cost = capital_cost
        for year in range(1, int(self.lifetime) + 1):
            discount_factor = (1 + self.interest_rate) ** year
            total_lifetime_cost += (annual_om + annual_actual) / discount_factor
            
        total_lifetime_energy = total_annual_energy * self.lifetime
        
        # Calculate power shortage metrics
        total_demand = np.sum(load_profile)
        total_shortage = np.sum(np.maximum(0, load_profile - (performance['pv_power'] + performance['battery_power'])))
        shortage_percentage = (total_shortage / total_demand * 100) if total_demand > 0 else 100
        
        return {
            'capital_cost': capital_cost,
            'battery_capital': battery_costs['capital_cost'],
            'annual_maintenance': annual_om,
            'baseline_cost': annual_baseline,
            'actual_cost': annual_actual,
            'annual_savings': annual_savings,
            'peak_cost': peak_cost,
            'valley_cost': valley_cost,
            'normal_cost': normal_cost,
            'payback_period': (capital_cost + annual_om) / annual_savings if annual_savings > 0 else float('inf'),
            'lcoe': lcoe,
            'total_annual_cost': annual_om + annual_actual,
            'total_lifetime_cost': total_lifetime_cost,
            'total_lifetime_energy': total_lifetime_energy,
            'shortage_percentage': shortage_percentage,
            'total_shortage': total_shortage,
            'total_demand': total_demand
        }
    
    def calculate_lcoe(self, 
                         capital_cost: float,
                         annual_om: float,
                         annual_grid_cost: float,
                         annual_energy: float) -> float:
        """
        Calculate Levelized Cost of Energy according to Zhao 2024 model:
        LCOE = (C_cap + sum(C_O&M,t + C_grid,t)/(1+r)^t) / sum(E_t/(1+r)^t)
        
        Args:
            capital_cost: Total capital cost ($)
            annual_om: Annual O&M cost ($/year)
            annual_grid_cost: Annual grid electricity cost ($/year)
            annual_energy: Annual energy served (kWh/year)
            
        Returns:
            LCOE in $/kWh
        """
        if annual_energy == 0:
            return float('inf')
        
        # Capital cost is not discounted
        numerator = capital_cost
        denominator = 0
        
        # Calculate discounted sums in numerator and denominator
        for year in range(1, int(self.lifetime) + 1):
            discount_factor = (1 + self.interest_rate) ** year
            # Add discounted annual costs to numerator
            numerator += (annual_om + annual_grid_cost) / discount_factor
            # Add discounted annual energy to denominator
            denominator += annual_energy / discount_factor
        
        if denominator == 0:
            return float('inf')
        
        return numerator / denominator

    def check_power_balance(self, pv_power: np.ndarray, load_profile: np.ndarray, 
                           E_bat: float) -> Tuple[bool, float]:
        """
        快速检查是否存在供电不足的情况
        
        Args:
            pv_power: PV输出功率
            load_profile: 负载需求
            E_bat: 电池容量
            
        Returns:
            (is_feasible, max_deficit): 是否可行，最大功率缺口
        """
        max_battery_discharge = E_bat * self.battery.c_rate if E_bat > 0 else 0
        power_balance = pv_power - load_profile
        
        # 找出所有功率缺口时刻
        deficit_mask = power_balance < 0
        if not np.any(deficit_mask):
            return True, 0.0
        
        # 计算最大功率缺口
        max_deficit = np.max(-power_balance[deficit_mask])
        
        # 如果最大功率缺口超过电池最大放电功率，则方案不可行
        return max_deficit <= max_battery_discharge, max_deficit
