"""
Agent evaluator — design-time evaluation surface.

Preserves the agent-cli contract (structured ``success`` + error-code payload)
used by the original ``vfed/agent/evaluator.py`` while targeting the new
parametric ODE + PVBES design simulator.

Error codes:
    E001  invalid / missing project configuration
    E003  weather acquisition failed
    E101  building simulation failed
    E103  empty / zero load profile
"""

from typing import Dict, Optional

import numpy as np

from ..design.project import DesignProject
from ..design.engine import DesignEngine
from ..design.sweep import sweep_design
from ..weather.weather_bridge import WeatherFetchError

__all__ = ["agent_evaluate", "agent_simulate"]


def agent_simulate(project: DesignProject,
                   cache_dir: Optional[str] = "weather_cache") -> Dict:
    """Run the building simulation for a project. Returns load + weather."""
    engine = DesignEngine(cache_dir=cache_dir)
    try:
        result = engine.run(project)
    except WeatherFetchError as e:
        return {"success": False, "error_code": "E003", "message": str(e)}
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error_code": "E101",
                "message": f"building simulation failed: {e}"}
    load = np.asarray(result["load"], dtype=float)
    if load.sum() <= 0:
        return {"success": False, "error_code": "E103",
                "message": "load profile is empty or zero"}
    return {"success": True, "load": load, "weather": result["weather"],
            "timeseries": result["timeseries"],
            "annual_load_kwh": result["annual_load_kwh"],
            "biomass_kg": result.get("biomass_kg", 0.0),
            "kwh_per_kg": result.get("kwh_per_kg", 0.0),
            "kwh_per_kg_fresh": result.get("kwh_per_kg_fresh", 0.0)}


def agent_evaluate(project_path: str,
                   cache_dir: Optional[str] = "weather_cache") -> Dict:
    """Load project → simulate → sweep (if parameter_ranges are defined).

    Returns ``{"success": True, ...}`` with best design and full enumeration
    table when ranges are present, or a single-point sim result otherwise.
    """
    # E001: configuration
    try:
        project = DesignProject.load(project_path)
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error_code": "E001",
                "message": f"invalid project config: {e}"}

    # Run sweep (handles single-point internally when parameter_ranges is empty).
    try:
        sweep = sweep_design(project, cache_dir=cache_dir or "weather_cache")
    except WeatherFetchError as e:
        return {"success": False, "error_code": "E003", "message": str(e)}
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error_code": "E101",
                "message": f"sweep evaluation failed: {e}"}

    # E103: empty / zero load profile (mirrors agent_simulate).
    best = sweep.get("best") or {}
    if best.get("annual_load_kwh", 0) <= 0:
        return {"success": False, "error_code": "E103",
                "message": "load profile is empty or zero"}

    return {
        "success": True,
        "project": project.name,
        "currency": project.currency,
        "exchange_rate": project.exchange_rate,
        "objective": sweep.get("objective", "lcoe"),
        "dry_matter_fraction": project.growth.dry_matter_fraction,
        "best": best,
        "results": sweep["results"],
    }
