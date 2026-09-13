"""P2-2: weather source provenance (self-evidence).

Pins the ``df.attrs`` metadata contract added to ``fetch_weather``:

* pre-downloaded city CSV path  -> ``weather_source = "pre-downloaded city
  file"`` + the data file name as detail;
* lat/lon ``weather_cache/`` hit -> ``weather_source = "cache"`` + the cache
  file name as detail;
* Open-Meteo live fetch         -> ``weather_source = "live fetch"`` + the
  API host as detail (host only -- no query string, no credentials);
* attrs are metadata only: the ``to_csv`` round-trip header and the returned
  column set are unchanged, so no CSV schema can drift from the provenance;
* DesignEngine relays the attrs into ``SimulationResult.weather_attrs`` with
  the physics baselines bitwise untouched (six-value pin below);
* ``vfed evaluate`` prints the pure-ASCII normal-style self-evidence line
  (cache reads as "cache hit"); attrs absent -> no line, no warning; the
  sweep console output never prints it (a 100-row sweep must not flood).
"""

import io
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

SRC = Path(__file__).resolve().parents[1] / "vfed"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from vfed.cli import main, _print_weather_source  # noqa: E402
from vfed.design.engine import DesignEngine  # noqa: E402
from vfed.design.presets import preset_609  # noqa: E402
from vfed.weather import weather_bridge  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parents[1]
_REPO_CACHE = _REPO_ROOT / "weather_cache"

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


def _block_network(monkeypatch):
    """Offline guard: any accidental network attempt fails fast instead of
    hanging the suite (cache/city paths must never need it)."""

    def boom(*args, **kwargs):
        raise ConnectionError("P2-2 test attempted a network fetch")

    monkeypatch.setattr(weather_bridge.requests, "get", boom)


# ── attrs: pre-downloaded city file path ──────────────────────────────────


def test_city_path_attrs(tmp_path, monkeypatch):
    """Synthetic aligned city file -> source + filename detail."""
    f = tmp_path / "TestCity_2025.csv"
    _write_weather_csv(f, _year_stamps(2025))
    monkeypatch.setattr(weather_bridge, "_find_city_csv", lambda city, year: f)
    import warnings as _w

    with _w.catch_warnings():
        _w.simplefilter("error")  # aligned file must load silently
        df = weather_bridge.fetch_weather(
            lat=31.23, lon=121.47, year=2025, tz_hours=8.0,
            tilt=20.0, azimuth=180.0, cache_dir=tmp_path, city="TestCity",
        )
    assert df.attrs["weather_source"] == "pre-downloaded city file"
    assert df.attrs["weather_source_detail"] == "TestCity_2025.csv"


def test_city_path_attrs_real_shanghai_file():
    """Real bundled offline data path: data/weather/Shanghai_2025.csv via the
    repo-root cache (fully offline; the lat/lon cache key already exists so
    nothing is written)."""
    df = weather_bridge.fetch_weather(
        lat=31.23, lon=121.47, year=2025, tz_hours=8.0,
        tilt=20.0, azimuth=180.0, cache_dir=_REPO_CACHE, city="Shanghai",
    )
    assert df.attrs["weather_source"] == "pre-downloaded city file"
    assert df.attrs["weather_source_detail"] == "Shanghai_2025.csv"


# ── attrs: lat/lon cache hit path ─────────────────────────────────────────


def test_cache_path_attrs_real_repo_cache(monkeypatch):
    """The repo-root tilt-aware cache file reports the cache hit + its cache
    key (file name).  Network is blocked so a stale/missing cache would fail
    fast instead of silently fetching."""
    _block_network(monkeypatch)
    df = weather_bridge.fetch_weather(
        lat=31.23, lon=121.47, year=2025, tz_hours=8.0,
        tilt=20.0, azimuth=180.0, cache_dir=_REPO_CACHE,
    )
    assert df.attrs["weather_source"] == "cache"
    assert df.attrs["weather_source_detail"] == (
        "weather_31.230_121.470_2025_t20.000_a180.000_z8.000.csv"
    )


# ── attrs: live fetch path (mocked transport, never online) ───────────────


