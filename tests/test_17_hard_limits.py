"""
Layer 17: unified hard limits (user12 T1) + tariff currency consistency
(user12 T2).

T1  ``HARD_LIMITS`` / ``PARAM_PATH_MAP`` live in ``design.project`` (sweep
    imports them), and ``DesignProject.from_dict`` rejects every scalar
    config field outside its band -- so the same guard fires at ALL three
    entry points (validate / evaluate / sweep), not only on sweep ranges.
    The user12 repro ``led.ppfd_target: 9999`` must be refused with E001
    before any simulation.  Bands are unchanged from the old sweep table.
T2  Every tariff-db region carries a ``currency``.  ``evaluate``/``sweep
    --tariff <REGION>`` fails fast (E001, exit 1) when the region currency
    differs from the project currency -- no auto-conversion, no auto
    rewrite of an existing project.  ``design new --tariff <REGION>``
    (a brand-new project) sets the currency automatically and says so.
    ``design tariffs`` lists the currency column.  A user-supplied
    ``--tariff`` YAML file is always treated as project-currency.
"""

import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[1] / "vfed"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from vfed.cli import main
from vfed.design import sweep as sweep_mod
from vfed.design.project import (
    HARD_LIMITS,
    PARAM_PATH_MAP,
    PARAM_TOPLEVEL_MAP,
    DesignProject,
)
from vfed.pvbes.tariff_db import TARIFF_DB

# ---------------------------------------------------------------------------
# fixtures / stubs
# ---------------------------------------------------------------------------


@pytest.fixture()
def design_yaml(tmp_path):
    """A clean project from the 609 preset (currency USD, all in-band)."""
    out = tmp_path / "farm.yaml"
    rc = main(["design", "new", "farm", "--preset", "609", "--out", str(out)])
    assert rc == 0 and out.is_file()
    return out


@pytest.fixture()
def bad_limit_yaml(tmp_path):
    """The user12 repro: preset project with led.ppfd_target pushed to 9999."""
    out = tmp_path / "bad_limit.yaml"
    rc = main(["design", "new", "u12", "--preset", "609", "--out", str(out)])
    assert rc == 0
    text = out.read_text(encoding="utf-8")
    assert "ppfd_target: 400.0" in text  # preset 609 default
    out.write_text(text.replace("ppfd_target: 400.0", "ppfd_target: 9999.0"), encoding="utf-8")
    return out


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
# T1  table location: project.py is the single source of truth
# ---------------------------------------------------------------------------
def test_hard_limits_live_in_project_sweep_imports_them():
    from vfed.design import project as project_mod

    assert sweep_mod.HARD_LIMITS is project_mod.HARD_LIMITS
    assert sweep_mod.PARAM_PATH_MAP is project_mod.PARAM_PATH_MAP


def test_toplevel_sizing_keys_cover_whole_table():
    """No HARD_LIMITS entry may be silently skipped by from_dict: the nine
    building params are in PARAM_PATH_MAP, pv_area/battery in
    PARAM_TOPLEVEL_MAP (same physical quantity as pv_area_m2/battery_kwh)."""
    mapped = set(PARAM_PATH_MAP) | set(PARAM_TOPLEVEL_MAP)
    assert mapped == set(HARD_LIMITS)


# ---------------------------------------------------------------------------
# T1  from_dict scalar guard: reject out-of-band, accept in-band
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("param", sorted(PARAM_PATH_MAP))
def test_scalar_over_limit_rejected_in_band_accepted(param):
    lo, hi = HARD_LIMITS[param]
    section, field = PARAM_PATH_MAP[param]
    delta = max(abs(hi) * 0.1, 1.0)
    for bad in (hi + delta, lo - delta):
        with pytest.raises(ValueError) as ei:
            DesignProject.from_dict({section: {field: bad}})
        msg = str(ei.value)
        assert f"{section}.{field}" in msg
        assert "hard limit" in msg
        assert msg.isascii()
    mid = lo + (hi - lo) / 2.0
    p = DesignProject.from_dict({section: {field: mid}})
    assert getattr(getattr(p, section), field) == pytest.approx(mid)


