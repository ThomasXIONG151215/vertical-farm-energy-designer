"""
Layer 6: Stress / edge-case tests.

Verifies the system handles boundary conditions, deadbands, and
extreme configurations gracefully.
"""
import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


# ---------------------------------------------------------------------------
# 6.1  Zero interest rate → LCOE defined
# ---------------------------------------------------------------------------
def test_zero_interest_lcoe_defined(project_609):
    """i=0 should still produce a finite LCOE (regression: DIV/0 was bug)."""
    from src.design.sweep import sweep_design

    p = project_609
    p.interest_rate = 0.0
    p.space.parameter_ranges = {
        "pv_area": [50, 200, 50],
    }
    result = sweep_design(p)
    best = result["best"]
    assert np.isfinite(best["lcoe"])
    assert best["lcoe"] >= 0


# ---------------------------------------------------------------------------
# 6.2  Minimal PVBES (pv=0, battery=0)
# ---------------------------------------------------------------------------
def test_zero_pv_zero_battery(project_609):
    """pv_area=0, battery=0 should produce finite LCOE (grid-only)."""
    from src.design.sweep import sweep_design

    p = project_609
    p.space.parameter_ranges = {
        "pv_area": [0, 100, 100],
        "battery": [0, 100, 100],
    }
    result = sweep_design(p)
    # find the row with pv_area=0, battery_kwh=0 manually
    df = result["results"]
    zero_row = df[(df["pv_area"] == 0) & (df["battery_kwh"] == 0)]
    assert len(zero_row) > 0
    assert np.isfinite(zero_row.iloc[0]["lcoe"])


# ---------------------------------------------------------------------------
# 6.3  Deadband — heating/cooling idle
# ---------------------------------------------------------------------------
def test_wide_deadband(project_609):
    """Deadband=10 should allow temperature to swing freely."""
    from src.design.engine import DesignEngine

    p = project_609
    p.hvac.deadband_c = 10.0
    engine = DesignEngine()
    sim = engine.run(p)
    T = sim["timeseries"]["T_z"].values
    # With large deadband the temperature should still be physical
    assert 0.0 < T.min() < 40.0
    assert T.max() < 60.0


# ---------------------------------------------------------------------------
# 6.4  Extreme PPFD bounds
# ---------------------------------------------------------------------------
def test_min_ppfd_runs(project_609):
    """ppfd=50 should run without crash (low PAR)."""
    from src.design.engine import DesignEngine

    p = project_609
    p.led.ppfd_target = 50.0
    engine = DesignEngine()
    sim = engine.run(p)
    assert sim["biomass_kg"] > 0

def test_max_ppfd_runs(project_609):
        """ppfd=500 should run without crash (high PAR)."""
        from src.design.engine import DesignEngine

        p = project_609
        p.led.ppfd_target = 500.0
        engine = DesignEngine()
        sim = engine.run(p)
        assert sim["biomass_kg"] > 0


# ---------------------------------------------------------------------------
# 6.5  Battery SOC bounds
# ---------------------------------------------------------------------------
def test_battery_soc_bounds(project_609):
    """SOC must stay in [soc_min, soc_max] regardless of configuration."""
    from src.design.sweep import _build_energy_system
    from src.design.engine import DesignEngine

    p = project_609
    es = _build_energy_system(p)
    engine = DesignEngine()
    sim = engine.run(p)
    perf = es.simulate_performance([100.0, 20.0], sim["weather"], sim["load"])
    soc = perf["battery_soc"]
    assert float(soc.min()) >= p.battery.soc_min - 1e-6, \
        f"SOC min={soc.min()} below allowed {p.battery.soc_min}"
    assert float(soc.max()) <= p.battery.soc_max + 1e-6, \
        f"SOC max={soc.max()} above allowed {p.battery.soc_max}"


# ---------------------------------------------------------------------------
# 6.6  Weather API
# ---------------------------------------------------------------------------
@pytest.mark.slow
def test_weather_fetch_real():
    """Real fetch_weather() should return 8760 hours for Fengxian."""
    from src.weather.weather_bridge import fetch_weather

    weather = fetch_weather(30.9, 121.5, year=2023, cache_dir="weather_cache")
    assert "temperature_2m" in weather
    assert len(weather["temperature_2m"]) == 8760

@pytest.mark.slow
def test_weather_no_cache(project_609):
    """fetch_weather with no existing cache file should work."""
    from src.weather.weather_bridge import fetch_weather

    import tempfile, os
    tmpdir = tempfile.mkdtemp()
    try:
        weather = fetch_weather(30.9, 121.5, year=2023, cache_dir=tmpdir)
        assert len(weather["temperature_2m"]) == 8760
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)
