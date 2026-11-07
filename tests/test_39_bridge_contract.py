"""T3 (wave-1): unified timestep-grid bridge contract.

Pins the relaxed weather-bridge exit contract:
  * validate_weather_grid accepts any uniform integer-second grid that
    covers the requested local year (900 s / 1800 s / 3600 s) and rejects
    gaps, disordered stamps, uneven steps, short windows, shifted starts
    and missing columns — each with the FIRST offending row index;
  * to_hourly aggregates sub-hourly grids to hourly rows (per-column
    arithmetic mean, hour-start stamps) and passes hourly input through
    bitwise-identically;
  * WeatherSeries.from_dataframe builds the loop lookup table from a
    timestamped frame (bridge column names), bit-identical to
    WeatherSeries.hourly on the same hourly data;
  * the city-CSV exit loads a 15-min aligned file silently at native
    resolution (integration with fetch_weather).
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

SRC = Path(__file__).resolve().parents[1] / "vfed"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from vfed.weather import weather_bridge  # noqa: E402
from vfed.weather.series import WeatherSeries  # noqa: E402


def _grid_frame(step_s: int, n: int, start: str = "2025-01-01") -> pd.DataFrame:
    """Uniform grid frame with the required bridge columns and float values."""
    idx = pd.date_range(start, periods=n, freq=f"{step_s}s")
    return pd.DataFrame(
        {
            "temperature_2m": np.linspace(-5.0, 35.0, n),
            "relative_humidity_2m": np.full(n, 55.0),
            "shortwave_radiation": np.linspace(0.0, 900.0, n),
        },
        index=idx,
    )


# ── validate_weather_grid: acceptance ─────────────────────────────────────


def test_validate_accepts_15min_full_year():
    """35040 rows of 900 s covering 2025 validate and return the step."""
    df = _grid_frame(900, 35040)
    assert weather_bridge.validate_weather_grid(df, 2025, "unit") == 900


def test_validate_accepts_hourly_full_year():
    df = _grid_frame(3600, 8760)
    assert weather_bridge.validate_weather_grid(df, 2025, "unit") == 3600


def test_validate_accepts_30min_leap_year():
    df = _grid_frame(1800, 17568, start="2024-01-01")
    assert weather_bridge.validate_weather_grid(df, 2024, "unit") == 1800


# ── validate_weather_grid: rejections carry the first offending row ───────


def test_reject_gap_reports_row_index():
    df = _grid_frame(3600, 8760).drop(index=pd.Timestamp("2025-01-05 04:00:00"))
    with pytest.raises(weather_bridge.WeatherFetchError, match="row 100"):
        weather_bridge.validate_weather_grid(df, 2025, "unit")


def test_reject_disorder_reports_row_index():
    df = _grid_frame(3600, 8760)
    idx = df.index.to_numpy().copy()  # shallow copy of the stamp array
    idx[50], idx[51] = idx[51], idx[50]
    df.index = pd.DatetimeIndex(idx)
    with pytest.raises(weather_bridge.WeatherFetchError, match="row 51"):
        weather_bridge.validate_weather_grid(df, 2025, "unit")


def test_reject_uneven_step_reports_row_index():
    idx = pd.DatetimeIndex(
        [pd.Timestamp("2025-01-01"), pd.Timestamp("2025-01-01 00:15:00"),
         pd.Timestamp("2025-01-01 00:45:00"), pd.Timestamp("2025-01-01 01:00:00")]
    )
    df = pd.DataFrame(
        {"temperature_2m": [1.0, 2.0, 3.0, 4.0],
         "relative_humidity_2m": [50.0, 50.0, 50.0, 50.0],
         "shortwave_radiation": [0.0, 0.0, 0.0, 0.0]},
        index=idx,
    )
    with pytest.raises(weather_bridge.WeatherFetchError, match="row 2"):
        weather_bridge.validate_weather_grid(df, 2025, "unit")


def test_reject_short_window_reports_expected_count():
    df = _grid_frame(3600, 8759)  # one hour missing at the tail
    with pytest.raises(weather_bridge.WeatherFetchError, match="expected 8760"):
        weather_bridge.validate_weather_grid(df, 2025, "unit")


def test_reject_shifted_start_reports_row_0():
    df = _grid_frame(3600, 8760, start="2025-01-01 08:00")
    with pytest.raises(weather_bridge.WeatherFetchError, match="row 0"):
        weather_bridge.validate_weather_grid(df, 2025, "unit")


def test_reject_missing_column_names_it():
    df = _grid_frame(3600, 8760).drop(columns=["shortwave_radiation"])
    with pytest.raises(weather_bridge.WeatherFetchError, match="shortwave_radiation"):
        weather_bridge.validate_weather_grid(df, 2025, "unit")


def test_reject_sub_second_step():
    idx = pd.date_range("2025-01-01", periods=3, freq="1500ms")
    df = pd.DataFrame(
        {"temperature_2m": [1.0, 2.0, 3.0],
         "relative_humidity_2m": [50.0, 50.0, 50.0],
         "shortwave_radiation": [0.0, 0.0, 0.0]},
        index=idx,
    )
    with pytest.raises(weather_bridge.WeatherFetchError, match="whole number of seconds"):
        weather_bridge.validate_weather_grid(df, 2025, "unit")


def test_city_context_tolerates_shifted_window():
    """strict_window=False keeps the city warn-and-use-as-is behaviour: a
    rotated window raises nothing here (the WARNING lives in fetch_weather
    and is pinned by test_10_time_axis)."""
    df = _grid_frame(3600, 8760, start="2025-01-01 08:00")
    step = weather_bridge.validate_weather_grid(
        df, 2025, "City weather file TestCity_2025.csv", strict_window=False
    )
    assert step == 3600


# ── to_hourly ─────────────────────────────────────────────────────────────


def test_to_hourly_aggregates_15min():
    df = _grid_frame(900, 35040)
    out = weather_bridge.to_hourly(df)
    assert len(out) == 8760
    assert (out.index == pd.date_range("2025-01-01", periods=8760, freq="h")).all()
    # GHI energy conservation: hourly mean W/m^2 * 3600 s == native sum * 900 s.
    assert out["shortwave_radiation"].sum() * 3600 == pytest.approx(
        df["shortwave_radiation"].sum() * 900
    )
    # Arithmetic mean of the first hour's four temperature rows.
    assert out["temperature_2m"].iloc[0] == pytest.approx(
        df["temperature_2m"].iloc[:4].mean()
    )


def test_to_hourly_hourly_input_is_bitwise_identity():
    df = _grid_frame(3600, 8760)
    df.attrs["weather_source"] = "unit"
    out = weather_bridge.to_hourly(df)
    assert len(out) == len(df)
    assert out.index.equals(df.index)
    assert out.dtypes.equals(df.dtypes)
    for c in df.columns:
        assert np.array_equal(out[c].to_numpy(), df[c].to_numpy())
    assert out.attrs == df.attrs
    # independence: mutating the copy leaves the input untouched
    out.iloc[0, 0] = -999.0
    assert df.iloc[0, 0] != -999.0


def test_to_hourly_rejects_step_not_dividing_hour():
    df = _grid_frame(2400, 12)  # 40-min steps never tile whole hours
    with pytest.raises(weather_bridge.WeatherFetchError, match="divide one hour"):
        weather_bridge.to_hourly(df)


def test_to_hourly_rejects_non_hour_anchored_start():
    df = _grid_frame(900, 8, start="2025-01-01 00:30:00")
    with pytest.raises(weather_bridge.WeatherFetchError, match="anchored on the"):
        weather_bridge.to_hourly(df)


def test_to_hourly_rejects_partial_hour_tail():
    df = _grid_frame(900, 6)  # 6 rows of 4 do not tile whole hours
    with pytest.raises(weather_bridge.WeatherFetchError, match="whole hours"):
        weather_bridge.to_hourly(df)


# ── WeatherSeries.from_dataframe ──────────────────────────────────────────


def _hourly_columns(seed: int = 7):
    rng = np.random.default_rng(seed)
    return {
        "T_ext": rng.uniform(-5, 35, 8760),
        "RH_ext": rng.uniform(20, 90, 8760),
        "GHI": rng.uniform(0, 900, 8760),
    }


def test_from_dataframe_matches_hourly_constructor():
    cols = _hourly_columns()
    df = pd.DataFrame(
        {
            "temperature_2m": cols["T_ext"],
            "relative_humidity_2m": cols["RH_ext"],
            "shortwave_radiation": cols["GHI"],
        },
        index=pd.date_range("2025-01-01", periods=8760, freq="h"),
    )
    ws_ref = WeatherSeries.hourly(cols)
    ws = WeatherSeries.from_dataframe(df)
    assert np.array_equal(ws._start, ws_ref._start)
    for name in ("T_ext", "RH_ext", "GHI"):
        assert np.array_equal(ws._columns[name], ws_ref._columns[name])
    for t in (0, 3600, 17 * 3600 + 1800, 8759 * 3600):
        assert ws.sample(t) == ws_ref.sample(t)


def test_from_dataframe_accepts_timestamp_column():
    cols = _hourly_columns()
    df = pd.DataFrame(
        {
            "timestamp": pd.date_range("2025-01-01", periods=8760, freq="h"),
            "temperature_2m": cols["T_ext"],
            "relative_humidity_2m": cols["RH_ext"],
            "shortwave_radiation": cols["GHI"],
        }
    )
    ws = WeatherSeries.from_dataframe(df)
    assert ws._step == 3600
    assert ws.sample(3 * 3600) == WeatherSeries.hourly(cols).sample(3 * 3600)


def test_from_dataframe_rejects_sub_second_stamps():
    idx = pd.date_range("2025-01-01", periods=3, freq="1500ms")
    df = pd.DataFrame(
        {"temperature_2m": [1.0, 2.0, 3.0],
         "relative_humidity_2m": [50.0, 50.0, 50.0],
         "shortwave_radiation": [0.0, 0.0, 0.0]},
        index=idx,
    )
    with pytest.raises(ValueError, match="whole seconds"):
        WeatherSeries.from_dataframe(df)


def test_from_dataframe_rejects_missing_column():
    df = _grid_frame(3600, 8760).drop(columns=["relative_humidity_2m"])
    with pytest.raises(ValueError, match="relative_humidity_2m"):
        WeatherSeries.from_dataframe(df)


# ── city-path integration: 15-min file loads at native resolution ────────


@pytest.fixture
def city_env(tmp_path, monkeypatch):
    holder = {"path": None}
    monkeypatch.setattr(weather_bridge, "_find_city_csv", lambda city, year, **kw: holder["path"])
    return holder


def test_city_path_loads_15min_file_silently(city_env, tmp_path):
    """An aligned 35040-row 15-min city file loads with NO warning at native
    resolution and aggregates to exactly 8760 hourly rows."""
    n = 35040
    df = pd.DataFrame(
        {
            "timestamp": pd.date_range("2025-01-01", periods=n, freq="15min")
                           .strftime("%Y-%m-%d %H:%M:%S"),
            "temperature_2m": np.linspace(-5.0, 35.0, n),
            "relative_humidity_2m": np.full(n, 55.0),
            "wind_speed_10m": np.full(n, 1.0),
            "shortwave_radiation": np.abs(np.sin(np.linspace(0.0, 1000.0, n))) * 800.0,
            "direct_radiation": np.zeros(n),
            "diffuse_radiation": np.zeros(n),
        }
    )
    f = tmp_path / "TestCity_2025.csv"
    df.to_csv(f, index=False)
    city_env["path"] = f

    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("error")  # aligned native-res file must be silent
        out = weather_bridge.fetch_weather(
            lat=31.23, lon=121.47, year=2025, tz_hours=8.0,
            tilt=20.0, azimuth=180.0, cache_dir=tmp_path, city="TestCity",
        )
    assert len(out) == 35040
    assert out.index[0] == pd.Timestamp("2025-01-01")
    assert (np.diff(out.index.asi8)[:5] == 900_000_000_000).all()  # native 15-min step
    hourly = weather_bridge.to_hourly(out)
    assert len(hourly) == 8760
    assert hourly["shortwave_radiation"].sum() * 3600 == pytest.approx(
        out["shortwave_radiation"].sum() * 900
    )


def test_city_path_rejects_broken_grid(city_env, tmp_path):
    """A gapped city file now RAISES (the pre-T3 code only warned on any
    misalignment; broken grids were silently passed downstream)."""
    df = _grid_frame(3600, 8760).drop(index=pd.Timestamp("2025-01-05 04:00:00"))
    df = df.reset_index().rename(columns={"index": "timestamp"})
    df["wind_speed_10m"] = 1.0
    df["direct_radiation"] = 0.0
    df["diffuse_radiation"] = 0.0
    f = tmp_path / "TestCity_2025.csv"
    df.to_csv(f, index=False)
    city_env["path"] = f

    with pytest.raises(weather_bridge.WeatherFetchError, match="row 100"):
        weather_bridge.fetch_weather(
            lat=31.23, lon=121.47, year=2025, tz_hours=8.0,
            tilt=20.0, azimuth=180.0, cache_dir=tmp_path, city="TestCity",
        )
