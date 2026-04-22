"""
OpenCROPS Agent Entry Point
===========================

Single entry point for AI agents to interact with OpenCROPS.

Usage:
    from src.agent import agent
    result = agent.run("minimize energy for lettuce farm in summer")
    print(result.data)
"""

import sys
from pathlib import Path
from typing import Optional, Dict, Any, Union

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from .result import AgentResult, ResultStatus
from .intent import parse_intent, IntentParser, ParsedIntent
from .evaluator import agent_evaluate
from .errors import ERROR_CATALOG


def run(intent: str, **kwargs) -> AgentResult:
    """
    Single entry point for agent operations.

    Parses natural language intent and routes to appropriate action.

    Args:
        intent: Natural language intent string
               Examples:
               - "minimize energy for shanghai"
               - "evaluate pv=100, battery=50 for beijing"
               - "optimize for lettuce farm in summer"
        **kwargs: Additional parameters passed to underlying functions

    Returns:
        AgentResult with structured data and _next_actions

    Example:
        >>> result = run("minimize energy for shanghai")
        >>> print(result.data["metrics"]["tlps_percent"])
        >>> print(result._next_actions)
    """
    # Parse intent
    parser = IntentParser()
    parsed = parser.parse(intent)

    # Route to appropriate action
    action = parsed.action or "evaluate"

    if action == "evaluate":
        return _handle_evaluate(parsed, **kwargs)
    elif action == "optimize":
        return _handle_optimize(parsed, **kwargs)
    elif action == "calibrate":
        return _handle_calibrate(parsed, **kwargs)
    elif action == "analyze":
        return _handle_analyze(parsed, **kwargs)
    elif action == "compare":
        return _handle_compare(parsed, **kwargs)
    elif action == "build_idf":
        return _handle_build_idf(parsed, **kwargs)
    elif action == "run_simulation":
        return _handle_simulation(parsed, **kwargs)
    else:
        from .result import Error
        return AgentResult(
            status=ResultStatus.FAILED.value,
            errors=[
                Error(
                    code="E_UNKNOWN_ACTION",
                    message=f"Unknown action: {action}",
                    _fix={
                        "action": "use_supported_action",
                        "supported_actions": ["evaluate", "optimize", "calibrate", "analyze", "compare"],
                    }
                )
            ],
        )


def _handle_evaluate(parsed: ParsedIntent, **kwargs) -> AgentResult:
    """Handle evaluate action"""
    # Extract parameters
    pv_area = parsed.pv_area or kwargs.get("pv_area", 100.0)
    battery_capacity = parsed.battery_capacity or kwargs.get("battery_capacity", 50.0)
    city = parsed.city or kwargs.get("city", "shanghai")
    start_hour = parsed.start_hour or kwargs.get("start_hour", 8)

    # Run evaluation
    return agent_evaluate(
        pv_area=pv_area,
        battery_capacity=battery_capacity,
        city=city,
        start_hour=start_hour,
        **kwargs
    )


def _handle_optimize(parsed: ParsedIntent, **kwargs) -> AgentResult:
    """Handle optimize action"""
    from .result import Warning

    city = parsed.city or kwargs.get("city", None)

    if city is None:
        from .result import Error
        return AgentResult(
            status=ResultStatus.FAILED.value,
            errors=[
                Error(
                    code="E003",
                    message="City is required for optimization",
                    _fix={
                        "action": "specify_city",
                        "example": 'run("optimize for shanghai")',
                    }
                )
            ],
        )

    # Run optimization
    try:
        from main import process_city
        from pathlib import Path

        base_dir = kwargs.get("base_dir", Path("test_case"))
        process_city(city, base_dir)

        return AgentResult(
            status=ResultStatus.SUCCESS.value,
            data={
                "city": city,
                "status": "optimization_complete",
                "message": f"Optimization for {city} completed successfully",
            },
            _next_actions=[
                f"evaluate optimized configuration for {city}",
                "compare different photoperiod strategies",
            ],
            warnings=[
                Warning(
                    code="W001",
                    message=f"Optimization complete for {city}",
                    severity="low"
                )
            ],
            _metadata={"city": city}
        )

    except Exception as e:
        from .result import Error
        return AgentResult(
            status=ResultStatus.FAILED.value,
            errors=[
                Error(
                    code="E_OPTIMIZE_FAILED",
                    message=f"Optimization failed: {str(e)}",
                    _fix={
                        "action": "retry_or_manual",
                        "command": f"vfed optimize --cities {city}",
                    }
                )
            ],
        )


