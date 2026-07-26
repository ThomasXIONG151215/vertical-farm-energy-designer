"""
Layer 1: Smoke tests — imports, compile, basic sweep.

These confirm the toolchain is wired up correctly.  No physics validation.
"""
import sys
from pathlib import Path

import pytest

# Add src to path for direct imports in tests
SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from src.design.presets import preset_609


# ---------------------------------------------------------------------------
# 1.1  All modules import
# ---------------------------------------------------------------------------
MODULES = [
    ("src.design.project", "DesignProject"),
    ("src.design.engine", "DesignEngine"),
    ("src.design.sweep", "sweep_design"),
    ("src.design.presets", "preset_609"),
    ("src.devices.hvac", "HVACDevice"),
    ("src.devices.dehumidifier", "DEHDevice"),
    ("src.devices.led", "LEDDevice"),
        ("src.devices.compressor", "CompressorState"),
        ("src.devices.lag", "FirstOrderLag"),
        ("src.physics.psychrometrics", "saturation_vapor_pressure"),
        ("src.physics.shr", "DynamicSHR"),
        ("src.physics.envelope", "Envelope"),
        ("src.physics.ode", "RoomODESolver"),
        ("src.plants.van_henten", "VanHenten"),
    ("src.plants.transpiration", "TranspirationModel"),
    ("src.pvbes.pv", "PVSystem"),
    ("src.pvbes.battery", "BatterySystem"),
    ("src.pvbes.grid", "Tariff"),
    ("src.pvbes.energy_system", "EnergySystem"),
    ("src.agent.evaluator", "agent_evaluate"),
    ("src.weather.weather_bridge", "fetch_weather"),
    ("src.weather.geocode", "geocode_city"),
]


@pytest.mark.parametrize("mod, name", MODULES)
def test_import_module(mod, name):
    """Every public module and its primary export must be importable."""
    m = __import__(mod, fromlist=[name])
    assert getattr(m, name) is not None


# ---------------------------------------------------------------------------
# 1.2  Compile all src/
# ---------------------------------------------------------------------------
def test_compile_all():
    """py_compile every .py under src/ — catches syntax errors."""
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
    from src.design.sweep import sweep_design

    result = sweep_design(project_609)
    assert result["results"] is None
    assert result["best"] is not None
    assert "kwh_per_kg_fresh" in result["best"]


# ---------------------------------------------------------------------------
# 1.4  Smoke sweep — with ranges
# ---------------------------------------------------------------------------
def test_sweep_with_ranges(project_609):
    """Two ppfd values times two pv areas = 4 configs."""
    from src.design.sweep import sweep_design

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
