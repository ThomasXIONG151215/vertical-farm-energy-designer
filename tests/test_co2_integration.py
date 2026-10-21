"""CO2 supplement M1: engine integration.

Contract under test (proposal §2.7, M1 rows):
  * ZERO DRIFT (the merge gate): preset_609 with the default
    co2.enabled=false reproduces the shared 48 h synthetic-run timeseries
    sha256 oracle EXACTLY (same constant as test_23..test_29), and no CO2
    column/key leaks into the default path.
  * enabled=true short window (7 days synthetic): CO2_z bounded inside
    [outdoor - eps, setpoint + band + dark-respiration headroom], no NaN,
    E_co2_Wh > 0 only during light hours, monthly/annual injected mass
    close, and the summary KPI keys appear.
"""

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

SRC = Path(__file__).resolve().parents[1] / "vfed"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from vfed.design.engine import DesignEngine
from vfed.design.presets import preset_609

# Zero-drift oracle: preset_609 on the deterministic 48 h synthetic weather
# below, timeseries JSON sha256 -- the SAME constant the test_23..test_29
# suites pin (re-captured at HEAD=01b7000 + R34/W3-D preset
# re-calibration).  The CO2 M1 supplement must not perturb it: every new
# engine float sits behind the co2.enabled guard.
ZERO_DRIFT_SHA256 = "1764f7e6ee6e185d41e8b438a2c3c81320f38e9d02468446dc5f249a25870192"


def synthetic_weather(n=48):
    """Deterministic synthetic weather (identical to test_23/24/25)."""
    idx = pd.date_range("2023-01-01 00:00", periods=n, freq="h")
    hour = np.arange(n, dtype=float)
    t_ext = 10.0 + 8.0 * np.sin((hour - 9.0) / 24.0 * 2.0 * np.pi)
    rh_ext = 70.0 + 10.0 * np.sin((hour - 3.0) / 24.0 * 2.0 * np.pi)
    ghi = np.clip(600.0 * np.sin((hour - 6.0) / 12.0 * np.pi), 0.0, None)
    return pd.DataFrame(
        {
            "temperature_2m": t_ext,
            "relative_humidity_2m": rh_ext,
            "wind_speed_10m": np.full(n, 2.0),
            "shortwave_radiation": ghi,
            "direct_radiation": ghi * 0.7,
            "diffuse_radiation": ghi * 0.3,
            "surface_pressure": np.full(n, 1013.25),
        },
        index=idx,
    )


