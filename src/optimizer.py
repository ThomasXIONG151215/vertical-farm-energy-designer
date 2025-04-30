import numpy as np
from typing import Dict, List, Tuple
import pandas as pd
import logging
from tqdm import tqdm
from tabulate import tabulate
import traceback
from pathlib import Path
import warnings
from numba.core.errors import NumbaPerformanceWarning

# Suppress Numba related warnings
warnings.filterwarnings('ignore', category=NumbaPerformanceWarning)
warnings.filterwarnings('ignore', module='numba')

from .system import PVSystem, BatterySystem, EnergySystem
from .utils import performance_monitor, detailed_memory_profile

logger = logging.getLogger(__name__)

class SystemOptimizer:
    """Optimizer for PV-Battery system using enumeration method"""
    def __init__(self, energy_system, results_dir=None):
        self.energy_system = energy_system
        self.results_dir = results_dir
        
        # Default configuration ranges and steps
        self.pv_area_range = (0.0, 200.0)  # m²
        self.battery_range = (0.0, 100.0)  # kWh
        self.pv_area_step = 10  # m²
        self.battery_step = 5  # kWh
        
        logger.info("Initialized SystemOptimizer")
        logger.info(f"PV range: {self.pv_area_range} m², step: {self.pv_area_step} m²")
        logger.info(f"Battery range: {self.battery_range} kWh, step: {self.battery_step} kWh")
    
    @performance_monitor
    @detailed_memory_profile
    def _optimize_enumeration(self, 
                            problem_data: Dict,
                            pv_area_range: tuple = None,
                            battery_range: tuple = None,
                            pv_area_step: float = None,
                            battery_step: float = None) -> dict:
        """
        Enumerate all possible configurations and find the optimal solution
        
        Args:
            problem_data: Dictionary containing energy system, weather data, load profile, and constraints
            pv_area_range: (min_area, max_area) in m²
            battery_range: (min_capacity, max_capacity) in kWh
            pv_area_step: Step size for PV area in m²
            battery_step: Step size for battery capacity in kWh
        """
        # Use class defaults if not specified
        pv_area_range = pv_area_range or self.pv_area_range
        battery_range = battery_range or self.battery_range
        pv_area_step = pv_area_step or self.pv_area_step
        battery_step = battery_step or self.battery_step
        
        try:
            energy_system = problem_data['energy_system']
            weather_data = problem_data['weather_data']
            load_profile = problem_data['load_profile']
            constraints = problem_data.get('constraints', {})
            city = problem_data.get('city')
            scenario = problem_data.get('scenario', 'grid_connected')
            
            # Extract schedule information from constraints
            schedule_start = constraints.get('schedule_start', 0)
            schedule_end = constraints.get('schedule_end', 0)
            photoperiod = constraints.get('photoperiod', 0)
            
            # Log city information
            logger.info(f"Processing optimization for city: {city}")
            if not city:
                logger.warning("City parameter is missing or None!")
            
            # Get constraint values with defaults
            tlps_max = constraints.get('tlps_max', 100)  # Maximum allowed TLPS in %
            soc_min = constraints.get('soc_min', 0.1)    # Minimum battery SOC
            soc_max = constraints.get('soc_max', 0.9)    # Maximum battery SOC
            max_charge_rate = constraints.get('max_charge_rate', 0.5)  # Maximum C-rate for charging
            max_discharge_rate = constraints.get('max_discharge_rate', 0.5)  # Maximum C-rate for discharging
            
            logger.info("Optimization Constraints:")
            logger.info(f"  - Maximum TLPS: {tlps_max}%")
            logger.info(f"  - Battery SOC Range: {soc_min*100:.0f}%-{soc_max*100:.0f}%")
            logger.info(f"  - Max Charge/Discharge C-rate: {max_charge_rate:.1f}C/{max_discharge_rate:.1f}C")
            logger.info(f"  - Schedule: {schedule_start:02d}:00-{schedule_end:02d}:00 ({photoperiod}h)")
            
            best_solution = None
            best_objective = float('inf')
            best_metrics = None
            best_performance = None
            feasible_configs = 0
            
            # Create progress bar for PV area configurations
            n_steps_pv = int((pv_area_range[1] - pv_area_range[0]) / pv_area_step) + 1
            n_steps_battery = int((battery_range[1] - battery_range[0]) / battery_step) + 1
            total_configs = n_steps_pv * n_steps_battery
            
            # Prepare list to store all solutions
            all_solutions = []
            
            logger.info(f"Starting enumeration of {total_configs} configurations...")
            
            # Ensure city is passed as-is
            if not city:
                city = 'unknown'
            
            # Create main progress bar
            with tqdm(total=total_configs, desc=f"Optimizing {city} ({scenario or 'default'})", unit="config") as pbar:
                # Enumerate all possible configurations
                for pv_area in np.arange(pv_area_range[0], pv_area_range[1] + pv_area_step, pv_area_step):
                    for battery_capacity in np.arange(battery_range[0], battery_range[1] + battery_step, battery_step):
                        x = np.array([pv_area, battery_capacity])
                        
                        # Simulate system performance
                        performance = energy_system.simulate_performance(x, weather_data, load_profile)
                        metrics = energy_system.calculate_metrics(x, weather_data, load_profile)
                        
                        # Calculate PV utilization
                        total_pv = metrics['annual_pv_generation']
                        total_load = np.sum(load_profile)
                        pv_used = min(total_pv, total_load - metrics['annual_grid_import'])
                        metrics['annual_pv_used'] = pv_used
                        
                        # Check constraints
                        is_feasible = True
                        constraint_violations = []
                        
                        if battery_capacity > 0:
                            # Check battery SOC constraints
                            if np.min(performance['battery_soc']) < soc_min:
                                is_feasible = False
                                constraint_violations.append(f"Min SOC violation: {np.min(performance['battery_soc']):.3f}")
                            if np.max(performance['battery_soc']) > soc_max:
                                is_feasible = False
                                constraint_violations.append(f"Max SOC violation: {np.max(performance['battery_soc']):.3f}")
                            
                            # Check C-rate constraints
                            max_charge = np.max(np.abs(performance['battery_power'])) / battery_capacity
                            if max_charge > max_charge_rate:
                                is_feasible = False
                                constraint_violations.append(f"C-rate violation: {max_charge:.2f}C")
                        
                        # Check TLPS constraint
                        if metrics['tlps'] > tlps_max:
                            is_feasible = False
                            constraint_violations.append(f"TLPS violation: {metrics['tlps']:.2f}%")
                        
                        # Check economic feasibility constraint
                        if constraints.get('min_annual_profit', False):
                            annual_savings = metrics['annual_savings']
                            annual_maintenance = metrics['annual_maintenance']
                            if annual_savings <= annual_maintenance:
                                is_feasible = False
                                constraint_violations.append(f"Economic infeasibility: Annual savings (${annual_savings:,.2f}) ≤ Maintenance cost (${annual_maintenance:,.2f})")
                        
                        # Get battery metrics directly from performance data
                        battery_charge = performance.get('total_charged_energy', 0.0)
                        battery_discharge = performance.get('total_discharged_energy', 0.0)
                        
                        # Add battery metrics to the metrics dictionary
                        metrics['annual_battery_charge'] = battery_charge
                        metrics['annual_battery_discharge'] = battery_discharge
                        
                        # Calculate net annual profit
                        net_annual_profit = metrics['annual_savings'] - metrics['annual_maintenance']
                        
                        # Store solution data
                        solution_data = {
                            'city': city,
                            'scenario': scenario,
                            'schedule_start': schedule_start,
                            'schedule_end': schedule_end,
                            'photoperiod': photoperiod,
                            'optimal_pv_area [m²]': pv_area,
                            'optimal_battery_capacity [kWh]': battery_capacity,
                            'capital_cost [$]': metrics['capital_cost'],
                            'annual_savings [$/year]': metrics['annual_savings'],
                            'annual_maintenance [$/year]': metrics['annual_maintenance'],
                            'net_annual_profit [$/year]': net_annual_profit,
                            'payback_period [years]': metrics['payback_period'],
                            'lcoe [$/kWh]': metrics['lcoe'],
                            'grid_cost [$/year]': metrics['grid_cost'],
                            'pv_depreciation [$/year]': metrics['pv_depreciation'],
                            'battery_depreciation [$/year]': metrics['battery_depreciation'],
                            'annual_pv_generation [kWh/year]': metrics['annual_pv_generation'],
                            'annual_pv_used [kWh/year]': pv_used,
                            'annual_grid_import [kWh/year]': metrics['annual_grid_import'],
                            'annual_grid_export [kWh/year]': metrics['annual_grid_export'],
                            'annual_battery_charge [kWh/year]': battery_charge,
                            'annual_battery_discharge [kWh/year]': battery_discharge,
                            'tlps [%]': metrics['tlps'],
                            'tlps_max [%]': tlps_max,
                            'is_feasible': is_feasible,
                            'is_optimal': best_solution is not None and np.array_equal(x, best_solution),
                            'constraint_violations': '; '.join(constraint_violations) if constraint_violations else 'None'
                        }
                        
                        # Save to local results file
                        output_dir = Path("results")
                        output_dir.mkdir(exist_ok=True)
                        output_file = output_dir / f"enumeration_results_{city}_{scenario}_start{schedule_start}_step{pv_area_step}_{battery_step}_max{pv_area_range[1]}_{battery_range[1]}.csv"
                        
                        # Append to local results file
                        if not output_file.exists():
                            pd.DataFrame([solution_data]).to_csv(output_file, index=False)
                        else:
                            pd.DataFrame([solution_data]).to_csv(output_file, mode='a', header=False, index=False)
                        
                        # Update the global results file using append mode
                        global_results_file = Path(f"all_optimization_results_step{pv_area_step}_{battery_step}_max{pv_area_range[1]}_{battery_range[1]}.csv")
                        
                        # If file doesn't exist, create it with headers
                        if not global_results_file.exists():
                            pd.DataFrame([solution_data]).to_csv(global_results_file, index=False)
                        else:
                            # Append without headers
                            pd.DataFrame([solution_data]).to_csv(global_results_file, mode='a', header=False, index=False)
                        
                        # Clear memory after saving
                        del solution_data
                        
                        # Update best solution if feasible
                        if is_feasible:
                            feasible_configs += 1
                            objective = metrics['lcoe']
                            if best_solution is None or objective < best_objective:
                                best_solution = x.copy()
                                best_objective = objective
                                best_metrics = metrics.copy()
                                best_performance = performance.copy()
                                
                                # Log new best solution details
                                logger.debug(f"\nNew best solution found:")
                                logger.debug(f"PV Area: {x[0]:.1f} m², Battery: {x[1]:.1f} kWh")
                                logger.debug(f"LCOE: ${objective:.4f}/kWh, TLPS: {metrics['tlps']:.1f}%")
                                if battery_capacity > 0:
                                    logger.debug(f"Battery metrics:")
                                    logger.debug(f"  - SOC range: {np.min(performance['battery_soc']):.2f}-{np.max(performance['battery_soc']):.2f}")
                                    logger.debug(f"  - Max C-rate: {max_charge:.2f}C")
                                    logger.debug(f"  - Cycles: {performance['battery_cycles']:.1f}")
                            
                            # Clear memory for best solution copies if not needed
                            #if best_solution is not None and not np.array_equal(x, best_solution):
                            #    del metrics
                            #    del performance
                        
                        # Update progress bar with current status
                        pbar.set_postfix({
                            'PV': f'{pv_area:.1f}/{pv_area_range[1]:.1f}m²',
                            'Battery': f'{battery_capacity:.1f}/{battery_range[1]:.1f}kWh',
                            'Best LCOE': f'${best_objective:.4f}/kWh' if best_solution is not None else 'None',
                            'Best PV': f'{best_solution[0]:.1f}m²' if best_solution is not None else 'None',
                            'Best Battery': f'{best_solution[1]:.1f}kWh' if best_solution is not None else 'None',
                            'Feasible': f'{feasible_configs}/{pbar.n+1}',
                            'TLPS': f"{metrics['tlps']:.1f}%"
                        })
                        pbar.update(1)
            
            # Save all solutions to CSV
            solutions_df = pd.DataFrame(all_solutions)
            
            # Use 'results' directory instead of 'optimization_results'
            output_dir = Path("results")
            output_dir.mkdir(exist_ok=True)
            
            output_file = output_dir / f"enumeration_results_{city}_{scenario}_start{schedule_start}.csv"
            solutions_df.to_csv(output_file, index=False)
            logger.info(f"Saved all enumeration results to {output_file}")
            
            if best_solution is None:
                logger.warning("No feasible solution found!")
                return None
            
            # Add feasibility information to metrics
            best_metrics['is_feasible'] = True  # Since this is the best solution, it must be feasible
            best_metrics['is_optimal'] = True
            best_metrics['constraint_violations'] = 'None'
            best_metrics['tlps_max'] = tlps_max
            
            # Add schedule information to metrics
            best_metrics['schedule_start'] = schedule_start
            best_metrics['schedule_end'] = schedule_end
            best_metrics['photoperiod'] = photoperiod
            
            # Store scenario information
            result = {
                'x': best_solution,
                'metrics': best_metrics,
                'performance': best_performance,
                'scenarios': {
                    'schedule_start': schedule_start,
                    'schedule_end': schedule_end,
                    'photoperiod': photoperiod,
                    'tlps_max': tlps_max
                }
            }
            
            logger.info(f"Optimization complete. Evaluated {total_configs} configurations, "
                       f"found {feasible_configs} feasible solutions.")
            logger.info(f"Best solution: PV Area = {best_solution[0]:.1f} m², "
                       f"Battery Capacity = {best_solution[1]:.1f} kWh")
            
            return result
            
        except Exception as e:
            logger.error(f"Error in optimization: {str(e)}")
            raise
    
    def _save_hourly_data(self,
                        config_type: str,
                        scenario: str,
                        schedule_name: str,
                        x: np.ndarray,
                        metrics: Dict,
                        performance: Dict,
                        weather_data: pd.DataFrame,
                        load_profile: np.ndarray,
                        results_dir: Path) -> None:
        """Save detailed hourly data for a configuration"""
        try:
            # Use timestamps from weather data
            if 'time' in weather_data.columns:
                times = weather_data['time']
            else:
                # Fallback to creating timestamps
                times = pd.date_range(start='2024-01-01', periods=len(load_profile), freq='H')
            
            # Calculate electricity prices for each hour
            prices = np.zeros(len(load_profile))
            for t in range(len(load_profile)):
                hour = pd.to_datetime(times[t]).hour
                if hour in self.energy_system.peak_hours:
                    prices[t] = self.energy_system.grid_prices['peak']
                elif hour in self.energy_system.valley_hours:
                    prices[t] = self.energy_system.grid_prices['valley']
                else:
                    prices[t] = self.energy_system.grid_prices['normal']
            
            # Create DataFrame with all hourly data
            hourly_data = pd.DataFrame({
                'timestamp': times,
                'hour': pd.to_datetime(times).hour,
                'load_profile_kWh': load_profile,
                'pv_generation_kWh': performance.get('pv_power', np.zeros_like(load_profile)),
                'battery_soc': performance.get('battery_soc', np.zeros(len(load_profile) + 1))[:-1],
                'battery_power_kWh': performance.get('battery_power', np.zeros_like(load_profile)),
                'battery_charging_kWh': np.maximum(0, performance.get('battery_power', np.zeros_like(load_profile))),
                'battery_discharging_kWh': np.maximum(0, -performance.get('battery_power', np.zeros_like(load_profile))),
                'grid_import_kWh': performance.get('grid_import', np.zeros_like(load_profile)),
                'electricity_price_$/kWh': prices,
                'direct_radiation_W/m2': weather_data['direct_radiation'],
                'diffuse_radiation_W/m2': weather_data['diffuse_radiation'],
                'shortwave_radiation_W/m2': weather_data['shortwave_radiation'],
                'temperature_C': weather_data['temperature_2m']
            })
            
            # Add configuration info
            hourly_data['pv_area_m2'] = x[0]
            hourly_data['battery_capacity_kWh'] = x[1]
            hourly_data['scenario'] = scenario
            hourly_data['configuration'] = config_type
            
            # Save to CSV
            output_file = Path(results_dir) / f"{schedule_name}_{scenario}_{config_type}_hourly_data.csv"
            hourly_data.to_csv(output_file, index=False)
            logger.info(f"Saved hourly data to {output_file}")
            
        except Exception as e:
            logger.error(f"Error saving hourly data: {str(e)}")
            logger.error(traceback.format_exc())
    
    def _optimize(self, 
                 load_profile: np.ndarray,
                 weather_data: pd.DataFrame,
                 constraints: Dict,
                 city: str = None,
                 scenario: str = None,
                 pv_area_range: tuple = None,
                 battery_range: tuple = None,
                 pv_area_step: float = None,
                 battery_step: float = None) -> Dict:
        """
        Run the optimization using enumeration
        """
        # Use class defaults if not specified
        pv_area_range = pv_area_range or self.pv_area_range
        battery_range = battery_range or self.battery_range
        pv_area_step = pv_area_step or self.pv_area_step
        battery_step = battery_step or self.battery_step
        
        try:
            # Prepare problem data
            problem_data = {
                'energy_system': self.energy_system,
                'weather_data': weather_data,
                'load_profile': load_profile,
                'constraints': constraints,
                'city': city if city and city != 'unknown' else 'default_city',
                'scenario': scenario
            }
            
            # Run enumeration optimization with specified ranges
            res = self._optimize_enumeration(
                problem_data,
                pv_area_range=pv_area_range,
                battery_range=battery_range,
                pv_area_step=pv_area_step,
                battery_step=battery_step
            )
            
            if res is None:
                raise ValueError(f"Optimization failed to complete for {scenario} scenario")
            
            optimal_solution = res['x']
            logger.info(f"Found optimal solution: PV={optimal_solution[0]:.1f}m², Battery={optimal_solution[1]:.1f}kWh")
            
            # Calculate final metrics for optimal solution
            metrics = res['metrics']
            logger.debug("Metrics calculated: %s", list(metrics.keys()))
            
            # Simulate performance for optimal solution
            performance = res['performance']
            logger.debug("Performance data keys: %s", list(performance.keys()))
            
            # Ensure pv_power exists in performance data
            if 'pv_power' not in performance:
                logger.warning("pv_power missing from performance data, recalculating...")
                pv_power = self.energy_system.pv.calculate_pv_output(
                    weather_data, optimal_solution[0], use_gpu=False
                )
                performance['pv_power'] = pv_power
                logger.info("Recalculated pv_power")
            
            # Calculate PV utilization
            total_pv = metrics['annual_pv_generation']
            total_load = np.sum(load_profile)
            pv_used = min(total_pv, total_load - metrics['annual_grid_import'])
            pv_wasted = max(0, total_pv - pv_used)
            
            # Create result dictionary
            result = {
                'success': True,
                'scenario': scenario,
                'optimal_pv': optimal_solution[0],
                'optimal_battery': optimal_solution[1],
                'metrics': metrics,
                'performance': performance,
                'ranges': {
                    'pv_area_range': pv_area_range,
                    'battery_range': battery_range
                }
            }
            
            return result
            
        except Exception as e:
            logger.error(f"Error in _optimize: {str(e)}")
            logger.error(traceback.format_exc())
            raise
        
    def optimize_configuration(self, 
                             load_profile: np.ndarray,
                             weather_data: pd.DataFrame,
                             constraints: Dict = None,
                             scenario: str = None,
                             city: str = None,
                             pv_area_range: tuple = None,
                             battery_range: tuple = None,
                             pv_area_step: float = None,
                             battery_step: float = None) -> Dict:
        """
        Optimize system configuration for given load profile and weather data
        """
        try:
            if constraints is None:
                constraints = {}
            
            # Create a copy of constraints to avoid modifying the original
            scenario_constraints = constraints.copy() if constraints else {}
            
            # Set default constraints
            scenario_constraints.setdefault('soc_min', 0.1)
            scenario_constraints.setdefault('soc_max', 0.9)
            
            # Validate battery constraints
            if battery_range is not None:
                if battery_range[0] < 0 or battery_range[1] < battery_range[0]:
                    raise ValueError(f"Invalid battery range: {battery_range}")
                logger.info(f"Using battery range: {battery_range[0]:.1f}-{battery_range[1]:.1f} kWh")
            
            if battery_step is not None:
                if battery_step <= 0:
                    raise ValueError(f"Invalid battery step: {battery_step}")
                logger.info(f"Using battery step: {battery_step:.1f} kWh")
            
            # Run optimization with specified ranges
            result = self._optimize(
                load_profile=load_profile,
                weather_data=weather_data,
                constraints=scenario_constraints,
                city=city,
                scenario=scenario,
                pv_area_range=pv_area_range,
                battery_range=battery_range,
                pv_area_step=pv_area_step,
                battery_step=battery_step
            )
            
            if result:
                logger.info(f"Optimization completed for city: {city}, scenario: {scenario}")
            else:
                logger.error(f"Optimization failed for city: {city}, scenario: {scenario}")
            
            # Ensure scenario is included in the result
            result['scenario'] = scenario
            return result
            
        except Exception as e:
            logger.error(f"Optimization failed for {scenario} scenario: {str(e)}")
            return {
                'scenario': scenario,
                'success': False,
                'error': str(e)
            }

    def optimize_both_scenarios(self, 
                              load_profile: np.ndarray,
                              weather_data: pd.DataFrame,
                              base_constraints: Dict = None,
                              city: str = None,
                               scenarios: List[Tuple[str, Dict]] = None
                               ) -> Dict:
        """
        Run optimization for specified scenarios
        """
        results = {}
        scenarios = scenarios or []
        
        # Create progress table header with exact same metrics as in CSV
        headers = [
            "Scenario",
            "PV Area [m²]",
            "Battery [kWh]",
            "LCOE [$/kWh]",
            "TLPS [%]",
            "Capital Cost [$]",
            "Annual Savings [$/yr]",
            "Annual Maintenance [$/yr]",
            "Net Annual Profit [$/yr]",
            "Grid Cost [$/yr]",
            "PV Depreciation [$/yr]",
            "Battery Depreciation [$/yr]"
        ]
        
        # Process each scenario
        for scenario, scenario_constraints in scenarios:
            logger.info(f"Starting optimization for city: {city}, scenario: {scenario}")
            
            # Combine base constraints with scenario constraints
            combined_constraints = base_constraints.copy() if base_constraints else {}
            combined_constraints.update(scenario_constraints)
            
            # Run optimization for this scenario
            result = self.optimize_configuration(
                load_profile=load_profile,
                weather_data=weather_data,
                constraints=combined_constraints,
                scenario=scenario,
                city=city
            )
            
            # Store result
            results[scenario] = result
            
            # Display result if successful
            if result['success']:
                metrics = result['metrics']
                
                # Calculate net annual profit
                net_annual_profit = metrics['annual_savings'] - metrics['annual_maintenance']
                
                # Create row with exact same metrics as stored in CSV
                row = [
                    scenario.capitalize(),
                    f"{result['optimal_pv']:.1f}",
                    f"{result['optimal_battery']:.1f}",
                    f"${metrics['lcoe']:.3f}",
                    f"{metrics['tlps']:.1f}",
                    f"${metrics['capital_cost']:,.0f}",
                    f"${metrics['annual_savings']:,.0f}",
                    f"${metrics['annual_maintenance']:,.0f}",
                    f"${net_annual_profit:,.0f}",
                    f"${metrics['grid_cost']:,.0f}",  # Using grid_cost from metrics
                    f"${metrics['pv_depreciation']:,.0f}",
                    f"${metrics['battery_depreciation']:,.0f}"
                ]
                
                # Display results table with fixed column widths
                print("\nOptimization Results:")
                print(tabulate([row], headers=headers, tablefmt="grid", numalign="right"))
                
                # Display energy metrics
                print("\nEnergy Metrics:")
                energy_headers = [
                    "PV Generation [kWh/yr]",
                    "PV Used [kWh/yr]",
                    "Grid Import [kWh/yr]",
                    "Grid Export [kWh/yr]",
                    "Battery Charge [kWh/yr]",
                    "Battery Discharge [kWh/yr]"
                ]
                energy_row = [
                    f"{metrics['annual_pv_generation']:,.0f}",
                    f"{metrics['annual_pv_used']:,.0f}",
                    f"{metrics['annual_grid_import']:,.0f}",
                    f"{metrics['annual_grid_export']:,.0f}",
                    f"{metrics['annual_battery_charge']:,.0f}",
                    f"{metrics['annual_battery_discharge']:,.0f}"
                ]
                print(tabulate([energy_row], headers=energy_headers, tablefmt="grid", numalign="right"))
            else:
                logger.error(f"Optimization failed for {scenario} scenario: {result.get('error', 'Unknown error')}")
        
        return results
