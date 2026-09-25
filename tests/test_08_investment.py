"""
Layer 8: P1-2 investment metrics.

* sweep results.csv investment columns (evaluate-parity + incremental)
* hand-rolled NPV / IRR (bisection, no numpy_financial)
* battery.allow_grid_charging: YAML validation + TOU dispatch + the
  default-False bitwise-invariance guarantee
"""

import math
import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[1] / "vfed"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from vfed.design.project import DesignProject
from vfed.pvbes.battery import BatterySystem
from vfed.pvbes.energy_system import EnergySystem
from vfed.pvbes.grid import Tariff


# ---------------------------------------------------------------------------
# 8.1  NPV (closed form) + battery replacement PV
# ---------------------------------------------------------------------------
def test_npv_zero_rate():
    from vfed.design.sweep import _incremental_npv

    # i = 0: NPV = -C + S * years
    assert _incremental_npv(1000.0, 100.0, 0.0, 25.0, 0.0) == pytest.approx(-1000.0 + 2500.0)


def test_npv_matches_manual_sum():
    from vfed.design.sweep import _incremental_npv

    i, savings, capital, years = 0.06, 26359.0, 142093.0, 25.0
    manual = -capital + sum(savings / (1 + i) ** t for t in range(1, 26))
    assert _incremental_npv(capital, savings, i, years, 0.0) == pytest.approx(manual, rel=1e-12)


def test_npv_with_replacement():
    from vfed.design.sweep import _battery_replacement_pv, _incremental_npv

    i = 0.06
    life = 4000.0 / 236.0  # ≈ 16.95 yr → exactly one replacement inside 25 yr
    repl = _battery_replacement_pv(8800.0, life, 25.0, i)
    assert repl == pytest.approx(8800.0 * (1 + i) ** (-life))
    npv = _incremental_npv(1000.0, 100.0, i, 25.0, repl)
    manual = -1000.0 + sum(100.0 / (1 + i) ** t for t in range(1, 26)) - repl
    assert npv == pytest.approx(manual, rel=1e-12)


def test_replacement_count_and_edges():
    from vfed.design.sweep import _battery_replacement_pv

    # life 8 yr over a 25-yr horizon → ceil(25/8)-1 = 3 units at years 8/16/24
    assert _battery_replacement_pv(100.0, 8.0, 25.0, 0.0) == pytest.approx(300.0)
    # battery outlives the horizon / absent / zero capital / never cycles
    assert _battery_replacement_pv(100.0, 25.0, 25.0, 0.06) == 0.0
    assert _battery_replacement_pv(100.0, None, 25.0, 0.06) == 0.0
    assert _battery_replacement_pv(0.0, 5.0, 25.0, 0.06) == 0.0
    assert _battery_replacement_pv(100.0, float("inf"), 25.0, 0.06) == 0.0


def test_npv_nan_on_degenerate_rate():
    from vfed.design.sweep import _incremental_npv

    assert math.isnan(_incremental_npv(1000.0, 100.0, -1.0, 25.0, 0.0))


# ---------------------------------------------------------------------------
# 8.2  IRR (bisection)
# ---------------------------------------------------------------------------
def test_irr_solves_npv_zero():
    from vfed.design.sweep import _annuity_factor, _incremental_irr

    capital, savings, years = 100000.0, 12000.0, 25.0
    irr = _incremental_irr(capital, savings, years, 0.0, None)
    assert math.isfinite(irr)
    # NPV at the reported root must vanish (bisection converged)
    assert -capital + savings * _annuity_factor(irr, years) == pytest.approx(0.0, abs=1e-6)
    # and bracket: NPV flips sign across the root
    assert -capital + savings * _annuity_factor(irr - 0.01, years) > 0.0
    assert -capital + savings * _annuity_factor(irr + 0.01, years) < 0.0


