"""
Layer 21: currency conversion engine (round 26).

Core principle (m0479/m0484, non-negotiable):
* An EXPLICIT price in the YAML is a literal in the project currency --
  NEVER converted.
* An OMITTED price (``None`` sentinel) falls back to the built-in
  USD-baseline default, which ``from_dict`` materializes into the project
  currency with ``exchange_rate`` (user-set; ``vfed design fx`` shows a
  reference snapshot).

Covered here:
* conversion math at CNY@7.2 for every USD-baseline default (tariff,
  export, opex labor/misc/water, C_pv, c_energy, rate_per_watt);
* explicit-value passthrough (no double conversion in non-USD projects);
* USD / exchange_rate=1.0 bitwise zero drift;
* to_dict/from_dict sentinel roundtrip fidelity (incl. partially explicit
  opex sections and the sweep ``_override_project`` clone path);
* ``vfed design fx`` CLI output (CNY/USD/EUR, pure ASCII);
* round-18 tariff-db currency rejection still E001;
* P1-7 OPEX-dominance warning under the new sentinel semantics
  (fires when ANY default price is in effect);
* the evaluate console USD-equivalent line (rate != 1 only).
"""

import sys
from pathlib import Path

import numpy as np
import pytest
import yaml

SRC = Path(__file__).resolve().parents[1] / "vfed"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import warnings

from vfed import cli as cli_mod
from vfed.cli import _resolve_tariff_arg, main
from vfed.design import fx as fx_mod
from vfed.design.engine import _warn_opex_dominance
from vfed.design.presets import preset_609
from vfed.design.project import DesignProject
from vfed.design.sweep import _resolve_capital, _total_capital, _override_project


def _project(**overrides):
    """Minimal valid project dict with R26 overrides applied."""
    d = {"name": "fx_probe", "site": {"lat": 31.2, "lon": 121.5}}
    d.update(overrides)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return DesignProject.from_dict(d)


_CNY = {"currency": "CNY", "exchange_rate": 7.2}


# ---------------------------------------------------------------------------
# 21.1  USD-baseline truth source (fx.py)
# ---------------------------------------------------------------------------
def test_fx_snapshot_covers_required_currencies():
    assert fx_mod.FX_SNAPSHOT["USD"] == 1.0
    for cur in ("CNY", "EUR"):
        assert cur in fx_mod.FX_SNAPSHOT
        assert fx_mod.FX_SNAPSHOT[cur] > 0
    assert fx_mod.FX_SNAPSHOT_DATE  # snapshot date annotated
    assert all(isinstance(v, float) and v > 0 for v in fx_mod.FX_SNAPSHOT.values())


def test_usd_baseline_constants_match_legacy_defaults():
    """The USD-baseline table is the single source of the historical
    literals (500/220/0.10/0.05/30000/5000/2.0/1.0)."""
    assert fx_mod.USD_C_PV == 500.0
    assert fx_mod.USD_C_ENERGY == 220.0
    assert fx_mod.USD_TARIFF == 0.10
    assert fx_mod.USD_EXPORT == 0.05
    assert fx_mod.USD_LABOR == 30000.0
    assert fx_mod.USD_MISC == 5000.0
    assert fx_mod.USD_WATER == 2.0
    assert fx_mod.USD_RATE_PER_WATT == 1.0


def test_usd_base_to_project_passthrough_and_conversion():
    assert fx_mod.usd_base_to_project(500.0, "USD", 1.0) == 500.0
    assert fx_mod.usd_base_to_project(500.0, "USD", 7.2) == 500.0  # USD wins
    assert fx_mod.usd_base_to_project(500.0, "CNY", 1.0) == 500.0  # rate 1.0 wins
    assert fx_mod.usd_base_to_project(500.0, "CNY", 7.2) == 3600.0  # exact float


# ---------------------------------------------------------------------------
# 21.2  conversion math: CNY @ 7.2 (defaults only -- nothing explicit)
# ---------------------------------------------------------------------------
def test_cny_defaults_tariff_and_export():
    p = _project(**_CNY)
    assert p.tariff.hourly_prices is not None
    assert len(p.tariff.hourly_prices) == 24
    for h in p.tariff.hourly_prices:
        assert h == pytest.approx(0.72)  # 0.10 x 7.2
    assert p.tariff.export_price == pytest.approx(0.36)  # 0.05 x 7.2


