"""Round 22: NASA POWER weather provider + ghi_scale.

Pins the additive provider switch across the stack:

* ``_parse_power_csv``: header block located by ``-END HEADER-`` marker
  (never by line count), name-based column mapping (column order in the
  response differs from the request), hourly ALLSKY value used AS W/m^2
  (no x3600), and fail-fast rejection of any ``-999`` / missing row;
* provider routing: ``provider="nasa-power"`` hits power.larc.nasa.gov and
  tags attrs ``weather_source="NASA POWER hourly (MERRA-2/CERES)"``; the
  default (provider unset) still hits archive-api.open-meteo.com;
* P4-16 alignment parity: the POWER path yields exactly 8760 local-year
  rows for tz != 0 (the engine rejects any other year length);
* cache key namespacing: the POWER cache carries a ``_power`` suffix and
  the two sources never cross-hit at the same coordinates;
* city path: ``provider="nasa-power"`` looks for ``{City}_{year}_power.csv``
  only — an Open-Meteo run never picks up a ``_power`` file;
* ghi_scale: scales the radiation field (GHI + POA components) at the df
  exit, records ``attrs["ghi_scale"]``, and leaves the on-disk cache
  UNSCALED (a scale change never invalidates or poisons a cache);
* config guards: provider enum + (0.5, 1.5] band raise E001-style
  ValueErrors at load time; SiteConfig / preset defaults keep the
  open-meteo path untouched.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

SRC = Path(__file__).resolve().parents[1] / "vfed"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from vfed.design.presets import preset_609, preset_default  # noqa: E402
from vfed.design.project import DesignProject, SiteConfig  # noqa: E402
from vfed.weather import weather_bridge  # noqa: E402
from vfed.weather.weather_bridge import WeatherFetchError, fetch_weather  # noqa: E402

# Captured BEFORE any monkeypatching: lets the city-routing tests redirect
# the search root without recursing into the patched attribute.
_real_find_city_csv = weather_bridge._find_city_csv

_POWER_CACHE_NAME = "weather_31.230_121.470_2025_t20.000_a180.000_z8.000_power.csv"
_OM_CACHE_NAME = "weather_31.230_121.470_2025_t20.000_a180.000_z8.000.csv"


# ── mock builders (never online) ──────────────────────────────────────────


def _power_csv_text(
    start="2024-12-31",
    end="2026-01-02",
    t2m=12.5,
    rh=70.0,
    ws=3.0,
    ghi=500.0,
    poison=None,
):
    """Synthetic POWER hourly CSV: marker-delimited header block + a UTC
    YEAR,MO,DY,HR grid.  Column order deliberately differs from the request
    parameter order (POWER returns its own canonical order) — parsing must
    be name-based.  ``poison=(timestamp, var_index)`` writes a -999 fill."""
    stamps = pd.date_range(start, end, freq="h")
    lines = [
        "-BEGIN HEADER-",
        "NASA POWER API",
        "Parameters: T2M, RH2M, WS10M, ALLSKY_SFC_SW_DWN",
        "-END HEADER-",
        # canonical POWER column order (NOT the request order)
        "YEAR,MO,DY,HR,ALLSKY_SFC_SW_DWN,RH2M,T2M,WS10M",
    ]
    for s in stamps:
        vals = [ghi, rh, t2m, ws]
        if poison is not None and s == poison[0]:
            vals[poison[1]] = -999
        lines.append(
            f"{s.year},{s.month:02d},{s.day:02d},{s.hour:02d},"
            + ",".join(repr(v) for v in vals)
        )
    return "\n".join(lines) + "\n"


class _FakePowerResp:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


class _FakeOmResp:
    """Minimal Open-Meteo archive JSON over the padded window (zeros)."""

    def raise_for_status(self):
        pass

    def json(self):
        stamps = pd.date_range("2024-12-31", "2026-01-02", freq="h")
        n = len(stamps)
        return {"hourly": {
            "time": [s.strftime("%Y-%m-%dT%H:%M") for s in stamps],
            "temperature_2m": [10.0] * n,
            "relative_humidity_2m": [50.0] * n,
            "surface_pressure": [1013.25] * n,
            "shortwave_radiation": [0.0] * n,
            "direct_radiation": [0.0] * n,
            "diffuse_radiation": [0.0] * n,
        }}


class _Recorder:
    """requests.get stand-in that records every URL and replays a response."""

    def __init__(self, resp):
        self.resp = resp
        self.urls = []

    def __call__(self, url, *args, **kwargs):
        self.urls.append(str(url))
        return self.resp


def _write_weather_csv(path, stamps, ghi=100.0):
    """Minimal aligned city CSV (city-file schema) with a constant GHI."""
    rows = ["timestamp,temperature_2m,relative_humidity_2m,wind_speed_10m,"
            "shortwave_radiation,direct_radiation,diffuse_radiation"]
    for s in stamps:
        rows.append(f"{s},10.0,50.0,1.0,{ghi},0.0,0.0")
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def _year_stamps(year, n=8760):
    return [s.strftime("%Y-%m-%d %H:%M:%S")
            for s in pd.date_range(f"{year}-01-01", periods=n, freq="h")]


def _block_network(monkeypatch):
    def boom(*args, **kwargs):
        raise ConnectionError("round-22 test attempted a network fetch")

    monkeypatch.setattr(weather_bridge.requests, "get", boom)


# ── POWER CSV parsing ─────────────────────────────────────────────────────


def test_parse_power_csv_header_and_units():
    """Marker-based header skip + name-based mapping; the hourly ALLSKY
    value IS the mean W/m^2 (used verbatim, no x3600)."""
    df = weather_bridge._parse_power_csv(_power_csv_text())
    stamps = pd.date_range("2024-12-31", "2026-01-02", freq="h")
    assert len(df) == len(stamps)
    assert str(df["timestamp"].dtype).endswith("UTC]")  # tz-aware UTC
    assert df["timestamp"].iloc[0] == pd.Timestamp("2024-12-31 00:00:00", tz="UTC")
    # name-based mapping from POWER's canonical column order
    assert np.allclose(df["temperature_2m"], 12.5)
    assert np.allclose(df["relative_humidity_2m"], 70.0)
    assert np.allclose(df["wind_speed_10m"], 3.0)
    assert np.allclose(df["shortwave_radiation"], 500.0)  # W/m^2 as-is


def test_parse_power_csv_minus999_rejected_any_variable():
    """A single -999 fill in ANY variable of ANY row fails fast (ASCII)."""
    poison_ts = pd.Timestamp("2025-06-01 05:00")
    with pytest.raises(WeatherFetchError) as ei:
        weather_bridge._parse_power_csv(_power_csv_text(poison=(poison_ts, 1)))
    assert "-999" in str(ei.value)
    assert "2025-06-01T05" in str(ei.value)
    assert str(ei.value).isascii()


def test_parse_power_csv_missing_marker_and_columns():
    with pytest.raises(WeatherFetchError, match="END HEADER"):
        weather_bridge._parse_power_csv("YEAR,MO,DY,HR,T2M\n2025,1,1,0,1\n")
    with pytest.raises(WeatherFetchError, match="missing columns"):
        weather_bridge._parse_power_csv(
            "-END HEADER-\nYEAR,MO,DY,HR,T2M,RH2M\n2025,1,1,0,1,50\n"
        )


# ── provider routing (mocked transport, never online) ─────────────────────


def test_power_fetch_routes_url_attrs_and_alignment(monkeypatch, tmp_path):
    rec = _Recorder(_FakePowerResp(_power_csv_text()))
    monkeypatch.setattr(weather_bridge.requests, "get", rec)
    df = fetch_weather(
        lat=31.23, lon=121.47, year=2025, tz_hours=8.0,
        tilt=20.0, azimuth=180.0, cache_dir=tmp_path, force=True,
        provider="nasa-power",
    )
    assert len(rec.urls) == 1
    url = rec.urls[0]
    assert url.startswith("https://power.larc.nasa.gov/api/temporal/hourly/point?")
    for fragment in (
        "parameters=T2M,RH2M,WS10M,ALLSKY_SFC_SW_DWN",
        "community=RE", "format=CSV", "time-standard=UTC",
        "latitude=31.23", "longitude=121.47",
    ):
        assert fragment in url
    # P4-16 parity: exactly 8760 local-year rows at tz=+8, starting Jan 1
    assert len(df) == 8760
    assert df.index[0] == pd.Timestamp("2025-01-01 00:00:00")
    assert df.index[-1] == pd.Timestamp("2025-12-31 23:00:00")
    assert df.index.tz is None  # naive local wall time (cache format)
    assert np.allclose(df["shortwave_radiation"], 500.0)
    assert df.attrs["weather_source"] == "NASA POWER hourly (MERRA-2/CERES)"
    assert df.attrs["weather_source_detail"] == "power.larc.nasa.gov"
    assert df.attrs["ghi_scale"] == 1.0


def test_default_provider_still_routes_open_meteo(monkeypatch, tmp_path):
    """Zero drift at the routing layer: provider unset == open-meteo."""
    rec = _Recorder(_FakeOmResp())
    monkeypatch.setattr(weather_bridge.requests, "get", rec)
    df = fetch_weather(
        lat=31.23, lon=121.47, year=2025, tz_hours=8.0,
        tilt=20.0, azimuth=180.0, cache_dir=tmp_path, force=True,
    )
    assert len(rec.urls) == 1
    assert "archive-api.open-meteo.com" in rec.urls[0]
    assert df.attrs["weather_source"] == "live fetch"
    assert df.attrs["weather_source_detail"] == "archive-api.open-meteo.com"


def test_unknown_provider_rejected(monkeypatch, tmp_path):
    with pytest.raises(WeatherFetchError, match="provider"):
        fetch_weather(lat=0.0, lon=0.0, year=2025, cache_dir=tmp_path,
                      provider="noaa")


# ── cache key namespacing (no cross-source hits) ──────────────────────────


def test_cache_key_power_suffix_no_cross_contamination(monkeypatch, tmp_path):
    """Same coordinates, two sources -> two distinct cache files; each later
    run (network blocked) hits ITS OWN file with ITS OWN values."""
    monkeypatch.setattr(
        weather_bridge.requests, "get",
        _Recorder(_FakePowerResp(_power_csv_text())),
    )
    dfp = fetch_weather(lat=31.23, lon=121.47, year=2025, tz_hours=8.0,
                        cache_dir=tmp_path, force=True, provider="nasa-power")
    monkeypatch.setattr(
        weather_bridge.requests, "get", _Recorder(_FakeOmResp()),
    )
    dfo = fetch_weather(lat=31.23, lon=121.47, year=2025, tz_hours=8.0,
                        cache_dir=tmp_path, force=True)
    names = {p.name for p in tmp_path.glob("weather_*.csv")}
    assert names == {_POWER_CACHE_NAME, _OM_CACHE_NAME}

    _block_network(monkeypatch)
    for provider, expect_ghi, expect_detail in (
        ("nasa-power", 500.0, _POWER_CACHE_NAME),
        ("open-meteo", 0.0, _OM_CACHE_NAME),
    ):
        kwargs = {"provider": provider} if provider != "open-meteo" else {}
        df = fetch_weather(lat=31.23, lon=121.47, year=2025, tz_hours=8.0,
                           cache_dir=tmp_path, **kwargs)
        assert df.attrs["weather_source"] == "cache"
        assert df.attrs["weather_source_detail"] == expect_detail
        assert np.allclose(df["shortwave_radiation"], expect_ghi)
    assert dfp.attrs["weather_source_detail"] == "power.larc.nasa.gov"
    assert dfo.attrs["weather_source_detail"] == "archive-api.open-meteo.com"


def test_power_run_never_adopts_legacy_open_meteo_cache(monkeypatch, tmp_path):
    """A pre-P6-1 legacy cache (open-meteo-era name) must not be adopted by
    a NASA POWER run: the POWER fetch happens even when the legacy file
    exists (mocked response answers; a silent adoption would never call)."""
    legacy = tmp_path / "weather_31.230_121.470_2025.csv"
    _write_weather_csv(legacy, _year_stamps(2025), ghi=123.0)
    rec = _Recorder(_FakePowerResp(_power_csv_text()))
    monkeypatch.setattr(weather_bridge.requests, "get", rec)
    df = fetch_weather(lat=31.23, lon=121.47, year=2025, tz_hours=8.0,
                       cache_dir=tmp_path, force=False, provider="nasa-power")
    assert len(rec.urls) == 1  # live POWER fetch happened
    assert np.allclose(df["shortwave_radiation"], 500.0)  # POWER values


# ── city path: {City}_{year}_power.csv ────────────────────────────────────


def test_city_power_file_used_only_by_power_provider(monkeypatch, tmp_path):
    root_path = tmp_path / "root"
    (root_path / "data" / "weather").mkdir(parents=True)
    f = root_path / "data" / "weather" / "TestCity_2025_power.csv"
    _write_weather_csv(f, _year_stamps(2025), ghi=100.0)
    monkeypatch.setattr(
        weather_bridge, "_find_city_csv",
        lambda city, year, provider="open-meteo", root=None:
        _find_city_csv_via(root_path, city, year, provider),
    )
    import warnings as _w

    with _w.catch_warnings():
        _w.simplefilter("error")  # aligned file must load silently
        df = fetch_weather(lat=31.23, lon=121.47, year=2025, tz_hours=8.0,
                           cache_dir=tmp_path, city="TestCity",
                           provider="nasa-power")
    assert df.attrs["weather_source"] == "pre-downloaded city file"
    assert df.attrs["weather_source_detail"] == "TestCity_2025_power.csv"
    assert np.allclose(df["shortwave_radiation"], 100.0)

    # open-meteo must NOT pick up the _power file: city lookup misses ->
    # lat/lon path -> network blocked -> E003 (fail fast, no cross-source).
    _block_network(monkeypatch)
    with pytest.raises(WeatherFetchError):
        fetch_weather(lat=31.23, lon=121.47, year=2025, tz_hours=8.0,
                      cache_dir=tmp_path, city="TestCity")


def _find_city_csv_via(root, city, year, provider):
    return _real_find_city_csv(city, year, provider=provider, root=root)


def test_find_city_csv_provider_naming(tmp_path):
    (tmp_path / "data" / "weather").mkdir(parents=True)
    power_file = tmp_path / "data" / "weather" / "CityX_2025_power.csv"
    om_file = tmp_path / "data" / "weather" / "CityX_2025.csv"
    assert weather_bridge._find_city_csv("CityX", 2025, provider="nasa-power",
                                         root=tmp_path) is None
    power_file.write_text("x\n", encoding="utf-8")
    found = weather_bridge._find_city_csv("CityX", 2025, provider="nasa-power",
                                          root=tmp_path)
    assert found is not None and found.name == "CityX_2025_power.csv"
    # the open-meteo name is still invisible to the power provider...
    om_file.write_text("x\n", encoding="utf-8")
    assert (weather_bridge._find_city_csv("CityX", 2025, provider="nasa-power",
                                          root=tmp_path).name
            == "CityX_2025_power.csv")
    # ...and the power name is invisible to open-meteo
    assert (weather_bridge._find_city_csv("CityX", 2025, root=tmp_path).name
            == "CityX_2025.csv")


# ── ghi_scale multiplier ──────────────────────────────────────────────────


def test_ghi_scale_scales_radiation_field_and_attrs(monkeypatch, tmp_path):
    rec = _Recorder(_FakePowerResp(_power_csv_text()))
    monkeypatch.setattr(weather_bridge.requests, "get", rec)
    raw = fetch_weather(lat=31.23, lon=121.47, year=2025, tz_hours=8.0,
                        cache_dir=tmp_path / "c1", force=True,
                        provider="nasa-power")
    scaled = fetch_weather(lat=31.23, lon=121.47, year=2025, tz_hours=8.0,
                           cache_dir=tmp_path / "c2", force=True,
                           provider="nasa-power", ghi_scale=0.9)
    assert scaled.attrs["ghi_scale"] == 0.9
    assert raw.attrs["ghi_scale"] == 1.0
    for col in ("shortwave_radiation", "direct_radiation",
                "diffuse_radiation", "poa_radiation"):
        # POA/PV/annual-GHI downstream all scale by exactly the factor
        assert np.allclose(scaled[col].to_numpy(), 0.9 * raw[col].to_numpy())
    assert abs(
        scaled["shortwave_radiation"].sum() - 0.9 * raw["shortwave_radiation"].sum()
    ) < 1e-6
    # the on-disk cache stays UNSCALED (scale is a run-time knob)
    cached = pd.read_csv(tmp_path / "c2" / _POWER_CACHE_NAME)
    assert np.allclose(cached["shortwave_radiation"], 500.0)


def test_ghi_scale_on_city_path_and_default_records_one(tmp_path, monkeypatch):
    root_path = tmp_path / "root"
    (root_path / "data" / "weather").mkdir(parents=True)
    _write_weather_csv(root_path / "data" / "weather" / "TestCity_2025.csv",
                       _year_stamps(2025), ghi=100.0)
    monkeypatch.setattr(
        weather_bridge, "_find_city_csv",
        lambda city, year, provider="open-meteo", root=None:
        _find_city_csv_via(root_path, city, year, provider),
    )
    import warnings as _w

    with _w.catch_warnings():
        _w.simplefilter("error")
        df = fetch_weather(lat=31.23, lon=121.47, year=2025, tz_hours=8.0,
                           cache_dir=tmp_path, city="TestCity")  # no scale
        assert np.allclose(df["shortwave_radiation"], 100.0)
        assert df.attrs["ghi_scale"] == 1.0
        df9 = fetch_weather(lat=31.23, lon=121.47, year=2025, tz_hours=8.0,
                            cache_dir=tmp_path, city="TestCity", ghi_scale=0.9)
        assert np.allclose(df9["shortwave_radiation"], 90.0)
        assert df9.attrs["ghi_scale"] == 0.9
        # POA scales by the same factor (proportional radiation scaling)
        assert np.allclose(df9["poa_radiation"].to_numpy(),
                           0.9 * df["poa_radiation"].to_numpy())


# ── config guards (E001 at load time) ─────────────────────────────────────


def test_siteconfig_and_preset_defaults():
    s = SiteConfig()
    assert s.weather_provider == "open-meteo"
    assert s.ghi_scale == 1.0
    for preset in (preset_609(), preset_default()):
        assert preset.site.weather_provider == "open-meteo"
        assert preset.site.ghi_scale == 1.0


def test_config_provider_enum():
    with pytest.raises(ValueError, match="weather_provider"):
        DesignProject.from_dict({"site": {"weather_provider": "noaa"}})
    p = DesignProject.from_dict({"site": {"weather_provider": "nasa-power"}})
    assert p.site.weather_provider == "nasa-power"


def test_config_ghi_scale_band():
    for bad in (0.5, 0.0, -1.0, 1.500001):
        with pytest.raises(ValueError, match="ghi_scale"):
            DesignProject.from_dict({"site": {"ghi_scale": bad}})
    with pytest.raises(ValueError, match="ghi_scale"):
        DesignProject.from_dict({"site": {"ghi_scale": "big"}})
    assert DesignProject.from_dict({"site": {"ghi_scale": 1.5}}).site.ghi_scale == 1.5
    assert DesignProject.from_dict({"site": {"ghi_scale": 0.873}}).site.ghi_scale == 0.873