def test_irr_user4_style_with_replacement():
    """user4 audit scenario: ΔCapital 142,093, ΔSavings 26,359/yr, 40 kWh
    battery at 236 cycles/yr → life ≈ 16.95 yr → one replacement."""
    from vfed.design.sweep import _annuity_factor, _incremental_irr

    capital, savings = 142093.0, 26359.0
    battery_capital, life = 40.0 * 220.0, 4000.0 / 236.0
    irr = _incremental_irr(capital, savings, 25.0, battery_capital, life)
    assert math.isfinite(irr)
    assert 0.10 < irr < 0.30  # user4's hand estimate was ≈ 18 %
    # residual NPV at the root ~ 0 (incl. the discounted replacement)
    residual = (
        -capital + savings * _annuity_factor(irr, 25.0) - battery_capital * (1 + irr) ** (-life)
    )
    assert residual == pytest.approx(0.0, abs=1e-6)


def test_irr_nan_when_no_payback():
    from vfed.design.sweep import _incremental_irr

    assert math.isnan(_incremental_irr(1000.0, 0.0, 25.0, 0.0, None))
    assert math.isnan(_incremental_irr(1000.0, -10.0, 25.0, 0.0, None))
    assert math.isnan(_incremental_irr(0.0, 100.0, 25.0, 0.0, None))


def test_irr_negative_when_below_hurdle():
    from vfed.design.sweep import _incremental_irr

    # S*25 << C → a (negative) root exists between -0.99 and 0
    irr = _incremental_irr(1000.0, 1.0, 25.0, 0.0, None)
    assert math.isfinite(irr)
    assert irr < 0.0


# ---------------------------------------------------------------------------
# 8.3  sweep results.csv investment columns
# ---------------------------------------------------------------------------
_INVESTMENT_COLS = (
    "grid_independence_pct",
    "pv_self_consumption_rate",
    "annual_savings",
    "payback_period",
    "delta_capital",
    "delta_annual_savings",
    "npv_25yr",
    "irr_pct",
)


def _sweep_project_609(project_609):
    d = project_609.to_dict()
    d["space"]["parameter_ranges"] = {"pv_area": [0, 100, 100], "battery": [0, 40, 40]}
    return DesignProject.from_dict(d)


def test_sweep_results_has_investment_columns(project_609):
    from vfed.design.sweep import sweep_design

    res = sweep_design(_sweep_project_609(project_609))
    df = res["results"]
    for col in _INVESTMENT_COLS:
        assert col in df.columns, col


def test_sweep_zero_row_semantics(project_609):
    """The [0,0] row IS the baseline: zero delta, zero savings, payback inf."""
    from vfed.design.sweep import sweep_design

    res = sweep_design(_sweep_project_609(project_609))
    zero = res["results"][(res["results"]["pv_area"] == 0) & (res["results"]["battery_kwh"] == 0)]
    assert len(zero) == 1
    z = zero.iloc[0]
    assert z["grid_independence_pct"] == 0.0
    assert z["pv_self_consumption_rate"] == 0.0
    assert z["annual_savings"] == pytest.approx(0.0, abs=1e-9)
    assert math.isinf(z["payback_period"])
    assert z["delta_capital"] == pytest.approx(0.0, abs=1e-9)
    assert z["delta_annual_savings"] == pytest.approx(0.0, abs=1e-9)
    assert z["npv_25yr"] == pytest.approx(0.0, abs=1e-9)
    assert math.isnan(z["irr_pct"])  # fail-fast: NaN, never a silent 0