def test_cny_defaults_opex():
    p = _project(**_CNY)
    assert p.opex.labor_cost_per_year == 216000.0  # 30000 x 7.2 (exact)
    assert p.opex.misc_opex_per_year == 36000.0  # 5000 x 7.2 (exact)
    assert p.opex.water_cost_per_m3 == 14.4  # 2.0 x 7.2 (exact)
    assert p.opex.maintenance_pct == 0.02  # fraction: NOT converted
    assert p.opex_was_defaulted is True


def test_cny_defaults_legacy_unit_prices():
    p = _project(pv_area_m2=43.0, battery_kwh=40.0, **_CNY)
    assert p.pv.C_pv == 3600.0  # 500 x 7.2 (exact)
    assert p.battery.c_energy == 1584.0  # 220 x 7.2 (exact)
    cap = _total_capital(p, 43.0, 40.0)  # 10 kWp / 40 kWh
    assert cap["PV"] == pytest.approx(3600.0 * 10.0)  # 36000
    assert cap["Battery"] == pytest.approx(1584.0 * 40.0)  # 63360


def test_cny_defaults_rate_per_watt_materialized_and_defense():
    p = _project(**_CNY)
    # from_dict materializes every capital block's sentinel
    for comp in (
        p.led.capital,
        p.hvac.capital,
        p.deh.capital,
        p.equipment_capital,
        p.envelope_capital,
        p.pump_capital,
    ):
        assert comp.rate_per_watt == pytest.approx(7.2)
    # defense in depth: a raw CapitalCostConfig still prices via the baseline
    from vfed.design.project import CapitalCostConfig

    raw = CapitalCostConfig(mode="per_watt")  # rate_per_watt=None (programmatic)
    assert (
        _resolve_capital(raw, 100.0, component="led", currency="CNY", exchange_rate=7.2)
        == pytest.approx(720.0)
    )
    assert (
        _resolve_capital(raw, 100.0, component="led", currency="USD", exchange_rate=1.0)
        == pytest.approx(100.0)
    )


# ---------------------------------------------------------------------------
# 21.3  explicit values pass through literally (NEVER converted)
# ---------------------------------------------------------------------------
def test_explicit_values_literal_in_cny_project():
    p = _project(
        **_CNY,
        tariff={"hourly_prices": [0.6] * 24, "export_price": 0.5},
        opex={
            "labor_cost_per_year": 100000.0,
            "misc_opex_per_year": 8000.0,
            "water_cost_per_m3": 5.0,
        },
        pv={"C_pv": 3500.0},  # e.g. RMB/kWp written by the user
        battery={"c_energy": 500.0},
        led={"capital": {"mode": "per_watt", "rate_per_watt": 1.0}},
    )
    assert p.tariff.hourly_prices == [0.6] * 24  # unchanged
    assert p.tariff.export_price == 0.5  # unchanged
    assert p.opex.labor_cost_per_year == 100000.0
    assert p.opex.misc_opex_per_year == 8000.0
    assert p.opex.water_cost_per_m3 == 5.0
    assert p.pv.C_pv == 3500.0  # NOT 3500 x 7.2
    assert p.battery.c_energy == 500.0
    assert p.led.capital.rate_per_watt == 1.0  # explicit 1.0 literal, NOT 7.2
    # mixed section: explicit labor + defaulted misc still converts misc only
    assert p.opex_was_defaulted is False  # all three core fields explicit


def test_explicit_null_is_the_sentinel():
    """``null`` counts as omitted (same rule as capital cost, F2)."""
    p = _project(
        **_CNY,
        tariff={"hourly_prices": None},
        opex={"labor_cost_per_year": 12345.0, "misc_opex_per_year": None},
    )
    for h in p.tariff.hourly_prices:
        assert h == pytest.approx(0.72)  # sentinel -> converted default
    assert p.opex.labor_cost_per_year == 12345.0  # explicit kept
    assert p.opex.misc_opex_per_year == 36000.0  # null -> converted default
    assert p.opex_was_defaulted is True  # a default price IS in effect


# ---------------------------------------------------------------------------
# 21.4  USD / rate=1.0 zero drift
# ---------------------------------------------------------------------------
def test_usd_zero_drift_defaults_are_exact_literals():
    p = _project()
    assert p.tariff.hourly_prices == [0.10] * 24
    assert p.tariff.export_price == 0.05
    assert p.opex.labor_cost_per_year == 30000.0
    assert p.opex.misc_opex_per_year == 5000.0
    assert p.opex.water_cost_per_m3 == 2.0
    assert p.pv.C_pv == 500.0
    assert p.battery.c_energy == 220.0
    assert p.led.capital.rate_per_watt == 1.0


