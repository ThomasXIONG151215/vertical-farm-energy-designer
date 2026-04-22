"""
Error Catalog & _fix Generator
==============================

Standardized error codes and fix suggestions for agent self-healing.

Error Format:
{
    "code": "E001",
    "message": "Human-readable error message",
    "parameter": "param_name",  # Optional: which parameter caused error
    "provided_value": 15.5,     # Optional: what value was provided
    "valid_range": [0.5, 10.0], # Optional: what values are valid
    "_fix": {
        "action": "action_name",
        "command": "suggested command",
        "example_configs": [...],  # Optional: example configurations
    }
}
"""

from typing import Dict, Any, Optional, List
from .result import Error


# Error Catalog - all defined errors
ERROR_CATALOG: Dict[str, Dict[str, Any]] = {
    # File/Dependency Errors
    "E001": {
        "name": "WEATHER_FILE_NOT_FOUND",
        "message": "Weather data not found for city '{city}'. Run 'vfed optimize' first to generate weather files.",
        "_fix": {
            "action": "run_optimize_first",
            "command": "vfed optimize --cities {city}",
            "auto_retry": True,
        }
    },
    "E002": {
        "name": "SCHEDULE_FILE_NOT_FOUND",
        "message": "Schedule file not found for start hour {start_hour} in {city}.",
        "_fix": {
            "action": "generate_schedule",
            "command": "vfed optimize --cities {city}",
            "note": "Weather data and schedules are generated together by optimize",
        }
    },
    "E003": {
        "name": "CITY_NOT_FOUND",
        "message": "Unknown city '{city}'. Available cities: {available_cities}",
        "_fix": {
            "action": "use_valid_city",
            "example_cities": ["shanghai", "beijing", "hangzhou", "shenzhen"],
            "add_city_command": "vfed city add --name {{name}} --lat {{lat}} --lon {{lon}}",
        }
    },
    "E004": {
        "name": "RESULTS_FILE_NOT_FOUND",
        "message": "Results file not found: {path}",
        "_fix": {
            "action": "run_optimize_first",
            "command": "vfed optimize --cities {city}",
        }
    },

    # Parameter Validation Errors
    "E101": {
        "name": "INVALID_PV_AREA",
        "message": "PV area {value} is out of valid range [0, {max}] m²",
        "_fix": {
            "action": "adjust_pv_area",
            "suggested_range": [0, 500],
            "example_configs": [
                {"pv_area": 100, "battery_capacity": 50},
                {"pv_area": 200, "battery_capacity": 100},
            ]
        }
    },
    "E102": {
        "name": "INVALID_BATTERY_CAPACITY",
        "message": "Battery capacity {value} is out of valid range [0, {max}] kWh",
        "_fix": {
            "action": "adjust_battery_capacity",
            "suggested_range": [0, 200],
            "example_configs": [
                {"pv_area": 100, "battery_capacity": 50},
                {"pv_area": 100, "battery_capacity": 100},
            ]
        }
    },
    "E103": {
        "name": "INVALID_START_HOUR",
        "message": "Start hour {value} must be between 0 and 23",
        "_fix": {
            "action": "use_valid_hour",
            "valid_hours": list(range(0, 24)),
        }
    },
    "E104": {
        "name": "INVALID_HOUR_RANGE",
        "message": "Invalid hour range: start={start_hour}, end={end_hour}",
        "_fix": {
            "action": "use_valid_hour_range",
            "note": "Start hour should be the beginning of photoperiod (e.g., 6 for 06:00-22:00)",
        }
    },

    # Constraint Violation Errors
    "E201": {
        "name": "TLPS_CONSTRAINT_VIOLATED",
        "message": "Time Loss of Power Supply (TLPS) = {value}% exceeds maximum {max}%",
        "_fix": {
            "action": "increase_pv_or_battery",
            "suggestions": [
                "Increase PV area by 20-50%",
                "Increase battery capacity by 30-50%",
                "Reduce load during peak hours",
            ]
        }
    },
    "E202": {
        "name": "BATTERY_SOC_VIOLATED",
        "message": "Battery SOC violation: min={min_soc}, max={max_soc}, allowed=[{soc_min}, {soc_max}]",
        "_fix": {
            "action": "adjust_battery_soc_limits",
            "suggested_soc_range": [0.1, 0.9],
        }
    },
    "E203": {
        "name": "ECONOMIC_INFEASIBLE",
        "message": "Configuration is economically infeasible: annual savings (${savings}) <= maintenance cost (${maintenance})",
        "_fix": {
            "action": "increase_pv_area",
            "suggestions": [
                "Increase PV area to reduce grid import",
                "Consider locations with better solar resources",
            ]
        }
    },

    # Simulation Errors
    "E301": {
        "name": "SIMULATION_FAILED",
        "message": "EnergyPlus simulation failed: {details}",
        "_fix": {
            "action": "check_idf_file",
            "suggestions": [
                "Validate IDF file syntax",
                "Check weather file format",
                "Ensure all referenced objects exist",
            ]
        }
    },
    "E302": {
        "name": "IDF_BUILD_FAILED",
        "message": "Failed to build IDF file: {details}",
        "_fix": {
            "action": "check_idf_parameters",
            "note": "Ensure floor_area > 0, zones >= 1, lighting_power > 0",
        }
    },

    # System Errors
    "E401": {
        "name": "ENERGY_PLUS_NOT_FOUND",
        "message": "EnergyPlus executable not found at {path}",
        "_fix": {
            "action": "install_energyplus",
            "path_hint": "C:/EnergyPlusV23-1-0/energyplus.exe",
            "download_url": "https://energyplus.net/downloads",
        }
    },
    "E402": {
        "name": "DEPENDENCY_NOT_INSTALLED",
        "message": "Required dependency '{package}' is not installed",
        "_fix": {
            "action": "install_dependency",
            "command": "pip install {package}",
        }
    },
}

