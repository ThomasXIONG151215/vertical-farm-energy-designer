"""
Layer 16: CLI UX contract tests (P2-3, T1/T2/T5/T7).

* T1  ``vfed --version`` prints "vfed <version>" and exits 0;
      ``vfed.__version__`` is the single source of the version string.
* T2  evaluate and sweep print the unified Project line
      ``Project: <yaml basename> (name: <internal name>)``.
* T5  both presets carry the authoritative city_db Shanghai coordinates
      (31.23, 121.47) so preset cache keys match the simulated city.
* T7  ``--tariff {NAME|PATH}`` on evaluate/sweep: db region name resolves
      through tariff_db, an existing YAML path parses its top-level
      ``tariff:`` section through the project schema, anything else fails
      fast (E001, pure ASCII, exit 1); the default (no flag) is a no-op.

The engine is stubbed where a full simulation is not the point -- these are
CLI-surface tests; numerical behaviour is pinned by the other layers.
"""

import sys
from pathlib import Path

import numpy as np
import pytest

# Add vfed to path for direct imports in tests
SRC = Path(__file__).resolve().parents[1] / "vfed"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import vfed
from vfed.cli import _resolve_tariff_arg, main

# ---------------------------------------------------------------------------
# fixtures / stubs
# ---------------------------------------------------------------------------


class _StubResult:
    """Minimal SimulationResult stand-in for the evaluate output path."""

    weather_attrs = {}
    summary = {
        "lcoe": None,
        "capital_total": None,
        "annual_om_pct_of_cost": None,
        "annual_grid_cost_net": None,
    }

    def get(self, key, default=None):
        if key == "load":
            return np.full(24, 1.0)
        return default


@pytest.fixture()
def farm_yaml(tmp_path):
    out = tmp_path / "farm.yaml"
    rc = main(["design", "new", "farm", "--preset", "609", "--out", str(out)])
    assert rc == 0 and out.is_file()
    return out


@pytest.fixture()
def stub_engine(monkeypatch):
    """Replace cli.DesignEngine with a recorder; returns the capture dict."""
    from vfed import cli as cli_mod

    captured = {}

    class _Engine:
        def __init__(self, cache_dir=None):
            pass

        def run(self, project):
            captured["tariff"] = project.tariff
            return _StubResult()

    monkeypatch.setattr(cli_mod, "DesignEngine", _Engine)
    return captured


# ---------------------------------------------------------------------------
# T1  --version
# ---------------------------------------------------------------------------
def test_dunder_version_matches_pyproject():
    assert vfed.__version__ == "2.1.0"


