"""
Agent evaluator — design-time evaluation surface.

Preserves the agent-cli contract (structured ``success`` + error-code payload)
used by the original ``src/agent/evaluator.py`` while targeting the new
parametric ODE + PVBES design simulator.

Error codes:
    E001  invalid / missing project configuration
    E003  weather acquisition failed
    E101  building simulation failed
    E102  no feasible PVBES design found
    E103  empty / zero load profile
"""

from typing import Dict, Optional

import numpy as np

from ..design.project import DesignProject
from ..design.engine import DesignEngine
from ..design.sweep import sweep_design

__all__ = ["agent_evaluate", "agent_simulate"]


def agent_simulate(project: DesignProject, cache_dir: Optional[str] = "weather_cache") -> Dict:
    """Run the building simulation for a project. Returns load + weather."""
    engine = DesignEngine(cache_dir=cache_dir)
    try:
        result = engine.run(project)
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


def agent_evaluate(project_path: str, cache_dir: Optional[str] = "weather_cache",
                   tlps_max: float = 100.0) -> Dict:
    """Full pipeline: load project -> simulate -> sweep PVBES -> best design."""
    # E001: configuration
    try:
        project = DesignProject.load(project_path)
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error_code": "E001",
                "message": f"invalid project config: {e}"}

    # Build simulation result (reuses weather cache internally).
    sim = agent_simulate(project, cache_dir=cache_dir)
    if not sim["success"]:
        # E003 if weather fetch is the underlying cause.
        if "weather" in str(sim.get("message", "")).lower() or "fetch" in str(sim.get("message", "")).lower():
            return {"success": False, "error_code": "E003", "message": sim["message"]}
        return sim

    try:
        sweep = sweep_design(project, sim["load"], sim["weather"], tlps_max=tlps_max)
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error_code": "E101",
                "message": f"PVBES evaluation failed: {e}"}

    if sweep["best"] is None:
        return {"success": False, "error_code": "E102",
                "message": "no feasible PVBES design found",
                "results": sweep["results"]}

    return {
        "success": True,
        "project": project.name,
        "best": sweep["best"],
        "results": sweep["results"],
        "timeseries": sim["timeseries"],
        "annual_load_kwh": sim["annual_load_kwh"],
        "biomass_kg": sim.get("biomass_kg", 0.0),
        "kwh_per_kg": sim.get("kwh_per_kg", 0.0),
        "kwh_per_kg_fresh": sim.get("kwh_per_kg_fresh", 0.0),
    }