def test_rate_one_non_usd_project_also_zero_drift():
    """exchange_rate=1.0 means 1:1 accounting (the P8-14 soft-guard regime):
    no conversion is applied even for a non-USD currency label."""
    p = _project(currency="CNY", exchange_rate=1.0)
    assert p.tariff.hourly_prices == [0.10] * 24
    assert p.opex.labor_cost_per_year == 30000.0
    assert p.pv.C_pv == 500.0


def test_preset_609_default_path_bitwise():
    """The 609 preset (USD, rate 1.0) materializes to the exact legacy
    numbers -- the bundled baselines stay bitwise unchanged."""
    p = preset_609()
    assert p.tariff.hourly_prices == [0.10] * 24
    assert p.tariff.export_price == 0.05
    assert p.opex.labor_cost_per_year == 30000.0
    assert p.opex.misc_opex_per_year == 5000.0
    assert p.pv.C_pv == 500.0
    assert p.battery.c_energy == 220.0
    assert p.led.capital.rate_per_watt == 1.0


# ---------------------------------------------------------------------------
# 21.5  sentinel roundtrip fidelity
# ---------------------------------------------------------------------------
def test_to_dict_omits_none_sentinels_on_programmatic_construction():
    d = DesignProject().to_dict()
    assert "tariff" not in d  # both sentinel fields omitted -> empty section
    assert "opex" not in d  # no explicit keys -> section dropped
    assert "cost" not in d["pv"]["capital"]
    assert "rate_per_watt" not in d["pv"]["capital"]
    assert "C_pv" not in d["pv"]
    assert "c_energy" not in d["battery"]
    assert "opex_explicit_keys" not in d  # internal key never serialized


def test_roundtrip_defaulted_cny_project():
    """A defaulted CNY project roundtrips with identical numbers; the
    materialized tariff is re-emitted explicitly, the defaulted opex section
    is dropped and re-derived."""
    p1 = _project(**_CNY, pv_area_m2=43.0, battery_kwh=40.0)
    d1 = p1.to_dict()
    assert "opex" not in d1
    assert d1["currency"] == "CNY" and d1["exchange_rate"] == 7.2
    p2 = DesignProject.from_dict(d1)
    assert p2.opex.labor_cost_per_year == 216000.0
    assert p2.opex_was_defaulted is True
    for a, b in zip(p2.tariff.hourly_prices, p1.tariff.hourly_prices):
        assert a == b  # bitwise
    assert p2.pv.C_pv == 3600.0 and p2.battery.c_energy == 1584.0


def test_roundtrip_partially_explicit_opex_keeps_explicit_values():
    """sweep._override_project clones through to_dict -> from_dict: a
    partially explicit opex section must not silently lose the explicit
    labor cost (it would re-price rows with the default)."""
    p1 = _project(
        **_CNY,
        opex={"labor_cost_per_year": 12345.0},
        led={"ppfd_target": 200.0},
    )
    assert p1.opex_was_defaulted is True
    p2 = _override_project(p1, {"ppfd_target": 300.0})
    assert p2.led.ppfd_target == 300.0
    assert p2.opex.labor_cost_per_year == 12345.0  # explicit value survived
    assert p2.opex.misc_opex_per_year == 36000.0  # default re-materialized
    assert p2.opex_was_defaulted is True  # provenance preserved


def test_internal_opex_explicit_keys_rejected_as_user_key():
    with pytest.raises(ValueError, match="internal VFED field"):
        DesignProject.from_dict({"opex_explicit_keys": ["labor_cost_per_year"]})


# ---------------------------------------------------------------------------
# 21.6  vfed design fx CLI
# ---------------------------------------------------------------------------
def test_design_fx_prints_snapshot_ascii(capsys):
    rc = main(["design", "fx"])
    out = capsys.readouterr().out
    assert rc == 0
    assert out.isascii()
    assert "CNY" in out and "USD" in out and "EUR" in out
    assert fx_mod.FX_SNAPSHOT_DATE in out
    # one line per snapshot currency, formatted as a table
    for cur, rate in fx_mod.FX_SNAPSHOT.items():
        assert cur in out
        assert f"{rate:g}" in out


