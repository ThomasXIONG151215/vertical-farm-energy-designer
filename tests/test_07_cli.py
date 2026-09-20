"""
Layer 7: CLI + weather/evaluator error-code contract tests.

Covers the batch-7 CLI hardening (P7-1..P7-15):

* ``design new``: default / explicit out path, overwrite warning, ``--city``
  coordinates carry the correct UTC offset (P7-10).
* ``evaluate``:   missing file -> E001; successful run.
* ``sweep``:      single-point ``--out`` writes a CSV (P7-4); ``--out`` into a
  missing directory returns 1 with a clean message, not a stack trace (P7-3).
* bare ``vfed``:  prints help and exits 2 instead of argparse's
  ``arguments required: cmd`` crash (P7-9).
* ``--help``:     parameters carry human-readable descriptions (P7-5).
* weather:        transport failures surface as ``WeatherFetchError`` (E003).
* evaluator:      ``WeatherFetchError`` -> E003 (P7-14); zero load -> E103.

End-to-end CLI cases run preset 609 (31.23, 121.47 = the city_db Shanghai
coordinates, 2025) against the disk cache, so they never touch the network.
"""
import sys
from pathlib import Path

import numpy as np
import pytest

# Add vfed to path for direct imports in tests
SRC = Path(__file__).resolve().parents[1] / "vfed"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from vfed.cli import main
from vfed.design.presets import preset_609


@pytest.fixture(scope="session")
def cli_project_yaml(tmp_path_factory):
    """``design new`` output for preset 609 (matches the disk-cached weather)."""
    d = tmp_path_factory.mktemp("cli")
    out = d / "farm.yaml"
    rc = main(["design", "new", "farm", "--preset", "609", "--out", str(out)])
    assert out.is_file()
    return out


# ---------------------------------------------------------------------------
# 7.1  design new
# ---------------------------------------------------------------------------
def test_design_new_default_out(tmp_path, monkeypatch):
    """No --out -> writes '<name>.yaml' in the current directory."""
    monkeypatch.chdir(tmp_path)
    rc = main(["design", "new", "myfarm", "--preset", "609"])
    assert (tmp_path / "myfarm.yaml").is_file()


