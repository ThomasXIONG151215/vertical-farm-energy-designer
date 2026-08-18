"""
Layer 1: Smoke tests — imports, compile, basic sweep.

These confirm the toolchain is wired up correctly.  No physics validation.
"""
import sys
from pathlib import Path

import pytest

# Add src to path for direct imports in tests
SRC = Path(__file__).resolve().parents[1] / "vfed"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from vfed.design.presets import preset_609


# ---------------------------------------------------------------------------
# 1.1  All modules import
# ---------------------------------------------------------------------------
MODULES = [
    ("vfed.design.project", "DesignProject"),
    ("vfed.design.engine", "DesignEngine"),
    ("vfed.design.sweep", "sweep_design"),
    ("vfed.design.presets", "preset_609"),
    ("vfed.devices.hvac", "HVACDevice"),
    ("vfed.devices.dehumidifier", "DEHDevice"),
    ("vfed.devices.led", "LEDDevice"),
        ("vfed.devices.compressor", "CompressorState"),
        ("vfed.devices.lag", "FirstOrderLag"),
        ("vfed.physics.psychrometrics", "saturation_vapor_pressure"),
        ("vfed.physics.shr", "DynamicSHR"),
        ("vfed.physics.envelope", "Envelope"),
        ("vfed.physics.ode", "RoomODESolver"),
        ("vfed.plants.van_henten", "VanHenten"),
    ("vfed.plants.transpiration", "TranspirationModel"),
    ("vfed.pvbes.pv", "PVSystem"),
    ("vfed.pvbes.battery", "BatterySystem"),
    ("vfed.pvbes.grid", "Tariff"),
    ("vfed.pvbes.energy_system", "EnergySystem"),
    ("vfed.agent.evaluator", "agent_evaluate"),
    ("vfed.weather.weather_bridge", "fetch_weather"),
    ("vfed.weather.geocode", "geocode_city"),
]


@pytest.mark.parametrize("mod, name", MODULES)
def test_import_module(mod, name):
    """Every public module and its primary export must be importable."""
    m = __import__(mod, fromlist=[name])
    assert getattr(m, name) is not None


# ---------------------------------------------------------------------------
# 1.2  Compile all vfed/
# ---------------------------------------------------------------------------
def test_compile_all():
    """py_compile every .py under vfed/ — catches syntax errors."""
    import py_compile

    root = SRC
    errors = []
    for path in sorted(root.rglob("*.py")):
        try:
            py_compile.compile(str(path), doraise=True)
        except py_compile.PyCompileError as e:
            errors.append(f"{path.relative_to(root)}: {e}")
    assert not errors, "\n".join(errors)


# ---------------------------------------------------------------------------
# 1.3  Smoke sweep — single-point
# ---------------------------------------------------------------------------
def test_sweep_single_point(project_609):
    """Empty parameter_ranges returns single-point result."""
    from vfed.design.sweep import sweep_design

    result = sweep_design(project_609)
    assert result["results"] is None
    assert result["best"] is not None
    assert "kwh_per_kg_fresh" in result["best"]


# ---------------------------------------------------------------------------
# 1.4  Smoke sweep — with ranges
# ---------------------------------------------------------------------------
def test_sweep_with_ranges(project_609):
    """Two ppfd values times two pv areas = 4 configs."""
    from vfed.design.sweep import sweep_design

    p = project_609
    p.space.parameter_ranges = {
        "ppfd_target": [200, 400, 200],
        "pv_area": [0, 50, 50],
    }
    result = sweep_design(p)
    assert result["results"] is not None
    assert len(result["results"]) == 4
    best = result["best"]
    assert "lcoe" in best
    assert best["lcoe"] >= 0
