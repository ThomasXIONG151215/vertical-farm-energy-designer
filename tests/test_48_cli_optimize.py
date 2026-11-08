"""
Layer 48: ``vfed optimize`` CLI contract tests.

Covers the optimize subcommand wrapping ``vfed.design.optimize``:

* ``optimize --help``: renders with the grid/pv/battery/workers/policy flags.
* top-level ``--help``: lists the optimize subcommand.
* small real run: 1 building combo (``--grid ppfd_target=250``) x 2 PV x 2
  battery = 4 rows, best-row console block in sweep style, ``--out`` CSV.
* CLI-vs-API: the CSV best LCOE equals the direct ``optimize()`` result on
  identical inputs (exact float equality -- both paths are deterministic).
* arg validation fail-fast (before any simulation): bad ``--policy-json``,
  unknown/duplicate ``--grid`` key, missing project file.

End-to-end cases run preset 609 (31.23, 121.47, 2025) against the repo disk
cache ``weather_cache``, so they never touch the network (same as test_07).
"""
import contextlib
import io
import sys
from pathlib import Path

import pandas as pd
import pytest

# Add vfed to path for direct imports in tests
SRC = Path(__file__).resolve().parents[1] / "vfed"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from vfed.cli import main
from vfed.design.project import DesignProject
from vfed.design.optimize import optimize


@pytest.fixture(scope="session")
def cli_project_yaml(tmp_path_factory):
    """``design new`` output for preset 609 (matches the disk-cached weather)."""
    d = tmp_path_factory.mktemp("cli_opt")
    out = d / "farm.yaml"
    rc = main(["design", "new", "farm", "--preset", "609", "--out", str(out)])
    assert rc == 0
    assert out.is_file()
    return out


@pytest.fixture(scope="session")
def optimize_run(cli_project_yaml, tmp_path_factory):
    """One real CLI optimize run: 1 building combo x 2 PV x 2 battery -> 4 rows."""
    csv = tmp_path_factory.mktemp("opt_out") / "results.csv"
    buf_out, buf_err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(buf_out), contextlib.redirect_stderr(buf_err):
        rc = main(
            [
                "optimize",
                str(cli_project_yaml),
                "--cache",
                "weather_cache",
                "--grid",
                "ppfd_target=250",
                "--pv",
                "0,5",
                "--battery",
                "0,1",
                "--out",
                str(csv),
            ]
        )
    return rc, buf_out.getvalue(), buf_err.getvalue(), csv


# ---------------------------------------------------------------------------
# 48.1  help
# ---------------------------------------------------------------------------
def test_optimize_help_renders(capsys):
    with pytest.raises(SystemExit) as ei:
        main(["optimize", "--help"])
    assert ei.value.code == 0
    out = capsys.readouterr().out
    for flag in ("--grid", "--pv", "--battery", "--objective", "--workers", "--policy-json"):
        assert flag in out
    assert "min:max:step" in out  # grid SPEC forms documented


def test_top_help_lists_optimize(capsys):
    with pytest.raises(SystemExit) as ei:
        main(["--help"])
    assert ei.value.code == 0
    assert "optimize" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# 48.2  small real run (disk cache, no network)
# ---------------------------------------------------------------------------
def test_optimize_run_rc_and_console(optimize_run):
    rc, out, err, csv = optimize_run
    assert rc == 0
    assert csv.is_file()
    assert "Configs enumerated = 4" in out
    assert "Best design (min LCOE)" in out
    assert "LCOE" in out
    assert "pv_area" in out
    assert "battery_kwh" in out


def test_optimize_csv_rows(optimize_run):
    _, _, _, csv = optimize_run
    df = pd.read_csv(csv, float_precision="round_trip")
    assert len(df) == 4
    assert set(df["pv_area"]) == {0.0, 5.0}
    assert set(df["battery_kwh"]) == {0.0, 1.0}


# ---------------------------------------------------------------------------
# 48.3  CLI vs direct optimize() API on identical inputs
# ---------------------------------------------------------------------------
def test_cli_best_matches_api(optimize_run, cli_project_yaml):
    _, _, _, csv = optimize_run
    # round_trip: pandas' default C float parser can be 1 ULP off on read.
    df = pd.read_csv(csv, float_precision="round_trip")
    csv_best_lcoe = float(df.loc[df["lcoe"].idxmin(), "lcoe"])

    project = DesignProject.load(str(cli_project_yaml))
    res = optimize(
        project,
        {"ppfd_target": [250.0]},
        cache_dir="weather_cache",
        pv_grid=[0.0, 5.0],
        battery_grid=[0.0, 1.0],
    )
    assert res["objective"] == "lcoe"
    assert len(res["results"]) == 4
    api_best_lcoe = float(res["best"]["lcoe"])
    assert csv_best_lcoe == api_best_lcoe  # exact: both paths deterministic


# ---------------------------------------------------------------------------
# 48.4  fail-fast arg validation (no simulation started)
# ---------------------------------------------------------------------------
def test_optimize_missing_file(capsys):
    rc = main(["optimize", "no_such_project.yaml", "--cache", "weather_cache"])
    assert rc != 0
    assert "E001" in capsys.readouterr().err


def test_optimize_bad_policy_json(cli_project_yaml, capsys):
    rc = main(
        [
            "optimize",
            str(cli_project_yaml),
            "--cache",
            "weather_cache",
            "--policy-json",
            "{not json",
        ]
    )
    assert rc != 0
    err = capsys.readouterr().err
    assert "E001" in err
    assert "not valid JSON" in err


def test_optimize_unknown_grid_key(cli_project_yaml, capsys):
    rc = main(
        [
            "optimize",
            str(cli_project_yaml),
            "--cache",
            "weather_cache",
            "--grid",
            "not_a_real_param=1:2:0.5",
        ]
    )
    assert rc != 0
    err = capsys.readouterr().err
    assert "E001" in err
    assert "not_a_real_param" in err


def test_optimize_duplicate_grid_key(cli_project_yaml, capsys):
    rc = main(
        [
            "optimize",
            str(cli_project_yaml),
            "--cache",
            "weather_cache",
            "--grid",
            "ppfd_target=250",
            "--grid",
            "ppfd_target=300",
        ]
    )
    assert rc != 0
    err = capsys.readouterr().err
    assert "E001" in err
    assert "duplicate" in err


def test_optimize_bad_grid_value(cli_project_yaml, capsys):
    rc = main(
        [
            "optimize",
            str(cli_project_yaml),
            "--cache",
            "weather_cache",
            "--grid",
            "ppfd_target=abc",
        ]
    )
    assert rc != 0
    assert "E001" in capsys.readouterr().err