def test_design_new_explicit_out(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rc = main(
        ["design", "new", "myfarm", "--preset", "609", "--out", str(tmp_path / "custom.yaml")]
    )
    assert (tmp_path / "custom.yaml").is_file()


def test_design_new_overwrite_warning(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "myfarm.yaml").write_text("existing\n")
    rc = main(["design", "new", "myfarm", "--preset", "609"])
    assert "overwriting" in capsys.readouterr().err.lower()


def test_design_new_city_coords(tmp_path, monkeypatch):
    """--city pulls the city's own UTC offset (Urumqi +6, not +8) — P7-10."""
    from vfed.design.project import DesignProject

    monkeypatch.chdir(tmp_path)
    rc = main(["design", "new", "uw", "--city", "Urumqi"])
    p = DesignProject.load(tmp_path / "uw.yaml")
    assert p.site.city == "Urumqi"
    assert p.site.tz_hours == 6.0


def test_design_new_latlon_clears_preset_city(tmp_path, monkeypatch, capsys):
    """CRITICAL-1: explicit --lat/--lon must clear the preset's hard-coded
    city so fetch_weather follows the given coordinates instead of silently
    simulating the preset city's climate."""
    from vfed.design.project import DesignProject

    monkeypatch.chdir(tmp_path)
    rc = main(
        [
            "design",
            "new",
            "nyc",
            "--preset",
            "609",
            "--lat",
            "40.71",
            "--lon",
            "-74.01",
            "--year",
            "2025",
        ]
    )
    assert rc == 0
    p = DesignProject.load(tmp_path / "nyc.yaml")
    assert p.site.city is None
    assert p.site.lat == pytest.approx(40.71)
    assert p.site.lon == pytest.approx(-74.01)
    assert "clearing preset city" in capsys.readouterr().err


def test_design_new_latlon_conflicts_city(tmp_path, monkeypatch, capsys):
    """CRITICAL-1: --city combined with --lat/--lon is ambiguous -> fail fast."""
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as exc:
        main(["design", "new", "x", "--preset", "609", "--city", "Shanghai", "--lat", "40.71"])
    assert exc.value.code == 1
    assert "cannot be combined" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# 7.2  evaluate
# ---------------------------------------------------------------------------
def test_evaluate_missing_file_e001(tmp_path, capsys):
    rc = main(["evaluate", str(tmp_path / "nope.yaml"), "--cache", "weather_cache"])
    assert rc == 1
    assert "E001" in capsys.readouterr().err


def test_evaluate_ok(cli_project_yaml, capsys):
    rc = main(["evaluate", str(cli_project_yaml), "--cache", "weather_cache"])
    out = capsys.readouterr()
    assert rc == 0
    assert "Annual load" in out.out
    # P0-4: the fixed preset must NOT trigger the full-load warning.
    assert "at rated capacity" not in out.out


def test_evaluate_full_load_warning_printed(cli_project_yaml, tmp_path, capsys):
    """P0-4: an unreachable dark setpoint (the pre-fix T_dark = 18 C, whose
    nights saturate the HVAC 2,920 h/yr) prints the rated-capacity WARNING
    in the same style as the capital = 0 warning."""
    from vfed.design.project import DesignProject

    p = DesignProject.load(cli_project_yaml)
    p.setpoints.T_dark = 18.0
    bad = tmp_path / "unreachable_dark.yaml"
    p.save(bad)
    rc = main(["evaluate", str(bad), "--cache", "weather_cache"])
    out = capsys.readouterr()
    assert rc == 0
    assert "[WARNING]" in out.out
    assert "HVAC cooling at rated capacity" in out.out
    assert "setpoint may be unreachable" in out.out


# ---------------------------------------------------------------------------
# 7.3  sweep
# ---------------------------------------------------------------------------
def test_sweep_single_point_out_csv(cli_project_yaml, tmp_path):
    out_csv = tmp_path / "sweep.csv"
    rc = main(["sweep", str(cli_project_yaml), "--cache", "weather_cache", "--out", str(out_csv)])
    assert rc == 0
    assert out_csv.is_file()
    assert "kwh_per_kg_fresh" in out_csv.read_text()


def test_sweep_out_missing_dir(cli_project_yaml, tmp_path, capsys):
    missing = tmp_path / "no_such_dir" / "out.csv"
    rc = main(["sweep", str(cli_project_yaml), "--cache", "weather_cache", "--out", str(missing)])
    assert rc == 1
    assert "cannot write" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# 7.4  bare command / help
# ---------------------------------------------------------------------------
def test_bare_vfed_prints_help_returns_2(capsys):
    rc = main([])
    assert rc == 2
    assert "usage" in capsys.readouterr().out.lower()


def test_help_describes_parameters(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["sweep", "--help"])
    assert exc.value.code == 0
    assert "CSV output file" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# 7.5  weather / evaluator error-code contract
# ---------------------------------------------------------------------------
def test_fetch_weather_connection_error_wrapped(monkeypatch, tmp_path):
    """Transport failure surfaces as WeatherFetchError, not a raw exception."""
    from vfed.weather import weather_bridge as wb

    def boom(*args, **kwargs):
        raise ConnectionError("simulated network outage")

    monkeypatch.setattr(wb.requests, "get", boom)
    with pytest.raises(wb.WeatherFetchError):
        wb.fetch_weather(30.9, 121.5, 2025, cache_dir=tmp_path, force=True)


def test_agent_evaluate_weather_error_e003(monkeypatch, tmp_path):
    from vfed.agent import evaluator
    from vfed.weather.weather_bridge import WeatherFetchError

    yaml = tmp_path / "p.yaml"
    preset_609().save(yaml)

    def boom(project, cache_dir=None):
        raise WeatherFetchError("network down")

    monkeypatch.setattr(evaluator, "sweep_design", boom)
    res = evaluator.agent_evaluate(str(yaml), cache_dir=str(tmp_path))
    assert res["success"] is False
    assert res["error_code"] == "E003"


def test_agent_simulate_zero_load_e103(monkeypatch):
    from vfed.agent import evaluator

    class ZeroLoadResult:
        def __getitem__(self, key):
            return {"load": np.zeros(24), "weather": {}, "timeseries": {}, "annual_load_kwh": 0.0}[
                key
            ]

        def get(self, key, default=None):
            if key in ("load", "weather", "timeseries", "annual_load_kwh"):
                return self[key]
            return default

    monkeypatch.setattr(evaluator.DesignEngine, "run", lambda self, project: ZeroLoadResult())
    res = evaluator.agent_simulate(preset_609())
    assert res["success"] is False
    assert res["error_code"] == "E103"


# ---------------------------------------------------------------------------
# 8.x  design new --tariff / validate subcommand (P8-9 / P8-11)
# ---------------------------------------------------------------------------
def test_design_new_tariff_shanghai(tmp_path, monkeypatch):
    from vfed.design.project import DesignProject

    monkeypatch.chdir(tmp_path)
    rc = main(["design", "new", "sh", "--preset", "609", "--tariff", "Shanghai"])
    assert rc == 0
    p = DesignProject.load(tmp_path / "sh.yaml")
    assert p.tariff.hourly_prices[8] == pytest.approx(1.0)
    assert p.tariff.export_price == pytest.approx(0.4155)


def test_design_new_tariff_unknown(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit):
        main(["design", "new", "x", "--preset", "609", "--tariff", "Mars"])
    assert "not found" in capsys.readouterr().err


def test_validate_missing_file_e001(tmp_path, capsys):
    rc = main(["validate", str(tmp_path / "nope.yaml")])
    assert rc == 1
    assert "E001" in capsys.readouterr().err


def test_validate_ok(cli_project_yaml, capsys):
    rc = main(["validate", str(cli_project_yaml)])
    out = capsys.readouterr()
    assert rc == 0
    assert "OK" in out.out


def test_validate_bad_key_e001(tmp_path, capsys):
    bad = tmp_path / "bad.yaml"
    bad.write_text("led:\n  ppfd_target: 400\n  bogus_key: 1\n")
    rc = main(["validate", str(bad)])
    assert rc == 1
    assert "E001" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# 7.6  Capital unit-price self-check output (P0-1)
# ---------------------------------------------------------------------------
def test_unit_price_line_format(capsys):
    """The self-check line shows the raw division (capital / rating = unit
    price) so the pricing basis can be verified by hand."""
    from vfed.cli import _print_unit_price

    _print_unit_price("  ", "PV unit cost", 162750.0, 46.5, "kWp", "RMB", extra=" (3.50 RMB/Wp)")
    out = capsys.readouterr().out
    assert "162750 RMB / 46.5 kWp" in out
    assert "3500.00 RMB/kWp" in out
    assert "(3.50 RMB/Wp)" in out


def test_unit_price_line_skips_zero_capital(capsys):
    from vfed.cli import _print_unit_price

    _print_unit_price("  ", "PV unit cost", 0.0, 46.5, "kWp", "RMB")
    assert capsys.readouterr().out == ""


def test_unit_price_line_skips_zero_rating(capsys):
    from vfed.cli import _print_unit_price

    _print_unit_price("  ", "PV unit cost", 50000.0, 0.0, "kWp", "RMB")
    assert capsys.readouterr().out == ""


def test_capital_unit_check_prints_pv_and_battery_lines(capsys):
    """A project priced per_kwp / per_kwh prints hand-checkable unit lines
    (pure config arithmetic - no weather or engine run needed)."""
    from vfed.cli import _print_capital_unit_check
    from vfed.design.project import DesignProject

    p = DesignProject.from_dict(
        {
            "pv": {"capital": {"mode": "per_kwp", "rate_per_kwp": 3500}},
            "battery": {"capital": {"mode": "per_kwh", "rate_per_kwh": 500}},
            "pv_area_m2": 200.0,  # 200 / 4.3 = 46.5 kWp
            "battery_kwh": 40.0,
        }
    )
    _print_capital_unit_check(p, "RMB")
    out = capsys.readouterr().out
    assert "3500.00 RMB/kWp" in out
    assert "(3.50 RMB/Wp)" in out
    assert "500.00 RMB/kWh" in out


# ---------------------------------------------------------------------------
# 7.7  Sweep guardrails: LCOE / capital=0 warning / boundary hint (P0-5)
# ---------------------------------------------------------------------------
def test_sweep_single_point_prints_lcoe_om_and_zero_capital_warning(cli_project_yaml, capsys):
    """P0-5 A: a single-point sweep must surface the LCOE, annual OPEX and,
    because preset 609 carries no capital blocks (capital_total = 0), the same
    OPEX-only warning the evaluate path prints (previously CSV-only)."""
    rc = main(["sweep", str(cli_project_yaml), "--cache", "weather_cache"])
    out = capsys.readouterr()
    assert rc == 0
    assert "LCOE" in out.out
    assert "annual_om" in out.out
    assert "Capital total" in out.out
    assert "all capital costs are zero" in out.out
    assert "OPEX only" in out.out


def _synthetic_sweep_payload(rows, best):
    """Build an agent_evaluate-shaped payload without running the engine —
    the sweep CLI only formats this dict, so tests can pin exact outputs."""
    import pandas as pd

    return {
        "success": True,
        "project": "synthetic",
        "currency": "USD",
        "exchange_rate": 1.0,
        "objective": "lcoe",
        "dry_matter_fraction": 0.05,
        "best": best,
        "results": pd.DataFrame(rows),
    }


def test_sweep_best_prints_annual_om_and_boundary_hints(cli_project_yaml, monkeypatch, capsys):
    """P0-5 B/C: the multi-point best block must print annual_om and flag an
    optimum pinned at a scan-range boundary.  pv_area = 200 caps its [0, 200]
    grid and battery = 40 caps its [0, 40] grid (two hints), while the
    interior T_light axis stays silent."""
    from vfed import cli as cli_mod

    def row(t_light, pv, bat, lcoe):
        return {
            "T_light": t_light,
            "currency": "USD",
            "pv_area": pv,
            "battery_kwh": bat,
            "lcoe": lcoe,
            "cost_per_kg_fresh": lcoe * 10.0,
            "kwh_per_kg_fresh": 13.0,
            "capital_total": 182791.0,
            "capital_pv": 162791.0,
            "capital_battery": 20000.0,
            "annual_capital": 15000.0,
            "annual_om": 35000.0,
            "annual_grid_cost": 6000.0,
            "annual_load_kwh": 66000.0,
            "biomass_kg": 250.0,
        }

    rows = [
        row(20.0, 0.0, 0.0, 0.90),
        row(21.0, 200.0, 40.0, 0.73),
        row(22.0, 100.0, 20.0, 0.80),
    ]
    monkeypatch.setattr(
        cli_mod,
        "agent_evaluate",
        lambda path, cache_dir=None: _synthetic_sweep_payload(rows, rows[1]),
    )
    rc = cli_mod.main(["sweep", str(cli_project_yaml), "--cache", "weather_cache"])
    out = capsys.readouterr()
    assert rc == 0
    assert "annual_om" in out.out
    assert "35000 USD/yr" in out.out
    assert out.out.count("optimum at grid boundary") == 2
    assert "pv_area = 200.0 m2 is at the scan range max" in out.out
    # user12 P2-6: the battery axis prints under its CSV column name.
    assert "battery_kwh = 40.0 kWh is at the scan range max" in out.out
    assert "consider widening the scan range" in out.out
    # interior axis (T_light = 21 within [20, 22]) must NOT be flagged
    assert "T_light = 21 is at the scan range" not in out.out


def test_sweep_multipoint_zero_capital_warning(cli_project_yaml, monkeypatch, capsys):
    """P0-5: a multi-point sweep whose best row has capital_total = 0 prints
    the same OPEX-only caveat as evaluate (user1's case: all capital blocks
    omitted).  Best is interior, so no boundary hint may appear."""
    from vfed import cli as cli_mod

    def row(t_light, lcoe):
        return {
            "T_light": t_light,
            "currency": "USD",
            "lcoe": lcoe,
            "cost_per_kg_fresh": lcoe * 10.0,
            "kwh_per_kg_fresh": 13.0,
            "capital_total": 0.0,
            "annual_capital": 0.0,
            "annual_om": 35000.0,
            "annual_grid_cost": 6000.0,
            "annual_load_kwh": 66000.0,
            "biomass_kg": 250.0,
        }

    rows = [row(20.0, 0.66), row(21.0, 0.63), row(22.0, 0.65)]
    monkeypatch.setattr(
        cli_mod,
        "agent_evaluate",
        lambda path, cache_dir=None: _synthetic_sweep_payload(rows, rows[1]),
    )
    rc = cli_mod.main(["sweep", str(cli_project_yaml), "--cache", "weather_cache"])
    out = capsys.readouterr()
    assert rc == 0
    assert "all capital costs are zero" in out.out
    assert "OPEX only" in out.out
    assert "Total capital" not in out.out
    assert "optimum at grid boundary" not in out.out


def test_boundary_hint_flags_min_endpoint_and_skips_interior(capsys):
    """P0-5: the boundary hint also fires at a range MIN (battery = 0 kWh is
    a legitimate optimum) and stays silent for interior values."""
    import pandas as pd

    from vfed.cli import _print_boundary_hints

    results = pd.DataFrame(
        [
            {"battery_kwh": 0.0, "lcoe": 0.50},
            {"battery_kwh": 20.0, "lcoe": 0.60},
            {"battery_kwh": 40.0, "lcoe": 0.70},
        ]
    )
    _print_boundary_hints({"battery_kwh": 0.0, "lcoe": 0.50}, results, "    ")
    out = capsys.readouterr().out
    # user12 P2-6: the axis is named battery_kwh (CSV column vocabulary).
    assert "battery_kwh = 0.0 kWh is at the scan range min" in out
    _print_boundary_hints({"battery_kwh": 20.0, "lcoe": 0.60}, results, "    ")
    assert capsys.readouterr().out == ""