class _FakeResp:
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


def test_live_fetch_attrs(monkeypatch, tmp_path):
    monkeypatch.setattr(weather_bridge.requests, "get", lambda *a, **k: _FakeResp())
    df = weather_bridge.fetch_weather(
        lat=40.71, lon=-74.01, year=2025, tz_hours=-5.0,
        tilt=20.0, azimuth=180.0, cache_dir=tmp_path, force=True,
    )
    assert len(df) == 8760  # fetch itself still aligns to the local year
    assert df.attrs["weather_source"] == "live fetch"
    # host only -- no query string, no credentials in the detail
    assert df.attrs["weather_source_detail"] == "archive-api.open-meteo.com"


# ── attrs are metadata only: CSV round-trip unchanged ─────────────────────


def test_attrs_do_not_leak_into_csv_roundtrip(tmp_path, monkeypatch):
    """The provenance must not alter to_csv output: no weather_source header,
    identical column set on re-read (regression pin against schema drift)."""
    f = tmp_path / "TestCity_2025.csv"
    _write_weather_csv(f, _year_stamps(2025))
    monkeypatch.setattr(weather_bridge, "_find_city_csv", lambda city, year: f)
    df = weather_bridge.fetch_weather(
        lat=31.23, lon=121.47, year=2025, tz_hours=8.0,
        tilt=20.0, azimuth=180.0, cache_dir=tmp_path, city="TestCity",
    )
    buf = io.StringIO()
    df.to_csv(buf)
    header = buf.getvalue().splitlines()[0]
    assert "weather_source" not in header
    back = pd.read_csv(io.StringIO(buf.getvalue()), parse_dates=["timestamp"]).set_index("timestamp")
    assert list(back.columns) == list(df.columns)


# ── engine relay + physics zero-drift (six-value baseline pin) ────────────


@pytest.fixture(scope="module")
def sim_city_baseline():
    """preset 609 @ bundled Shanghai 2025 city file (same run feeds the
    provenance relay check and the authoritative six-value baseline)."""
    p = preset_609()
    p.site.lat = 31.23
    p.site.lon = 121.47
    p.site.city = "Shanghai"
    p.site.year = 2025
    return DesignEngine(cache_dir=str(_REPO_CACHE)).run(p)


def test_engine_carries_weather_attrs(sim_city_baseline):
    r = sim_city_baseline
    assert r.weather_attrs["weather_source"] == "pre-downloaded city file"
    assert r.weather_attrs["weather_source_detail"] == "Shanghai_2025.csv"


def test_engine_baseline_six_values_unchanged(sim_city_baseline):
    """Physics zero-drift pin: the P1-3b aligned-window authoritative
    baseline must hold bitwise on the rounded summary values."""
    s = sim_city_baseline.summary
    assert s["annual_energy_kwh"] == 62444.50
    assert s["specific_energy_kwh_per_kg"] == 31.0499
    assert s["annual_harvest_kg"] == 100.55
    assert s["annual_water_m3"] == 10.37
    assert s["annual_grid_cost_net"] == 6244.45
    assert s["lcoe"] == 0.6608


def test_engine_caller_weather_without_attrs_degrades_to_empty():
    """A caller-supplied weather df carries no provenance: engine relays an
    empty dict and nothing downstream may warn about it."""
    df = pd.DataFrame(
        {
            "temperature_2m": [10.0] * 24,
            "relative_humidity_2m": [50.0] * 24,
            "surface_pressure": [1013.25] * 24,
            "shortwave_radiation": [0.0] * 24,
            "direct_radiation": [0.0] * 24,
            "diffuse_radiation": [0.0] * 24,
        },
        index=pd.date_range("2025-01-01", periods=24, freq="h"),
    )
    engine = DesignEngine(cache_dir=str(_REPO_CACHE))
    p = preset_609()
    result = engine.run(p, weather=df)
    assert result.weather_attrs == {}


# ── CLI self-evidence line ────────────────────────────────────────────────


