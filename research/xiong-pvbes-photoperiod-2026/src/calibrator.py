import numpy as np
import pandas as pd
from pathlib import Path
import logging
from typing import Dict, List, Tuple
import time
from tqdm import tqdm
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import warnings
import matplotlib.pyplot as plt
import seaborn as sns

from .system import EnergySystem
from .optimizer import SystemOptimizer
from .utils import load_schedule

# Suppress all Numba related logs
logging.getLogger('numba').setLevel(logging.WARNING)
warnings.filterwarnings('ignore', module='numba')

logger = logging.getLogger(__name__)

class StepSizeCalibrator:
    """Calibrate optimal step sizes for PV area and battery capacity"""
    
    def __init__(self, reference_city: str, pv_max: float, battery_max: float, step_sizes: List[float]):
        self.city = reference_city
        self.pv_max = pv_max
        self.battery_max = battery_max
        self.step_sizes = sorted(step_sizes)  # Sort from smallest to largest
        self.energy_system = EnergySystem()
        self.optimizer = SystemOptimizer(self.energy_system)
        self.all_results = []  # Store all results for comparison
        
        # Create results directory
        self.results_dir = Path("calibration_results")
        self.results_dir.mkdir(exist_ok=True)
        
        logger.info(f"Initialized calibrator for {reference_city}")
        logger.info(f"PV range: 0-{pv_max}m², Battery range: 0-{battery_max}kWh")
        logger.info(f"Step sizes to test: {step_sizes}")
        logger.info(f"Total combinations to test: {len(step_sizes) * len(step_sizes) * 2}")  # Each base step has a doubled version
    
    def _load_weather_data(self) -> pd.DataFrame:
        """Load weather data for reference city"""
        weather_file = Path(f"test_case/{self.city}/weather/{self.city}_2024.csv")
        if not weather_file.exists():
            raise FileNotFoundError(f"Weather data not found for {self.city}")
        return pd.read_csv(weather_file)
    
    def _load_load_profile(self) -> np.ndarray:
        """Load a representative load profile"""
        # Use the first available schedule file
        schedule_dir = Path(f"test_case/{self.city}/output")
        schedule_files = list(schedule_dir.glob("annual_energy_schedule_*.csv"))
        if not schedule_files:
            raise FileNotFoundError(f"No schedule files found for {self.city}")
        return load_schedule(schedule_files[0])
    
    def _generate_step_combinations(self) -> List[Dict]:
        """Generate step size combinations to test
        For each base step size x, test:
        1. (x, x) - base steps
        2. (2x, 2x) - doubled steps
        3. (x, 2x) - base PV with doubled battery
        4. (2x, x) - doubled PV with base battery
        """
        combinations = []
        for pv_base_step in self.step_sizes:
            for battery_base_step in self.step_sizes:
                # Test base step combination (x, x)
                combinations.append({
                    'pv_step': pv_base_step,
                    'battery_step': battery_base_step,
                    'is_base': True,
                    'pv_base': pv_base_step,
                    'battery_base': battery_base_step
                })
                
                # Test doubled step combination (2x, 2x)
                combinations.append({
                    'pv_step': pv_base_step * 2,
                    'battery_step': battery_base_step * 2,
                    'is_base': False,
                    'pv_base': pv_base_step,
                    'battery_base': battery_base_step
                })
                
                # Test mixed combination (x, 2x)
                combinations.append({
                    'pv_step': pv_base_step,
                    'battery_step': battery_base_step * 2,
                    'is_mixed': True,
                    'is_base': False,
                    'pv_base': pv_base_step,
                    'battery_base': battery_base_step
                })
                
                # Test mixed combination (2x, x)
                combinations.append({
                    'pv_step': pv_base_step * 2,
                    'battery_step': battery_base_step,
                    'is_mixed': True,
                    'is_base': False,
                    'pv_base': pv_base_step,
                    'battery_base': battery_base_step
                })
        
        logger.info(f"Generated {len(combinations)} combinations to test:")
        logger.info(f"- Base combinations (x, x)")
        logger.info(f"- Doubled combinations (2x, 2x)")
        logger.info(f"- Mixed combinations (x, 2x) and (2x, x)")
        
        return combinations
    
    def _test_step_combination(self, combo: Dict, weather_data: pd.DataFrame, 
                             load_profile: np.ndarray) -> Dict:
        """Test a single combination of step sizes"""
        # Calculate PV and battery metrics directly
        pv_power = self.energy_system.pv.calculate_pv_output(
            weather_data=weather_data,
            A_pv=combo['pv_step']
        )
        
        battery_flows = self.energy_system.battery.calculate_power_flows(
            power_balance=pv_power - load_profile,
            load_profile=load_profile,
            E_bat=combo['battery_step']
        )
        
        # Calculate LCOE
        metrics = self.energy_system.calculate_metrics(
            x=np.array([combo['pv_step'], combo['battery_step']]),
            weather_data=weather_data,
            load_profile=load_profile
        )
        
        return {
            'city': self.city,
            'pv_step': combo['pv_step'],
            'battery_step': combo['battery_step'],
            'is_base': combo['is_base'],
            'pv_base': combo['pv_base'],
            'battery_base': combo['battery_base'],
            'lcoe': metrics['lcoe']
        }
    
    def _calculate_lcoe_variations(self, results: Dict) -> Dict:
        """Calculate LCOE variations between different step size combinations"""
        # For base step results, return zero variations
        if results['is_base']:
            return {
                'max_pv_variation': 0,
                'max_battery_variation': 0,
                'avg_pv_variation': 0,
                'avg_battery_variation': 0
            }
        
        # Find the base result for comparison
        base_result = next(r for r in self.all_results 
                         if r['pv_base'] == results['pv_base'] 
                         and r['battery_base'] == results['battery_base']
                         and r['is_base'])
        
        # Calculate variation percentage
        variation = abs(results['lcoe'] - base_result['lcoe']) / base_result['lcoe'] * 100
        
        # For mixed combinations, only report variation for the doubled parameter
        if results.get('is_mixed', False):
            is_pv_doubled = results['pv_step'] > results['pv_base']
            return {
                'max_pv_variation': variation if is_pv_doubled else 0,
                'max_battery_variation': variation if not is_pv_doubled else 0,
                'avg_pv_variation': variation if is_pv_doubled else 0,
                'avg_battery_variation': variation if not is_pv_doubled else 0
            }
        else:
            # For fully doubled combinations, report variation for both parameters
            return {
                'max_pv_variation': variation,
                'max_battery_variation': variation,
                'avg_pv_variation': variation,
                'avg_battery_variation': variation
            }
    
    def _select_optimal_steps(self, all_results: List[Dict]) -> Dict:
        """Select optimal step sizes based on results"""
        # Filter out failed results
        valid_results = [r for r in all_results if r is not None]
        
        # Group results by base step size
        step_pairs = {}
        for result in valid_results:
            key = (result['pv_base'], result['battery_base'])
            if key not in step_pairs:
                step_pairs[key] = {'base': None, 'doubled': None}
            if result['is_base']:
                step_pairs[key]['base'] = result
            else:
                step_pairs[key]['doubled'] = result
        
        # Analyze each step size pair
        acceptable_steps = {
            'pv': set(),
            'battery': set()
        }
        
        for (pv_base, battery_base), pair in step_pairs.items():
            if pair['base'] is None or pair['doubled'] is None:
                continue
                
            # Calculate LCOE difference percentage
            lcoe_diff_percent = abs(pair['doubled']['lcoe'] - pair['base']['lcoe']) / pair['base']['lcoe'] * 100
            
            # Check PV step size
            if lcoe_diff_percent < 5.0:  # Only check LCOE variation
                acceptable_steps['pv'].add(pv_base * 2)  # Use doubled step if acceptable
            else:
                acceptable_steps['pv'].add(pv_base)  # Use base step if needed
            
            # Check battery step size
            if lcoe_diff_percent < 5.0:  # Only check LCOE variation
                acceptable_steps['battery'].add(battery_base * 2)  # Use doubled step if acceptable
            else:
                acceptable_steps['battery'].add(battery_base)  # Use base step if needed
        
        # Select largest acceptable step sizes
        optimal_steps = {
            'pv': max(acceptable_steps['pv']) if acceptable_steps['pv'] else min(self.step_sizes),
            'battery': max(acceptable_steps['battery']) if acceptable_steps['battery'] else min(self.step_sizes)
        }
        
        # Calculate performance metrics
        baseline_configs = (self.pv_max / min(self.step_sizes)) * (self.battery_max / min(self.step_sizes))
        optimal_configs = (self.pv_max / optimal_steps['pv']) * (self.battery_max / optimal_steps['battery'])
        computation_reduction = (baseline_configs - optimal_configs) / baseline_configs * 100
        
        return {
            'pv_area_step': optimal_steps['pv'],
            'battery_step': optimal_steps['battery'],
            'analysis': {
                'computation_reduction': computation_reduction
            }
        }
    
    def _create_visualizations(self, all_results: List[Dict]) -> None:
        """Create visualization plots for calibration results"""
        # Prepare data for plots
        plot_data = []
        for r in all_results:
            if r is not None and not r['is_base']:  # Only look at doubled/mixed combinations
                plot_data.append({
                    'pv_base_step': r['pv_base'],
                    'battery_base_step': r['battery_base'],
                    'step_type': 'Mixed' if r.get('is_mixed', False) else 'Doubled',
                    'lcoe_diff_percent': abs(r['lcoe'] - next(
                        base_r['lcoe'] for base_r in all_results 
                        if base_r['is_base'] 
                        and base_r['pv_base'] == r['pv_base']
                        and base_r['battery_base'] == r['battery_base']
                    )) / r['lcoe'] * 100
                })
        
        df = pd.DataFrame(plot_data)
        
        # Calculate average differences for each base step combination
        avg_diff = df.groupby(['pv_base_step', 'battery_base_step'])['lcoe_diff_percent'].mean().reset_index()
        
        # Create heatmap
        plt.figure(figsize=(12, 8), dpi=300)
        pivot_table = avg_diff.pivot(
            index='battery_base_step',
            columns='pv_base_step',
            values='lcoe_diff_percent'
        )
        
        sns.heatmap(pivot_table, 
                    annot=True, 
                    fmt='.2f',
                    cmap='YlOrRd',
                    cbar_kws={'label': 'Average LCOE Difference (%)'},
                    vmin=0,
                    vmax=10)
        
        plt.title('Average LCOE Difference (%) for Different Step Size Combinations')
        plt.xlabel('PV Step Size (m²)')
        plt.ylabel('Battery Step Size (kWh)')
        
        # Save plot
        plt.tight_layout()
        plt.savefig(self.results_dir / f"{self.city}_step_size_heatmap.png", 
                    dpi=300, 
                    bbox_inches='tight')
        plt.close()
        
        # Create bar plot for step types
        plt.figure(figsize=(12, 6), dpi=300)
        sns.boxplot(data=df, x='pv_base_step', y='lcoe_diff_percent', hue='step_type')
        plt.title('LCOE Differences by Step Size and Type')
        plt.xlabel('Base Step Size')
        plt.ylabel('LCOE Difference (%)')
        
        # Save plot
        plt.tight_layout()
        plt.savefig(self.results_dir / f"{self.city}_step_size_comparison.png", 
                    dpi=300, 
                    bbox_inches='tight')
        plt.close()
        
        logger.info(f"Visualization plots saved to {self.results_dir}")
    
    def run(self) -> Dict:
        """Run the calibration process"""
        try:
            # Load data
            weather_data = self._load_weather_data()
            load_profile = self._load_load_profile()
            
            # Generate combinations
            combinations = self._generate_step_combinations()
            
            # Test all combinations
            self.all_results = []  # Clear previous results
            with tqdm(combinations, desc="Calibrating step sizes", ncols=100) as pbar:
                for combo in pbar:
                    result = self._test_step_combination(combo, weather_data, load_profile)
                    if result:
                        result['lcoe_variations'] = self._calculate_lcoe_variations(result)
                        self.all_results.append(result)
                        
                        pbar.set_postfix({
                            'PV': f"{combo['pv_step']:.1f}",
                            'Batt': f"{combo['battery_step']:.1f}"
                        }, refresh=True)
            
            # Select optimal steps
            optimal_steps = self._select_optimal_steps(self.all_results)
            
            # Save all results to CSV
            results_df = pd.DataFrame([
                {
                    'city': r['city'],
                    'pv_step': r['pv_step'],
                    'battery_step': r['battery_step'],
                    'step_type': 'Base' if r['is_base'] else 'Mixed' if r.get('is_mixed', False) else 'Doubled',
                    'lcoe': r['lcoe'],
                    'max_pv_variation': r['lcoe_variations']['max_pv_variation'],
                    'max_battery_variation': r['lcoe_variations']['max_battery_variation']
                }
                for r in self.all_results
            ])
            
            # Save to calibration_results directory
            results_df.to_csv(self.results_dir / f"{self.city}_step_size_results.csv", index=False)
            
            # Create visualizations
            self._create_visualizations(self.all_results)
            
            # Log final results only
            logger.info(f"\nCalibration complete!")
            logger.info(f"Optimal steps - PV: {optimal_steps['pv_area_step']:.1f}m², Battery: {optimal_steps['battery_step']:.1f}kWh")
            logger.info(f"Computation reduction: {optimal_steps['analysis']['computation_reduction']:.1f}%")
            
            return optimal_steps
            
        except Exception as e:
            logger.error(f"Calibration failed: {str(e)}")
            raise 