def _handle_calibrate(parsed: ParsedIntent, **kwargs) -> AgentResult:
    """Handle calibrate action"""
    from .result import Error

    city = parsed.city or kwargs.get("city", None)

    if city is None:
        return AgentResult(
            status=ResultStatus.FAILED.value,
            errors=[
                Error(
                    code="E003",
                    message="City is required for calibration",
                    _fix={"action": "specify_city", "example": 'run("calibrate for shanghai")'}
                )
            ],
        )

    try:
        from src.calibrator import StepSizeCalibrator
        import json
        from pathlib import Path

        pv_max = kwargs.get("pv_max", 500.0)
        battery_max = kwargs.get("battery_max", 500.0)

        calibrator = StepSizeCalibrator(
            reference_city=city,
            pv_max=pv_max,
            battery_max=battery_max,
            step_sizes=[0.5, 1.0, 5.0, 10.0, 15.0, 20.0, 30, 50],
        )

        optimal_steps = calibrator.run()

        output_dir = Path("calibration_results")
        output_dir.mkdir(parents=True, exist_ok=True)
        output_file = output_dir / f"optimal_steps_{city}.json"

        with open(output_file, "w") as f:
            json.dump(optimal_steps, f, indent=4)

        return AgentResult(
            status=ResultStatus.SUCCESS.value,
            data={
                "city": city,
                "optimal_steps": optimal_steps,
                "output_file": str(output_file),
            },
            _metadata={"city": city, "pv_max": pv_max, "battery_max": battery_max}
        )

    except Exception as e:
        return AgentResult(
            status=ResultStatus.FAILED.value,
            errors=[
                Error(
                    code="E_CALIBRATE_FAILED",
                    message=f"Calibration failed: {str(e)}",
                )
            ],
        )


def _handle_analyze(parsed: ParsedIntent, **kwargs) -> AgentResult:
    """Handle analyze action"""
    from .result import Error

    results_file = kwargs.get("results_file", None)

    if results_file is None:
        return AgentResult(
            status=ResultStatus.FAILED.value,
            errors=[
                Error(
                    code="E004",
                    message="Results file is required for analysis",
                    _fix={
                        "action": "specify_results_file",
                        "note": "Run optimize first to generate results"
                    }
                )
            ],
        )

    try:
        from pathlib import Path
        from analyze_results import analyze_city_climate_energy

        output_dir = kwargs.get("output_dir", Path("results"))
        output_dir.mkdir(parents=True, exist_ok=True)

        analyze_city_climate_energy(output_dir=output_dir)

        return AgentResult(
            status=ResultStatus.SUCCESS.value,
            data={
                "status": "analysis_complete",
                "output_dir": str(output_dir),
            },
            _next_actions=["visualize_results", "generate_report"]
        )

    except Exception as e:
        from .result import Error
        return AgentResult(
            status=ResultStatus.FAILED.value,
            errors=[
                Error(code="E_ANALYZE_FAILED", message=f"Analysis failed: {str(e)}")
            ],
        )


def _handle_compare(parsed: ParsedIntent, **kwargs) -> AgentResult:
    """Handle compare action - placeholder for multi-config comparison"""
    from .result import Warning

    pv_area = parsed.pv_area or kwargs.get("pv_area", 100.0)
    battery_capacity = parsed.battery_capacity or kwargs.get("battery_capacity", 50.0)
    city = parsed.city or kwargs.get("city", "shanghai")
    start_hour1 = kwargs.get("start_hour1", 6)
    start_hour2 = kwargs.get("start_hour2", 18)

    # Run mechanism comparison
    try:
        from main import evaluate_mechanism_configs
        from pathlib import Path

        base_dir = kwargs.get("base_dir", Path("test_case"))

        evaluate_mechanism_configs(
            pv_area=pv_area,
            battery_capacity=battery_capacity,
            start_hour1=start_hour1,
            start_hour2=start_hour2,
            city_key=city,
            base_dir=base_dir,
        )

        return AgentResult(
            status=ResultStatus.SUCCESS.value,
            data={
                "city": city,
                "pv_area": pv_area,
                "battery_capacity": battery_capacity,
                "photoperiod1": f"{start_hour1:02d}:00",
                "photoperiod2": f"{start_hour2:02d}:00",
                "comparison_complete": True,
            },
            _next_actions=[
                "analyze comparison results",
                "select optimal photoperiod strategy"
            ],
            _metadata={
                "city": city,
                "start_hour1": start_hour1,
                "start_hour2": start_hour2,
            }
        )

    except Exception as e:
        from .result import Error
        return AgentResult(
            status=ResultStatus.FAILED.value,
            errors=[
                Error(code="E_COMPARE_FAILED", message=f"Comparison failed: {str(e)}")
            ],
        )