def test_sweep_pv_row_invariants(project_609):
    from vfed.design.sweep import sweep_design

    p = _sweep_project_609(project_609)
    res = sweep_design(p)
    df = res["results"]
    row = df[(df["pv_area"] == 100) & (df["battery_kwh"] == 0)].iloc[0]
    assert 0.0 < row["pv_self_consumption_rate"] <= 1.0
    assert 0.0 < row["grid_independence_pct"] <= 100.0
    assert row["annual_savings"] > 0.0
    assert math.isfinite(row["payback_period"]) and row["payback_period"] > 0
    # delta capital = PV + battery capital (the other components cancel vs baseline)
    assert row["delta_capital"] == pytest.approx(row["capital_pv"] + row["capital_battery"])
    # F1 (round 21): incremental payback identity -- payback x annual_savings
    # == delta capital, so the column is recomputable from the CSV itself
    # (preset 609 has no capital blocks -> legacy C_pv fallback pricing, so
    # delta_capital == capital_pv + capital_battery == the payback numerator).
    assert row["payback_period"] == pytest.approx(
        row["delta_capital"] / row["annual_savings"], rel=1e-12
    )
    assert row["payback_period"] * row["annual_savings"] == pytest.approx(
        row["delta_capital"], rel=1e-9
    )
    # corrected delta savings = legacy bill savings - O&M on the delta capital
    assert row["delta_annual_savings"] == pytest.approx(
        row["annual_savings"] - p.opex.maintenance_pct * row["delta_capital"], rel=1e-9
    )
    assert math.isfinite(row["npv_25yr"])
    assert math.isfinite(row["irr_pct"]) and row["irr_pct"] > 0.0


def test_single_point_row_has_investment_columns(project_609):
    from vfed.design.sweep import sweep_design

    d = project_609.to_dict()
    d["pv_area_m2"] = 50.0
    d["battery_kwh"] = 0.0
    d["space"]["parameter_ranges"] = {}
    res = sweep_design(DesignProject.from_dict(d))
    best = res["best"]
    for col in _INVESTMENT_COLS:
        assert col in best, col
    assert best["delta_capital"] > 0.0
    assert math.isfinite(best["payback_period"])
    # F1 (round 21): same incremental identity on the single-point row
    assert best["payback_period"] == pytest.approx(
        best["delta_capital"] / best["annual_savings"], rel=1e-12
    )
    # grid-only single point: baseline == config → zero-delta semantics
    d2 = project_609.to_dict()
    d2["space"]["parameter_ranges"] = {}
    res2 = sweep_design(DesignProject.from_dict(d2))
    b2 = res2["best"]
    assert b2["annual_savings"] == pytest.approx(0.0, abs=1e-9)
    assert math.isinf(b2["payback_period"])
    assert math.isnan(b2["irr_pct"])


def test_single_point_payback_user13_econ_scenario(project_609):
    """user13 audit repro (round 21 F1): PV 100 m2 (23.2558 kWp) priced
    per_kwp 3500 + battery 40 kWh priced per_kwh 500 -- the same sizing and
    rates as ``user-gym/user13/u13_econ.yaml`` (annual load 62,444.5,
    baseline grid bill 6,244.45).

    The audit's FAIL item: the exported ``payback_period`` (6.4914 yr) used
    the legacy hidden unit prices C_pv=500/kWp + c_energy=220/kWh
    (capital 20,427.907) and matched no documented formula.  Under the F1
    definition it becomes delta_capital / annual_savings = 101,395.349 /
    3,146.920 = 32.2205 yr -- recomputable from the row's own columns."""
    from vfed.design.presets import preset_609
    from vfed.design.sweep import sweep_design

    # fresh preset: the session-scoped project_609 fixture carries auto-sized
    # HVAC/DEH nameplates written back by earlier engine runs (same pattern
    # as test_09's column-set pin).
    d = preset_609().to_dict()
    d["pv"]["capital"] = {"mode": "per_kwp", "rate_per_kwp": 3500}
    d["battery"]["capital"] = {"mode": "per_kwh", "rate_per_kwh": 500}
    d["pv_area_m2"] = 100.0
    d["battery_kwh"] = 40.0
    d["space"]["parameter_ranges"] = {}
    best = sweep_design(DesignProject.from_dict(d))["best"]

    # user13's delta_capital: 3500 x (100/4.3) + 500 x 40 = 101,395.3488...
    assert best["delta_capital"] == pytest.approx(3500.0 * 100.0 / 4.3 + 500.0 * 40.0, rel=1e-9)
    # same savings regime as the audit (3,146.92 currency/yr)
    assert best["annual_savings"] == pytest.approx(3146.92, abs=0.02)
    # F1 identity: payback x annual_savings == delta capital
    assert best["payback_period"] == pytest.approx(
        best["delta_capital"] / best["annual_savings"], rel=1e-12
    )
    # the audited value under the corrected definition (user13 hand-check:
    # 101,395.3488 / 3,146.9201 = 32.2205), NOT the legacy 6.4914
    assert best["payback_period"] == pytest.approx(32.2205, abs=5e-3)
    assert not math.isclose(best["payback_period"], 6.4914, abs_tol=0.5)


