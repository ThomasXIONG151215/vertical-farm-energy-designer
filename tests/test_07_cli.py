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

End-to-end CLI cases run preset 609 (30.9, 121.5, 2025) against the disk
cache, so they never touch the network.
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
    rc = main(["design", "new", "myfarm", "--preset", "609",
               "--out", str(tmp_path / "custom.yaml")])
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


# ---------------------------------------------------------------------------
# 7.3  sweep
# ---------------------------------------------------------------------------
def test_sweep_single_point_out_csv(cli_project_yaml, tmp_path):
    out_csv = tmp_path / "sweep.csv"
    rc = main(["sweep", str(cli_project_yaml), "--cache", "weather_cache",
               "--out", str(out_csv)])
    assert rc == 0
    assert out_csv.is_file()
    assert "kwh_per_kg_fresh" in out_csv.read_text()


def test_sweep_out_missing_dir(cli_project_yaml, tmp_path, capsys):
    missing = tmp_path / "no_such_dir" / "out.csv"
    rc = main(["sweep", str(cli_project_yaml), "--cache", "weather_cache",
               "--out", str(missing)])
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
            return {"load": np.zeros(24),
                    "weather": {},
                    "timeseries": {},
                    "annual_load_kwh": 0.0}[key]

        def get(self, key, default=None):
            if key in ("load", "weather", "timeseries", "annual_load_kwh"):
                return self[key]
            return default

    monkeypatch.setattr(evaluator.DesignEngine, "run",
                        lambda self, project: ZeroLoadResult())
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