# Warning Catalog
WARNING_CATALOG: Dict[str, Dict[str, Any]] = {
    "W001": {
        "name": "WEATHER_DATA_OLD",
        "message": "Weather data is from {year}, consider updating to current year",
        "severity": "low",
    },
    "W002": {
        "name": "PV_AREA_LARGE",
        "message": "PV area {value} m² is unusually large, may exceed available space",
        "severity": "medium",
    },
    "W003": {
        "name": "BATTERY_CAPACITY_LARGE",
        "message": "Battery capacity {value} kWh is unusually large, consider capacity sizing",
        "severity": "medium",
    },
    "W004": {
        "name": "LOW_CONFIDENCE",
        "message": "Simulation confidence is low ({confidence}), results may be unreliable",
        "severity": "medium",
    },
    "W005": {
        "name": "HIGH_TLPS",
        "message": "TLPS = {value}% is high but within constraints",
        "severity": "low",
    },
}


def get_fix(error_code: str, **kwargs) -> Optional[Dict[str, Any]]:
    """
    Get _fix dictionary for an error code with variable substitution.

    Args:
        error_code: Error code (e.g., "E001")
        **kwargs: Variables to substitute in message/fix templates

    Returns:
        _fix dictionary with substituted values, or None if error_code not found
    """
    if error_code not in ERROR_CATALOG:
        return None

    error = ERROR_CATALOG[error_code]
    fix = error.get("_fix", {}).copy()

    # Substitute placeholders in message
    if "message" in error:
        error["message"] = error["message"].format(**kwargs)

    # Substitute placeholders in fix
    for key, value in fix.items():
        if isinstance(value, str):
            fix[key] = value.format(**kwargs)
        elif isinstance(value, list):
            fix[key] = [
                v.format(**kwargs) if isinstance(v, str) else v
                for v in value
            ]

    return fix


def create_error(
    error_code: str,
    **kwargs
) -> Error:
    """
    Create an Error object from error code with variable substitution.

    Args:
        error_code: Error code (e.g., "E001")
        **kwargs: Variables to substitute in message

    Returns:
        Error object
    """
    if error_code not in ERROR_CATALOG:
        return Error(
            code=error_code,
            message=f"Unknown error: {error_code}",
        )

    error_def = ERROR_CATALOG[error_code]
    fix = get_fix(error_code, **kwargs)

    return Error(
        code=error_code,
        message=error_def["message"].format(**kwargs),
        _fix=fix,
        **{k: v for k, v in kwargs.items()
           if k in ["parameter", "provided_value", "valid_range"]}
    )


def create_warning(
    warning_code: str,
    **kwargs
):
    """Create a Warning object from warning code"""
    from .result import Warning

    if warning_code not in WARNING_CATALOG:
        return Warning(
            code=warning_code,
            message=f"Unknown warning: {warning_code}",
        )

    warning_def = WARNING_CATALOG[warning_code]
    return Warning(
        code=warning_code,
        message=warning_def["message"].format(**kwargs),
        severity=warning_def.get("severity", "low"),
    )