# ---------------------------------------------------------------------------
# 21.7  round-18 tariff-db currency rejection still fires
# ---------------------------------------------------------------------------
def test_tariff_db_currency_mismatch_still_rejected():
    """Beijing is CNY-priced: on a USD project it must fail fast (E001),
    R26 does not add any silent FX conversion to the --tariff path."""
    with pytest.raises(SystemExit) as exc:
        _resolve_tariff_arg("Beijing", project_currency="USD")
    assert exc.value.code == 1


def test_tariff_db_matching_currency_passthrough():
    """A currency-matching db region passes through literally (no
    conversion, round-18 semantics preserved)."""
    cfg = _resolve_tariff_arg("USA", project_currency="USD")
    assert cfg.hourly_prices[0] == pytest.approx(0.08)  # not rescaled


# ---------------------------------------------------------------------------
# 21.8  P1-7 warning under the new sentinel semantics
# ---------------------------------------------------------------------------
def test_opex_default_warning_fires_for_partially_explicit_section(monkeypatch):
    import vfed.design.engine as engine_mod

    monkeypatch.setattr(engine_mod, "_OPEX_DEFAULT_WARNED", False)
    p = _project(opex={"labor_cost_per_year": 12345.0})  # misc/water defaulted
    assert p.opex_was_defaulted is True
    with pytest.warns(UserWarning, match="default OPEX in effect"):
        _warn_opex_dominance(p, 35020.75, 0.9)

    # fully explicit section: silent even at 90%
    monkeypatch.setattr(engine_mod, "_OPEX_DEFAULT_WARNED", False)
    p_full = _project(
        opex={
            "labor_cost_per_year": 12345.0,
            "misc_opex_per_year": 678.0,
            "water_cost_per_m3": 1.5,
        }
    )
    assert p_full.opex_was_defaulted is False
    with warnings.catch_warnings(record=True) as rec:
        warnings.simplefilter("always")
        _warn_opex_dominance(p_full, 35020.75, 0.9)
    assert len(rec) == 0


# ---------------------------------------------------------------------------
# 21.9  evaluate console USD-equivalent line (rate != 1 only)
# ---------------------------------------------------------------------------
class _StubResult:
    weather_attrs = {}
    summary = {
        "lcoe": 7.2,  # CNY/kWh in the stub world
        "capital_total": None,
        "annual_om_pct_of_cost": None,
        "annual_grid_cost_net": None,
    }

    def get(self, key, default=None):
        if key == "load":
            return np.full(24, 1.0)
        return default


def test_evaluate_prints_usd_equivalent_line(tmp_path, monkeypatch, capsys):
    yaml_path = tmp_path / "cny.yaml"
    _project(**_CNY).save(yaml_path)

    class _Engine:
        def __init__(self, cache_dir=None):
            pass

        def run(self, project):
            return _StubResult()

    monkeypatch.setattr(cli_mod, "DesignEngine", _Engine)
    rc = main(["evaluate", str(yaml_path), "--cache", "weather_cache"])
    out = capsys.readouterr().out
    assert rc == 0
    assert out.isascii()
    assert "LCOE             = 7.2000 CNY/kWh" in out
    assert "USD equivalent   = LCOE 1.0000 USD/kWh (at 1 USD = 7.2 CNY)" in out


def test_evaluate_no_usd_equivalent_line_for_usd(tmp_path, monkeypatch, capsys):
    yaml_path = tmp_path / "usd.yaml"
    _project().save(yaml_path)

    class _Engine:
        def __init__(self, cache_dir=None):
            pass

        def run(self, project):
            return _StubResult()

    monkeypatch.setattr(cli_mod, "DesignEngine", _Engine)
    rc = main(["evaluate", str(yaml_path), "--cache", "weather_cache"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "USD equivalent" not in out


# ---------------------------------------------------------------------------
# 21.10  design new template documents the currency model
# ---------------------------------------------------------------------------
def test_design_new_template_currency_comment(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["design", "new", "t", "--preset", "609"]) == 0
    text = (tmp_path / "t.yaml").read_text(encoding="utf-8")
    assert "vfed design fx" in text
    assert "NEVER converted" in text
    raw = yaml.safe_load(text)
    assert "opex_explicit_keys" not in raw  # internal key never in templates
    assert raw["currency"] == "USD" and raw["exchange_rate"] == 1.0