def test_print_weather_source_labels(capsys):
    """All three variants + detail-less + absent-attrs skip (helper level)."""
    _print_weather_source(SimpleNamespace(weather_attrs={
        "weather_source": "pre-downloaded city file",
        "weather_source_detail": "Shanghai_2025.csv",
    }))
    assert capsys.readouterr().out == (
        "  Weather source  : pre-downloaded city file (Shanghai_2025.csv)\n"
    )
    _print_weather_source(SimpleNamespace(weather_attrs={
        "weather_source": "cache",
        "weather_source_detail": "weather_31.230_121.470_2025_t20.000_a180.000_z8.000.csv",
    }))
    out = capsys.readouterr().out
    assert out == (
        "  Weather source  : cache hit "
        "(weather_31.230_121.470_2025_t20.000_a180.000_z8.000.csv)\n"
    )
    _print_weather_source(SimpleNamespace(weather_attrs={
        "weather_source": "live fetch",
        "weather_source_detail": "api.open-meteo.com",
    }))
    assert capsys.readouterr().out == "  Weather source  : live fetch (api.open-meteo.com)\n"
    # no detail -> bare label; attrs absent/empty -> silent skip, no warning
    _print_weather_source(SimpleNamespace(weather_attrs={"weather_source": "live fetch"}))
    assert capsys.readouterr().out == "  Weather source  : live fetch\n"
    _print_weather_source(SimpleNamespace(weather_attrs={}))
    assert capsys.readouterr().out == ""
    _print_weather_source(SimpleNamespace())
    assert capsys.readouterr().out == ""
    # every printed line is pure ASCII (P2-1 regime)
    for line in capsys.readouterr().out.splitlines():
        assert line.isascii()


@pytest.fixture(scope="module")
def cli_project_yaml(tmp_path_factory):
    d = tmp_path_factory.mktemp("p22_cli")
    out = d / "farm_city.yaml"
    rc = main(["design", "new", "farm", "--preset", "609", "--out", str(out)])
    assert rc == 0
    return out


def test_cli_evaluate_prints_city_source(cli_project_yaml, capsys):
    rc = main(["evaluate", str(cli_project_yaml), "--cache", str(_REPO_CACHE)])
    out = capsys.readouterr().out
    assert rc == 0
    line = "  Weather source  : pre-downloaded city file (Shanghai_2025.csv)"
    assert line in out
    assert all(ch.isascii() for ch in line)


def test_cli_evaluate_prints_cache_source(cli_project_yaml, tmp_path, capsys):
    """city=None + lat/lon matching the repo cache -> the cache hit variant
    (the two P1-3b provenances are now visibly distinct on the console)."""
    from vfed.design.project import DesignProject

    p = DesignProject.load(cli_project_yaml)
    p.site.city = None
    p.site.lat = 31.23
    p.site.lon = 121.47
    p.site.year = 2025
    yaml_path = tmp_path / "farm_cache.yaml"
    p.save(yaml_path)
    rc = main(["evaluate", str(yaml_path), "--cache", str(_REPO_CACHE)])
    out = capsys.readouterr().out
    assert rc == 0
    assert (
        "  Weather source  : cache hit "
        "(weather_31.230_121.470_2025_t20.000_a180.000_z8.000.csv)"
    ) in out


def test_sweep_console_never_prints_source(cli_project_yaml, monkeypatch, capsys):
    """Sweep enumerates many rows: provenance stays in the attrs, the sweep
    console output must not repeat it."""
    from vfed import cli as cli_mod

    payload = {
        "success": True,
        "project": "synthetic",
        "currency": "USD",
        "exchange_rate": 1.0,
        "objective": "lcoe",
        "dry_matter_fraction": 0.05,
        "best": {
            "annual_load_kwh": 62444.5,
            "kwh_per_kg_fresh": 31.0,
            "biomass_kg": 100.5,
            "lcoe": 0.66,
            "capital_total": 0.0,
            "annual_om": 35021.0,
        },
        "results": None,
    }
    monkeypatch.setattr(cli_mod, "agent_evaluate", lambda path, cache_dir=None: payload)
    rc = cli_mod.main(["sweep", str(cli_project_yaml), "--cache", str(_REPO_CACHE)])
    assert rc == 0
    assert "Weather source" not in capsys.readouterr().out