@pytest.mark.parametrize("param", sorted(PARAM_TOPLEVEL_MAP))
def test_toplevel_sizing_over_limit_rejected(param):
    field = PARAM_TOPLEVEL_MAP[param]
    lo, hi = HARD_LIMITS[param]
    with pytest.raises(ValueError, match="hard limit"):
        DesignProject.from_dict({field: hi + 1.0})
    p = DesignProject.from_dict({field: lo})  # 0 = disabled, must stay legal
    assert getattr(p, field) == 0


def test_hard_limit_band_edges_accepted():
    """Bands are inclusive: exact limits pass (no tightening, no relaxing)."""
    DesignProject.from_dict({"led": {"ppfd_target": 50}})
    DesignProject.from_dict({"led": {"ppfd_target": 500}})


def test_ppfd_9999_rejected_with_path_value_band():
    """The exact user12 repro must be refused, message ASCII with the
    field path, the offending value and the valid band."""
    with pytest.raises(ValueError) as ei:
        DesignProject.from_dict({"led": {"ppfd_target": 9999}})
    msg = str(ei.value)
    assert "led.ppfd_target" in msg
    assert "9999" in msg
    assert "[50, 500]" in msg
    assert msg.isascii()


def test_missing_key_still_legal():
    """The guard is band-only: omitted keys keep the dataclass defaults."""
    p = DesignProject.from_dict({})
    assert 50 <= p.led.ppfd_target <= 500


# ---------------------------------------------------------------------------
# T1  entry-point parity: validate / evaluate / sweep all E001, exit != 0
# ---------------------------------------------------------------------------
def test_validate_entry_rejects_ppfd_9999(bad_limit_yaml, capsys):
    rc = main(["validate", str(bad_limit_yaml)])
    assert rc == 1
    err = capsys.readouterr().err
    assert "[ERROR E001]" in err
    assert "led.ppfd_target" in err
    assert "9999" in err
    assert err.isascii()


