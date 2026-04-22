"""
Agent Evaluator Wrapper
=======================

Agent-friendly wrapper around evaluate_single_config.
Handles dependencies automatically and returns AgentResult.
"""

import sys
from pathlib import Path
from typing import Optional, Dict, Any, List

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
import pandas as pd

from .result import AgentResult, ResultStatus, Warning, Error
from .errors import create_error, create_warning, ERROR_CATALOG
from ..system import EnergySystem
from ...weather.city_coordinates import get_city_coordinates


def _generate_next_actions(
    pv_area: float,
    battery_capacity: float,
    metrics: Dict[str, Any],
) -> List[str]:
    """
    Generate suggested next actions based on evaluation results.

    Args:
        pv_area: Evaluated PV area
        battery_capacity: Evaluated battery capacity
        metrics: Evaluation metrics

    Returns:
        List of suggested next actions
    """
    actions = []

    # TLPS-based suggestions
    tlps = metrics.get("tlps", 0)
    if tlps > 10:
        actions.append("increase_battery_capacity")
        actions.append("increase_pv_area_if_space_available")
    elif tlps > 5:
        actions.append("consider_increasing_battery_by_20pct")

    # Economic suggestions
    lcoe = metrics.get("lcoe", float("inf"))
    if lcoe > 0.5:
        actions.append("optimize_pv_area_to_reduce_lcoe")

    # Grid dependency suggestions
    grid_dep = metrics.get("grid_dependency", 100)
    if grid_dep > 50:
        actions.append("increase_pv_area_to_reduce_grid_dependency")
    elif grid_dep > 25:
        actions.append("consider_battery_expansion_for_higher_self_consumption")

    # Payback suggestions
    payback = metrics.get("payback_period", float("inf"))
    if payback > 10:
        actions.append("evaluate_incentive_options")
        actions.append("consider_pv_efficiency_upgrade")

    # PV utilization suggestions
    pv_util = metrics.get("PV_utilization", 100)
    if pv_util < 50:
        actions.append("optimize_load_schedule_to_match_pv_generation")
        actions.append("consider_load_shifting_strategy")

    return actions