def test_version_flag_prints_and_exits_zero(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == "vfed 2.1.0"


def test_version_flag_position_independent(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert out.isascii()


# ---------------------------------------------------------------------------
# T2  unified Project line
# ---------------------------------------------------------------------------
def test_evaluate_project_line_file_and_name(farm_yaml, stub_engine, capsys):
    rc = main(["evaluate", str(farm_yaml), "--cache", "weather_cache"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Project: farm.yaml (name: farm)" in out
    for line in out.splitlines():
        assert line.isascii()


def test_sweep_project_line_file_and_name(farm_yaml, monkeypatch, capsys):
    from vfed import cli as cli_mod

    monkeypatch.setattr(
        cli_mod,
        "agent_evaluate",
        lambda path, cache_dir=None: {
            "success": True,
            "project": "farm",
            "currency": "USD",
            "exchange_rate": 1.0,
            "objective": "lcoe",
            "dry_matter_fraction": 0.05,
            "best": {"annual_load_kwh": 1.0, "lcoe": 0.5},
            "results": None,
        },
    )
    rc = cli_mod.main(["sweep", str(farm_yaml), "--cache", "weather_cache"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Project: farm.yaml (name: farm)" in out


# ---------------------------------------------------------------------------
# T5  preset coordinates == city_db Shanghai
# ---------------------------------------------------------------------------
def test_preset_coords_match_city_db():
    from vfed.design.presets import preset_609, preset_default
    from vfed.weather.city_db import city_coords

    expected = city_coords("Shanghai")
    assert expected is not None
    for p in (preset_default(), preset_609()):
        assert (p.site.lat, p.site.lon) == expected[:2]
        assert p.site.tz_hours == expected[2]
        assert p.site.city == "Shanghai"


# ---------------------------------------------------------------------------
# T7  --tariff {NAME|PATH}
# ---------------------------------------------------------------------------
def test_resolve_tariff_none_is_noop():
    assert _resolve_tariff_arg(None) is None


def test_resolve_tariff_db_name():
    from vfed.design.project import TariffConfig

    cfg = _resolve_tariff_arg("Shanghai")
    assert isinstance(cfg, TariffConfig)
    assert cfg.hourly_prices[8] == pytest.approx(1.0)
    assert cfg.hourly_prices[0] == pytest.approx(0.30)
    assert cfg.export_price == pytest.approx(0.4155)


def test_resolve_tariff_yaml_path_hourly(tmp_path):
    from vfed.design.project import TariffConfig

    f = tmp_path / "my_tariff.yaml"
    prices = ", ".join(["0.42"] * 24)
    f.write_text(f"tariff:\n  hourly_prices: [{prices}]\n  export_price: 0.11\n")
    cfg = _resolve_tariff_arg(str(f))
    assert isinstance(cfg, TariffConfig)
    assert cfg.hourly_prices == pytest.approx([0.42] * 24)
    assert cfg.export_price == pytest.approx(0.11)


def test_resolve_tariff_yaml_path_legacy_peak_valley(tmp_path):
    """The file path routes through the project schema, so the legacy
    peak/normal/valley form is accepted exactly like in a project YAML."""
    f = tmp_path / "legacy.yaml"
    f.write_text(
        "tariff:\n"
        "  peak_price: 0.90\n"
        "  normal_price: 0.50\n"
        "  valley_price: 0.30\n"
        "  peak_hours: [8, 9, 18]\n"
        "  valley_hours: [0, 1, 2]\n"
        "  export_price: 0.20\n"
    )
    cfg = _resolve_tariff_arg(str(f))
    assert cfg.hourly_prices[8] == pytest.approx(0.90)
    assert cfg.hourly_prices[3] == pytest.approx(0.50)
    assert cfg.hourly_prices[1] == pytest.approx(0.30)
    assert cfg.export_price == pytest.approx(0.20)


def test_resolve_tariff_yaml_path_bad_prices_fails_fast(tmp_path, capsys):
    f = tmp_path / "bad.yaml"
    f.write_text("tariff:\n  hourly_prices: [0.5, 0.6]\n")
    with pytest.raises(SystemExit) as exc:
        _resolve_tariff_arg(str(f))
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "E001" in err
    assert "exactly 24" in err
    assert err.isascii()


def test_resolve_tariff_yaml_path_no_section_fails_fast(tmp_path, capsys):
    f = tmp_path / "nosec.yaml"
    f.write_text("site:\n  lat: 31.23\n")
    with pytest.raises(SystemExit) as exc:
        _resolve_tariff_arg(str(f))
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "no top-level 'tariff:' section" in err
    assert err.isascii()


def test_resolve_tariff_unknown_fails_fast_ascii(capsys):
    with pytest.raises(SystemExit) as exc:
        _resolve_tariff_arg("Mars")
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "E001" in err
    assert "neither a tariff-db region name" in err
    assert "vfed design tariffs" in err
    assert err.isascii()


def test_evaluate_tariff_db_name_overrides(farm_yaml, stub_engine, capsys):
    """USA is USD-priced like the default preset project (user12 T2: a
    CNY-priced region on a USD project is rejected -- see test_17)."""
    rc = main(
        ["evaluate", str(farm_yaml), "--cache", "weather_cache", "--tariff", "USA"]
    )
    out = capsys.readouterr()
    assert rc == 0
    assert stub_engine["tariff"].hourly_prices[8] == pytest.approx(0.13)
    assert stub_engine["tariff"].export_price == pytest.approx(0.03)
    assert out.out.isascii()


def test_evaluate_tariff_yaml_path_overrides(farm_yaml, stub_engine, capsys, tmp_path):
    f = tmp_path / "my_tariff.yaml"
    prices = ", ".join(["0.77"] * 24)
    f.write_text(f"tariff:\n  hourly_prices: [{prices}]\n  export_price: 0.05\n")
    rc = main(["evaluate", str(farm_yaml), "--cache", "weather_cache", "--tariff", str(f)])
    assert rc == 0
    assert stub_engine["tariff"].hourly_prices == pytest.approx([0.77] * 24)


def test_evaluate_tariff_unknown_fails_fast(farm_yaml, stub_engine, capsys):
    with pytest.raises(SystemExit) as exc:
        main(["evaluate", str(farm_yaml), "--cache", "weather_cache", "--tariff", "Mars"])
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "E001" in err
    assert err.isascii()
    # fail fast: the engine must never have been constructed
    assert "tariff" not in stub_engine


def test_evaluate_default_tariff_untouched(farm_yaml, stub_engine, capsys):
    """No --tariff flag -> project.tariff passes through unchanged (the
    preset 609 default hourly price table)."""
    rc = main(["evaluate", str(farm_yaml), "--cache", "weather_cache"])
    assert rc == 0
    assert stub_engine["tariff"].hourly_prices == pytest.approx([0.10] * 24)
    assert stub_engine["tariff"].export_price == pytest.approx(0.05)


def test_sweep_tariff_unknown_fails_fast_before_any_work(farm_yaml, monkeypatch, capsys):
    from vfed import cli as cli_mod

    def boom(*args, **kwargs):
        raise AssertionError("agent_evaluate must not run when --tariff is invalid")

    monkeypatch.setattr(cli_mod, "agent_evaluate", boom)
    with pytest.raises(SystemExit) as exc:
        cli_mod.main(["sweep", str(farm_yaml), "--cache", "weather_cache", "--tariff", "Mars"])
    assert exc.value.code == 1
    assert "E001" in capsys.readouterr().err


def test_agent_evaluate_tariff_kwarg_applied_and_default_noop(tmp_path, monkeypatch):
    """agent_evaluate(tariff=...) overrides project.tariff after load; the
    default (None) keeps the YAML tariff -- sweep numerics unchanged."""
    from vfed.agent import evaluator as ev
    from vfed.design.presets import preset_609
    from vfed.design.project import TariffConfig

    yaml_path = tmp_path / "p.yaml"
    preset_609().save(yaml_path)
    seen = []

    def fake_sweep(project, cache_dir=None):
        seen.append(project.tariff)
        return {"best": {"annual_load_kwh": 1.0}, "results": None, "objective": "lcoe"}

    monkeypatch.setattr(ev, "sweep_design", fake_sweep)

    cfg = TariffConfig(hourly_prices=[0.9] * 24, export_price=0.2)
    res = ev.agent_evaluate(str(yaml_path), cache_dir=str(tmp_path), tariff=cfg)
    assert res["success"] is True
    assert seen[-1].hourly_prices == pytest.approx([0.9] * 24)
    assert seen[-1].export_price == pytest.approx(0.2)

    ev.agent_evaluate(str(yaml_path), cache_dir=str(tmp_path))
    assert seen[-1].hourly_prices == pytest.approx([0.10] * 24)
    assert seen[-1].export_price == pytest.approx(0.05)
