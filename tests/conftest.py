"""
Shared pytest fixtures (session-scoped for performance).

* ``weather_609``: real weather DataFrame for Fengxian 2023 (disk-cached).
* ``project_609``: DesignProject from preset_609 (Fengxian lettuce PFAL).
* ``sim_609``: DesignEngine.run() result for the preset_609 project.
"""

import pytest

from src.design.project import DesignProject
from src.design.presets import preset_609
from src.design.engine import DesignEngine
from src.weather.weather_bridge import fetch_weather


@pytest.fixture(scope="session")
def weather_609():
    """Hourly weather for Fengxian 2023 — real API, disk-cached."""
    return fetch_weather(
        lat=30.9, lon=121.5, year=2023, tz_hours=8.0, tilt=20.0, azimuth=180.0,
        cache_dir="weather_cache", force=False,
    )


@pytest.fixture(scope="session")
def project_609():
    """Fengxian lettuce PFAL (preset 609) DesignProject."""
    return preset_609()


@pytest.fixture(scope="session")
def sim_609(project_609):
    """Single-point engine.run() result for preset_609."""
    engine = DesignEngine(cache_dir="weather_cache")
    return engine.run(project_609)
