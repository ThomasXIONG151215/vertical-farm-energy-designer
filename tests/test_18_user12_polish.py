"""
Layer 18: user12 cold-start fix batch, commit B (T3/T4/T5/T6/T7).

* T4  ``design new`` templates omit placeholder canonical sizing keys, so
      adding a datasheet alias from the README tutorial can no longer trip
      the Ambiguous double-spec error; genuine double-spec rejection and its
      new placeholder hint are pinned too.
* T5  the legacy-cache POA-recompute notice fires exactly once per process
      (fetch level and sweep level), carries the cache filename + a refetch
      action, and never a .py source path; pure ASCII.
* T6  ``evaluate`` prints a first-class RH compliance KPI line, silently
      skipped when the summary lacks the keys.
* P2-1 evaluate announces "Resolving weather" (cache/city hits don't fetch).
* P2-4 ``design cities`` lists lat/lon/tz columns.
* P2-5 a pre-downloaded city hit writes NOTHING into the --cache directory.
"""
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

SRC = Path(__file__).resolve().parents[1] / "vfed"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from vfed.cli import main
from vfed.design.presets import preset_609
from vfed.design.project import DesignProject


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _generate_template(tmp_path, name="t"):
    out = tmp_path / f"{name}.yaml"
    assert main(["design", "new", name, "--preset", "609", "--out", str(out)]) == 0
    return out