def agent_evaluate(
    pv_area: float,
    battery_capacity: float,
    city: str,
    start_hour: int = 8,
    end_hour: Optional[int] = None,
    goal: Optional[str] = None,
    constraints: Optional[Dict[str, Any]] = None,
    auto_setup: bool = True,
) -> AgentResult:
    """
    Agent-friendly evaluation function.

    Automatically handles:
    - Weather data availability check
    - Schedule file lookup/generation
    - Parameter validation
    - Structured result with _next_actions

    Args:
        pv_area: PV area in m²
        battery_capacity: Battery capacity in kWh
        city: City key (e.g., "shanghai", "beijing")
        start_hour: Photoperiod start hour (0-23), default 8
        end_hour: Photoperiod end hour (0-23), if None inferred from start_hour
        goal: Optimization goal (currently unused, reserved for future)
        constraints: Additional constraints (currently unused, reserved)
        auto_setup: If True, auto-run optimize if weather files missing

    Returns:
        AgentResult with evaluation results
    """
    warnings_list: List[Warning] = []
    errors_list: List[Error] = []

    # Step 1: Validate city
    available_cities = list(get_city_coordinates().keys())
    if city not in available_cities:
        err = create_error("E003", city=city, available_cities=", ".join(available_cities[:5]) + "...")
        errors_list.append(err)
        return AgentResult(
            status=ResultStatus.FAILED.value,
            errors=errors_list,
        )

    # Step 2: Validate parameters
    if pv_area < 0 or pv_area > 1000:
        err = create_error(
            "E101",
            value=pv_area,
            max=500,
        )
        errors_list.append(err)

    if battery_capacity < 0 or battery_capacity > 500:
        err = create_error(
            "E102",
            value=battery_capacity,
            max=200,
        )
        errors_list.append(err)

    if not (0 <= start_hour <= 23):
        err = create_error("E103", value=start_hour)
        errors_list.append(err)

    if errors_list:
        return AgentResult(
            status=ResultStatus.FAILED.value,
            errors=errors_list,
        )

    # Step 3: Setup directories and find files
    base_dir = PROJECT_ROOT / "test_case"
    city_dir = base_dir / city

    weather_csv = city_dir / "weather" / f"{city}_2024.csv"
    output_dir = city_dir / "output"
    results_dir = city_dir / "results"

    # Create directories if needed
    for d in [output_dir, results_dir]:
        d.mkdir(parents=True, exist_ok=True)

    # Step 4: Check weather data, auto-setup if needed
    if not weather_csv.exists():
        if auto_setup:
            # Need to run optimize first - return partial with fix
            err = create_error("E001", city=city)
            err._fix = {
                "action": "run_optimize_first",
                "command": f"vfed optimize --cities {city}",
                "auto_retry": True,
                "note": "agent_evaluate will auto-retry after optimize completes",
            }
            errors_list.append(err)

            # Trigger optimize (this would be async in real implementation)
            try:
                from main import process_city
                process_city(city, base_dir)
            except Exception as e:
                errors_list.append(Error(
                    code="E_OPTIMIZE_FAILED",
                    message=f"Auto-setup optimize failed: {str(e)}",
                    _fix={"action": "manual_optimize", "command": f"vfed optimize --cities {city}"}
                ))

            # Recheck weather file
            if not weather_csv.exists():
                return AgentResult(
                    status=ResultStatus.FAILED.value,
                    errors=errors_list,
                    _metadata={"auto_setup_attempted": True}
                )
        else:
            err = create_error("E001", city=city)
            errors_list.append(err)
            return AgentResult(
                status=ResultStatus.FAILED.value,
                errors=errors_list,
            )

    # Step 5: Find schedule file
    if end_hour is None:
        end_hour = (start_hour + 16) % 24  # Default 16h photoperiod

    schedule_pattern = f"annual_energy_schedule_{start_hour:02d}_{end_hour:02d}*.csv"
    schedule_files = list(output_dir.glob(schedule_pattern))

    if not schedule_files:
        # Try any schedule for this start hour
        schedule_pattern = f"annual_energy_schedule_{start_hour:02d}_*.csv"
        schedule_files = list(output_dir.glob(schedule_pattern))

    if not schedule_files:
        err = create_error("E002", city=city, start_hour=start_hour)
        errors_list.append(err)
        return AgentResult(
            status=ResultStatus.FAILED.value,
            errors=errors_list,
        )

    schedule_file = schedule_files[0]

    # Step 6: Load data
    try:
        weather_data = pd.read_csv(weather_csv)
    except Exception as e:
        errors_list.append(Error(
            code="E_DATA_LOAD_FAILED",
            message=f"Failed to load weather data: {str(e)}",
        ))
        return AgentResult(
            status=ResultStatus.FAILED.value,
            errors=errors_list,
        )

    # Step 7: Run evaluation
    try:
        from main import load_schedule

        energy_system = EnergySystem()
        load_profile = load_schedule(schedule_file)
        x = np.array([pv_area, battery_capacity])

        # Simulate performance
        performance = energy_system.simulate_performance(
            x, weather_data, load_profile, is_independent=False
        )

        # Calculate metrics
        metrics = energy_system.calculate_metrics(x, weather_data, load_profile)

        # Calculate additional metrics
        total_pv = metrics["annual_pv_generation"]
        total_load = np.sum(load_profile)
        pv_used = min(total_pv, total_load - metrics["annual_grid_import"])
        pv_util = pv_used / total_pv * 100 if total_pv > 0 else 0
        grid_dep = metrics["annual_grid_import"] / total_load * 100 if total_load > 0 else 100

        metrics["PV_utilization"] = pv_util
        metrics["grid_dependency"] = grid_dep

        # Generate next actions
        next_actions = _generate_next_actions(pv_area, battery_capacity, metrics)

        # Check for warnings
        if pv_area > 300:
            warnings_list.append(create_warning("W002", value=pv_area))

        if battery_capacity > 150:
            warnings_list.append(create_warning("W003", value=battery_capacity))

        if grid_dep > 50:
            warnings_list.append(create_warning("W005", value=grid_dep))

        # Build result data
        result_data = {
            "configuration": {
                "pv_area_m2": pv_area,
                "battery_capacity_kwh": battery_capacity,
                "city": city,
                "photoperiod": f"{start_hour:02d}:00-{end_hour:02d}:00",
            },
            "metrics": {
                "tlps_percent": metrics["tlps"],
                "lcoe_per_kwh": metrics["lcoe"],
                "capital_cost": metrics["capital_cost"],
                "annual_savings": metrics["annual_savings"],
                "payback_period_years": metrics["payback_period"],
                "annual_pv_generation_kwh": metrics["annual_pv_generation"],
                "annual_grid_import_kwh": metrics["annual_grid_import"],
                "pv_utilization_percent": pv_util,
                "grid_dependency_percent": grid_dep,
            },
            "summary": {
                "total_annual_load_kwh": float(np.sum(load_profile)),
                "total_pv_generation_kwh": float(total_pv),
                "self_sufficiency_percent": 100 - grid_dep,
            }
        }

        return AgentResult(
            status=ResultStatus.SUCCESS.value,
            data=result_data,
            _next_actions=next_actions,
            warnings=warnings_list,
            _confidence=0.9 if pv_util > 50 else 0.7,
            _metadata={
                "city": city,
                "schedule_file": str(schedule_file),
                "weather_file": str(weather_csv),
            }
        )

    except Exception as e:
        return AgentResult(
            status=ResultStatus.FAILED.value,
            errors=[
                Error(
                    code="E_EVALUATION_FAILED",
                    message=f"Evaluation failed: {str(e)}",
                    _fix={
                        "action": "check_parameters",
                        "suggestions": [
                            "Verify PV area and battery capacity are valid",
                            "Check weather data quality",
                            "Try with smaller PV area or battery",
                        ]
                    }
                )
            ],
        )