# ---------------------------------------------------------------------------
# 8.4  battery.allow_grid_charging — config contract
# ---------------------------------------------------------------------------
def test_allow_grid_charging_default_false(project_609):
    d = project_609.to_dict()
    assert DesignProject.from_dict(d).battery.allow_grid_charging is False
    # presets never set it explicitly → default survives
    from vfed.design.presets import preset_609

    assert preset_609().battery.allow_grid_charging is False


def test_allow_grid_charging_yaml_true():
    d = {"name": "x", "battery": {"allow_grid_charging": True}}
    assert DesignProject.from_dict(d).battery.allow_grid_charging is True


@pytest.mark.parametrize("bad", ["true", "True", "yes", 1, 0])
def test_allow_grid_charging_fail_fast(bad):
    d = {"name": "x", "battery": {"allow_grid_charging": bad}}
    with pytest.raises(ValueError, match="allow_grid_charging"):
        DesignProject.from_dict(d)


# ---------------------------------------------------------------------------
# 8.5  dispatch: default bitwise-invariance + TOU grid charging
# ---------------------------------------------------------------------------
_TOU = [0.30] * 8 + [0.70] * 8 + [1.00] * 8  # valley 0-7, peak 18-21


def _rng_case(n=240):
    rng = np.random.default_rng(7)
    load = rng.uniform(0.0, 10.0, n)
    pv = np.clip(rng.uniform(-2.0, 8.0, n), 0.0, None)
    hours = np.arange(n) % 24
    return pv - load, load, pv, hours


def test_default_dispatch_bitwise_unchanged_with_prices():
    """allow_grid_charging=False must ignore prices/hours entirely."""
    pb, load, _pv, hours = _rng_case()
    a = BatterySystem().calculate_battery_flows(pb, load, 12.0, hourly_prices=_TOU, hours=hours)
    b = BatterySystem().calculate_battery_flows(pb, load, 12.0)
    for key, val in a.items():
        if isinstance(val, np.ndarray):
            assert np.array_equal(val, b[key]), key
        else:
            assert val == b[key], key


def test_grid_charging_valley_only_and_profitable():
    """PV=0, load only at peak: valley top-up must cut the electricity bill."""
    hours = np.arange(48) % 24
    load = np.where(np.isin(hours, [18, 19, 20, 21]), 5.0, 0.0)
    pv = np.zeros_like(load)
    on = BatterySystem(allow_grid_charging=True).calculate_battery_flows(
        pv - load, load, 10.0, hourly_prices=_TOU, hours=hours
    )
    off = BatterySystem().calculate_battery_flows(pv - load, load, 10.0)
    # charging happened, and only in valley hours
    assert on["grid_charged"].sum() > 0.0
    gc_hours = set(hours[on["grid_charged"] > 0].tolist())
    assert gc_hours and gc_hours.issubset(set(range(8)))
    # more energy cycled through the battery
    assert on["total_discharged"] > off["total_discharged"]
    assert on["battery_cycles"] > off["battery_cycles"]
    # and the arbitrage is profitable at the tariff
    # (grid_import = max(0, load - pv - dch) + grid_charged; pv = 0 here)
    tariff = Tariff(hourly_prices=list(_TOU))
    cost_on = tariff.annual_cost(
        load - on["battery_discharge"] + on["grid_charged"], np.zeros(48), hours
    )["net_grid_cost"]
    cost_off = tariff.annual_cost(load - off["battery_discharge"], np.zeros(48), hours)[
        "net_grid_cost"
    ]
    assert cost_on < cost_off