def _legacy_cache_csv(cache_dir: Path, lat=30.0, lon=120.0, year=2025) -> Path:
    """Write a pre-P6-1 legacy cache (tilt/azimuth/tz NOT in the filename,
    poa_radiation column present, aligned local-year window)."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    idx = pd.date_range(f"{year}-01-01", periods=(365 + int(year % 4 == 0)) * 24, freq="h")
    df = pd.DataFrame(
        {
            "timestamp": idx,
            "shortwave_radiation": np.full(len(idx), 100.0),
            "poa_radiation": np.full(len(idx), 120.0),
            "direct_radiation": np.full(len(idx), 60.0),
            "diffuse_radiation": np.full(len(idx), 60.0),
        }
    )
    path = cache_dir / f"weather_{lat:.3f}_{lon:.3f}_{year}.csv"
    df.to_csv(path, index=False)
    return path


@pytest.fixture()
def reset_legacy_notice():
    """The T5 dedup state is process-global; tests start from a clean slate
    and leave it clean (the sentinel stays set afterwards, as in production)."""
    from vfed.weather import weather_bridge as wb

    wb._LEGACY_CACHE_NOTICE_SENT.clear()
    yield
    wb._LEGACY_CACHE_NOTICE_SENT.clear()


# ---------------------------------------------------------------------------
# T4  template placeholders / alias tutorial
# ---------------------------------------------------------------------------
PLACEHOLDER_CANONICALS = {
    "hvac": ["Q_cool_nom", "cop_value", "P_rated_w"],
    "deh": ["M_deh_nom", "P_ref_w"],
}


def test_template_omits_placeholder_alias_keys(tmp_path):
    """user12 T4: every alias-target canonical key that sits at its dataclass
    default is omitted from the generated template."""
    out = _generate_template(tmp_path)
    raw = yaml.safe_load(out.read_text(encoding="utf-8"))
    for section, keys in PLACEHOLDER_CANONICALS.items():
        for key in keys:
            assert key not in raw[section], (
                f"placeholder {section}.{key} must not be written into the "
                f"template (users adding the datasheet alias would trip the "
                f"ambiguous double-spec error)"
            )


def test_template_add_alias_keys_loads_clean(tmp_path):
    """The README §3 flow on a fresh template: add datasheet keys, load OK,
    values land on the canonical fields (previously an Ambiguous error)."""
    out = _generate_template(tmp_path)
    text = out.read_text(encoding="utf-8")
    text = text.replace(
        "deh:\n", "deh:\n  capacity_l_per_day: 30\n  power_w: 260\n", 1
    )
    text = text.replace(
        "hvac:\n",
        "hvac:\n  cooling_capacity_kw: 3.5\n  cop: 3.2\n  power_w: 1200\n",
        1,
    )
    out.write_text(text, encoding="utf-8")
    p = DesignProject.load(out)
    assert p.deh.M_deh_nom == pytest.approx(30.0)
    assert p.deh.P_ref_w == pytest.approx(260.0)
    assert p.hvac.Q_cool_nom == pytest.approx(3.5)
    assert p.hvac.cop_value == pytest.approx(3.2)
    assert p.hvac.P_rated_w == pytest.approx(1200.0)


def test_template_roundtrip_defaults_unchanged(tmp_path):
    """Stripping placeholders must not change the loaded configuration."""
    out = _generate_template(tmp_path)
    p = DesignProject.load(out)
    ref = preset_609()
    assert p.deh.M_deh_nom == ref.deh.M_deh_nom
    assert p.deh.P_ref_w == ref.deh.P_ref_w
    assert p.hvac.cop_value == ref.hvac.cop_value
    assert p.hvac.P_rated_w == ref.hvac.P_rated_w


def test_double_explicit_different_values_still_ambiguous():
    """user12 T4: the old-style genuine conflict keeps failing fast."""
    with pytest.raises(ValueError, match="Ambiguous 'deh' config"):
        DesignProject.from_dict(
            {"deh": {"M_deh_nom": 5.0, "capacity_l_per_day": 30.0}}
        )


def test_ambiguous_message_names_placeholder_cause():
    with pytest.raises(ValueError) as exc:
        DesignProject.from_dict(
            {"deh": {"M_deh_nom": 0.0, "capacity_l_per_day": 30.0}}
        )
    msg = str(exc.value)
    assert "placeholder" in msg
    assert "delete the placeholder line" in msg
    assert msg.isascii()


def test_double_explicit_equal_values_collapse():
    p = DesignProject.from_dict(
        {"deh": {"M_deh_nom": 30.0, "capacity_l_per_day": 30.0}}
    )
    assert p.deh.M_deh_nom == pytest.approx(30.0)


# ---------------------------------------------------------------------------
# T5  legacy-cache notice: once per process, actionable, path-free, ASCII
# ---------------------------------------------------------------------------
def test_fetch_legacy_notice_once_per_process(tmp_path, reset_legacy_notice):
    from vfed.weather import weather_bridge as wb

    cache = tmp_path / "cache"
    path = _legacy_cache_csv(cache)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        wb.fetch_weather(30.0, 120.0, 2025, cache_dir=cache)
        wb.fetch_weather(30.0, 120.0, 2025, cache_dir=cache)
        wb.fetch_weather(30.0, 120.0, 2025, tilt=35.0, azimuth=200.0, cache_dir=cache)
    legacy = [
        w for w in caught
        if issubclass(w.category, UserWarning) and "Legacy weather cache" in str(w.message)
    ]
    assert len(legacy) == 1
    msg = str(legacy[0].message)
    assert path.name in msg                      # names the cache file
    assert "Delete the file to refetch" in msg   # actionable refetch guide
    assert ".py" not in msg                      # no source path
    assert msg.isascii()
    # the returned frame still carries recomputed POA (behaviour unchanged)
    df = wb.fetch_weather(30.0, 120.0, 2025, cache_dir=cache)
    assert "poa_radiation" in df.columns
    assert df.attrs["weather_source"] == "cache"


def test_sweep_precheck_single_notice_for_whole_run(tmp_path, monkeypatch, reset_legacy_notice):
    """A multi-config sweep emits the legacy notice exactly ONCE, up front --
    never once per enumerated row."""
    from vfed.design import sweep as sweep_mod

    cache = tmp_path / "cache"
    _legacy_cache_csv(cache, lat=30.0, lon=120.0, year=2025)

    project = preset_609()
    project.site.city = None
    project.site.lat, project.site.lon = 30.0, 120.0
    project.site.year = 2025
    project.space.parameter_ranges = {"T_light": [20.0, 22.0, 1.0]}  # 3 configs

    class _StubSim:
        summary = {"annual_water_m3": 10.0}

        def __getitem__(self, key):
            return {
                "kwh_per_kg_fresh": 10.0,
                "annual_load_kwh": 1000.0,
                "biomass_kg": 20.0,
                "load": np.full(24, 1.0),
                "weather": {"hour": np.arange(24)},
            }[key]

    class _StubEngine:
        def __init__(self, cache_dir=None):
            pass

        def run(self, project):
            return _StubSim()

    monkeypatch.setattr(sweep_mod, "DesignEngine", _StubEngine)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        sweep_mod.sweep_design(project, cache_dir=str(cache))
    legacy = [
        w for w in caught
        if issubclass(w.category, UserWarning) and "Legacy weather cache" in str(w.message)
    ]
    assert len(legacy) == 1
    assert str(legacy[0].message).isascii()

    # a second sweep in the same process stays fully silent (process-level
    # once semantics; the precheck consumes the same budget as the fetch)
    with warnings.catch_warnings(record=True) as caught2:
        warnings.simplefilter("always")
        sweep_mod.sweep_design(project, cache_dir=str(cache))
    assert not [
        w for w in caught2
        if issubclass(w.category, UserWarning) and "Legacy weather cache" in str(w.message)
    ]


def test_sweep_precheck_silent_without_legacy_cache(tmp_path, monkeypatch, reset_legacy_notice):
    from vfed.design import sweep as sweep_mod

    project = preset_609()
    project.site.city = None
    project.space.parameter_ranges = {"T_light": [20.0, 21.0, 1.0]}

    class _StubEngine:
        def __init__(self, cache_dir=None):
            pass

        def run(self, project):
            raise AssertionError("engine must not run in this precheck test")

    monkeypatch.setattr(sweep_mod, "DesignEngine", _StubEngine)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        sweep_mod._precheck_legacy_cache_notice(project, str(tmp_path / "empty_cache"))
    assert not [
        w for w in caught if issubclass(w.category, UserWarning)
    ]


# ---------------------------------------------------------------------------
# T6  RH compliance console KPI
# ---------------------------------------------------------------------------
class _StubResultRH:
    def __init__(self, summary):
        self.weather_attrs = {}
        self.summary = summary

    def get(self, key, default=None):
        if key == "load":
            return np.full(24, 1.0)
        return self.summary.get(key, default)


def _run_evaluate_with_summary(tmp_path, monkeypatch, capsys, summary):
    from vfed import cli as cli_mod

    out = tmp_path / "farm.yaml"
    assert main(["design", "new", "farm", "--preset", "609", "--out", str(out)]) == 0

    class _Engine:
        def __init__(self, cache_dir=None):
            pass

        def run(self, project):
            return _StubResultRH(summary)

    monkeypatch.setattr(cli_mod, "DesignEngine", _Engine)
    rc = main(["evaluate", str(out), "--cache", "weather_cache"])
    return rc, capsys.readouterr()


def test_rh_compliance_line_printed(tmp_path, monkeypatch, capsys):
    summary = {
        "lcoe": None,
        "capital_total": None,
        "rh_setpoint_pct": 70.0,
        "rh_exceed_hours": 155,
        "rh_exceed_pct": 0.0177,
        "rh_p95_pct": 71.2,
        "rh_max_pct": 76.3,
    }
    rc, out = _run_evaluate_with_summary(tmp_path, monkeypatch, capsys, summary)
    assert rc == 0
    line = [ln for ln in out.out.splitlines() if "RH compliance" in ln]
    assert len(line) == 1
    assert (
        "98.2% hours within setpoint (exceed 155 h, p95 71.20%, max 76.30%, setpoint 70%)"
        in line[0]
    )
    assert line[0].isascii()
    assert not line[0].strip().startswith("[WARNING]")  # KPI style, not a warning


def test_rh_compliance_line_skipped_without_keys(tmp_path, monkeypatch, capsys):
    summary = {"lcoe": None, "capital_total": None}
    rc, out = _run_evaluate_with_summary(tmp_path, monkeypatch, capsys, summary)
    assert rc == 0
    assert "RH compliance" not in out.out


# ---------------------------------------------------------------------------
# P2-1  "Resolving weather" wording
# ---------------------------------------------------------------------------
def test_evaluate_says_resolving_not_fetching(tmp_path, monkeypatch, capsys):
    summary = {"lcoe": None, "capital_total": None}
    rc, out = _run_evaluate_with_summary(tmp_path, monkeypatch, capsys, summary)
    assert rc == 0
    assert "Resolving weather for" in out.err
    assert "Fetching weather for" not in out.err


# ---------------------------------------------------------------------------
# P2-4  cities list carries coordinates
# ---------------------------------------------------------------------------
def test_cities_list_has_coords_columns(capsys):
    main(["design", "cities"])  # _cmd_cities returns None, like the other listings
    out = capsys.readouterr().out
    assert out.isascii()
    sh = [ln for ln in out.splitlines() if ln.strip().startswith("Shanghai")][0]
    assert "31.23" in sh and "121.47" in sh and "UTC+8" in sh
    ld = [ln for ln in out.splitlines() if ln.strip().startswith("London")][0]
    assert "51.51" in ld and "-0.13" in ld and "UTC+0" in ld


# ---------------------------------------------------------------------------
# P2-5  city hit: no cache side effects
# ---------------------------------------------------------------------------
def test_city_hit_writes_nothing_to_cache_dir(tmp_path):
    """A pre-downloaded city hit must leave the --cache directory untouched
    (previously it silently materialised a lat/lon cache entry)."""
    from vfed.weather import weather_bridge as wb

    fresh = tmp_path / "brand_new_cache_dir"
    df = wb.fetch_weather(
        31.23, 121.47, 2025, tilt=20.0, azimuth=180.0,
        cache_dir=fresh, city="Shanghai",
    )
    assert not fresh.exists(), "city hit must not create the cache directory"
    assert df.attrs["weather_source"] == "pre-downloaded city file"


def test_design_new_latlon_warn_explains_priority(tmp_path, monkeypatch, capsys):
    """user12 T3: the clearing warning says why (explicit coordinates take
    priority) and how the coordinates will be used."""
    monkeypatch.chdir(tmp_path)
    rc = main(["design", "new", "nyc", "--preset", "609", "--lat", "40.71",
               "--lon", "-74.01", "--year", "2025"])
    assert rc == 0
    err = capsys.readouterr().err
    assert "clearing preset city" in err
    assert "take priority" in err
    assert "weather cache key" in err
    assert err.isascii()
