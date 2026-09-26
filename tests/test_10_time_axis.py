"""P1-3b: time-axis / window alignment.

Pins the aligned local-calendar-year contract:
  * city CSV ingestion guard (P4-16 parity): rotated-window files trigger a
    grep-able ASCII WARNING and are used as-is (no interpolation), aligned
    files load silently; the misleading legacy "+00:00" suffix is stripped so
    the index is naive local wall time;
  * timeseries.csv gains ISO8601 local timestamp + hourly tariff price
    columns (additive): 8760 rows, strictly monotonic, first = {year}-01-01
    00:00, price bitwise-equal to tariff.hourly_prices;
  * monthly buckets are natural months (m1 = 744 h in 2025);
  * the regenerated Shanghai 2025 city file pins the new aligned-window
    authoritative baseline (migrated from the rotating-window 62,452.72 set).
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

SRC = Path(__file__).resolve().parents[1] / "vfed"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from vfed.design.engine import DesignEngine  # noqa: E402
from vfed.design.presets import preset_609  # noqa: E402
from vfed.weather import weather_bridge  # noqa: E402

# Natural-month hour counts for the non-leap year 2025.
HOURS_2025 = [744, 672, 744, 720, 744, 720, 744, 744, 720, 744, 720, 744]

_COLS = [
    "timestamp", "temperature_2m", "relative_humidity_2m", "wind_speed_10m",
    "shortwave_radiation", "direct_radiation", "diffuse_radiation",
]


def _write_weather_csv(path, stamps, suffix=""):
    """Minimal hourly CSV with the city-file schema; zeros are fine for the
    guard tests (add_poa handles an all-zero horizontal input)."""
    rows = ["timestamp,temperature_2m,relative_humidity_2m,wind_speed_10m,"
            "shortwave_radiation,direct_radiation,diffuse_radiation"]
    for s in stamps:
        rows.append(f"{s}{suffix},10.0,50.0,1.0,0.0,0.0,0.0")
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def _year_stamps(year, n=8760):
    return [s.strftime("%Y-%m-%d %H:%M:%S")
            for s in pd.date_range(f"{year}-01-01", periods=n, freq="h")]


@pytest.fixture
def city_env(tmp_path, monkeypatch):
    """Isolated fetch_weather(city=...) environment: _find_city_csv points at
    a caller-populated temp file; cache writes stay inside tmp_path."""
    holder = {"path": None}

    def fake_find(city, year, **kw):
        return holder["path"]

    monkeypatch.setattr(weather_bridge, "_find_city_csv", fake_find)
    return holder


# ── T4-1: guard fires on rotated window, silent on aligned window ─────────


def test_guard_warns_on_rotated_window(city_env, tmp_path):
    """Legacy rotated file (first row 08:00 local, tail wrapped into 2026):
    WARNING with filename + actual first stamp, then use as-is (8760 rows,
    no interpolation, no synthesized rows)."""
    stamps = [s.strftime("%Y-%m-%d %H:%M:%S")
              for s in pd.date_range("2025-01-01 08:00", periods=8760, freq="h")]
    f = tmp_path / "TestCity_2025.csv"
    _write_weather_csv(f, stamps, suffix="+00:00")
    city_env["path"] = f

    with pytest.warns(UserWarning, match="TestCity_2025.csv") as rec:
        df = weather_bridge.fetch_weather(
            lat=31.23, lon=121.47, year=2025, tz_hours=8.0,
            tilt=20.0, azimuth=180.0, cache_dir=tmp_path, city="TestCity",
        )
    msg = str(rec[0].message)
    assert "not aligned" in msg
    assert "2025-01-01 08:00:00" in msg  # actual first row timestamp
    assert msg == msg.encode("ascii").decode("ascii")  # pure ASCII, grep-able
    # used as-is: rotated window preserved, no rows invented
    assert len(df) == 8760
    assert df.index[0] == pd.Timestamp("2025-01-01 08:00:00")


def test_guard_silent_on_aligned_window(city_env, tmp_path):
    f = tmp_path / "TestCity_2025.csv"
    _write_weather_csv(f, _year_stamps(2025))
    city_env["path"] = f

    import warnings as _w

    with _w.catch_warnings():
        _w.simplefilter("error")  # any warning fails the test
        df = weather_bridge.fetch_weather(
            lat=31.23, lon=121.47, year=2025, tz_hours=8.0,
            tilt=20.0, azimuth=180.0, cache_dir=tmp_path, city="TestCity",
        )
    assert df.index[0] == pd.Timestamp("2025-01-01 00:00:00")
    assert df.index[-1] == pd.Timestamp("2025-12-31 23:00:00")


def test_guard_strips_misleading_utc_suffix(city_env, tmp_path):
    """Legacy '+00:00' labels are a misleading tag on local wall-clock values:
    after ingestion the index must be naive with values unchanged."""
    stamps = [s.strftime("%Y-%m-%d %H:%M:%S")
              for s in pd.date_range("2025-01-01 08:00", periods=8760, freq="h")]
    f = tmp_path / "TestCity_2025.csv"
    _write_weather_csv(f, stamps, suffix="+00:00")
    city_env["path"] = f

    with pytest.warns(UserWarning):
        df = weather_bridge.fetch_weather(
            lat=31.23, lon=121.47, year=2025, tz_hours=8.0,
            tilt=20.0, azimuth=180.0, cache_dir=tmp_path, city="TestCity",
        )
    assert df.index.tz is None
    assert df.index[0] == pd.Timestamp("2025-01-01 08:00:00")  # wall value kept
    assert df.index[-1] == pd.Timestamp("2026-01-01 07:00:00")


# ── city-path simulation (regenerated Shanghai file) ───────────────────────


@pytest.fixture(scope="module")
def sim_shanghai_aligned():
    """preset 609 @ regenerated (aligned) Shanghai 2025 city file."""
    p = preset_609()
    p.site.lat = 31.23
    p.site.lon = 121.47
    p.site.city = "Shanghai"
    p.site.year = 2025
    return DesignEngine(cache_dir="weather_cache").run(p)


def test_timestamp_column_iso8601_monotonic_unique(sim_shanghai_aligned):
    ts = sim_shanghai_aligned.timeseries
    stamps = ts["timestamp"]
    assert len(stamps) == 8760
    assert len(set(stamps)) == 8760  # no duplicates (old file had (1,1,h) twice)
    parsed = pd.to_datetime(pd.Series(stamps))
    assert parsed.is_monotonic_increasing
    assert stamps[0] == "2025-01-01T00:00:00"
    assert stamps[-1] == "2025-12-31T23:00:00"


def test_price_column_bitwise_matches_tariff(sim_shanghai_aligned):
    from vfed.design.presets import preset_609 as _p609

    tariff = _p609().tariff.hourly_prices
    ts = sim_shanghai_aligned.timeseries
    hod = np.asarray(ts["hour_of_day"]).astype(int)
    assert np.array_equal(np.asarray(ts["price"]), np.asarray(tariff)[hod])


def test_monthly_buckets_are_natural_months(sim_shanghai_aligned):
    ts = sim_shanghai_aligned.timeseries
    counts = pd.Series(ts["month"]).value_counts().sort_index()
    assert counts.tolist() == HOURS_2025
    assert counts.loc[1] == 744  # m1 = 744 h (was 736 + 8 phantom next-year h)


def test_monthly_electricity_cost_closes_annual(sim_shanghai_aligned):
    m = sim_shanghai_aligned.monthly
    s = sim_shanghai_aligned.summary
    assert sum(m["electricity_cost"]) == pytest.approx(s["annual_grid_cost_net"], abs=0.01)


# ── T4-5: new aligned-window authoritative baseline pin ────────────────────
# Migrated from the rotating-window pin set (annual 62,452.72 / specific
# 31.177 / m1 harvest 8.2964): the city files were regenerated on the aligned
# local calendar year, so the same physics now lands on these numbers.


def test_shanghai_aligned_baseline_energy(sim_shanghai_aligned):
    s = sim_shanghai_aligned.summary
    assert s["annual_energy_kwh"] == pytest.approx(62444.50, abs=5e-3)
    assert s["specific_energy_kwh_per_kg"] == pytest.approx(31.0499, abs=5e-4)
    assert s["annual_led_kwh"] == pytest.approx(42048.0, abs=0.01)
    assert s["annual_hvac_kwh"] == pytest.approx(10163.59, abs=0.01)
    assert s["lcoe"] == pytest.approx(0.6608, abs=5e-5)
    assert s["annual_grid_cost_net"] == pytest.approx(6244.45, abs=0.01)


def test_shanghai_aligned_baseline_harvest(sim_shanghai_aligned):
    s = sim_shanghai_aligned.summary
    m = sim_shanghai_aligned.monthly
    assert s["annual_harvest_kg"] == pytest.approx(100.55, abs=5e-3)
    assert s["harvest_final_standing_kg"] == pytest.approx(1.4617, abs=5e-4)
    assert m["harvest_kg"][0] == pytest.approx(8.3285, abs=5e-4)
    assert sum(m["harvest_kg"]) == pytest.approx(
        s["annual_harvest_kg"] - s["harvest_final_standing_kg"], abs=0.01
    )