class TestZeroDrift:
    def test_engine_default_path_sha256_unchanged(self):
        engine = DesignEngine(cache_dir=None)
        result = engine.run(preset_609(), weather=synthetic_weather(48))
        ts_json = json.dumps(result.timeseries, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(ts_json.encode("utf-8")).hexdigest()
        assert digest == ZERO_DRIFT_SHA256
        # additive columns/keys must not leak into the default path
        assert "CO2_z" not in result.timeseries
        assert "S_co2_inj_g_h" not in result.timeseries
        assert "E_co2_Wh" not in result.timeseries
        for key in (
            "annual_co2_injected_kg",
            "co2_mean_ppm",
            "co2_min_ppm",
            "co2_max_ppm",
            "co2_energy_kwh",
            "co2_below_setpoint_hours",
            "co2_clamp_stats",
        ):
            assert key not in result.summary
        assert "co2_injected_kg" not in result.monthly

    def test_explicit_disabled_section_same_digest(self):
        """An explicit co2 section with enabled=false is still the legacy
        path (config surface alone must not perturb the oracle)."""
        from vfed.design.project import DesignProject

        base = preset_609().to_dict()
        base["co2"] = {
            "enabled": False,
            "band_ppm": 80.0,
            "capacity_g_per_h": 300.0,
        }
        p = DesignProject.from_dict(base)
        engine = DesignEngine(cache_dir=None)
        result = engine.run(p, weather=synthetic_weather(48))
        ts_json = json.dumps(result.timeseries, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(ts_json.encode("utf-8")).hexdigest()
        assert digest == ZERO_DRIFT_SHA256


@pytest.fixture(scope="module")
def co2_run():
    """preset_609 + CO2 enabled, 7-day synthetic window (168 h)."""
    p = preset_609()
    p.co2.enabled = True  # setpoint inherits setpoints.co2_ppm = 800
    engine = DesignEngine(cache_dir=None)
    return engine.run(p, weather=synthetic_weather(168))


class TestEnabledRun:
    def test_columns_present_and_finite(self, co2_run):
        ts = co2_run.timeseries
        for col in ("CO2_z", "S_co2_inj_g_h", "E_co2_Wh"):
            assert col in ts
            arr = np.asarray(ts[col], dtype=float)
            assert len(arr) == 168
            assert np.isfinite(arr).all()

    def test_concentration_bounds(self, co2_run):
        """CO2_z within [outdoor - eps, setpoint + band + headroom].

        Upper headroom (300 ppm) covers the two physical overshoot
        mechanisms on a 600 s control step: the bang-bang injector can
        cross sp+band by up to one substep of capacity (~91 ppm for
        200 g/h on the 240 kg air store), and the dark-period respiration
        source accumulates on top (no injection, no purge at ach=0.001,
        up to ~100 ppm over 8 h at late-cycle biomass)."""
        co2 = np.asarray(co2_run.timeseries["CO2_z"], dtype=float)
        sp, band, outdoor = 800.0, 50.0, 420.0
        assert co2.min() >= outdoor - 1.0
        assert co2.max() <= sp + band + 300.0
        # injector keeps the light period inside a sane control envelope
        hod = np.asarray(co2_run.timeseries["hour_of_day"], dtype=float)
        light = (hod >= 6.0) & (hod < 22.0)
        assert co2[light].max() <= sp + band + 150.0

    def test_injection_only_in_light(self, co2_run):
        ts = co2_run.timeseries
        e = np.asarray(ts["E_co2_Wh"], dtype=float)
        hod = np.asarray(ts["hour_of_day"], dtype=float)
        light = (hod >= 6.0) & (hod < 22.0)
        dark = ~light
        assert (e[dark] == 0.0).all(), "injector drew power in the dark"
        assert (e[light] > 0.0).any(), "injector never ran in the light"
        s = np.asarray(ts["S_co2_inj_g_h"], dtype=float)
        assert (s[dark] >= 0.0).all()
        assert s.max() <= 200.0 + 1e-9, "capacity cap violated"

    def test_summary_kpis_and_closures(self, co2_run):
        s = co2_run.summary
        assert s["annual_co2_injected_kg"] > 0.0
        assert 400.0 <= s["co2_min_ppm"] <= s["co2_mean_ppm"] <= s["co2_max_ppm"]
        assert s["co2_below_setpoint_hours"] > 0
        e = np.asarray(co2_run.timeseries["E_co2_Wh"], dtype=float)
        assert s["co2_energy_kwh"] == pytest.approx(float(e.sum()) / 1000.0, abs=0.01)
        # monthly buckets close against the annual total
        m = co2_run.monthly["co2_injected_kg"]
        assert len(m) == 12
        assert sum(m) == pytest.approx(s["annual_co2_injected_kg"], abs=0.01)
        # uptake cap keeps the Γ floor untouched in a sane configuration
        assert s["co2_clamp_stats"]["floor_clip_events"] == 0

    def test_energy_breakdown_structure_unchanged(self, co2_run):
        """4-key structure intact; CO2 electricity folded into misc so the
        shares still close against the annual total, and the hourly E
        columns (incl. E_co2_Wh) close against load_kw."""
        eb = co2_run.energy_breakdown
        assert set(eb) == {"hvac_pct", "deh_pct", "led_pct", "misc_pct"}
        assert sum(eb.values()) == pytest.approx(1.0, abs=5e-4)
        ts = co2_run.timeseries
        load_kwh = float(np.sum(np.asarray(ts["load_kw"], dtype=float)))
        comp_kwh = sum(
            float(np.sum(np.asarray(ts[c], dtype=float))) / 1000.0
            for c in ("E_hvac_Wh", "E_deh_Wh", "E_led_Wh", "E_misc_Wh", "E_co2_Wh")
        )
        assert comp_kwh == pytest.approx(load_kwh, rel=1e-6)

    def test_dark_respiration_accumulation_visible(self, co2_run):
        """M1 includes the dark-period respiration source: with
        inject_in_dark=false and a near-sealed room, CO2 rises during the
        dark stretch (the proposal's built-in sanity check)."""
        co2 = np.asarray(co2_run.timeseries["CO2_z"], dtype=float)
        hod = np.asarray(co2_run.timeseries["hour_of_day"], dtype=float)
        dark = (hod >= 22.0) | (hod < 6.0)
        assert co2[dark].max() > 800.0  # above the setpoint: respiration