def _handle_build_idf(parsed: ParsedIntent, **kwargs) -> AgentResult:
    """Handle build_idf action"""
    from src.idf_builder import IDFBuilder
    from .result import Warning

    name = kwargs.get("name", "PFAL")
    output_path = kwargs.get("output", None)
    floor_area = parsed.pv_area or kwargs.get("floor_area", 100.0)
    num_zones = kwargs.get("num_zones", 4)
    lighting_power = kwargs.get("lighting_power", 350.0)

    if output_path is None:
        from .result import Error
        return AgentResult(
            status=ResultStatus.FAILED.value,
            errors=[
                Error(
                    code="E_NO_OUTPUT_PATH",
                    message="Output path is required for IDF build",
                    _fix={"action": "specify_output_path", "example": 'run("build idf for lettuce", output="mybuilding.idf")'}
                )
            ],
        )

    try:
        from pathlib import Path

        output = Path(output_path)

        idf = IDFBuilder()
        idf.set_building(name, floor_area=floor_area, num_zones=num_zones)

        for i in range(num_zones):
            idf.add_zone(
                name=f"Zone_{i:02d}",
                x=0, y=0, z=i * 2.5,
                multiplier=1,
                ceiling_height=2.5,
                floor_area=floor_area / num_zones
            )

        for i in range(num_zones):
            idf.add_lights(
                zone_idx=i,
                power_density=lighting_power,
                zone_name=f"Zone_{i:02d}",
                schedule_name="LightSchedule"
            )

        for i in range(num_zones):
            idf.add_electric_equipment(
                zone_idx=i,
                design_level=500.0,
                zone_name=f"Zone_{i:02d}",
                schedule_name="EquipSchedule"
            )

        for i in range(num_zones):
            idf.add_ventilation(
                zone_idx=i,
                air_changes_per_hour=0.3,
                zone_name=f"Zone_{i:02d}",
                schedule_name="VentilationSchedule"
            )

        for i in range(num_zones):
            idf.add_thermostat(
                zone_idx=i,
                heating_setpoint=20.0,
                cooling_setpoint=25.0,
                zone_name=f"Zone_{i:02d}"
            )

        output.parent.mkdir(parents=True, exist_ok=True)
        idf_content = idf.build()
        output.write_text(idf_content, encoding='utf-8')

        return AgentResult(
            status=ResultStatus.SUCCESS.value,
            data={
                "idf_file": str(output),
                "building_name": name,
                "floor_area_m2": floor_area,
                "num_zones": num_zones,
                "lighting_power_wm2": lighting_power,
            },
            _next_actions=[f"run simulation with {output.name}", "extract loads for optimization"],
            _metadata={"zone_config": "stacked_vertically"}
        )

    except Exception as e:
        from .result import Error
        return AgentResult(
            status=ResultStatus.FAILED.value,
            errors=[
                Error(code="E_IDF_BUILD_FAILED", message=f"IDF build failed: {str(e)}")
            ],
        )


def _handle_simulation(parsed: ParsedIntent, **kwargs) -> AgentResult:
    """Handle run_simulation action - placeholder"""
    from .result import Warning, Error

    idf_file = kwargs.get("idf", None)
    weather_file = kwargs.get("weather", None)

    if idf_file is None or weather_file is None:
        return AgentResult(
            status=ResultStatus.FAILED.value,
            errors=[
                Error(
                    code="E_MISSING_INPUTS",
                    message="IDF file and weather file are required for simulation",
                    _fix={
                        "action": "provide_inputs",
                        "example_idf": "build_idf(output='building.idf')",
                        "example_weather": "Use weather from vfed optimize"
                    }
                )
            ],
        )

    return AgentResult(
        status=ResultStatus.PARTIAL.value,
        data={
            "idf_file": idf_file,
            "weather_file": weather_file,
            "status": "simulation_not_implemented_in_agent",
        },
        _next_actions=[
            "use vfed idf run command directly",
            "consider using EnergyPlus CLI"
        ],
        warnings=[
            Warning(
                code="W_SIMULATION_LIMITED",
                message="Direct simulation not yet implemented in agent interface",
                severity="low"
            )
        ]
    )


# Module-level convenience function
def agent_run(intent: str, **kwargs) -> AgentResult:
    """Alias for run() - convenient for direct imports"""
    return run(intent, **kwargs)