def test_grid_charging_flat_tariff_noop():
    pb, load, _pv, hours = _rng_case()
    on = BatterySystem(allow_grid_charging=True).calculate_battery_flows(
        pb, load, 10.0, hourly_prices=[0.5] * 24, hours=hours
    )
    off = BatterySystem().calculate_battery_flows(pb, load, 10.0)
    assert on["grid_charged"].sum() == 0.0
    assert np.array_equal(on["battery_charge"], off["battery_charge"])
    assert np.array_equal(on["battery_discharge"], off["battery_discharge"])
    assert on["total_charged"] == off["total_charged"]


def test_grid_charging_requires_prices():
    pb, load, _pv, _hours = _rng_case(24)
    with pytest.raises(ValueError, match="hourly_prices"):
        BatterySystem(allow_grid_charging=True).calculate_battery_flows(pb, load, 10.0)


def test_energy_system_grid_charging_balance_and_export():
    """Grid-charged power lands in grid_import; export stays PV-only; the
    annual balance (pv + import + discharge = load + charge + export) closes."""
    # valley at midday so PV surplus and grid charging co-occur
    prices = [0.70] * 10 + [0.30] * 4 + [0.70] * 10  # valley h10-13
    hours = np.arange(48) % 24
    weather = {
        "hour": hours,
        "direct_radiation": np.where((hours >= 8) & (hours < 17), 800.0, 0.0),
        "diffuse_radiation": np.zeros(48),
        "temperature_2m": np.full(48, 20.0),
    }
    load = np.where(np.isin(hours, [18, 19, 20, 21]), 5.0, 1.0)
    es = EnergySystem(
        battery=BatterySystem(allow_grid_charging=True, c_rate=1.0),
        tariff=Tariff(hourly_prices=prices),
    )
    perf = es.simulate_performance([10.0, 2.0], weather, load)
    pv = perf["pv_power"]
    assert pv.sum() > 0.0
    # recompute the flows to recover the per-timestep grid_charged array
    flows = BatterySystem(allow_grid_charging=True, c_rate=1.0).calculate_battery_flows(
        pv - load, load, 2.0, hourly_prices=prices, hours=hours
    )
    g = flows["grid_charged"]
    assert g.sum() > 0.0
    lhs = pv.sum() + perf["grid_import"].sum() + perf["battery_discharge"].sum()
    rhs = load.sum() + perf["battery_charge"].sum() + perf["grid_export"].sum()
    assert lhs == pytest.approx(rhs, abs=1e-6)
    assert perf["grid_import"].sum() > 0.0
    # a valley surplus hour: export must net out ONLY the PV-side charge
    for i in range(48):
        if hours[i] in (10, 11, 12, 13) and pv[i] > 0:
            assert perf["grid_export"][i] == pytest.approx(
                max(0.0, pv[i] - (perf["battery_charge"][i] - g[i]) - load[i]), abs=1e-9
            )


def test_engine_passes_allow_grid_charging(project_609, monkeypatch):
    import vfed.pvbes.battery as bat_mod
    from vfed.design.engine import DesignEngine

    captured = {}
    orig_init = bat_mod.BatterySystem.__init__

    def spy_init(self, *args, **kwargs):
        captured.update(kwargs)
        orig_init(self, *args, **kwargs)

    monkeypatch.setattr(bat_mod.BatterySystem, "__init__", spy_init)
    d = project_609.to_dict()
    d["battery"]["allow_grid_charging"] = True
    d["pv_area_m2"] = 50.0
    p2 = DesignProject.from_dict(d)
    DesignEngine(cache_dir="weather_cache").run(p2)
    assert captured.get("allow_grid_charging") is True