def test_evaluate_entry_rejects_ppfd_9999(bad_limit_yaml, monkeypatch, capsys):
    from vfed import cli as cli_mod

    def boom(*a, **k):
        raise AssertionError("engine must never run for an out-of-band config")

    monkeypatch.setattr(cli_mod, "DesignEngine", boom)
    rc = main(["evaluate", str(bad_limit_yaml), "--cache", "weather_cache"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "[ERROR E001]" in err
    assert "9999" in err
    assert err.isascii()


def test_sweep_entry_rejects_ppfd_9999(bad_limit_yaml, capsys):
    """Real agent_evaluate path: the config fails at load, before any
    weather fetch or simulation."""
    rc = main(["sweep", str(bad_limit_yaml), "--cache", "weather_cache"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "[ERROR E001]" in err
    assert "9999" in err
    assert err.isascii()


def test_validate_entry_accepts_in_band_yaml(design_yaml, capsys):
    rc = main(["validate", str(design_yaml)])
    assert rc == 0
    assert "OK" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# T2  tariff db carries currency metadata
# ---------------------------------------------------------------------------
_EXPECTED_CURRENCIES = {
    "Shanghai": "CNY",
    "Beijing": "CNY",
    "Jiangsu": "CNY",
    "Zhejiang": "CNY",
    "Guangdong": "CNY",
    "Sichuan": "CNY",
    "Hubei": "CNY",
    "Japan": "JPY",
    "Singapore": "SGD",
    "USA": "USD",
}


def test_tariff_db_regions_carry_currency():
    for rid, cur in _EXPECTED_CURRENCIES.items():
        assert TARIFF_DB[rid]["currency"] == cur
    for rec in TARIFF_DB.values():
        assert isinstance(rec["currency"], str) and rec["currency"].isascii()


def test_design_tariffs_lists_currency_column(capsys):
    assert main(["design", "tariffs"]) in (0, None)
    out = capsys.readouterr().out
    for cur in ("CNY", "USD", "JPY", "SGD"):
        assert cur in out
    for rid, cur in _EXPECTED_CURRENCIES.items():
        line = next(l for l in out.splitlines() if rid in l)
        assert cur in line
    for line in out.splitlines():
        assert line.isascii()


# ---------------------------------------------------------------------------
# T2  evaluate/sweep --tariff: currency mismatch rejected, match accepted
# ---------------------------------------------------------------------------
def test_evaluate_rejects_currency_mismatch(design_yaml, monkeypatch, capsys):
    """USD project + CNY-priced Beijing -> E001 exit 1, both fixes named,
    engine never constructed (fail fast, no mislabelled LCOE)."""
    from vfed import cli as cli_mod

    def boom(*a, **k):
        raise AssertionError("engine must never run on a currency mismatch")

    monkeypatch.setattr(cli_mod, "DesignEngine", boom)
    with pytest.raises(SystemExit) as exc:
        main(["evaluate", str(design_yaml), "--cache", "weather_cache", "--tariff", "Beijing"])
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "[ERROR E001]" in err
    assert "CNY" in err
    assert "USD" in err
    assert "currency" in err.lower()
    assert "design tariffs" in err
    assert err.isascii()


def test_sweep_rejects_currency_mismatch_before_any_work(design_yaml, monkeypatch, capsys):
    from vfed import cli as cli_mod

    def boom(*a, **k):
        raise AssertionError("agent_evaluate must not run on a currency mismatch")

    monkeypatch.setattr(cli_mod, "agent_evaluate", boom)
    with pytest.raises(SystemExit) as exc:
        main(["sweep", str(design_yaml), "--cache", "weather_cache", "--tariff", "Beijing"])
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "[ERROR E001]" in err
    assert "CNY" in err and "USD" in err
    assert err.isascii()


def test_evaluate_accepts_matching_currency(design_yaml, stub_engine):
    """USA is USD-priced like the preset project -> accepted, prices applied."""
    rc = main(["evaluate", str(design_yaml), "--cache", "weather_cache", "--tariff", "USA"])
    assert rc == 0
    assert stub_engine["tariff"].hourly_prices[0] == pytest.approx(0.08)
    assert stub_engine["tariff"].export_price == pytest.approx(0.03)


def test_custom_tariff_file_skips_currency_check(design_yaml, stub_engine, tmp_path):
    """A user-supplied --tariff YAML file is project-currency by definition:
    no check, no rejection (user12 T2 item 5)."""
    my = tmp_path / "my_tariff.yaml"
    prices = ", ".join(["0.42"] * 24)
    my.write_text(f"tariff:\n  hourly_prices: [{prices}]\n  export_price: 0.11\n")
    rc = main(["evaluate", str(design_yaml), "--cache", "weather_cache", "--tariff", str(my)])
    assert rc == 0
    assert stub_engine["tariff"].hourly_prices == pytest.approx([0.42] * 24)


def test_existing_project_currency_never_rewritten(design_yaml):
    """No auto-conversion / auto-rewrite: after a rejected mismatch the
    project file on disk is untouched."""
    before = design_yaml.read_text(encoding="utf-8")
    from vfed import cli as cli_mod

    try:
        cli_mod._resolve_tariff_arg("Beijing", project_currency="USD")
    except SystemExit as e:
        assert e.code == 1
    assert design_yaml.read_text(encoding="utf-8") == before
    assert "currency: CNY" not in before


# ---------------------------------------------------------------------------
# T2  design new --tariff: new project adopts the region currency
# ---------------------------------------------------------------------------
def test_design_new_tariff_sets_currency(tmp_path, capsys):
    out = tmp_path / "farm.yaml"
    rc = main(
        ["design", "new", "farm", "--preset", "609", "--tariff", "Beijing", "--out", str(out)]
    )
    assert rc == 0
    out_txt = capsys.readouterr().out
    assert "Currency set to CNY" in out_txt
    assert out_txt.isascii()
    text = out.read_text(encoding="utf-8")
    assert "currency: CNY" in text
    p = DesignProject.load(out)
    assert p.currency == "CNY"
    assert p.tariff.hourly_prices[8] == pytest.approx(1.05)


def test_design_new_tariff_usd_stays_usd(tmp_path):
    out = tmp_path / "farm.yaml"
    assert (
        main(["design", "new", "farm", "--preset", "609", "--tariff", "USA", "--out", str(out)])
        == 0
    )
    p = DesignProject.load(out)
    assert p.currency == "USD"
    assert p.tariff.hourly_prices[0] == pytest.approx(0.08)


def test_design_new_without_tariff_keeps_default_currency(design_yaml):
    assert DesignProject.load(design_yaml).currency == "USD"
